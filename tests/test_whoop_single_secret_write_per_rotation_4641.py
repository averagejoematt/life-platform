"""tests/test_whoop_single_secret_write_per_rotation_4641.py — #4641: one UpdateSecret per Whoop rotation.

Live read 2026-10-27 (scripts/ingestion_churn_remeasure.py, 8 days): Whoop made 160 UpdateSecret
calls for ~10 real rotations a day. `authenticate()` persists the rotated token immediately (#2069)
and the framework then wrote the SAME dict again, because it compares the returned credentials with
the dict it read, not with what is now stored. After a successful persist the baseline is brought up
to the stored value, so the framework's writeback is a no-op; after a failed persist it is not, so
the framework's retried writeback is still the second chance.
"""

import json
import logging
import os

for _k, _v in {
    "S3_BUCKET": "test-bucket",
    "TABLE_NAME": "life-platform",
    "USER_ID": "matthew",
    "WHOOP_SECRET_NAME": "life-platform/whoop",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_REGION": "us-west-2",
}.items():
    os.environ.setdefault(_k, _v)

from ingestion import (  # noqa: E402
    ingestion_framework as fw,
    whoop_lambda as whoop,
)


class _SM:
    def __init__(self, fail=False):
        self.writes = []
        self.fail = fail

    def update_secret(self, SecretId=None, SecretString=None, **_kw):
        if self.fail:
            raise RuntimeError("throttled")
        self.writes.append(json.loads(SecretString))


def _read_secret():
    return {"client_id": "cid", "client_secret": "csec", "refresh_token": "rt-old", "access_token": "at-old"}


def _run(monkeypatch, sm):
    """authenticate() then the framework's own writeback, exactly as run_ingestion sequences them."""
    monkeypatch.setattr(whoop.boto3, "client", lambda *a, **k: sm)
    monkeypatch.setattr(whoop.time, "sleep", lambda *_: None)
    monkeypatch.setattr(whoop, "_refresh_access_token", lambda *a, **k: ("at-new", "rt-new", 3600))
    secret_data = _read_secret()
    credentials = whoop.authenticate(secret_data)
    wrote = fw._writeback_credentials(
        type("C", (), {"secret_id": "life-platform/whoop"})(), sm, secret_data, credentials, logging.getLogger("t")
    )
    return credentials, wrote


def test_a_rotation_is_written_once_not_twice(monkeypatch):
    sm = _SM()
    credentials, framework_wrote = _run(monkeypatch, sm)
    assert credentials["refresh_token"] == "rt-new"
    assert len(sm.writes) == 1, f"one rotation must cost one UpdateSecret, got {len(sm.writes)}"
    assert sm.writes[0]["refresh_token"] == "rt-new"
    assert framework_wrote is False


def test_a_failed_immediate_persist_still_gets_the_framework_writeback(monkeypatch):
    sm = _SM(fail=True)
    monkeypatch.setattr(whoop.boto3, "client", lambda *a, **k: sm)
    monkeypatch.setattr(whoop.time, "sleep", lambda *_: None)
    monkeypatch.setattr(whoop, "_refresh_access_token", lambda *a, **k: ("at-new", "rt-new", 3600))
    secret_data = _read_secret()
    credentials = whoop.authenticate(secret_data)
    assert secret_data["refresh_token"] == "rt-old", "the baseline must not claim a write that never landed"
    good = _SM()
    wrote = fw._writeback_credentials(
        type("C", (), {"secret_id": "life-platform/whoop"})(), good, secret_data, credentials, logging.getLogger("t")
    )
    assert wrote is True and good.writes[0]["refresh_token"] == "rt-new"


def test_a_reused_token_writes_nothing(monkeypatch):
    import time

    sm = _SM()
    monkeypatch.setattr(whoop.boto3, "client", lambda *a, **k: sm)
    monkeypatch.setattr(whoop, "_refresh_access_token", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no exchange")))
    secret_data = dict(_read_secret(), access_token_expires_at=int(time.time()) + 3600)
    credentials = whoop.authenticate(secret_data)
    wrote = fw._writeback_credentials(
        type("C", (), {"secret_id": "life-platform/whoop"})(), sm, secret_data, credentials, logging.getLogger("t")
    )
    assert not sm.writes and wrote is False
