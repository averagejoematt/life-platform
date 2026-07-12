"""tests/test_board_quality_gate_968.py — #968: the ADR-108 coach quality gate
extends to the public board (the coach-voiced ask surface).

The daily brief enforces the gate regenerate-or-HOLD (`ai_calls._enforce_quality_gate`,
#390/ADR-108). The board is a synchronous reader-facing path, so its enforcement
(`web/board_quality_gate.enforce`, wired into both site_api_ai_lambda board
handlers) is evaluate-then-regenerate-once under a HARD TIME BUDGET and FAILS
OPEN — the reader always gets an answer; a fired verdict that can't be corrected
in budget is served with log + metric + eval retention.

Pinned here, mirroring tests/test_coach_quality_gate_390.py's fakes (no AWS):

  U1  no Lambda context (tests/local direct calls) → gate skipped entirely
  U2  insufficient remaining time → gate skipped (never evaluated)
  U3  passing verdict → answer unchanged, nothing retained
  U4  gate infra failure → fail-open (via ai_calls._invoke_quality_gate_sync)
  U5  fired verdict + budget → ONE corrective regen; grounded candidate served
  U6  fired verdict, regen candidate UNGROUNDED → original served (a voice fix
      must never smuggle in a fabricated number)
  U7  fired verdict, regen raises / returns empty → original served
  U8  fired verdict, no budget left for regen → original served, no regen call
  U9  fired verdicts emit the BoardQualityGateFired metric + retention pair
  W1  handler wiring: board_ask serves the corrected text and stores IT (not
      the flagged draft) in the coach's episodic memory + follow-up thread
  W2  handler wiring: follow-up path gates too
  W3  without a Lambda context the handlers behave exactly as before (the
      pre-#968 suite must stay green untouched)
  S1  scope posture (ADR-103 row): inter_coach_dialogue + coach_memoir are
      deliberately NOT wired to the quality gate; both board call sites are
"""

import json
import os
import sys
from unittest.mock import MagicMock

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AI_SRC = open(os.path.join(ROOT, "lambdas/web/site_api_ai_lambda.py")).read()
BQG_SRC = open(os.path.join(ROOT, "lambdas/web/board_quality_gate.py")).read()
DIALOGUE_SRC = open(os.path.join(ROOT, "lambdas/coach/inter_coach_dialogue_lambda.py")).read()
MEMOIR_SRC = open(os.path.join(ROOT, "lambdas/compute/coach_memoir_lambda.py")).read()


def _bqg():
    from web import board_quality_gate as bqg

    return bqg


def _ai():
    from web import site_api_ai_lambda as ai

    return ai


class _FakeContext:
    """get_remaining_time_in_millis returns the values in order, then repeats
    the last one — lets a test drain the budget between gate steps."""

    def __init__(self, *remaining):
        self._vals = list(remaining)

    def get_remaining_time_in_millis(self):
        return self._vals.pop(0) if len(self._vals) > 1 else self._vals[0]


def _gate_client_returning(*reports):
    """Fake boto3 lambda client, one coach-quality-gate report per invoke —
    same shape as tests/test_coach_quality_gate_390._lambda_client_returning."""
    client = MagicMock()
    iterator = iter(reports)

    def _invoke(**kwargs):
        assert kwargs["FunctionName"] == "coach-quality-gate"
        assert kwargs["InvocationType"] == "RequestResponse"
        payload_mock = MagicMock()
        payload_mock.read.return_value = json.dumps(next(iterator)).encode()
        return {"Payload": payload_mock}

    client.invoke.side_effect = _invoke
    return client


_FIRED = {
    "statusCode": 200,
    "passed": False,
    "score": 62,
    "anti_pattern_violations": [{"phrase": "As an AI coach", "context": "opening"}],
    "suggestions": ["Vary your opening"],
}


def _arm(bqg, monkeypatch, context, client):
    """Point the gate module at a fake deadline + fake gate lambda + fake CW,
    and return the retention capture list."""
    retained = []
    monkeypatch.setattr(bqg, "_LAMBDA_CONTEXT", context)
    monkeypatch.setattr(bqg, "_qg_lambda_client", lambda: client)
    monkeypatch.setattr(bqg, "_cw_client", lambda: MagicMock())
    return retained, (lambda *a, **k: retained.append((a, k)))


# ── U: the fail-open regenerate-once state machine ───────────────────────────


def test_no_lambda_context_skips_the_gate_entirely(monkeypatch):
    bqg = _bqg()
    client = _gate_client_returning()  # any invoke would StopIteration
    _, retain = _arm(bqg, monkeypatch, None, client)
    out = bqg.enforce("sleep_coach", "answer", lambda n: "regen", lambda t: True, retain)
    assert out == "answer"
    assert client.invoke.call_count == 0


def test_insufficient_budget_skips_the_gate(monkeypatch):
    bqg = _bqg()
    client = _gate_client_returning()
    _, retain = _arm(bqg, monkeypatch, _FakeContext(bqg.QG_EVAL_MIN_REMAINING_MS - 1), client)
    out = bqg.enforce("sleep_coach", "answer", lambda n: "regen", lambda t: True, retain)
    assert out == "answer"
    assert client.invoke.call_count == 0


def test_passing_verdict_serves_the_answer_untouched(monkeypatch):
    bqg = _bqg()
    retained, retain = _arm(
        bqg, monkeypatch, _FakeContext(29_000), _gate_client_returning({"statusCode": 200, "passed": True, "score": 92})
    )
    out = bqg.enforce("sleep_coach", "answer", lambda n: "regen", lambda t: True, retain)
    assert out == "answer"
    assert retained == []


def test_gate_infra_failure_fails_open(monkeypatch):
    bqg = _bqg()
    client = MagicMock()
    client.invoke.side_effect = RuntimeError("Lambda unreachable")
    retained, retain = _arm(bqg, monkeypatch, _FakeContext(29_000), client)
    out = bqg.enforce("sleep_coach", "answer", lambda n: "regen", lambda t: True, retain)
    assert out == "answer"  # ai_calls._invoke_quality_gate_sync fails open
    assert retained == []


def test_fired_verdict_regenerates_once_and_serves_the_grounded_candidate(monkeypatch):
    bqg = _bqg()
    retained, retain = _arm(bqg, monkeypatch, _FakeContext(29_000), _gate_client_returning(_FIRED))
    notes = []

    def _regen(note):
        notes.append(note)
        return "a corrected, on-voice answer"

    out = bqg.enforce("sleep_coach", "the flagged draft", _regen, lambda t: True, retain)
    assert out == "a corrected, on-voice answer"
    assert len(notes) == 1
    assert "As an AI coach" in notes[0]  # the correction note carries the finding
    ((args, kwargs),) = [retained[0]]
    assert args[1] == "flagged_corrected"
    assert args[2] == "the flagged draft" and args[3] == "a corrected, on-voice answer"
    assert kwargs["extra"]["gate"] == "adr108_quality"


def test_ungrounded_regen_candidate_is_rejected_and_original_served(monkeypatch):
    """A voice correction must never smuggle in a fabricated number — the
    candidate re-runs the ADR-104 grounding check and loses if it fails."""
    bqg = _bqg()
    retained, retain = _arm(bqg, monkeypatch, _FakeContext(29_000), _gate_client_returning(_FIRED))
    out = bqg.enforce("sleep_coach", "the flagged draft", lambda n: "HRV jumped 41 to 78", lambda t: False, retain)
    assert out == "the flagged draft"
    assert retained[0][0][1] == "flagged_kept"


def test_regen_exception_and_empty_regen_serve_the_original(monkeypatch):
    bqg = _bqg()
    retained, retain = _arm(bqg, monkeypatch, _FakeContext(29_000), _gate_client_returning(_FIRED, _FIRED))

    def _boom(note):
        raise RuntimeError("bedrock hiccup")

    assert bqg.enforce("sleep_coach", "draft", _boom, lambda t: True, retain) == "draft"
    assert bqg.enforce("sleep_coach", "draft", lambda n: "   ", lambda t: True, retain) == "draft"
    assert [r[0][1] for r in retained] == ["flagged_kept", "flagged_kept"]


def test_budget_drained_after_evaluation_skips_the_regen(monkeypatch):
    """Evaluate consumed the slack: the second budget check (< regen floor)
    must serve the original WITHOUT a regeneration call."""
    bqg = _bqg()
    ctx = _FakeContext(bqg.QG_EVAL_MIN_REMAINING_MS, bqg.QG_REGEN_MIN_REMAINING_MS - 1)
    retained, retain = _arm(bqg, monkeypatch, ctx, _gate_client_returning(_FIRED))
    regen_calls = []
    out = bqg.enforce("sleep_coach", "draft", lambda n: regen_calls.append(n) or "regen", lambda t: True, retain)
    assert out == "draft"
    assert regen_calls == []
    assert retained[0][0][1] == "flagged_kept"


def test_fired_verdict_emits_the_cloudwatch_metric(monkeypatch):
    bqg = _bqg()
    cw = MagicMock()
    monkeypatch.setattr(bqg, "_LAMBDA_CONTEXT", _FakeContext(29_000))
    monkeypatch.setattr(bqg, "_qg_lambda_client", lambda: _gate_client_returning(_FIRED))
    monkeypatch.setattr(bqg, "_cw_client", lambda: cw)
    bqg.enforce("labs_coach", "draft", lambda n: "fixed", lambda t: True, lambda *a, **k: None)
    (call,) = cw.put_metric_data.call_args_list
    metric = call.kwargs["MetricData"][0]
    assert metric["MetricName"] == "BoardQualityGateFired"
    assert {"Name": "CoachID", "Value": "labs_coach"} in metric["Dimensions"]


# ── W: handler wiring (same fake harness as tests/test_board_ask_grounding.py) ──


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


FLAGGED_TEXT = "As an AI coach, recovery looks steady to me."
CORRECTED_TEXT = "Recovery looks steady from where I sit — hold the routine."


def _wire(ai, monkeypatch, table):
    monkeypatch.setattr(ai, "table", table)
    monkeypatch.setattr(ai, "_ai_paused_response", lambda: None)
    monkeypatch.setattr(ai, "_get_anthropic_key", lambda: "fake-key")
    monkeypatch.setattr(ai, "_ddb_rate_check", lambda *a, **k: (True, 4, 0))
    monkeypatch.setattr(ai, "_RATE_LIMITER_READY", True)
    monkeypatch.setattr(ai, "_ask_fetch_context", lambda: {"recovery_pct": 48.0})
    monkeypatch.setattr(ai, "_coach_voice_core", lambda pid: "")
    monkeypatch.setattr(ai, "_cw", MagicMock())

    class _FakeBedrock:
        @staticmethod
        def invoke(req):
            last = req["messages"][-1]["content"]
            txt = CORRECTED_TEXT if "QUALITY GATE FEEDBACK" in last else FLAGGED_TEXT
            return {"content": [{"type": "text", "text": txt}], "usage": {}}

    monkeypatch.setitem(sys.modules, "bedrock_client", _FakeBedrock)


def _post(body, ip="203.0.113.9"):
    return {
        "rawPath": "/api/board_ask",
        "requestContext": {"http": {"method": "POST", "sourceIp": ip}},
        "body": json.dumps(body),
        "headers": {},
    }


def test_board_ask_serves_and_remembers_the_corrected_text(monkeypatch):
    ai, bqg = _ai(), _bqg()
    table = _FakeTable()
    _wire(ai, monkeypatch, table)
    monkeypatch.setattr(bqg, "_LAMBDA_CONTEXT", _FakeContext(29_000))
    monkeypatch.setattr(bqg, "_qg_lambda_client", lambda: _gate_client_returning(_FIRED))
    monkeypatch.setattr(bqg, "_cw_client", lambda: MagicMock())
    monkeypatch.setattr(ai, "_retain_board_flag", lambda *a, **k: None)

    resp = ai._handle_board_ask(_post({"question": "How is recovery trending?", "personas": ["sleep_coach"]}))
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["responses"]["sleep_coach"] == CORRECTED_TEXT

    # The gated text — not the flagged draft — is what entered the coach's own
    # episodic memory and the follow-up thread seed.
    interactions = [v for (pk, sk), v in table.store.items() if pk == "COACH#sleep_coach" and sk.startswith("INTERACTION#")]
    assert len(interactions) == 1 and interactions[0]["answer"] == CORRECTED_TEXT
    sessions = [v for (pk, sk), v in table.store.items() if pk.startswith("BOARDSESS#")]
    assert sessions and sessions[0]["threads"]["sleep_coach"][0]["a"] == CORRECTED_TEXT


def test_board_followup_gates_the_turn_too(monkeypatch):
    ai, bqg = _ai(), _bqg()
    table = _FakeTable()
    _wire(ai, monkeypatch, table)
    monkeypatch.setattr(bqg, "_LAMBDA_CONTEXT", _FakeContext(29_000))
    monkeypatch.setattr(bqg, "_qg_lambda_client", lambda: _gate_client_returning(_FIRED))
    monkeypatch.setattr(bqg, "_cw_client", lambda: MagicMock())
    monkeypatch.setattr(ai, "_retain_board_flag", lambda *a, **k: None)

    token = ai._create_board_session("203.0.113.9", {"sleep_coach": [{"q": "Opening question?", "a": "Recovery looks steady."}]})
    resp = ai._handle_board_followup(
        {"session_token": token, "persona": "sleep_coach", "question": "And what about consistency?"}, "203.0.113.9"
    )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["response"] == CORRECTED_TEXT


def test_handlers_unchanged_without_a_lambda_context(monkeypatch):
    """Direct handler calls (the whole pre-#968 suite) carry no context — the
    gate must not evaluate, and the answer must flow exactly as before."""
    ai, bqg = _ai(), _bqg()
    table = _FakeTable()
    _wire(ai, monkeypatch, table)
    monkeypatch.setattr(bqg, "_LAMBDA_CONTEXT", None)
    client = _gate_client_returning()  # any invoke would StopIteration
    monkeypatch.setattr(bqg, "_qg_lambda_client", lambda: client)

    resp = ai._handle_board_ask(_post({"question": "How is recovery trending?", "personas": ["sleep_coach"]}))
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["responses"]["sleep_coach"] == FLAGGED_TEXT
    assert client.invoke.call_count == 0


# ── S1: the recorded scope posture (ADR-103 row / ADR-108 note, #968) ────────


def test_scope_posture_board_gated_dialogue_and_memoir_deliberately_not():
    # Both coach-voiced board call sites run the gate…
    assert AI_SRC.count("_bqg.enforce(") == 2  # initial ask + follow-up
    assert 'endpoint="board_followup"' in AI_SRC
    assert "set_lambda_context(context)" in AI_SRC  # the deadline is captured per-invocation
    # …the budget/deadline machinery exists…
    assert "get_remaining_time_in_millis" in BQG_SRC
    # …and the deliberately-out-of-scope surfaces stay grounding-only (ADR-103
    # ledger row dated 2026-07-11; re-open only with a measured failure rate).
    for src in (DIALOGUE_SRC, MEMOIR_SRC):
        assert "board_quality_gate" not in src
        assert "coach-quality-gate" not in src
        assert "_enforce_quality_gate" not in src


def test_decisions_md_records_the_scope_extension():
    decisions = open(os.path.join(ROOT, "docs/DECISIONS.md")).read()
    assert "Scope extension (2026-07-11, #968)" in decisions
    assert "ADR-108 coach quality gate — scope (#968)" in decisions
