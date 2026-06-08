"""
test_ai_endpoint_hardening.py — PG-10 guard for the public AI endpoints.

A public AI endpoint has an unbounded request denominator: one traffic spike
must not breach the $75 ceiling or serve uncalibrated claims (Dana/Anika).
Most of this hardening already shipped (DDB rate limit, paused-degrade, token
caps, input cap) — these tests pin the invariants so they can't silently
regress, and add the correlative/confidence-framing rule (PG-10's last gap).

Source-grep style (no AWS import needed) — matches test_site_api_routes.py.
"""

import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_PATH = os.path.join(HERE, "lambdas", "web", "site_api_ai_lambda.py")
with open(SRC_PATH, encoding="utf-8") as f:
    SRC = f.read()


def _handler_body(name: str) -> str:
    """Return the source of a top-level def up to the next top-level def."""
    m = re.search(rf"\ndef {re.escape(name)}\(.*?\n(?=\ndef |\Z)", SRC, re.S)
    assert m, f"handler {name} not found"
    return m.group(0)


def test_both_handlers_check_budget_pause():
    """Tier-2+ budget must short-circuit BEFORE any inference — on both endpoints,
    including the expensive 6-call board_ask. Otherwise a spike empties the budget."""
    for h in ("_handle_ask", "_handle_board_ask"):
        body = _handler_body(h)
        assert "_ai_paused_response()" in body, f"{h} must check the budget pause"
        # the pause check must come before any bedrock invoke in the handler
        pause_at = body.index("_ai_paused_response()")
        invoke_at = body.find("_bedrock_invoke")
        if invoke_at != -1:
            assert pause_at < invoke_at, f"{h}: pause check must precede inference"


def test_paused_response_is_200_not_5xx():
    """Graceful degrade: paused AI returns a calm HTTP-200 payload, never a 5xx."""
    m = re.search(r"def _ai_paused_response\(.*?\n(?=\ndef |\Z)", SRC, re.S)
    assert m, "_ai_paused_response not found"
    block = m.group(0)
    assert '"paused": True' in block or "'paused': True" in block
    assert "200" in block and "500" not in block and "503" not in block


def test_both_endpoints_rate_limited():
    """Per-IP DDB rate limiting on both endpoints (survives warm-container spread)."""
    assert "_ddb_rate_check" in SRC
    assert _handler_body("_handle_ask").count("_ask_rate_check") >= 1
    assert "_ddb_rate_check" in _handler_body("_handle_board_ask")
    # 429 returned on limit, with a Retry-After
    assert "429" in SRC and "Retry-After" in SRC


def test_per_request_token_caps_present():
    """Output tokens are bounded on every inference call (cost ceiling per request)."""
    assert re.search(r'"max_tokens":\s*\d+', SRC), "max_tokens cap missing"
    caps = [int(x) for x in re.findall(r'"max_tokens":\s*(\d+)', SRC)]
    assert caps and all(c <= 1000 for c in caps), f"max_tokens caps too high: {caps}"


def test_input_length_capped():
    """Question input is truncated so prompt-token cost is bounded regardless of payload."""
    assert SRC.count("[:500]") >= 2, "both endpoints must cap question length"


def test_ask_prompt_is_correlative_and_confidence_labelled():
    """PG-10: public AI output must be correlative (never causal) + confidence-labelled
    (the Henning standard) — the interpret-only rule."""
    m = re.search(r"def _ask_build_prompt\(.*?\n(?=\ndef |\Z)", SRC, re.S)
    assert m, "_ask_build_prompt not found"
    prompt = m.group(0).upper()
    assert "CORRELATIVE ONLY, NEVER CAUSAL" in prompt
    assert "LABEL CONFIDENCE HONESTLY" in prompt


def test_content_safety_filters_present():
    """Sensitive-category query filter + output scrub both wired (abuse guard)."""
    assert "_ASK_BLOCKED_PATTERNS" in SRC and "_ask_question_safe" in SRC
    assert "_scrub_blocked_terms" in SRC
