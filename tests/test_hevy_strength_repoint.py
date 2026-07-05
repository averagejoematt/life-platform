"""tests/test_hevy_strength_repoint.py — #485 dry-run proof.

The daily brief + weekly digest strength sections used to read the
macrofactor_workouts partition, which stopped ingesting ~4 months ago. Both
now read Hevy (the live, hourly-ingested strength source, ADR-060). These
tests feed synthetic Hevy per-workout records — the same shape
hevy_common.normalize_workout writes to DDB — through the new mapping/
extraction functions and all the way to rendered HTML, proving the "lifting
detail" shows up on a week that actually has lifts (the issue's acceptance
criterion #2).

No AWS credentials or network access required: DDB reads are monkeypatched.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "lambdas" / "emails"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")


def _hevy_record(date_str, title, exercise_sets):
    """One Hevy per-workout DDB record — matches hevy_common.normalize_workout's
    shape (sk=DATE#{date}#WORKOUT#{id}, weight stored in kg, one record per
    workout rather than one per day)."""
    exercises = [{"name": ex_name, "sets": [{"weight_kg": w_kg, "reps": reps} for (w_kg, reps) in sets]} for ex_name, sets in exercise_sets]
    return {
        "pk": "USER#matthew#SOURCE#hevy",
        "sk": f"DATE#{date_str}#WORKOUT#abc123",
        "source": "hevy",
        "source_workout_id": "abc123",
        "date": date_str,
        "title": title,
        "exercises": exercises,
        "exercise_count": len(exercises),
        "set_count": sum(len(s) for _, s in exercise_sets),
    }


_PUSH_DAY = _hevy_record(
    "2026-07-01",
    "Push Day",
    [
        ("Bench Press", [(100.0, 5), (100.0, 5), (100.0, 5)]),
        ("Overhead Press", [(50.0, 8), (50.0, 8)]),
    ],
)
_EXPECTED_VOLUME_LBS = round((100.0 * 5 * 3 + 50.0 * 8 * 2) / 0.45359237)
_EXPECTED_SETS = 5


# ══════════════════════════════════════════════════════════════════════════════
# weekly_digest_lambda: ex_hevy_workouts + query_range_list
# ══════════════════════════════════════════════════════════════════════════════


def test_weekly_digest_ex_hevy_workouts_maps_real_hevy_shape():
    import weekly_digest_lambda as m

    out = m.ex_hevy_workouts([_PUSH_DAY])
    assert out is not None
    assert out["workout_count"] == 1
    assert out["total_sets"] == _EXPECTED_SETS
    assert out["total_volume_lbs"] == _EXPECTED_VOLUME_LBS
    assert out["workouts"][0]["name"] == "Push Day"
    assert out["workouts"][0]["exercises"] == 2
    assert out["best_workout"]["name"] == "Push Day"


def test_weekly_digest_ex_hevy_workouts_empty_returns_none():
    import weekly_digest_lambda as m

    assert m.ex_hevy_workouts([]) is None
    assert m.ex_hevy_workouts(None) is None


def test_weekly_digest_ex_hevy_workouts_handles_two_a_day_same_date():
    """A day with two Hevy sessions must produce two workout entries, not one
    collapsed record — the reason query_range_list returns a flat list instead
    of query_range's {date: record} dict (which would silently drop one)."""
    import weekly_digest_lambda as m

    second = _hevy_record("2026-07-01", "Evening Mobility", [("Hip Flexor Stretch", [(0.0, 1)])])
    out = m.ex_hevy_workouts([_PUSH_DAY, second])
    assert out["workout_count"] == 2
    names = {w["name"] for w in out["workouts"]}
    assert names == {"Push Day", "Evening Mobility"}


def test_weekly_digest_query_range_list_boundary_includes_end_date_suffix():
    """Hevy's sk (DATE#{end}#WORKOUT#{id}) sorts after the plain "DATE#{end}"
    upper bound query_range uses — query_range_list's trailing '~' must still
    capture a workout logged exactly on the range's last day."""
    import weekly_digest_lambda as m

    fake_table = MagicMock()
    fake_table.query.return_value = {"Items": [_PUSH_DAY]}
    real_table = m.table
    m.table = fake_table
    try:
        out = m.query_range_list("hevy", "2026-06-25", "2026-07-01")
    finally:
        m.table = real_table
    assert len(out) == 1
    call_kwargs = fake_table.query.call_args.kwargs
    assert call_kwargs["ExpressionAttributeValues"][":e"] == "DATE#2026-07-01~"


def test_weekly_digest_strength_section_renders_with_hevy_data():
    """End-to-end: a week with real lifts renders "Strength Sessions" + the
    workout name in the weekly digest HTML (acceptance criterion #2)."""
    import weekly_digest_lambda as m

    def empty_packet(mf_workouts):
        return {
            "day_grades": None,
            "whoop": None,
            "sleep": None,
            "strava": m.ex_strava({}, {}),
            "apple": m.ex_apple_health({}),
            "macrofactor": m.ex_macrofactor({}, {}),
            "mf_workouts": mf_workouts,
            "withings": None,
            "habitify": m.ex_habitify({}, {}),
            "todoist": m.ex_todoist({}),
            "journal": m.ex_journal({}),
        }

    this = empty_packet(m.ex_hevy_workouts([_PUSH_DAY]))
    prior = empty_packet(None)
    data = {
        "this": this,
        "prior": prior,
        "training_load": {"atl": 40.0, "ctl": 45.0, "tsb": 5.0},
        "trends": {},
        "sleep_debt": {},
        "projection": {},
        "dates": {"this_start": "2026-06-25", "this_end": "2026-07-01"},
    }
    html = m.build_html(data, "", {"sleep_target_hours_ideal": 7.5, "goal_weight_lbs": 265})
    assert "Strength Sessions" in html
    assert "Push Day" in html


# ══════════════════════════════════════════════════════════════════════════════
# daily_brief_lambda: fetch_hevy_workouts
# ══════════════════════════════════════════════════════════════════════════════


def test_daily_brief_fetch_hevy_workouts_maps_real_hevy_shape(monkeypatch):
    import daily_brief_lambda as m

    fake_table = MagicMock()
    fake_table.query.return_value = {"Items": [_PUSH_DAY]}
    monkeypatch.setattr(m, "table", fake_table)

    out = m.fetch_hevy_workouts("2026-07-01")
    assert out is not None
    assert out["total_sets"] == _EXPECTED_SETS
    assert out["total_volume_lbs"] == pytest.approx(_EXPECTED_VOLUME_LBS, abs=0.5)
    assert out["workouts"][0]["workout_name"] == "Push Day"
    bench = out["workouts"][0]["exercises"][0]
    assert bench["exercise_name"] == "Bench Press"
    assert bench["sets"][0]["reps"] == 5
    assert bench["sets"][0]["weight_lbs"] == pytest.approx(220.5, abs=0.1)
    # Hevy reports RPE, not RIR (a different scale) — must not be mislabeled.
    assert "rir" not in bench["sets"][0]

    # The query used begins_with on the date (not fetch_date's exact-sk match,
    # which would silently return nothing for Hevy's #WORKOUT#-suffixed sk).
    call_kwargs = fake_table.query.call_args.kwargs
    assert "KeyConditionExpression" in call_kwargs


def test_daily_brief_fetch_hevy_workouts_no_data_returns_none(monkeypatch):
    import daily_brief_lambda as m

    fake_table = MagicMock()
    fake_table.query.return_value = {"Items": []}
    monkeypatch.setattr(m, "table", fake_table)
    assert m.fetch_hevy_workouts("2026-07-01") is None


def test_daily_brief_fetch_hevy_workouts_query_failure_fails_soft(monkeypatch):
    import daily_brief_lambda as m

    fake_table = MagicMock()
    fake_table.query.side_effect = RuntimeError("boom")
    monkeypatch.setattr(m, "table", fake_table)
    assert m.fetch_hevy_workouts("2026-07-01") is None


def test_daily_brief_training_report_renders_with_hevy_data():
    """End-to-end: html_builder's Training Report section (which the daily
    brief feeds mf_workouts into) renders the Hevy-derived shape correctly."""
    from html_builder import _brief_training_body

    mf_workouts = {
        "workouts": [
            {
                "workout_name": "Push Day",
                "exercises": [
                    {"exercise_name": "Bench Press", "sets": [{"reps": 5, "weight_lbs": 220.5}]},
                ],
            }
        ],
        "total_volume_lbs": _EXPECTED_VOLUME_LBS,
        "total_sets": _EXPECTED_SETS,
    }
    html = _brief_training_body(
        {"mf_workouts": mf_workouts},
        full_streak=0,
        mvp_streak=0,
        profile={},
        training_nutrition={},
    )
    assert "Push Day" in html
    assert "Bench Press" in html
    assert "section unavailable" not in html
