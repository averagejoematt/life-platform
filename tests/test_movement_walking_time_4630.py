"""tests/test_movement_walking_time_4630.py — ADR-163: the day grade's movement score rewards walking time (#4630 box 3).

Owner ruling, #4644 Q5: "b — score movement from walking time". The step half of
`health.scoring_engine.score_movement` is replaced by a walking-minutes half read through
`training.walking_volume.walking_minutes_for_day` — the walking layer's own sources, counting rule
and #4068 time de-dup over one day — against the profile's `walking_minutes_target` (default: the
permanent 8.5 h/wk walking floor over seven days).

Fixtures are the WIRE: the real stored Strava day rows and Hevy workout rows of 2026-09-16/17
(tests/fixtures/shared_quantities_4068/, read read-only from DDB for #4068). On 09-17 the Hevy
session 12:10–14:21Z carries a 60-minute Walking block and WHOOP posted the same walk to Strava as
its own 58-minute `Walk` starting 13:03Z — ONE walk, seen twice. On 09-16 the Hevy block is Cycling
(not walking time) and a 14.5-minute Garmin walk sits outside every session.

Mutation controls (run red, then restored green — output in the PR):
  * drop the de-dup — make `walking_volume.hevy_cardio_intervals` return [] — 09-17 reads 118 min
    and `test_a_hevy_treadmill_block_and_its_whoop_strava_twin_count_once` reds;
  * drop the target read — replace `profile.get("walking_minutes_target")` with None in
    `score_movement` — `test_the_target_is_read_from_the_profile` reds.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lambdas"))
for _k, _v in (("TABLE_NAME", "life-platform-test"), ("USER_ID", "matthew"), ("AWS_DEFAULT_REGION", "us-west-2")):
    os.environ.setdefault(_k, _v)

from health import scoring_engine as se  # noqa: E402
from training import owner_redlines, walking_volume as wv  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "shared_quantities_4068"
STRAVA = {r["date"]: r for r in json.loads((FIX / "strava_2026-09-08_22.json").read_text())}
HEVY = json.loads((FIX / "hevy_2026-09-08_22.json").read_text())


def _day(day: str) -> dict:
    """The day's data the way daily-metrics-compute assembles it: the Strava DATE# row and the day's Hevy WORKOUT# rows."""
    return {"date": day, "strava": STRAVA.get(day), "hevy": [w for w in HEVY if w["sk"].startswith(f"DATE#{day}#")]}


def test_the_default_target_is_the_walking_floor_over_seven_days():
    assert owner_redlines.REDLINES["walking_floor_hr_wk"]["value"] == 8.5
    assert se.WALKING_MINUTES_TARGET_DEFAULT == 73  # round(8.5 * 60 / 7)


def test_a_hevy_treadmill_block_and_its_whoop_strava_twin_count_once():
    """09-17: Hevy Walking 60 min + the WHOOP `Walk` (58 min) inside the same session → 60 min, not 118."""
    walk = wv.walking_minutes_for_day(day="2026-09-17", strava_items=[STRAVA["2026-09-17"]], hevy_workouts=_day("2026-09-17")["hevy"])
    assert walk["minutes"] == 60.0
    assert walk["by_source"] == {"strava": 0.0, "hevy": 60.0}
    score, details = se.score_movement(_day("2026-09-17"), {})
    assert details["walking_minutes"] == 60.0
    assert details["walking_score"] == 82  # 60 / 73
    assert details["walking_minutes_target"] == 73


def test_walking_at_or_above_the_target_scores_full_marks_on_that_half():
    score, details = se.score_movement(_day("2026-09-17"), {"walking_minutes_target": 60})
    assert details["walking_score"] == 100
    score, details = se.score_movement(_day("2026-09-17"), {"walking_minutes_target": 45})
    assert details["walking_score"] == 100


def test_the_target_is_read_from_the_profile():
    _, details = se.score_movement(_day("2026-09-17"), {"walking_minutes_target": 120})
    assert (details["walking_score"], details["walking_minutes_target"]) == (50, 120)


def test_cycling_is_not_walking_time_and_a_walk_outside_the_session_counts():
    """09-16: the Hevy block is Cycling (60 min, not walking) and a 14.5-min Garmin walk sits outside it."""
    _, details = se.score_movement(_day("2026-09-16"), {"walking_minutes_target": 60})
    assert details["walking_minutes"] == 14.4  # 0.24 h — the layer's hour rounding, 870 s
    assert details["walking_minutes_by_source"] == {"strava": 14.4, "hevy": 0.0}
    assert details["walking_score"] == 24


def test_no_strava_row_and_no_hevy_session_drops_the_walking_half():
    """The dropout semantics are the step half's, mirrored: unknown walking leaves the exercise half alone."""
    score, details = se.score_movement({"date": "2026-09-23", "strava": None, "hevy": []}, {})
    assert score == 0 and details == {"exercise_score": 0}
    assert wv.walking_minutes_for_day(day="2026-09-23", strava_items=[], hevy_workouts=[]) is None


def test_a_lift_only_day_reads_zero_walking_never_unknown():
    """A Hevy session with no walking block is a READ day with 0 walking minutes — not a dropout."""
    lift = {"sk": "DATE#2026-09-24#WORKOUT#x", "date": "2026-09-24", "exercises": [{"name": "Bench Press", "sets": [{"reps": 5}]}]}
    _, details = se.score_movement({"date": "2026-09-24", "strava": None, "hevy": [lift]}, {})
    assert (details["walking_minutes"], details["walking_score"]) == (0.0, 0)


def test_score_movement_no_longer_reads_steps():
    src = (ROOT / "lambdas" / "health" / "scoring_engine.py").read_text(encoding="utf-8")
    body = src[src.index("def score_movement(") : src.index("def habitify_reading(")]
    assert "resolve_steps" not in body and "step_target" not in body
