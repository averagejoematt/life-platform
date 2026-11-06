"""tests/test_walking_completeness_2026_10_20.py — a signalled walk the layer did not count is named, never read as zero.

THE SPECIMEN

On 2026-10-20 a WHOOP-detected outdoor walk reached Strava (activity 20669407754), was
ingested, then vanished from Strava's list; the #4638 reconciler tombstoned the day and the
10-16..22 walking week read 7.95 h with `total_is_floor: False` and no honesty line. The WHOOP
workout and a completed "Walk Outdoor >2mi" habit both said he walked. The rows below are the
live WHOOP workout and habit status, field-projected.

EACH TEST NAMES THE MUTATION THAT REDS IT.
"""

from __future__ import annotations

from training import walking_volume as wv

DAY = "2026-10-20"

WHOOP_WALK = {
    "pk": "USER#matthew#SOURCE#whoop",
    "sk": "DATE#2026-10-20#WORKOUT#5f70ea18-0cf3-485c-8527-8c184b8423de",
    "date": DAY,
    "workout_id": "5f70ea18-0cf3-485c-8527-8c184b8423de",
    "sport_name": "walking",
    "start_time": "2026-10-20T23:09:23.734Z",
    "end_time": "2026-10-21T02:03:37.542Z",
    "zone_0_minutes": "113.03",
    "zone_1_minutes": "52.37",
    "zone_2_minutes": "5.72",
    "zone_3_minutes": "3.08",
    "zone_4_minutes": "0.03",
    "zone_5_minutes": "0",
}
WHOOP_DAY = {"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-10-20", "date": DAY, "recovery_score": 60}
HABIT_DAY = {
    "sk": "DATE#2026-10-20",
    "date": DAY,
    "habit_statuses": {
        "Walk Outdoor >2mi": {"aliases": ["Walk 5k"], "status": "completed"},
        "Cold Shower": {"status": "failed"},
    },
}
# The Strava day as it was ingested, before the vendor list dropped it.
STRAVA_DAY = {
    "date": DAY,
    "activities": [
        {
            "strava_id": "20669407754",
            "sport_type": "Walk",
            "device_name": "WHOOP",
            "start_date": "2026-10-20T23:09:23Z",
            "moving_time_seconds": 10454,
            "elapsed_time_seconds": 10454,
        }
    ],
}
OTHER_DAY_STRAVA = {
    "date": "2026-10-19",
    "activities": [{"sport_type": "Walk", "start_date": "2026-10-19T13:21:29Z", "moving_time_seconds": 2705, "elapsed_time_seconds": 2705}],
}


def _build(strava, hevy=None, inputs=None, start="2026-10-19", end=DAY):
    return wv.build(window_start=start, window_end=end, strava_items=strava, hevy_workouts=hevy or [], completeness_inputs=inputs)


def _signals(layer):
    return [(g["date"], g["signal"]) for g in layer["completeness"]["gaps"]]


def test_the_tombstoned_day_is_named_and_the_total_becomes_a_floor():
    """Mutation control: drop the `complete["gaps"]` term from `total_is_floor` — reds on the floor assert;
    drop the habit or WHOOP loop in `completeness` — reds on the signals."""
    layer = _build([OTHER_DAY_STRAVA], inputs={"whoop": [WHOOP_DAY, WHOOP_WALK], "habitify": [HABIT_DAY]})
    assert layer["total_hr"] == 0.75
    assert layer["total_is_floor"] is True
    assert _signals(layer) == [(DAY, "walk_habit_completed"), (DAY, "whoop_walk_workout")]
    assert any(h.startswith(DAY) and "floor" in h for h in layer["honesty"])


def test_a_signal_is_never_hours():
    """The WHOOP span (174 min) over-ran the walk; it is reported, never added to the total."""
    layer = _build([OTHER_DAY_STRAVA], inputs={"whoop": [WHOOP_WALK], "habitify": []})
    gap = layer["completeness"]["gaps"][0]
    assert gap["span_minutes"] == 174.2 and gap["zone_1_5_minutes"] == 61.2 and gap["counted"] is False
    assert layer["total_hr"] == 0.75


def test_a_counted_walk_over_the_same_minutes_clears_both_signals():
    """The day as ingested (Strava carrying the WHOOP walk) is complete. Mutation control: invert the
    overlap test — reds."""
    layer = _build([OTHER_DAY_STRAVA, STRAVA_DAY], inputs={"whoop": [WHOOP_WALK], "habitify": [HABIT_DAY]})
    assert _signals(layer) == []
    assert not any(h.startswith(DAY) for h in layer["honesty"])


def test_any_overlap_clears_an_over_run_whoop_walk():
    """A 52-min Apple-bounded walk inside the 174-min WHOOP span is the same walk, not a gap."""
    short = {**STRAVA_DAY, "activities": [{**STRAVA_DAY["activities"][0], "moving_time_seconds": 3120, "elapsed_time_seconds": 3120}]}
    layer = _build([short], inputs={"whoop": [WHOOP_WALK], "habitify": [HABIT_DAY]})
    assert _signals(layer) == []


def test_a_whoop_walk_inside_a_hevy_cardio_session_is_not_a_gap():
    """The #4068 class: WHOOP auto-detects the treadmill block inside a Hevy session."""
    hevy = [
        {
            "date": DAY,
            "start_time": "2026-10-20T23:00:00Z",
            "end_time": "2026-10-21T01:00:00Z",
            "exercises": [{"name": "Treadmill", "sets": [{"duration_sec": 3600}]}],
        }
    ]
    layer = _build([], hevy=hevy, inputs={"whoop": [WHOOP_WALK], "habitify": [HABIT_DAY]})
    assert _signals(layer) == []


def test_the_habit_matches_its_old_name_through_the_alias():
    renamed = {**HABIT_DAY, "habit_statuses": {"Walk 5k": {"status": "completed"}}}
    assert _signals(_build([], inputs={"whoop": [], "habitify": [renamed]})) == [(DAY, "walk_habit_completed")]


def test_non_walk_whoop_workouts_and_failed_habits_are_not_signals():
    ride = {**WHOOP_WALK, "sport_name": "cycling"}
    failed = {**HABIT_DAY, "habit_statuses": {"Walk Outdoor >2mi": {"status": "failed"}}}
    assert _signals(_build([], inputs={"whoop": [ride], "habitify": [failed]})) == []


def test_an_unreadable_signal_source_is_said_and_a_caller_that_did_not_ask_is_not_checked():
    layer = _build([OTHER_DAY_STRAVA], inputs={"whoop": None, "habitify": [HABIT_DAY]})
    assert layer["completeness"]["unreadable"] == ["whoop"]
    assert _signals(layer) == [(DAY, "walk_habit_completed")]
    assert _build([OTHER_DAY_STRAVA])["completeness"] == {"status": "not_checked", "gaps": []}
