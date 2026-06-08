"""
tests/test_auth_breaker.py — Unit tests for the ADR-052 auth-failure
circuit breaker in ingestion_framework.

Covers:
  - _looks_like_auth_failure recognizes 401/403 messages and HTTPError.code
  - _check_auth_breaker returns None when marker absent
  - _check_auth_breaker returns the item when marker is fresh
  - _check_auth_breaker returns None when marker is expired (>24h old)
  - _mark_auth_failure writes a DDB item with TTL ~24h in the future
  - _clear_auth_failure deletes the marker

Run:  python3 -m pytest tests/test_auth_breaker.py -v
"""

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "cdk", "layer-build", "python"))

import ingestion_framework as ig  # noqa: E402


@pytest.fixture
def logger():
    lg = logging.getLogger("test")
    lg.setLevel(logging.DEBUG)
    return lg


def test_looks_like_auth_failure_recognizes_401():
    assert ig._looks_like_auth_failure(Exception("HTTP 401 Unauthorized"))
    assert ig._looks_like_auth_failure(Exception("got 403 Forbidden"))


def test_looks_like_auth_failure_recognizes_keywords():
    assert ig._looks_like_auth_failure(Exception("invalid token"))
    assert ig._looks_like_auth_failure(Exception("Token Expired, please refresh"))
    assert ig._looks_like_auth_failure(Exception("authentication failed"))


def test_looks_like_auth_failure_recognizes_httperror_code():
    class FakeHTTPError(Exception):
        code = 401

    assert ig._looks_like_auth_failure(FakeHTTPError("oops"))


def test_looks_like_auth_failure_ignores_5xx():
    assert not ig._looks_like_auth_failure(Exception("HTTP 503 Service Unavailable"))
    assert not ig._looks_like_auth_failure(Exception("connection timeout"))


def test_check_auth_breaker_absent_returns_none(logger):
    table = MagicMock()
    table.get_item.return_value = {}
    assert ig._check_auth_breaker(table, "whoop", "matthew", logger) is None


def test_check_auth_breaker_fresh_returns_item(logger):
    table = MagicMock()
    table.get_item.return_value = {
        "Item": {
            "pk": "USER#matthew#SOURCE#whoop",
            "sk": "AUTH_FAILURE",
            "marked_at": datetime.now(timezone.utc).isoformat(),
            "error": "401 Unauthorized",
        }
    }
    result = ig._check_auth_breaker(table, "whoop", "matthew", logger)
    assert result is not None
    assert result["error"] == "401 Unauthorized"


def test_check_auth_breaker_expired_returns_none(logger):
    table = MagicMock()
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    table.get_item.return_value = {
        "Item": {
            "pk": "USER#matthew#SOURCE#whoop",
            "sk": "AUTH_FAILURE",
            "marked_at": old,
        }
    }
    assert ig._check_auth_breaker(table, "whoop", "matthew", logger) is None


def test_mark_auth_failure_writes_item_with_ttl(logger):
    table = MagicMock()
    ig._mark_auth_failure(table, "whoop", "matthew", "401 Unauthorized", logger)
    table.put_item.assert_called_once()
    item = table.put_item.call_args.kwargs["Item"]
    assert item["pk"] == "USER#matthew#SOURCE#whoop"
    assert item["sk"] == "AUTH_FAILURE"
    assert item["error"] == "401 Unauthorized"
    # TTL is unix timestamp ~24h in the future.
    expected_ttl = int(datetime.now(timezone.utc).timestamp()) + 24 * 3600
    assert abs(item["ttl"] - expected_ttl) < 5


def test_clear_auth_failure_deletes_item(logger):
    table = MagicMock()
    ig._clear_auth_failure(table, "garmin", "matthew", logger)
    table.delete_item.assert_called_once_with(Key={"pk": "USER#matthew#SOURCE#garmin", "sk": "AUTH_FAILURE"})
