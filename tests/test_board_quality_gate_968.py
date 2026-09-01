"""tests/test_board_quality_gate_968.py — the ADR-108 coach quality gate and
the public board: why it is NOT on the reader path (#3413), and the #1973
cycle-boundary rule that still is.

HISTORY. #968 wired `web/board_quality_gate.enforce` into both board handlers:
the coach-quality-gate lambda invoked SYNCHRONOUSLY while a reader waited,
evaluate-then-regenerate-once under a hard time budget, fail-open. #3413
removed it, because it never once produced a verdict and was the direct cause
of /api/board_ask serving 504s on 2026-09-01 (launch day). The measurement and
the reasoning live in `lambdas/web/board_quality_gate.py`'s docstring; the
headline is that the callee's measured p50 (16371ms) was above the caller's
whole 14s evaluate budget, and 7 days of live traffic produced 8 attempts and
0 verdicts.

What this file pins now:

  G1  the board reader path performs NO synchronous cross-Lambda invoke — the
      #3413 class cannot be reintroduced silently
  G2  no client-side invoke cap survives on that path, and any future one must
      be justified against MEASURED callee latency (the assumed "≈2-5s" comment
      that sized the old cap is gone)
  G3  the module retains no I/O machinery at all — it is a pure rule module now
  G4  the removal is recorded where a reader will find it, with its measurement
  W1  board_ask serves the grounded answer and makes zero gate invokes
  S1  scope posture: dialogue + memoir stay deliberately ungated (ADR-103 row)
  #1973 the Day<=3 cycle-boundary rule, direct and through the ONE enforcement
      path that remains (`ai_calls._invoke_quality_gate_sync`, which merges it
      into the same report the daily brief acts on — so the rule still covers
      both coach-voiced surfaces from a single definition)

Fabrication protection is not tested here and never was this gate's job: that
is the ADR-104 grounding gate (tests/test_board_ask_grounding.py).
"""

import json
import os
import sys
from unittest.mock import MagicMock

from bundle_stubs import stub_bundled_module

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


AI_CALLS_SRC = open(os.path.join(ROOT, "lambdas/ai/ai_calls.py")).read()


def _bqg():
    from web import board_quality_gate as bqg

    return bqg


def _ai():
    from web import site_api_ai_lambda as ai

    return ai


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


# ── G: the #3413 guard — this class must not come back silently ──────────────
#
# The defect was not "a timeout was tuned wrong". It was a client-side cap
# (10s) written from an ASSUMED callee cost ("gate ≈2-5s", a comment) that sat
# below the callee's real p50 (16.4s) — so the gate could not return at its
# TYPICAL speed, burned the budget, and the result was discarded every time.
# The guard is therefore structural rather than numeric: no synchronous
# cross-Lambda invoke belongs on this reader path at all. A numeric
# cap-vs-p99 assertion was considered and rejected — it would need live
# CloudWatch in CI, and it would still pass while the cap quietly did nothing.


def _code_without_comments(src: str) -> str:
    """Source with COMMENT tokens removed, string literals KEPT.

    The guards below must judge what the module DOES, not what it says about
    itself — the #3413 record in site_api_ai_lambda.py necessarily names the
    gate it removed, and a bare substring match over raw source would read that
    explanation as the offence. String literals stay in scope on purpose: a
    function name reaching the wire is a literal, not a comment.

    Comments are BLANKED IN PLACE rather than dropped, so every other byte keeps
    its original position — a multi-token needle like `_bqg.enforce(` still
    matches. (Rebuilding the source by joining token strings looks equivalent
    and is not: it separates `_bqg` `.` `enforce` `(`, and every multi-token
    assertion below silently stops matching anything. That mistake was made
    here first and caught by the mutation proof in the next test.)
    """
    import io
    import tokenize

    lines = src.splitlines(keepends=True)
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            (r, c0), (_, c1) = tok.start, tok.end
            line = lines[r - 1]
            lines[r - 1] = line[:c0] + " " * (c1 - c0) + line[c1:]
    return "".join(lines)


AI_CODE = _code_without_comments(AI_SRC)


def test_board_reader_path_makes_no_synchronous_cross_lambda_invoke():
    """G1. The reader lambda must not invoke another Lambda and wait for it.

    Mutation proof: restoring any of these to site_api_ai_lambda.py reds this
    test, which is exactly what should happen — the person doing it has to come
    back here and justify the latency against a measurement.
    """
    for banned in ("_bqg.enforce(", "board_quality_gate", "coach-quality-gate", "_invoke_quality_gate_sync", "RequestResponse"):
        assert banned not in AI_CODE, f"#3413: {banned!r} is back on the board reader path — measure the callee's p50 before you do this"


def test_the_guard_itself_sees_a_reintroduced_invoke():
    """G1's positive control. A guard that only ever passes is not a guard:
    prove the comment-stripping did not blind it to the real thing."""
    reintroduced = '_txt = _bqg.enforce(pid, _txt)  # noqa\nc.invoke(FunctionName="coach-quality-gate", InvocationType="RequestResponse")\n'
    code = _code_without_comments(reintroduced)
    # Every banned needle must be findable, INCLUDING the multi-token one —
    # this is the assertion that fails if the stripper reflows the source.
    for banned in ("_bqg.enforce(", "coach-quality-gate", "RequestResponse"):
        assert banned in code, f"the guard is blind to {banned!r} — it would pass while the invoke is live"
    # …while an explanation of the removal is correctly ignored.
    assert "coach-quality-gate" not in _code_without_comments("# we removed the coach-quality-gate invoke\n")


def test_no_client_side_invoke_cap_survives_on_the_board_path():
    """G2. The cap and the budget constants it was sized against are gone, and
    so is the assumed-latency comment that justified them."""
    for gone in ("QG_INVOKE_TIMEOUT_S", "QG_EVAL_MIN_REMAINING_MS", "QG_REGEN_MIN_REMAINING_MS"):
        assert gone not in BQG_SRC and gone not in AI_SRC
    # The assumed cost that sized the old cap survives only as history, next to
    # the measurement that refuted it — never again as a live justification.
    assert "2-5s" in BQG_SRC and "10434ms" in BQG_SRC
    assert "get_remaining_time_in_millis" not in AI_CODE


def test_the_gate_module_is_now_pure_with_no_io():
    """G3. No boto3, no clients, no invocation context — a rule module only.

    This is what makes G1 hard to undo by accident: there is no longer any
    machinery here for a call site to reach for.
    """
    assert "import boto3" not in BQG_SRC
    assert "def enforce(" not in BQG_SRC
    assert "put_metric_data" not in BQG_SRC
    bqg = _bqg()
    assert not hasattr(bqg, "enforce")
    assert not hasattr(bqg, "set_lambda_context")
    # …and the rule it still owns is intact and reachable.
    assert callable(bqg.cycle_boundary_violations)


def test_the_removal_carries_its_measurement():
    """G4. A future reader must be able to see this was MEASURED, not assumed —
    the failure mode that caused #3413 in the first place. Numbers and the
    command that produced them, in the module a maintainer opens first."""
    assert "p50=10434ms" in BQG_SRC and "p50=16371ms" in BQG_SRC  # both windows, incl. the weaker one
    assert "filter-log-events" in BQG_SRC  # the derivation, not just the result
    assert "0 verdicts" in BQG_SRC
    assert "#3414" in BQG_SRC  # the open question is named, not buried


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

    stub_bundled_module(monkeypatch, "ai.bedrock_client", _FakeBedrock)


def _post(body, ip="203.0.113.9"):
    return {
        "rawPath": "/api/board_ask",
        "requestContext": {"http": {"method": "POST", "sourceIp": ip}},
        "body": json.dumps(body),
        "headers": {},
    }


def test_board_ask_serves_the_grounded_answer_and_invokes_no_gate(monkeypatch):
    """W1. The reader gets the answer with no cross-Lambda call in the path.

    `_gate_client_returning()` yields nothing, so ANY invoke raises
    StopIteration — the assertion is that the count is zero, not that a fake
    absorbed the call."""
    ai = _ai()
    table = _FakeTable()
    _wire(ai, monkeypatch, table)
    client = _gate_client_returning()
    monkeypatch.setattr(ai, "_retain_board_flag", lambda *a, **k: None)

    resp = ai._handle_board_ask(_post({"question": "How is recovery trending?", "personas": ["sleep_coach"]}))
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["responses"]["sleep_coach"] == FLAGGED_TEXT
    assert client.invoke.call_count == 0

    # The served text is what entered episodic memory and the thread seed.
    interactions = [v for (pk, sk), v in table.store.items() if pk == "COACH#sleep_coach" and sk.startswith("INTERACTION#")]
    assert len(interactions) == 1 and interactions[0]["answer"] == FLAGGED_TEXT


def test_board_followup_also_serves_without_a_gate_invoke(monkeypatch):
    ai = _ai()
    table = _FakeTable()
    _wire(ai, monkeypatch, table)
    client = _gate_client_returning()
    monkeypatch.setattr(ai, "_retain_board_flag", lambda *a, **k: None)

    token = ai._create_board_session("203.0.113.9", {"sleep_coach": [{"q": "Opening question?", "a": "Recovery looks steady."}]})
    resp = ai._handle_board_followup(
        {"session_token": token, "persona": "sleep_coach", "question": "And what about consistency?"}, "203.0.113.9"
    )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["response"] == FLAGGED_TEXT
    assert client.invoke.call_count == 0


# ── S1: the recorded scope posture (ADR-103 row / ADR-108 note, #968) ────────


def test_scope_posture_board_ungated_dialogue_and_memoir_still_ungated():
    # #3413: the board reader path no longer runs the gate at all…
    assert AI_SRC.count("_bqg.enforce(") == 0
    assert "set_lambda_context" not in AI_SRC
    # …the deterministic #1973 rule is still merged from the one place that
    # covers BOTH coach-voiced surfaces…
    assert "from web.board_quality_gate import cycle_boundary_violations" in AI_CALLS_SRC
    # …and the deliberately-out-of-scope surfaces stay grounding-only (ADR-103
    # ledger row dated 2026-07-11; re-open only with a measured failure rate).
    for src in (DIALOGUE_SRC, MEMOIR_SRC):
        assert "board_quality_gate" not in src
        assert "coach-quality-gate" not in src
        assert "_enforce_quality_gate" not in src


def test_decisions_md_records_the_scope_withdrawal_and_its_measurement():
    """The scope change is only real if the record says so. #968's extension
    stays in the file as history — deleting it would hide that this was once
    decided the other way — but it must be marked retired, and the withdrawal
    must carry the measurement that justified it, not just the verdict."""
    decisions = open(os.path.join(ROOT, "docs/DECISIONS.md")).read()
    assert "Scope extension (2026-07-11, #968)" in decisions  # kept as history…
    assert "RETIRED 2026-09-01 by the #3413 amendment" in decisions  # …and marked
    assert "Amendment (2026-09-01, #3413)" in decisions
    assert "p50=10434ms" in decisions or "p50 10434ms" in decisions  # the number, not just the claim
    assert "0 verdicts" in decisions
    # The ADR-103 ledger row must name the narrowing too — a scope row that
    # still reads "two surfaces" is how the next reviewer re-extends it.
    assert "ADR-108 coach quality gate — scope (#968, narrowed #3413)" in decisions
    assert "unknown" in decisions.split("narrowed #3413")[1][:1200]  # the open question is stated


# ── #1973: Day<=3 cycle-boundary framing rule ────────────────────────────────
#
# Early-cycle narratives cited last cycle's graded calls in present tense with
# no framing (the live failure: "I called lunch wrong. I predicted it would be
# your structural weak point. That hasn't materialized" on a Day-1 read, while
# /api/predictions showed the new cycle's own decided count at zero). The
# fix is deterministic (regex, no LLM) — a prompt instruction alone can't
# guarantee structure — merged into the SAME `_invoke_quality_gate_sync`
# report both board_quality_gate.enforce and the daily-brief
# `ai_calls._enforce_quality_gate` already act on, so one rule definition
# covers both coach-voiced surfaces.

_UNFRAMED_GRADED_CALL = (
    "I called lunch wrong. I predicted it would be your structural weak point. " "That hasn't materialized, and I want to own it plainly."
)
_FRAMED_GRADED_CALL = (
    "Last cycle I called lunch wrong — I predicted it would be your structural weak point. "
    "That hasn't materialized yet in this new cycle, but we're only three days in."
)
_NO_GRADED_CALL = "Recovery looks steady this week — nothing dramatic to report."


def test_cycle_boundary_violations_flags_unframed_graded_call_on_day_one():
    bqg = _bqg()
    v = bqg.cycle_boundary_violations(_UNFRAMED_GRADED_CALL, day_n=1)
    assert len(v) == 1
    assert "Day 1" in v[0]["reason"]
    assert "called" in v[0]["excerpt"].lower()


def test_cycle_boundary_violations_clears_when_explicitly_framed():
    bqg = _bqg()
    assert bqg.cycle_boundary_violations(_FRAMED_GRADED_CALL, day_n=1) == []


def test_cycle_boundary_violations_scoped_to_days_one_through_three():
    bqg = _bqg()
    assert bqg.cycle_boundary_violations(_UNFRAMED_GRADED_CALL, day_n=3) != []
    assert bqg.cycle_boundary_violations(_UNFRAMED_GRADED_CALL, day_n=4) == []  # out of window
    assert bqg.cycle_boundary_violations(_UNFRAMED_GRADED_CALL, day_n=0) == []  # pre-genesis, out of scope


def test_cycle_boundary_violations_skips_when_day_n_is_unknowable(monkeypatch):
    """day_n=None means 'resolve the live default' (see the defaults test
    below) — the genuinely-unknowable case is the live helper itself
    returning None (e.g. a constants read failure), which must fail-soft to
    no violation rather than mis-arm on a bad day count."""
    bqg = _bqg()
    monkeypatch.setattr(bqg, "_day_n_today", lambda: None)
    assert bqg.cycle_boundary_violations(_UNFRAMED_GRADED_CALL) == []


def test_cycle_boundary_violations_never_fires_without_graded_call_language():
    """No false positive on an ordinary Day-1 draft with no prediction talk."""
    bqg = _bqg()
    assert bqg.cycle_boundary_violations(_NO_GRADED_CALL, day_n=1) == []


def test_cycle_boundary_violations_defaults_day_n_to_the_live_helper(monkeypatch):
    bqg = _bqg()
    monkeypatch.setattr(bqg, "_day_n_today", lambda: 2)
    assert bqg.cycle_boundary_violations(_UNFRAMED_GRADED_CALL) != []
    monkeypatch.setattr(bqg, "_day_n_today", lambda: 40)
    assert bqg.cycle_boundary_violations(_UNFRAMED_GRADED_CALL) == []


def test_day_n_today_uses_the_pacific_calendar_day_not_utc(monkeypatch):
    """#2812: `_day_n_today()` used `date.today()` (naive, Lambda TZ=UTC) via the
    `from datetime import date as _date` idiom that evaded the #2414 guard's
    alias-blind matcher. Pin an instant in the 17:00-24:00 PT window — genesis
    EVENING, still Day 1 in Pacific but already past midnight (tomorrow, Day 2)
    in UTC — the exact shape that mis-armed cycle_boundary_violations live."""
    bqg = _bqg()
    from datetime import datetime as _dt

    from common import pacific_time

    # 2026-08-17 20:30 PT (genesis day evening) == 2026-08-18 03:30 UTC.
    monkeypatch.setattr(pacific_time, "pacific_now", lambda: _dt(2026, 8, 17, 20, 30))
    monkeypatch.setattr("common.constants.EXPERIMENT_START_DATE", "2026-08-17")
    assert bqg._day_n_today() == 1  # Pacific "today" == genesis day, not UTC's Day 2


# ── #1973 through the ONE enforcement path that remains ──────────────────────
#
# These were `enforce()` integration proofs until #3413. They now run against
# `ai_calls._invoke_quality_gate_sync`, which is where the rule is merged into
# the gate report for BOTH surfaces — so the proof follows the rule to the
# path that still executes it (the daily brief), instead of dying with the
# board wrapper it happened to be written against.


def _sync_report(monkeypatch, coach_id, text, llm_report, day_n=1):
    from ai import ai_calls
    from web import board_quality_gate as bqg

    monkeypatch.setattr(bqg, "_day_n_today", lambda: day_n)
    return ai_calls._invoke_quality_gate_sync(_gate_client_returning(llm_report), coach_id, text, None)


_LLM_PASSES = {"statusCode": 200, "passed": True, "score": 95}


def test_the_rule_fails_a_report_the_llm_verdict_alone_passed(monkeypatch):
    """Integration proof: the LLM-scored verdict says passed=True with zero
    findings (the exact live-failure shape — nothing in the anti-pattern /
    decision-class / similarity checks catches this). The deterministic day<=3
    rule is what flips the report to failing, which is what drives the
    daily brief's regenerate-or-hold loop."""
    report = _sync_report(monkeypatch, "physical_coach", _UNFRAMED_GRADED_CALL, _LLM_PASSES)
    assert report["passed"] is False
    assert len(report["cycle_boundary_violations"]) == 1

    from ai.ai_calls import _quality_gate_correction_note

    note = _quality_gate_correction_note(report)
    assert "cycle" in note.lower()  # the correction note names the missing framing


def test_a_correctly_framed_call_leaves_the_passing_verdict_alone(monkeypatch):
    report = _sync_report(monkeypatch, "physical_coach", _FRAMED_GRADED_CALL, _LLM_PASSES)
    assert report["passed"] is True
    assert "cycle_boundary_violations" not in report


def test_regression_guard_without_the_rule_the_llm_pass_alone_lets_it_through(monkeypatch):
    """The negative control, kept from #1973: stub `cycle_boundary_violations`
    back to a no-op — i.e. simulate the gate as it stood BEFORE #1973 — and the
    identical Day-1 unframed draft, under the identical passing LLM verdict,
    sails through untouched. This assertion FAILS if the rule is removed."""
    from web import board_quality_gate as bqg

    monkeypatch.setattr(bqg, "cycle_boundary_violations", lambda *a, **k: [])
    report = _sync_report(monkeypatch, "physical_coach", _UNFRAMED_GRADED_CALL, _LLM_PASSES)
    assert report["passed"] is True  # unchanged — the pre-#1973 gate never saw a problem
    assert "cycle_boundary_violations" not in report
