"""tests/test_coach_quality_gate_fail_closed_3083.py — #3083: the ADR-108 gate
fails CLOSED when its own LLM judge cannot run (owner decision 2026-08-29).

Before this, `coach_quality_gate._build_fallback_report` returned `passed: True`,
so the BLOCKING gate green-lit drafts it never evaluated — 84 of 484 metered
calls (17.4%) over the 30 days to 2026-08-23 (#2893). The dominant trigger (the
gate's own 800-token cap) was removed by #3081 (post-fix rate 0/42) and
`LifePlatform/AI TruncatedResponses` guards its recurrence, which is what made
fail-closed cheap enough to choose.

These tests exercise the REAL wire, not a lookalike (fixture-must-be-the-wire):
the fake `lambda_client.invoke` runs the actual `coach_quality_gate.lambda_handler`
on the actual `quality_gate_event` payload, with only the AWS boundaries (S3
voice spec, DynamoDB history, the Haiku call, CloudWatch, retention) stubbed.
So the verdict travels handler -> Payload JSON -> `_invoke_quality_gate_sync`
-> `_enforce_quality_gate`, the exact production path.

Protect-longest is NOT re-pinned here: a hold surfaces as `CoachHold`, which
`daily_brief_lambda` treats as terminal for that one domain only
(tests/test_daily_brief_grounding_and_hold.py pins that a held domain never
darkens the rest of the brief, and test_pipeline_hold_points_return_coach_hold_sentinel
pins that the quality-gate hold returns the sentinel, not bare None).
"""

import io
import json
import os
import sys
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from ai import ai_calls  # noqa: E402
from coach import coach_quality_gate as gate  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# Boundary fakes — only the AWS edges, never the logic under test
# ──────────────────────────────────────────────────────────────────────────────


class _NoSuchKey(Exception):
    pass


class _FakeS3:
    exceptions = type("_E", (), {"NoSuchKey": _NoSuchKey})()

    def get_object(self, Bucket=None, Key=None, **kw):
        raise _NoSuchKey(Key)  # no voice spec in S3 — the gate falls back


class _FakeTable:
    def get_item(self, **kw):
        return {}

    def query(self, **kw):
        return {"Items": []}


@pytest.fixture
def wire(monkeypatch):
    """The production call path with a scripted judge.

    Returns a dict with:
      client        — a lambda_client whose .invoke() runs the REAL handler
      judge_calls   — one entry per Haiku attempt
      judge_results — script: exceptions are raised, dicts are returned, in order;
                      the last entry repeats once exhausted
      cw            — the CloudWatch put_metric_data mock on the caller side
      retain        — the retention mock on the caller side
    """
    monkeypatch.setattr(gate, "s3", _FakeS3())
    monkeypatch.setattr(gate, "table", _FakeTable())

    judge_calls = []
    judge_results = []

    def _scripted_haiku(system=None, user_message=None, **kw):
        judge_calls.append({"system": system, "user_message": user_message})
        step = judge_results[min(len(judge_calls), len(judge_results)) - 1]
        if isinstance(step, Exception):
            raise step
        return step

    monkeypatch.setattr(gate, "_call_haiku", _scripted_haiku)

    def _invoke(FunctionName=None, InvocationType=None, Payload=None):
        assert FunctionName == "coach-quality-gate"
        assert InvocationType == "RequestResponse"
        event = json.loads(Payload.decode())
        resp = gate.lambda_handler(event, None)
        return {"Payload": io.BytesIO(json.dumps(resp).encode())}

    client = MagicMock()
    client.invoke.side_effect = _invoke

    cw = MagicMock()
    monkeypatch.setattr(ai_calls._cw, "put_metric_data", cw)
    retain = MagicMock()
    monkeypatch.setattr(ai_calls, "_retain_coach_brief_flag", retain)

    return {"client": client, "judge_calls": judge_calls, "judge_results": judge_results, "cw": cw, "retain": retain}


# ──────────────────────────────────────────────────────────────────────────────
# The decision itself — an unjudgeable draft is held, never green-lit
# ──────────────────────────────────────────────────────────────────────────────


class TestJudgeDownHolds:
    def test_a_dead_judge_holds_the_draft_instead_of_passing_it(self, wire):
        """THE #3083 flip. Pre-fix, this exact path returned the draft with
        `passed: True` — the blocking gate green-lighting a draft it never
        evaluated. Now: regenerate once (the judge gets a second chance on a
        fresh draft), and hold when that attempt cannot be judged either."""
        wire["judge_results"][:] = [RuntimeError("bedrock 500"), RuntimeError("bedrock 500")]
        regenerate_fn = MagicMock(return_value="a fresh draft")

        output, report = ai_calls._enforce_quality_gate(wire["client"], "sleep_coach", "the draft", {}, regenerate_fn)

        assert output is None, "an unjudged draft must be HELD, not published (#3083)"
        assert report["passed"] is False
        assert report["_fallback"] is True
        regenerate_fn.assert_called_once()  # regenerate FIRST — hold is the last resort
        assert len(wire["judge_calls"]) == 2  # the judge was retried on the fresh draft

    def test_the_hold_is_reported_like_any_other_hold(self, wire):
        """The hold rides the existing machinery: CoachQualityGateHeld metric +
        retention — no parallel bookkeeping path (ADR-108's one-state-machine rule)."""
        wire["judge_results"][:] = [RuntimeError("down"), RuntimeError("down")]
        output, _ = ai_calls._enforce_quality_gate(wire["client"], "sleep_coach", "the draft", {}, lambda note: "fresh")
        assert output is None
        wire["cw"].assert_called_once()
        assert wire["cw"].call_args[1]["MetricData"][0]["MetricName"] == "CoachQualityGateHeld"
        wire["retain"].assert_called_once()
        assert wire["retain"].call_args[0][1] == "flagged_dropped"

    def test_a_transient_judge_failure_publishes_after_a_clean_reverdict(self, wire):
        """Fail-closed must not mean fragile: when the judge recovers on the
        regenerated draft, the clean verdict publishes — the hold only fires
        when the draft stays unjudgeable (or keeps failing) through the cap."""
        wire["judge_results"][:] = [RuntimeError("blip"), {"passed": True, "score": 88}]
        output, report = ai_calls._enforce_quality_gate(wire["client"], "sleep_coach", "the draft", {}, lambda note: "fresh draft")
        assert output == "fresh draft"
        assert report["passed"] is True
        assert "_fallback" not in report

    def test_the_fallback_report_names_the_infrastructure_failure(self, wire):
        """Honest reason, not a silent verdict: the report says WHY it could not
        judge, in a dedicated `reason` field (the #1927 dark-gate lesson)."""
        wire["judge_results"][:] = [RuntimeError("bedrock timeout"), RuntimeError("bedrock timeout")]
        _, report = ai_calls._enforce_quality_gate(wire["client"], "sleep_coach", "the draft", {}, lambda note: "fresh")
        assert "bedrock timeout" in report.get("reason", "")
        assert "fail-closed" in report["reason"]

    def test_an_unparseable_judge_reply_is_the_same_unjudged_class(self, wire):
        """The non-dict path (#2893's actual trigger: a truncated reply that will
        not parse as JSON) holds exactly like a raised exception does."""
        wire["judge_results"][:] = ["I think this draft looks fi", "ne, mostly"]
        output, report = ai_calls._enforce_quality_gate(wire["client"], "sleep_coach", "the draft", {}, lambda note: "fresh")
        assert output is None
        assert report["passed"] is False
        assert report["_fallback"] is True


class TestTheBoundaryDidNotMove:
    def test_a_transport_level_invoke_failure_still_fails_open(self, wire):
        """#3083 flips the judge-failure class ONLY. A gate Lambda that never
        responded made no judgment, so the transport fail-open (N-06) stands —
        pinned here so the two postures cannot be conflated."""
        client = MagicMock()
        client.invoke.side_effect = RuntimeError("Lambda unreachable")
        regenerate_fn = MagicMock(side_effect=AssertionError("must not regenerate on a transport fail-open"))
        output, report = ai_calls._enforce_quality_gate(client, "sleep_coach", "the draft", {}, regenerate_fn)
        assert output == "the draft"
        assert report["passed"] is True
        assert report["_fail_open"] is True
