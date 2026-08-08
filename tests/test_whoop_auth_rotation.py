"""tests/test_whoop_auth_rotation.py — #2069.

Whoop's refresh_token rotation was lost overnight (2026-08-03): a token-endpoint
502 with no retry cost a refresh attempt outright, and the following hour's
genuine 400 ("Whoop refresh 400 with unchanged refresh_token") was never
classified as an auth failure by `common.auth_breaker.looks_like_auth_failure`
(401/403 + keywords only) — so the breaker never latched, `IngestAuthHealthy`
was never emitted, and the ingestion DLQ filled silently, hour after hour.

Three durable gaps, three test groups:

  1. Classifier — a token-endpoint 400 with an unchanged refresh_token (the
     call site KNOWS this is auth, per its own log line) must latch the
     breaker; a plain data-fetch 400 must NOT (negative test — status code
     alone must never trip it).
  2. Rotation durability — the rotated refresh_token is persisted by
     `authenticate()` itself, immediately, before it returns (ordering test);
     a transient 5xx on the token endpoint (the actual first failure of the
     2026-08-03 incident, a bare 502) is retried instead of losing the whole
     attempt.
  3. (DLQ/alarm-citation trail is verified against live CloudWatch/SNS
     evidence in the PR body — not something a unit test can assert.)
"""

import json
import os
import urllib.error
from unittest.mock import MagicMock

for _k, _v in {
    "S3_BUCKET": "test-bucket",
    "TABLE_NAME": "life-platform",
    "USER_ID": "matthew",
    "WHOOP_SECRET_NAME": "life-platform/whoop",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_REGION": "us-west-2",
}.items():
    os.environ.setdefault(_k, _v)

from common import auth_breaker as ab  # noqa: E402
from ingestion import whoop_lambda as whoop  # noqa: E402


def _http_error(code, msg="err"):
    return urllib.error.HTTPError(url="https://api.prod.whoop.com/oauth/oauth2/token", code=code, msg=msg, hdrs=None, fp=None)


def _raiser(exc):
    """Return a callable that raises `exc` — used to monkeypatch a function
    that must fail with a specific, pre-built exception instance."""

    def _fn(*_a, **_k):
        raise exc

    return _fn


# ── Group 1: classifier — call-site context, not a global '400' keyword ────────


def test_marked_token_endpoint_400_latches_the_breaker():
    """Simulated response: whoop_lambda's own genuine-auth-failure branch marks
    the exception via mark_as_auth_failure. The breaker's classifier must then
    say yes — and mark_failure must emit IngestAuthHealthy=0 (acceptance box 1)."""
    exc = ab.mark_as_auth_failure(_http_error(400))
    assert ab.looks_like_auth_failure(exc) is True

    calls = []

    class _CW:
        def put_metric_data(self, **kw):
            calls.append(kw)

    import boto3 as _boto3

    orig_client = _boto3.client
    _boto3.client = lambda *a, **k: _CW()
    try:
        ab.mark_failure(MagicMock(), "whoop", "matthew", exc, None)
    finally:
        _boto3.client = orig_client

    assert calls, "a classified auth failure must emit the auth-health metric"
    dimensionless = [p for p in calls[-1]["MetricData"] if not p.get("Dimensions")][0]
    assert dimensionless["MetricName"] == "IngestAuthHealthy"
    assert dimensionless["Value"] == 0


def test_unmarked_data_fetch_400_does_not_latch():
    """The NEGATIVE case the issue explicitly calls for: a plain 400 from a
    DATA-fetch endpoint (never passed through mark_as_auth_failure) must not
    be classified as auth — status code alone is not enough. If this ever
    starts returning True, someone added '400' back to the generic list."""
    exc = _http_error(400)  # unmarked — exactly what a data-fetch 400 looks like
    assert ab.looks_like_auth_failure(exc) is False


def test_401_and_403_still_classify_without_marking():
    """The generic heuristic is unchanged for the codes it always covered."""
    assert ab.looks_like_auth_failure(_http_error(401)) is True
    assert ab.looks_like_auth_failure(_http_error(403)) is True


def test_mark_as_auth_failure_is_best_effort_on_unmarkable_objects():
    class Unmarkable:
        __slots__ = ()

        def __str__(self):
            return "no 400 no keywords"

    obj = Unmarkable()
    returned = ab.mark_as_auth_failure(obj)
    assert returned is obj
    # Marking failed silently (no attribute settable) — must not crash, and
    # the generic heuristic still correctly says "not auth" for this message.
    assert ab.looks_like_auth_failure(obj) is False


# ── whoop_lambda.authenticate(): the genuine-400 branch marks the exception ────


def _patch_secretsmanager_get(monkeypatch, unchanged_refresh_token):
    """authenticate()'s 400-handler re-reads the secret twice (1.5s apart) to
    check for a concurrent winner. Return the UNCHANGED token both times so
    the genuine-auth-failure branch is reached."""

    class _SM:
        def get_secret_value(self, SecretId):
            return {"SecretString": json.dumps({"access_token": "at-old", "refresh_token": unchanged_refresh_token})}

    monkeypatch.setattr(whoop.boto3, "client", lambda *a, **k: _SM())
    monkeypatch.setattr(whoop.time, "sleep", lambda *_: None)  # don't actually wait 1.5s x2 in tests


def test_authenticate_marks_genuine_400_as_auth_failure(monkeypatch):
    """End-to-end: authenticate() hits a 400 whose refresh_token is confirmed
    UNCHANGED (no concurrent winner) — the exact 'genuine auth failure' branch
    whose own log line inspired this issue. The raised exception must satisfy
    looks_like_auth_failure via the explicit marker, not a keyword/code guess."""
    secret_data = {"client_id": "cid", "client_secret": "csec", "refresh_token": "rt-stale", "access_token": "at-old"}
    _patch_secretsmanager_get(monkeypatch, unchanged_refresh_token="rt-stale")
    monkeypatch.setattr(whoop, "_refresh_access_token", _raiser(_http_error(400)))

    try:
        whoop.authenticate(secret_data)
        assert False, "expected the genuine-auth-failure branch to raise"
    except urllib.error.HTTPError as e:
        assert e.code == 400
        assert ab.looks_like_auth_failure(e) is True, "call site must have marked this as auth_context"


def test_authenticate_concurrent_rotation_adopts_without_raising(monkeypatch):
    """The benign race (2026-06-08): a concurrent invocation already rotated
    the token. authenticate() must adopt it and return normally — no
    exception, so nothing for the breaker to (mis)classify either way."""
    secret_data = {"client_id": "cid", "client_secret": "csec", "refresh_token": "rt-stale", "access_token": "at-old"}
    _patch_secretsmanager_get(monkeypatch, unchanged_refresh_token="rt-NEW-from-winner")
    monkeypatch.setattr(whoop, "_refresh_access_token", _raiser(_http_error(400)))

    result = whoop.authenticate(secret_data)
    assert result["refresh_token"] == "rt-NEW-from-winner"


def test_authenticate_other_http_codes_propagate_unmarked(monkeypatch):
    """A non-400 HTTPError (e.g. the actual 502 seen 2026-08-03 12:00 UTC,
    after retry is exhausted) must propagate as-is — authenticate() only
    special-cases 400; it must not be misclassified as auth by this path."""
    monkeypatch.setattr(whoop, "_refresh_access_token", _raiser(_http_error(502)))
    secret_data = {"client_id": "cid", "client_secret": "csec", "refresh_token": "rt", "access_token": "at"}
    try:
        whoop.authenticate(secret_data)
        assert False, "expected the 502 to propagate"
    except urllib.error.HTTPError as e:
        assert e.code == 502
        assert ab.looks_like_auth_failure(e) is False, "a transport 502 must not be classified as auth"


# ── Group 2: rotation durability — persist immediately, retry the transport ────


def test_authenticate_persists_rotated_secret_before_returning(monkeypatch):
    """Ordering test (acceptance box 2): the very function that has the new
    refresh_token must write it to Secrets Manager before returning — not
    rely solely on the framework's later, separate writeback step."""
    write_calls = []

    class _SM:
        def update_secret(self, SecretId, SecretString):
            write_calls.append((SecretId, json.loads(SecretString)))

    monkeypatch.setattr(whoop.boto3, "client", lambda *a, **k: _SM())
    monkeypatch.setattr(whoop, "_refresh_access_token", lambda *a, **k: ("at-NEW", "rt-NEW", 3600))

    secret_data = {"client_id": "cid", "client_secret": "csec", "refresh_token": "rt-OLD", "access_token": "at-OLD"}
    result = whoop.authenticate(secret_data)

    assert result["refresh_token"] == "rt-NEW"
    assert write_calls, "authenticate() must persist the rotated secret itself, immediately"
    secret_id, written = write_calls[0]
    assert secret_id == whoop.SECRET_NAME
    assert written["refresh_token"] == "rt-NEW", "must persist the NEW token, not the stale one"


def test_persist_refreshed_secret_retries_once_then_gives_up_without_raising(monkeypatch):
    """#481/A-9-shaped: a persistent Secrets Manager failure must not raise —
    an otherwise-successful token exchange must not fail the whole run over a
    metadata-write hiccup. Verified it actually retried (attempt count)."""
    attempts = []

    class _SM:
        def update_secret(self, **kw):
            attempts.append(1)
            raise RuntimeError("throttled")

    monkeypatch.setattr(whoop.boto3, "client", lambda *a, **k: _SM())
    monkeypatch.setattr(whoop.time, "sleep", lambda *_: None)

    ok = whoop._persist_refreshed_secret({"refresh_token": "rt", "access_token": "at"})

    assert ok is False
    assert len(attempts) == 2, "expected exactly 2 attempts (initial + 1 retry)"


def test_refresh_access_token_retries_transient_502(monkeypatch):
    """The ACTUAL first failure of the 2026-08-03 incident: a bare 502 on the
    token endpoint. One further attempt is still made so a genuinely
    unprocessed 5xx recovers inside the invocation — but since #2196 that
    attempt is whoop_lambda's own single CLASSIFIED probe (http_retry is called
    with the non-idempotent escape hatch, max_attempts=1), not http_retry's
    blind 3-attempt policy. Drives the real path end-to-end by patching only
    the underlying urllib.urlopen that http_retry itself calls."""
    from common import http_retry

    class _Resp:
        headers = {}
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"access_token": "at-2", "refresh_token": "rt-2"}).encode()

    attempts = {"n": 0}

    def fake_urlopen(req, timeout=30):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _http_error(502, "Bad Gateway")
        return _Resp()

    monkeypatch.setattr(http_retry.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(http_retry.time, "sleep", lambda *_: None)  # skip the real 2s/8s backoff in tests
    monkeypatch.setattr(whoop.time, "sleep", lambda *_: None)  # skip whoop's own probe delay

    access_token, refresh_token, expires_in = whoop._refresh_access_token("cid", "csec", "rt-1")
    assert (access_token, refresh_token) == ("at-2", "rt-2")
    assert expires_in == 0, "this fixture's token body carries no expires_in"
    assert attempts["n"] == 2, "expected exactly one classified probe after the 502"
