"""tests/test_ritual_log_endpoint.py — #769 (ADR-124): the evening-ritual one-tap
write path (GET /api/ritual_log, lambdas/web/site_api_social.py::_handle_ritual_log).

Covers:
  * validation — metric, value range, date format/window
  * the forgery guard — HMAC token must match (date, metric, value) exactly
  * idempotency — last-tap-wins, per metric independently
  * rate limiting — DynamoDB-backed, same shape as nudge/checkin
"""

import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from ritual_link import sign_ritual_token  # noqa: E402
from web import site_api_social as social  # noqa: E402

SECRET = "test-ritual-secret-0123456789"


def _ev(qs):
    return {
        "queryStringParameters": qs,
        "headers": {"x-forwarded-for": "5.5.5.5"},
        "requestContext": {"http": {"sourceIp": "5.5.5.5"}},
    }


class _FakeTable:
    def __init__(self):
        self.update_args = None
        self.update_calls = 0

    def update_item(self, **kw):
        self.update_args = kw
        self.update_calls += 1
        return {}


def _today():
    return datetime.now(social.PT).strftime("%Y-%m-%d")


def _days_ago(n):
    return (datetime.now(social.PT) - timedelta(days=n)).strftime("%Y-%m-%d")


def _setup(monkeypatch, allowed=True):
    monkeypatch.setattr(social, "_get_ritual_token_secret", lambda: SECRET)
    monkeypatch.setattr(social, "_RATE_LIMITER_READY", True)
    monkeypatch.setattr(social, "_ddb_rate_check", lambda *a, **k: (allowed, 0, 0))
    ft = _FakeTable()
    monkeypatch.setattr(social, "table", ft)
    return ft


def _valid_qs(date_str, metric, value):
    token = sign_ritual_token(SECRET, date_str, metric, value)
    return {"date": date_str, "metric": metric, "value": str(value), "token": token}


# ── validation ──────────────────────────────────────────────────────────────


def test_rejects_unknown_metric(monkeypatch):
    _setup(monkeypatch)
    qs = {"date": _today(), "metric": "vibes", "value": "3", "token": "whatever"}
    r = social._handle_ritual_log(_ev(qs))
    assert r["statusCode"] == 400


def test_rejects_out_of_range_value(monkeypatch):
    _setup(monkeypatch)
    d = _today()
    qs = {"date": d, "metric": "connection", "value": "9", "token": sign_ritual_token(SECRET, d, "connection", 9)}
    r = social._handle_ritual_log(_ev(qs))
    assert r["statusCode"] == 400


def test_rejects_non_integer_value(monkeypatch):
    _setup(monkeypatch)
    qs = {"date": _today(), "metric": "connection", "value": "abc", "token": "whatever"}
    r = social._handle_ritual_log(_ev(qs))
    assert r["statusCode"] == 400


def test_rejects_malformed_date(monkeypatch):
    _setup(monkeypatch)
    qs = {"date": "not-a-date", "metric": "connection", "value": "2", "token": "whatever"}
    r = social._handle_ritual_log(_ev(qs))
    assert r["statusCode"] == 400


def test_rejects_date_beyond_the_lookback_window(monkeypatch):
    _setup(monkeypatch)
    old = "2020-01-01"
    qs = {"date": old, "metric": "connection", "value": "2", "token": sign_ritual_token(SECRET, old, "connection", 2)}
    r = social._handle_ritual_log(_ev(qs))
    assert r["statusCode"] == 400


def test_rejects_future_date(monkeypatch):
    _setup(monkeypatch)
    future = "2099-01-01"
    qs = {"date": future, "metric": "connection", "value": "2", "token": sign_ritual_token(SECRET, future, "connection", 2)}
    r = social._handle_ritual_log(_ev(qs))
    assert r["statusCode"] == 400


def test_accepts_date_within_the_week_long_grace_window(monkeypatch):
    ft = _setup(monkeypatch)
    d = _days_ago(6)  # inside the 7-day window — an unread nudge email tapped late
    r = social._handle_ritual_log(_ev(_valid_qs(d, "connection", 2)))
    assert r["statusCode"] == 200
    assert ft.update_calls == 1


# ── forgery guard ───────────────────────────────────────────────────────────


def test_rejects_bad_token(monkeypatch):
    ft = _setup(monkeypatch)
    d = _today()
    qs = {"date": d, "metric": "connection", "value": "3", "token": "0" * 32}
    r = social._handle_ritual_log(_ev(qs))
    assert r["statusCode"] == 403
    assert ft.update_args is None


def test_token_signed_for_one_value_does_not_validate_a_different_value(monkeypatch):
    ft = _setup(monkeypatch)
    d = _today()
    token = sign_ritual_token(SECRET, d, "connection", 1)  # signed for value=1
    qs = {"date": d, "metric": "connection", "value": "4", "token": token}  # submitting value=4
    r = social._handle_ritual_log(_ev(qs))
    assert r["statusCode"] == 403
    assert ft.update_args is None


def test_token_signed_for_one_metric_does_not_validate_the_other(monkeypatch):
    ft = _setup(monkeypatch)
    d = _today()
    token = sign_ritual_token(SECRET, d, "connection", 3)
    qs = {"date": d, "metric": "mood_valence", "value": "3", "token": token}
    r = social._handle_ritual_log(_ev(qs))
    assert r["statusCode"] == 403
    assert ft.update_args is None


def test_missing_token_rejected(monkeypatch):
    ft = _setup(monkeypatch)
    qs = {"date": _today(), "metric": "connection", "value": "2", "token": ""}
    r = social._handle_ritual_log(_ev(qs))
    assert r["statusCode"] == 403
    assert ft.update_args is None


def test_signing_secret_unavailable_fails_closed_503(monkeypatch):
    def _raise():
        raise RuntimeError("secret unavailable")

    monkeypatch.setattr(social, "_get_ritual_token_secret", _raise)
    monkeypatch.setattr(social, "_RATE_LIMITER_READY", True)
    monkeypatch.setattr(social, "_ddb_rate_check", lambda *a, **k: (True, 0, 0))
    ft = _FakeTable()
    monkeypatch.setattr(social, "table", ft)
    qs = {"date": _today(), "metric": "connection", "value": "2", "token": "irrelevant"}
    r = social._handle_ritual_log(_ev(qs))
    assert r["statusCode"] == 503
    assert ft.update_args is None


# ── happy path + write shape ────────────────────────────────────────────────


def test_valid_tap_writes_ddb_record_keyed_to_the_day(monkeypatch):
    ft = _setup(monkeypatch)
    d = _today()
    r = social._handle_ritual_log(_ev(_valid_qs(d, "connection", 3)))
    assert r["statusCode"] == 200
    body = json.loads(r["body"])
    assert body["logged"] is True
    assert body["date"] == d
    assert body["metric"] == "connection"
    assert body["value"] == 3

    assert ft.update_args["Key"] == {"pk": f"{social.USER_PREFIX}evening_ritual", "sk": f"DATE#{d}"}
    assert ft.update_args["ExpressionAttributeValues"][":v"] == 3
    assert ft.update_args["ExpressionAttributeNames"]["#m"] == "connection"
    assert ft.update_args["ExpressionAttributeNames"]["#ts"] == "connection_logged_at"


# ── idempotency: last-tap-wins ───────────────────────────────────────────────


def test_second_tap_same_metric_overwrites_last_tap_wins(monkeypatch):
    ft = _setup(monkeypatch)
    d = _today()
    r1 = social._handle_ritual_log(_ev(_valid_qs(d, "mood_valence", 1)))
    r2 = social._handle_ritual_log(_ev(_valid_qs(d, "mood_valence", 4)))
    assert r1["statusCode"] == 200
    assert r2["statusCode"] == 200
    assert ft.update_calls == 2
    # last write wins — the most recent update_item call carries the final value
    assert ft.update_args["ExpressionAttributeValues"][":v"] == 4


def test_tapping_one_metric_does_not_touch_the_other(monkeypatch):
    ft = _setup(monkeypatch)
    d = _today()
    social._handle_ritual_log(_ev(_valid_qs(d, "connection", 2)))
    assert ft.update_args["ExpressionAttributeNames"]["#m"] == "connection"

    social._handle_ritual_log(_ev(_valid_qs(d, "mood_valence", 3)))
    assert ft.update_args["ExpressionAttributeNames"]["#m"] == "mood_valence"
    # each tap is an independent SET on its own field — no read-modify-write
    assert "SET #m = :v" in ft.update_args["UpdateExpression"]


# ── rate limit ────────────────────────────────────────────────────────────────


def test_rate_limited_blocks_before_any_write(monkeypatch):
    ft = _setup(monkeypatch, allowed=False)
    r = social._handle_ritual_log(_ev(_valid_qs(_today(), "connection", 2)))
    assert r["statusCode"] == 429
    assert ft.update_args is None
