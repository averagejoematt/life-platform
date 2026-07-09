"""tests/test_vitals_depth_421.py — the vitals-DEPTH endpoint (#421 / VIT-02/03/04, PHY-06).

Covers the three shipped panels (VO2max arc, walking HR, fitness age) and the two deferred
ones (hourly habits, vascular age). The hard rules under test:
  • real data only — a panel is available only when its source records genuinely exist;
  • gaps stay gaps — the VO2max series is returned sorted and un-gap-filled;
  • walking HR is Strava Walk activities WITH average_heartrate only (Runs / HR-less walks out);
  • Option A privacy — no chronological age (or age-gap) is ever served or derivable;
  • fitness age is a monotonic VO2max→age map with a personal-variance band.

Fixtures use OLD dates on purpose so the fitness-age recency filter deterministically falls back
to the most-recent handful — the estimate is then wall-clock-independent (no golden time bomb).
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import site_api_vitals_depth as vd  # noqa: E402


def _garmin_vo2(records):
    """records: list of (date, vo2). Live-shaped Garmin DDB rows."""
    return [{"sk": f"DATE#{d}", "date": d, "vo2_max": v, "resting_heart_rate": 55} for (d, v) in records]


def _strava_day(date, activities):
    return {"sk": f"DATE#{date}", "date": date, "activities": activities, "phase": "pilot"}


def _fake_query(garmin=None, strava=None):
    def _q(source, start, end, include_pilot=False):
        if source == "garmin":
            return list(garmin or [])
        if source == "strava":
            return list(strava or [])
        return []

    return _q


# ── VO2max arc ───────────────────────────────────────────────────────────────────────────────
def test_vo2max_arc_real_series_sorted_gaps_preserved(monkeypatch):
    # Fed out of order + a sparse gap; must come back sorted, un-gap-filled, real values only.
    garmin = _garmin_vo2([("2022-05-02", 44.8), ("2022-04-25", 45.6), ("2026-05-19", 33.3), ("2026-04-02", 30.8)])
    monkeypatch.setattr(vd, "_query_source", _fake_query(garmin=garmin))
    body = json.loads(vd.handle_vitals_depth()["body"])
    vo = body["vo2max"]
    assert vo["available"] is True
    assert vo["source"] == "Garmin"
    dates = [p["date"] for p in vo["series"]]
    assert dates == sorted(dates)  # chronological
    assert dates == ["2022-04-25", "2022-05-02", "2026-04-02", "2026-05-19"]  # no fabricated in-between days
    assert vo["n"] == 4
    assert vo["current"] == 33.3 and vo["as_of"] == "2026-05-19"
    assert vo["peak"] == 45.6
    assert vo["trend"] == "declining"  # 45.6 -> 33.3


def test_vo2max_absent_is_honest_empty(monkeypatch):
    monkeypatch.setattr(vd, "_query_source", _fake_query(garmin=[]))
    body = json.loads(vd.handle_vitals_depth()["body"])
    assert body["vo2max"]["available"] is False
    assert body["fitness_age"]["available"] is False  # nothing to map from


# ── Walking heart rate ───────────────────────────────────────────────────────────────────────
def test_walking_hr_only_walk_activities_with_hr(monkeypatch):
    strava = [
        _strava_day(
            "2026-07-06",
            [
                {"type": "Walk", "average_heartrate": 113.3, "max_heartrate": 123, "name": "Evening Walk"},
                {"type": "Run", "average_heartrate": 150.0},  # not a walk → excluded
                {"type": "Walk", "name": "No-HR Walk"},  # walk but no HR → excluded
            ],
        ),
        _strava_day("2026-07-05", [{"type": "Walk", "average_heartrate": 119.1, "max_heartrate": 141}]),
        _strava_day("2026-06-25", [{"sport_type": "Walk", "average_heartrate": 112.3}]),
        _strava_day("2026-06-20", [{"type": "Walk", "average_heartrate": 110.0}]),
    ]
    monkeypatch.setattr(vd, "_query_source", _fake_query(strava=strava))
    body = json.loads(vd.handle_vitals_depth()["body"])
    w = body["walking_hr"]
    assert w["available"] is True
    assert w["source"] == "Strava (Walk activities)"
    # exactly the 4 Walk activities that carried HR (Run + HR-less walk dropped)
    assert w["n_total"] == 4
    vals = [pt["value"] for pt in w["series"]]
    assert 150.0 not in vals  # the run never leaks in
    assert w["series"][-1]["value"] == 113.3  # latest walk


def test_walking_hr_absent_is_honest_empty(monkeypatch):
    monkeypatch.setattr(vd, "_query_source", _fake_query(strava=[]))
    body = json.loads(vd.handle_vitals_depth()["body"])
    assert body["walking_hr"]["available"] is False


# ── Fitness age (Option A privacy) ───────────────────────────────────────────────────────────
def test_fitness_age_mapping_is_monotonic():
    # Higher VO2max must map to a YOUNGER (lower) fitness age. Feeding VO2max in DESCENDING order
    # must therefore yield ages in ASCENDING order (strictly monotonic across the table interior).
    ages = [vd._fitness_age_for_vo2max(v) for v in (48, 45, 40, 33.3, 31, 25)]
    assert ages == sorted(ages)
    assert vd._fitness_age_for_vo2max(45) < vd._fitness_age_for_vo2max(31)
    assert vd._fitness_age_for_vo2max(48) <= 20.0  # clamps to youngest table age
    assert vd._fitness_age_for_vo2max(20) >= 80.0  # clamps to oldest table age
    assert vd._fitness_age_for_vo2max(None) is None


def test_fitness_age_estimate_has_band_and_n(monkeypatch):
    garmin = _garmin_vo2([("2022-04-25", 45.6), ("2026-04-02", 30.8), ("2026-04-03", 30.5), ("2026-05-19", 33.3)])
    monkeypatch.setattr(vd, "_query_source", _fake_query(garmin=garmin))
    fa = json.loads(vd.handle_vitals_depth()["body"])["fitness_age"]
    assert fa["available"] is True
    assert fa["range_low"] <= fa["estimate"] <= fa["range_high"]
    assert fa["range_high"] - fa["range_low"] >= 1  # a real band, never a bare point
    assert fa["n"] >= 3
    assert fa["citation"] and fa["method"]


def test_no_chronological_age_served_or_derivable(monkeypatch):
    """Option A: the entire payload must never carry chronological age, a DOB, or an age-gap."""
    garmin = _garmin_vo2([("2026-04-02", 30.8), ("2026-04-03", 30.5), ("2026-05-19", 33.3)])
    monkeypatch.setattr(vd, "_query_source", _fake_query(garmin=garmin))
    raw = vd.handle_vitals_depth()["body"].lower()
    for forbidden in ("chronological", "date_of_birth", '"dob"', "birth", "chrono", "age_gap", "real_age", "actual_age"):
        assert forbidden not in raw, f"privacy leak: {forbidden!r} present in payload"


# ── Deferred receipts (never faked) ──────────────────────────────────────────────────────────
def test_deferred_panels_carry_receipts(monkeypatch):
    monkeypatch.setattr(vd, "_query_source", _fake_query())
    body = json.loads(vd.handle_vitals_depth()["body"])
    panels = {d["panel"] for d in body["deferred"]}
    assert "hourly_habit_glyphs" in panels
    assert "vascular_age" in panels
    for d in body["deferred"]:
        assert d.get("reason")  # every deferral states why


def test_status_200_and_shape(monkeypatch):
    monkeypatch.setattr(vd, "_query_source", _fake_query())
    resp = vd.handle_vitals_depth()
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    for key in ("vo2max", "walking_hr", "fitness_age", "deferred"):
        assert key in body
