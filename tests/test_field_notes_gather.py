"""tests/test_field_notes_gather.py — the training gatherer reads the real Strava record shape.

Replays the 2026-W26 live bug: Strava items are DAY rollups (activity_count,
total_moving_time_seconds, activities[]), but the gatherer summed the
per-activity field `moving_time_seconds` off the day record — always 0 — so the
published field note read "4 sessions logged but zero total minutes recorded"
and the AI publicly flagged its own pipeline as broken.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "intelligence"))

import field_notes_lambda as fnl  # noqa: E402

# The real stored shape (see strava_lambda.transform, lines ~297-310).
_DAY_RECORDS = [
    {
        "pk": "USER#matthew#SOURCE#strava",
        "sk": "DATE#2026-06-23",
        "activity_count": 2,
        "total_moving_time_seconds": 4980,  # 83 min
        "activities": [
            {"name": "Morning Walk", "moving_time_seconds": 2700},
            {"name": "Evening Walk", "moving_time_seconds": 2280},
        ],
    },
    {
        "pk": "USER#matthew#SOURCE#strava",
        "sk": "DATE#2026-06-25",
        "activity_count": 1,
        "total_moving_time_seconds": 3600,  # 60 min
        "activities": [{"name": "Ruck", "moving_time_seconds": 3600}],
    },
]


class _NoAwsTable:
    """gather_week_data queries the journal (and _latest_item the character sheet)
    DIRECTLY on `table`, not via _query_source — unstubbed, these tests silently
    queried PROD DynamoDB when local creds existed and died in CI on the invalid
    token (the live-coupled-test trap). Hermetic now: every direct read is empty."""

    def query(self, **_kw):
        return {"Items": []}

    def get_item(self, **_kw):
        return {}


def _gather_with(records, monkeypatch):
    monkeypatch.setattr(fnl, "table", _NoAwsTable())
    monkeypatch.setattr(fnl, "_query_source", lambda src, s, e: records if src == "strava" else [])
    return fnl.gather_week_data("2026-06-22", "2026-06-28")


def test_training_minutes_from_day_rollups(monkeypatch):
    data = _gather_with(_DAY_RECORDS, monkeypatch)
    assert data["training"]["total_minutes"] == 143  # 83 + 60, never 0
    assert data["training"]["sessions"] == 3  # activity_count sum, not len(day records)


def test_training_falls_back_to_activities_list(monkeypatch):
    legacy = [
        {
            "sk": "DATE#2026-06-24",
            "activities": [{"moving_time_seconds": 1800}, {"elapsed_time_seconds": 600}],
        }
    ]
    data = _gather_with(legacy, monkeypatch)
    assert data["training"]["total_minutes"] == 40
    assert data["training"]["sessions"] == 2


def test_training_omitted_when_no_records(monkeypatch):
    data = _gather_with([], monkeypatch)
    assert "training" not in data


# The whoop partition also stores DATE#<day>#WORKOUT#<uuid> sub-records — counting
# them as nights produced "20 nights of sleep in one week", which the regenerated
# W26 note then flagged as a tracking error in its own data (2026-07-02).
_WHOOP_RECORDS = [
    {"sk": "DATE#2026-06-22", "sleep_duration_hours": 7.5, "hrv": 44.0},
    {"sk": "DATE#2026-06-22#WORKOUT#53900157-2526-4bcb-be21-80a07f56adea", "strain": 12.1},
    {"sk": "DATE#2026-06-23", "sleep_duration_hours": 7.9, "hrv": 44.2},
    {"sk": "DATE#2026-06-23#WORKOUT#230994b0-a21e-4071-8f0f-00a18b8c4dee", "strain": 9.4},
    {"sk": "DATE#2026-06-23#WORKOUT#28a877e8-676d-4a17-b64b-8c90a97686c0", "strain": 6.2},
]


def test_sleep_nights_count_day_records_only(monkeypatch):
    monkeypatch.setattr(fnl, "table", _NoAwsTable())
    monkeypatch.setattr(fnl, "_query_source", lambda src, s, e: _WHOOP_RECORDS if src == "whoop" else [])
    data = fnl.gather_week_data("2026-06-22", "2026-06-28")
    assert data["sleep"]["nights"] == 2  # never 5 — workout sub-records aren't nights
    assert data["sleep"]["avg_hours"] == 7.7


def test_day_record_filter_shape():
    assert fnl._DAY_SK_RE.match("DATE#2026-06-22")
    assert not fnl._DAY_SK_RE.match("DATE#2026-06-22#WORKOUT#abc")
    assert not fnl._DAY_SK_RE.match("YEAR#2026")
