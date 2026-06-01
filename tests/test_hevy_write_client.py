"""tests/test_hevy_write_client.py — auth header, retries, GET-before-PUT guard."""
from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest

import hevy_write_client as wc
from hevy_write_client import HevyAuthError, HevyConflict, HevyRetryable


@pytest.fixture(autouse=True)
def _reset_throttle():
    wc._reset_throttle_for_tests()
    yield
    wc._reset_throttle_for_tests()


def _mock_response(body: dict, status: int = 200):
    class _R:
        def __init__(self):
            self.status = status
        def read(self):
            return json.dumps(body).encode()
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
        def getheader(self, *a, **k):
            return None
    return _R()


def _mock_secret(api_key: str = "test-key-abc"):
    return patch.object(wc, "get_secret_json", return_value={"api_key": api_key})


def test_api_key_header_set():
    captured: dict = {}
    def fake_urlopen(req, timeout=30):
        captured["headers"] = dict(req.headers)
        captured["method"] = req.get_method()
        return _mock_response({"routines": []})
    with _mock_secret(), patch.object(wc, "urlopen_with_retry", side_effect=fake_urlopen):
        wc.list_routines()
    assert captured["headers"].get("Api-key") == "test-key-abc"


def test_auth_error_on_401():
    import urllib.error
    def fake_urlopen(req, timeout=30):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b""))
    with _mock_secret(), patch.object(wc, "urlopen_with_retry", side_effect=fake_urlopen):
        with pytest.raises(HevyAuthError):
            wc.list_routines()


def test_retryable_on_429():
    import urllib.error
    def fake_urlopen(req, timeout=30):
        raise urllib.error.HTTPError(req.full_url, 429, "rate limit", {}, io.BytesIO(b""))
    with _mock_secret(), patch.object(wc, "urlopen_with_retry", side_effect=fake_urlopen):
        with pytest.raises(HevyRetryable):
            wc.list_routines()


def test_update_with_guard_refuses_on_mismatch():
    def fake_urlopen(req, timeout=30):
        if req.get_method() == "GET":
            return _mock_response({"routine": {"id": "r1", "updated_at": "2026-06-01T20:00:00Z"}})
        raise AssertionError("PUT should not run when guard fails")
    with _mock_secret(), patch.object(wc, "urlopen_with_retry", side_effect=fake_urlopen):
        with pytest.raises(HevyConflict):
            wc.update_routine_with_guard("r1", {"routine": {}}, expected_updated_at="2026-06-01T18:00:00Z")


def test_update_with_guard_passes_through_on_match():
    calls: list[str] = []
    def fake_urlopen(req, timeout=30):
        calls.append(req.get_method())
        if req.get_method() == "GET":
            return _mock_response({"routine": {"id": "r1", "updated_at": "2026-06-01T18:00:00Z"}})
        return _mock_response({"routine": {"id": "r1", "updated_at": "2026-06-01T20:00:00Z"}})
    with _mock_secret(), patch.object(wc, "urlopen_with_retry", side_effect=fake_urlopen):
        wc.update_routine_with_guard("r1", {"routine": {}}, expected_updated_at="2026-06-01T18:00:00Z")
    assert calls == ["GET", "PUT"]


def test_create_routine_recovers_orphan():
    """Hevy quirk: 400 on POST can still create the routine. Probe + raise HevyOrphanCreated."""
    import urllib.error
    from datetime import datetime, timezone
    calls: list[str] = []
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    def fake_urlopen(req, timeout=30):
        calls.append(req.get_method())
        if req.get_method() == "POST":
            raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(b'{"error":"x"}'))
        # GET list -> return a matching just-created routine
        return _mock_response({"routines": [
            {"id": "orphan-id", "title": "Upper — 2026-06-01",
             "created_at": now_iso, "updated_at": now_iso},
        ]})
    with _mock_secret(), patch.object(wc, "urlopen_with_retry", side_effect=fake_urlopen):
        with pytest.raises(wc.HevyOrphanCreated) as exc:
            wc.create_routine({"routine": {"title": "Upper — 2026-06-01", "exercises": []}})
    assert exc.value.hevy_routine_id == "orphan-id"
    assert exc.value.status == 400
    assert calls == ["POST", "GET"]


def test_create_routine_no_orphan_match_reraises_400():
    """If the title-match probe finds nothing, the original HTTPError surfaces."""
    import urllib.error
    def fake_urlopen(req, timeout=30):
        if req.get_method() == "POST":
            raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(b''))
        return _mock_response({"routines": [
            {"id": "unrelated", "title": "Something else", "created_at": "2020-01-01T00:00:00Z"},
        ]})
    with _mock_secret(), patch.object(wc, "urlopen_with_retry", side_effect=fake_urlopen):
        with pytest.raises(urllib.error.HTTPError):
            wc.create_routine({"routine": {"title": "Upper — 2026-06-01", "exercises": []}})


def test_throttle_holds_calls_apart(monkeypatch):
    monkeypatch.setattr(wc, "MIN_INTERVAL_SECONDS", 0.05)
    sleeps: list[float] = []
    monkeypatch.setattr(wc.time, "sleep", lambda s: sleeps.append(s))

    def fake_urlopen(req, timeout=30):
        return _mock_response({"routines": []})
    with _mock_secret(), patch.object(wc, "urlopen_with_retry", side_effect=fake_urlopen):
        wc.list_routines()
        wc.list_routines()
    # Second call should have triggered a sleep of up to MIN_INTERVAL
    assert any(s > 0 for s in sleeps)
