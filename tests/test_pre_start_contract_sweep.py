"""tests/test_pre_start_contract_sweep.py — the #948 pre-start contract sweep.

#939 shipped the pre-start countdown contract for /api/journey, /api/snapshot and
/api/pulse; the 2026-07-11 platform sweep found the endpoints it missed. These tests
pin the sweep, one endpoint at a time, each with BOTH fixtures:

  * pre_start  — genesis staged in the FUTURE (the countdown window):
      - /api/observatory_week: honest empty shape (null summary/period), never an
        inverted start>end window with fabricated zero-comparisons
      - /api/cycle_compare:   window_days 0 + "begins <genesis>" note, never the
        degenerate "first 1 days" pseudo-window
      - /api/vacation_fund:   day_count 0 / end_date None, never start > end
      - /api/weekly_priority: null priority (the stored integrator read predates
        the staged genesis), never the wiped cycle's "week's call"
      - /api/journey_waveform: day_n 0 (matching /api/journey) so the front-end
        #931 gates fire; no fabricated single-day strip
      - /api/character + /api/character_stats: the zeroed sheet's as_of_date is
        clamped to today — never a future date — and the two endpoints AGREE
      - /api/forecast: carries the pre_start flag so the cockpit can frame the
        panel as the model's warm-up
  * post-genesis — genesis in the past: every branch is structurally inert
    (pre_start False / absent-meta, numbers flow exactly as before), proven so the
    sweep can ship BEFORE Sunday's genesis and stay dead code after it.

Week-1 honesty rides along (ADR-104): a week-over-week delta needs BOTH weeks —
"vs 0 last week" against a prior window that clamps empty at genesis is fabricated.

All offline; genesis dates derive from now(PT) (no wall-clock time bombs).
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from fakes import FakeDdbTable  # noqa: E402
from web import (  # noqa: E402
    site_api_coach as coach,
    site_api_common as common,
    site_api_data as data,
    site_api_lambda as lam,
    site_api_vitals as vitals,
)

FUTURE_GENESIS_DAYS = 2  # the real reset window: constants regenerate ~2 days ahead


def _today_pt():
    return datetime.now(common.PT).date()


def _iso(d):
    return d.strftime("%Y-%m-%d")


def _set_genesis(monkeypatch, iso):
    """Point every module's imported EXPERIMENT_START at the same genesis.
    pre_start_meta() reads common's module global, so patching common is what
    flips the contract; the per-module constants cover window math."""
    for mod in (common, data, vitals, coach):
        monkeypatch.setattr(mod, "EXPERIMENT_START", iso)


def _future(monkeypatch):
    start = _today_pt() + timedelta(days=FUTURE_GENESIS_DAYS)
    _set_genesis(monkeypatch, _iso(start))
    return _iso(start)


def _past(monkeypatch, days=30):
    start = _today_pt() - timedelta(days=days)
    _set_genesis(monkeypatch, _iso(start))
    return _iso(start)


def _body(resp):
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def _whoop(date, dur=7.4, rec=66):
    return {"sk": f"DATE#{date}", "recovery_score": rec, "sleep_duration_hours": dur}


# ── /api/observatory_week ─────────────────────────────────────────────────────


def test_observatory_week_pre_start_honest_empty(monkeypatch):
    start = _future(monkeypatch)

    def _boom(*a, **k):
        raise AssertionError("pre-start must not query an inverted window")

    monkeypatch.setattr(data, "_query_source", _boom)
    b = _body(data.handle_observatory_week({"domain": "sleep"}))
    assert b["pre_start"] is True
    assert b["days_until_start"] == FUTURE_GENESIS_DAYS
    assert b["start_date"] == start
    assert b["summary"] is None  # the front-end's "numbers aren't in yet" branch engages
    assert b["notable"] is None
    assert b["period"] is None  # never start 07-12 → end 07-11


def test_observatory_week_pre_start_time_travel_still_serves_history(monkeypatch):
    # ?date= is the cross-cycle history view — the countdown must not blank it.
    _future(monkeypatch)
    past = _iso(_today_pt() - timedelta(days=20))
    monkeypatch.setattr(data, "_query_source", lambda *a, **k: [_whoop(past)])
    b = _body(data.handle_observatory_week({"domain": "sleep", "date": past}))
    assert b["time_travel"] is True
    assert b["summary"]["primary"]["value"] is not None
    assert "pre_start" not in b


def test_observatory_week_inert_when_genesis_past(monkeypatch):
    _past(monkeypatch)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d3 = _iso(_today_pt() - timedelta(days=3))
    d10 = _iso(_today_pt() - timedelta(days=10))

    def qs(source, s, e, include_pilot=False):
        # current window ends today; the prior week's window ends before it
        return [_whoop(d3, 7.0)] if e == today else [_whoop(d10, 8.0)]

    monkeypatch.setattr(data, "_query_source", qs)
    b = _body(data.handle_observatory_week({"domain": "sleep"}))
    assert "pre_start" not in b
    assert b["period"]["end"] == today
    assert b["period"]["start"] <= b["period"]["end"]
    p = b["summary"]["primary"]
    assert p["value"] == 7.0
    assert p["delta"] == -1.0  # both weeks present → the comparison is real
    assert p["delta_label"] == "vs 8.0 last week"


def test_observatory_week_week1_no_fabricated_comparison(monkeypatch):
    # Week 1 of a cycle: the prior window clamps to genesis and stays empty —
    # never "vs 0 last week" (ADR-104).
    _past(monkeypatch, days=3)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d1 = _iso(_today_pt() - timedelta(days=1))

    def qs(source, s, e, include_pilot=False):
        return [_whoop(d1, 7.2)] if e == today else []

    monkeypatch.setattr(data, "_query_source", qs)
    b = _body(data.handle_observatory_week({"domain": "sleep"}))
    p = b["summary"]["primary"]
    assert p["value"] == 7.2
    assert p["delta"] is None
    assert p["delta_label"] == ""
    assert p["trend"] == "flat"
    assert "vs last week" not in (b["notable"] or "")


# ── /api/cycle_compare ────────────────────────────────────────────────────────


def test_cycle_compare_pre_start_no_pseudo_window(monkeypatch):
    start = _future(monkeypatch)
    monkeypatch.setattr(data, "CYCLE_GENESES", {4: _iso(_today_pt() - timedelta(days=27)), 5: start})

    def _boom(*a, **k):
        raise AssertionError("pre-start must not compute a 1-day pseudo-window")

    monkeypatch.setattr(data, "_query_source", _boom)
    b = _body(data.handle_cycle_compare())
    assert b["pre_start"] is True
    assert b["window_days"] == 0
    assert b["cycles"] == []
    assert f"begins {start}" in b["note"]
    assert "first 1 days" not in b["note"]


def test_cycle_compare_day1_singular_and_inert(monkeypatch):
    # Genesis TODAY: the countdown is over (pre_start_meta is None), the window is a
    # legitimate 1 day — and the note must read "day", not "1 days" (recurs on every
    # genesis day of every cycle).
    today = _iso(_today_pt())
    _set_genesis(monkeypatch, today)
    monkeypatch.setattr(data, "CYCLE_GENESES", {4: _iso(_today_pt() - timedelta(days=27)), 5: today})
    monkeypatch.setattr(data, "_query_source", lambda *a, **k: [])
    b = _body(data.handle_cycle_compare())
    assert "pre_start" not in b
    assert b["window_days"] == 1
    assert len(b["cycles"]) == 2
    assert "first 1 day —" in b["note"]
    assert "1 days" not in b["note"]


def test_cycle_compare_inert_when_genesis_past(monkeypatch):
    g = _past(monkeypatch, days=9)
    monkeypatch.setattr(data, "CYCLE_GENESES", {4: _iso(_today_pt() - timedelta(days=40)), 5: g})
    monkeypatch.setattr(data, "_query_source", lambda *a, **k: [])
    b = _body(data.handle_cycle_compare())
    assert "pre_start" not in b
    assert b["window_days"] == 10  # 9 days ago, 1-indexed
    assert "first 10 days" in b["note"]


# ── /api/vacation_fund ────────────────────────────────────────────────────────


def _fund_payload(g, end, days):
    return {
        "start_date": g,
        "end_date": end,
        "day_count": days,
        "rate_per_mile": 1.0,
        "total_miles": 0.0,
        "miles_usd": 0.0,
        "manual_adjustment_usd": 0.0,
        "total_usd": 0.0,
        "pace": {"miles_per_week": 0.0, "projected_usd_1yr": 0.0},
        "warnings": [],
    }


def test_vacation_fund_pre_start_no_inverted_window(monkeypatch):
    start = _future(monkeypatch)
    import vacation_fund as vf

    monkeypatch.setattr(vf, "compute_vacation_fund", lambda *a, **k: _fund_payload(start, _iso(_today_pt()), 1))
    b = _body(lam.handle_vacation_fund())
    assert b["pre_start"] is True
    assert b["days_until_start"] == FUTURE_GENESIS_DAYS
    assert b["start_date"] == start  # "counting begins at genesis"
    assert b["end_date"] is None  # never end < start
    assert b["day_count"] == 0
    assert b["pace"] == {"miles_per_week": None, "projected_usd_1yr": None}


def test_vacation_fund_inert_when_genesis_past(monkeypatch):
    g = _past(monkeypatch)
    import vacation_fund as vf

    today = _iso(_today_pt())
    monkeypatch.setattr(vf, "compute_vacation_fund", lambda *a, **k: _fund_payload(g, today, 31))
    b = _body(lam.handle_vacation_fund())
    assert b["pre_start"] is False
    assert b["end_date"] == today
    assert b["day_count"] == 31
    assert b["pace"]["miles_per_week"] == 0.0


# ── /api/weekly_priority ──────────────────────────────────────────────────────

_STALE_INTEGRATOR = {
    "analysis": "the wiped cycle's week's call",
    "cross_domain_notes": {"sleep": "stale"},
    "generated_at": "2026-06-25T00:00:00Z",
    "week_number": 2,
}


def test_weekly_priority_pre_start_null(monkeypatch):
    start = _future(monkeypatch)
    row = dict(_STALE_INTEGRATOR, pk=f"{coach.USER_PREFIX}ai_analysis", sk="EXPERT#integrator")
    monkeypatch.setattr(coach, "table", FakeDdbTable(rows=[row]))
    b = _body(coach.handle_weekly_priority({}))
    assert b["pre_start"] is True
    assert b["start_date"] == start
    assert b["weekly_priority"] is None  # the stored read predates the staged genesis
    assert b["cross_domain_notes"] == {}


def test_weekly_priority_inert_when_genesis_past(monkeypatch):
    _past(monkeypatch)
    row = dict(_STALE_INTEGRATOR, pk=f"{coach.USER_PREFIX}ai_analysis", sk="EXPERT#integrator")
    monkeypatch.setattr(coach, "table", FakeDdbTable(rows=[row]))
    b = _body(coach.handle_weekly_priority({}))
    assert b["pre_start"] is False
    assert b["weekly_priority"] == "the wiped cycle's week's call"
    assert b["coach_name"] == "Dr. Kai Nakamura"


# ── /api/journey_waveform ─────────────────────────────────────────────────────


def test_journey_waveform_pre_start_day_zero(monkeypatch):
    start = _future(monkeypatch)
    monkeypatch.setattr(vitals, "table", FakeDdbTable(rows=[]))
    b = _body(vitals.handle_journey_waveform())
    assert b["pre_start"] is True
    assert b["start_date"] == start
    assert b["day_n"] == 0  # matches /api/journey — the front-end #931 gate fires
    assert b["week_n"] == 0
    assert b["days"] == []  # no fabricated single-day strip
    assert b["window"] == 0


def test_journey_waveform_inert_when_genesis_past(monkeypatch):
    _past(monkeypatch, days=5)
    monkeypatch.setattr(vitals, "table", FakeDdbTable(rows=[]))
    b = _body(vitals.handle_journey_waveform())
    assert b["pre_start"] is False
    assert b["day_n"] == 6  # 5 days ago, 1-indexed
    assert len(b["days"]) == 6


# ── /api/character + /api/character_stats — the as_of stamps agree ────────────


def test_character_zeroed_pre_start_as_of_never_future(monkeypatch):
    start = _future(monkeypatch)
    monkeypatch.setattr(vitals, "table", FakeDdbTable(rows=[]))  # every sheet phase-hidden post-reset
    b = _body(vitals.handle_character())
    ch = b["character"]
    assert ch["pre_experiment"] is True
    assert ch["as_of_date"] == _iso(_today_pt())  # clamped — never "as of <tomorrow>"
    assert ch["as_of_date"] < start
    assert b["pre_start"] is True
    assert b["days_until_start"] == FUTURE_GENESIS_DAYS


def test_character_stats_pre_start_agrees_with_character(monkeypatch):
    start = _future(monkeypatch)
    # A stale prior-cycle sheet is still reachable via get_item (no phase filter) —
    # the served stamp must be the clamped "now", not the stale record's date, so
    # the two character endpoints stop disagreeing.
    utc_today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stale = {"pk": f"{vitals.USER_PREFIX}character_sheet", "sk": f"DATE#{utc_today}", "character_level": 13}
    monkeypatch.setattr(vitals, "table", FakeDdbTable(rows=[stale]))
    b = _body(vitals.handle_character_stats())
    cs = b["character_stats"]
    assert cs["pre_experiment"] is True
    assert cs["level"] == 1  # zeroed, not the stale level
    assert cs["as_of_date"] == _iso(_today_pt())
    assert cs["as_of_date"] < start
    assert b["pre_start"] is True

    # The cross-endpoint agreement, stated directly:
    monkeypatch.setattr(vitals, "table", FakeDdbTable(rows=[]))
    ch = _body(vitals.handle_character())["character"]
    assert ch["as_of_date"] == cs["as_of_date"]


def test_character_zeroed_inert_when_genesis_past(monkeypatch):
    g = _past(monkeypatch)
    monkeypatch.setattr(vitals, "table", FakeDdbTable(rows=[]))
    b = _body(vitals.handle_character())
    ch = b["character"]
    assert ch["pre_experiment"] is True
    assert ch["as_of_date"] == g  # past genesis: the clamp is a no-op
    assert b["pre_start"] is False


def test_character_stats_normal_when_genesis_past(monkeypatch):
    _past(monkeypatch)
    utc_today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = {
        "pk": f"{vitals.USER_PREFIX}character_sheet",
        "sk": f"DATE#{utc_today}",
        "character_level": 5,
        "character_tier": "Momentum",
        "character_xp": 120,
    }
    monkeypatch.setattr(vitals, "table", FakeDdbTable(rows=[row]))
    b = _body(vitals.handle_character_stats())
    cs = b["character_stats"]
    assert "pre_experiment" not in cs
    assert cs["level"] == 5
    assert cs["as_of_date"] == utc_today


# ── /api/forecast — the pre_start flag for the cockpit's warm-up frame ───────


def _forecast_row():
    return {
        "pk": "USER#matthew#SOURCE#forecast",
        "sk": "DATE#2026-01-01",
        "record_type": "forecast_summary",
        "forecasts": [{"metric": "weight_lbs", "horizon_days": 1, "point": 300.9, "lo": 299.3, "hi": 302.5}],
        "coverage": {"n_resolved": 12, "coverage_pct": 83},
    }


def test_forecast_pre_start_flag(monkeypatch):
    start = _future(monkeypatch)
    monkeypatch.setattr(data, "table", FakeDdbTable(rows=[_forecast_row()]))
    b = _body(data.handle_forecast())
    assert b["available"] is True
    assert b["pre_start"] is True
    assert b["start_date"] == start
    assert b["days_until_start"] == FUTURE_GENESIS_DAYS


def test_forecast_inert_when_genesis_past(monkeypatch):
    _past(monkeypatch)
    monkeypatch.setattr(data, "table", FakeDdbTable(rows=[_forecast_row()]))
    b = _body(data.handle_forecast())
    assert b["pre_start"] is False
    assert "days_until_start" not in b
