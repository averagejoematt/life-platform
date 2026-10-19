"""tests/test_steps_resolver_5081.py — the one daily-steps resolver (#5081).

The fixture is the WIRE: field-projected copies of six live DynamoDB days (read-only query,
2026-10-18) across Whoop, Apple Health, Strava and Hevy, loaded as Decimal (the boto3 type):

  2026-09-20  Whoop row has no step_count yet (vendor field from 09-21) -> the phone answers,
              `fallback`; the WHOOP walk sits inside a Hevy treadmill session -> de-duped to 0 min.
  2026-10-01  the phone (8,510.61) is ABOVE the wrist (3,420) — Whoop still wins (#4644 Q4).
  2026-10-05  the phone on a desk (1,255) vs the wrist (9,057); a Strava walk outside any session.
  2026-10-14  wrist 17,739 vs phone 13,157.82 (the #4628 delivered sum); one Garmin walk.
  2026-10-17  the watch's second day: wrist 17,866 vs phone 13,856; three Strava walks, two WHOOP
              walks inside the longer Garmin walk -> the #4068 de-dup removes them.
  2026-10-18  Whoop's cycle still open (no cycle_end, #5002) -> `partial_day`.
"""

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT))

for _k, _v in (("TABLE_NAME", "life-platform-test"), ("USER_ID", "matthew"), ("AWS_DEFAULT_REGION", "us-west-2")):
    os.environ.setdefault(_k, _v)

from common import metric_truth  # noqa: E402
from training import steps_resolver as sr  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "steps_resolver_5081" / "days.json"
DAYS = json.loads(FIX.read_text(), parse_float=Decimal, parse_int=Decimal)["days"]


def _day(d: str) -> dict:
    return dict(DAYS[d])


# ── the winner rule on real disagreeing days ──────────────────────────────────────────


REAL_DAYS = (
    # (day, steps, winner, degraded, the loser's value)
    ("2026-09-20", 3463, "apple_health", "fallback", None),
    ("2026-10-01", 3420, "whoop", None, 8510.61),
    ("2026-10-05", 9057, "whoop", None, 1255.0),
    ("2026-10-14", 17739, "whoop", None, 13157.82),
    ("2026-10-17", 17866, "whoop", None, 13856.0),
    ("2026-10-18", 6436, "whoop", "partial_day", 4719.36),
)


def test_real_days_resolve_to_one_named_winner():
    """Mutation: sum or max the sources, drop the losers, or let the phone win on a both-count day.
    One test over every real day (a parametrized test is one census gate per day); every offender reported."""
    bad = []
    for day, steps, winner, degraded, loser_value in REAL_DAYS:
        r = sr.resolve_daily_steps(day, _day(day))
        got = (r["steps"], r["winner"], r["degraded"], r["method"])
        if got != (steps, winner, degraded, "measured"):
            bad.append(f"{day}: {got}")
        losers = [(lo["source"], round(float(lo["value"]), 2), round(float(lo["delta_vs_winner"]), 2)) for lo in r["losers"]]
        want = [] if loser_value is None else [("apple_health", round(loser_value, 2), round(loser_value - steps, 2))]
        if losers != want:
            bad.append(f"{day}: losers {losers} != {want}")
        if set(r["candidates"]) != set(metric_truth.steps_sources()):
            bad.append(f"{day}: candidates {sorted(r['candidates'])}")
    assert not bad, bad


def test_phone_above_wrist_still_loses_the_owner_rule_is_rank_not_max():
    """2026-10-01: a max rule would pick the phone's 8,511 — the ruling is Whoop when both count."""
    r = sr.resolve_daily_steps("2026-10-01", _day("2026-10-01"))
    assert r["steps"] == 3420 and r["candidates"]["apple_health"] > r["steps"]


def test_no_source_is_null_never_zero():
    """ADR-104: nothing fetched, or nothing usable, is `steps: None` + `no_source` — never 0."""
    for rows in ({}, {"whoop": None, "apple_health": None}, {"whoop": {"sk": "DATE#2026-09-01", "date": "2026-09-01"}}):
        r = sr.resolve_daily_steps("2026-09-01", rows)
        assert r["steps"] is None and r["winner"] is None and r["degraded"] == "no_source" and r["method"] is None
    assert sr.summarize([sr.resolve_daily_steps("2026-09-01", {})])["mean_steps"] is None


def test_a_zero_report_is_a_reading_only_when_nothing_counted():
    r = sr.resolve_daily_steps("2026-09-02", {"whoop": {"step_count": Decimal("0")}, "apple_health": None})
    assert r["steps"] == 0 and r["winner"] == "whoop" and r["degraded"] is None
    r = sr.resolve_daily_steps("2026-10-14", {**_day("2026-10-14"), "whoop": {"step_count": Decimal("0")}})
    assert r["winner"] == "apple_health" and r["degraded"] == "fallback"


# ── Strava walks: DERIVED, labelled, never merged ─────────────────────────────────────


def test_strava_walk_outside_a_session_is_a_derived_estimate_never_merged():
    """Mutation: add the derived estimate into `steps`, or drop the DERIVED label."""
    r = sr.resolve_daily_steps("2026-10-05", _day("2026-10-05"))
    d = r["derived"][sr.DERIVED_KEY]
    assert d["status"] == "read" and d["walking_minutes"] == pytest.approx(71.4, abs=0.1)
    est = d["estimate"]
    assert est["measured"] is False and est["label"] == "DERIVED" and est["never_merge_into"] == "steps"
    assert est["value"] == 7140
    assert r["steps"] == 9057  # the wrist count, untouched by the walk estimate


def test_walk_inside_a_hevy_session_and_two_devices_on_one_walk_count_once():
    """09-20: the WHOOP walk is inside a Hevy treadmill session; 10-17: two WHOOP walks inside a Garmin walk."""
    d = sr.resolve_daily_steps("2026-09-20", _day("2026-09-20"))["derived"][sr.DERIVED_KEY]
    assert d["walking_minutes"] == 0.0 and d["hevy_read_for_dedup"] is True
    d = sr.resolve_daily_steps("2026-10-17", _day("2026-10-17"))["derived"][sr.DERIVED_KEY]
    assert d["walking_minutes"] == pytest.approx(168.3, abs=0.5)  # the Garmin walk's moving time, not + the WHOOP pair
    assert d["dedup_minutes_removed_all_modalities"] > 60


def test_strava_not_read_is_no_derived_block():
    rows = {k: v for k, v in _day("2026-10-14").items() if k not in ("strava", "hevy")}
    assert sr.resolve_daily_steps("2026-10-14", rows)["derived"][sr.DERIVED_KEY] is None


# ── watch slot: the claim is tied to the watch map, so it cannot go stale ─────────────


def test_watch_slot_reported_and_still_true():
    """Mutation: map a watch steps field without moving it into METRIC_TRUTH (the slot would lie)."""
    from ingestion.health_auto_export_watch import WATCH_METRIC_DEFS

    fields = [cfg["field"] for _names, cfg in WATCH_METRIC_DEFS]
    assert not [f for f in fields if "step" in f], "a watch steps field exists — add it to METRIC_TRUTH['steps'] and remove WATCH_SLOT"
    r = sr.resolve_daily_steps("2026-10-17", _day("2026-10-17"))
    assert r["slots"]["apple_watch"]["status"] == "not_stored"
    assert "apple_watch" not in r["candidates"]


def test_whoop_is_a_steps_source_with_its_own_field():
    facet = metric_truth.metric_truth(metric_truth.STEPS)
    assert facet["truth_source"] == "whoop" and facet["field_by_source"]["whoop"] == "step_count"
    assert "pending" not in facet["ruling"]


# ── no second derivation ──────────────────────────────────────────────────────────────


def test_resolver_delegates_the_pick_to_metric_truth(monkeypatch):
    """Mutation: re-implement the precedence here instead of calling the registry-driven resolver."""
    seen = []
    orig = metric_truth.resolve_steps
    monkeypatch.setattr(metric_truth, "resolve_steps", lambda rows: (seen.append(rows), orig(rows))[1])
    sr.resolve_daily_steps("2026-10-14", _day("2026-10-14"))
    assert seen and set(seen[0]) <= set(metric_truth.steps_sources())
    src = (ROOT / "lambdas" / "training" / "steps_resolver.py").read_text()
    for literal in ('"step_count"', '"whoop"', '"apple_health"', '"garmin"'):
        assert literal not in src, f"the precedence belongs in METRIC_TRUTH, not {literal}"


# ── the range reader ──────────────────────────────────────────────────────────────────


def _fetch_from_fixture(source, start, end):
    out = []
    for d, day in DAYS.items():
        if start <= d <= end:
            v = day.get(source)
            out.extend(v if isinstance(v, list) else ([v] if v else []))
    return out


def test_steps_range_resolves_every_day_including_absent_ones():
    out = sr.steps_range("2026-10-13", "2026-10-18", fetch=_fetch_from_fixture)
    by = {d["date"]: d for d in out["days"]}
    assert list(by) == ["2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-17", "2026-10-18"]
    assert by["2026-10-13"]["degraded"] == "no_source" and by["2026-10-13"]["steps"] is None
    assert by["2026-10-14"]["steps"] == 17739 and by["2026-10-14"]["derived"][sr.DERIVED_KEY]["status"] == "read"
    s = out["summary"]
    assert s["days"] == 6 and s["days_measured"] == 3
    assert s["mean_steps"] == round((17739 + 17866 + 6436) / 3)
    assert s["wins_by_source"] == {"whoop": 3} and s["degraded_days"] == {"no_source": 3, "partial_day": 1}
    assert "Whoop" in out["rule"] and "DERIVED" in out["rule"]


def test_daily_steps_reads_through_the_range():
    assert sr.daily_steps("2026-09-20", fetch=_fetch_from_fixture)["winner"] == "apple_health"
    r = sr.daily_steps("2026-09-20", fetch=_fetch_from_fixture, derived=False)
    assert r["derived"][sr.DERIVED_KEY] is None
