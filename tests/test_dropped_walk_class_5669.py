"""tests/test_dropped_walk_class_5669.py — the 2026-10-20 dropped walk, as a CLASS (#5669).

THE SPECIMEN

A WHOOP walk reached Strava (activity 20669407754), was ingested, then left Strava's list; the #4638
reconciler tombstoned 2026-10-20 and every reader that counts walking from Strava read the day as
zero. PR #5670 gave the weekly walking layer a walk-signal check. This file pins the rest of the set:

  * `training.recent_aerobic.build` (the plan's `constraint_block.recent_aerobic`, the routine
    generator's `z2_minutes_7d`, the cardio pick, the walking tripwires) runs the same check, and each
    reader that turns a total into a verdict goes unknown only in the direction a missing walk could flip;
  * `mcp.shared_quantities.recent_aerobic_layer` and `hevy_routine_cron._z2_minutes_7d` wire it;
  * `shared_quantities.weekly_walking_hours` (the adherence critic's bare number) is None on a gap;
  * the two #4638 tombstone writers keep what they supersede (capture-all, interpret later).

EACH TEST NAMES THE MUTATION THAT REDS IT.
"""

from __future__ import annotations

import os

for _k, _v in {
    "S3_BUCKET": "test-bucket",
    "TABLE_NAME": "life-platform",
    "USER_ID": "matthew",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_REGION": "us-west-2",
}.items():
    os.environ.setdefault(_k, _v)

from training import (
    recent_aerobic as ra,  # noqa: E402
    walking_volume as wv,  # noqa: E402
)

DAY = "2026-10-20"
# The live WHOOP workout and habit row, field-projected (as tests/test_walking_completeness_2026_10_20.py).
WHOOP_WALK = {
    "sk": "DATE#2026-10-20#WORKOUT#5f70ea18-0cf3-485c-8527-8c184b8423de",
    "date": DAY,
    "workout_id": "5f70ea18-0cf3-485c-8527-8c184b8423de",
    "sport_name": "walking",
    "start_time": "2026-10-20T23:09:23.734Z",
    "end_time": "2026-10-21T02:03:37.542Z",
    "zone_1_minutes": "52.37",
    "zone_2_minutes": "5.72",
    "zone_3_minutes": "3.08",
    "zone_4_minutes": "0.03",
    "zone_5_minutes": "0",
}
HABIT_DAY = {"sk": "DATE#2026-10-20", "date": DAY, "habit_statuses": {"Walk Outdoor >2mi": {"status": "completed"}}}
SIGNALS = {"whoop": [WHOOP_WALK], "habitify": [HABIT_DAY]}
# The Strava copy as it was ingested, before the vendor list dropped it.
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


def _walk(day: str, hour_utc: int, minutes: int) -> dict:
    return {
        "date": day,
        "activities": [
            {
                "sport_type": "Walk",
                "start_date": f"{day}T{hour_utc:02d}:00:00Z",
                "moving_time_seconds": minutes * 60,
                "elapsed_time_seconds": minutes * 60,
            }
        ],
    }


def _block(strava, target="2026-10-22", inputs=SIGNALS, today="2026-10-25"):
    return ra.build(target_date=target, today=today, strava_items=strava, hevy_workouts=[], completeness_inputs=inputs)


# ── recent_aerobic: the block ────────────────────────────────────────────────────────


def test_the_tombstoned_day_is_named_and_the_block_is_a_floor():
    """Mutation control: drop the `complete["gaps"]` term from `totals_are_floor` — reds on the floor;
    drop `completeness_inputs=` from the `walking_volume.completeness` call — reds on the gaps."""
    b = _block([_walk("2026-10-19", 15, 45)])
    assert [(g["date"], g["signal"]) for g in b["completeness"]["gaps"]] == [(DAY, "walk_habit_completed"), (DAY, "whoop_walk_workout")]
    assert b["totals_are_floor"] is True
    assert any(h.startswith(DAY) and "floor" in h for h in b["honesty"])
    assert b["version"] == "recent-aerobic@1.4.0"  # 1.4.0 (#5916): heart rate is a measurement with its basis, never graded


def test_the_day_as_ingested_is_complete():
    """With the Strava copy in hand the signals overlap a counted walk — no gap, no floor."""
    b = _block([_walk("2026-10-19", 15, 45), STRAVA_DAY])
    assert b["completeness"]["gaps"] == [] and b["totals_are_floor"] is False


def test_a_caller_that_did_not_ask_is_not_checked_and_not_floored():
    b = _block([_walk("2026-10-19", 15, 45)], inputs=None)
    assert b["completeness"] == {"status": "not_checked", "gaps": []}
    assert b["totals_are_floor"] is False


def test_an_unread_signal_source_is_said_but_is_not_a_floor():
    """Mutation control: drop the unreadable loop from `walking_volume.completeness_honesty` — reds."""
    b = _block([_walk("2026-10-19", 15, 45)], inputs={"whoop": None, "habitify": []})
    assert b["completeness"]["unreadable"] == ["whoop"]
    assert b["totals_are_floor"] is False
    assert any("walk-signal check could not read whoop" in h for h in b["honesty"])


# ── recent_aerobic: the readers that turn a total into a decision ─────────────────────


def test_z2_minutes_is_unknown_when_the_trailing_week_holds_a_gap():
    """Mutation control: drop the `gap_days(...)` term in `aerobic_minutes_7d` — reds (it returns 45.0)."""
    assert ra.aerobic_minutes_7d(_block([_walk("2026-10-19", 15, 45)])) is None
    assert ra.aerobic_minutes_7d(_block([_walk("2026-10-19", 15, 45), STRAVA_DAY])) == round(round((2700 + 10454) / 3600, 2) * 60, 1)


def test_a_gap_only_in_the_prior_week_leaves_z2_minutes_exact():
    """Target 10-28: trailing 10-21..10-27, prior 10-14..10-20 — the gap does not touch the counted week.
    Mutation control: key `aerobic_minutes_7d` on `totals_are_floor` again — reds (None)."""
    b = _block([_walk("2026-10-22", 15, 60)], target="2026-10-28", today="2026-10-30")
    assert b["totals_are_floor"] is True
    assert ra.aerobic_minutes_7d(b) == 60.0


def test_fresh_legs_cannot_be_claimed_over_an_uncounted_walk():
    """Target 10-22: the 48 h are 10-20..10-21. Mutation control: drop the `missed` branch in `legs_loaded` — reds (False)."""
    loaded, why = ra.legs_loaded(_block([_walk("2026-10-19", 15, 45)]))
    assert loaded is None and DAY in why and "FLOOR" in why
    assert ra.legs_loaded(_block([_walk("2026-10-19", 15, 45)], inputs=None))[0] is False
    assert ra.cardio_pick(_block([_walk("2026-10-19", 15, 45)]), "upper")["movement_key"] == "cycling"


def test_a_collapse_resting_on_an_uncounted_walk_is_unknown_not_tripped():
    """Prior week 3 h, this week nothing counted but the 10-20 signals. Mutation control: drop the `gap_this`
    term in `weekly_reports` — reds (tripped)."""
    strava = [_walk("2026-10-10", 15, 180)]
    assert ra.weekly_reports(_block(strava, inputs=None), 30.0)["walking_collapse"][0] == "tripped"
    state, _obs, detail = ra.weekly_reports(_block(strava), 30.0)["walking_collapse"]
    assert state == "unknown" and DAY in detail


def test_a_clear_week_over_a_floored_prior_week_is_unknown():
    """Target 10-28: an equal hour each week reads clear, but the prior week (10-14..10-20) is a floor.
    Mutation control: drop the `gap_last` term — reds (clear)."""
    strava = [_walk("2026-10-15", 15, 60), _walk("2026-10-22", 15, 60), _walk("2026-10-23", 15, 60), _walk("2026-10-24", 15, 60)]
    b = _block(strava, target="2026-10-28", today="2026-10-30")
    hours = ra.weekly_reports(b, 30.0)["walking_collapse"]
    assert hours[1] is not None and hours[1] > -30.0
    assert hours[0] == "unknown"
    clean = _block(strava, target="2026-10-28", today="2026-10-30", inputs=None)
    assert ra.weekly_reports(clean, 30.0)["walking_collapse"][0] == "clear"


def test_an_overshoot_clear_over_an_uncounted_walk_is_unknown():
    """Week to date 10-19..10-21 holds the gap; 0.75 h reads clear. Mutation control: drop the `gap_wtd` term — reds."""
    state, _h, detail = ra.weekly_reports(_block([_walk("2026-10-19", 15, 45)]), 30.0)["walking_overshoot"]
    assert state == "unknown" and DAY in detail
    assert ra.weekly_reports(_block([_walk("2026-10-19", 15, 45)], inputs=None), 30.0)["walking_overshoot"][0] == "clear"


# ── the wiring ────────────────────────────────────────────────────────────────────────


def _reader(by_source):
    def read(source, start, end):
        return [r for r in by_source.get(source, []) if start <= str(r.get("date") or "")[:10] <= end]

    return read


def test_the_mcp_recent_aerobic_layer_wires_the_signals():
    """Mutation control: drop `completeness_inputs=` from `shared_quantities.recent_aerobic_layer` — reds (not_checked)."""
    from mcp import shared_quantities as sq

    read = _reader({"strava": [_walk("2026-10-19", 15, 45)], "whoop": [WHOOP_WALK], "habitify": [HABIT_DAY]})
    b = sq.recent_aerobic_layer("2026-10-22", today="2026-10-25", read=read)
    assert b["completeness"]["status"] == "checked"
    assert {g["date"] for g in b["completeness"]["gaps"]} == {DAY}
    assert sq.z2_minutes_7d("2026-10-22", today="2026-10-25", read=read) is None


def test_the_routine_cron_z2_minutes_wires_the_signals():
    """Mutation control: drop `completeness_inputs=` from `hevy_routine_cron._z2_minutes_7d` — reds (45.0)."""
    from operational import hevy_routine_cron_lambda as cron

    read = _reader({"strava": [_walk("2026-10-19", 15, 45)], "whoop": [WHOOP_WALK], "habitify": [HABIT_DAY]})
    assert cron._z2_minutes_7d("2026-10-22", read=read) is None
    read_clean = _reader({"strava": [_walk("2026-10-19", 15, 45)], "whoop": [], "habitify": []})
    assert cron._z2_minutes_7d("2026-10-22", read=read_clean) == 45.0


def test_weekly_walking_hours_is_none_on_a_gap(monkeypatch):
    """The adherence critic reads a bare number; a floored week would read as a collapse. Mutation control:
    drop the `gaps` term in `weekly_walking_hours` — reds (0.75)."""
    from mcp import shared_quantities as sq

    sources = {"strava": [_walk("2026-10-19", 15, 45)], "hevy": [], "whoop": [WHOOP_WALK], "habitify": [HABIT_DAY]}
    monkeypatch.setattr(sq._core, "query_source_range", _reader(sources))
    assert sq.weekly_walking_hours("2026-10-22", today="2026-10-25") is None
    sources["whoop"], sources["habitify"] = [], []
    assert sq.weekly_walking_hours("2026-10-22", today="2026-10-25") == 0.75


def test_the_weekly_layer_says_an_unread_signal_source():
    def build(inputs):
        return wv.build(
            window_start="2026-10-19",
            window_end=DAY,
            strava_items=[_walk("2026-10-19", 15, 45)],
            hevy_workouts=[],
            completeness_inputs=inputs,
        )

    layer, control = build({"whoop": [], "habitify": None}), build({"whoop": [], "habitify": []})
    assert any("could not read habitify" in h for h in layer["honesty"])
    assert not any("could not read" in h for h in control["honesty"])
    assert layer["total_is_floor"] == control["total_is_floor"]  # an unread signal is said, never a floor by itself
    assert layer["version"] == "walking-volume@1.4.0"


# ── the writers: a tombstone keeps what it supersedes ─────────────────────────────────


class _Recording:
    def __init__(self):
        self.puts = []

    def put_item(self, Item):
        self.puts.append(Item)


def test_the_strava_tombstone_keeps_the_activities_it_empties():
    """Mutation control: drop `**kept` from `_empty_day_record` — reds (the walk is gone from the table)."""
    from ingestion import strava_lambda as strava

    table = _Recording()
    out = strava._write_empty_days(table, [(DAY, ["20669407754"])], 5, {DAY: STRAVA_DAY["activities"]})
    assert out["emptied"] == [DAY]
    item = table.puts[0]
    assert item["activities"] == [] and item["tombstone"] is True
    assert item["emptied_activities"] == STRAVA_DAY["activities"]
    # a caller that hands no stored day writes the pre-#5669 shape
    assert "emptied_activities" not in strava._empty_day_record(DAY, ["x"])


def test_the_whoop_tombstone_keeps_the_row_it_replaces():
    """Mutation control: drop the `emptied_record` entry from `empty_day_records` — reds."""
    from ingestion import whoop_empty_day as wed

    stored = {**WHOOP_WALK, "pk": "USER#matthew#SOURCE#whoop", "strain": "8.1"}
    recs = wed.empty_day_records(DAY, [(WHOOP_WALK["workout_id"], WHOOP_WALK["sk"])], "matthew", {WHOOP_WALK["sk"]: stored})
    assert len(recs) == 1 and recs[0]["tombstone"] is True and "strain" not in recs[0]
    kept = recs[0]["emptied_record"]
    assert kept["strain"] == "8.1" and kept["zone_1_minutes"] == "52.37" and "pk" not in kept and "sk" not in kept
    assert "emptied_record" not in wed.empty_day_records(DAY, [("w", "DATE#2026-10-20#WORKOUT#w")], "matthew")[0]


# ── the WHOOP key frame: UTC day of the start, never the Pacific day ──────────────────
# Live rows: `DATE#2026-10-06#WORKOUT#37ee55bb…` is a walk that began 2026-10-05 17:41 PT (00:41Z); Strava
# files the same walk (Garmin) under 2026-10-05. Judged by the key, every window starting 10-06 read a gap.
WHOOP_EVENING = {
    "sk": "DATE#2026-10-06#WORKOUT#37ee55bb-9ff0-491a-baab-bdd851f8e6c1",
    "date": "2026-10-06",
    "workout_id": "37ee55bb-9ff0-491a-baab-bdd851f8e6c1",
    "sport_name": "walking",
    "start_time": "2026-10-06T00:41:29.000Z",
    "end_time": "2026-10-06T01:52:56.000Z",
}
STRAVA_EVENING = {
    "date": "2026-10-05",
    "activities": [
        {
            "sport_type": "Walk",
            "device_name": "Garmin epix (Gen2)",
            "start_date": "2026-10-06T00:41:29Z",
            "moving_time_seconds": 4287,
            "elapsed_time_seconds": 4287,
        }
    ],
}


def _week(strava, whoop, start, end):
    return wv.build(
        window_start=start, window_end=end, strava_items=strava, hevy_workouts=[], completeness_inputs={"whoop": whoop, "habitify": []}
    )


def test_a_pacific_evening_walk_before_the_window_is_not_a_gap_on_its_first_day():
    """Mutation control: date `_whoop_walks` by `_row_day(r)` again — reds (a 10-06 gap)."""
    assert _week([], [WHOOP_EVENING], "2026-10-06", "2026-10-12")["completeness"]["gaps"] == []


def test_a_pacific_evening_walk_on_the_last_day_is_judged_on_its_pacific_day():
    gaps = _week([], [WHOOP_EVENING], "2026-09-29", "2026-10-05")["completeness"]["gaps"]
    assert [(g["date"], g["signal"]) for g in gaps] == [("2026-10-05", "whoop_walk_workout")]
    assert _week([STRAVA_EVENING], [WHOOP_EVENING], "2026-09-29", "2026-10-05")["completeness"]["gaps"] == []


def test_the_readers_read_whoop_one_utc_day_past_the_window():
    """The walk on 10-05's evening is keyed 10-06: a reader that stops at 10-05 never sees it. Mutation
    control: set `COMPLETENESS_READ_PAST_END_DAYS["whoop"]` to 0 — reds (no gap)."""
    from mcp import shared_quantities as sq

    read = _reader({"strava": [], "hevy": [], "whoop": [WHOOP_EVENING], "habitify": []})
    layer = sq.walking_layer_for_day("2026-10-05", today="2026-10-10", read=read, with_apple=False)
    assert [g["date"] for g in layer["completeness"]["gaps"]] == ["2026-10-05"]
