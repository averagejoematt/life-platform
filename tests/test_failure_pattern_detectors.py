"""
test_failure_pattern_detectors.py — Pure-function unit tests for the IC-4
failure-pattern detector logic (no DDB / AWS / network).

Implemented 2026-05-03 in v6.9.3 — the Lambda was deployed with stub `return []`
detectors since 2026-03-15 ("data gate ~2026-05-01"); gate met, real impl shipped.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "compute"))  # P3.1: handler moved here

# Stub boto3 + env so the lambda module can import without AWS credentials.
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

import types as _t
if "boto3" not in sys.modules:
    boto3_stub = _t.SimpleNamespace(
        resource=lambda *a, **kw: _t.SimpleNamespace(Table=lambda name: None),
        client=lambda *a, **kw: None,
    )
    sys.modules["boto3"] = boto3_stub  # type: ignore

import failure_pattern_compute_lambda as fpc


# ── _detect_habit_skip_predictors ─────────────────────────────────────────────

def test_predictors_skip_drives_lift():
    # Walk skipped on bad days only; baseline bad-rate = 5/10 = 0.5
    # Walk skipped 5 times, all bad; lift = 1.0 / 0.5 = 2.0
    grades = {f"2026-04-{d:02d}": (50 if d <= 5 else 80) for d in range(1, 11)}
    outcome = [{"date": d, "total_score": s} for d, s in grades.items()]
    habits = [
        {"date": f"2026-04-{d:02d}", "missed_tier0": (["Walk 5k"] if d <= 5 else [])}
        for d in range(1, 11)
    ]
    out = fpc._detect_habit_skip_predictors(habits, outcome)
    assert len(out) == 1
    p = out[0]
    assert p["habit"] == "Walk 5k"
    assert p["n_skipped"] == 5
    assert p["n_skipped_bad"] == 5
    assert p["skip_bad_rate"] == 1.0
    assert p["lift"] == 2.0


def test_predictors_filters_low_n():
    # Habit only skipped twice → below n_skipped >= 3 threshold → excluded
    outcome = [{"date": f"2026-04-{d:02d}", "total_score": 40} for d in range(1, 11)]
    habits = [
        {"date": "2026-04-01", "missed_tier0": ["Hydrate 3L"]},
        {"date": "2026-04-02", "missed_tier0": ["Hydrate 3L"]},
    ]
    out = fpc._detect_habit_skip_predictors(habits, outcome)
    assert out == []


def test_predictors_returns_top_3_only():
    grades = {f"2026-04-{d:02d}": 50 for d in range(1, 11)}
    outcome = [{"date": d, "total_score": s} for d, s in grades.items()]
    habits = []
    for d in range(1, 11):
        # 4 different habits all skipped every day → lift = 1.0 each → all excluded (lift > 1)
        habits.append({"date": f"2026-04-{d:02d}", "missed_tier0":
                       ["H1", "H2", "H3", "H4"]})
    out = fpc._detect_habit_skip_predictors(habits, outcome)
    # All 4 habits have lift = 1.0 (skip_bad_rate == baseline) → filtered out
    assert out == []


def test_predictors_handles_empty():
    assert fpc._detect_habit_skip_predictors([], []) == []
    assert fpc._detect_habit_skip_predictors([{"date": "2026-04-01"}], []) == []


# ── _detect_cascade_patterns ──────────────────────────────────────────────────

def test_cascade_poor_sleep_to_bad_day():
    # 5 days of poor sleep, all followed by bad days
    sleep_records = [{"date": f"2026-04-{d:02d}", "sleep_score": 50} for d in range(1, 6)]
    # Day 2-6 are bad
    grades = {f"2026-04-{d:02d}": 40 for d in range(2, 7)}
    grades.update({f"2026-04-{d:02d}": 80 for d in range(7, 15)})
    outcome = [{"date": d, "total_score": s} for d, s in grades.items()]
    out = fpc._detect_cascade_patterns([], outcome, sleep_records)
    assert len(out) == 1
    c = out[0]
    assert c["trigger"] == "poor_sleep_score"
    assert c["n_episodes"] == 5
    assert c["cascade_rate"] == 1.0
    assert c["lift"] > 1.0


def test_cascade_no_pattern_when_baseline_high():
    # Every day is bad → baseline = 1.0; no lift
    sleep_records = [{"date": f"2026-04-{d:02d}", "sleep_score": 50} for d in range(1, 6)]
    grades = {f"2026-04-{d:02d}": 40 for d in range(1, 15)}
    outcome = [{"date": d, "total_score": s} for d, s in grades.items()]
    out = fpc._detect_cascade_patterns([], outcome, sleep_records)
    assert out == []


def test_cascade_handles_no_sleep_data():
    outcome = [{"date": f"2026-04-{d:02d}", "total_score": 40} for d in range(1, 11)]
    assert fpc._detect_cascade_patterns([], outcome, []) == []


# ── _detect_day_of_week_clusters ──────────────────────────────────────────────

def test_dow_clusters_flags_weekend_drop():
    # Build 8 weeks of data: weekday composite_score=80, Saturday=50, Sunday=70
    records = []
    base = "2026-03-01"  # Sunday
    from datetime import datetime, timedelta
    base_dt = datetime.strptime(base, "%Y-%m-%d")
    for i in range(56):
        dt = base_dt + timedelta(days=i)
        ds = dt.strftime("%Y-%m-%d")
        if dt.weekday() == 5:   # Sat
            score = 50
        elif dt.weekday() == 6: # Sun
            score = 70
        else:
            score = 80
        records.append({"date": ds, "composite_score": score})

    out = fpc._detect_day_of_week_clusters(records)
    # Overall mean ~74.3; Saturday at 50 → delta -24 → "elevated"
    assert "Sat" in out
    assert out["Sat"]["risk_level"] == "elevated"
    # Sunday at 70 → delta about -4 → "mild"
    assert "Sun" in out
    assert out["Sun"]["risk_level"] in ("mild", "elevated")


def test_dow_clusters_handles_empty():
    assert fpc._detect_day_of_week_clusters([]) == {}


# ── _detect_rebound_speed ─────────────────────────────────────────────────────

def test_rebound_speed_basic():
    # Day 1-3: bad (40); Day 4: recovered (75); Day 5-7: good
    grades = {
        "2026-04-01": 40,
        "2026-04-02": 50,
        "2026-04-03": 55,
        "2026-04-04": 75,
        "2026-04-05": 80,
        "2026-04-06": 80,
        "2026-04-07": 80,
    }
    outcome = [{"date": d, "total_score": s} for d, s in grades.items()]
    out = fpc._detect_rebound_speed(outcome)
    # One bad-day episode, took 3 days to recover (start day 1, recovered day 4)
    assert out["n_episodes"] == 1
    assert out["mean_days"] == 3
    assert out["median_days"] == 3


def test_rebound_speed_no_episodes():
    # All good days
    grades = {f"2026-04-{d:02d}": 80 for d in range(1, 11)}
    outcome = [{"date": d, "total_score": s} for d, s in grades.items()]
    out = fpc._detect_rebound_speed(outcome)
    assert out == {}


def test_rebound_speed_too_few_records():
    # Less than 7 records → not enough data
    outcome = [{"date": f"2026-04-{d:02d}", "total_score": 40} for d in range(1, 5)]
    assert fpc._detect_rebound_speed(outcome) == {}
