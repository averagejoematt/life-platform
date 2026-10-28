"""#5371: the uploader inventory / 7-day proof read is a command, and it reads only what it says it reads."""

import io
import json
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import strava_uploader_proof as proof  # noqa: E402


class _NoSuchKey(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


def _act(sid, device, sport="WeightTraining", start="2026-10-26T09:41:58Z", trainer=True, elapsed="3600"):
    return {
        "strava_id": sid,
        "device_name": device,
        "sport_type": sport,
        "start_date": start,
        "start_date_local": start,
        "trainer": trainer,
        "elapsed_time_seconds": elapsed,  # raw rows carry numbers as strings
        "moving_time_seconds": elapsed,
        "zone2_seconds": "120",
        "distance_meters": "0",
    }


class _S3:
    def __init__(self, days):
        self.days = days
        self.keys = []

    def get_object(self, Bucket, Key):
        self.keys.append(Key)
        day = Key.rsplit("/", 1)[-1][:-5]
        if day not in self.days:
            raise _NoSuchKey()
        return {"Body": io.BytesIO(json.dumps({"raw": {"activities": self.days[day]}}).encode())}


class _CW:
    def __init__(self, values):
        self.values = values
        self.calls = []

    def get_metric_statistics(self, **kw):
        self.calls.append(kw)
        base = datetime(2026, 10, 26, tzinfo=timezone.utc)
        return {"Datapoints": [{"Timestamp": base.replace(day=26 + i), "Maximum": v} for i, v in enumerate(self.values)]}


def test_inventory_counts_distinct_activities_by_uploader_and_reads_only_the_raw_zone():
    s3 = _S3(
        {
            "2026-10-26": [_act(1, "Hevy"), _act(2, "Apple Watch Ultra 4", "Walk", trainer=False)],
            "2026-10-27": [_act(2, "Apple Watch Ultra 4", "Walk", trainer=False), _act(3, "WHOOP")],  # 2 repeats day to day
        }
    )
    w = proof.read_window(s3, date(2026, 10, 26), date(2026, 10, 28))
    assert w["activities"] == 3
    assert w["by_device"] == {"Hevy": 1, "Apple Watch Ultra 4": 1, "WHOOP": 1}
    assert w["trainer_true_by_device"] == {"Hevy": 1, "WHOOP": 1}
    assert w["watch_rows"] == 1
    assert all(k.startswith("raw/matthew/strava/activities/2026/10/") for k in s3.keys)


def test_whoop_rows_are_counted_only_on_gym_days_and_na_without_one():
    s3 = _S3({"2026-10-26": [_act(1, "Hevy"), _act(2, "WHOOP", start="2026-10-26T09:59:00Z")], "2026-10-27": [_act(3, "WHOOP")]})
    w = proof.read_window(s3, date(2026, 10, 26), date(2026, 10, 28))
    assert w["gym_days"] == ["2026-10-26"] and w["whoop_rows_on_gym_days"] == 1
    none = proof.read_window(_S3({"2026-10-27": [_act(3, "WHOOP")]}), date(2026, 10, 26), date(2026, 10, 28))
    assert none["gym_days"] == [] and none["whoop_rows_on_gym_days"] is None, "no gym day must read n/a, never 0 (a pass)"


def test_fold_count_reads_the_seam_on_string_numerics():
    twice = [_act(1, "WHOOP", "Walk", "2026-10-26T09:00:00Z", False), _act(2, "Garmin epix", "Walk", "2026-10-26T09:05:00Z", False)]
    assert proof.fold_count(twice) == 1
    assert proof.fold_count(twice[:1]) == 0


def test_report_compares_with_the_equal_length_window_before_and_prints_no_activity_fields():
    s3 = _S3({"2026-10-20": [_act(9, "WHOOP")], "2026-10-26": [_act(1, "Hevy")]})
    cw = _CW([0.0, 0.0])
    rep = proof.build_report(s3, cw, date(2026, 10, 26), date(2026, 10, 28))
    assert (rep["baseline"]["since"], rep["baseline"]["until_exclusive"]) == ("2026-10-24", "2026-10-26")
    assert rep["window"]["missing_activity_daily_max"] == [0.0, 0.0]
    text = proof.render(rep)
    assert "average_heartrate" not in text and "polyline" not in text
