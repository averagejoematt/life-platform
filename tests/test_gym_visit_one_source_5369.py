"""tests/test_gym_visit_one_source_5369.py — one gym visit, its parts each counted once (#5369, #5353, #5371).

Owner ruling 2026-10-25/26: Hevy is the ONE routine source (lift + cycling block + mobility block).
The watch's own workouts, the pliability app's workouts, their HealthKit echoes and every Strava
push are echoes of the same visit and must count once.

THE FIXTURE IS THE 2026-10-25 WIRE'S STRUCTURE, WITH SYNTHETIC NUMBERS. The structure was read
(read-only DynamoDB, 2026-10-25, field shapes only — no value is copied): one Hevy session holding a
lift, a 60-minute Cycling block and a Stretching block; three `apple_workouts` entries on the
apple_health day row — Indoor Cycling recorded by the watch, Traditional Strength Training whose
HealthKit origin is Hevy (`com.hevyapp.hevy`), Flexibility whose origin is the pliability app
(`com.romwodllc.romwod`); four Strava activities — WeightTraining from device `Hevy`, WeightTraining
twice from device `WHOOP`, and a Ride from `WHOOP` over the watch ride; and (the full-wire variant)
the matching three Whoop workout rows. Every time, duration, heart-rate bin and zone below is
invented; no GPS, no name, no device identifier is real.

Session 16:40–19:20 UTC (09:40–12:20 PDT): lift, Cycling 60 min (18:00–19:00), Stretching 18 min.
  Strava  Hevy push 16:40 (9600 s) · WHOOP WeightTraining 16:58 (1000 s) · WHOOP Ride 18:00
          (3600 s) · WHOOP WeightTraining 19:00 (1300 s)
  Apple   Indoor Cycling 11:00–12:00 PDT (watch) · Traditional Strength Training 12:00–12:21 PDT
          (Hevy) · Flexibility 12:02–12:22 PDT (pliability)

Expected: one lift, one ride, one mobility block; the ride keeps its identity; minutes once.
"""

from __future__ import annotations

import copy
import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from training import (  # noqa: E402
    recent_aerobic,
    walking_volume as wv,
    workout_identity as wi,
    zone2_minutes as z2m,
)

DAY = "2026-10-25"

HEVY = {
    "pk": "USER#matthew#SOURCE#hevy",
    "sk": f"DATE#{DAY}#WORKOUT#hv-synth-5369",
    "date": DAY,
    "workout_uid": "hv-synth-5369",
    "start_time": "2026-10-25T16:40:00+00:00",
    "end_time": "2026-10-25T19:20:00+00:00",
    "exercises": [
        {"name": "Shoulder Press (Dumbbell)", "sets": [{"reps": 10, "weight_kg": 10.0, "duration_sec": None}] * 3},
        {"name": "Triceps Rope Pushdown", "sets": [{"reps": 12, "weight_kg": 20.0, "duration_sec": None}] * 3},
        {"name": "Cycling", "sets": [{"duration_sec": 3600, "distance_m": 18000}]},
        {"name": "Stretching", "sets": [{"duration_sec": 1080}]},
    ],
}

_WATCH = {"identifier": "com.apple.health.SYNTH-0000", "name": "Synthetic Apple\xa0Watch"}
_HEVY_APP = {"identifier": "com.hevyapp.hevy", "name": "Hevy"}
_PLIABILITY = {"identifier": "com.romwodllc.romwod", "name": "pliability"}


def _apple(wid, name, start, end, source, bins):
    return {
        "id": wid,
        "name": name,
        "start": f"{DAY} {start} -0700",
        "end": f"{DAY} {end} -0700",
        "duration": float(sum(bins.values())),
        "source": source,
        "derived": {"hr_seconds_by_bpm5": bins, "version": "synthetic"},
    }


# bins sum to each workout's own length, so a recording's measured seconds are its interval
APPLE_CYCLING = _apple("AW-CYC-0001", "Indoor Cycling", "11:00:00", "12:00:00", _WATCH, {"110": 1800.0, "120": 1800.0})
APPLE_LIFT = _apple("AW-STR-0002", "Traditional Strength Training", "12:00:00", "12:21:00", _HEVY_APP, {"100": 1260.0})
APPLE_FLEX = _apple("AW-FLX-0003", "Flexibility", "12:02:00", "12:22:00", _PLIABILITY, {"95": 1200.0})


def _apple_row(*workouts):
    return {
        "pk": "USER#matthew#SOURCE#apple_health",
        "sk": f"DATE#{DAY}",
        "date": DAY,
        "apple_workouts": {w["id"]: copy.deepcopy(w) for w in workouts},
    }


def _act(sid, sport, device, start, secs, zones=None, avg_hr=None):
    a = {
        "strava_id": sid,
        "sport_type": sport,
        "type": sport,
        "device_name": device,
        "start_date": f"{DAY}T{start}Z",
        "start_date_local": f"{DAY}T{start}Z",
        "elapsed_time_seconds": secs,
        "moving_time_seconds": secs,
        "distance_meters": 0,
        "trainer": True,
        "average_heartrate": avg_hr,
    }
    for i, z in enumerate(zones or (), start=1):
        a[f"zone{i}_seconds"] = z
    return a


STRAVA_HEVY_PUSH = _act("90000001", "WeightTraining", "Hevy", "16:40:00", 9600, (6000, 2400, 600, 0, 0), avg_hr=96.0)
STRAVA_WHOOP_LIFT_A = _act("90000002", "WeightTraining", "WHOOP", "16:58:00", 1000, (700, 300, 0, 0, 0), avg_hr=92.0)
STRAVA_WHOOP_RIDE = _act("90000003", "Ride", "WHOOP", "18:00:00", 3600, (1200, 2400, 0, 0, 0), avg_hr=118.0)
STRAVA_WHOOP_LIFT_B = _act("90000004", "WeightTraining", "WHOOP", "19:00:00", 1300, (1300, 0, 0, 0, 0), avg_hr=88.0)


def _strava_row(*acts):
    return {"pk": "USER#matthew#SOURCE#strava", "sk": f"DATE#{DAY}", "date": DAY, "activities": [dict(a) for a in acts]}


def _whoop(wid, sport, start, end, zones):
    row = {
        "pk": "USER#matthew#SOURCE#whoop",
        "sk": f"DATE#{DAY}#WORKOUT#{wid}",
        "date": DAY,
        "workout_id": wid,
        "start_time": f"{DAY}T{start}Z",
        "end_time": f"{DAY}T{end}Z",
        "sport_name": sport,
        "vendor_sport_name": sport,
    }
    row.update({f"zone_{i}_minutes": m for i, m in enumerate(zones)})
    return row


WHOOP_ROWS = [
    {"pk": "USER#matthew#SOURCE#whoop", "sk": f"DATE#{DAY}", "date": DAY, "strain": 9.0},  # a DAY row — ignored
    # zone_0 .. zone_5 minutes (zone_0 is below zone 1)
    _whoop("wh-lift-a", "weightlifting", "16:58:00", "17:14:40", (10.0, 6.67, 0, 0, 0, 0)),
    _whoop("wh-ride", "cycling", "18:00:00", "19:00:00", (0, 15.0, 45.0, 0, 0, 0)),
    _whoop("wh-lift-b", "weightlifting", "19:00:00", "19:21:40", (21.67, 0, 0, 0, 0, 0)),
]

ALL_STRAVA = (STRAVA_HEVY_PUSH, STRAVA_WHOOP_LIFT_A, STRAVA_WHOOP_RIDE, STRAVA_WHOOP_LIFT_B)


def _sessions(strava=ALL_STRAVA, apple=(APPLE_CYCLING, APPLE_LIFT, APPLE_FLEX), whoop=(), hevy=(HEVY,)):
    return z2m.counted_sessions([_strava_row(*strava)], list(whoop), [_apple_row(*apple)], hevy_rows=list(hevy))


def _by_family(sessions):
    out = {}
    for s in sessions:
        out.setdefault(s["family"], []).append(s)
    return out


# ── box 1: the wire resolves to one lift, one ride, one mobility block ─────────────────


def test_the_wire_is_one_lift_one_ride_one_mobility_block():
    sessions = _sessions()
    fams = _by_family(sessions)
    assert sorted(fams) == ["cycling", "mobility", "strength"], [(s["family"], s["ids"]) for s in sessions]
    assert all(len(v) == 1 for v in fams.values()), fams
    ride, lift, mob = fams["cycling"][0], fams["strength"][0], fams["mobility"][0]
    # the ride keeps its identity: Hevy's block, the WHOOP ride and the watch ride are ONE, called a ride
    assert ride["sport"] == "Ride" and ride["strava_id"] == "90000003"
    assert ride["ids"] == sorted(["hevy:hv-synth-5369#cycling", "strava:90000003", "apple_health:AW-CYC-0001"])
    assert lift["sport"] == "WeightTraining" and "apple_health/hevy:AW-STR-0002" in lift["ids"]
    assert mob["sport"] == "Mobility" and "apple_health/pliability:AW-FLX-0003" in mob["ids"]


def test_minutes_are_counted_once_and_the_parts_sum_to_the_visit():
    sessions = _sessions()
    fams = {s["family"]: s for s in sessions}
    # durations come from the logged Hevy blocks (precedence Hevy > Strava > Apple > Whoop)
    assert fams["cycling"]["duration_minutes"] == 60.0
    assert fams["mobility"]["duration_minutes"] == 18.0
    assert fams["strength"]["duration_minutes"] == 160.0 - 60.0 - 18.0
    assert sum(s["duration_minutes"] for s in sessions) == 160.0, "the parts sum to the visit, never more"
    # zone time: the lift (Hevy's watch app, 12:00–12:21) and the mobility block (pliability,
    # 12:02–12:22) carry the same minutes — they are measured once across the read
    assert fams["mobility"]["measured_minutes"] == 20.0 and fams["mobility"]["overlap_minutes_removed"] == 0.0
    assert fams["strength"]["measured_minutes"] == pytest.approx(2.0, abs=0.01)
    assert fams["strength"]["overlap_minutes_removed"] == pytest.approx(19.0, abs=0.01)
    assert fams["cycling"]["measured_minutes"] == 60.0
    union_min = 60.0 + 22.0  # 11:00–12:00 and 12:00–12:22 PDT
    assert sum(s["measured_minutes"] for s in sessions) == pytest.approx(union_min, abs=0.01)


def test_hevy_cardio_stays_its_own_bucket_beside_zone2():
    sessions = _sessions()
    win = z2m.zone2_window(None, None, [HEVY], DAY, DAY, sessions=sessions)
    assert win["hevy_cardio_minutes"] == 60.0  # the Cycling block (Stretching is not a cardio token)
    assert win["zone_2_minutes"] == round(sum(s["zone_2_minutes"] or 0 for s in sessions if s["source"]), 1)
    assert win["zone_2_minutes"] + win["hevy_cardio_minutes"] != win["zone_2_minutes"]  # two buckets, never summed


def test_the_seam_folds_the_whoop_pieces_into_hevys_push_which_drops_as_its_echo():
    """Both WHOOP WeightTraining pieces lie inside Hevy's push (different devices, >= 80% contained),
    so the read seam folds them into it; the push is then dropped as the Hevy session's echo."""
    kept = wi.strava_without_echoes([_strava_row(*ALL_STRAVA)], [HEVY])
    assert [a["strava_id"] for a in kept[0]["activities"]] == ["90000003"]
    without_hevy = wi.strava_without_echoes([_strava_row(*ALL_STRAVA)], [])
    assert sorted(a["strava_id"] for a in without_hevy[0]["activities"]) == ["90000001", "90000003"]


def test_without_hevys_push_the_two_whoop_pieces_are_chunks_of_one_lift():
    """No Hevy push for the seam to fold into: WHOOP's two disjoint pieces both join the Hevy lift as
    its chunks (never a second lift)."""
    sessions = _sessions(strava=(STRAVA_WHOOP_LIFT_A, STRAVA_WHOOP_RIDE, STRAVA_WHOOP_LIFT_B))
    fams = _by_family(sessions)
    assert sorted(fams) == ["cycling", "mobility", "strength"] and len(fams["strength"]) == 1
    assert {"strava:90000002", "strava:90000004"} <= set(fams["strength"][0]["ids"])


def test_the_full_wire_with_whoop_rows_is_still_three_parts_with_whoops_own_zones():
    sessions = _sessions(whoop=WHOOP_ROWS)
    fams = _by_family(sessions)
    assert sorted(fams) == ["cycling", "mobility", "strength"] and all(len(v) == 1 for v in fams.values())
    assert fams["cycling"][0]["source"] == "whoop" and fams["cycling"][0]["zone_2_minutes"] == 45.0
    assert {"whoop:wh-lift-a", "whoop:wh-lift-b"} <= set(fams["strength"][0]["ids"]), "Whoop's two lift pieces: one lift"
    total = sum(s["measured_minutes"] for s in sessions)
    assert total <= (160.0 + 2.0), "no minute of the visit is measured twice"


def test_readers_work_without_whoops_strava_copies():
    """From 2026-10-26 WHOOP no longer shares to Strava and the watch uploads its own ride: the same
    three parts, the ride still a ride."""
    watch_ride = _act("90000010", "Ride", "Apple Watch Ultra", "18:00:00", 3600, (1800, 1800, 0, 0, 0), avg_hr=115.0)
    sessions = _sessions(strava=(STRAVA_HEVY_PUSH, watch_ride))
    fams = _by_family(sessions)
    assert sorted(fams) == ["cycling", "mobility", "strength"] and fams["cycling"][0]["sport"] == "Ride"
    no_strava = _sessions(strava=())
    assert sorted(_by_family(no_strava)) == ["cycling", "mobility", "strength"]
    assert _by_family(no_strava)["cycling"][0]["sport"] == "Ride"  # Strava's word for a Hevy-anchored ride


def test_the_family_split_keeps_the_watch_ride_out_of_the_lift(monkeypatch):
    """Mutation control for box 1: with the family test switched off (the retired `_same_session`
    grouped across sports), the watch's ride is swallowed by the lift Hevy pushed to Strava — the
    pre-#5369 over-merge. With it, the ride keeps the watch's record."""

    def ride_ids():
        sessions = _sessions(hevy=())  # no Hevy rows: Hevy's push stays as the lift's record
        return [s["ids"] for s in sessions if s["sport"] == "Ride"][0]

    assert "apple_health:AW-CYC-0001" in ride_ids()
    monkeypatch.setattr(wi, "compatible", lambda a, b: True)
    assert "apple_health:AW-CYC-0001" not in ride_ids()


# ── box 2: HealthKit-origin workouts fold into their source's record ───────────────────


def test_a_hevy_origin_lift_folds_into_the_hevy_lift_never_a_second_watch_session():
    watch_lift = _apple("AW-STR-0009", "Traditional Strength Training", "09:45:00", "12:15:00", _WATCH, {"100": 9000.0})
    sessions = _sessions(strava=(), apple=(watch_lift, APPLE_LIFT))
    lifts = _by_family(sessions)["strength"]
    assert len(lifts) == 1, [s["ids"] for s in lifts]
    assert {"apple_health:AW-STR-0009", "apple_health/hevy:AW-STR-0002", "hevy:hv-synth-5369#strength"} <= set(lifts[0]["ids"])


def test_the_hevy_origin_fold_can_fail(monkeypatch):
    """Mutation control: read every HealthKit workout as the watch's (the pre-#5369 zone2 reader) and
    Hevy's own lift becomes a SECOND watch lift beside the watch's."""
    watch_lift = _apple("AW-STR-0009", "Traditional Strength Training", "09:45:00", "12:15:00", _WATCH, {"100": 9000.0})
    monkeypatch.setattr(wi, "apple_workout_source", lambda w: "apple_health")
    monkeypatch.setattr(wi, "_apple_source", lambda w: "apple_health")
    monkeypatch.setattr(z2m, "apple_workout_source", lambda w: "apple_health")
    sessions = _sessions(strava=(), apple=(watch_lift, APPLE_LIFT))
    assert len(_by_family(sessions)["strength"]) == 2


def test_a_pliability_session_folds_into_the_hevy_mobility_block():
    sessions = _sessions(strava=(), apple=(APPLE_FLEX,))
    (mob,) = sessions
    assert mob["family"] == "mobility" and mob["sport"] == "Mobility"
    assert mob["ids"] == sorted(["hevy:hv-synth-5369#mobility", "apple_health/pliability:AW-FLX-0003"])
    assert wv.apple_workout_source(APPLE_FLEX) == "apple_health/pliability"
    assert wv.apple_workout_source(APPLE_LIFT) == "apple_health/hevy"
    assert wv.apple_workout_source(APPLE_CYCLING) == "apple_health"


def test_mobility_is_a_family_on_every_side():
    assert wi.APPLE_FAMILY["flexibility"] == wi.MOBILITY
    assert wi._hevy_family("Stretching") == wi.MOBILITY
    assert wi.whoop_family("stretching") == wi.MOBILITY
    assert wi.whoop_family("activity").startswith(wi.OTHER_PREFIX)


# ── #5353 rides along: the Apple leg counts on an Apple-only day ───────────────────────


def test_an_apple_only_day_counts_its_zone_minutes():
    ride = _apple("AW-CYC-0100", "Outdoor Cycling", "15:00:00", "15:40:00", _WATCH, {"120": 2400.0})
    (s,) = z2m.counted_sessions([], [], [_apple_row(ride)], max_hr=180)
    assert s["source"] == "apple_health" and s["zone_2_minutes"] > 0 and s["sport"] == "Outdoor Cycling"


# ── #5371 backstop: the walking readers read the watch's own workouts ───────────────────


WATCH_WALK = _apple("AW-WLK-0200", "Outdoor Walk", "14:00:00", "14:45:00", _WATCH, {"105": 2700.0})
STRAVA_WATCH_WALK = _act("90000200", "Walk", "Apple Watch Ultra", "21:00:00", 2700, avg_hr=104.0)  # 14:00 PDT
WHOOP_WALK_COPY = _act("90000201", "Walk", "WHOOP", "21:01:00", 2600, avg_hr=103.0)


# a lift-only Hevy session on the walk's day: Hevy READ (so the layer is not a floor) with no walking block
LIFT_ONLY = {**HEVY, "start_time": "2026-10-25T16:00:00+00:00", "end_time": "2026-10-25T17:00:00+00:00", "exercises": HEVY["exercises"][:2]}


def _walk_layer(strava, apple):
    return wv.build(window_start=DAY, window_end=DAY, strava_items=[_strava_row(*strava)], hevy_workouts=[LIFT_ONLY], apple_items=apple)


def test_a_walk_only_the_watch_recorded_is_counted():
    layer = _walk_layer((), [_apple_row(WATCH_WALK)])
    assert layer["by_modality"] == {"walking": 0.75}
    assert layer["by_source"]["apple_health"]["hours"] == 0.75
    assert layer["total_is_floor"] is False


def test_a_walk_in_strava_and_apple_is_counted_once_with_or_without_whoops_copy():
    for strava in ((STRAVA_WATCH_WALK,), (STRAVA_WATCH_WALK, WHOOP_WALK_COPY), (WHOOP_WALK_COPY,)):
        layer = _walk_layer(strava, [_apple_row(WATCH_WALK)])
        assert layer["by_modality"]["walking"] == pytest.approx(0.75, abs=0.02), strava


def test_the_watch_backstop_reads_only_the_watchs_own_workouts():
    hevy_lift_walk = _apple("AW-WLK-0201", "Outdoor Walk", "14:00:00", "14:45:00", _HEVY_APP, {"105": 2700.0})
    layer = _walk_layer((), [_apple_row(hevy_lift_walk)])
    assert layer["by_modality"] == {}


def test_unwired_apple_leaves_the_layer_unchanged_and_a_failed_read_is_a_floor():
    base = wv.build(window_start=DAY, window_end=DAY, strava_items=[_strava_row(STRAVA_WATCH_WALK)], hevy_workouts=[LIFT_ONLY])
    assert "apple_health" not in base["by_source"]
    empty = _walk_layer((STRAVA_WATCH_WALK,), [])
    assert empty["total_is_floor"] is False and empty["total_hr"] == base["total_hr"]
    failed = _walk_layer((STRAVA_WATCH_WALK,), None)
    assert failed["total_is_floor"] is True


def test_a_hevy_treadmill_block_claims_the_watch_walk_inside_it():
    treadmill = {**HEVY, "exercises": [{"name": "Treadmill", "sets": [{"duration_sec": 2400}]}]}
    inside = _apple("AW-WLK-0300", "Indoor Walk", "10:00:00", "10:40:00", _WATCH, {"110": 2400.0})
    layer = wv.build(window_start=DAY, window_end=DAY, strava_items=[], hevy_workouts=[treadmill], apple_items=[_apple_row(inside)])
    assert layer["by_modality"] == {"walking": round(2400 / 3600, 2)}, "counted once — the Hevy block's hours"


def test_recent_aerobic_carries_the_watch_walk_as_a_row_without_its_heart_rate():
    target = "2026-10-26"
    block = recent_aerobic.build(target_date=target, today=target, strava_items=[], hevy_workouts=[], apple_items=[_apple_row(WATCH_WALK)])
    (row,) = block["rows"]
    assert row["source"] == "apple_health" and row["modality"] == "walk" and row["moving_min"] == 45.0
    assert row["avg_hr"] is None and row["distance_mi"] is None
    assert block["totals"]["standalone_walks"]["trailing_7d"]["count"] == 1
    with_copy = recent_aerobic.build(
        target_date=target,
        today=target,
        strava_items=[_strava_row(STRAVA_WATCH_WALK)],
        hevy_workouts=[],
        apple_items=[_apple_row(WATCH_WALK)],
    )
    assert with_copy["totals"]["trailing_7d"]["hours"] == 0.75, "the uploaded copy and the watch's own: one walk"


def test_a_pacific_evening_walk_filed_under_the_next_utc_day_lands_on_its_pacific_day():
    evening = _apple("AW-WLK-0400", "Outdoor Walk", "19:00:00", "19:30:00", _WATCH, {"100": 1800.0})  # 02:00Z next day
    next_row = {**_apple_row(evening), "sk": "DATE#2026-10-26", "date": "2026-10-26"}
    counted, _ = wv.apple_sessions([next_row], DAY, DAY)
    assert [c["date"] for c in counted] == [DAY]
    assert wv.apple_sessions([next_row], "2026-10-26", "2026-10-26")[0] == []
