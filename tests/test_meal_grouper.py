"""Tests for the deterministic meal grouper (Phase 1).

Asserts the four invariants and the named-fixture splits from
SPEC_MEAL_GROUPING §13 / the build prompt. No AWS, no MCP, no model calls —
pure logic over the 4 real fixture days + a synthetic anchor-set case.
"""

import copy
import json
import os

import pytest

import meal_grouper as mg  # conftest puts lambdas/ on sys.path

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "food_log_2026-06-15_18.json")


@pytest.fixture(scope="module")
def days():
    with open(FIXTURE) as fh:
        return json.load(fh)


def _entries(days, date):
    return days[date]["food_log"]


def _names(groups):
    return [g["meal_name"] for g in groups]


def _meals(groups):
    """Named meals only (kind == 'meal'), in time order."""
    meals = [g for g in groups if g["kind"] == "meal"]
    return sorted(meals, key=lambda g: g["time_window"]["start"] or "")


def _find(groups, template_id):
    return [g for g in groups if g.get("template_id") == template_id]


# ── conservation: every fixture day reconciles to the cent ────────────────────
@pytest.mark.parametrize("date", ["2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18"])
def test_conservation_each_day(days, date):
    entries = _entries(days, date)
    groups = mg.group_day(entries)
    # sum(rollups) == sum(raw entries), field by field
    raw = {f: 0.0 for f in mg.MACRO_FIELDS}
    for e in entries:
        for f in mg.MACRO_FIELDS:
            raw[f] += mg._num(e.get(f))
    summed = {f: 0.0 for f in mg.MACRO_FIELDS}
    for g in groups:
        for f in mg.MACRO_FIELDS:
            summed[f] += g["rollup"][f]
    for f in mg.MACRO_FIELDS:
        assert summed[f] == pytest.approx(raw[f], abs=0.01), f"{date} {f}: {summed[f]} != {raw[f]}"


def test_every_entry_assigned_exactly_once(days):
    for date in days:
        entries = _entries(days, date)
        groups = mg.group_day(entries)
        idxs = [ref["idx"] for g in groups for ref in (g["member_refs"] + g["sides"])]
        assert sorted(idxs) == list(range(len(entries))), f"{date}: every entry once"


# ── 06-18 19:46 collision blob splits three ways (2 meals + 1 uncategorized) ──
def test_0618_blob_splits_into_three(days):
    groups = mg.group_day(_entries(days, "2026-06-18"))
    # the 19:46 blob splits into THREE groups — the split is preserved
    at1946 = [g for g in groups if g["time_window"]["start"] == "19:46"]
    assert len(at1946) == 3, f"expected 3 groups at 19:46, got {_names(at1946)}"

    # two are named meals
    meals = [g for g in at1946 if g["kind"] == "meal"]
    assert {g["meal_name"] for g in meals} == {"Turkey Tacos", "Protein Yogurt Dessert"}

    # the bare grilled-chicken + Chicken Dippin' group now lands UNCATEGORIZED
    # (coverage-confidence < 0.7 because the unseeded nuggets aren't explained)
    uncat = [g for g in at1946 if g["kind"] == "uncategorized"]
    assert len(uncat) == 1, f"expected 1 uncategorized group, got {_names(uncat)}"
    chicken = uncat[0]
    ctok = {r["token"] for r in chicken["member_refs"]} | {s["token"] for s in chicken["sides"]}
    assert "chicken_breast" in ctok
    assert "chicken_nuggets" in ctok  # Chicken Dippin' attaches as a side, no phantom meal
    assert chicken["confidence"] < mg.CONF_MIN
    assert chicken["meal_name"] != "Mixed meal"

    # tacos absorbed the taco scaffolding; dessert absorbed the sweets
    tacos = _find(groups, "tpl_turkey_tacos")[0]
    assert {"tortilla", "taco_shell"} <= {r["token"] for r in tacos["member_refs"]}
    dessert = _find(groups, "tpl_protein_yogurt_dessert")[0]
    assert {"cool_whip", "cherry_gels"} <= {r["token"] for r in dessert["member_refs"]}


# ── 06-16 lunch: tuna+mayo dominates a minor eggs anchor → uncategorized; snacks peel ──
def test_0616_tuna_lunch_uncategorized_and_snacks_peeled(days):
    groups = mg.group_day(_entries(days, "2026-06-16"))
    at1234 = [g for g in groups if g["time_window"]["start"] == "12:34"]

    # the lunch group (eggs + mayo + tuna) is uncategorized, NOT "Scrambled Eggs"
    lunch = [
        g for g in at1234 if any(r["token"] in ("eggs", "tuna") for r in g["member_refs"]) or any(s["token"] == "tuna" for s in g["sides"])
    ]
    assert lunch, "expected a lunch group at 12:34"
    assert all(g["kind"] == "uncategorized" for g in lunch)
    assert all(g["meal_name"] != "Scrambled Eggs" for g in lunch)

    # IQ bar + smoothie peel OUT into a standalone snack, not folded into lunch
    snack = [g for g in at1234 if g["kind"] == "snack"]
    assert snack, "IQ bar + smoothie should peel out as a snack"
    snack_tokens = {r["token"] for g in snack for r in g["member_refs"]}
    assert {"smoothie", "protein_bar"} <= snack_tokens
    lunch_tokens = {r["token"] for g in lunch for r in g["member_refs"]}
    assert "smoothie" not in lunch_tokens and "protein_bar" not in lunch_tokens


# ── 06-16 splits tacos / dessert on the time gap ──────────────────────────────
def test_0616_gap_split_tacos_dessert(days):
    groups = mg.group_day(_entries(days, "2026-06-16"))
    tacos = _find(groups, "tpl_turkey_tacos")
    dessert = _find(groups, "tpl_protein_yogurt_dessert")
    assert tacos, "Turkey Tacos at 19:03"
    assert dessert, "Protein Yogurt Dessert at 19:29"
    # they are distinct groups split on the >15-min gap (19:03 vs 19:29)
    assert tacos[0]["time_window"]["start"] == "19:03"
    assert dessert[0]["time_window"]["start"] == "19:29"
    assert tacos[0]["signature"] != dessert[0]["signature"]


# ── 06-15 → Yogurt Bowl + Katsu Curry; snacks bucketed ────────────────────────
def test_0615_yogurt_and_katsu(days):
    groups = mg.group_day(_entries(days, "2026-06-15"))
    assert _find(groups, "tpl_yogurt_oats_bowl"), "12:24 yogurt bowl"
    assert _find(groups, "tpl_chicken_katsu_curry"), "19:22 katsu (panko+curry beats plain plate)"
    # the 11:00 smoothie and 16:28 peanut-butter chip are snacks, not meals
    snacks = [g for g in groups if g["kind"] == "snack"]
    assert snacks, "snack singletons land in the snack bucket"
    snack_tokens = {r["token"] for g in snacks for r in g["member_refs"]}
    assert "smoothie" in snack_tokens


# ── determinism: identical input → byte-identical output ──────────────────────
def test_determinism(days):
    for date in days:
        entries = _entries(days, date)
        a = json.dumps(mg.group_day(entries), sort_keys=True)
        b = json.dumps(mg.group_day(copy.deepcopy(entries)), sort_keys=True)
        assert a == b, f"{date} not deterministic"


# ── no-mutation: grouper writes nothing back to the raw entries ───────────────
def test_no_mutation_of_raw(days):
    for date in days:
        entries = _entries(days, date)
        before = copy.deepcopy(entries)
        mg.group_day(entries)
        assert entries == before, f"{date}: raw food_log was mutated"


# ── multi-protein single meal does NOT wrongly split (anchor-SET) ─────────────
def test_chicken_salmon_anchor_set_single_meal():
    # one occasion, both proteins at the same time → ONE Chicken & Salmon Plate
    entries = [
        {"food_name": "Chicken Breast (grilled)", "time": "18:30", "calories_kcal": 300, "protein_g": 55, "carbs_g": 0, "fat_g": 7},
        {"food_name": "Salmon (baked)", "time": "18:30", "calories_kcal": 250, "protein_g": 30, "carbs_g": 0, "fat_g": 14},
        {"food_name": "Sweet Potato (baked)", "time": "18:32", "calories_kcal": 120, "protein_g": 2, "carbs_g": 28, "fat_g": 0},
    ]
    groups = mg.group_day(entries)
    meals = _meals(groups)
    assert len(meals) == 1, f"chicken+salmon must be ONE meal, got {_names(meals)}"
    assert meals[0]["template_id"] == "tpl_chicken_salmon_plate"
    assert meals[0]["meal_name"] == "Chicken & Salmon Plate"


# ── below-CONF_MIN clusters are uncategorized, not a junk 'Mixed meal' ─────────
def test_low_confidence_is_uncategorized_not_mixed():
    # a high-kcal anchorless novel cluster → uncategorized (never a junk "Mixed meal")
    entries = [
        {"food_name": "Mystery Restaurant Bowl", "time": "12:00", "calories_kcal": 650, "protein_g": 30, "carbs_g": 70, "fat_g": 25},
    ]
    groups = mg.group_day(entries)
    assert all(g["meal_name"] != "Mixed meal" for g in groups)
    assert any(g["kind"] == "uncategorized" for g in groups)
