"""tests/test_ingest_liveness_standalone.py — #466/#467 (epic #459).

The pattern-exempt standalone ingesters (hevy, notion, dropbox) never wrote the
ER-01 INGEST_HEALTH sentinel, so their ingest-consecutive-failures alarms and
pipeline_health_check coverage watched metrics that could not exist. These
tests pin the new wiring:

  - hevy_backfill records attempt+outcome at every terminal path and RAISES on
    a fatal HevyAPIError (Lambda Errors/DLQ engage instead of a swallowed 500).
  - record_ingest_health (the public standalone entry) writes the sentinel via
    ingest_health.update_outcome streak math and emits the EMF line.
"""

import os
import sys
import types

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")


@pytest.fixture(autouse=True)
def _stub_aws(monkeypatch):
    """Stub boto3 before the hevy modules build clients at import time."""
    fake_boto3 = types.ModuleType("boto3")

    class _FakeTable:
        def __init__(self):
            self.items = {}

        def put_item(self, Item=None, **kw):
            if Item:
                self.items[(Item.get("pk"), Item.get("sk"))] = Item

        def get_item(self, Key=None, **kw):
            item = self.items.get((Key.get("pk"), Key.get("sk"))) if Key else None
            return {"Item": item} if item else {}

    class _FakeDDBResource:
        def Table(self, name):
            return _FakeTable()

    fake_boto3.client = lambda *a, **k: object()
    fake_boto3.resource = lambda *a, **k: _FakeDDBResource()
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)


def _load_backfill():
    import hevy_backfill_lambda as hb

    return hb


UPDATED_EVENT = {
    "type": "updated",
    "workout": {"id": "wkt_1", "title": "Push", "start_time": "2026-07-01T17:00:00Z"},
}


def _quiet_pipeline(monkeypatch, hb):
    monkeypatch.setattr(hb, "load_since", lambda: "2026-07-01T00:00:00+00:00")
    monkeypatch.setattr(hb, "save_since", lambda ts: None)
    monkeypatch.setattr(hb, "archive_raw", lambda wid, ev: None)
    monkeypatch.setattr(
        hb, "normalize_workout", lambda ev: {"date": "2026-07-01", "workout_uid": "wkt_1", "set_count": 3, "total_volume_kg": 100.0}
    )
    monkeypatch.setattr(hb, "write_normalized", lambda rec: None)
    monkeypatch.setattr(hb, "_derive_training_notes", lambda rec: None)


def test_clean_run_records_success_sentinel(monkeypatch):
    hb = _load_backfill()
    _quiet_pipeline(monkeypatch, hb)
    monkeypatch.setattr(hb, "fetch_events_page", lambda since, page, page_size: {"page_count": 1, "events": [UPDATED_EVENT]})

    calls = []
    monkeypatch.setattr(hb, "record_ingest_health", lambda table, src, log, **kw: calls.append((src, kw)))
    monkeypatch.setattr(hb, "_INGEST_HEALTH_AVAILABLE", True)

    out = hb.lambda_handler({}, None)

    assert out["statusCode"] == 200
    assert calls == [("hevy", {"attempted": True, "succeeded": True, "error_class": "none"})]


def test_fatal_api_error_records_failure_and_raises(monkeypatch):
    hb = _load_backfill()
    from hevy_common import HevyAPIError

    _quiet_pipeline(monkeypatch, hb)

    def _boom(since, page, page_size):
        raise HevyAPIError("Hevy GET /v1/workouts/events → HTTP 401: bad key")

    monkeypatch.setattr(hb, "fetch_events_page", _boom)

    calls = []
    monkeypatch.setattr(hb, "record_ingest_health", lambda table, src, log, **kw: calls.append((src, kw)))
    monkeypatch.setattr(hb, "_INGEST_HEALTH_AVAILABLE", True)

    with pytest.raises(HevyAPIError):
        hb.lambda_handler({}, None)

    assert calls == [("hevy", {"attempted": True, "succeeded": False, "error_class": "auth"})]


def test_per_event_error_records_parse_failure_but_returns_200(monkeypatch):
    hb = _load_backfill()
    _quiet_pipeline(monkeypatch, hb)
    monkeypatch.setattr(hb, "fetch_events_page", lambda since, page, page_size: {"page_count": 1, "events": [UPDATED_EVENT]})
    monkeypatch.setattr(hb, "normalize_workout", lambda ev: (_ for _ in ()).throw(KeyError("exercises")))

    calls = []
    monkeypatch.setattr(hb, "record_ingest_health", lambda table, src, log, **kw: calls.append((src, kw)))
    monkeypatch.setattr(hb, "_INGEST_HEALTH_AVAILABLE", True)

    out = hb.lambda_handler({}, None)

    assert out["statusCode"] == 200  # partial failure: since not advanced, run completes
    assert calls == [("hevy", {"attempted": True, "succeeded": False, "error_class": "parse"})]


# ── #467: notion + dropbox emit the sentinel ──────────────────────────────


def test_notion_success_and_failure_paths_record_sentinel(monkeypatch):
    sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))
    import notion_lambda as nl

    calls = []
    monkeypatch.setattr(nl, "record_ingest_health", lambda table, src, log, **kw: calls.append((src, kw)))
    monkeypatch.setattr(nl, "_INGEST_HEALTH_AVAILABLE", True)
    monkeypatch.setattr(nl, "get_secrets", lambda: ("key", "db"))
    monkeypatch.setattr(nl, "query_database", lambda *a, **k: [])

    out = nl.lambda_handler({}, None)
    assert out["statusCode"] == 200
    assert calls == [("notion", {"attempted": True, "succeeded": True, "error_class": "none"})]

    calls.clear()
    monkeypatch.setattr(nl, "get_secrets", lambda: (_ for _ in ()).throw(RuntimeError("Notion API → HTTP 401 unauthorized")))
    with pytest.raises(RuntimeError):
        nl.lambda_handler({}, None)
    assert calls == [("notion", {"attempted": True, "succeeded": False, "error_class": "auth"})]


def test_dropbox_healthy_skip_and_failure_record_sentinel(monkeypatch):
    sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))
    import dropbox_poll_lambda as dp

    calls = []
    monkeypatch.setattr(dp, "record_ingest_health", lambda table, src, log, **kw: calls.append((src, kw)))
    monkeypatch.setattr(dp, "_INGEST_HEALTH_AVAILABLE", True)
    monkeypatch.setattr(dp, "get_tracker_item", lambda: {"recently": "empty"})
    monkeypatch.setattr(dp, "_is_recently_empty", lambda tracker: True)

    out = dp.lambda_handler({}, None)
    assert out["statusCode"] == 200
    assert calls == [("dropbox", {"attempted": True, "succeeded": True, "error_class": "none"})]

    calls.clear()
    monkeypatch.setattr(dp, "_is_recently_empty", lambda tracker: False)
    monkeypatch.setattr(dp, "get_dropbox_secret", lambda: (_ for _ in ()).throw(TimeoutError("connection timed out")))
    with pytest.raises(TimeoutError):
        dp.lambda_handler({}, None)
    assert calls == [("dropbox", {"attempted": True, "succeeded": False, "error_class": "transport"})]


def test_framework_breaker_delegates_to_auth_breaker(monkeypatch):
    """#467 (X-13): the framework's breaker hooks must go through auth_breaker so
    the SIMP-2 sources emit IngestAuthHealthy like notion/dropbox do."""
    import ingestion_framework as fw

    assert fw._HAS_AUTH_BREAKER_MODULE is True

    seen = []
    monkeypatch.setattr(fw, "_ab_clear_failure", lambda table, src, uid, log: seen.append(("clear", src)))
    monkeypatch.setattr(fw, "_ab_mark_failure", lambda table, src, uid, err, log: seen.append(("mark", src)))
    monkeypatch.setattr(fw, "_ab_check_breaker", lambda table, src, uid, log: seen.append(("check", src)))

    fw._clear_auth_failure(None, "whoop", "matthew", None)
    fw._mark_auth_failure(None, "whoop", "matthew", "401", None)
    fw._check_auth_breaker(None, "whoop", "matthew", None)
    assert seen == [("clear", "whoop"), ("mark", "whoop"), ("check", "whoop")]


def test_pipeline_health_check_lists_only_emitting_sources():
    sys.path.insert(0, os.path.join(ROOT, "lambdas", "operational"))
    import pipeline_health_check_lambda as ph

    # hevy is a scheduled pull with a cron that can go stale — it must be watched
    # now that it emits (#466); notion + dropbox emit since #467.
    for src in ("hevy", "notion", "dropbox"):
        assert src in ph.ACTIVE_API_SOURCES


def test_record_ingest_health_writes_sentinel_and_streak():
    import logging
    from datetime import datetime, timezone

    from ingest_health import evaluate_source_health, ingest_health_sk
    from ingestion_framework import record_ingest_health

    class _Table:
        def __init__(self):
            self.items = {}

        def put_item(self, Item=None, **kw):
            self.items[(Item["pk"], Item["sk"])] = Item

        def get_item(self, Key=None, **kw):
            item = self.items.get((Key["pk"], Key["sk"]))
            return {"Item": item} if item else {}

    table = _Table()
    log = logging.getLogger("test")

    for _ in range(3):
        record_ingest_health(table, "hevy", log, attempted=True, succeeded=False, error_class="auth")

    sentinel = table.items[("USER#system", ingest_health_sk("hevy"))]
    assert sentinel["consecutive_failures"] == 3
    verdict = evaluate_source_health(sentinel, now=datetime.now(timezone.utc), source="hevy")
    assert verdict["status"] == "failing" and verdict["alert"] is True

    record_ingest_health(table, "hevy", log, attempted=True, succeeded=True)
    sentinel = table.items[("USER#system", ingest_health_sk("hevy"))]
    assert sentinel["consecutive_failures"] == 0 and sentinel["last_error_class"] == "none"
