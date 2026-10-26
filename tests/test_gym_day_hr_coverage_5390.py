"""tests/test_gym_day_hr_coverage_5390.py — the box-1 read prints spans and counts, never a health value (#5390).

`scripts/gym_day_hr_coverage.py` reads one gym day's raw Strava and raw Health Auto Export records (S3,
read-only) and reports which records carry heart rate over the lift's span. The fixture is the 2026-10-25
wire's STRUCTURE — a Hevy push spanning the session, WHOOP's pieces and ride, the watch's Indoor Cycling,
the Hevy-origin and pliability-origin HealthKit workouts — with synthetic times and values. Every heart-rate
value below is a sentinel that must never reach the output.
"""

from __future__ import annotations

import io
import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "scripts"), os.path.join(_REPO, "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import gym_day_hr_coverage as g  # noqa: E402
from ingestion.source_registry import raw_date_key_candidates, raw_layout_for  # noqa: E402

DAY = "2026-10-25"
SENTINEL_BPM = 187.25  # never printed
SENTINEL_ZONE = 4321.5  # a zone split, never printed (only the zone SUM, as minutes)


def _act(sid, sport, device, start_utc, secs, hr=True):
    a = {
        "strava_id": sid,
        "sport_type": sport,
        "type": sport,
        "device_name": device,
        "start_date": f"{DAY}T{start_utc}Z",
        "elapsed_time_seconds": secs,
        "moving_time_seconds": secs,
        "has_heartrate": hr,
        "average_heartrate": SENTINEL_BPM if hr else None,
        "max_heartrate": SENTINEL_BPM if hr else None,
        "kilojoules": 999.0,
        "location_city": "Nowhere",
    }
    if hr:
        a.update({"zone1_seconds": SENTINEL_ZONE, "zone2_seconds": secs - SENTINEL_ZONE})
    return a


def _hk(wid, name, start_pdt, end_pdt, ident, source_name, sample_minutes):
    return {
        "id": wid,
        "name": name,
        "start": f"{DAY} {start_pdt} -0700",
        "end": f"{DAY} {end_pdt} -0700",
        "source": {"identifier": ident, "name": source_name},
        "route": [{"latitude": 1.0, "longitude": 2.0}],
        "heartRateData": [
            {"date": f"{DAY} {m} -0700", "Avg": SENTINEL_BPM, "Min": SENTINEL_BPM, "Max": SENTINEL_BPM} for m in sample_minutes
        ],
    }


STRAVA = [
    _act("1", "WeightTraining", "Hevy", "16:40:00", 9600),
    _act("2", "WeightTraining", "WHOOP", "16:58:00", 1000),
    _act("3", "Ride", "WHOOP", "18:00:00", 3600),
    _act("4", "Walk", "WHOOP", "03:00:00", 600),  # 20:00 PDT the evening BEFORE: another Pacific day
]
HK = [
    _hk(
        "A",
        "Indoor Cycling",
        "11:00:00",
        "12:00:00",
        "com.apple.health.SYNTH",
        "Synthetic Apple\xa0Watch",
        ["11:00:00", "11:30:00", "12:00:00"],
    ),
    _hk("B", "Traditional Strength Training", "12:01:00", "12:20:00", "com.hevyapp.hevy", "Hevy", ["12:01:00", "12:10:00"]),
    _hk("B", "Traditional Strength Training", "12:01:00", "12:20:00", "com.hevyapp.hevy", "Hevy", ["12:01:00"]),  # a re-delivery
    _hk("C", "Flexibility", "12:02:00", "12:22:00", "com.romwodllc.romwod", "pliability", ["12:05:00"]),
]


def _report():
    return g.report(DAY, g.strava_records(STRAVA, DAY), g.healthkit_records(HK, DAY))


def test_the_report_names_the_records_and_the_span_and_carries_no_health_value():
    rep = _report()
    text = json.dumps(rep, sort_keys=True)
    for leak in (str(SENTINEL_BPM), str(SENTINEL_ZONE), "999", "Nowhere", "latitude", "Synthetic"):
        assert leak not in text, leak
    s = rep["summary"]
    assert (s["hevy_pushes"], s["hevy_pushes_carrying_own_hr"], s["lift_span_minutes"]) == (1, 1, 160.0)
    assert s["hevy_origin_healthkit_workouts"] == 1 and s["watch_workouts"] == 1
    (rel,) = s["hevy_origin_vs_watch"]
    assert rel["overlap_min"] == 0.0 and rel["hevy_start_minus_watch_end_min"] == 1.0
    # the other heart-rate records cover 16:58–17:14:40, 18:00–19:00 and 19:01–19:20 of the 16:40–19:20 span
    assert s["span_minutes_covered_by_other_hr_records"] == round(1000 / 60 + 60 + 19, 1)
    labels = [(r["kind"], r["who"], r["label"]) for r in rep["records"]]
    assert ("strava", "Hevy", "WeightTraining") in labels and len(labels) == 6, "the evening-before walk is another day"


def test_a_healthkit_workout_is_one_record_with_its_fullest_delivery():
    rows = [r for r in _report()["records"] if r["who"] == "apple_health/hevy"]
    assert len(rows) == 1 and rows[0]["hr_samples"] == 2 and rows[0]["hr_samples_in_lift_span"] == 2


def test_a_day_with_no_hevy_push_reports_no_span():
    rep = g.report(DAY, g.strava_records(STRAVA[2:3], DAY), [])
    assert rep["summary"]["hevy_pushes"] == 0 and rep["summary"]["lift_span_minutes"] is None
    assert rep["records"][0]["minutes_in_lift_span"] is None


class _FakeS3:
    """Read-only surface: get_object / list_objects_v2 only — a write would raise AttributeError."""

    class exceptions:
        class NoSuchKey(Exception):
            pass

    def __init__(self, objects):
        self.objects, self.got = objects, []

    def get_object(self, Bucket, Key):
        self.got.append(Key)
        if Key not in self.objects:
            raise self.exceptions.NoSuchKey(Key)
        return {"Body": io.BytesIO(json.dumps(self.objects[Key]).encode())}

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        fake = self

        class _P:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k} for k in sorted(fake.objects) if k.startswith(Prefix)]}

        return _P()


def test_the_reads_use_the_registry_raw_layout_and_never_write():
    strava_key = raw_date_key_candidates("strava", DAY)[0]
    hae_key = f"{raw_layout_for('apple_health')['prefix']}/2026/10/26_0000000000000000.json"
    s3 = _FakeS3({strava_key: {"fetched_at": "x", "raw": {"activities": STRAVA}}, hae_key: {"data": {"workouts": HK}}})
    acts = g.read_strava(s3, DAY)
    workouts, n = g.read_healthkit(s3, DAY, lag_days=2)
    assert len(acts) == len(STRAVA) and n == 1 and len(workouts) == len(HK)
    assert strava_key in s3.got and all(k in s3.objects or k.startswith("raw/") for k in s3.got)
