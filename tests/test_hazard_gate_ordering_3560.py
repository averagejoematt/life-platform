#!/usr/bin/env python3
"""tests/test_hazard_gate_ordering_3560.py — the hazard gate wins over MONEY, behaviourally.

#3050 wired a deterministic hazard classifier in front of every free-text AI door and
wrote the ordering rule into `_req.hazard_gate`'s docstring: it runs before the WR-40
privacy filter, before the rate limit, and (implied by "this path is $0") before the
budget pause. Only the first clause was ever asserted. The other two were false:

  * `_handle_board_ask` charged its DynamoDB rate token as its 3rd statement and only
    reached `_req.hazard_gate` ~45 lines later — a reader past the hourly budget who
    typed "I'm having chest pain, should I still train today?" got
    `429 {"error": "Rate limit reached. Try again in an hour."}`.
  * All three doors called `_ai_paused_response()` first, so at budget tier 3 the same
    reader got the "the AI assistant is paused for the rest of the month" card.

Both are now ordered behind the gate. `tests/test_safety_contract_3050.py` owns the
STRUCTURAL rule (an AST walk with its own positive control); this file owns the WIRE:
it calls the real handlers with the real gates denying, and asserts what a person
actually receives. The structural test alone would have passed on a handler whose
hazard gate ran first and then fell through to the 429 anyway.

Every assertion here has a matching NEGATIVE CONTROL in the same test: the same request
with a BENIGN question must still be refused. Without it, deleting the rate limit and
the pause outright would turn this file green.

Run: python3 -m pytest tests/test_hazard_gate_ordering_3560.py -v
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, _REPO)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

import pytest  # noqa: E402
from ai import safety_contract as sc  # noqa: E402
from web import site_api_ai_lambda as A  # noqa: E402

HAZARD_Q = "I'm having chest pain, should I still train today?"
BENIGN_Q = "what drove my HRV down last week?"


def _event(body: dict) -> dict:
    return {
        "rawPath": "/api/board_ask",
        "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.7"}},
        "headers": {},
        "body": json.dumps(body),
    }


def _no_model(*_a, **_k):
    raise AssertionError("a paid path was reached — the hazard gate must short-circuit before any model call")


@pytest.fixture
def paused(monkeypatch):
    """Budget tier 3: `_ai_paused_response()` returns the 'paused' card."""
    card = {
        "statusCode": 200,
        "headers": {**A.CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps({"answer": "The AI assistant is paused…", "paused": True, "remaining": 0}),
    }
    monkeypatch.setattr(A, "_ai_paused_response", lambda: dict(card), raising=True)


@pytest.fixture
def not_paused(monkeypatch):
    monkeypatch.setattr(A, "_ai_paused_response", lambda: None, raising=True)


@pytest.fixture
def rate_limited(monkeypatch):
    """Past the hourly budget on BOTH limiters — the DDB-backed production path
    (`board_ask`) and `/api/ask`'s counter."""
    monkeypatch.setattr(A, "_RATE_LIMITER_READY", True, raising=False)
    monkeypatch.setattr(A, "_ddb_rate_check", lambda *a, **k: (False, 0, 3600), raising=False)
    monkeypatch.setattr(A, "_ask_rate_check", lambda *a, **k: (False, 0), raising=False)
    monkeypatch.setattr(A, "_emit_rate_limit_metric", lambda *_a, **_k: None, raising=False)


@pytest.fixture
def not_rate_limited(monkeypatch):
    monkeypatch.setattr(A, "_RATE_LIMITER_READY", True, raising=False)
    monkeypatch.setattr(A, "_ddb_rate_check", lambda *a, **k: (True, 5, 0), raising=False)
    monkeypatch.setattr(A, "_ask_rate_check", lambda *a, **k: (True, 5), raising=False)


def _safety_payload(resp: dict, key: str) -> dict:
    assert resp["statusCode"] == 200, f"expected the resource copy, got {resp['statusCode']}: {resp['body'][:200]}"
    body = json.loads(resp["body"])
    assert body.get("safety") == sc.ACUTE_SYMPTOM, f"not the hazard response: {body}"
    assert body[key] == sc.RESPONSES[sc.ACUTE_SYMPTOM]
    return body


# ── /api/ask ─────────────────────────────────────────────────────────────────────


def test_ask_serves_the_resource_copy_when_rate_limited(monkeypatch, not_paused, rate_limited):
    monkeypatch.setattr(A, "_get_anthropic_key", _no_model, raising=True)
    resp = A._handle_ask(_event({"question": HAZARD_Q}))
    _safety_payload(resp, "answer")

    # NEGATIVE CONTROL: the limiter is still wired and still refuses everyone else.
    benign = A._handle_ask(_event({"question": BENIGN_Q}))
    assert benign["statusCode"] == 429, "the rate limit stopped working — the test above proves nothing"


def test_ask_serves_the_resource_copy_at_budget_tier_3(monkeypatch, paused, not_rate_limited):
    monkeypatch.setattr(A, "_get_anthropic_key", _no_model, raising=True)
    resp = A._handle_ask(_event({"question": HAZARD_Q}))
    _safety_payload(resp, "answer")

    benign = A._handle_ask(_event({"question": BENIGN_Q}))
    assert json.loads(benign["body"]).get("paused") is True, "the budget pause stopped working"


# ── /api/board_ask (the widest door: up to 12 Bedrock calls) ─────────────────────


def test_board_ask_serves_the_resource_copy_when_rate_limited(not_paused, rate_limited):
    resp = A._handle_board_ask(_event({"question": HAZARD_Q}))
    _safety_payload(resp, "response")

    benign = A._handle_board_ask(_event({"question": BENIGN_Q}))
    assert benign["statusCode"] == 429
    assert json.loads(benign["body"])["error"].startswith("Rate limit reached")


def test_board_ask_serves_the_resource_copy_at_budget_tier_3(paused, not_rate_limited):
    resp = A._handle_board_ask(_event({"question": HAZARD_Q}))
    _safety_payload(resp, "response")

    benign = A._handle_board_ask(_event({"question": BENIGN_Q}))
    assert json.loads(benign["body"]).get("paused") is True


def test_board_ask_serves_the_resource_copy_past_the_in_memory_hourly_budget(monkeypatch, not_paused):
    """The fail-open fallback limiter, exercised literally: the IP has already spent
    every token of the hour, so the NEXT question is over the line."""
    monkeypatch.setattr(A, "_RATE_LIMITER_READY", False, raising=False)
    monkeypatch.setattr(A, "_emit_rate_limit_metric", lambda *_a, **_k: None, raising=False)
    store: dict = {}
    monkeypatch.setattr(A, "_board_rate_store", store, raising=False)
    ev = _event({"question": HAZARD_Q})
    ip_hash = hashlib.sha256(A._rate_limit_identity(ev).encode()).hexdigest()[:16]
    store[ip_hash] = [int(time.time())] * A.BOARD_RATE_LIMIT

    _safety_payload(A._handle_board_ask(ev), "response")
    assert store[ip_hash] == [store[ip_hash][0]] * A.BOARD_RATE_LIMIT, "the hazard path must not burn a token"

    benign = A._handle_board_ask(_event({"question": BENIGN_Q}))
    assert benign["statusCode"] == 429, "the fallback limiter stopped working"


# ── the board FOLLOW-UP, reached through /api/board_ask's own dispatch ───────────


def _followup_body(question: str) -> dict:
    persona = sorted(A.COACH_ROSTER)[0]
    return {"session_token": "a" * 32, "persona": persona, "question": question}


def test_board_followup_serves_the_resource_copy_when_rate_limited(monkeypatch, not_paused, rate_limited):
    """#3560 moved the pause + the token charge OUT of the opening path and INTO the
    follow-up, below its own hazard gate. Both must still bite a benign follow-up."""
    monkeypatch.setattr(A, "_load_board_session", _no_model, raising=True)
    resp = A._handle_board_ask(_event(_followup_body(HAZARD_Q)))
    body = _safety_payload(resp, "response")
    assert body["persona"] == sorted(A.COACH_ROSTER)[0], "the follow-up's persona echo was lost"

    benign = A._handle_board_ask(_event(_followup_body(BENIGN_Q)))
    assert benign["statusCode"] == 429, "the follow-up no longer charges the shared board_ask token"


def test_board_followup_serves_the_resource_copy_at_budget_tier_3(monkeypatch, paused, not_rate_limited):
    monkeypatch.setattr(A, "_load_board_session", _no_model, raising=True)
    _safety_payload(A._handle_board_ask(_event(_followup_body(HAZARD_Q))), "response")

    benign = A._handle_board_ask(_event(_followup_body(BENIGN_Q)))
    assert json.loads(benign["body"]).get("paused") is True, "the follow-up no longer honours the budget pause"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
