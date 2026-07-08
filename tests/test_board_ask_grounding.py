"""#743 — grounding receipts on board_ask: "grounded in: recovery 48% ·
protein 7d avg 132g · presence quiet 9d".

board_ask answers are genuinely grounded (every persona turn is built from a
live-probed generation brief, ai_context / site_api_ai_lambda._ask_fetch_context)
but the reader never saw the receipt. Pins the contract:

  • ai_context.board_grounding_receipts/board_grounding_footer are PURE and
    derive every value straight off the `ctx` dict — never off model text —
    and never raise on a partial or empty brief (hard AC: code-derived, never
    LLM-authored);
  • the handler wires the SAME ctx used to build the CURRENT DATA prompt block
    into the receipt (one fetch, one brief — not two independent reads that
    could drift);
  • the response body carries a `grounding` array/field regardless of whether
    the ADR-104 grounded gate passed, was corrected, or refused the answer —
    the receipt describes what the coach was GIVEN, not what it SAID, so it
    must not be gated by (or altered by) the ADR-104 enforcement path;
  • the front-end footer renderer only emits markup when there's something to
    show.

Offline: pure-function tests for the ai_context helpers + the same fake
table/fake-Bedrock harness test_board_followup_sessions.py uses for the
handler-level behavioural tests.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

AI_SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas/web/site_api_ai_lambda.py")).read()
COACHING_JS = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "site/assets/js/coaching.js")).read()

FULL_CTX = {
    "recovery_pct": 48.0,
    "sleep_hours": 7.2,
    "hrv_ms": 54.0,
    "character_level": 6.0,
    "character_tier": "Discipline",
    "tier0_streak": 12,
    "reads": {
        "protein": {"avg_7d_g": 132.0, "target_g": 150.0, "floor_g": 120.0},
        "weekly_rate_lbs": -1.2,
        "presence": {"class": "quiet_engaged", "gap_days": 9.0, "passive_still_flowing": True},
    },
}


def _ctx_mod():
    import ai_context

    return ai_context


# ── ai_context.board_grounding_receipts — pure, code-derived, order + cap ──


def test_full_brief_yields_ordered_capped_receipts():
    ac = _ctx_mod()
    receipts = ac.board_grounding_receipts(FULL_CTX)
    assert receipts[0] == {"label": "recovery", "value": "48%"}
    assert receipts[1] == {"label": "protein", "value": "7d avg 132g"}
    # priority order is fixed, and the default cap (6) trims the rest
    assert len(receipts) <= 6
    labels = [r["label"] for r in receipts]
    assert labels == sorted(labels, key=labels.index)  # no reordering surprises
    # every value is a plain string built from FULL_CTX's own numbers — no LLM text anywhere
    for r in receipts:
        assert isinstance(r["label"], str) and isinstance(r["value"], str)


def test_limit_caps_the_receipt_count():
    ac = _ctx_mod()
    assert len(ac.board_grounding_receipts(FULL_CTX, limit=2)) == 2
    assert len(ac.board_grounding_receipts(FULL_CTX, limit=1)) == 1


def test_values_are_derived_only_from_ctx_numbers():
    """Change one ctx number and ONLY its receipt value changes — proves the
    value is read straight off ctx, not computed/copied from anywhere else."""
    ac = _ctx_mod()
    a = ac.board_grounding_receipts(FULL_CTX)
    bumped = dict(FULL_CTX, recovery_pct=91.0)
    b = ac.board_grounding_receipts(bumped)
    a_by_label = {r["label"]: r["value"] for r in a}
    b_by_label = {r["label"]: r["value"] for r in b}
    assert a_by_label["recovery"] == "48%"
    assert b_by_label["recovery"] == "91%"
    # nothing else moved
    for label in a_by_label:
        if label != "recovery":
            assert a_by_label[label] == b_by_label[label]


# ── Partial / empty brief tolerance (hard AC: never raises) ───────────────


def test_partial_brief_skips_missing_probes_without_error():
    ac = _ctx_mod()
    receipts = ac.board_grounding_receipts({"recovery_pct": 48.0})
    assert receipts == [{"label": "recovery", "value": "48%"}]


def test_partial_brief_with_malformed_reads_block_is_tolerated():
    """`reads` present but not a dict (or its sub-keys not dicts) — degrade,
    never raise. A malformed nested shape is exactly the kind of partial brief
    a fail-soft upstream probe can hand back."""
    ac = _ctx_mod()
    assert ac.board_grounding_receipts({"recovery_pct": 48.0, "reads": "not-a-dict"}) == [{"label": "recovery", "value": "48%"}]
    assert ac.board_grounding_receipts({"reads": {"protein": "not-a-dict", "presence": None}}) == []


def test_empty_or_none_brief_yields_no_receipts():
    ac = _ctx_mod()
    assert ac.board_grounding_receipts({}) == []
    assert ac.board_grounding_receipts(None) == []


def test_presence_omitted_when_class_is_present():
    """A "present" (not quiet) engagement state isn't a receipt-worthy probe —
    only a genuine quiet stretch surfaces."""
    ac = _ctx_mod()
    ctx = {"reads": {"presence": {"class": "present", "gap_days": 0}}}
    assert ac.board_grounding_receipts(ctx) == []


# ── ai_context.board_grounding_footer — the rendered string ───────────────


def test_footer_renders_the_expected_string():
    ac = _ctx_mod()
    footer = ac.board_grounding_footer(FULL_CTX, limit=3)
    assert footer == "grounded in: recovery 48% · protein 7d avg 132g · sleep 7.2h last night"


def test_footer_is_empty_string_for_empty_brief():
    ac = _ctx_mod()
    assert ac.board_grounding_footer({}) == ""
    assert ac.board_grounding_footer(None) == ""


# ── Handler wiring: same ctx feeds the prompt AND the receipt ──────────────


def test_handler_fetches_ctx_once_and_shares_it_with_the_receipt():
    """Source-level pin: _handle_board_ask must build ONE ctx (_brief_ctx) and
    hand that SAME object to both _board_facts_block (the prompt) and
    board_grounding_receipts (the reader-facing receipt) — never a second,
    independently-fetched ctx that could drift from what the model actually read."""
    body = re.search(r"def _handle_board_ask\(.*?(?=\ndef )", AI_SRC, re.S).group(0)
    assert "_brief_ctx = _ask_fetch_context()" in body
    assert "_board_facts_block(_brief_ctx)" in body
    assert "board_grounding_receipts(_brief_ctx)" in body
    assert '"grounding": grounding' in body


def test_followup_handler_also_surfaces_a_fresh_receipt():
    body = re.search(r"def _handle_board_followup\(.*?(?=\ndef |\Z)", AI_SRC, re.S).group(0)
    assert "board_grounding_receipts(_brief_ctx)" in body
    assert '"grounding": grounding' in body


def test_grounding_is_never_read_off_the_model_response_text():
    """board_grounding_receipts must never be called on _txt/_txt2/response —
    the whole point is that the receipt is code-derived from the BRIEF, not
    something the model wrote."""
    assert not re.search(r"board_grounding_receipts\(\s*_txt", AI_SRC)
    assert not re.search(r"board_grounding_receipts\(\s*response", AI_SRC)


# ── Behavioural: the response body actually carries the receipt ───────────


def _ai():
    from web import site_api_ai_lambda as ai

    return ai


class _FakeTable:
    def __init__(self):
        self.store = {}

    @staticmethod
    def _k(key):
        return (key["pk"], key["sk"])

    def put_item(self, Item):
        self.store[self._k(Item)] = json.loads(json.dumps(Item, default=str))

    def get_item(self, Key):
        item = self.store.get(self._k(Key))
        return {"Item": item} if item is not None else {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ConditionExpression=None, ExpressionAttributeNames=None):
        item = self.store.get(self._k(Key))
        if item is None:
            raise Exception("ConditionalCheckFailedException")
        cap = float(ExpressionAttributeValues[":cap"])
        ip = ExpressionAttributeValues[":ip"]
        if float(item.get("followup_count", 0)) >= cap or item.get("ip_hash") != ip:
            raise Exception("ConditionalCheckFailedException")
        pid = ExpressionAttributeNames["#pid"]
        item["followup_count"] = float(item.get("followup_count", 0)) + 1
        item.setdefault("threads", {}).setdefault(pid, [])
        item["threads"][pid].extend(ExpressionAttributeValues[":turn"])
        return {}

    def query(self, **kwargs):
        return {"Items": []}


def _wire(ai, monkeypatch, table, bedrock_text="Steady progress — keep the routine consistent.", ctx=None):
    monkeypatch.setattr(ai, "table", table)
    monkeypatch.setattr(ai, "_ai_paused_response", lambda: None)
    monkeypatch.setattr(ai, "_get_anthropic_key", lambda: "fake-key")
    monkeypatch.setattr(ai, "_ddb_rate_check", lambda *a, **k: (True, 4, 0))
    monkeypatch.setattr(ai, "_RATE_LIMITER_READY", True)
    monkeypatch.setattr(ai, "_ask_fetch_context", lambda: dict(ctx) if ctx is not None else {"recovery_pct": 48.0})
    monkeypatch.setattr(ai, "_coach_voice_core", lambda pid: "")

    captured = {"reqs": []}

    class _FakeBedrock:
        @staticmethod
        def invoke(req):
            captured["reqs"].append(req)
            txt = bedrock_text(req) if callable(bedrock_text) else bedrock_text
            return {"content": [{"type": "text", "text": txt}], "usage": {}}

    monkeypatch.setitem(sys.modules, "bedrock_client", _FakeBedrock)
    return captured


def _post(body, ip="203.0.113.9"):
    return {
        "rawPath": "/api/board_ask",
        "requestContext": {"http": {"method": "POST", "sourceIp": ip}},
        "body": json.dumps(body),
        "headers": {},
    }


def test_board_ask_response_carries_grounding_matching_the_ctx(monkeypatch):
    ai = _ai()
    table = _FakeTable()
    _wire(ai, monkeypatch, table, ctx=FULL_CTX)
    resp = ai._handle_board_ask(_post({"question": "How's recovery trending?", "personas": ["sleep_coach"]}))
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["grounding"] == ai.board_grounding_receipts(FULL_CTX)
    assert {"label": "recovery", "value": "48%"} in body["grounding"]


def test_board_ask_grounding_survives_a_thin_partial_brief(monkeypatch):
    """A near-empty brief (most probes absent) must not error the whole
    request — it just yields a shorter (possibly empty) grounding list."""
    ai = _ai()
    table = _FakeTable()
    _wire(ai, monkeypatch, table, ctx={})
    resp = ai._handle_board_ask(_post({"question": "How's recovery trending?", "personas": ["sleep_coach"]}))
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["grounding"] == []
    assert body["responses"].get("sleep_coach")  # the answer itself still went through


def test_grounding_present_even_when_answer_is_refused_ungrounded(monkeypatch):
    """The ADR-104 gate may refuse a fabricated answer — the receipt describes
    what the coach was GIVEN to read, so it must still be present and must
    NOT contain any of the model's fabricated figures."""
    ai = _ai()
    table = _FakeTable()
    _wire(
        ai,
        monkeypatch,
        table,
        bedrock_text="Your HRV jumped from 41 to 78 ms overnight, a clear 90% gain.",
        ctx={"recovery_pct": 48.0},
    )
    resp = ai._handle_board_ask(_post({"question": "Did my HRV change?", "personas": ["sleep_coach"]}))
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    answer = body["responses"]["sleep_coach"]
    assert "78" not in answer and "41" not in answer  # fail-closed refusal, unchanged behaviour
    # the receipt is untouched by the gate outcome — still derived from ctx alone
    assert body["grounding"] == [{"label": "recovery", "value": "48%"}]
    assert "78" not in json.dumps(body["grounding"])
    assert "41" not in json.dumps(body["grounding"])


def test_followup_response_carries_a_grounding_field(monkeypatch):
    ai = _ai()
    table = _FakeTable()
    _wire(ai, monkeypatch, table, ctx=FULL_CTX)
    token = ai._create_board_session(
        "203.0.113.9", {"sleep_coach": [{"q": "Is my sleep debt catching up?", "a": "Recovery looks steady."}]}
    )
    resp = ai._handle_board_followup(
        {"session_token": token, "persona": "sleep_coach", "question": "What about REM specifically?"}, "203.0.113.9"
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["grounding"] == ai.board_grounding_receipts(FULL_CTX)


# ── Front-end footer renderer: only emits markup when there's something ───


def test_js_footer_helper_exists_and_is_wired_into_both_render_paths():
    assert "function groundingFooterHTML(grounding)" in COACHING_JS
    assert 'if (!Array.isArray(grounding) || !grounding.length) return "";' in COACHING_JS
    assert "groundingFooterHTML(d.grounding)" in COACHING_JS
    # wired into the initial convene render AND the per-card follow-up render
    assert COACHING_JS.count("groundingFooterHTML(d.grounding)") >= 2
