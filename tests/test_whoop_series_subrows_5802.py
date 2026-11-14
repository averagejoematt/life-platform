"""#5802: the Whoop partition holds `DATE#<day>#WORKOUT#<id>` sub-rows beside each daily row. `whoop_series` keyed
both by the day, so a workout row (no sleep, no RHR) overwrote the daily row and the `sleep` tripwire and the RHR
stop line read unknown on every training day. The fixture is the live partition's shape: sub-rows sort AFTER the daily row."""

import os

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from mcp.nutrition_critics_inputs import whoop_series  # noqa: E402

KEYS = ["2026-01-05", "2026-01-06", "2026-01-07"]


def _partition():
    return [
        {"sk": "DATE#2026-01-05", "sleep_duration_hours": 7.5, "resting_heart_rate": 55},
        {"sk": "DATE#2026-01-05#WORKOUT#aaaa", "strain": 9.1},
        {"sk": "DATE#2026-01-05#WORKOUT#bbbb", "strain": 4.0},
        {"sk": "DATE#2026-01-06", "sleep_duration_hours": 6.0, "resting_heart_rate": 57},
        {"sk": "DATE#2026-01-07#WORKOUT#cccc", "strain": 7.0},
    ]


def test_a_training_days_daily_row_survives_its_workout_sub_rows():
    assert whoop_series(_partition(), KEYS) == [7.5, 6.0, None]
    assert whoop_series(_partition(), KEYS, "resting_heart_rate") == [55.0, 57.0, None]


def test_a_day_with_only_workout_rows_is_unmeasured_not_borrowed():
    assert whoop_series(_partition(), ["2026-01-07"]) == [None]


def test_an_unreadable_partition_stays_none():
    assert whoop_series(None, KEYS) is None


def test_CONTROL_the_old_keying_loses_the_daily_row():
    """The defect, reproduced: last-row-wins on the 10-char day prefix reads a workout row for 01-05."""
    by_day = {str(r.get("sk") or "").replace("DATE#", "")[:10]: r for r in _partition()}
    assert by_day["2026-01-05"].get("sleep_duration_hours") is None
