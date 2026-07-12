"""tests/test_honest_read_guards_1084.py — #1084 honest-numbers read guards.

Two guard classes (ADR-105 rigor bar / ADR-077 "clamped, not hidden"):

1. /api/training_overview — a trailing per-day mean must never be fabricated
   from a partial day: `avg_daily_steps` (and the sibling `avg_strain`) exclude
   TODAY (still accruing) and need >= 3 complete days before claiming an
   average; weekly averages (`weekly_avg`, `z2_weekly_avg_min`, `z2_pct`)
   divide by the REAL genesis-clamped window and read None below a 7-day floor
   instead of a fixed /4.3.

2. /api/vitals — LIVE trailing windows (d30/d7/apple-health weight backscan)
   clamp at genesis so they never reach into prior-cycle rows; time-travel
   (?date=) deliberately keeps the full reach (ADR-058). `hrv_30d_avg` carries
   min-n semantics + an explicit `hrv_30d_n`.

All dates are computed relative to the wall clock at test time and genesis is
monkeypatched per-test — no frozen-fixture time bombs.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import (
    site_api_observatory as obs,  # noqa: E402
    site_api_vitals as vitals,  # noqa: E402
)

_NOW = datetime.now(timezone.utc)


def _d(days_ago: int) -> str:
    return (_NOW - timedelta(days=days_ago)).strftime("%Y-%m-%d")


class _FakeTable:
    def query(self, **_kw):
        return {"Items": []}


def _fake_query_source(data_by_source, calls=None):
    def fake(source, start, end, include_pilot=False):
        if calls is not None:
            calls.append((source, start, end, include_pilot))
        return [dict(r) for r in data_by_source.get(source, [])]

    return fake


def _setup_training(monkeypatch, data, genesis_days_ago=400, calls=None):
    """Wire handle_training_overview offline: fake sources + a genesis-clamped
    _experiment_date that mirrors the real helper's max(raw, EXPERIMENT_START)."""
    genesis = _d(genesis_days_ago)
    monkeypatch.setattr(obs, "EXPERIMENT_START", genesis)
    monkeypatch.setattr(obs, "_experiment_date", lambda n=30: max(_d(n), genesis))
    monkeypatch.setattr(obs, "_query_source", _fake_query_source(data, calls))
    monkeypatch.setattr(obs, "table", _FakeTable())
    return genesis


def _training_body(monkeypatch, data, **kw):
    _setup_training(monkeypatch, data, **kw)
    resp = obs.handle_training_overview()
    assert resp["statusCode"] == 200
    return json.loads(resp["body"])


# ── 1a. avg_daily_steps: n >= floor, partial today excluded ─────────────────


def test_steps_avg_excludes_partial_today_at_floor(monkeypatch):
    ah = [{"sk": f"DATE#{_d(i)}", "steps": 10000} for i in (1, 2, 3)]
    ah.append({"sk": f"DATE#{_d(0)}", "steps": 2000})  # today, partial
    body = _training_body(monkeypatch, {"apple_health": ah})
    walking = body["walking"]
    assert walking["avg_daily_steps"] == 10000  # not dragged down by the partial
    assert walking["avg_daily_steps_n"] == 3
    assert walking["avg_daily_steps_reason"] is None
    assert body["training"]["avg_daily_steps"] == 10000
    # the per-day trend still charts today — a daily value, not an average
    assert len(walking["daily_steps_trend"]) == 4
    assert any(p["date"] == _d(0) for p in walking["daily_steps_trend"])


def test_steps_avg_n1_partial_today_is_null_with_reason(monkeypatch):
    # The verified #1084 root cause: Day 1, only today's partial count exists.
    ah = [{"sk": f"DATE#{_d(0)}", "steps": 1234}]
    body = _training_body(monkeypatch, {"apple_health": ah})
    walking = body["walking"]
    assert walking["avg_daily_steps"] is None
    assert walking["avg_daily_steps_n"] == 0  # today never counts
    assert walking["avg_daily_steps_reason"] == "insufficient_data"
    assert body["training"]["avg_daily_steps"] is None


def test_steps_avg_below_min_n_is_null(monkeypatch):
    ah = [{"sk": f"DATE#{_d(i)}", "steps": 9000} for i in (1, 2)]  # 2 complete days < floor
    walking = _training_body(monkeypatch, {"apple_health": ah})["walking"]
    assert walking["avg_daily_steps"] is None
    assert walking["avg_daily_steps_n"] == 2
    assert walking["avg_daily_steps_reason"] == "insufficient_data"


def test_steps_avg_n0_no_data(monkeypatch):
    walking = _training_body(monkeypatch, {})["walking"]
    assert walking["avg_daily_steps"] is None
    assert walking["avg_daily_steps_n"] == 0
    assert walking["avg_daily_steps_reason"] == "insufficient_data"


# ── 1b. weekly averages: real window, None below the 7-day floor ────────────


def _strava_day(days_ago, minutes=60, avg_hr=120):
    # avg_hr 120 sits inside Zone 2 for max_hr 184 (110.4–128.8)
    return {
        "sk": f"DATE#{_d(days_ago)}",
        "activities": [{"sport_type": "Walk", "duration_minutes": minutes, "average_heartrate": avg_hr}],
    }


def test_weekly_avgs_divide_by_real_window(monkeypatch):
    strava = [_strava_day(i) for i in range(1, 11)]  # 10 activities in-window
    t = _training_body(monkeypatch, {"strava": strava})["training"]
    win_weeks = 30 / 7.0  # full genesis-distant window: d30 = today-30
    assert t["weekly_avg"] == round(10 / win_weeks, 1)
    assert t["z2_weekly_avg_min"] == round(600 / win_weeks)
    assert t["z2_pct"] == round(round(600 / win_weeks) / 150 * 100)


def test_weekly_avgs_null_below_window_floor(monkeypatch):
    # Genesis 2 days ago: the clamped "30d" window spans 2 complete days (< 7).
    strava = [_strava_day(1)]
    t = _training_body(monkeypatch, {"strava": strava}, genesis_days_ago=2)["training"]
    assert t["weekly_avg"] is None  # old code: 1 workout / "4.3 weeks"
    assert t["z2_weekly_avg_min"] is None
    assert t["z2_pct"] is None
    # honest raw counts still surface
    assert t["workouts_30d"] == 1
    assert t["z2_trailing_7d_min"] == 60  # the trailing SUM stays — it is not a mean


# ── 1c. avg_strain sibling guard ─────────────────────────────────────────────


def test_avg_strain_excludes_partial_today(monkeypatch):
    whoop = [{"sk": f"DATE#{_d(i)}", "strain": 10.0} for i in (1, 2, 3)]
    whoop.append({"sk": f"DATE#{_d(0)}", "strain": 20.0})  # today accrues until midnight
    t = _training_body(monkeypatch, {"whoop": whoop})["training"]
    assert t["avg_strain"] == 10.0


def test_avg_strain_below_min_n_is_null(monkeypatch):
    whoop = [{"sk": f"DATE#{_d(i)}", "strain": 12.0} for i in (1, 2)]
    t = _training_body(monkeypatch, {"whoop": whoop})["training"]
    assert t["avg_strain"] is None


# ── 2. /api/vitals genesis clamp + hrv min-n ─────────────────────────────────


def _whoop_rec(date_str, hrv=60.0, rhr=52):
    return {"sk": f"DATE#{date_str}", "recovery_score": 66, "hrv": hrv, "resting_heart_rate": rhr, "sleep_duration_hours": 7.2}


def _setup_vitals(monkeypatch, genesis, data=None, calls=None):
    monkeypatch.setattr(vitals, "EXPERIMENT_START", genesis)
    monkeypatch.setattr(vitals, "_query_source", _fake_query_source(data or {}, calls))
    monkeypatch.setattr(vitals, "_latest_item", lambda *_a, **_k: {})
    monkeypatch.setattr(vitals, "_latest_item_asof", lambda *_a, **_k: {})


def test_vitals_live_trailing_windows_clamp_at_genesis(monkeypatch):
    genesis = _d(5)
    calls = []
    _setup_vitals(monkeypatch, genesis, calls=calls)
    assert vitals.handle_vitals()["statusCode"] == 200
    whoop_calls = [c for c in calls if c[0] == "whoop"]
    assert whoop_calls, "handle_vitals must query whoop"
    # both the 7d and 30d windows would reach past a 5-day-old genesis — clamped
    assert all(start == genesis for (_s, start, _e, _p) in whoop_calls)
    assert all(pilot is False for (*_x, pilot) in whoop_calls)
    ah_calls = [c for c in calls if c[0] == "apple_health"]
    assert ah_calls and all(start == genesis for (_s, start, _e, _p) in ah_calls)


def test_vitals_time_travel_keeps_full_reach(monkeypatch):
    genesis = _d(5)
    anchor = _d(20)  # scrub to a pre-genesis morning
    calls = []
    _setup_vitals(monkeypatch, genesis, calls=calls)
    assert vitals.handle_vitals(date=anchor)["statusCode"] == 200
    whoop_calls = [c for c in calls if c[0] == "whoop"]
    assert whoop_calls
    # windows anchor at the scrubbed date and are NOT genesis-clamped (ADR-058)
    assert all(start < genesis for (_s, start, _e, _p) in whoop_calls)
    assert all(pilot is True for (*_x, pilot) in whoop_calls)


def test_vitals_future_staged_genesis_never_500s(monkeypatch):
    genesis = (_NOW + timedelta(days=2)).strftime("%Y-%m-%d")
    calls = []
    _setup_vitals(monkeypatch, genesis, calls=calls)
    resp = vitals.handle_vitals()
    assert resp["statusCode"] == 200
    v = json.loads(resp["body"])["vitals"]
    assert v["hrv_30d_avg"] is None and v["weight_lbs"] is None
    # the clamp pushes start past end — the real _query_source treats that as []
    whoop_calls = [c for c in calls if c[0] == "whoop"]
    assert all(start == genesis for (_s, start, _e, _p) in whoop_calls)


def test_vitals_hrv_avg_min_n(monkeypatch):
    genesis = "2020-01-01"
    # n=2 < floor → None, but n is surfaced and the latest reading still shows
    _setup_vitals(monkeypatch, genesis, data={"whoop": [_whoop_rec(_d(1), 60.0), _whoop_rec(_d(2), 62.0)]})
    v = json.loads(vitals.handle_vitals()["body"])["vitals"]
    assert v["hrv_30d_avg"] is None
    assert v["hrv_30d_n"] == 2
    assert v["hrv_ms"] == 60.0  # latest reading is a reading, not an average

    # n=3 ≥ floor → the average shows, with its n
    _setup_vitals(monkeypatch, genesis, data={"whoop": [_whoop_rec(_d(i), h) for i, h in ((1, 60.0), (2, 62.0), (3, 64.0))]})
    v = json.loads(vitals.handle_vitals()["body"])["vitals"]
    assert v["hrv_30d_avg"] == 62.0
    assert v["hrv_30d_n"] == 3
