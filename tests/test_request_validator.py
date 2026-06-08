"""
tests/test_request_validator.py — Phase 2.2 envelope validation.

Covers:
  - Legit requests pass cleanly
  - Oversized body / query string rejected
  - Path traversal / XSS / SQL injection patterns blocked
  - Bad user_id / date / source values rejected
  - Per-param helpers work

Run:  python3 -m pytest tests/test_request_validator.py -v
"""

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

import request_validator as rv  # noqa: E402

# ── Legit traffic should not raise ──


def test_legit_get_passes():
    event = {
        "rawPath": "/api/vitals",
        "queryStringParameters": {"user_id": "matthew", "days": "30"},
        "rawQueryString": "user_id=matthew&days=30",
        "body": "",
    }
    rv.validate_envelope(event, path="/api/vitals", method="GET")


def test_legit_post_passes():
    event = {
        "rawPath": "/api/ask",
        "body": '{"question": "what is my sleep score?"}',
    }
    rv.validate_envelope(event, path="/api/ask", method="POST")


# ── Abuse should raise ──


def test_oversized_body_rejected():
    big = "x" * (rv.MAX_BODY_BYTES + 1)
    event = {"rawPath": "/api/ask", "body": big}
    with pytest.raises(rv.ValidationError) as exc:
        rv.validate_envelope(event)
    assert exc.value.status == 413


def test_oversized_query_string_rejected():
    event = {"rawPath": "/api/x", "rawQueryString": "k=" + "v" * (rv.MAX_QUERY_STRING_LENGTH + 1)}
    with pytest.raises(rv.ValidationError) as exc:
        rv.validate_envelope(event)
    assert exc.value.status == 414


def test_path_traversal_rejected():
    event = {"rawPath": "/api/../etc/passwd"}
    with pytest.raises(rv.ValidationError):
        rv.validate_envelope(event)


def test_xss_in_query_rejected():
    event = {
        "rawPath": "/api/x",
        "queryStringParameters": {"q": "<script>alert(1)</script>"},
    }
    with pytest.raises(rv.ValidationError):
        rv.validate_envelope(event)


def test_sql_injection_pattern_rejected():
    event = {
        "rawPath": "/api/x",
        "queryStringParameters": {"id": "1; DROP TABLE users"},
    }
    with pytest.raises(rv.ValidationError):
        rv.validate_envelope(event)


def test_null_byte_rejected():
    event = {"rawPath": "/api/x", "queryStringParameters": {"name": "matt\x00admin"}}
    with pytest.raises(rv.ValidationError):
        rv.validate_envelope(event)


def test_bad_user_id_format_rejected():
    event = {"rawPath": "/api/x", "queryStringParameters": {"user_id": "Matthew Walker"}}  # uppercase + space
    with pytest.raises(rv.ValidationError) as exc:
        rv.validate_envelope(event)
    assert "user_id" in exc.value.message.lower()


def test_bad_date_format_rejected():
    event = {"rawPath": "/api/x", "queryStringParameters": {"date": "yesterday"}}
    with pytest.raises(rv.ValidationError):
        rv.validate_envelope(event)


def test_bad_source_format_rejected():
    event = {"rawPath": "/api/x", "queryStringParameters": {"source": "WHOOP!!"}}
    with pytest.raises(rv.ValidationError):
        rv.validate_envelope(event)


# ── Per-param helpers ──


def test_validate_user_id_passes():
    assert rv.validate_user_id("matthew") == "matthew"


def test_validate_user_id_rejects_invalid():
    with pytest.raises(rv.ValidationError):
        rv.validate_user_id("Matt!")


def test_validate_date_passes():
    assert rv.validate_date("2026-05-16") == "2026-05-16"


def test_validate_date_rejects_invalid():
    with pytest.raises(rv.ValidationError):
        rv.validate_date("05/16/2026")


def test_validate_source_rejects_unknown():
    with pytest.raises(rv.ValidationError):
        rv.validate_source("fitbit")  # not in KNOWN_SOURCES


def test_validate_source_allows_unknown_with_flag():
    assert rv.validate_source("future_source", allow_unknown=True) == "future_source"


def test_validate_int_param_range():
    assert rv.validate_int_param("30", "days", min_v=1, max_v=365) == 30
    with pytest.raises(rv.ValidationError):
        rv.validate_int_param("999", "days", min_v=1, max_v=365)
    with pytest.raises(rv.ValidationError):
        rv.validate_int_param("not-a-number", "days")
