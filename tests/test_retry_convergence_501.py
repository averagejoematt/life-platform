"""
tests/test_retry_convergence_501.py — #501/X-11 + B-9.

Covers the four bespoke retry implementations converged onto the shared
http_retry.urlopen_with_retry policy:
  - whoop_lambda._fetch_endpoint     (was a hand-rolled 3-attempt 2s/8s loop)
  - todoist_lambda.api_get           (was a hand-rolled 3-attempt 2s/8s loop,
                                       and never retried network errors)
  - weather_lambda.fetch_day         (was a bare, unretried urlopen)
  - hevy_write_client._request       (already used http_retry, but retried
                                       POST/PUT the same as GET — see
                                       tests/test_hevy_write_client.py for the
                                       GET-only-retry assertions)

Plus B-9: withings_lambda.fetch_day now serves a whole gap-fill run from ONE
getmeas range call instead of one call per missing date.

Fully offline — patches urllib.request.urlopen (or http_retry.urlopen_with_retry
directly), no AWS/network calls.
"""

import io
import json
import os
import sys
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))

# Ingestion modules build an IngestionConfig at import time (reads env). Set dummies.
for _k, _v in {
    "S3_BUCKET": "test-bucket",
    "TABLE_NAME": "life-platform",
    "USER_ID": "matthew",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_REGION": "us-west-2",
}.items():
    os.environ.setdefault(_k, _v)

import http_retry  # noqa: E402
from ingestion import todoist_lambda, weather_lambda, whoop_lambda, withings_lambda  # noqa: E402


def _fake_ok(body: dict):
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = json.dumps(body).encode()
    cm.__enter__.return_value.headers = {}
    cm.__enter__.return_value.status = 200
    return cm


def _http_error(code):
    return urllib.error.HTTPError("http://x", code, f"HTTP {code}", {}, io.BytesIO(b""))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(http_retry, "_BACKOFF_DELAYS", [0, 0])


# ══════════════════════════════════════════════════════════════════════════
# whoop_lambda._fetch_endpoint
# ══════════════════════════════════════════════════════════════════════════
def test_whoop_fetch_endpoint_retries_on_503():
    with patch("urllib.request.urlopen") as m:
        m.side_effect = [_http_error(503), _fake_ok({"records": []})]
        result = whoop_lambda._fetch_endpoint("tok", "recovery", "2026-07-01", "2026-07-02")
    assert result == {"records": []}
    assert m.call_count == 2


def test_whoop_fetch_endpoint_raises_immediately_on_401():
    with patch("urllib.request.urlopen") as m:
        m.side_effect = _http_error(401)
        with pytest.raises(urllib.error.HTTPError) as exc:
            whoop_lambda._fetch_endpoint("tok", "recovery", "2026-07-01", "2026-07-02")
        assert exc.value.code == 401
    assert m.call_count == 1  # no retry for auth failures


# ══════════════════════════════════════════════════════════════════════════
# todoist_lambda.api_get
# ══════════════════════════════════════════════════════════════════════════
def test_todoist_api_get_retries_on_503():
    with patch("urllib.request.urlopen") as m:
        m.side_effect = [_http_error(503), _fake_ok({"items": []})]
        result = todoist_lambda.api_get("/projects", "tok")
    assert result == {"items": []}
    assert m.call_count == 2


def test_todoist_api_get_now_retries_network_errors():
    """The pre-convergence hand-rolled loop only caught HTTPError — a bare
    URLError (timeout, DNS blip) propagated uncaught. http_retry fixes that."""
    with patch("urllib.request.urlopen") as m:
        m.side_effect = [urllib.error.URLError("timeout"), _fake_ok({"items": []})]
        result = todoist_lambda.api_get("/projects", "tok")
    assert result == {"items": []}
    assert m.call_count == 2


# ══════════════════════════════════════════════════════════════════════════
# weather_lambda.fetch_day
# ══════════════════════════════════════════════════════════════════════════
def test_weather_fetch_day_retries_on_503():
    """Previously a bare urlopen with zero retry — one transient 5xx dropped
    the whole day."""
    with patch("urllib.request.urlopen") as m:
        m.side_effect = [_http_error(503), _fake_ok({"daily": {"time": ["2026-07-01"]}})]
        result = weather_lambda.fetch_day({}, "2026-07-01")
    assert result == {"daily": {"time": ["2026-07-01"]}}
    assert m.call_count == 2


# ══════════════════════════════════════════════════════════════════════════
# withings_lambda — B-9: one range call covers a multi-day gap-fill
# ══════════════════════════════════════════════════════════════════════════
def _withings_secret():
    return {
        "client_id": "cid",
        "client_secret": "csecret",
        "refresh_token": "rtok",
        "access_token": "atok",
    }


def _grp(ts: int, weight_kg: float = 80.0):
    return {"date": ts, "measures": [{"type": 1, "value": int(weight_kg * 1000), "unit": -3}]}


@pytest.fixture(autouse=True)
def _reset_withings_caches():
    withings_lambda._secret_cache["secret"] = None
    withings_lambda._range_cache["window"] = None
    withings_lambda._range_cache["by_date"] = {}
    yield
    withings_lambda._secret_cache["secret"] = None
    withings_lambda._range_cache["window"] = None
    withings_lambda._range_cache["by_date"] = {}


def test_withings_gap_fill_uses_one_range_call_for_multiple_dates(monkeypatch):
    """#501/B-9: the framework calls fetch_day once per missing date; before
    the fix that meant one getmeas call per date. Now the first call in an
    invocation fetches the whole lookback window and the rest are served from
    cache — asserted here by counting the underlying HTTP calls."""
    monkeypatch.setenv("LOOKBACK_DAYS", "7")
    secret = _withings_secret()
    withings_lambda._secret_cache["secret"] = secret

    import datetime as dt

    now = dt.datetime.now(dt.timezone.utc)
    d0 = (now - dt.timedelta(days=3)).strftime("%Y-%m-%d")
    d1 = (now - dt.timedelta(days=2)).strftime("%Y-%m-%d")
    d2 = (now - dt.timedelta(days=1)).strftime("%Y-%m-%d")

    ts0 = int((now - dt.timedelta(days=3)).replace(hour=8, minute=0, second=0, microsecond=0).timestamp())
    ts2 = int((now - dt.timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0).timestamp())

    call_count = {"n": 0}

    def fake_urlopen(req, timeout=30):
        call_count["n"] += 1
        # Single getmeas response covering the whole requested range.
        body = {"status": 0, "body": {"measuregrps": [_grp(ts0), _grp(ts2, 81.0)]}}
        cm = MagicMock()
        cm.__enter__.return_value.read.return_value = json.dumps(body).encode()
        cm.__enter__.return_value.headers = {}
        cm.__enter__.return_value.status = 200
        return cm

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        r0 = withings_lambda.fetch_day(secret, d0)
        r1 = withings_lambda.fetch_day(secret, d1)
        r2 = withings_lambda.fetch_day(secret, d2)

    assert call_count["n"] == 1  # ONE getmeas call served all three dates
    assert r0 is not None and r0["measuregrps"][0]["date"] == ts0
    assert r1 is None  # no weigh-in that day
    assert r2 is not None and r2["measuregrps"][0]["date"] == ts2


def test_withings_authenticate_resets_range_cache(monkeypatch):
    """A fresh invocation (authenticate() call) must force a fresh range
    fetch — a stale cross-invocation cache would silently serve last run's
    data on a warm container."""
    secret = _withings_secret()
    withings_lambda._range_cache["window"] = ("stale", "stale")
    withings_lambda._range_cache["by_date"] = {"2020-01-01": {"measuregrps": []}}

    def fake_post_form(url, params):
        if params.get("action") == "getnonce":
            return {"status": 0, "body": {"nonce": "n"}}
        return {"status": 0, "body": {"access_token": "new-a", "refresh_token": "new-r"}}

    with patch.object(withings_lambda, "_post_form", side_effect=fake_post_form):
        withings_lambda.authenticate(secret)

    assert withings_lambda._range_cache["window"] is None
    assert withings_lambda._range_cache["by_date"] == {}
