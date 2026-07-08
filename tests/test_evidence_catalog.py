"""tests/test_evidence_catalog.py — catalog-restore behaviour for the Evidence pages.

After an experiment reset wipes the live partitions, the supplements / experiments /
challenges / habits pages must still render from their config catalogs, and the
habits list (now sourced from Habitify, which tracks vices too) must never leak a
blocked vice. These tests cover:

  * the content filter drops blocked habit names (porn/marijuana/…)
  * _habits_from_habitify maps + filters + carries the per-habit group
  * _experiment_catalog surfaces the library tagged origin='library' with a shelf status
"""

import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from fakes import FakeDdbTable  # noqa: E402
from web import (
    site_api_common as common,  # noqa: E402
    site_api_data as data,  # noqa: E402
)

_BLOCKLIST = {
    "blocked_vices": ["No porn", "No marijuana"],
    "blocked_vice_keywords": ["porn", "marijuana", "cannabis", "weed", "thc", "edible", "edibles"],
}


def _set_filter():
    common._content_filter_cache = dict(_BLOCKLIST)


# ── content filter on habit names ────────────────────────────────────────────


def test_blocked_vices_filtered_from_habit_names():
    _set_filter()
    assert common._is_blocked_vice("No marijuana") is True
    assert common._is_blocked_vice("No porn") is True
    assert common._is_blocked_vice("Cannabis gummies") is True
    assert common._is_blocked_vice("Morning sunlight") is False
    assert common._is_blocked_vice("Creatine 5g") is False


# ── habits sourced from Habitify ─────────────────────────────────────────────


def test_habits_from_habitify_filters_and_groups(monkeypatch):
    _set_filter()
    item = {
        "pk": "USER#matthew#SOURCE#habitify",
        "sk": "DATE#2026-06-14",
        "habit_statuses": {
            "Morning sunlight": {"group": "Wellbeing", "periodicity": "daily", "scheduled_today": True},
            "Creatine 5g": {"group": "Supplements", "periodicity": "daily"},
            "No marijuana": {"group": "Discipline", "periodicity": "daily"},
            "No porn": {"group": "Discipline", "periodicity": "daily"},
        },
    }
    monkeypatch.setattr(data, "table", FakeDdbTable(rows=[item]))
    habits = data._habits_from_habitify()
    names = {h["name"] for h in habits}
    assert names == {"Morning sunlight", "Creatine 5g"}, "blocked vices must not appear"
    by_name = {h["name"]: h for h in habits}
    assert by_name["Morning sunlight"]["group"] == "Wellbeing"
    assert by_name["Creatine 5g"]["frequency"] == "daily"


def test_habits_from_habitify_empty_when_no_record(monkeypatch):
    monkeypatch.setattr(data, "table", FakeDdbTable(rows=[]))
    assert data._habits_from_habitify() == []


# ── experiment library overlay ───────────────────────────────────────────────


def test_experiment_catalog_tags_origin_and_shelf(monkeypatch):
    lib = {
        "experiments": [
            {"id": "ex-a", "name": "Cold plunge", "status": "active", "hypothesis_template": "H1", "pillar": "Recovery"},
            {"id": "ex-b", "name": "Magnesium", "status": "backlog", "hypothesis_template": "H2", "pillar": "Sleep"},
            {"id": "ex-c", "name": "Already running", "status": "backlog"},
        ]
    }

    class _Body:
        def read(self):
            return io.BytesIO(json.dumps(lib).encode()).read()

    class _S3:
        def get_object(self, **_kw):
            return {"Body": _Body()}

    monkeypatch.setattr(data.boto3, "client", lambda *a, **k: _S3())
    out = data._experiment_catalog(exclude_ids={"ex-c"}, exclude_names=set())
    ids = {x["id"] for x in out}
    assert ids == {"ex-a", "ex-b"}, "running experiment (ex-c) must be excluded"
    shelves = {x["id"]: x["status"] for x in out}
    assert shelves["ex-a"] == "available" and shelves["ex-b"] == "backlog"
    assert all(x["origin"] == "library" for x in out)
