"""Tests for build_weekly_signal_data() in wednesday_chronicle_lambda.py"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambdas'))

# Set required env vars before import
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("CHRONICLE_SENDER", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "test@example.com")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("CHRONICLE_SENDER", "test@example.com")


def test_build_weekly_signal_data_basic():
    """Test that build_weekly_signal_data returns expected keys with mock data."""
    # Import from the Lambda file
    from wednesday_chronicle_lambda import build_weekly_signal_data

    data = {
        "profile": {"journey_start_date": "2026-04-01", "journey_start_weight_lbs": 302},
        "withings": {"weight_kg": 135.0},
        "whoop": {"recovery_score": 72, "hrv": 65, "sleep_efficiency_pct": 88},
        "sleep": {"sleep_duration_hours": 7.2},
        "strava": {"activities": [{"type": "Run"}, {"type": "Ruck"}]},
        "habits": {"tier0_completed": 8, "tier0_possible": 10},
        "day_grades": {"avg_score": 7.5},
    }

    result = build_weekly_signal_data(data, week_num=5)

    assert "weight_lbs" in result
    assert "avg_sleep_hours" in result
    assert "training_sessions" in result
    assert "habit_pct" in result
    assert "featured_member_id" in result
    assert "featured_observatory" in result
    assert result["training_sessions"] == 2
    assert result["habit_pct"] == 80
    assert result["avg_recovery_pct"] == 72
    assert result["avg_hrv_ms"] == 65


def test_build_weekly_signal_data_empty():
    """Test graceful handling of empty data."""
    from wednesday_chronicle_lambda import build_weekly_signal_data

    result = build_weekly_signal_data({}, week_num=1)

    assert result["weight_lbs"] is None
    assert result["training_sessions"] == 0
    assert result["habit_pct"] == 0
    assert result["featured_member_id"] is not None


def test_board_rotation_deterministic():
    """Test that board member rotation is deterministic."""
    from wednesday_chronicle_lambda import build_weekly_signal_data

    r1 = build_weekly_signal_data({}, week_num=1)
    r2 = build_weekly_signal_data({}, week_num=1)
    assert r1["featured_member_id"] == r2["featured_member_id"]

    # Different weeks should (usually) get different members
    r3 = build_weekly_signal_data({}, week_num=2)
    assert r3["featured_member_id"] != r1["featured_member_id"]


def test_observatory_rotation():
    """Test observatory rotation cycles through 7 pages."""
    from wednesday_chronicle_lambda import build_weekly_signal_data

    slugs = set()
    for w in range(1, 8):
        r = build_weekly_signal_data({}, week_num=w)
        slugs.add(r["featured_observatory"]["slug"])
    assert len(slugs) == 7
