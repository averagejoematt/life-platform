"""tests/test_public_write_hardening.py — elite review (2026-06-15) batch 2.

Hardening for the public write surface on site_api_social.py:
  * challenge_vote — reject catalog_ids that aren't real public challenges
    (previously minted arbitrary VOTES#challenges/CH#<anything> rows); fail-closed
    when the catalog can't load.
  * challenge_checkin — #6087: a reader's check-in never touches the owner's row
    (it was an idempotent per-date REPLACE of his own entry before).
  * submit_finding — content-based id so a same-day retry overwrites the same S3
    object instead of creating a duplicate pending finding.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import site_api_social as social  # noqa: E402


def _event(body):
    # #1221/#2932: identity is CloudFront-Viewer-Address (the edge-set header) —
    # the forgeable pair is kept alongside it so these tests run against the
    # envelope production actually produces, with the trusted header winning.
    # Without it every caller is identity-less: rate limiting fails CLOSED into one
    # shared bucket and the capture doors' content dedup switches OFF (per-request
    # ids), so `test_submit_finding_id_is_content_stable` would assert nothing real.
    return {
        "body": json.dumps(body),
        "headers": {"x-forwarded-for": "1.2.3.4", "cloudfront-viewer-address": "1.2.3.4:23456"},
        "requestContext": {"http": {"sourceIp": "1.2.3.4"}},
    }


class _FakeTable:
    def __init__(self, get_item_result=None):
        self._get = get_item_result
        self.update_args = None
        self.put_called = False

    def get_item(self, **_kw):
        return {"Item": self._get} if self._get else {}

    def put_item(self, **_kw):
        self.put_called = True
        return {}

    def update_item(self, **kw):
        self.update_args = kw
        return {"Attributes": {"vote_count": 1}}


# ── challenge_vote: catalog_id validation ─────────────────────────────────────


def _pin_catalog(monkeypatch, catalog):
    """Inject the catalog cache AND pin its TTL stamp (None = pinned — the
    documented test-injection contract at site_api_social._challenge_catalog_cache_at).

    Patching only the cache dict is order-dependent: any earlier test that ran a
    real load leaves a monotonic stamp, and once the suite has run longer than the
    config TTL, _catalog_cached() ignores the injected dict and re-loads from S3 —
    which 503s under CI's FAKE creds but silently serves the REAL catalog under
    local creds (the fixture-must-be-the-wire failure mode; redded main 2026-08-17)."""
    monkeypatch.setattr(social, "_challenge_catalog_cache", catalog)
    monkeypatch.setattr(social, "_challenge_catalog_cache_at", None)


def test_vote_rejects_unknown_catalog_id(monkeypatch):
    _pin_catalog(monkeypatch, {"challenges": [{"id": "cold-shower", "public": True}]})
    ft = _FakeTable()
    monkeypatch.setattr(social, "table", ft)
    r = social._handle_challenge_vote(_event({"catalog_id": "totally-fake"}))
    assert r["statusCode"] == 404
    assert ft.put_called is False  # rejected before any write


def test_vote_rejects_private_challenge(monkeypatch):
    # public:false vice entries must not be voteable from the public site
    _pin_catalog(monkeypatch, {"challenges": [{"id": "no-zzq-30", "public": False}]})
    ft = _FakeTable()
    monkeypatch.setattr(social, "table", ft)
    r = social._handle_challenge_vote(_event({"catalog_id": "no-zzq-30"}))
    assert r["statusCode"] == 404
    assert ft.put_called is False


def test_vote_503_when_catalog_unavailable(monkeypatch):
    _pin_catalog(monkeypatch, {})  # empty → _public_challenge_ids returns None
    ft = _FakeTable()
    monkeypatch.setattr(social, "table", ft)
    r = social._handle_challenge_vote(_event({"catalog_id": "cold-shower"}))
    assert r["statusCode"] == 503
    assert ft.put_called is False


def test_vote_accepts_known_catalog_id(monkeypatch):
    _pin_catalog(monkeypatch, {"challenges": [{"id": "cold-shower", "public": True}]})
    ft = _FakeTable()
    monkeypatch.setattr(social, "table", ft)
    r = social._handle_challenge_vote(_event({"catalog_id": "cold-shower"}))
    assert r["statusCode"] == 200
    assert ft.put_called is True
    assert json.loads(r["body"])["new_count"] == 1


# ── challenge_checkin: a reader never writes the owner's row (#6087) ──────────
# Replaces `test_checkin_dedups_same_date`, which pinned a same-date REPLACE inside the
# owner's own `daily_checkins` — the very write that let a stranger overwrite his check-in. The
# full contract (switch, replay, concurrency, duplicates) is tests/test_challenge_checkin_isolation_6087.py.


def _open_reader_door(monkeypatch):
    from web import site_api_social_challenges as chal

    monkeypatch.setattr(chal, "PUBLIC_CHECKIN_LIVE", True)
    monkeypatch.setattr(social, "_rate_check", lambda *a, **k: (True, 1, 0))


def test_checkin_while_shut_writes_nothing(monkeypatch):
    ft = _FakeTable(get_item_result={"status": "active", "duration_days": 7, "daily_checkins": []})
    monkeypatch.setattr(social, "table", ft)
    r = social._handle_challenge_checkin(_event({"challenge_id": "cs", "completed": True}))
    assert r["statusCode"] == 403
    assert ft.update_args is None and ft.put_called is False


def test_checkin_same_date_never_replaces_the_owner_entry(monkeypatch):
    _open_reader_door(monkeypatch)
    existing = {
        "status": "active",
        "duration_days": 7,
        "daily_checkins": [{"date": "2026-06-15", "completed": True, "logged_at": "earlier"}],
    }
    ft = _FakeTable(get_item_result=existing)
    monkeypatch.setattr(social, "table", ft)
    r = social._handle_challenge_checkin(_event({"challenge_id": "cs", "completed": False, "date": "2026-06-15"}))
    assert r["statusCode"] == 400  # a reader logs today only — never a chosen past day
    r = social._handle_challenge_checkin(_event({"challenge_id": "cs", "completed": False}))
    assert r["statusCode"] == 200
    assert ft.update_args is None, "the reader door must never update the owner's challenge row"
    assert ft.put_called is True  # its own reader-partition item
    assert "total_checkins" not in json.loads(r["body"])  # no owner progress echoed to a stranger


# ── submit_finding: content-stable id ─────────────────────────────────────────


def test_submit_finding_id_is_content_stable(monkeypatch):
    class _FakeS3:
        def put_object(self, **_kw):
            return {}

    monkeypatch.setattr(social.boto3, "client", lambda *a, **k: _FakeS3())
    # Rate limiting is now DDB-backed; force the in-memory fallback + clear it so
    # the two retries deterministically pass the limiter (no real DDB / no creds).
    monkeypatch.setattr(social, "_RATE_LIMITER_READY", False)
    body = {"metric_a": "sleep", "metric_b": "hrv", "finding": "more sleep tracks higher hrv over time"}

    social._FALLBACK_RATE_STORE.clear()  # #2237: one shared fallback store, not a per-endpoint dict
    r1 = social._handle_submit_finding(_event(body))
    social._FALLBACK_RATE_STORE.clear()  # bypass the per-IP rate limit for the retry
    r2 = social._handle_submit_finding(_event(body))

    id1 = json.loads(r1["body"])["finding_id"]
    id2 = json.loads(r2["body"])["finding_id"]
    assert id1 == id2, "identical submission must yield the same id (idempotent S3 key)"
