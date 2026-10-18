"""#5002 — a Whoop DATE# day row carries the cycle that STARTED on that UTC day, deduped on the cycle id.

The fixture is the wire: ``tests/fixtures/upstream/whoop/cycle_days_5002.json`` holds the two archived
framework envelopes ``{fetched_at, raw}`` for the UTC-day fetches of 2026-10-17 and 2026-10-18 (both
fetched 2026-10-18T16:00Z), verbatim except ``user_id`` -> 0. The shape that reproduced the bug:

  10-17 fetch  cycle 1881434574 (start 10-17T06:08Z, end null — still open) + cycle 1878873501
               (start 10-16T05:20Z, overlapping the window) + its recovery (62) and sleep
  10-18 fetch  ONLY cycle 1881434574 again — it overlaps 10-18's window because it is still open —
               and no recovery, no sleep. Before #5002 the writer took ``records[0]`` and filed it
               under DATE#2026-10-18: strain 10.82 / kilojoule 17068.35 / step_count 17904 /
               max HR 157 / avg HR 62, the 10-17 row copied field-for-field (DDB read 2026-10-18).

Mutation controls (run by hand, recorded in the PR):
  M1  ``cycle_for_day`` returning ``records[0]`` regardless of day  -> the start-day tests red
  M2  ``drop_cycle_filed_elsewhere`` a no-op (the cycle-id guard removed) -> the guard tests red
  M1 + M2 -> the 10-18 duplicate is written again under DATE#2026-10-18 (the regression test reds)
"""

from __future__ import annotations

import copy
import json
import os
import sys
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
for _k, _v in {
    "S3_BUCKET": "test-bucket",
    "TABLE_NAME": "life-platform",
    "USER_ID": "matthew",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_REGION": "us-west-2",
}.items():
    os.environ.setdefault(_k, _v)

from ingestion import whoop_cycle_day, whoop_lambda  # noqa: E402

_FIXTURE = os.path.join(ROOT, "tests", "fixtures", "upstream", "whoop", "cycle_days_5002.json")
_OPEN_CYCLE = 1881434574  # started 2026-10-17T06:08:38.930Z, still open at fetch
_PK = "USER#matthew#SOURCE#whoop"


class _FakeTable:
    """Returns the stored rows for any query; the callers filter by sk themselves."""

    def __init__(self, items=(), raises=None):
        self.items = list(items)
        self.raises = raises

    def query(self, **_kw):
        if self.raises:
            raise self.raises
        return {"Items": copy.deepcopy(self.items)}


def _raw(day: str) -> dict:
    with open(_FIXTURE) as fh:
        return json.load(fh)[day]["raw"]


def _day_rows(items: list) -> list:
    return [it for it in items if "workout_id" not in it]


def _transform(monkeypatch, day: str, raw: dict, stored=()) -> list:
    monkeypatch.setattr(whoop_lambda, "_table", _FakeTable(stored))
    return _day_rows(whoop_lambda.transform(raw, day))


# The 10-17 row as the fixed writer stores it (what sits under DATE#2026-10-17 once live).
_STORED_1017 = {"pk": _PK, "sk": "DATE#2026-10-17", "cycle_id": Decimal(_OPEN_CYCLE), "strain": Decimal("10.82")}


# ── the regression: the 10-18 fetch writes no copy of 10-17's cycle ─────────────────────────


def test_the_10_18_fetch_does_not_rewrite_the_10_17_cycle(monkeypatch):
    """The issue's specimen, with the fixed 10-17 row stored beside it: no DATE#2026-10-18 cycle fields."""
    rows = _transform(monkeypatch, "2026-10-18", _raw("2026-10-18"), stored=[_STORED_1017])
    assert rows == [], f"DATE#2026-10-18 must carry nothing copied from cycle {_OPEN_CYCLE}: {rows}"


def test_start_day_rule_alone_refuses_the_open_prior_cycle(monkeypatch):
    """Against a store holding no cycle ids (every row written before #5002), the start-day rule
    by itself keeps the 10-17 cycle off 10-18 — the guard is not what carries this."""
    rows = _transform(monkeypatch, "2026-10-18", _raw("2026-10-18"))
    assert rows == []
    assert whoop_cycle_day.cycle_for_day(_raw("2026-10-18")["cycle"]["records"], "2026-10-18", whoop_lambda._utc_day) is None


def test_the_10_17_fetch_files_its_own_cycle_with_its_identity(monkeypatch):
    rows = _transform(monkeypatch, "2026-10-17", _raw("2026-10-17"))
    assert len(rows) == 1
    r = rows[0]
    assert (r["date"], r["cycle_id"], r["cycle_start"]) == ("2026-10-17", _OPEN_CYCLE, "2026-10-17T06:08:38.930Z")
    assert "cycle_end" not in r, "the vendor sent end=null: an open cycle carries no end"
    assert (r["strain"], r["kilojoule"], r["step_count"]) == (Decimal("10.82"), Decimal("17068.35"), Decimal(17904))
    assert (r["max_heart_rate"], r["average_heart_rate"], r["recovery_score"]) == (Decimal(157), Decimal(62), Decimal(62))


def test_selection_is_by_start_day_not_by_record_order(monkeypatch):
    """Reversing the vendor's order (the 10-16 cycle first) still files the 10-17 cycle under 10-17."""
    raw = _raw("2026-10-17")
    raw["cycle"]["records"].reverse()
    (r,) = _transform(monkeypatch, "2026-10-17", raw)
    assert r["cycle_id"] == _OPEN_CYCLE and r["step_count"] == Decimal(17904)


def test_no_cycle_started_yet_is_an_honest_partial(monkeypatch):
    """10-17's recovery + sleep with only the overlapping 10-16 cycle returned: the row carries the
    recovery and sleep and NO cycle field — nothing borrowed from 10-16."""
    raw = _raw("2026-10-17")
    raw["cycle"]["records"] = [c for c in raw["cycle"]["records"] if c["id"] != _OPEN_CYCLE]
    (r,) = _transform(monkeypatch, "2026-10-17", raw)
    assert r["recovery_score"] == Decimal(62) and "sleep_start" in r
    assert not set(whoop_cycle_day.CYCLE_FIELDS) & set(r), r


# ── the cycle-id guard ───────────────────────────────────────────────────────────────────────


def _redated_1018() -> dict:
    """The 10-18 payload with the open cycle's start moved across 00:00Z onto 10-18 — the vendor
    re-dating a cycle — so the start-day rule alone WOULD file the same id on a second day."""
    raw = _raw("2026-10-18")
    raw["cycle"]["records"][0]["start"] = "2026-10-18T00:10:00.000Z"
    return raw


def test_guard_refuses_a_cycle_id_already_under_the_previous_day(monkeypatch):
    rows = _transform(monkeypatch, "2026-10-18", _redated_1018(), stored=[_STORED_1017])
    assert rows == [], f"cycle {_OPEN_CYCLE} already sits under DATE#2026-10-17: {rows}"


def test_guard_refuses_a_cycle_id_already_under_the_next_day(monkeypatch):
    raw = _raw("2026-10-17")
    stored = [{"pk": _PK, "sk": "DATE#2026-10-18", "cycle_id": Decimal(_OPEN_CYCLE)}]
    (r,) = _transform(monkeypatch, "2026-10-17", raw, stored=stored)
    assert not set(whoop_cycle_day.CYCLE_FIELDS) & set(r)
    assert r["recovery_score"] == Decimal(62), "only the cycle fields are refused — recovery/sleep stay"


def test_guard_ignores_its_own_row_workouts_and_other_ids(monkeypatch):
    stored = [
        {"pk": _PK, "sk": "DATE#2026-10-17", "cycle_id": Decimal(_OPEN_CYCLE)},  # its own day — a refresh
        {"pk": _PK, "sk": "DATE#2026-10-16#WORKOUT#x", "cycle_id": Decimal(_OPEN_CYCLE)},
        {"pk": _PK, "sk": "DATE#2026-10-16", "cycle_id": Decimal(1878873501)},
        {"pk": _PK, "sk": "DATE#2026-10-18"},  # a pre-#5002 row, no cycle id
    ]
    (r,) = _transform(monkeypatch, "2026-10-17", _raw("2026-10-17"), stored=stored)
    assert r["cycle_id"] == _OPEN_CYCLE


def test_guard_fails_open_on_a_read_error(monkeypatch):
    monkeypatch.setattr(whoop_lambda, "_table", _FakeTable(raises=RuntimeError("throttled")))
    normalized = whoop_lambda._extract_cycle(_redated_1018()["cycle"], "2026-10-18")
    whoop_cycle_day.drop_cycle_filed_elsewhere(whoop_lambda._table, "matthew", normalized, "2026-10-18", whoop_lambda.logger)
    assert normalized["cycle_id"] == _OPEN_CYCLE


# ── unchanged readers ────────────────────────────────────────────────────────────────────────


def test_extract_cycle_without_a_day_keeps_the_records0_reading():
    """Callers holding one payload with no day (the upstream-contract tests, the #4630 back-fill
    script) keep the pre-#5002 reading."""
    cyc = _raw("2026-10-17")["cycle"]
    assert whoop_lambda._extract_cycle(cyc)["cycle_id"] == cyc["records"][0]["id"]


def test_cycle_identity_stores_only_an_integer_id():
    bad = [b for b in (None, "1881434574", True) if "cycle_id" in whoop_cycle_day.cycle_identity({"id": b, "start": "x"})]
    assert not bad, f"a non-int vendor id became a cycle_id: {bad}"


# ── the read-only census of stored rows of the same shape ───────────────────────────────────


def test_census_counts_the_specimen_shape_and_nothing_else():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import whoop_daily_duplicates_5002 as census_mod

    cyc = {"kilojoule": Decimal("17068.35"), "strain": Decimal("10.82"), "average_heart_rate": Decimal(62), "max_heart_rate": Decimal(157)}
    rows = [
        {"sk": "DATE#2026-10-17", **cyc, "step_count": Decimal(17904), "recovery_score": Decimal(62)},
        {"sk": "DATE#2026-10-18", **cyc, "step_count": Decimal("17904.0")},  # the specimen: a copy, no recovery
        {"sk": "DATE#2026-10-18#WORKOUT#x", **cyc},  # a workout sub-row is never a day row
        {"sk": "DATE#2026-10-19", **cyc, "step_count": Decimal(17904), "recovery_score": Decimal(80)},  # reported apart
        {"sk": "DATE#2026-10-21", **cyc, "step_count": Decimal(17904)},  # 10-20 absent: no predecessor
        {"sk": "DATE#2026-10-22", **cyc, "step_count": Decimal(433)},  # one field differs
        {"sk": "DATE#2026-10-23", "recovery_score": Decimal(70)},
        {"sk": "DATE#2026-10-24"},  # two empty rows are not a copied cycle
    ]
    out = census_mod.census(rows)
    assert out["write_mode"] == "none" and out["day_rows_read"] == 7
    assert [m["date"] for m in out["members"]] == ["2026-10-18"] and out["duplicates"] == 1
    assert out["members"][0]["average_heart_rate"] == "62", "exponent-free values (Decimal(62) normalises to 6.2E+1)"
    assert [m["date"] for m in out["same_cycle_fields_with_recovery_members"]] == ["2026-10-19"]
    assert census_mod.main([]) == 2, "no write mode: without --dry-run it refuses"
