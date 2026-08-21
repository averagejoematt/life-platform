"""#1221 box 5 — /api/board_ask charges its Bedrock FAN-OUT, not just the request.

THE DEFECT
==========
`BOARD_RATE_LIMIT = 5` reads as "5 board_asks per IP per hour". It was not bounding
what it exists to bound. One board_ask makes **one Bedrock call per persona**, and the
persona list comes from the CALLER (`body["personas"]`, capped at 8). The rate check
also ran BEFORE the list was resolved, so a request asking for 8 coaches cost the same
one token as a request asking for 1.

Real ceiling: **5 x 7 = 35 Haiku calls/IP/hour**, against a limit that says 5. Two
numbers in the code were wrong about this: the constant's comment said "up to 6 Haiku
calls", and the `personas[:8]` cap never binds because COACH_ROSTER holds 7.

THE FIX
=======
One token is still charged up front (it covers the follow-up path, which really is one
Bedrock call, and a panel's first persona). The REST of the fan-out is charged after the
list is final and **before any paid call**, via the shared limiter's new `cost=`.

These tests assert the ECONOMICS, not the plumbing: N personas must cost N tokens, and
exhausting the budget through fan-out must 429 without reaching Bedrock.
"""

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

IP = "203.0.113.7"


def _ai():
    from web import site_api_ai_lambda as ai

    return ai


def _post(body):
    """Wire-shaped: carries the trusted header, since #1221 fails closed without it."""
    return {
        "rawPath": "/api/board_ask",
        "requestContext": {"http": {"method": "POST", "sourceIp": IP}},
        "headers": {"CloudFront-Viewer-Address": f"{IP}:16225"},
        "body": json.dumps(body),
    }


def _spy(ai, monkeypatch, allowed=True):
    """Record every rate-limiter charge so the test can assert the TOTAL cost."""
    charges = []

    def _fake(table, endpoint, ip_hash, limit, window_seconds=3600, fail_open=True, cost=1):
        charges.append(cost)
        return (allowed, max(0, limit - sum(charges)), 0 if allowed else 3600)

    monkeypatch.setattr(ai, "_ddb_rate_check", _fake)
    monkeypatch.setattr(ai, "_RATE_LIMITER_READY", True)
    monkeypatch.setattr(ai, "_ai_paused_response", lambda: None)
    monkeypatch.setattr(ai, "_get_anthropic_key", lambda: "fake-key")
    return charges


def test_a_panel_costs_one_token_per_persona(monkeypatch):
    ai = _ai()
    charges = _spy(ai, monkeypatch)
    # deliberately fails later (no Bedrock stub) — we only care about the charges
    try:
        ai._handle_board_ask(_post({"question": "how is my sleep trending?", "personas": ["sleep_coach", "nutrition_coach", "mind_coach"]}))
    except Exception:
        pass
    assert sum(charges) == 3, f"3 personas must cost 3 tokens, charged {charges} (total {sum(charges)})"


def test_a_single_persona_panel_still_costs_exactly_one(monkeypatch):
    """The fix must not over-charge the cheap case — no extra token when there is no fan-out."""
    ai = _ai()
    charges = _spy(ai, monkeypatch)
    try:
        ai._handle_board_ask(_post({"question": "how is my sleep trending?", "personas": ["sleep_coach"]}))
    except Exception:
        pass
    assert sum(charges) == 1, f"1 persona must cost 1 token, charged {charges}"


def test_the_maximum_panel_cannot_buy_more_than_it_pays_for(monkeypatch):
    """The headline number: a full panel used to be N Bedrock calls for 1 token."""
    ai = _ai()
    charges = _spy(ai, monkeypatch)
    roster = list(getattr(ai, "COACH_ROSTER", []))[:8]
    assert roster, "COACH_ROSTER is empty — the parser or the roster moved"
    try:
        ai._handle_board_ask(_post({"question": "full board please, everyone", "personas": roster}))
    except Exception:
        pass
    assert sum(charges) == len(roster), (
        f"a full {len(roster)}-coach panel must cost {len(roster)} tokens, charged {charges} "
        f"(total {sum(charges)}) — that gap IS the defect"
    )


def test_exhausting_the_budget_through_fanout_429s_before_any_paid_call(monkeypatch):
    """A panel that cannot afford its fan-out must be refused BEFORE Bedrock."""
    ai = _ai()
    _spy(ai, monkeypatch, allowed=False)
    called = []
    for attr in ("_get_anthropic_key",):
        monkeypatch.setattr(ai, attr, lambda: (called.append(attr), "fake-key")[1])
    resp = ai._handle_board_ask(
        _post({"question": "how is my sleep trending?", "personas": ["sleep_coach", "nutrition_coach", "mind_coach"]})
    )
    assert resp["statusCode"] == 429, f"expected 429, got {resp['statusCode']}"
    assert not called, "the AI key was fetched despite the rate limit — a paid path was reached"


def test_the_shared_limiter_defaults_to_cost_one(monkeypatch):
    """Every OTHER endpoint must be unaffected — `cost` is opt-in."""
    from common import rate_limiter

    seen = {}

    class _T:
        def update_item(self, **kw):
            seen.update(kw["ExpressionAttributeValues"])
            return {"Attributes": {"count": 1}}

    rate_limiter.check_rate_limit(_T(), endpoint="anything", ip_hash=hashlib.sha256(b"x").hexdigest()[:16], limit=5)
    assert seen[":inc"] == 1, f"default cost must be 1, got {seen[':inc']}"
