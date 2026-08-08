"""tests/test_whoop_rotation_budget.py — #2196: stop the Whoop credential-death
treadmill.

Measured premise (2026-08-07 read-only investigation): `authenticate()` ran on
EVERY invocation, before gap detection, and unconditionally spent one
single-use refresh_token rotation — ~22 exchanges/day. Whoop's token endpoint
5xx'd on ~1% of them, and TWICE (08-03, 08-04) the server had already consumed
the rotation before the 5xx, so the new token was lost in transit. Expected
loss: every 4-5 days. Observed: 08-01, 08-03, 08-04.

Six acceptance boxes, six test groups, all OFFLINE — the vendor posture is
hostile, so nothing here may ever touch a real Whoop endpoint:

  1. exchange gated on the stored access-token expiry (in the secret JSON);
  2. the token POST uses http_retry's non-idempotent escape hatch;
  3. a 400-after-5xx on the same POST is classified "lost rotation" and emits
     its own signal, distinct from the generic auth latch;
  4. the warm-container secret cache is invalidated after a rotation write;
  5. `_reconcile` honors the auth breaker;
  6. a single data-endpoint 401 seconds after a healthy rotation does NOT latch
     the 24h breaker — and a recurrence does.
"""

import json
import os
import time
import urllib.error

import pytest

for _k, _v in {
    "S3_BUCKET": "test-bucket",
    "TABLE_NAME": "life-platform",
    "USER_ID": "matthew",
    "WHOOP_SECRET_NAME": "life-platform/whoop",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_REGION": "us-west-2",
}.items():
    os.environ.setdefault(_k, _v)

from common import (
    auth_breaker as ab,  # noqa: E402
    secret_cache,  # noqa: E402
)
from ingestion import (
    ingestion_framework as fw,  # noqa: E402
    whoop_lambda as whoop,  # noqa: E402
)


def _http_error(code, msg="err"):
    return urllib.error.HTTPError(url="https://api.prod.whoop.com/oauth/oauth2/token", code=code, msg=msg, hdrs=None, fp=None)


def _raiser(exc):
    def _fn(*_a, **_k):
        raise exc

    return _fn


def _boom(*_a, **_k):
    raise AssertionError("this call must not happen")


def _secret(**over):
    s = {"client_id": "cid", "client_secret": "csec", "refresh_token": "rt-old", "access_token": "at-old"}
    s.update(over)
    return s


class _FakeSM:
    """Secrets Manager stand-in: records writes, serves a canned secret."""

    def __init__(self, secret_string: str = "{}"):  # noqa: S107 — a JSON blob fixture, not a credential
        self.secret_string = secret_string
        self.writes = []

    def update_secret(self, SecretId=None, SecretString=None, **_kw):
        self.writes.append((SecretId, json.loads(SecretString)))

    def get_secret_value(self, SecretId=None, **_kw):
        return {"SecretString": self.secret_string}


class _FakeCW:
    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kw):
        self.calls.append(kw)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Module state is per-invocation scratch (reserved concurrency = 1) — reset
    it between tests, and never sleep for real."""
    whoop._secret_cache["access_token"] = None
    whoop._rotation_state["rotated_at"] = None
    secret_cache.invalidate()
    monkeypatch.setattr(whoop.time, "sleep", lambda *_: None)
    yield
    whoop._secret_cache["access_token"] = None
    whoop._rotation_state["rotated_at"] = None
    secret_cache.invalidate()


# ── Box 1: exchange only near expiry ──────────────────────────────────────────


def test_valid_stored_access_token_is_reused_without_spending_a_rotation(monkeypatch):
    """THE fix: a run that already holds a live access token must not touch the
    token endpoint at all. Every avoided exchange is an avoided ~1% chance of
    losing the credential."""
    monkeypatch.setattr(whoop, "_refresh_access_token", _boom)

    out = whoop.authenticate(_secret(access_token_expires_at=int(time.time()) + 3600))

    assert out["access_token"] == "at-old"
    assert out["refresh_token"] == "rt-old", "the single-use refresh_token must be untouched"
    assert whoop._secret_cache["access_token"] == "at-old", "fetch_day must be able to use the reused token"
    assert whoop._rotation_state["rotated_at"] is None, "no rotation happened, so no rotation grace is owed"


def test_token_inside_the_skew_margin_is_refreshed(monkeypatch):
    """A token with less life left than the skew margin is refreshed — the run
    itself takes time, so 'valid right now' is not good enough."""
    calls = []
    monkeypatch.setattr(whoop, "_refresh_access_token", lambda *a, **k: calls.append(a) or ("at-new", "rt-new", 3600))
    monkeypatch.setattr(whoop, "_persist_refreshed_secret", lambda secret: True)

    out = whoop.authenticate(_secret(access_token_expires_at=int(time.time()) + 60))

    assert calls, "a near-expiry token must be exchanged"
    assert out["access_token"] == "at-new"


def test_missing_expiry_is_treated_as_expired(monkeypatch):
    """The conservative direction for a secret written before this change (or a
    fresh re-auth that predates the expiry stamp): exchange, don't gamble on a
    token whose life we cannot bound."""
    calls = []
    monkeypatch.setattr(whoop, "_refresh_access_token", lambda *a, **k: calls.append(a) or ("at-new", "rt-new", 3600))
    monkeypatch.setattr(whoop, "_persist_refreshed_secret", lambda secret: True)

    whoop.authenticate(_secret())

    assert calls, "no stored expiry ⇒ refresh"


def test_unparseable_expiry_is_treated_as_expired(monkeypatch):
    calls = []
    monkeypatch.setattr(whoop, "_refresh_access_token", lambda *a, **k: calls.append(a) or ("at-new", "rt-new", 3600))
    monkeypatch.setattr(whoop, "_persist_refreshed_secret", lambda secret: True)

    whoop.authenticate(_secret(access_token_expires_at="not-a-number"))

    assert calls


def test_rotation_stamps_the_provider_reported_expiry_into_the_secret(monkeypatch):
    """The expiry lives IN the existing secret JSON — no new storage — and comes
    from Whoop's own `expires_in`, never a guessed constant."""
    sm = _FakeSM()
    monkeypatch.setattr(whoop.boto3, "client", lambda *a, **k: sm)
    monkeypatch.setattr(whoop, "_refresh_access_token", lambda *a, **k: ("at-new", "rt-new", 3600))

    before = int(time.time())
    out = whoop.authenticate(_secret())

    assert before + 3600 <= out["access_token_expires_at"] <= int(time.time()) + 3600
    assert sm.writes, "the rotated secret is persisted immediately"
    assert sm.writes[0][1]["access_token_expires_at"] == out["access_token_expires_at"]


def test_rotation_without_expires_in_clears_the_stamp(monkeypatch):
    """If the provider stops reporting a lifetime we must not keep an old stamp
    alive — a stale expiry would reuse a dead token for an hour."""
    monkeypatch.setattr(whoop.boto3, "client", lambda *a, **k: _FakeSM())
    monkeypatch.setattr(whoop, "_refresh_access_token", lambda *a, **k: ("at-new", "rt-new", 0))

    out = whoop.authenticate(_secret(access_token_expires_at=int(time.time()) + 90))

    assert "access_token_expires_at" not in out


# ── Box 2: the token POST is non-idempotent — no blind retry ──────────────────


def test_token_post_uses_the_non_idempotent_escape_hatch(monkeypatch):
    """http_retry documents max_attempts=1 for 'a POST whose 5xx might mean the
    write actually landed'. Whoop's token POST is exactly that: the server
    consumes the single-use refresh_token before responding."""
    seen = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"access_token": "at", "refresh_token": "rt", "expires_in": 3600}).encode()

    def _fake(req, timeout=30, max_attempts=None):
        seen["max_attempts"] = max_attempts
        return _Resp()

    monkeypatch.setattr(whoop, "urlopen_with_retry", _fake)

    assert whoop._refresh_access_token("cid", "csec", "rt-old") == ("at", "rt", 3600)
    assert seen["max_attempts"] == 1, "the shared retry policy must be disabled for this POST"


def test_a_5xx_pair_costs_exactly_two_posts_not_the_three_attempt_policy(monkeypatch):
    """Drives the REAL http_retry code: with the escape hatch engaged, the only
    second attempt is whoop's own classified probe — 2 POSTs total, never the
    3-attempt/2s/8s policy."""
    from common import http_retry

    attempts = {"n": 0}

    def fake_urlopen(req, timeout=30):
        attempts["n"] += 1
        raise _http_error(502, "Bad Gateway")

    monkeypatch.setattr(http_retry.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(http_retry.time, "sleep", lambda *_: None)

    with pytest.raises(urllib.error.HTTPError) as ei:
        whoop._refresh_access_token("cid", "csec", "rt-old")

    assert ei.value.code == 502
    assert attempts["n"] == 2, "one POST + one classified probe"


# ── Box 3: 400-after-5xx = lost rotation, with its own signal ─────────────────


def _token_endpoint(monkeypatch, responses):
    """Sequence a fake token endpoint: each entry is an int status (raise) or a
    dict token body (return)."""
    seq = list(responses)
    calls = {"n": 0}

    class _Resp:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(self.body).encode()

    def _fake(req, timeout=30, max_attempts=None):
        calls["n"] += 1
        nxt = seq.pop(0)
        if isinstance(nxt, int):
            raise _http_error(nxt)
        return _Resp(nxt)

    monkeypatch.setattr(whoop, "urlopen_with_retry", _fake)
    return calls


def test_5xx_then_400_is_classified_as_a_lost_rotation(monkeypatch):
    """The measured 08-04 fingerprint: the 502'd POST had already rotated the
    token server-side, so the probe with the SAME token is rejected. That is
    provable credential death, not a generic auth expiry."""
    _token_endpoint(monkeypatch, [502, 400])

    with pytest.raises(whoop.WhoopRotationLost) as ei:
        whoop._refresh_access_token("cid", "csec", "rt-old")

    assert "WHOOP_ROTATION_LOST" in str(ei.value)
    assert "re-auth required NOW" in str(ei.value), "the operator-visible text must name the fix"


def test_5xx_then_success_recovers_inside_the_invocation(monkeypatch):
    """The other half of the 5xx population — genuinely unprocessed. The #2069
    benefit is kept: recover in this run rather than wait for the next one."""
    calls = _token_endpoint(monkeypatch, [503, {"access_token": "at-2", "refresh_token": "rt-2", "expires_in": 3600}])

    assert whoop._refresh_access_token("cid", "csec", "rt-old") == ("at-2", "rt-2", 3600)
    assert calls["n"] == 2


def test_5xx_then_5xx_is_transport_not_rotation_loss(monkeypatch):
    """Only a 400 proves the token was consumed. A second 5xx says nothing —
    it must NOT be dressed up as credential death."""
    _token_endpoint(monkeypatch, [502, 503])

    with pytest.raises(urllib.error.HTTPError) as ei:
        whoop._refresh_access_token("cid", "csec", "rt-old")
    assert ei.value.code == 503


def test_a_first_pass_400_is_not_a_lost_rotation(monkeypatch):
    """A 400 with no preceding 5xx is the ordinary stale-token/race case that
    `_rotate` already handles — it must reach that branch as an HTTPError."""
    _token_endpoint(monkeypatch, [400])

    with pytest.raises(urllib.error.HTTPError) as ei:
        whoop._refresh_access_token("cid", "csec", "rt-old")
    assert ei.value.code == 400


def test_authenticate_emits_the_distinct_rotation_lost_signal(monkeypatch):
    """The signal rides the EXISTING OAuth channel (same namespace + Source
    dimension as IngestAuthHealthy, on a grant the ingestion role already
    holds) — but as its own metric, so 'rotation lost, re-auth NOW' is
    separable from 'credential expired'. The generic latch still happens: the
    exception is marked so the framework's breaker catches it."""
    cw = _FakeCW()
    monkeypatch.setattr(whoop, "_cw", cw)
    monkeypatch.setattr(whoop, "_refresh_access_token", _raiser(whoop.WhoopRotationLost("WHOOP_ROTATION_LOST — re-auth required NOW")))

    with pytest.raises(whoop.WhoopRotationLost) as ei:
        whoop.authenticate(_secret())

    assert ab.looks_like_auth_failure(ei.value) is True, "must still latch the breaker (stop hammering a dead credential)"
    (call,) = cw.calls
    assert call["Namespace"] == "LifePlatform/OAuth"
    (point,) = call["MetricData"]
    assert point["MetricName"] == "OAuthRotationLost"
    assert point["Dimensions"] == [{"Name": "Source", "Value": "whoop"}]
    assert point["Value"] == 1.0


def test_rotation_lost_metric_failure_never_breaks_the_run(monkeypatch):
    class _DeadCW:
        def put_metric_data(self, **_kw):
            raise RuntimeError("cloudwatch down")

    monkeypatch.setattr(whoop, "_cw", _DeadCW())
    monkeypatch.setattr(whoop, "_refresh_access_token", _raiser(whoop.WhoopRotationLost("lost")))

    with pytest.raises(whoop.WhoopRotationLost):
        whoop.authenticate(_secret())


# ── Box 4: invalidate the warm-container secret cache after a rotation ────────


def test_persisting_a_rotation_invalidates_the_secret_cache(monkeypatch):
    """Pre-#2196 `secret_cache.invalidate` had ZERO callers, so a warm container
    served the PRE-rotation secret for up to 15 minutes — every 'a concurrent
    invocation already rotated the token; adopting it' WARNING is that."""
    monkeypatch.setattr(whoop.boto3, "client", lambda *a, **k: _FakeSM())
    secret_cache._cache[whoop.SECRET_NAME] = {"value": json.dumps({"refresh_token": "rt-STALE"}), "ts": time.time()}

    assert whoop._persist_refreshed_secret({"refresh_token": "rt-new"}) is True
    assert whoop.SECRET_NAME not in secret_cache._cache


def test_framework_writeback_invalidates_the_secret_cache(monkeypatch):
    """The framework's own writeback is the shared rotation point for every
    rotating-token source — invalidate there too, not just in whoop."""
    sm = _FakeSM(secret_string=json.dumps({"refresh_token": "rt-old"}))

    class _FakeTable:
        def get_item(self, **_kw):
            return {}

        def put_item(self, **_kw):
            return {}

        def delete_item(self, **_kw):
            return {}

        def query(self, **_kw):
            return {"Items": []}

    monkeypatch.setattr(fw, "_init_aws", lambda config: (_FakeTable(), None, sm))
    config = fw.IngestionConfig(source_name="testsrc", secret_id="life-platform/testsrc", enable_secret_writeback=True)

    fw.run_ingestion(
        config,
        authenticate_fn=lambda secret: {"refresh_token": "rt-new"},
        fetch_day_fn=lambda creds, date_str: None,
        transform_fn=lambda raw, date_str: [],
        event={},
        context=None,
    )

    assert sm.writes, "writeback must have run"
    assert "life-platform/testsrc" not in secret_cache._cache, "the stale pre-rotation copy must be dropped"


# ── Box 5: _reconcile honors the auth breaker ────────────────────────────────


def test_reconcile_skips_while_the_breaker_is_latched(monkeypatch):
    """08-03 → 08-07: the credential was dead and the daily reconcile invocation
    authenticated anyway, one more exchange per day against a provider that had
    already locked us out."""
    monkeypatch.setattr(whoop, "check_breaker", lambda *a, **k: {"marked_at": "2026-08-04T00:00:00+00:00"})
    monkeypatch.setattr(whoop, "authenticate", _boom)
    monkeypatch.setattr(whoop.boto3, "client", _boom)

    resp = whoop._reconcile({"reconcile": True}, None)

    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["skipped"] == "auth_failure_circuit_breaker"
    assert body["marked_at"] == "2026-08-04T00:00:00+00:00"


def test_reconcile_runs_normally_when_the_breaker_is_clear(monkeypatch):
    monkeypatch.setattr(whoop, "check_breaker", lambda *a, **k: None)
    monkeypatch.setattr(whoop.boto3, "client", lambda *a, **k: _FakeSM(secret_string=json.dumps(_secret())))
    monkeypatch.setattr(whoop, "authenticate", lambda secret: dict(secret, access_token="at"))
    monkeypatch.setattr(whoop, "_fetch_all_records", lambda *a, **k: [])
    monkeypatch.setattr(whoop, "_fetch_stored_records", lambda *a, **k: (set(), []))
    monkeypatch.setattr(whoop, "_emit_reconciliation_metric", lambda n: None)

    body = json.loads(whoop._reconcile({"reconcile": True}, None)["body"])
    assert body["missing_count"] == 0


def test_reconcile_marks_the_breaker_when_it_discovers_an_auth_failure(monkeypatch):
    """Swallowing the auth failure (the old behavior) left the breaker unlatched,
    so the next reconcile went straight back at the dead endpoint."""
    marks = []
    monkeypatch.setattr(whoop, "check_breaker", lambda *a, **k: None)
    monkeypatch.setattr(whoop, "mark_failure", lambda table, source_name, user_id, error_msg, logger: marks.append(source_name))
    monkeypatch.setattr(whoop.boto3, "client", lambda *a, **k: _FakeSM(secret_string=json.dumps(_secret())))
    monkeypatch.setattr(whoop, "authenticate", _raiser(_http_error(401)))

    resp = whoop._reconcile({"reconcile": True}, None)

    assert resp["statusCode"] == 200, "a reconcile failure must stay non-fatal"
    assert marks == ["whoop"]


def test_reconcile_does_not_mark_on_a_non_auth_failure(monkeypatch):
    marks = []
    monkeypatch.setattr(whoop, "check_breaker", lambda *a, **k: None)
    monkeypatch.setattr(whoop, "mark_failure", lambda table, source_name, user_id, error_msg, logger: marks.append(source_name))
    monkeypatch.setattr(whoop.boto3, "client", lambda *a, **k: _FakeSM(secret_string=json.dumps(_secret())))
    monkeypatch.setattr(whoop, "authenticate", _raiser(RuntimeError("whoop gateway timeout")))

    whoop._reconcile({"reconcile": True}, None)

    assert marks == [], "a transport failure must not latch the auth breaker"


# ── Box 6: a transient data-endpoint 401 must not latch ──────────────────────


def test_401_seconds_after_a_healthy_rotation_does_not_latch(monkeypatch):
    """2026-08-01, exactly: refresh succeeded at 12:00:20, a data endpoint 401'd
    at 12:00:28, and the 24h breaker latched on a credential that was never
    dead. The raised exception must be invisible to the auth classifier."""
    whoop._rotation_state["rotated_at"] = time.time()
    monkeypatch.setattr(whoop, "_fetch_all_endpoints", _raiser(_http_error(401)))
    monkeypatch.setattr(whoop, "_glitch_marker_is_fresh", lambda: False)
    marked = []
    monkeypatch.setattr(whoop, "_mark_glitch", lambda: marked.append(1))

    with pytest.raises(whoop.WhoopTransientAuthGlitch) as ei:
        whoop.fetch_day({"access_token": "at"}, "2026-08-06")

    assert ab.looks_like_auth_failure(ei.value) is False, "the framework must NOT trip the breaker on this"
    assert marked == [1], "the one-shot grace must be recorded durably"


def test_the_grace_message_can_never_contain_a_classifier_substring(monkeypatch):
    """Guarding the SET, not the instance: the classifier matches on substrings,
    so an age of 401 SECONDS (inside the 600s grace window) would have made the
    message self-latch. Rendered in minutes for exactly that reason."""
    whoop._rotation_state["rotated_at"] = time.time() - 401
    monkeypatch.setattr(whoop, "_fetch_all_endpoints", _raiser(_http_error(401)))
    monkeypatch.setattr(whoop, "_glitch_marker_is_fresh", lambda: False)
    monkeypatch.setattr(whoop, "_mark_glitch", lambda: None)

    with pytest.raises(whoop.WhoopTransientAuthGlitch) as ei:
        whoop.fetch_day({"access_token": "at"}, "2026-08-06")

    msg = str(ei.value)
    assert "401" not in msg and "403" not in msg
    assert ab.looks_like_auth_failure(ei.value) is False


def test_a_recurring_401_latches_the_breaker(monkeypatch):
    """The grace is one-shot and durable: if the previous run already used it,
    this one is a real auth failure and must latch."""
    whoop._rotation_state["rotated_at"] = time.time()
    monkeypatch.setattr(whoop, "_fetch_all_endpoints", _raiser(_http_error(401)))
    monkeypatch.setattr(whoop, "_glitch_marker_is_fresh", lambda: True)
    monkeypatch.setattr(whoop, "_mark_glitch", _boom)

    with pytest.raises(urllib.error.HTTPError) as ei:
        whoop.fetch_day({"access_token": "at"}, "2026-08-06")

    assert ei.value.code == 401
    assert ab.looks_like_auth_failure(ei.value) is True


def test_401_long_after_the_rotation_still_latches(monkeypatch):
    """The discriminator is 'the refresh succeeded SECONDS ago in this same
    invocation'. Outside that window a 401 is what it has always been."""
    whoop._rotation_state["rotated_at"] = time.time() - (whoop._ROTATION_GRACE_SECONDS + 60)
    monkeypatch.setattr(whoop, "_fetch_all_endpoints", _raiser(_http_error(401)))
    monkeypatch.setattr(whoop, "_glitch_marker_is_fresh", _boom)

    with pytest.raises(urllib.error.HTTPError) as ei:
        whoop.fetch_day({"access_token": "at"}, "2026-08-06")
    assert ei.value.code == 401


def test_non_401_errors_are_untouched(monkeypatch):
    monkeypatch.setattr(whoop, "_fetch_all_endpoints", _raiser(_http_error(500)))

    with pytest.raises(urllib.error.HTTPError) as ei:
        whoop.fetch_day({"access_token": "at"}, "2026-08-06")
    assert ei.value.code == 500


def test_a_rejected_REUSED_token_spends_one_rotation_and_retries(monkeypatch):
    """The regression the expiry gate could otherwise introduce: before #2196
    every run refreshed, so a stored access token could never go stale
    mid-flight. Now it can — so a 401 on a REUSED token buys one rotation and a
    single retry before anything is concluded about the credential."""
    seen = []

    def _fetch(token, _s, _e):
        seen.append(token)
        if token == "at-old":
            raise _http_error(401)
        return {"recovery": {"records": []}}

    def _rotate(secret):
        whoop._rotation_state["rotated_at"] = time.time()
        return dict(secret, access_token="at-new", refresh_token="rt-new")

    monkeypatch.setattr(whoop, "_fetch_all_endpoints", _fetch)
    monkeypatch.setattr(whoop, "_rotate", _rotate)
    creds = _secret()

    assert whoop.fetch_day(creds, "2026-08-06") == {"recovery": {"records": []}}
    assert seen == ["at-old", "at-new"]
    assert creds["access_token"] == "at-new", "later dates in this run must reuse the new token"


def test_a_genuinely_dead_credential_still_latches_through_the_retry_path(monkeypatch):
    """Guarding the negative: if the forced rotation itself fails as auth, that
    propagates untouched — the grace must never rescue a real death."""
    monkeypatch.setattr(whoop, "_fetch_all_endpoints", _raiser(_http_error(401)))
    monkeypatch.setattr(whoop, "_rotate", _raiser(ab.mark_as_auth_failure(_http_error(400))))

    with pytest.raises(urllib.error.HTTPError) as ei:
        whoop.fetch_day(_secret(), "2026-08-06")

    assert ei.value.code == 400
    assert ab.looks_like_auth_failure(ei.value) is True


# ── the durable one-shot marker itself ───────────────────────────────────────


def test_glitch_marker_freshness_is_age_based(monkeypatch):
    class _T:
        def __init__(self, item):
            self.item = item

        def get_item(self, **_kw):
            return {"Item": self.item} if self.item else {}

    monkeypatch.setattr(whoop, "_table", _T({"marked_at_epoch": int(time.time()) - 60}))
    assert whoop._glitch_marker_is_fresh() is True

    monkeypatch.setattr(whoop, "_table", _T({"marked_at_epoch": int(time.time()) - whoop._GLITCH_TTL_SECONDS - 1}))
    assert whoop._glitch_marker_is_fresh() is False, "an expired-but-unreaped row must not latch a healthy run"

    monkeypatch.setattr(whoop, "_table", _T(None))
    assert whoop._glitch_marker_is_fresh() is False


def test_glitch_marker_read_failure_fails_open(monkeypatch):
    class _T:
        def get_item(self, **_kw):
            raise RuntimeError("ddb down")

    monkeypatch.setattr(whoop, "_table", _T())
    assert whoop._glitch_marker_is_fresh() is False


def test_glitch_marker_write_uses_decimal_and_a_ttl(monkeypatch):
    """DDB rejects float; the marker must also self-reap like the auth breaker's."""
    from decimal import Decimal

    written = {}

    class _T:
        def put_item(self, Item=None, **_kw):
            written.update(Item)

    monkeypatch.setattr(whoop, "_table", _T())
    whoop._mark_glitch()

    assert written["sk"] == whoop._GLITCH_SK
    assert written["pk"] == "USER#matthew#SOURCE#whoop"
    assert isinstance(written["marked_at_epoch"], Decimal)
    assert written["ttl"] > time.time()
