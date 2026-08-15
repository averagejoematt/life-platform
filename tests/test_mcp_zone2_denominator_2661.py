"""#2661 — the zone-2 adherence denominator was "weeks I trained", not "weeks I asked about".

`weekly` is a defaultdict keyed by activity, so a week with no qualifying activity never
existed as a key, and `n_weeks = len(weekly_sorted)` counted ACTIVE weeks. A missed week
therefore vanished from the denominator instead of lowering the rate — the exact opposite
of what an adherence number is for.

Measured against the deployed `life-platform-mcp` Lambda on 2026-08-15, BEFORE the fix:

    get_zone2_breakdown {}
      -> period 2026-05-18 .. 2026-08-15   (13 calendar weeks)
         weeks_analyzed: 1                 (1 qualifying activity in the whole window)

Every rate in that response divided by 1. With 150 zone-2 minutes in a single week out of
thirteen, `avg_weekly_zone_2_min` reports 150 against a 150 target and
`target_hit_rate_pct` reports 100 — a perfect score for training once in three months.
The one number a longevity-training tracker exists to produce.

ADR-105: the denominator is now calendar weeks in the requested window, and the response
says so (`denominator`, `active_weeks`, `zero_activity_weeks`). A window rarely starts on
a Monday, so `partial_weeks` names the first/last week when it is not wholly inside the
window rather than quietly rounding in either direction.

THE SECOND HALF — a target of 0. `target_met` was `z2 >= weekly_target_min`, so with a
target of zero every week qualified, including the empty ones, and the tool reported a
100% hit rate against a target nobody set. It is not that the target was met; the question
is not answerable. `target_hit_rate_pct` is now None with `target_applicable: false` and a
note saying why — and the deficit alerts are suppressed too, since "0 min target (-N min
shortfall)" is the same nonsense in prose.

These are unit tests over `tool_get_zone2_breakdown` with `query_source` and `get_profile`
replaced. The activity fixture is what makes them real: one 150-minute zone-2 session in a
thirteen-week window is the shape that produced the live 100%.
"""

from __future__ import annotations

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

import pytest  # noqa: E402

from mcp import tools_correlation as tc  # noqa: E402

MAX_HR = 190.0
# Zone 2 is 0.60–0.70 of max HR in HR_ZONE_BOUNDS: 114–133 bpm at max 190.
Z2_HR = 120.0

# A thirteen-week window (2026-05-18 is a Monday; 2026-08-16 is the Sunday 13 weeks on).
START, END = "2026-05-18", "2026-08-16"
THIRTEEN = 13


def _day(date, minutes, hr=Z2_HR):
    return {
        "date": date,
        "activities": [{"moving_time_seconds": minutes * 60, "average_heartrate": hr, "sport_type": "Ride", "name": "ride"}],
    }


@pytest.fixture(autouse=True)
def _no_aws(monkeypatch):
    monkeypatch.setattr(tc, "get_profile", lambda: {"max_heart_rate": MAX_HR})


def _run(days, monkeypatch, **args):
    monkeypatch.setattr(tc, "query_source", lambda *a, **k: list(days))
    return tc.tool_get_zone2_breakdown({"start_date": START, "end_date": END, **args})


# ── the live shape: one good week in thirteen ────────────────────────────────


ONE_GOOD_WEEK = [_day("2026-05-20", 150)]


def test_the_denominator_is_calendar_weeks_not_active_weeks(monkeypatch):
    out = _run(ONE_GOOD_WEEK, monkeypatch)
    assert out["summary"]["weeks_analyzed"] == THIRTEEN, "pre-fix this was 1 — the single week that had data"
    assert out["summary"]["active_weeks"] == 1
    assert out["summary"]["zero_activity_weeks"] == THIRTEEN - 1


def test_one_perfect_week_in_thirteen_is_not_a_100_percent_hit_rate(monkeypatch):
    """The issue's headline. Pre-fix: 100. Hand-derived: 1/13 = 7.69 -> 8."""
    out = _run(ONE_GOOD_WEEK, monkeypatch)["summary"]
    assert out["weeks_meeting_target"] == 1
    assert out["target_hit_rate_pct"] == 8, f"1 of 13 weeks met the target: {out['target_hit_rate_pct']}"


def test_the_weekly_average_is_diluted_by_the_weeks_with_no_training(monkeypatch):
    """Pre-fix: 150.0 (150/1). Hand-derived: 150/13 = 11.538 -> 11.5."""
    assert _run(ONE_GOOD_WEEK, monkeypatch)["summary"]["avg_weekly_zone_2_min"] == 11.5


def test_adding_a_zero_activity_week_lowers_the_rate(monkeypatch):
    """Acceptance box 3, stated as a comparison rather than a remembered constant."""
    narrow = _run(ONE_GOOD_WEEK, monkeypatch, start_date="2026-05-18", end_date="2026-05-24")["summary"]
    wide = _run(ONE_GOOD_WEEK, monkeypatch)["summary"]
    assert narrow["weeks_analyzed"] == 1 and narrow["target_hit_rate_pct"] == 100
    assert wide["target_hit_rate_pct"] < narrow["target_hit_rate_pct"]
    assert wide["avg_weekly_zone_2_min"] < narrow["avg_weekly_zone_2_min"]


def test_every_calendar_week_appears_in_the_weekly_breakdown(monkeypatch):
    """The denominator and the rows must be the same set, or one of them is lying."""
    out = _run(ONE_GOOD_WEEK, monkeypatch)
    assert len(out["weekly_breakdown"]) == THIRTEEN
    empty = [w for w in out["weekly_breakdown"] if w["activity_count"] == 0]
    assert len(empty) == THIRTEEN - 1
    assert all(w["zone_2_minutes"] == 0 and w["target_met"] is False for w in empty)


# ── ADR-105: the response states what it counted ─────────────────────────────


def test_the_response_names_its_denominator(monkeypatch):
    out = _run(ONE_GOOD_WEEK, monkeypatch)["summary"]
    assert out["denominator"] == "calendar weeks in the requested window"
    assert out["weeks_analyzed"] == out["active_weeks"] + out["zero_activity_weeks"]


def test_a_partial_week_at_either_end_is_named_not_rounded_away(monkeypatch):
    """2026-05-20 is a Wednesday, so the first week is partial and the last is too."""
    out = _run(ONE_GOOD_WEEK, monkeypatch, start_date="2026-05-20", end_date="2026-06-04")["summary"]
    assert out["partial_weeks"], "a window that starts mid-week must say so"
    assert all(isinstance(w, str) for w in out["partial_weeks"])


def test_a_window_aligned_to_whole_weeks_reports_no_partial_weeks(monkeypatch):
    """The control — Monday 2026-05-18 through Sunday 2026-08-16 is 13 whole weeks."""
    assert _run(ONE_GOOD_WEEK, monkeypatch)["summary"]["partial_weeks"] == []


# ── the second half: a target of zero ────────────────────────────────────────


def test_a_target_of_zero_is_not_a_100_percent_hit_rate(monkeypatch):
    """`z2 >= 0` was True for every week, empty ones included."""
    out = _run(ONE_GOOD_WEEK, monkeypatch, weekly_target_minutes=0)["summary"]
    assert out["target_hit_rate_pct"] is None, f"a target of 0 reported {out['target_hit_rate_pct']}"
    assert out["target_applicable"] is False
    assert "not defined" in out["target_note"]
    assert out["weeks_meeting_target"] is None


@pytest.mark.parametrize("target", [0, -50])
def test_a_non_positive_target_suppresses_the_deficit_prose_too(monkeypatch, target):
    """ "0 min target (-N min shortfall)" is the same nonsense written out."""
    out = _run(ONE_GOOD_WEEK, monkeypatch, weekly_target_minutes=target)
    assert not [a for a in out["alerts"] if "shortfall" in a], out["alerts"]


def test_a_non_positive_target_leaves_the_per_week_verdict_unanswered(monkeypatch):
    out = _run(ONE_GOOD_WEEK, monkeypatch, weekly_target_minutes=0)
    assert all(w["target_met"] is None and w["target_pct"] is None for w in out["weekly_breakdown"])


# ── the controls: the honest cases must be unchanged ─────────────────────────


def test_a_real_target_still_produces_a_verdict_and_a_deficit_alert(monkeypatch):
    out = _run(ONE_GOOD_WEEK, monkeypatch)
    assert out["summary"]["target_applicable"] is True
    assert out["summary"]["target_note"] is None
    assert [a for a in out["alerts"] if "shortfall" in a], "11.5 min/week against a 150 target is a deficit"


def test_a_fully_adherent_window_still_reports_100(monkeypatch):
    """A denominator fix that can never reach 100% would be a different bug."""
    days = [_day(d, 150) for d in ("2026-05-18", "2026-05-25", "2026-06-01")]
    out = _run(days, monkeypatch, start_date="2026-05-18", end_date="2026-06-07")["summary"]
    assert out["weeks_analyzed"] == 3 and out["active_weeks"] == 3
    assert out["target_hit_rate_pct"] == 100
    assert out["avg_weekly_zone_2_min"] == 150.0


def test_total_zone_2_minutes_are_unchanged_by_the_denominator_fix(monkeypatch):
    """Totals are counts of what happened; only the RATES had the wrong divisor."""
    out = _run(ONE_GOOD_WEEK, monkeypatch)["summary"]
    assert out["total_zone_2_min"] == 150.0
    assert out["total_activities"] == 1
