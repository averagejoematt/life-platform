"""tests/test_vitals_evening_pt_frame_1937.py — #1937 behavioral replay.

The AST guard (test_pt_date_anchor_guard_1937.py) proves NO naked UTC
day-anchor idiom remains in the source. This file proves the fix actually
changes handler BEHAVIOR at the exact instant the bug was only observable:
5pm-midnight PT, where the UTC calendar day has already rolled to tomorrow
while the Pacific day has not (#1936's finding — `/api/vitals` claimed
"Day 7" on Day 6 at 2026-08-02T02:36Z, which is 2026-08-01 19:36 PDT).

Frozen at 2026-07-01T02:30:00Z == 2026-06-30 19:30 PDT (squarely in that
window, mirroring tests/test_pacific_date_selection.py's EVENING_PT fixture).
A UTC-anchored handler would query/report through 2026-07-01; the fix must
report 2026-06-30 — never wall-clock `datetime.now()`.
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from common import pacific_time  # noqa: E402
from web import (  # noqa: E402
    site_api_common as common,
    site_api_vitals as vitals,
)

# 2026-07-01 02:30 UTC == 2026-06-30 19:30 PDT — inside the 5pm-midnight PT
# window where a UTC day-anchor runs one calendar day ahead of PT.
EVENING_UTC = datetime(2026, 7, 1, 2, 30, tzinfo=timezone.utc)
PT_DAY = "2026-06-30"
WRONG_UTC_DAY = "2026-07-01"


def _freeze(monkeypatch, module, instant):
    """Pin `module.datetime.now()` — mirrors test_pacific_date_selection.py's
    `_freeze` helper. Applied to BOTH site_api_vitals and site_api_common
    since some handlers call into common's `_experiment_date`/`_clamp_today`,
    which resolve `datetime.now(...)` in THEIR OWN module namespace, not the
    caller's."""

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(module, "datetime", _Frozen)


def _freeze_all(monkeypatch):
    _freeze(monkeypatch, vitals, EVENING_UTC)
    _freeze(monkeypatch, common, EVENING_UTC)
    # pacific_day_n(EXPERIMENT_START) (no on_date arg — handle_journey line 368)
    # falls back to pacific_time.pacific_today(), which resolves `datetime.now`
    # in pacific_time's OWN module namespace — pin it too so day_n is frozen.
    _freeze(monkeypatch, pacific_time, EVENING_UTC)


def _body(resp):
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def test_handle_journey_queries_and_reports_the_pt_day_not_utc(monkeypatch):
    _freeze_all(monkeypatch)
    seen_ends = []

    def fake_qs(source, start, end, include_pilot=False):
        seen_ends.append(end)
        return []

    monkeypatch.setattr(vitals, "_query_source", fake_qs)
    monkeypatch.setattr(vitals, "_latest_item", lambda source, include_pilot=False: None)
    monkeypatch.setattr(vitals, "_get_profile", lambda: {})
    monkeypatch.setattr(vitals, "EXPERIMENT_START", "2026-06-01")

    resp = vitals.handle_journey()
    body = _body(resp)

    # Every DDB query end-bound is the PT day, never the UTC day one ahead.
    assert seen_ends, "handle_journey never called _query_source"
    assert all(e == PT_DAY for e in seen_ends), seen_ends
    assert WRONG_UTC_DAY not in seen_ends
    # day_n uses the shared pacific_day_n helper (#1955) — 2026-06-01 -> Day 30
    # in the PT frame; a UTC-anchored bug would have reported Day 31.
    assert body["journey"]["day_n"] == 30


def test_handle_weight_progress_window_ends_on_the_pt_day(monkeypatch):
    _freeze_all(monkeypatch)
    seen = {}

    def fake_qs(source, start, end, include_pilot=False):
        seen["start"], seen["end"] = start, end
        return []

    monkeypatch.setattr(vitals, "_query_source", fake_qs)
    vitals.handle_weight_progress()
    assert seen["end"] == PT_DAY
    assert seen["end"] != WRONG_UTC_DAY


def test_handle_glucose_actual_days_and_trend_date_are_pt_anchored(monkeypatch):
    """The exact consequence #1937 names: `_window_span`'s published
    `actual_days` (fed to `_w30`) and the trend's latest date must reflect the
    PT-elapsed window, not a UTC day that hasn't happened yet in Pacific."""
    _freeze_all(monkeypatch)

    def fake_qs(source, start, end, include_pilot=False):
        assert end == PT_DAY, f"handle_glucose queried through {end}, expected {PT_DAY}"
        # one CGM reading landing exactly on "today" (PT) — proves the trend's
        # own latest date doesn't drift to the UTC day either.
        return [{"sk": f"DATE#{PT_DAY}", "blood_glucose_avg": 95.0, "blood_glucose_time_in_range_pct": 88.0}]

    monkeypatch.setattr(vitals, "_query_source", fake_qs)
    monkeypatch.setattr(vitals, "EXPERIMENT_START", "2026-05-01")  # long-elapsed genesis, well >= 30d
    resp = vitals.handle_glucose()
    body = _body(resp)
    assert body["glucose_trend"][-1]["date"] == PT_DAY
    assert body["glucose_trend"][-1]["date"] != WRONG_UTC_DAY


def test_handle_sleep_detail_window_is_pt_anchored(monkeypatch):
    _freeze_all(monkeypatch)

    def fake_qs(source, start, end, include_pilot=False):
        assert end == PT_DAY, f"handle_sleep_detail queried {source} through {end}, expected {PT_DAY}"
        if source == "eightsleep":
            return [{"sk": f"DATE#{PT_DAY}", "sleep_score": 82, "sleep_hours": 7.5, "sleep_efficiency": 91}]
        return []

    monkeypatch.setattr(vitals, "_query_source", fake_qs)
    monkeypatch.setattr(vitals, "EXPERIMENT_START", "2026-05-01")
    resp = vitals.handle_sleep_detail()
    body = _body(resp)
    assert body["sleep_trend"][-1]["date"] == PT_DAY
    assert body["sleep_trend"][-1]["date"] != WRONG_UTC_DAY


def test_handle_timeline_weight_query_ends_on_the_pt_day(monkeypatch):
    _freeze_all(monkeypatch)
    seen = {}

    def fake_qs(source, start, end, include_pilot=False):
        if source == "withings":
            seen["end"] = end
        return []

    class _NullResp:
        @staticmethod
        def get(key, default=None):
            return default if key != "Items" else []

    class _FakeTable:
        def query(self, **kwargs):
            return {"Items": []}

    monkeypatch.setattr(vitals, "_query_source", fake_qs)
    monkeypatch.setattr(vitals, "table", _FakeTable())
    monkeypatch.setattr(vitals, "_get_profile", lambda: {})
    monkeypatch.setattr(vitals, "EXPERIMENT_START", "2026-06-01")

    vitals.handle_timeline()
    assert seen["end"] == PT_DAY
    assert seen["end"] != WRONG_UTC_DAY
