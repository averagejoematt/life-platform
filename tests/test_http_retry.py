"""
tests/test_http_retry.py — Phase 3.5 generic ingestion retry.

Covers:
  - Successful first attempt returns body
  - 503 then success retries + returns
  - 401 raises immediately (no retry; auth_breaker territory)
  - Three 503s raises HTTPError after exhausting attempts
  - URLError (timeout) retries

Run:  python3 -m pytest tests/test_http_retry.py -v
"""

import os
import sys
import urllib.error
from io import BytesIO
from unittest.mock import patch, MagicMock

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

import http_retry as hr  # noqa: E402


def _fake_ok_response(body=b'{"ok":true}'):
    """Mock urlopen context manager returning success."""
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = body
    cm.__enter__.return_value.headers = {}
    cm.__enter__.return_value.status = 200
    return cm


def _http_error(code):
    return urllib.error.HTTPError("http://x", code, f"HTTP {code}", {}, BytesIO(b""))


def test_first_attempt_success(monkeypatch):
    monkeypatch.setattr(hr, "_BACKOFF_DELAYS", [0, 0])  # no sleep in tests
    with patch("urllib.request.urlopen", return_value=_fake_ok_response(b'{"hello":"world"}')) as m:
        with hr.urlopen_with_retry("req") as r:
            assert r.read() == b'{"hello":"world"}'
        assert m.call_count == 1


def test_503_then_success_retries(monkeypatch):
    monkeypatch.setattr(hr, "_BACKOFF_DELAYS", [0, 0])
    with patch("urllib.request.urlopen") as m:
        m.side_effect = [_http_error(503), _fake_ok_response(b'{"recovered":1}')]
        with hr.urlopen_with_retry("req") as r:
            assert r.read() == b'{"recovered":1}'
        assert m.call_count == 2


def test_401_raises_immediately(monkeypatch):
    monkeypatch.setattr(hr, "_BACKOFF_DELAYS", [0, 0])
    with patch("urllib.request.urlopen") as m:
        m.side_effect = _http_error(401)
        with pytest.raises(urllib.error.HTTPError) as exc:
            hr.urlopen_with_retry("req")
        assert exc.value.code == 401
        assert m.call_count == 1  # No retry for auth failures


def test_three_503s_raises_after_attempts(monkeypatch):
    monkeypatch.setattr(hr, "_BACKOFF_DELAYS", [0, 0])
    with patch("urllib.request.urlopen") as m:
        m.side_effect = [_http_error(503), _http_error(503), _http_error(503)]
        with pytest.raises(urllib.error.HTTPError):
            hr.urlopen_with_retry("req")
        assert m.call_count == 3  # 3 attempts total


def test_network_error_retries(monkeypatch):
    monkeypatch.setattr(hr, "_BACKOFF_DELAYS", [0, 0])
    with patch("urllib.request.urlopen") as m:
        m.side_effect = [
            urllib.error.URLError("timeout"),
            _fake_ok_response(b'{"ok":1}'),
        ]
        with hr.urlopen_with_retry("req") as r:
            assert r.read() == b'{"ok":1}'
        assert m.call_count == 2
