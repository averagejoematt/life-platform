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

from coach import persona_registry  # noqa: E402  (#1986 — the byline's single source)
from fakes import FakeDdbTable  # noqa: E402
from web import (  # noqa: E402
    site_api_coach as coach,
    site_api_common as common,
    site_api_data as data,
    site_api_intelligence as intel,  # #1240: handle_forecast moved here from site_api_data
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
    # Week 1 of a cycle: there is no prior window inside the cycle (#1977: it is
    # never manufactured by clamping) — never "vs 0 last week" (ADR-104).
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


# ── /api/observatory_week week-1 genesis clamp (#1977) ────────────────────────
#
# The pre-fix clamp mapped a fully-pre-genesis prev window onto [genesis, genesis]
# — INSIDE the current week — so Day 1 compared today to itself ("declined 0.0h
# vs last week", trend 'down') the moment genesis day had data. A window-shaped
# stub (return [] unless e == today) masks that; these tests stub a TABLE: rows
# keyed by date, any query that touches a row's date returns it, and every
# queried window is recorded so the guard is negative-tested structurally.


def _stub_table(monkeypatch, records):
    """Stubbed table: serves rows whose date falls inside the queried window
    (like the real DDB BETWEEN) and logs every queried window."""
    windows = []

    def qs(source, s, e, include_pilot=False):
        windows.append((s, e))
        return [r for r in records if s <= str(r["sk"])[5:] <= e]

    monkeypatch.setattr(data, "_query_source", qs)
    return windows


def _mf(date, kcal=2000, protein=150):
    return {"sk": f"DATE#{date}", "total_calories_kcal": kcal, "total_protein_g": protein}


def test_observatory_week_genesis_day_prev_window_never_manufactured(monkeypatch):
    # anchor == genesis, genesis day HAS data: the honest output is absence —
    # null delta, 'flat', no "vs last week" — and the prev window is never queried.
    genesis = _past(monkeypatch, days=0)
    windows = _stub_table(monkeypatch, [_whoop(genesis, 7.2)])
    b = _body(data.handle_observatory_week({"domain": "sleep"}))
    p = b["summary"]["primary"]
    assert p["value"] == 7.2
    assert p["delta"] is None
    assert p["delta_label"] == ""
    assert p["trend"] == "flat"
    assert "vs last week" not in (b["notable"] or "")
    # the ONLY query is the current window — no manufactured prev window
    # intersecting [start, end] (pre-fix: a second [genesis, genesis] query)
    assert windows == [(b["period"]["start"], b["period"]["end"])]


def test_observatory_week_week1_day3_absence_not_zero_delta(monkeypatch):
    # anchor == genesis+2d with data on every cycle day so far: still absence —
    # pre-fix this served the genesis row as "last week".
    genesis = _past(monkeypatch, days=2)
    g = datetime.strptime(genesis, "%Y-%m-%d")
    windows = _stub_table(monkeypatch, [_whoop(_iso(g + timedelta(days=i)), 7.0 + 0.1 * i) for i in range(3)])
    b = _body(data.handle_observatory_week({"domain": "sleep"}))
    p = b["summary"]["primary"]
    assert p["delta"] is None
    assert p["trend"] == "flat"
    assert "vs last week" not in (b["notable"] or "")
    assert windows == [(b["period"]["start"], b["period"]["end"])]


def test_observatory_week_partial_prior_week_still_compares(monkeypatch):
    # Week 2: the prev window is partially pre-genesis — its START clamps to
    # genesis (a real, shorter prior window), the comparison is real, and the
    # prev window never intersects the current week.
    genesis = _past(monkeypatch, days=10)
    g = datetime.strptime(genesis, "%Y-%m-%d")
    anchor = datetime.now(timezone.utc)
    windows = _stub_table(
        monkeypatch,
        [_whoop(_iso(g + timedelta(days=1)), 8.0), _whoop(_iso(anchor - timedelta(days=1)), 7.0)],
    )
    b = _body(data.handle_observatory_week({"domain": "sleep"}))
    p = b["summary"]["primary"]
    assert p["value"] == 7.0
    assert p["delta"] == -1.0
    assert p["delta_label"] == "vs 8.0 last week"
    assert p["trend"] == "down"
    prev_windows = [w for w in windows if w != (b["period"]["start"], b["period"]["end"])]
    assert prev_windows, "the partial prior week must still be queried"
    assert all(w[0] >= genesis and w[1] < b["period"]["start"] for w in prev_windows)


def test_observatory_week_tie_is_flat_not_down(monkeypatch):
    # Both weeks present at the same average: delta 0.0 must read 'flat' with a
    # neutral notable — pre-fix the tie mapped to 'down' ("declined 0.0h").
    _past(monkeypatch, days=30)
    anchor = datetime.now(timezone.utc)
    _stub_table(monkeypatch, [_whoop(_iso(anchor - timedelta(days=1)), 7.5), _whoop(_iso(anchor - timedelta(days=9)), 7.5)])
    b = _body(data.handle_observatory_week({"domain": "sleep"}))
    p = b["summary"]["primary"]
    assert p["delta"] == 0.0
    assert p["trend"] == "flat"
    assert "declined" not in b["notable"] and "improved" not in b["notable"]
    assert "held steady" in b["notable"]


def test_observatory_week_nutrition_week1_absence_and_tie(monkeypatch):
    # Same contract on the other week-over-week branch (nutrition).
    genesis = _past(monkeypatch, days=1)
    windows = _stub_table(monkeypatch, [_mf(genesis)])
    b = _body(data.handle_observatory_week({"domain": "nutrition"}))
    p = b["summary"]["primary"]
    assert p["delta"] is None
    assert p["delta_label"] == ""
    assert p["trend"] == "flat"
    assert windows == [(b["period"]["start"], b["period"]["end"])]

    _past(monkeypatch, days=30)
    anchor = datetime.now(timezone.utc)
    _stub_table(monkeypatch, [_mf(_iso(anchor - timedelta(days=1))), _mf(_iso(anchor - timedelta(days=9)))])
    b2 = _body(data.handle_observatory_week({"domain": "nutrition"}))
    p2 = b2["summary"]["primary"]
    assert p2["delta"] == 0
    assert p2["trend"] == "flat"


def test_observatory_week_physical_tie_is_flat(monkeypatch):
    # Physical's intra-week delta: an unchanged weight is 'flat', never "gained 0.0 lbs".
    _past(monkeypatch, days=30)
    anchor = datetime.now(timezone.utc)
    _stub_table(
        monkeypatch,
        [{"sk": f"DATE#{_iso(anchor - timedelta(days=d))}", "weight_lbs": 200.0} for d in (5, 1)],
    )
    b = _body(data.handle_observatory_week({"domain": "physical"}))
    p = b["summary"]["primary"]
    assert p["delta"] == 0.0
    assert p["trend"] == "flat"
    assert b["notable"] == "Weight held steady this week"


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
    from content import vacation_fund as vf

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
    from content import vacation_fund as vf

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
    # #1986: the byline is the persona registry's single board lead, not a literal.
    assert b["coach_name"] == persona_registry.lead_name()


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
    # #2060: handle_character_stats's get_item lookback is PT-clocked (today/yesterday
    # in PT, matching handle_character's PT-based as_of), not UTC — keying the fixture
    # off UTC drifts a day out of reach whenever PT and UTC straddle midnight.
    today_pt = _iso(_today_pt())
    stale = {"pk": f"{vitals.USER_PREFIX}character_sheet", "sk": f"DATE#{today_pt}", "character_level": 13}
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
    # #2060: same PT-clocked lookback as above — the row must be keyed on the PT
    # date handle_character_stats's today/yesterday loop actually queries.
    today_pt = _iso(_today_pt())
    row = {
        "pk": f"{vitals.USER_PREFIX}character_sheet",
        "sk": f"DATE#{today_pt}",
        "character_level": 5,
        "character_tier": "Momentum",
        "character_xp": 120,
    }
    monkeypatch.setattr(vitals, "table", FakeDdbTable(rows=[row]))
    b = _body(vitals.handle_character_stats())
    cs = b["character_stats"]
    assert "pre_experiment" not in cs
    assert cs["level"] == 5
    assert cs["as_of_date"] == today_pt


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
    monkeypatch.setattr(intel, "table", FakeDdbTable(rows=[_forecast_row()]))
    b = _body(intel.handle_forecast())
    assert b["available"] is True
    assert b["pre_start"] is True
    assert b["start_date"] == start
    assert b["days_until_start"] == FUTURE_GENESIS_DAYS


def test_forecast_inert_when_genesis_past(monkeypatch):
    _past(monkeypatch)
    monkeypatch.setattr(intel, "table", FakeDdbTable(rows=[_forecast_row()]))
    b = _body(intel.handle_forecast())
    assert b["pre_start"] is False
    assert "days_until_start" not in b


# ── /api/journey_timeline — the Day-1 anchor (#1021) ─────────────────────────
# Launch eve: the anchor event was stamped with the CLAMPED query bound (today),
# so the timeline read "2026-07-11 · Day 1" while the hero counted down to the
# 12th — the page contradicted itself. The anchor (and the pre-experiment
# filter) must use the TRUE genesis; the clamp exists only for sk.between().


def test_journey_timeline_pre_start_day1_dated_at_genesis(monkeypatch):
    start = _future(monkeypatch)
    monkeypatch.setattr(vitals, "table", FakeDdbTable(rows=[]))
    monkeypatch.setattr(vitals, "_get_profile", lambda: {})
    b = _body(vitals.handle_journey_timeline())
    day1 = [e for e in b["events"] if e["title"] == "Day 1"]
    assert len(day1) == 1
    assert day1[0]["date"] == start  # never today's (clamped) date on launch eve
    assert all(e["date"] >= start for e in b["events"])  # nothing pre-genesis


def test_journey_timeline_pre_start_excludes_wiped_cycle_events(monkeypatch):
    # A leftover active experiment stamped launch eve (>= the clamped bound but
    # < genesis) must not render next to the countdown as if the cycle had begun.
    start = _future(monkeypatch)
    eve = _iso(_today_pt())
    row = {
        "pk": f"{vitals.USER_PREFIX}experiments",
        "sk": "EXP#stale",
        "start_date": eve,
        "status": "active",
        "name": "Wiped-cycle straggler",
        "hypothesis": "should not appear pre-genesis",
    }
    monkeypatch.setattr(vitals, "table", FakeDdbTable(rows=[row]))
    monkeypatch.setattr(vitals, "_get_profile", lambda: {})
    b = _body(vitals.handle_journey_timeline())
    assert all(e["date"] >= start for e in b["events"])
    assert not any("straggler" in e["title"] for e in b["events"])


def test_journey_timeline_inert_when_genesis_past(monkeypatch):
    # Post-boundary (Day 1 onward): genesis == clamped bound, so the anchor keeps
    # its historical date and the filter admits everything from genesis forward.
    start = _past(monkeypatch, days=30)
    d20 = _iso(_today_pt() - timedelta(days=20))
    row = {
        "pk": f"{vitals.USER_PREFIX}experiments",
        "sk": "EXP#real",
        "start_date": d20,
        "status": "active",
        "name": "Mid-cycle experiment",
        "hypothesis": "runs normally after genesis",
    }
    monkeypatch.setattr(vitals, "table", FakeDdbTable(rows=[row]))
    monkeypatch.setattr(vitals, "_get_profile", lambda: {})
    b = _body(vitals.handle_journey_timeline())
    day1 = [e for e in b["events"] if e["title"] == "Day 1"]
    assert len(day1) == 1
    assert day1[0]["date"] == start
    assert any("Mid-cycle experiment" in e["title"] for e in b["events"])
