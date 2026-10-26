"""tests/test_workout_identity_4973.py — one workout identity across Apple Health, Strava and Hevy (#4973).

Fixture tests only: no Apple Watch workout exists in the store yet (the watch is configured under
#4968), so the Apple records are built in the shape `health_auto_export_lambda.process_workouts`
writes (id, name, start/end in HAE's 'YYYY-MM-DD HH:MM:SS -0700', duration_min) plus the `route`
HAE carries for an outdoor workout. Strava rows are the stored `_normalize` shape (strava_id,
sport_type, start_date, elapsed/moving seconds, summary_polyline, location_*); Hevy rows are the
`DATE#d#WORKOUT#<id>` sub-item shape walking_volume reads.

Pinned: (1) a Hevy lift Apple also recorded as Traditional Strength Training is ONE identity;
(2) a Strava walk Apple recorded as Walking plus the Hevy walk block of the same session is ONE
identity, counted once — and agrees with walking_volume's #4068 de-dup; (3) a lone Apple workout
is its own identity; (4) the route / GPS / location / free-text labels never reach the public
projection; plus mutation controls on the overlap threshold, the family match and the
one-record-per-source rule.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from training import (
    walking_volume as wv,  # noqa: E402
    workout_identity as wi,  # noqa: E402
)

# ── the session: 2026-10-14, a Hevy "Engine" session 15:00–17:00 UTC = 08:00–10:00 PDT ──
HEVY_SESSION = {
    "pk": "USER#matthew#SOURCE#hevy",
    "sk": "DATE#2026-10-14#WORKOUT#hv-7f3a",
    "date": "2026-10-14",
    "title": "Foundation - Engine - 2 - 4",
    "start_time": "2026-10-14T15:00:00+00:00",
    "end_time": "2026-10-14T17:00:00+00:00",
    "exercises": [
        {"name": "Squat (Barbell)", "sets": [{"reps": 5, "weight_kg": 80}, {"reps": 5, "weight_kg": 80}]},
        {"name": "Bench Press (Barbell)", "sets": [{"reps": 5, "weight_kg": 60}]},
        {"name": "Treadmill", "sets": [{"duration_sec": 2700, "distance_m": 4200}]},
    ],
}
APPLE_STRENGTH = {
    "id": "AP-1111",
    "name": "Traditional Strength Training",
    "category": "other",
    "start": "2026-10-14 08:01:00 -0700",
    "end": "2026-10-14 09:58:00 -0700",
    "duration_min": 117.0,
    "active_energy_kcal": 512.0,
    "is_indoor": True,
}
# the treadmill block, seen by the wrist (WHOOP → Strava) and by the watch (Apple "Walking")
STRAVA_WALK = {
    "strava_id": "16112233445",
    "name": "Morning Walk",
    "type": "Walk",
    "sport_type": "Walk",
    "start_date": "2026-10-14T16:12:00Z",
    "elapsed_time_seconds": 2760,
    "moving_time_seconds": 2650,
    "device_name": "WHOOP",
    "summary_polyline": "a~l~Fjk~uOwHJy@P",
    "location_city": "Seattle",
    "location_state": "WA",
    "timezone": "(GMT-08:00) America/Los_Angeles",
}
APPLE_WALK = {
    "id": "AP-2222",
    "name": "Indoor Walk",
    "category": "other",
    "start": "2026-10-14 09:13:00 -0700",
    "end": "2026-10-14 09:58:00 -0700",
    "duration_min": 45.0,
    "is_indoor": True,
}
# an evening outdoor walk only the watch recorded — with its route
APPLE_LONE = {
    "id": "AP-3333",
    "name": "Outdoor Walk",
    "category": "other",
    "start": "2026-10-14 18:30:00 -0700",
    "end": "2026-10-14 19:10:00 -0700",
    "duration_min": 40.0,
    "is_indoor": False,
    "route": [
        {"lat": 47.6801, "lon": -122.3273, "altitude": 61.2, "timestamp": "2026-10-14 18:30:05 -0700"},
        {"lat": 47.6812, "lon": -122.3290, "altitude": 62.0, "timestamp": "2026-10-14 18:31:05 -0700"},
    ],
}
STRAVA_DAY = {"pk": "USER#matthew#SOURCE#strava", "sk": "DATE#2026-10-14", "date": "2026-10-14", "activities": [STRAVA_WALK]}


def _resolve(**kw):
    base = {"apple": [APPLE_STRENGTH, APPLE_WALK, APPLE_LONE], "strava": [STRAVA_DAY], "hevy": [HEVY_SESSION]}
    base.update(kw)
    return wi.resolve_workout_identities(**base)


def _by_family(ids):
    out = {}
    for i in ids:
        out.setdefault(i["family"], []).append(i)
    return out


def test_the_lift_apple_also_recorded_is_one_identity():
    strength = _by_family(_resolve())["strength"]
    assert len(strength) == 1
    s = strength[0]
    assert s["members"] == {"hevy": ["hv-7f3a#strength"], "apple_health": ["AP-1111"]}
    assert s["seconds_source"] == "hevy" and s["seconds"] == 7200 - 2700, "counted once, from the logged session"


def test_the_walk_three_ways_is_one_identity_counted_once():
    walks = _by_family(_resolve())["walking"]
    inside = [w for w in walks if "hevy" in w["sources"]]
    assert len(inside) == 1
    w = inside[0]
    assert w["members"] == {"hevy": ["hv-7f3a#walking"], "strava": ["16112233445"], "apple_health": ["AP-2222"]}
    assert (w["seconds_source"], w["seconds"]) == ("hevy", 2700)


def test_a_lone_apple_workout_is_its_own_identity():
    lone = [i for i in _resolve() if i["sources"] == ["apple_health"]]
    assert len(lone) == 1 and lone[0]["members"] == {"apple_health": ["AP-3333"]}
    assert lone[0]["seconds"] == 2400 and lone[0]["family"] == "walking"


def test_totals_count_each_identity_once():
    t = wi.identity_totals(_resolve())
    assert t["sessions"] == 3
    assert t["minutes"] == round((4500 + 2700 + 2400) / 60.0, 1)
    assert t["by_family"] == {"strength": {"sessions": 1, "minutes": 75.0}, "walking": {"sessions": 2, "minutes": 85.0}}
    # the naive per-source sum this replaces: 6 records, the session's walk counted three times
    naive = (
        len(wi.hevy_members([HEVY_SESSION]))
        + len(wi.strava_members([STRAVA_DAY]))
        + len(wi.apple_members([APPLE_STRENGTH, APPLE_WALK, APPLE_LONE]))
    )
    assert naive == 6


def test_agrees_with_walking_volume_on_the_shared_walk():
    """The walking-volume layer's #4068 de-dup (Hevy claims the session, the WHOOP walk inside it
    counts 0) and this resolver give the same walking minutes for the Hevy+Strava pair."""
    day = wv.walking_minutes_for_day(day="2026-10-14", strava_items=[STRAVA_DAY], hevy_workouts=[HEVY_SESSION])
    ids = wi.resolve_workout_identities(strava=[STRAVA_DAY], hevy=[HEVY_SESSION])
    assert day["minutes"] == wi.identity_totals(ids)["by_family"]["walking"]["minutes"] == 45.0


def test_the_same_vendor_record_twice_is_one_member():
    ids = _resolve(strava=[STRAVA_DAY, dict(STRAVA_DAY)], apple=[APPLE_WALK, dict(APPLE_WALK)])
    walking = [i for i in ids if i["family"] == "walking"]
    assert len(walking) == 1 and walking[0]["members"]["strava"] == ["16112233445"]


def test_untimed_record_is_its_own_identity_and_says_so():
    ids = wi.resolve_workout_identities(apple=[{"id": "AP-9", "name": "Walking", "duration_min": 30}])
    assert len(ids) == 1 and ids[0]["untimed"] is True and ids[0]["seconds"] == 1800
    assert wi.identity_totals(ids)["untimed"] == 1


# ── privacy: the route and every location field stay owner-only ──────────────────


_FORBIDDEN_VALUES = ("47.68", "-122.32", "a~l~F", "Seattle", "America/Los_Angeles", "Morning Walk", "Foundation - Engine")


def test_public_projection_carries_no_route_gps_or_label():
    ids = _resolve()
    owner = json.dumps([i["owner_only"] for i in ids], default=str)
    assert "47.6801" in owner and "a~l~F" in owner, "the owner-only block keeps the route (stored ≠ published)"
    public = json.dumps([wi.public_projection(i) for i in ids], default=str)
    leaked = [v for v in _FORBIDDEN_VALUES if v in public]
    assert not leaked, f"owner-only values on the public projection: {leaked}"

    def keys(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield k
                yield from keys(v)
        elif isinstance(o, list):
            for v in o:
                yield from keys(v)

    assert not set(keys([wi.public_projection(i) for i in ids])) & (wi.OWNER_ONLY_KEYS | {"owner_only"})


def test_privacy_guard_can_fail(monkeypatch):
    """Mutation control: empty OWNER_ONLY_KEYS and a stray route reaches the projection (with it
    armed, the route AND its lat are stripped — two layers, so a one-key mutation stays caught)."""
    ident = {"workout_identity": "x", "owner_only": {}, "extra": {"route": [{"lat": 47.6801}]}}
    assert "47.6801" not in json.dumps(wi.public_projection(ident))
    monkeypatch.setattr(wi, "OWNER_ONLY_KEYS", frozenset())
    ident = {"workout_identity": "x", "owner_only": {}, "extra": {"route": [{"lat": 47.6801}]}}
    assert "47.6801" in json.dumps(wi.public_projection(ident))


# ── mutation controls on the clustering rule ──────────────────────────────────────


def test_below_half_the_shorter_interval_is_two_workouts():
    """A Strava walk whose overlap with the session is 40% of the walk is NOT the session's block."""
    w = dict(STRAVA_WALK, start_date="2026-10-14T16:42:00Z", elapsed_time_seconds=3000)  # 16:42–17:32, 18 min inside
    ids = wi.resolve_workout_identities(strava=[{"activities": [w]}], hevy=[HEVY_SESSION])
    assert len([i for i in ids if i["family"] == "walking"]) == 2
    w = dict(STRAVA_WALK, start_date="2026-10-14T16:30:00Z", elapsed_time_seconds=3000)  # 30 of 50 min inside = 60%
    ids = wi.resolve_workout_identities(strava=[{"activities": [w]}], hevy=[HEVY_SESSION])
    assert len([i for i in ids if i["family"] == "walking"]) == 1


def test_threshold_mutation_changes_the_answer(monkeypatch):
    monkeypatch.setattr(wi, "OVERLAP_SHARE", 1.01)  # nothing can overlap more than fully
    assert wi.identity_totals(_resolve())["sessions"] == 6


def test_a_different_family_never_merges():
    ride = dict(STRAVA_WALK, sport_type="Ride", type="Ride")
    ids = wi.resolve_workout_identities(strava=[{"activities": [ride]}], hevy=[HEVY_SESSION])
    fams = sorted(i["family"] for i in ids)
    assert fams == ["cycling", "strength", "walking"]


def test_two_records_from_one_source_are_never_one_identity():
    """Two Strava records over the same minutes are Strava's own de-dup problem (strava_read_seam), not
    this resolver's clustering to fold: a pair the seam keeps (a Walk and a Hike — the seam folds the
    same sport only) stays two identities, and only ONE of them joins the Apple walk. Since #5369 the
    resolver reads Strava THROUGH the seam, so a same-sport twin from a second device is folded there."""
    twin = dict(STRAVA_WALK, strava_id="16112233446", device_name="Garmin", sport_type="Hike", type="Hike")
    ids = wi.resolve_workout_identities(strava=[{"activities": [STRAVA_WALK, twin]}], apple=[APPLE_WALK])
    assert len(ids) == 2
    assert sorted(len(i["sources"]) for i in ids) == [1, 2]
    same_sport = dict(STRAVA_WALK, strava_id="16112233446", device_name="Garmin")
    ids = wi.resolve_workout_identities(strava=[{"activities": [STRAVA_WALK, same_sport]}], apple=[APPLE_WALK])
    assert len(ids) == 1 and len(ids[0]["members"]["strava"]) == 1, "the seam folds a same-sport twin before clustering"


def test_both_timestamp_frames_parse_to_the_same_instant():
    want = wi._parse("2026-10-14T15:01:00+00:00").timestamp()
    got = {raw: wi._parse(raw).timestamp() for raw in ("2026-10-14 08:01:00 -0700", "2026-10-14T15:01:00Z")}
    assert set(got.values()) == {want}, got
