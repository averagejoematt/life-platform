"""tests/test_nudge_finding_rate_limit.py — elite review (2026-06-15).

/api/nudge and /api/submit_finding used in-memory rate stores that reset on
Lambda cold start (so the limit was trivially evaded). They now use the shared
DynamoDB rate_limiter (the same one /api/ask uses), with the in-memory store as
a fail-open fallback. The site_api role already permits UpdateItem on RATE#* —
no IAM change.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import site_api_social as social  # noqa: E402


class _FakeLimiter:
    def __init__(self, allowed_seq):
        self.calls = []
        self._seq = list(allowed_seq)

    def __call__(self, table, endpoint, ip_hash, limit, window_seconds, fail_open):
        self.calls.append({"endpoint": endpoint, "limit": limit, "window": window_seconds})
        allowed = self._seq.pop(0) if self._seq else True
        return (allowed, 0, 0)


def _ev(body):
    return {
        "body": json.dumps(body),
        "headers": {"x-forwarded-for": "9.9.9.9"},
        "requestContext": {"http": {"sourceIp": "9.9.9.9"}},
    }


# ── nudge ─────────────────────────────────────────────────────────────────────


def test_nudge_uses_ddb_per_category_and_blocks(monkeypatch):
    rl = _FakeLimiter([False])
    monkeypatch.setattr(social, "_RATE_LIMITER_READY", True)
    monkeypatch.setattr(social, "_ddb_rate_check", rl)
    r = social._handle_nudge(_ev({"category": "watching"}))
    assert r["statusCode"] == 429
    assert rl.calls[0]["endpoint"] == "nudge:watching"  # per-category key
    assert rl.calls[0]["limit"] == 1
    assert rl.calls[0]["window"] == 3600


def test_nudge_allowed_returns_200(monkeypatch):
    monkeypatch.setattr(social, "_RATE_LIMITER_READY", True)
    monkeypatch.setattr(social, "_ddb_rate_check", _FakeLimiter([True]))
    r = social._handle_nudge(_ev({"category": "watching"}))
    assert r["statusCode"] == 200


# ── submit_finding ────────────────────────────────────────────────────────────


def test_submit_finding_uses_ddb_endpoint_and_limit(monkeypatch):
    rl = _FakeLimiter([False])
    monkeypatch.setattr(social, "_RATE_LIMITER_READY", True)
    monkeypatch.setattr(social, "_ddb_rate_check", rl)
    r = social._handle_submit_finding(_ev({"metric_a": "a", "metric_b": "b", "finding": "a finding long enough"}))
    assert r["statusCode"] == 429
    assert rl.calls[0]["endpoint"] == "submit_finding"
    assert rl.calls[0]["limit"] == social.FINDING_RATE_LIMIT


def test_submit_finding_allowed_writes(monkeypatch):
    monkeypatch.setattr(social, "_RATE_LIMITER_READY", True)
    monkeypatch.setattr(social, "_ddb_rate_check", _FakeLimiter([True]))

    class _S3:
        def put_object(self, **_k):
            return {}

    monkeypatch.setattr(social.boto3, "client", lambda *a, **k: _S3())
    r = social._handle_submit_finding(_ev({"metric_a": "sleep", "metric_b": "hrv", "finding": "more sleep tracks higher hrv"}))
    assert r["statusCode"] == 200


# ── fallback ──────────────────────────────────────────────────────────────────


def test_nudge_in_memory_fallback_still_limits(monkeypatch):
    # When the shared limiter is unavailable, the in-memory fallback must still
    # block a repeat within the hour (degraded but not absent).
    monkeypatch.setattr(social, "_RATE_LIMITER_READY", False)
    social._nudge_rate_store.clear()
    first = social._handle_nudge(_ev({"category": "watching"}))
    second = social._handle_nudge(_ev({"category": "watching"}))
    assert first["statusCode"] == 200
    assert second["statusCode"] == 429
