"""tests/test_predict_week_freshness.py — #1198 nightly predict-the-week guard.

Proves qa_smoke_lambda.check_predict_week_freshness FAILs the nightly run when
/api/predict_week is live on a stale ISO week (the exact regression the site-api
_predict_subject fail-closed guard prevents), and passes when the subject is
current or inactive, and fail-SOFTs (warns, never reds) on an unreachable API.

Non-vacuous: the stale-week case asserts .passed is False — a guard that never
fails would not satisfy it.
"""

import json
import os
import sys
from datetime import datetime

# qa_smoke_lambda reads these at import time (conftest supplies fake AWS creds).
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import qa_smoke_lambda as qa  # noqa: E402


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch(monkeypatch, payload=None, raise_exc=None):
    def _urlopen(req, timeout=None):
        if raise_exc:
            raise raise_exc
        return _Resp(payload)

    monkeypatch.setattr(qa.urllib.request, "urlopen", _urlopen)
    # Pin "now" so the current ISO week is deterministic: 2026-07-16 -> 2026-W29.
    monkeypatch.setattr(qa, "pt_now", lambda: datetime(2026, 7, 16, 12, 0, 0))


def test_stale_week_fails_the_nightly(monkeypatch):
    _patch(monkeypatch, {"active": True, "week_id": "2026-W27"})
    (c,) = qa.check_predict_week_freshness()
    assert c.passed is False
    assert "stale week" in c.message and "2026-W27" in c.message


def test_current_week_passes(monkeypatch):
    _patch(monkeypatch, {"active": True, "week_id": "2026-W29"})
    (c,) = qa.check_predict_week_freshness()
    assert c.passed is True


def test_inactive_passes(monkeypatch):
    _patch(monkeypatch, {"active": False})
    (c,) = qa.check_predict_week_freshness()
    assert c.passed is True


def test_fetch_error_is_fail_soft(monkeypatch):
    _patch(monkeypatch, raise_exc=OSError("boom"))
    (c,) = qa.check_predict_week_freshness()
    assert c.passed is None  # warn — a fetch blip must never red the nightly
