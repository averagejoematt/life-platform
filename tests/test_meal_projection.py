"""Tests for the meal projection writer.

The load-bearing guard (Omar/Jin): the writer must NEVER touch the raw
SOURCE#macrofactor partition — only SOURCE#macrofactor_meals. Plus idempotency:
re-running a day doesn't duplicate, and a smaller re-grouping prunes stale ordinals.
No AWS — a fake table records every write/delete/query.
"""

import json
import os

import meal_projection as mp  # conftest puts lambdas/ on sys.path
import pytest
from fakes import FakeDdbTable

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "food_log_2026-06-15_18.json")
USER = "matthew"
RAW_PK = f"USER#{USER}#SOURCE#macrofactor"
MEALS_PK = f"USER#{USER}#SOURCE#macrofactor_meals"


def FakeTable():
    """FakeDdbTable configured to answer begins_with queries the way this
    writer needs: put_item/delete_item use the shared (pk, sk)-keyed store
    (.puts/.deletes log every call) unmodified; only query() is bespoke.

    Only used for _existing_meal_sks: pk == MEALS_PK, sk begins_with
    DATE#<date>#MEAL#. Emulate by returning stored meal sks for the queried
    pk/date prefix. Deriving the prefix from the KeyConditionExpression is
    awkward; instead match all meal-partition rows (the writer only ever
    queries the meals pk for one date)."""

    def _query_hook(table, **_kwargs):
        items = [{"sk": sk} for (pk, sk) in table.store if pk == MEALS_PK]
        return {"Items": items}

    return FakeDdbTable(query_hook=_query_hook)


@pytest.fixture(scope="module")
def days():
    with open(FIXTURE) as fh:
        return json.load(fh)


def _groups(days, date):
    from meal_grouper import group_day

    return group_day(days[date]["food_log"])


# ── no-write-to-raw: every write/delete targets ONLY the meals partition ──────
def test_never_writes_raw_partition(days):
    t = FakeTable()
    for date in days:
        mp.write_day_projection(t, date, _groups(days, date), user=USER, now_iso="2026-06-19T00:00:00Z")
    assert t.puts, "expected writes"
    for item in t.puts:
        assert item["pk"] == MEALS_PK
        assert item["pk"] != RAW_PK
        assert item["sk"].startswith("DATE#")
        assert "#MEAL#" in item["sk"]
    for key in t.deletes:
        assert key["pk"] == MEALS_PK and key["pk"] != RAW_PK


# ── stamping: algo_version, signature, rollup, ordinal present ────────────────
def test_items_stamped(days):
    items = mp.build_meal_items("2026-06-18", _groups(days, "2026-06-18"), user=USER, now_iso="2026-06-19T00:00:00Z")
    assert items
    for i, it in enumerate(items, 1):
        assert it["ordinal"] == i
        assert it["sk"] == f"DATE#2026-06-18#MEAL#{i:02d}"
        assert it["algo_version"].startswith("meal-grouper@")
        assert it["signature"]
        assert set(it["rollup"]).issuperset({"calories_kcal", "protein_g"})
        assert it["inferred"] is True


# ── idempotency: re-running a day overwrites the same sks, no duplicates ───────
def test_idempotent_rewrite(days):
    t = FakeTable()
    g = _groups(days, "2026-06-16")
    mp.write_day_projection(t, "2026-06-16", g, user=USER, now_iso="2026-06-19T00:00:00Z")
    n_after_first = len([k for k in t.store if k[0] == MEALS_PK])
    mp.write_day_projection(t, "2026-06-16", g, user=USER, now_iso="2026-06-19T01:00:00Z")
    n_after_second = len([k for k in t.store if k[0] == MEALS_PK])
    assert n_after_first == n_after_second, "re-run must not duplicate rows"


# ── pruning: a smaller re-grouping deletes stale higher ordinals ──────────────
def test_prunes_stale_ordinals():
    t = FakeTable()
    # seed a day with 4 meals
    big = [
        {
            "meal_name": f"M{i}",
            "kind": "meal",
            "method": "template",
            "confidence": 1.0,
            "signature": f"sig{i}",
            "time_window": {"start": f"1{i}:00", "end": f"1{i}:00"},
            "member_refs": [],
            "sides": [],
            "rollup": {"calories_kcal": 100.0, "protein_g": 10.0},
        }
        for i in range(4)
    ]
    mp.write_day_projection(t, "2026-06-20", big, user=USER, now_iso="2026-06-19T00:00:00Z")
    assert len([k for k in t.store if k[0] == MEALS_PK]) == 4
    # re-group the same day into just 2 meals → ordinals 03/04 must be pruned
    small = big[:2]
    res = mp.write_day_projection(t, "2026-06-20", small, user=USER, now_iso="2026-06-19T02:00:00Z")
    remaining = sorted(sk for (pk, sk) in t.store if pk == MEALS_PK)
    assert remaining == ["DATE#2026-06-20#MEAL#01", "DATE#2026-06-20#MEAL#02"]
    assert res["stale_pruned"] == 2 and res["deleted"] == 2


# ── dry-run writes nothing ────────────────────────────────────────────────────
def test_dry_run_writes_nothing(days):
    t = FakeTable()
    res = mp.write_day_projection(t, "2026-06-15", _groups(days, "2026-06-15"), user=USER, dry_run=True)
    assert res["dry_run"] and res["wrote"] == 0
    assert not t.puts and not t.deletes
    assert res["meals"] > 0  # but it computed the items for preview
