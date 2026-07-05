"""tests/test_coach_quality_gate_390.py — #390 (N-06): coach quality gate, advisory -> blocking.

The gate Lambda (coach_quality_gate.py) itself is unchanged — it always returns a
score/verdict and never blocks anything on its own. What changed is the CALLER
(ai_calls._run_coach_v2_pipeline): it used to fire the gate asynchronously and
discard the report; it now calls it synchronously via `_enforce_quality_gate` and
acts on `passed=False` — one corrective regeneration, then hold (return None, no
publish) if still failing. These tests pin that regenerate-or-hold state machine
without touching AWS: `lambda_client` and `regenerate_fn` are simple fakes.

See ADR-107 (docs/DECISIONS.md) for the measured 30-day re-evaluation that
justified promoting the gate from advisory to blocking.
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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import ai_calls  # noqa: E402


def _lambda_client_returning(*reports):
    """A fake boto3 lambda client whose .invoke() returns each report in turn
    (RequestResponse-shaped Payload), one per call — mirrors successive
    coach-quality-gate verdicts across a regenerate-or-hold loop."""
    client = MagicMock()
    iterator = iter(reports)

    def _invoke(**kwargs):
        assert kwargs["FunctionName"] == "coach-quality-gate"
        assert kwargs["InvocationType"] == "RequestResponse"
        report = next(iterator)
        payload_mock = MagicMock()
        payload_mock.read.return_value = json.dumps(report).encode()
        return {"Payload": payload_mock}

    client.invoke.side_effect = _invoke
    return client


class TestInvokeQualityGateSync:
    def test_passing_report_round_trips(self):
        client = _lambda_client_returning({"statusCode": 200, "passed": True, "score": 92})
        report = ai_calls._invoke_quality_gate_sync(client, "sleep_coach", "some coaching text", {})
        assert report["passed"] is True
        assert report["score"] == 92

    def test_missing_passed_field_defaults_to_true(self):
        client = _lambda_client_returning({"statusCode": 200, "score": 80})
        report = ai_calls._invoke_quality_gate_sync(client, "sleep_coach", "text", {})
        assert report["passed"] is True

    def test_fails_open_on_invoke_exception(self):
        client = MagicMock()
        client.invoke.side_effect = RuntimeError("Lambda unreachable")
        report = ai_calls._invoke_quality_gate_sync(client, "sleep_coach", "text", {})
        assert report["passed"] is True
        assert report["_fail_open"] is True

    def test_fails_open_on_malformed_payload(self):
        client = MagicMock()
        payload_mock = MagicMock()
        payload_mock.read.return_value = b'"not a dict"'
        client.invoke.return_value = {"Payload": payload_mock}
        report = ai_calls._invoke_quality_gate_sync(client, "sleep_coach", "text", {})
        assert report["passed"] is True
        assert report["_fail_open"] is True


class TestQualityGateCorrectionNote:
    def test_mentions_forbidden_phrase(self):
        note = ai_calls._quality_gate_correction_note({"anti_pattern_violations": [{"phrase": "As an AI coach", "context": "opening"}]})
        assert "As an AI coach" in note

    def test_mentions_decision_class_overreach(self):
        note = ai_calls._quality_gate_correction_note(
            {"decision_class_violations": [{"expected_max": "observational", "excerpt": "stop lifting weights"}]}
        )
        assert "observational" in note
        assert "stop lifting weights" in note

    def test_falls_back_to_generic_guidance_when_report_is_thin(self):
        note = ai_calls._quality_gate_correction_note({})
        assert "distinctive" in note.lower()

    def test_never_raises_on_malformed_findings(self):
        # Findings that don't match the expected {"phrase": ...} / dict shape
        # (e.g. a bare string) must not crash the correction-note builder.
        note = ai_calls._quality_gate_correction_note(
            {
                "anti_pattern_violations": ["a bare string finding"],
                "cross_coach_similarity_flags": [{"similar_to": "mind_coach", "reason": "same opening line"}],
                "suggestions": ["Vary your opening"],
            }
        )
        assert "mind_coach" in note
        assert "Vary your opening" in note


class TestEnforceQualityGate:
    def test_first_attempt_passes_no_regeneration(self):
        client = _lambda_client_returning({"passed": True, "score": 92})
        regenerate_fn = MagicMock(side_effect=AssertionError("should not regenerate on a first-attempt pass"))
        output, report = ai_calls._enforce_quality_gate(client, "sleep_coach", "good draft", {}, regenerate_fn)
        assert output == "good draft"
        assert report["passed"] is True
        regenerate_fn.assert_not_called()

    def test_fails_then_passes_on_the_bounded_retry(self):
        client = _lambda_client_returning(
            {"passed": False, "score": 62, "suggestions": ["too generic"]},
            {"passed": True, "score": 90},
        )
        regenerate_fn = MagicMock(return_value="regenerated draft")
        output, report = ai_calls._enforce_quality_gate(client, "nutrition_coach", "first draft", {}, regenerate_fn)
        assert output == "regenerated draft"  # the accepted (regenerated) text, not the discarded draft
        assert report["passed"] is True
        regenerate_fn.assert_called_once()
        # the correction note passed to the regenerator carries the gate's own finding
        (note,), _ = regenerate_fn.call_args
        assert "too generic" in note

    def test_cap_hit_holds_and_returns_none(self):
        # Two failing verdicts: the original + one regeneration attempt, both
        # sub-threshold — the bounded cap (1 regeneration) must stop here.
        client = _lambda_client_returning(
            {"passed": False, "score": 62},
            {"passed": False, "score": 62},
        )
        regenerate_fn = MagicMock(return_value="still bad draft")
        output, report = ai_calls._enforce_quality_gate(client, "glucose_coach", "first draft", {}, regenerate_fn)
        assert output is None  # held — nothing publishes this cycle
        assert report["passed"] is False
        regenerate_fn.assert_called_once()  # never more than max_regenerations attempts

    def test_cap_hit_emits_a_cloudwatch_metric_for_operator_visibility(self, monkeypatch):
        put_metric = MagicMock()
        monkeypatch.setattr(ai_calls._cw, "put_metric_data", put_metric)
        client = _lambda_client_returning(
            {"passed": False, "score": 62},
            {"passed": False, "score": 62},
        )
        output, _ = ai_calls._enforce_quality_gate(client, "labs_coach", "draft", {}, lambda note: "still bad")
        assert output is None
        put_metric.assert_called_once()
        _, kwargs = put_metric.call_args
        assert kwargs["Namespace"] == ai_calls._CW_NAMESPACE
        metric = kwargs["MetricData"][0]
        assert metric["MetricName"] == "CoachQualityGateHeld"
        assert {"Name": "CoachID", "Value": "labs_coach"} in metric["Dimensions"]

    def test_regeneration_exception_keeps_the_prior_draft_and_holds(self):
        client = _lambda_client_returning({"passed": False, "score": 62})
        regenerate_fn = MagicMock(side_effect=RuntimeError("bedrock timeout"))
        output, report = ai_calls._enforce_quality_gate(client, "training_coach", "first draft", {}, regenerate_fn)
        assert output is None
        assert report["passed"] is False

    def test_empty_regeneration_keeps_the_prior_draft_and_holds(self):
        client = _lambda_client_returning({"passed": False, "score": 62})
        output, report = ai_calls._enforce_quality_gate(client, "training_coach", "first draft", {}, lambda note: "   ")
        assert output is None
        assert report["passed"] is False

    def test_gate_infra_failure_fails_open_first_try(self):
        # An unreachable gate must never block a draft that was never actually scored.
        client = MagicMock()
        client.invoke.side_effect = RuntimeError("unreachable")
        regenerate_fn = MagicMock(side_effect=AssertionError("should not regenerate on a fail-open pass"))
        output, report = ai_calls._enforce_quality_gate(client, "physical_coach", "draft", {}, regenerate_fn)
        assert output == "draft"
        assert report["passed"] is True
        regenerate_fn.assert_not_called()
