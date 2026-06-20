"""
tests/test_di1_movement_integrity.py — regression net for WORKORDER DI-1
(movement data integrity & coach honesty guard).

The bug: the movement/sedentary computation joined only Strava for "did he train",
and the TSB training-stress signal derived purely from Strava kilojoules. With
Strava deliberately paused (402 paywall) and Garmin rate-limited, real Hevy
training days (Push/Pull/Legs/Engine 6/16–6/19) were stamped has_workout=false
and flagged sedentary, and TSB collapsed toward zero.

These tests assert the fix WITHOUT touching AWS:
  DI-1.2 — daily-metrics Hevy join (boolean) + Hevy-aware TSB (training signal).

Observed fixtures (2026-06-19, from the work order — do not re-derive):
  Hevy: Push 6/16 (27 sets, 104m), Pull 6/17 (22 sets, 106m),
        Legs 6/18 (17 sets, 108m), Engine 6/19 (30 sets, 151m).
  Apple steps over the window are low/blank; Strava last wrote 6/14 (paused).
"""

import os
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("DYNAMODB_TABLE", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

import mcp.tools_lifestyle as tl  # noqa: E402

# daily_metrics_compute_lambda makes boto3 calls at import; conftest puts
# lambdas/compute on the path. Guard-import so a path break skips, not errors.
try:
    import unittest.mock as _mock

    with _mock.patch("boto3.resource"), _mock.patch("boto3.client"):
        import daily_metrics_compute_lambda as dmc
    _DMC_OK = True
except Exception as _e:  # pragma: no cover
    _DMC_OK = False
    _DMC_ERR = str(_e)


def _hevy(date_str, set_count, duration_min):
    """A normalized Hevy workout record as stored under DATE#{date}#WORKOUT#{id}."""
    return {
        "date": date_str,
        "sk": f"DATE#{date_str}#WORKOUT#{date_str}-uid",
        "source": "hevy",
        "set_count": set_count,
        "duration_sec": duration_min * 60,
        "title": "Foundation",
    }


# ==============================================================================
# DI-1.2 — daily-metrics Hevy join (boolean: has_workout / sedentary)
# ==============================================================================

JUN = "2026-06-"
HEVY_4DAYS = [
    _hevy("2026-06-16", 27, 104),
    _hevy("2026-06-17", 22, 106),
    _hevy("2026-06-18", 17, 108),
    _hevy("2026-06-19", 30, 151),
]


def test_has_workout_true_with_hevy_low_steps(monkeypatch):
    """A Hevy lifting day with low steps + no Strava is has_workout=true, not sedentary."""

    def fake_sources(sources, start, end, *a, **k):
        return {
            # 444 steps, <200 active cal — would be 'sedentary' under the old Strava-only join
            "apple_health": [{"date": "2026-06-18", "steps": 444, "active_calories": 120}],
            "strava": [],  # paused
            "hevy": [_hevy("2026-06-18", 17, 108)],
        }

    monkeypatch.setattr(tl, "parallel_query_sources", fake_sources)
    out = tl.tool_get_movement_score({"start_date": "2026-06-01", "end_date": "2026-06-18"})

    row = next(r for r in out["daily"] if r["date"] == "2026-06-18")
    assert row["has_workout"] is True, row
    assert row.get("sedentary_flag") is not True, row
    assert "hevy" in row.get("workout_sources", []), row
    assert out["summary"]["sedentary_days"] == 0, out["summary"]


def test_no_sedentary_on_hevy_days_jun16_19(monkeypatch):
    """Re-running movement over 6/16–6/19 (four Hevy sessions) yields 0 sedentary days."""

    def fake_sources(sources, start, end, *a, **k):
        return {
            # The real low/blank Apple step pattern from the work order
            "apple_health": [
                {"date": "2026-06-16", "steps": 402, "active_calories": 95},
                {"date": "2026-06-17", "steps": 1538, "active_calories": 110},
                {"date": "2026-06-18", "steps": 444, "active_calories": 120},
                {"date": "2026-06-19", "steps": 5712, "active_calories": 240},
            ],
            "strava": [],  # paused — last wrote 6/14
            "hevy": HEVY_4DAYS,
        }

    monkeypatch.setattr(tl, "parallel_query_sources", fake_sources)
    out = tl.tool_get_movement_score({"start_date": "2026-06-01", "end_date": "2026-06-19"})

    assert out["summary"]["sedentary_days"] == 0, out["summary"]
    for d in ("2026-06-16", "2026-06-17", "2026-06-18", "2026-06-19"):
        row = next(r for r in out["daily"] if r["date"] == d)
        assert row["has_workout"] is True, row
        assert row.get("sedentary_flag") is not True, row


def test_hevy_only_day_appears_when_no_apple_record(monkeypatch):
    """A Hevy training day with NO Apple Health record still surfaces as has_workout."""

    def fake_sources(sources, start, end, *a, **k):
        return {
            "apple_health": [{"date": "2026-06-16", "steps": 6000, "active_calories": 300}],
            "strava": [],
            "hevy": [_hevy("2026-06-18", 17, 108)],  # no apple record this day
        }

    monkeypatch.setattr(tl, "parallel_query_sources", fake_sources)
    out = tl.tool_get_movement_score({"start_date": "2026-06-01", "end_date": "2026-06-18"})

    row = next((r for r in out["daily"] if r["date"] == "2026-06-18"), None)
    assert row is not None, "Hevy-only day must not silently vanish"
    assert row["has_workout"] is True, row


# ==============================================================================
# DI-1.2 — Hevy-aware TSB (training-stress signal)
# ==============================================================================


@pytest.mark.skipif(not _DMC_OK, reason="daily_metrics_compute_lambda unavailable")
def test_tsb_nonzero_from_hevy_when_strava_off():
    """With Strava off (no kJ), recent Hevy sessions keep TSB nonzero instead of 0."""
    today = date(2026, 6, 20)
    hevy_60d = [
        _hevy("2026-06-16", 27, 104),
        _hevy("2026-06-17", 22, 106),
        _hevy("2026-06-18", 17, 108),
        _hevy("2026-06-19", 30, 151),
    ]

    # Regression baseline: Strava off + no Hevy = the broken behaviour (TSB pinned at 0).
    assert dmc.compute_tsb([], today) == 0.0

    # Fixed: Hevy fallback supplies load → TSB is nonzero (recent load → fatigued/negative).
    tsb = dmc.compute_tsb([], today, hevy_60d)
    assert tsb != 0.0, "Hevy-derived load must keep TSB nonzero when Strava is off"
    assert tsb < 0, f"four recent hard sessions → ATL>CTL → negative TSB, got {tsb}"

    basis = dmc.tsb_load_basis([], hevy_60d, today)
    assert basis["confidence"] == "hevy_fallback", basis
    assert basis["hevy_fallback_days"] == 4 and basis["strava_days"] == 0, basis


@pytest.mark.skipif(not _DMC_OK, reason="daily_metrics_compute_lambda unavailable")
def test_tsb_strava_authoritative_when_present():
    """When Strava has kJ for a day, it wins over the Hevy proxy (basis = strava/mixed)."""
    today = date(2026, 6, 20)
    strava_60d = [{"date": "2026-06-18", "activities": [{"kilojoules": 1800}]}]
    hevy_60d = [_hevy("2026-06-18", 17, 108)]  # same day — Strava must win

    basis = dmc.tsb_load_basis(strava_60d, hevy_60d, today)
    assert basis["strava_days"] == 1 and basis["hevy_fallback_days"] == 0, basis
    assert basis["confidence"] == "strava", basis


# ==============================================================================
# DI-1.3 — coach honesty guard (withhold under-training when movement unavailable)
# ==============================================================================

import importlib.util  # noqa: E402

_IC_SPEC = importlib.util.find_spec("intelligence_common")
_IC_OK = _IC_SPEC is not None
if _IC_OK:
    import intelligence_common as ic  # noqa: E402


@pytest.mark.skipif(not _IC_OK, reason="intelligence_common (shared layer) unavailable")
def test_coach_guard_withholds_undertraining_when_strava_paused():
    """A Hevy day + paused Strava: the position_summary must withhold the under-training
    verdict, name the unavailable source(s) + reason, and still reflect the Hevy session.

    This is the regression test that keeps Dr. Chen from relapsing into six days of
    "you're under-training" off a Hevy-blind, Strava-dead read.
    """
    state = {"strava": "paused", "garmin": "rate_limited", "steps": "missing"}
    assess = ic.movement_assessability(state)
    assert assess["assessable"] is False, assess

    # An LLM-generated summary that wrongly asserts under-training off the dead sources.
    raw = "Matthew is under-training — mostly rest days this week, very low training stimulus."
    guarded = ic.apply_movement_honesty_guard(raw, assess, hevy_present=True, hevy_summary="4 Hevy sessions, 96 sets, 469 min")

    low = guarded.lower()
    # 1. Verdict withheld — no under-training / sedentary / rest-day language survives.
    assert "under-train" not in low and "undertrain" not in low, guarded
    assert "sedentary" not in low, guarded
    assert "rest day" not in low and "low training stimulus" not in low, guarded
    # 2. Names the unavailable source(s) + reason.
    assert "strava: paused" in low, guarded
    assert "rate-limited" in low, guarded
    assert "not assessable" in low, guarded
    # 3. Still reflects the Hevy training that happened.
    assert "hevy" in low and "96 sets" in low, guarded


@pytest.mark.skipif(not _IC_OK, reason="intelligence_common (shared layer) unavailable")
def test_coach_guard_passes_through_when_strava_live():
    """When Strava is live the picture IS assessable — the guard must not touch the text."""
    assess = ic.movement_assessability({"strava": "live", "garmin": "rate_limited", "steps": "live"})
    assert assess["assessable"] is True, assess
    text = "Aerobic volume is light this week; consider one more Zone-2 session."
    assert ic.apply_movement_honesty_guard(text, assess, hevy_present=True) == text


@pytest.mark.skipif(not _IC_OK, reason="intelligence_common (shared layer) unavailable")
def test_coach_guard_noop_when_no_undertraining_assertion():
    """Not assessable, but the summary makes no under-training claim → leave it alone."""
    assess = ic.movement_assessability({"strava": "paused", "garmin": "stale", "steps": "missing"})
    text = "Hevy shows a clean PPL+Engine block — four sessions, strong set volume."
    assert ic.apply_movement_honesty_guard(text, assess, hevy_present=True) == text
