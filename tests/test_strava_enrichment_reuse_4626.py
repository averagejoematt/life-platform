"""tests/test_strava_enrichment_reuse_4626.py — #4626 epic row.

The trailing-3-days refresh used to re-fetch zones + the HR stream for every heart-rate
activity on every run. Stored enrichment for an unchanged activity is now reused; a changed
duration, a missing field or an unreadable store falls back to the vendor call.
"""

import os

for _k, _v in {"S3_BUCKET": "t", "TABLE_NAME": "life-platform", "USER_ID": "matthew", "AWS_DEFAULT_REGION": "us-west-2"}.items():
    os.environ.setdefault(_k, _v)

from ingestion import strava_lambda as strava  # noqa: E402

DAY = "2026-10-17"
ACT = {"id": 99, "start_date_local": f"{DAY}T07:00:00Z", "has_heartrate": True, "elapsed_time": 1800, "name": "Run"}
STORED = {
    "99": {"zones": {"zone1_seconds": 5, "zone2_seconds": 600}, "hr_recovery": {"hr_peak": 170}, "elapsed": 1800},
}


def _run(monkeypatch, stored, act=ACT):
    calls = {"zones": 0, "streams": 0}

    def zones(sid, secret):
        calls["zones"] += 1
        return {"zone1_seconds": 1}, secret

    def streams(sid, secret):
        calls["streams"] += 1
        return {"hr_peak": 1}, secret

    monkeypatch.setattr(strava, "_fetch_activities_in_range", lambda s, a, b: ([dict(act)], s))
    monkeypatch.setattr(strava, "_fetch_activity_zones", zones)
    monkeypatch.setattr(strava, "_fetch_activity_streams", streams)
    monkeypatch.setattr(strava, "_stored_enrichment", lambda d: stored)
    out = strava.fetch_day({"access_token": "x"}, DAY)
    return out["activities"][0], calls


def test_unchanged_activity_reuses_stored_zones_and_stream(monkeypatch):
    rec, calls = _run(monkeypatch, STORED)
    assert calls == {"zones": 0, "streams": 0}
    assert rec["zone2_seconds"] == 600 and rec["hr_recovery"] == {"hr_peak": 170}


def test_changed_duration_refetches(monkeypatch):
    rec, calls = _run(monkeypatch, STORED, dict(ACT, elapsed_time=2400))
    assert calls == {"zones": 1, "streams": 1}


def test_new_activity_or_unreadable_store_refetches(monkeypatch):
    _, calls = _run(monkeypatch, {})
    assert calls == {"zones": 1, "streams": 1}


def test_missing_stream_only_refetches_the_stream(monkeypatch):
    stored = {"99": dict(STORED["99"], hr_recovery={})}
    _, calls = _run(monkeypatch, stored)
    assert calls == {"zones": 0, "streams": 1}


def test_stored_enrichment_read_failure_is_soft(monkeypatch):
    class Boom:
        def Table(self, n):
            raise RuntimeError("no ddb")

    monkeypatch.setattr(strava.boto3, "resource", lambda *a, **k: Boom())
    assert strava._stored_enrichment(DAY) == {}
