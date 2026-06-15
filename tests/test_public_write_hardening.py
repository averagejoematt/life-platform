"""tests/test_public_write_hardening.py — elite review (2026-06-15) batch 2.

Hardening for the public write surface on site_api_social.py:
  * challenge_vote — reject catalog_ids that aren't real public challenges
    (previously minted arbitrary VOTES#challenges/CH#<anything> rows); fail-closed
    when the catalog can't load.
  * challenge_checkin — idempotent per-date write (a double-tap / network retry
    must not duplicate a day and inflate completion_pct / success_rate).
  * submit_finding — content-based id so a same-day retry overwrites the same S3
    object instead of creating a duplicate pending finding.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import site_api_social as social  # noqa: E402


def _event(body):
    return {
        "body": json.dumps(body),
        "headers": {"x-forwarded-for": "1.2.3.4"},
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


def test_vote_rejects_unknown_catalog_id(monkeypatch):
    monkeypatch.setattr(social, "_challenge_catalog_cache", {"challenges": [{"id": "cold-shower", "public": True}]})
    ft = _FakeTable()
    monkeypatch.setattr(social, "table", ft)
    r = social._handle_challenge_vote(_event({"catalog_id": "totally-fake"}))
    assert r["statusCode"] == 404
    assert ft.put_called is False  # rejected before any write


def test_vote_rejects_private_challenge(monkeypatch):
    # public:false vice entries must not be voteable from the public site
    monkeypatch.setattr(social, "_challenge_catalog_cache", {"challenges": [{"id": "no-weed-30", "public": False}]})
    ft = _FakeTable()
    monkeypatch.setattr(social, "table", ft)
    r = social._handle_challenge_vote(_event({"catalog_id": "no-weed-30"}))
    assert r["statusCode"] == 404
    assert ft.put_called is False


def test_vote_503_when_catalog_unavailable(monkeypatch):
    monkeypatch.setattr(social, "_challenge_catalog_cache", {})  # empty → _public_challenge_ids returns None
    ft = _FakeTable()
    monkeypatch.setattr(social, "table", ft)
    r = social._handle_challenge_vote(_event({"catalog_id": "cold-shower"}))
    assert r["statusCode"] == 503
    assert ft.put_called is False


def test_vote_accepts_known_catalog_id(monkeypatch):
    monkeypatch.setattr(social, "_challenge_catalog_cache", {"challenges": [{"id": "cold-shower", "public": True}]})
    ft = _FakeTable()
    monkeypatch.setattr(social, "table", ft)
    r = social._handle_challenge_vote(_event({"catalog_id": "cold-shower"}))
    assert r["statusCode"] == 200
    assert ft.put_called is True
    assert json.loads(r["body"])["new_count"] == 1


# ── challenge_checkin: per-date idempotency ───────────────────────────────────


def test_checkin_dedups_same_date(monkeypatch):
    existing = {
        "status": "active",
        "duration_days": 7,
        "daily_checkins": [{"date": "2026-06-15", "completed": False, "logged_at": "earlier"}],
    }
    ft = _FakeTable(get_item_result=existing)
    monkeypatch.setattr(social, "table", ft)
    r = social._handle_challenge_checkin(_event({"challenge_id": "cs", "completed": True, "date": "2026-06-15"}))
    assert r["statusCode"] == 200
    written = ft.update_args["ExpressionAttributeValues"][":cl"]
    same_day = [c for c in written if c["date"] == "2026-06-15"]
    assert len(same_day) == 1, "same-date check-in must not duplicate"
    assert same_day[0]["completed"] is True, "re-check-in must replace with the new value"
    assert json.loads(r["body"])["total_checkins"] == 1


def test_checkin_keeps_distinct_dates(monkeypatch):
    existing = {
        "status": "active",
        "duration_days": 7,
        "daily_checkins": [{"date": "2026-06-14", "completed": True, "logged_at": "earlier"}],
    }
    ft = _FakeTable(get_item_result=existing)
    monkeypatch.setattr(social, "table", ft)
    r = social._handle_challenge_checkin(_event({"challenge_id": "cs", "completed": True, "date": "2026-06-15"}))
    assert r["statusCode"] == 200
    written = ft.update_args["ExpressionAttributeValues"][":cl"]
    assert {c["date"] for c in written} == {"2026-06-14", "2026-06-15"}
    assert json.loads(r["body"])["total_checkins"] == 2


# ── submit_finding: content-stable id ─────────────────────────────────────────


def test_submit_finding_id_is_content_stable(monkeypatch):
    class _FakeS3:
        def put_object(self, **_kw):
            return {}

    monkeypatch.setattr(social.boto3, "client", lambda *a, **k: _FakeS3())
    body = {"metric_a": "sleep", "metric_b": "hrv", "finding": "more sleep tracks higher hrv over time"}

    social._finding_rate_store.clear()
    r1 = social._handle_submit_finding(_event(body))
    social._finding_rate_store.clear()  # bypass the per-IP rate limit for the retry
    r2 = social._handle_submit_finding(_event(body))

    id1 = json.loads(r1["body"])["finding_id"]
    id2 = json.loads(r2["body"])["finding_id"]
    assert id1 == id2, "identical submission must yield the same id (idempotent S3 key)"
