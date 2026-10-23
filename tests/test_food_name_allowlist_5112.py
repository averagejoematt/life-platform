"""tests/test_food_name_allowlist_5112.py — public meal endpoints show owner-approved food names only (#5112).

Owner ruling R5 (2026-10-23): `/api/frequent_meals` and `/api/protein_sources` stay public, approved
names only. `/api/meal_glucose` publishes the same MacroFactor names, so it is held to the same rule.
The list (`privacy.food_names.APPROVED_FOOD_NAMES`) ships EMPTY: fail closed.

What this holds:
  1. On the SHIPPED list, a food name that is not on it reaches none of the three payloads, and the
     payload says how many names it held back.
  2. With a name approved, exactly that name (case/whitespace-insensitive) is published — never a
     longer name that merely starts with it.
  3. Hiding a name never changes a number that is not keyed by name.
  4. Every handler in `web/site_api_meals.py` that reads `food_name` routes it through
     `food_names.approved` — derived from the module's AST, so a fourth name-publishing handler
     cannot ship ungated.
"""

import ast
import inspect
import json
import os
import sys
from datetime import datetime

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))

from privacy import food_names  # noqa: E402
from web import (
    site_api_common as sac,  # noqa: E402
    site_api_meals as meals,  # noqa: E402
)

SECRET = "Zz Corner Taqueria Burrito 5112"  # a name that is never on the approved list
APPROVED = "Eggs"
_NOW = datetime(2026, 4, 20, 12, 0, tzinfo=sac.PT)


class _Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        return _NOW if tz is None else _NOW.astimezone(tz)


@pytest.fixture(autouse=True)
def _frozen(monkeypatch):
    monkeypatch.setattr(meals, "datetime", _Frozen)
    monkeypatch.setattr(sac, "datetime", _Frozen)
    monkeypatch.setattr(sac, "EXPERIMENT_START", "2026-01-01")
    sac.set_request_id(None)
    yield
    sac.set_request_id(None)


def _food(name, **kw):
    return {"food_name": name, "protein_g": 30, "calories_kcal": 400, "carbs_g": 40, "fat_g": 10, "time": "12:30", **kw}


def _g(names):
    day = {"sk": "DATE#2026-04-15", "food_log": [_food(n) for n in names]}
    cgm = {"sk": "DATE#2026-04-15", "blood_glucose_avg": 100, "blood_glucose_max": 140, "blood_glucose_min": 80}

    def _query_source(source, start, end):
        return {"macrofactor": [day], "apple_health": [cgm]}.get(source, [])

    return {"_query_source": _query_source, "_experiment_date": sac._experiment_date}


def _body(fn, names):
    resp = fn(_g=_g(names))
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


_ENDPOINTS = {
    "protein_sources": (meals.protein_sources, "protein_sources", "food"),
    "frequent_meals": (meals.frequent_meals, "meals", "name"),
    "meal_glucose": (meals.meal_glucose, "meals", "meal"),
}


def test_the_shipped_list_publishes_no_unapproved_name_on_any_endpoint():
    """Fail closed: on the list as shipped, the sentinel never reaches a payload, anywhere in it."""
    offenders = []
    for label, (fn, rows_key, _name_key) in _ENDPOINTS.items():
        body = _body(fn, [SECRET, SECRET])
        if SECRET.casefold() in json.dumps(body).casefold():
            offenders.append(f"{label}: the unapproved name is in the payload")
        if body[rows_key]:
            offenders.append(f"{label}: {len(body[rows_key])} row(s) published for an unapproved name")
        if body.get("names_withheld") != 1:
            offenders.append(f"{label}: names_withheld={body.get('names_withheld')!r}, expected 1")
    assert not offenders, offenders


def test_an_approved_name_is_published_and_a_longer_name_that_starts_with_it_is_not(monkeypatch):
    monkeypatch.setattr(food_names, "APPROVED_FOOD_NAMES", frozenset({APPROVED}))
    offenders = []
    for label, (fn, rows_key, name_key) in _ENDPOINTS.items():
        body = _body(fn, ["  eggs ", "Eggs (Corner Taqueria)", SECRET])
        names = [r[name_key] for r in body[rows_key]]
        if [n.strip().casefold() for n in names] != ["eggs"]:
            offenders.append(f"{label}: published {names!r}")
        if "taqueria" in json.dumps(body).casefold():
            offenders.append(f"{label}: a non-exact name leaked")
        if body.get("names_withheld") != 2:
            offenders.append(f"{label}: names_withheld={body.get('names_withheld')!r}, expected 2")
    assert not offenders, offenders


def test_withholding_a_name_never_changes_a_number_not_keyed_by_name(monkeypatch):
    """protein per day and days analysed count every logged entry, approved or not."""
    shown = _body(meals.protein_sources, [SECRET, APPROVED])
    monkeypatch.setattr(food_names, "APPROVED_FOOD_NAMES", frozenset({APPROVED, SECRET}))
    everything = _body(meals.protein_sources, [SECRET, APPROVED])
    assert shown["total_protein_avg_g"] == everything["total_protein_avg_g"] == 60.0
    assert shown["days_analyzed"] == everything["days_analyzed"] == 1


def test_matching_forgives_case_and_whitespace_only(monkeypatch):
    monkeypatch.setattr(food_names, "APPROVED_FOOD_NAMES", frozenset({"Greek  Yogurt"}))
    assert food_names.approved("greek yogurt")
    assert food_names.approved(" GREEK\tYOGURT ")
    assert not food_names.approved("Greek Yogurt Bowl")
    assert not food_names.approved("Greek")
    assert not food_names.approved("")
    assert not food_names.approved(None)


def test_the_shipped_list_is_a_frozenset_of_names():
    assert isinstance(food_names.APPROVED_FOOD_NAMES, frozenset)
    assert all(isinstance(n, str) and n.strip() for n in food_names.APPROVED_FOOD_NAMES)


def test_every_handler_that_reads_food_name_routes_it_through_the_allowlist():
    """Derived SET: every function in site_api_meals whose body contains the "food_name" key also
    calls `food_names.approved`. Non-vacuous: the set must hold the three known publishers."""
    tree = ast.parse(inspect.getsource(meals))
    readers, ungated = [], []
    for fn in tree.body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        consts = {n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        if "food_name" not in consts:
            continue
        readers.append(fn.name)
        calls = {
            (n.func.value.id, n.func.attr)
            for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
        }
        if ("food_names", "approved") not in calls:
            ungated.append(fn.name)
    assert {"protein_sources", "frequent_meals", "meal_glucose"} <= set(readers), readers
    assert not ungated, f"reads food_name without the #5112 allowlist: {ungated}"
