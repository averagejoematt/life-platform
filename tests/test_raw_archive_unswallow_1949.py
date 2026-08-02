"""tests/test_raw_archive_unswallow_1949.py — #1949: a raw-archive write failure
must surface, never vanish.

Pre-#1949, `_archive_raw` caught every exception, printed one [ERROR] line, and
run_ingestion carried on as a fully-healthy run: statusCode 200, ER-01
ingest-health `succeeded=True`, no metric, no alarm. That is how weather's
archive stayed dead for ~5 months after the 2026-03-09 IAM migration removed
its PutObject grant.

The repaired contract, asserted functionally here by driving run_ingestion with
fakes:
  * archive failure ⇒ 207, `archive_failures` in the summary, ingest-health
    `succeeded=False` with a non-"none" error class (streak grows ⇒ heartbeat
    alerts) — while the date's DDB records still store (non-fatal per date);
  * the ADR-052 auth breaker is NOT tripped by an S3 AccessDenied (it is an
    IAM/role fault, not an upstream credential one);
  * clean archive ⇒ 200 and `succeeded=True`, exactly as before.
"""

import json
import os
import sys

os.environ.setdefault("S3_BUCKET", "test-bucket")  # IngestionConfig reads it at construction

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from ingestion import ingestion_framework as fw  # noqa: E402


class _FakeTable:
    def __init__(self):
        self.put_items = []
        self.deleted = []

    def get_item(self, **kwargs):
        return {}  # no breaker marker, no state

    def put_item(self, Item=None, **kwargs):
        self.put_items.append(Item or {})
        return {}

    def delete_item(self, **kwargs):
        self.deleted.append(kwargs)
        return {}

    def query(self, **kwargs):
        return {"Items": []}


class _FakeS3:
    def __init__(self, fail=False):
        self.fail = fail
        self.put_keys = []

    def put_object(self, Bucket=None, Key=None, **kwargs):
        if self.fail:
            raise Exception("An error occurred (AccessDenied) when calling the PutObject operation: Access Denied")
        self.put_keys.append(Key)
        return {}


def _run(monkeypatch, *, s3_fails):
    table = _FakeTable()
    s3 = _FakeS3(fail=s3_fails)
    health = {}

    monkeypatch.setattr(fw, "_init_aws", lambda config: (table, s3, None))
    monkeypatch.setattr(
        fw,
        "record_ingest_health",
        lambda t, source_name, logger, *, attempted, succeeded, error_class="none": health.update(
            {"attempted": attempted, "succeeded": succeeded, "error_class": error_class}
        ),
    )

    config = fw.IngestionConfig(source_name="testsrc", s3_archive_prefix="raw/testsrc")
    resp = fw.run_ingestion(
        config,
        authenticate_fn=lambda secret: {},
        fetch_day_fn=lambda creds, d: {"payload": 1},
        transform_fn=lambda raw, d: [{"source": "testsrc", "date": d, "value": 7}],
        event={"date_override": "today"},
        context=None,
    )
    return resp, table, s3, health


def test_archive_failure_is_a_failed_run_not_a_silent_success(monkeypatch):
    resp, table, s3, health = _run(monkeypatch, s3_fails=True)

    body = json.loads(resp["body"])
    assert resp["statusCode"] == 207, f"archive failure must not report a clean 200: {resp}"
    assert body["archive_failures"] == 1
    # The date's data still stored — archive failure is non-fatal per date.
    assert body["records_written"] == 1
    stored = [i for i in table.put_items if str(i.get("sk", "")).startswith("DATE#")]
    assert len(stored) == 1

    # ER-01: the run's liveness record fails ⇒ streak grows ⇒ heartbeat alerts.
    assert health["succeeded"] is False
    assert health["error_class"] != "none"

    # ADR-052: an S3 AccessDenied must NOT trip the upstream-credential breaker.
    assert not [i for i in table.put_items if i.get("sk") == fw._AUTH_FAIL_SK], "S3 archive failure tripped the auth breaker"


def test_clean_archive_is_still_a_clean_run(monkeypatch):
    resp, table, s3, health = _run(monkeypatch, s3_fails=False)

    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["archive_failures"] == 0
    assert health["succeeded"] is True
    assert health["error_class"] == "none"
    # The archive landed under the config prefix with the date-tree shape.
    assert len(s3.put_keys) == 1 and s3.put_keys[0].startswith("raw/testsrc/")


def test_archive_raw_returns_the_exception_not_silence():
    """The helper's own contract: None on success, the exception on failure."""
    config = fw.IngestionConfig(source_name="testsrc", s3_archive_prefix="raw/testsrc")
    ok = fw._archive_raw(_FakeS3(fail=False), config, "2026-08-02", {"a": 1})
    assert ok is None
    err = fw._archive_raw(_FakeS3(fail=True), config, "2026-08-02", {"a": 1})
    assert isinstance(err, Exception) and "AccessDenied" in str(err)
