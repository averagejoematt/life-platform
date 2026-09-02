"""#3419 — the board persona pass runs in PARALLEL, side effects stay on the main thread.

Sequentially, ~5s/persona meant every panel size the rate arithmetic allows was
undeliverable in wall time (live probe 2026-09-02: a 5-persona panel hit the
Lambda's own 30s ceiling, Status: timeout, the 5th persona never reached). The
fix fans the Bedrock generation out across worker threads while keeping every
other boto3 touch (DDB context reads, metrics, retention, episodic write-back,
the #3414 observer) on the main thread — boto3 resources are not thread-safe.

These tests assert the STRUCTURE the fix promises:
  * a full 7-coach panel answers completely, generation spread over >1 thread
  * per-persona side effects (episodic write-back) run on the MAIN thread only
  * one failing persona degrades to its "[name] temporarily unavailable]" stub
    without touching the other six answers

Run:  python3 -m pytest tests/test_board_ask_parallel_3419.py -v
"""

import json
import os
import sys
import threading

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

IP = "203.0.113.9"
ANSWER = "Keep the room cool and hold the earlier bedtime steady."


def _ai():
    from web import site_api_ai_lambda as ai

    return ai


def _post(body):
    return {
        "rawPath": "/api/board_ask",
        "requestContext": {"http": {"method": "POST", "sourceIp": IP}},
        "headers": {"CloudFront-Viewer-Address": f"{IP}:16225"},
        "body": json.dumps(body),
    }


def _wire_stubs(ai, monkeypatch, invoke_stub, writes=None):
    """Stub every non-generation dependency so the test isolates the loop shape."""
    import ai.bedrock_client as bc

    monkeypatch.setattr(ai, "_ai_paused_response", lambda: None)
    monkeypatch.setattr(ai, "_RATE_LIMITER_READY", True)
    monkeypatch.setattr(ai, "_ddb_rate_check", lambda *a, **k: (True, 5, 0))
    monkeypatch.setattr(ai, "_get_anthropic_key", lambda: "fake-key")
    monkeypatch.setattr(ai, "_ask_question_safe", lambda q: (True, ""))
    monkeypatch.setattr(ai._req, "hazard_gate", lambda *a, **k: None)
    monkeypatch.setattr(ai, "_ask_fetch_context", lambda: {})
    monkeypatch.setattr(ai, "_board_facts_block", lambda ctx: "no data yet")
    monkeypatch.setattr(ai, "board_grounding_receipts", lambda ctx: [])
    monkeypatch.setattr(ai, "_phase_context_block", lambda: "PHASE: test")
    monkeypatch.setattr(ai, "_coach_stance_bits", lambda pid: "")
    monkeypatch.setattr(ai, "_coach_memory_bits", lambda pid: "")
    monkeypatch.setattr(ai, "_coach_recent_interactions", lambda pid: "")
    monkeypatch.setattr(ai, "_coach_system", lambda pid: f"You are the coach voice for {pid}.")
    monkeypatch.setattr(ai, "board_grounding_findings", lambda *a, **k: [])
    monkeypatch.setattr(ai, "_emit_token_metrics", lambda usage, endpoint: None)
    monkeypatch.setattr(ai, "_retain_board_flag", lambda *a, **k: None)
    monkeypatch.setattr(ai, "_observe_board_verdict", lambda pid, text: None)
    monkeypatch.setattr(ai, "_create_board_session", lambda ip_hash, threads: None)
    if writes is not None:
        monkeypatch.setattr(ai, "_write_board_interaction", lambda pid, q, a, grounded: writes.append((pid, threading.get_ident())))
    else:
        monkeypatch.setattr(ai, "_write_board_interaction", lambda *a, **k: None)
    monkeypatch.setattr(bc, "invoke", invoke_stub)


def test_full_board_answers_all_seven_across_threads(monkeypatch):
    ai = _ai()
    idents = []
    writes = []

    def _invoke(body, model_name=None):
        idents.append(threading.get_ident())
        import time

        time.sleep(0.05)  # give the pool a window to actually overlap workers
        return {"content": [{"type": "text", "text": ANSWER}], "usage": {"input_tokens": 10, "output_tokens": 20}}

    _wire_stubs(ai, monkeypatch, _invoke, writes=writes)
    roster = list(ai.COACH_ROSTER)
    assert len(roster) == 7, f"roster drifted to {len(roster)} — re-derive this test's premise"
    res = ai._handle_board_ask(_post({"question": "what single change would most improve recovery?", "personas": roster}))
    assert res["statusCode"] == 200, res
    body = json.loads(res["body"])
    assert sorted(body["responses"]) == sorted(roster), "every convened coach must answer"
    assert all(v == ANSWER for v in body["responses"].values()), body["responses"]
    assert len(set(idents)) > 1, "generation must be spread across worker threads, not serialized"
    # boto3 side effects stay on the MAIN thread — the #3419 division of labor
    main = threading.get_ident()
    assert [w[1] for w in writes] == [main] * 7, "episodic write-back must run on the main thread only"
    assert [w[0] for w in writes] == roster, "write-back must preserve request order"


def test_one_failing_persona_degrades_only_itself(monkeypatch):
    ai = _ai()

    def _invoke(body, model_name=None):
        sys_txt = body["system"][0]["text"]
        if "physical_coach" in sys_txt:
            raise RuntimeError("bedrock transient")
        return {"content": [{"type": "text", "text": ANSWER}], "usage": {}}

    _wire_stubs(ai, monkeypatch, _invoke)
    roster = list(ai.COACH_ROSTER)
    res = ai._handle_board_ask(_post({"question": "how is the sleep trending this week?", "personas": roster}))
    assert res["statusCode"] == 200
    body = json.loads(res["body"])
    unavailable = f"[{ai.COACH_ROSTER['physical_coach']['name']} is temporarily unavailable]"
    assert body["responses"]["physical_coach"] == unavailable
    others = [pid for pid in roster if pid != "physical_coach"]
    assert all(body["responses"][pid] == ANSWER for pid in others), "one failure must not touch the other answers"
