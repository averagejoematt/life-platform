"""tests/test_strava_reingest_decimal_5255.py — #5255.

Re-ingesting an already-stored Strava day raised `Decimal + float`: #4626 reuses the stored
zones of an unchanged activity, and boto3 hands those back as Decimal, while a re-fetched
activity's zones are API floats. `transform()`'s day sums then mixed the two and the whole
day errored on every hourly run until it left the trailing window (2026-10-18, 10-21 → 10-22).

The fixture is the wire shape: a boto3-deserialized item (every number a Decimal).
"""

import os
from decimal import Decimal

for _k, _v in {"S3_BUCKET": "t", "TABLE_NAME": "life-platform", "USER_ID": "matthew", "AWS_DEFAULT_REGION": "us-west-2"}.items():
    os.environ.setdefault(_k, _v)

from ingestion import strava_lambda as strava  # noqa: E402

DAY = "2026-10-18"
STORED_ACT = {"id": 1, "start_date_local": f"{DAY}T07:00:00Z", "has_heartrate": True, "elapsed_time": 1800, "moving_time": 1700}
FRESH_ACT = {"id": 2, "start_date_local": f"{DAY}T12:00:00Z", "has_heartrate": True, "elapsed_time": 1000, "moving_time": 950}

# What boto3's resource API returns for a stored row: numbers are Decimal, all the way down.
STORED_ROW = {
    "activities": [
        {
            "strava_id": "1",
            "elapsed_time_seconds": Decimal("1800"),
            "moving_time_seconds": Decimal("1700"),
            "zone1_seconds": Decimal("1100"),
            "zone2_seconds": Decimal("600.5"),
            "hr_recovery": {"hr_peak": Decimal("170"), "hr_30s_recovery": Decimal("22")},
        }
    ]
}


def _fake_table(monkeypatch, item):
    class Tbl:
        def get_item(self, Key):
            return {"Item": item}

    monkeypatch.setattr(strava.boto3, "resource", lambda *a, **k: type("R", (), {"Table": lambda s, n: Tbl()})())


def _reingest(monkeypatch):
    _fake_table(monkeypatch, STORED_ROW)
    monkeypatch.setattr(strava, "_fetch_activities_in_range", lambda s, a, b: ([dict(STORED_ACT), dict(FRESH_ACT)], s))
    monkeypatch.setattr(strava, "_fetch_activity_zones", lambda sid, s: ({"zone1_seconds": 700.0, "zone2_seconds": 300.0}, s))
    monkeypatch.setattr(strava, "_fetch_activity_streams", lambda sid, s: ({"hr_peak": 150, "hr_30s_recovery": 18}, s))
    return strava.fetch_day({"access_token": "x"}, DAY)


def _decimals(obj, path="$"):
    if isinstance(obj, Decimal):
        return [path]
    if isinstance(obj, dict):
        return [p for k, v in obj.items() for p in _decimals(v, f"{path}.{k}")]
    if isinstance(obj, list):
        return [p for i, v in enumerate(obj) for p in _decimals(v, f"{path}[{i}]")]
    return []


def test_reingest_of_a_stored_day_mixing_decimal_and_float_transforms(monkeypatch):
    raw = _reingest(monkeypatch)
    [rec] = strava.transform(raw, DAY)
    assert rec["activity_count"] == 2
    assert rec["total_zone2_seconds"] == 900.5
    assert rec["total_moving_time_seconds"] == 2650


def test_stored_activity_was_reused_not_refetched(monkeypatch):
    raw = _reingest(monkeypatch)
    stored = next(a for a in raw["activities"] if a["strava_id"] == "1")
    assert stored["zone2_seconds"] == 600.5 and stored["hr_recovery"]["hr_peak"] == 170


def test_no_decimal_crosses_the_stored_read_boundary(monkeypatch):
    """The guard over every aggregate sum in `transform()`: whatever field it sums, no value
    reaching it can be a Decimal, because nothing read back from the store leaves the reader
    as one. A new reused field inherits the guard without a new test."""
    _fake_table(monkeypatch, STORED_ROW)
    assert _decimals(strava._stored_enrichment(DAY)) == []
    assert _decimals(_reingest(monkeypatch)) == []


def test_unchanged_duration_still_matches_after_normalisation(monkeypatch):
    """Decimal('1800') normalised must still equal the API's int 1800, or reuse silently stops."""
    _fake_table(monkeypatch, STORED_ROW)
    assert strava._stored_enrichment(DAY)["1"]["elapsed"] == STORED_ACT["elapsed_time"]
