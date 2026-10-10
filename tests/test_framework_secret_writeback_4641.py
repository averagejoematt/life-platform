"""#4641: the ingestion framework writes the secret back only when the token changed."""

import logging
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "ingestion"))

import ingestion.ingestion_framework as fw  # noqa: E402

_CFG = SimpleNamespace(secret_id="life-platform/test")
_LOG = logging.getLogger("t4641")


class _SM:
    def __init__(self, fail_first=0):
        self.writes = []
        self.fail_first = fail_first

    def update_secret(self, **kw):
        if self.fail_first:
            self.fail_first -= 1
            raise RuntimeError("throttled")
        self.writes.append(kw)


def test_unchanged_credentials_do_not_write():
    sm = _SM()
    secret = {"access_token": "a", "refresh_token": "r"}
    assert fw._writeback_credentials(_CFG, sm, secret, dict(secret), _LOG) is False
    assert sm.writes == []


def test_rotated_credentials_write_and_retry_once(monkeypatch):
    monkeypatch.setattr(fw.time, "sleep", lambda *_: None)
    sm = _SM(fail_first=1)
    assert fw._writeback_credentials(_CFG, sm, {"refresh_token": "old"}, {"refresh_token": "new"}, _LOG) is True
    assert len(sm.writes) == 1 and "new" in sm.writes[0]["SecretString"]


def test_rotated_credentials_double_failure_returns_false(monkeypatch):
    monkeypatch.setattr(fw.time, "sleep", lambda *_: None)
    sm = _SM(fail_first=2)
    assert fw._writeback_credentials(_CFG, sm, {"refresh_token": "old"}, {"refresh_token": "new"}, _LOG) is False
