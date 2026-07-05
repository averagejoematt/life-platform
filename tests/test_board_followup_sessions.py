"""#546 — /api/board_ask short-lived server-side follow-up sessions.

Pins the contract for the follow-up thread mechanism:
  • a board_ask response mints an OPAQUE, unguessable session token (no PII);
  • the session record carries a DDB TTL ≤ 1h and no PII (only an IP hash);
  • a follow-up with a valid token routes to the SAME coach with the prior
    turns replayed as context (the "as I told you earlier" capability);
  • the ≤3-follow-up cap is enforced BEFORE any model spend;
  • an expired session is unresumable (defensive in-code TTL check);
  • the session is bound to its originating IP (a leaked token can't roam);
  • per-IP rate limiting still gates the follow-up path;
  • the per-turn grounded gate stays FAIL-CLOSED (an ungrounded follow-up is
    refused in voice, never served with a fabricated number).

Behavioural — the handlers are driven with a fake in-memory DDB table and a
fake Bedrock so no AWS calls are made.
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))


def _ai():
    from web import site_api_ai_lambda as ai

    return ai


class _FakeTable:
    """Minimal single-table stand-in: enough of put/get/update/query for the
    session + episodic-write paths the follow-up handler exercises."""

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
        if item is None:  # attribute_exists(pk) fails
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


def _wire(ai, monkeypatch, table, bedrock_text="Steady progress — keep the routine consistent."):
    """Stub out every external dependency so the handlers run offline."""
    monkeypatch.setattr(ai, "table", table)
    monkeypatch.setattr(ai, "_ai_paused_response", lambda: None)
    monkeypatch.setattr(ai, "_get_anthropic_key", lambda: "fake-key")
    monkeypatch.setattr(ai, "_ddb_rate_check", lambda *a, **k: (True, 4, 0))
    monkeypatch.setattr(ai, "_RATE_LIMITER_READY", True)
    monkeypatch.setattr(ai, "_ask_fetch_context", lambda: {"recovery_pct": 64.0})
    monkeypatch.setattr(ai, "_coach_voice_core", lambda pid: "")  # no S3
    captured = {"reqs": []}

    class _FakeBedrock:
        @staticmethod
        def invoke(req):
            captured["reqs"].append(req)
            txt = bedrock_text(req) if callable(bedrock_text) else bedrock_text
            return {"content": [{"type": "text", "text": txt}], "usage": {}}

    monkeypatch.setitem(sys.modules, "bedrock_client", _FakeBedrock)
    return captured


def _post(body, ip="203.0.113.7"):
    return {
        "rawPath": "/api/board_ask",
        "requestContext": {"http": {"method": "POST", "sourceIp": ip}},
        "body": json.dumps(body),
        "headers": {},
    }


# ── Session token: opaque, no PII ─────────────────────────────────────────


def test_create_session_returns_opaque_token_no_pii():
    ai = _ai()
    table = _FakeTable()
    ai_table_backup = ai.table
    ai.table = table
    try:
        token = ai._create_board_session("iphash-abc", {"sleep_coach": [{"q": "hi there", "a": "hello back"}]})
    finally:
        ai.table = ai_table_backup
    # opaque + unguessable shape (url-safe, not sequential, no PII embedded)
    assert token and ai._SESSION_TOKEN_RE.match(token)
    assert re.match(r"^[A-Za-z0-9_-]{16,64}$", token)
    item = table.store[(f"BOARDSESS#{token}", "SESSION")]
    # NO PII: only an ip hash, the transcript, a counter, and a TTL
    assert item["ip_hash"] == "iphash-abc"
    assert "email" not in item and "sourceIp" not in json.dumps(item)


def test_ttl_is_set_within_one_hour():
    ai = _ai()
    table = _FakeTable()
    before = int(time.time())
    ai_table_backup = ai.table
    ai.table = table
    try:
        token = ai._create_board_session("iphash-ttl", {"sleep_coach": [{"q": "hi there", "a": "hello back"}]})
    finally:
        ai.table = ai_table_backup
    item = table.store[(f"BOARDSESS#{token}", "SESSION")]
    ttl = int(float(item["ttl"]))
    assert before < ttl <= before + ai.SESSION_TTL_SECONDS + 2
    assert ai.SESSION_TTL_SECONDS <= 3600  # acceptance ceiling


def test_board_ask_response_carries_a_session_token(monkeypatch):
    ai = _ai()
    table = _FakeTable()
    _wire(ai, monkeypatch, table)
    resp = ai._handle_board_ask(_post({"question": "How is recovery trending?", "personas": ["sleep_coach"]}))
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "responses" in body and body["responses"].get("sleep_coach")
    token = body.get("session_token")
    assert token and ai._SESSION_TOKEN_RE.match(token)
    assert body["followups_remaining"] == ai.MAX_FOLLOWUPS
    # the session was persisted with the opening turn for that coach
    item = table.store[(f"BOARDSESS#{token}", "SESSION")]
    assert "sleep_coach" in item["threads"]


# ── Follow-up: same coach, prior context ──────────────────────────────────


def _seed_session(ai, table, ip="203.0.113.7", persona="sleep_coach"):
    return ai._create_board_session(
        ip,
        {persona: [{"q": "Is my sleep debt catching up?", "a": "Your recovery looks steady; keep the window consistent."}]},
    )


def test_followup_routes_to_same_coach_with_prior_context(monkeypatch):
    ai = _ai()
    table = _FakeTable()
    cap = _wire(ai, monkeypatch, table, bedrock_text="As I said earlier, hold the routine steady and it should settle.")
    token = _seed_session(ai, table)
    resp = ai._handle_board_followup(
        {"session_token": token, "persona": "sleep_coach", "question": "What about REM specifically?"}, "203.0.113.7"
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["persona"] == "sleep_coach"
    assert body["session_token"] == token
    assert body["followups_remaining"] == ai.MAX_FOLLOWUPS - 1
    # the model saw the SAME coach's system prompt and the prior turn as context
    req = cap["reqs"][-1]
    sys_txt = req["system"][0]["text"]
    assert "Dr. Lisa Park" in sys_txt  # the sleep coach persona
    convo = json.dumps(req["messages"])
    assert "Is my sleep debt catching up?" in convo  # prior question replayed
    assert "keep the window consistent" in convo  # prior answer replayed
    assert "What about REM specifically?" in convo  # the new follow-up
    # the turn was appended + the counter bumped
    item = table.store[(f"BOARDSESS#{token}", "SESSION")]
    assert float(item["followup_count"]) == 1
    assert len(item["threads"]["sleep_coach"]) == 2


def test_followup_cap_enforced_before_spend(monkeypatch):
    ai = _ai()
    table = _FakeTable()
    cap = _wire(ai, monkeypatch, table)
    token = _seed_session(ai, table)
    # exhaust the cap
    item = table.store[(f"BOARDSESS#{token}", "SESSION")]
    item["followup_count"] = ai.MAX_FOLLOWUPS
    resp = ai._handle_board_followup({"session_token": token, "persona": "sleep_coach", "question": "One more thing?"}, "203.0.113.7")
    assert resp["statusCode"] == 429
    assert json.loads(resp["body"])["followups_remaining"] == 0
    assert cap["reqs"] == []  # NO model call once the cap is reached


def test_expired_session_is_unresumable(monkeypatch):
    ai = _ai()
    table = _FakeTable()
    _wire(ai, monkeypatch, table)
    token = _seed_session(ai, table)
    # force the record past its TTL (DDB deletion is lazy; the in-code check backstops it)
    table.store[(f"BOARDSESS#{token}", "SESSION")]["ttl"] = int(time.time()) - 10
    resp = ai._handle_board_followup({"session_token": token, "persona": "sleep_coach", "question": "Still there?"}, "203.0.113.7")
    assert resp["statusCode"] == 404


def test_followup_bound_to_originating_ip(monkeypatch):
    ai = _ai()
    table = _FakeTable()
    _wire(ai, monkeypatch, table)
    token = _seed_session(ai, table, ip="203.0.113.7")
    # a different client presenting a stolen token is refused
    resp = ai._handle_board_followup({"session_token": token, "persona": "sleep_coach", "question": "Give me the thread"}, "10.9.8.7")
    assert resp["statusCode"] == 403


def test_malformed_token_rejected_before_any_read(monkeypatch):
    ai = _ai()
    table = _FakeTable()
    cap = _wire(ai, monkeypatch, table)
    resp = ai._handle_board_followup(
        {"session_token": "../../etc/passwd", "persona": "sleep_coach", "question": "hello there"}, "203.0.113.7"
    )
    assert resp["statusCode"] == 400
    assert cap["reqs"] == []


def test_followup_rate_limited(monkeypatch):
    ai = _ai()
    table = _FakeTable()
    _wire(ai, monkeypatch, table)
    token = _seed_session(ai, table)
    # rate limiter says "no" — the whole board_ask entrypoint (incl. follow-ups) 429s
    monkeypatch.setattr(ai, "_ddb_rate_check", lambda *a, **k: (False, 0, 3600))
    resp = ai._handle_board_ask(_post({"session_token": token, "persona": "sleep_coach", "question": "one more please"}))
    assert resp["statusCode"] == 429


# ── Grounded gate stays fail-closed per turn ──────────────────────────────


def test_ungrounded_followup_is_refused_fail_closed(monkeypatch):
    ai = _ai()
    table = _FakeTable()
    # every model call fabricates a number absent from the grounding context —
    # both the first draft and the single correction retry stay ungrounded.
    _wire(ai, monkeypatch, table, bedrock_text="Your HRV jumped from 41 to 78 ms overnight, a clear 90% gain.")
    token = _seed_session(ai, table)
    resp = ai._handle_board_followup({"session_token": token, "persona": "sleep_coach", "question": "Did my HRV change?"}, "203.0.113.7")
    assert resp["statusCode"] == 200
    answer = json.loads(resp["body"])["response"]
    # fail-closed: the fabricated figures never reach the reader
    assert "78" not in answer and "41" not in answer
    assert "ground" in answer.lower()  # the honest in-voice refusal


def test_followup_through_board_ask_entrypoint(monkeypatch):
    """A session_token on the main /api/board_ask route dispatches to the
    follow-up path (the frontend posts to one endpoint)."""
    import hashlib

    ai = _ai()
    table = _FakeTable()
    _wire(ai, monkeypatch, table, bedrock_text="Holding steady is the right call here.")
    # the entrypoint hashes the source IP — seed the session with that hash so
    # the IP-binding check passes end-to-end.
    ip_hash = hashlib.sha256(b"203.0.113.7").hexdigest()[:16]
    token = _seed_session(ai, table, ip=ip_hash)
    resp = ai._handle_board_ask(_post({"session_token": token, "persona": "sleep_coach", "question": "and tomorrow?"}))
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["persona"] == "sleep_coach" and "response" in body
