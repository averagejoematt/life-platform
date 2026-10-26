#!/usr/bin/env python3
"""tests/test_hae_workouts_all_types_4973.py — every Apple workout type as one owner-only summary
per workout id on the apple_health day row, joined to the one-workout-identity resolver (#4973).

The contracts, each a caller-visible fact about the stored row or the resolved identity:

  * every workout type the payload carries is summarised (not only the recovery types), with
    HAE's own vendor keys kept verbatim (type, start/end, duration, energy, distance, avg/max HR,
    effort, source device) — nothing renamed, nothing picked;
  * per-sample series are summarised (heart rate, running power / stride / ground contact /
    vertical oscillation), with the HR distribution in 5-bpm bins and HR recovery derived;
  * the route and every lat/lon never reach the table (route_points is the only trace);
  * identity by vendor id: a re-send of the same workout is the same map entry, field-merged
    (a partial re-send never erases a key); a workout with no id is not stored;
  * day frame: the UTC day of the start (an 18:00 PDT run is on the next DATE#);
  * floats reach DynamoDB as Decimal;
  * the stored day row feeds `training.workout_identity` directly, and a session present in
    Apple, Strava and Hevy resolves to ONE identity counted once; a WHOOP workout HealthKit
    re-exports is its own source and folds into the watch's identity, never beside it;
  * `apple_workouts` is tiered owner-only and has a docs/SCHEMA.md row.

FIXTURE: tests/fixtures/hae_workouts_mixed_4973.json is SYNTHETIC — the key names follow Health
Auto Export's v2 workout export (checked against the shape of a live raw-archive payload,
read-only, 2026-10-24); every value, id and device name is invented.
"""

import json
import os
import re
import sys
from decimal import Decimal

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("DYNAMODB_TABLE", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import health_auto_export_lambda as hae  # noqa: E402
from ingestion import health_auto_export_workouts as hw  # noqa: E402
from privacy.field_tiers import TIER_OWNER_ONLY, tier_of  # noqa: E402
from training import workout_identity as wi  # noqa: E402

PK = "USER#matthew#SOURCE#apple_health"
with open(os.path.join(ROOT, "tests", "fixtures", "hae_workouts_mixed_4973.json"), encoding="utf-8") as _fh:
    FIXTURE = json.load(_fh)
WORKOUTS = FIXTURE["payload"]["data"]["workouts"]
RESEND = FIXTURE["resend"]["data"]["workouts"]


class StatefulTable:
    """Applies the writer's SET (plain + if_not_exists) to one in-memory item per key."""

    def __init__(self, get_error=None):
        self.items = {}
        self.get_error = get_error

    def get_item(self, Key=None, **kw):
        if self.get_error:
            raise self.get_error
        item = self.items.get(Key["sk"])
        return {"Item": dict(item)} if item else {}

    def update_item(self, Key=None, UpdateExpression="", ExpressionAttributeNames=None, ExpressionAttributeValues=None, **kw):
        item = self.items.setdefault(Key["sk"], {})
        names, values = ExpressionAttributeNames, ExpressionAttributeValues
        for attr, rhs, guarded in re.findall(r"(#\w+) = (if_not_exists\(#\w+, (:\w+)\)|:\w+)", UpdateExpression[4:]):
            if guarded:
                item.setdefault(names[attr], values[guarded])
            else:
                item[names[attr]] = values[rhs]

    def row(self, day):
        return self.items.get(f"DATE#{day}", {})


def _write(table, workouts):
    return hw.write_apple_workouts(workouts, table, hae.parse_date_str, lambda d: {"pk": PK, "sk": f"DATE#{d}"}, phase_for_date=None)


def _stored():
    table = StatefulTable()
    assert _write(table, WORKOUTS) == 2  # 2026-10-14 and 2026-10-15
    return table


def _walk(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


# ── every type, vendor keys verbatim ─────────────────────────────────────────


def test_every_type_with_an_id_is_summarised_on_its_utc_start_day():
    t = _stored()
    day14, day15 = t.row("2026-10-14")["apple_workouts"], t.row("2026-10-15")["apple_workouts"]
    assert set(day14) == {"FX-STR-0001", "FX-WLK-0002", "FX-WHP-0005"}
    # 18:00 PDT run and 20:00 PDT flexibility start after 00:00 UTC → the next DATE# (#3677 frame)
    assert set(day15) == {"FX-RUN-0003", "FX-FLX-0004"}
    names = {v["name"] for d in (day14, day15) for v in d.values()}
    assert names == {"Traditional Strength Training", "Indoor Walk", "Functional Strength Training", "Outdoor Run", "Flexibility"}


def test_a_workout_without_an_id_is_not_stored():
    assert hw.summarize_workout({"name": "Walking", "start": "2026-10-14 12:00:00 -0700"}) is None
    t = _stored()
    stored = [v for d in t.items.values() for v in d["apple_workouts"].values()]
    assert all(v.get("id") for v in stored) and not any(v["start"].startswith("2026-10-14 12:00") for v in stored)


def test_vendor_keys_are_kept_under_their_own_names():
    walk = _stored().row("2026-10-14")["apple_workouts"]["FX-WLK-0002"]
    assert walk["start"] == "2026-10-14 09:13:00 -0700" and walk["end"] == "2026-10-14 09:58:00 -0700"
    assert walk["duration"] == Decimal("2700.0")
    assert walk["activeEnergyBurned"] == {"qty": Decimal("301.5"), "units": "kcal"}
    assert walk["distance"] == {"qty": Decimal("2.61"), "units": "mi"}
    assert walk["avgHeartRate"]["qty"] == Decimal("122.0") and walk["maxHeartRate"]["qty"] == 147
    assert walk["heartRate"]["min"] == {"qty": 97, "units": "bpm"}
    assert walk["estimatedEffortScore"] == {"qty": 5, "units": "appleEffortScore"}
    assert walk["source"]["name"] == "Fixture’s Apple Watch"
    assert walk["isIndoor"] is True and walk["location"] == "Indoor"


def test_no_float_reaches_dynamodb():
    t = _stored()
    floats = [(k, v) for d in t.items.values() for k, v in _walk(d) if isinstance(v, float)]
    assert not floats, floats[:5]


# ── series: summarised, HR distribution, HR recovery, running dynamics ───────


def test_running_dynamics_series_are_summarised_by_vendor_key():
    run = _stored().row("2026-10-15")["apple_workouts"]["FX-RUN-0003"]
    series = run["derived"]["series"]
    for key in ("runningPower", "runningStrideLength", "runningGroundContactTime", "runningVerticalOscillation", "heartRateData"):
        assert key in series, key
    assert series["runningPower"] == {"n": 30, "mean": Decimal("254.5"), "min": Decimal("240.0"), "max": Decimal("269.0"), "units": "W"}
    assert series["runningGroundContactTime"]["units"] == "ms"
    assert run["derived"]["counts"] == {"segments": 1, "splits": 1}


def test_hr_distribution_covers_the_series_in_5bpm_bins():
    walk = _stored().row("2026-10-14")["apple_workouts"]["FX-WLK-0002"]
    bins = walk["derived"]["hr_seconds_by_bpm5"]
    # 45 per-minute samples, 100..144 bpm → nine 5-bpm bins of 5 minutes each
    assert set(bins) == {str(b) for b in range(100, 145, 5)}
    assert all(v == Decimal("300.0") for v in bins.values())
    assert walk["derived"]["series"]["heartRateData"]["max"] == 147  # the series' own Max honoured


def test_hr_recovery_is_derived_from_the_recovery_series():
    rec = _stored().row("2026-10-14")["apple_workouts"]["FX-WLK-0002"]["derived"]["hr_recovery"]
    # last in-workout sample 144 bpm; recovery samples every 15 s from 140 down by 2
    assert rec["end_bpm"] == 144 and rec["samples"] == 12
    assert rec["bpm_60s"] == 134 and rec["drop_60s"] == 10
    assert rec["bpm_120s"] == 126 and rec["drop_120s"] == 18


def test_absent_series_means_absent_derived_fields():
    flex = _stored().row("2026-10-15")["apple_workouts"]["FX-FLX-0004"]
    assert set(flex["derived"]) == {"version"}


# ── GPS never in the table ───────────────────────────────────────────────────


def test_route_and_coordinates_never_reach_the_table():
    t = _stored()
    keys = {k for d in t.items.values() for k, _ in _walk(d)}
    assert not keys & hw.GPS_KEYS, keys & hw.GPS_KEYS
    run = t.row("2026-10-15")["apple_workouts"]["FX-RUN-0003"]
    assert run["derived"]["route_points"] == 5
    assert run["activities"][0]["metrics"]["distance"]["qty"] == Decimal("4989.0")  # the leg kept, its route not


# ── identity by vendor id: re-sends ──────────────────────────────────────────


def test_a_resend_is_the_same_entry_field_merged():
    t = _stored()
    _write(t, RESEND)
    walks = t.row("2026-10-14")["apple_workouts"]
    assert len(walks) == 3, "a re-send never adds a second entry"
    walk = walks["FX-WLK-0002"]
    assert walk["activeEnergyBurned"]["qty"] == Decimal("305.0"), "a key the re-send carries wins"
    assert walk["derived"]["hr_recovery"]["end_bpm"] == 144, "a key the partial re-send lacks is kept"
    assert walk["distance"]["qty"] == Decimal("2.61")


def test_an_unreadable_stored_map_skips_the_day_rather_than_overwrite():
    t = StatefulTable(get_error=RuntimeError("throttled"))
    assert _write(t, WORKOUTS) == 0 and not t.items


# ── the handler wires it ─────────────────────────────────────────────────────


def test_handler_writes_the_all_type_summary(monkeypatch):
    table = StatefulTable()

    class _S3:
        class exceptions:
            class NoSuchKey(Exception):
                pass

        def get_object(self, **kw):
            raise self.exceptions.NoSuchKey()

        def put_object(self, **kw):
            return {}

    monkeypatch.setattr(hae, "table", table)
    monkeypatch.setattr(hae, "s3_client", _S3())
    monkeypatch.setattr(hae, "get_api_key", lambda: "k")
    monkeypatch.setattr(hae, "merge_day_to_dynamo", lambda *a, **k: None)
    event = {"headers": {"authorization": "Bearer k"}, "body": json.dumps(FIXTURE["payload"])}
    resp = hae.lambda_handler(event, None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200 and body["workout_summary_days"] == 2
    assert body["recovery_days"] == 1  # the v1.6.0 recovery aggregate (Flexibility) still runs
    assert len(table.row("2026-10-14")["apple_workouts"]) == 3


# ── joined to the one-workout-identity resolver ──────────────────────────────

HEVY_SESSION = {
    "sk": "DATE#2026-10-14#WORKOUT#hv-fx01",
    "start_time": "2026-10-14T15:00:00+00:00",  # 08:00 PDT
    "end_time": "2026-10-14T17:00:00+00:00",
    "exercises": [
        {"name": "Squat (Barbell)", "sets": [{"reps": 5, "weight_kg": 80}]},
        {"name": "Treadmill", "sets": [{"duration_sec": 2700}]},
    ],
}
STRAVA_DAY = {
    "sk": "DATE#2026-10-14",
    "activities": [
        {
            "strava_id": "99001",
            "sport_type": "Walk",
            "start_date": "2026-10-14T16:12:00Z",
            "elapsed_time_seconds": 2760,
            "moving_time_seconds": 2650,
        }
    ],
}


def _resolve_stored():
    t = _stored()
    rows = [hw._plain(t.row("2026-10-14")), hw._plain(t.row("2026-10-15"))]
    return wi.resolve_workout_identities(apple=rows, strava=[STRAVA_DAY], hevy=[HEVY_SESSION])


def test_one_session_in_apple_strava_and_hevy_is_one_identity_counted_once():
    walks = [i for i in _resolve_stored() if i["family"] == "walking"]
    assert len(walks) == 1
    w = walks[0]
    assert w["members"] == {"hevy": ["hv-fx01#walking"], "strava": ["99001"], "apple_health": ["FX-WLK-0002"]}
    assert (w["seconds_source"], w["seconds"]) == ("hevy", 2700)


def test_a_whoop_workout_healthkit_reexports_folds_into_the_watch_lift():
    strength = [i for i in _resolve_stored() if i["family"] == "strength"]
    assert len(strength) == 1, "the watch's lift and WHOOP's HealthKit copy are one session, not two"
    assert strength[0]["members"] == {"hevy": ["hv-fx01#strength"], "apple_health": ["FX-STR-0001"], "apple_health/whoop": ["FX-WHP-0005"]}


def test_resolved_totals_count_every_stored_type_once():
    t = wi.identity_totals(_resolve_stored())
    # strength (1) + walking (1) + the evening run (1) + flexibility (1) — Flexibility is the
    # `mobility` family since #5369 (the pliability app writes its sessions into HealthKit under it)
    assert t["sessions"] == 4
    assert set(t["by_family"]) == {"strength", "walking", "running", "mobility"}


def test_a_row_seen_twice_is_one_member():
    t = _stored()
    row = hw._plain(t.row("2026-10-14"))
    once = wi.resolve_workout_identities(apple=[row])
    twice = wi.resolve_workout_identities(apple=[row, row])
    assert len(once) == len(twice)


def test_the_public_projection_carries_no_device_or_place():
    for ident in _resolve_stored():
        pub = json.dumps(wi.public_projection(ident))
        assert "Fixture" not in pub and "Outdoor" not in pub and "latitude" not in pub


# ── tiered; documented ───────────────────────────────────────────────────────


def test_apple_workouts_is_tiered_owner_only():
    assert tier_of("apple_health", hw.WORKOUTS_FIELD) == TIER_OWNER_ONLY


def test_apple_workouts_has_a_schema_row():
    with open(os.path.join(ROOT, "docs", "SCHEMA.md"), encoding="utf-8") as fh:
        assert f"| `{hw.WORKOUTS_FIELD}` |" in fh.read()
