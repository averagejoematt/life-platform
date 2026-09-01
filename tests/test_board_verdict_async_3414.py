"""tests/test_board_verdict_async_3414.py — #3414: the board's ADR-108 voice
verdict, captured CALLEE-side for async callers.

The board's #968 synchronous gate produced 0 verdicts in 7 days of live traffic
and was removed by #3413 — an async (Event) invoke returns nothing to its
caller, so the verdict must be captured where the gate always runs to
completion: inside `coach_quality_gate.lambda_handler` itself, behind the
explicit `emit_verdict` opt-in on the wire event.

What this file pins:

  A1  opt-in + passing verdict  → BoardQualityGateVerdict (Surface) +
      (Surface, Outcome=passed); NO Fired metric; NO retention
  A2  opt-in + failing verdict  → Outcome=failed + BoardQualityGateFired
      (CoachID, the #968 name finally with datapoints) + eval retention with
      the HONEST disposition "observed" (draft == final — nothing regenerated)
  A3  opt-in + fallback report  → Outcome=unjudged, never counted as a failure
      (ADR-104 honest absence: an unjudged draft is not a fidelity datapoint)
  A4  NO opt-in (the daily brief's event shape) → none of this machinery runs —
      the enforcement path is behaviourally byte-unchanged
  A5  the capture is fail-soft in BOTH halves: a dead CloudWatch or a dead
      retention import still returns the full statusCode-200 report
  A6  the report an async caller's verdict is computed from is the SAME report
      a synchronous caller would have received (capture observes, never forks)

The event is built by the real `quality_gate_event` builder (fixture-must-be-
the-wire) and runs the real `lambda_handler`, with only the AWS boundaries
(S3 voice spec, DynamoDB, the Haiku judge, CloudWatch, retention) stubbed —
same harness discipline as tests/test_coach_quality_gate_fail_closed_3083.py.
"""

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

from ai.quality_gate_contract import EMIT_VERDICT_KEY, quality_gate_event  # noqa: E402
from coach import coach_quality_gate as gate  # noqa: E402
from experiment import eval_retention  # noqa: E402


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
def rig(monkeypatch):
    """The real handler with scripted judge + mocked emission boundaries."""
    monkeypatch.setattr(gate, "s3", _FakeS3())
    monkeypatch.setattr(gate, "table", _FakeTable())

    judge_results = []

    def _scripted_haiku(system=None, user_message=None, **kw):
        step = judge_results[0]
        if isinstance(step, Exception):
            raise step
        return step

    monkeypatch.setattr(gate, "_call_haiku", _scripted_haiku)

    cw = MagicMock()
    monkeypatch.setattr(gate._cw, "put_metric_data", cw)
    retain = MagicMock(return_value=True)
    monkeypatch.setattr(eval_retention, "retain", retain)

    return {"judge_results": judge_results, "cw": cw, "retain": retain}


def _run(judge_verdict_or_exc, rig, emit=True, text="Recovery looks steady from where I sit."):
    rig["judge_results"][:] = [judge_verdict_or_exc]
    event = quality_gate_event("sleep_coach", text, None, generation_date="2026-06-15", emit_verdict="board_ask" if emit else None)
    return gate.lambda_handler(event, None)


def _board_metrics(cw):
    """All Board* metric data emitted across every put_metric_data call."""
    out = []
    for call in cw.call_args_list:
        for m in call.kwargs.get("MetricData", []):
            if m["MetricName"].startswith("BoardQualityGate"):
                out.append(m)
    return out


def _dims(m):
    return {d["Name"]: d["Value"] for d in m.get("Dimensions", [])}


# ── A1: a passing verdict lands as a datapoint, and only a datapoint ─────────


def test_a_passing_verdict_emits_the_denominator_and_the_passed_outcome(rig):
    resp = _run({"passed": True, "score": 91}, rig)
    assert resp["statusCode"] == 200 and resp["passed"] is True

    metrics = _board_metrics(rig["cw"])
    names = [(m["MetricName"], _dims(m)) for m in metrics]
    assert ("BoardQualityGateVerdict", {"Surface": "board_ask"}) in names
    assert ("BoardQualityGateVerdict", {"Surface": "board_ask", "Outcome": "passed"}) in names
    assert not any(m["MetricName"] == "BoardQualityGateFired" for m in metrics)
    rig["retain"].assert_not_called()  # clean passes need no second copy


# ── A2: a failing verdict is the measurement this whole channel exists for ───


def test_a_failing_verdict_fires_the_968_metric_and_retains_observed(rig):
    resp = _run(
        {"passed": False, "score": 40, "anti_pattern_violations": [{"phrase": "as an AI"}]},
        rig,
        text="As an AI coach, recovery looks steady.",
    )
    assert resp["statusCode"] == 200 and resp["passed"] is False  # the report is unchanged by capture

    metrics = _board_metrics(rig["cw"])
    names = [(m["MetricName"], _dims(m)) for m in metrics]
    assert ("BoardQualityGateVerdict", {"Surface": "board_ask", "Outcome": "failed"}) in names
    assert ("BoardQualityGateFired", {"CoachID": "sleep_coach"}) in names

    rig["retain"].assert_called_once()
    args, kwargs = rig["retain"].call_args
    assert args == ("board_ask", "observed")  # honest: nothing was regenerated, refused or held
    assert kwargs["draft"] == kwargs["final"] == "As an AI coach, recovery looks steady."
    assert {"type": "anti_pattern", "detail": "as an AI"} in kwargs["findings"]
    assert kwargs["extra"]["coach_id"] == "sleep_coach"
    assert kwargs["extra"]["regenerated"] is False


# ── A3: an unjudged draft is honest absence, never a failure datapoint ───────


def test_a_dead_judge_counts_as_unjudged_not_failed(rig):
    resp = _run(RuntimeError("bedrock 500"), rig)
    assert resp["passed"] is False and resp.get("_fallback") is True  # #3083 fail-closed report…

    metrics = _board_metrics(rig["cw"])
    outcomes = [_dims(m).get("Outcome") for m in metrics if "Outcome" in _dims(m)]
    assert outcomes == ["unjudged"]  # …but the MEASUREMENT records honest absence
    assert not any(m["MetricName"] == "BoardQualityGateFired" for m in metrics)
    rig["retain"].assert_not_called()  # an unjudged draft carries no findings worth harvesting


# ── A4: no opt-in, no machinery — the enforcement wire is byte-unchanged ─────


def test_without_the_optin_none_of_this_runs(rig):
    """The daily brief's event carries no `emit_verdict` key; its behaviour
    through the handler must be identical to pre-#3414."""
    event = quality_gate_event("sleep_coach", "text", None, generation_date="2026-06-15")
    assert EMIT_VERDICT_KEY not in event  # the builder attaches nothing by default

    resp = _run({"passed": False, "score": 40}, rig, emit=False)
    assert resp["statusCode"] == 200 and resp["passed"] is False
    assert _board_metrics(rig["cw"]) == []
    rig["retain"].assert_not_called()


# ── A5: both capture halves are fail-soft — telemetry never breaks the scorer ─


def test_a_dead_cloudwatch_still_returns_the_full_report(rig):
    rig["cw"].side_effect = RuntimeError("cloudwatch down")
    resp = _run({"passed": False, "score": 40}, rig)
    assert resp["statusCode"] == 200 and resp["passed"] is False
    rig["retain"].assert_called_once()  # metric death does not take retention with it


def test_a_dead_retention_still_returns_the_full_report(rig):
    rig["retain"].side_effect = RuntimeError("ddb down")
    resp = _run({"passed": False, "score": 40}, rig)
    assert resp["statusCode"] == 200 and resp["passed"] is False


# ── A6: capture observes the real report — it never forks the verdict ────────


def test_the_captured_outcome_tracks_the_returned_report(rig):
    """Negative control for the whole channel: neuter the emitter and the
    handler's own return is bit-for-bit what a synchronous caller gets — the
    capture is a tap on the report, not a second judge."""
    with_capture = _run({"passed": True, "score": 91}, rig)

    seen = {}

    def _spy(surface, coach_id, report, output_text):
        seen.update({"passed": report.get("passed"), "score": report.get("score")})

    import unittest.mock as _mock

    with _mock.patch.object(gate, "_emit_async_verdict", _spy):
        again = _run({"passed": True, "score": 91}, rig)
    assert seen == {"passed": True, "score": 91}  # the spy saw the same verdict…
    assert again == with_capture  # …and the wire report is identical either way
