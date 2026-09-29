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

from ai import ai_calls  # noqa: E402


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


# #4343 (2026-09-28 brief, request 15d734b8): the judge PASSED sleep's draft at 92; it was
# failed by one deterministic banned word ("gates"). The note carried no draft, so the rewrite
# was a fresh sample — and the sleep final added `autocorrelation` and `slow-wave`. The judge's
# similarity reason on that run quoted the other coach's wording verbatim (below).
SLEEP_0928_DRAFT = (
    "This isn't a small methodological footnote. It gates everything. On the night of September 26th, the numbers "
    "are genuinely strong — 89% recovery, HRV of 48.9 ms, resting heart rate of 55 bpm, and a deep sleep percentage "
    "of 30.1%, which is notable."
)
SLEEP_0928_REPORT = {
    "passed": False,
    "score": 92,
    "cross_coach_similarity_flags": [
        {
            "similar_to": "physical_coach",
            "reason": "Both use autocorrelation threshold language ('five consecutive same-direction observations').",
        }
    ],
    "suggestions": ["[banned_term] Replace 'gates' with a plain condition ('once …')."],
}


class TestQualityGateNoteRevisesTheDraft:
    def test_the_note_quotes_the_draft_and_asks_for_a_revision(self):
        note = ai_calls._quality_gate_correction_note(SLEEP_0928_REPORT, SLEEP_0928_DRAFT)
        assert SLEEP_0928_DRAFT in note
        assert "REVISE" in note and "keep every other sentence" in note
        assert "Replace 'gates'" in note  # a term the draft used stays named — it is the fix's target

    def test_the_note_hands_the_rewrite_no_banned_term_the_draft_lacked(self):
        from coach import reader_checks as rc

        note = ai_calls._quality_gate_correction_note(SLEEP_0928_REPORT, SLEEP_0928_DRAFT)
        instructions = note.replace(SLEEP_0928_DRAFT, "")
        introduced = {f["claimed"].lower() for f in rc.banned_term(instructions)} - {
            f["claimed"].lower() for f in rc.banned_term(SLEEP_0928_DRAFT)
        }
        assert introduced == set(), introduced
        assert "(jargon) threshold language" in note

    def test_mutation_control_an_unscrubbed_note_primes_autocorrelation(self, monkeypatch):
        from ai import quality_gate_note as qgn

        monkeypatch.setattr(qgn, "_banned_patterns", lambda: ())
        note = ai_calls._quality_gate_correction_note(SLEEP_0928_REPORT, SLEEP_0928_DRAFT)
        assert "autocorrelation" in note

    def test_without_a_draft_the_note_keeps_its_old_shape(self):
        note = ai_calls._quality_gate_correction_note(SLEEP_0928_REPORT)
        assert "YOUR DRAFT" not in note and note.startswith("REVIEW FEEDBACK")

    def test_the_enforcer_passes_the_failing_draft_into_the_note(self):
        client = _lambda_client_returning(SLEEP_0928_REPORT, {"passed": True, "score": 92})
        regenerate_fn = MagicMock(return_value=SLEEP_0928_DRAFT.replace("It gates everything.", "Everything waits on it."))
        output, report = ai_calls._enforce_quality_gate(client, "sleep_coach", SLEEP_0928_DRAFT, {}, regenerate_fn)
        (note,), _ = regenerate_fn.call_args
        assert SLEEP_0928_DRAFT in note
        assert report["passed"] is True

    def test_the_revision_share_is_logged(self, capsys):
        from ai import quality_gate_note as qgn

        share = qgn.log_revision("sleep_coach", SLEEP_0928_DRAFT, SLEEP_0928_DRAFT.replace("methodological footnote", "footnote"))
        assert 0.0 < share < 1.0
        assert "QG_REVISION kept=" in capsys.readouterr().out


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


class _FakeContext:
    """A Lambda context whose clock reads a fixed remaining time."""

    def __init__(self, remaining_ms):
        self.remaining_ms = remaining_ms

    def get_remaining_time_in_millis(self):
        return self.remaining_ms


class TestRegenerationTimeGuard4343:
    """#4343: past the reserved tail (the lead read + the send), a failing coach is HELD
    without the regenerate attempt. 09-27 ran 728.7 s of 900 s with every coach regenerating."""

    RESERVE_MS = int(ai_calls._deadline.RESERVE_SECONDS * 1000)

    def teardown_method(self):
        ai_calls._deadline.arm(None)

    def _run(self, remaining_ms):
        from ai import regen_deadline

        regen_deadline.arm(_FakeContext(remaining_ms) if remaining_ms is not None else None)
        client = _lambda_client_returning({"passed": False, "score": 42}, {"passed": True, "score": 92})
        regenerate_fn = MagicMock(return_value="regenerated draft")
        output, report = ai_calls._enforce_quality_gate(client, "physical_coach", "first draft", {}, regenerate_fn)
        return output, report, regenerate_fn

    def test_below_the_reserve_the_draft_is_held_without_a_regenerate_call(self, capsys):
        output, report, regenerate_fn = self._run(self.RESERVE_MS - 1)
        regenerate_fn.assert_not_called()
        assert output is None and report["passed"] is False
        assert "regeneration SKIPPED" in capsys.readouterr().out  # the skip is logged

    def test_at_or_above_the_reserve_it_regenerates(self):
        output, _, regenerate_fn = self._run(self.RESERVE_MS)
        regenerate_fn.assert_called_once()
        assert output == "regenerated draft"

    def test_an_unarmed_run_always_regenerates(self):
        """Every other ai_calls caller (analyzer, chat) never armed the deadline."""
        _, _, regenerate_fn = self._run(None)
        regenerate_fn.assert_called_once()

    def test_the_reserve_covers_the_measured_tail(self):
        # 09-27: last coach -> lead read 21.6 s -> Sent 52.9 s (74.4 s tail) + one rewrite <= 45 s.
        assert ai_calls._deadline.RESERVE_SECONDS >= 74.4 + 45

    def test_the_brief_handler_arms_the_deadline(self):
        import ast

        path = os.path.join(os.path.dirname(__file__), "..", "lambdas", "emails", "daily_brief_lambda.py")
        handler = next(n for n in ast.parse(open(path).read()).body if isinstance(n, ast.FunctionDef) and n.name == "lambda_handler")
        assert "regen_deadline.arm(context)" in ast.unparse(handler)


class TestEnforceQualityGateRetention:
    """#744: `_enforce_quality_gate` is the ORIGINAL surface #744 named (the
    highest-fire-rate ADR-104-adjacent gate, ADR-108) and #812's retention
    wiring (`eval_retention.py`) missed it. These pin that a fired verdict now
    reaches `eval_retention.retain("coach_brief", ...)` — and that a clean
    first-attempt pass, or a fail-open, does NOT retain anything (retention is
    only for a gate that actually fired a real verdict)."""

    def test_first_attempt_pass_retains_nothing(self, monkeypatch):
        retain = MagicMock()
        monkeypatch.setattr(ai_calls, "_retain_coach_brief_flag", retain)
        client = _lambda_client_returning({"passed": True, "score": 92})
        ai_calls._enforce_quality_gate(client, "sleep_coach", "good draft", {}, MagicMock())
        retain.assert_not_called()

    def test_fail_open_retains_nothing(self, monkeypatch):
        retain = MagicMock()
        monkeypatch.setattr(ai_calls, "_retain_coach_brief_flag", retain)
        client = MagicMock()
        client.invoke.side_effect = RuntimeError("unreachable")
        ai_calls._enforce_quality_gate(client, "physical_coach", "draft", {}, MagicMock())
        retain.assert_not_called()

    def test_fired_then_corrected_retains_the_pair(self, monkeypatch):
        retain = MagicMock()
        monkeypatch.setattr(ai_calls, "_retain_coach_brief_flag", retain)
        client = _lambda_client_returning(
            {"passed": False, "score": 62, "suggestions": ["too generic"]},
            {"passed": True, "score": 90},
        )
        output, report = ai_calls._enforce_quality_gate(client, "nutrition_coach", "first draft", {}, lambda note: "regenerated draft")
        assert output == "regenerated draft"
        # #3202: the brief rides along so the retained record carries the grounding
        # allow-list + facts that produced the verdict, not just the draft text.
        retain.assert_called_once_with("nutrition_coach", "flagged_corrected", "first draft", "regenerated draft", report, {})

    def test_fired_then_held_retains_the_pair(self, monkeypatch):
        retain = MagicMock()
        monkeypatch.setattr(ai_calls, "_retain_coach_brief_flag", retain)
        client = _lambda_client_returning(
            {"passed": False, "score": 62},
            {"passed": False, "score": 62},
        )
        output, report = ai_calls._enforce_quality_gate(client, "glucose_coach", "first draft", {}, lambda note: "still bad draft")
        assert output is None
        retain.assert_called_once_with("glucose_coach", "flagged_dropped", "first draft", "still bad draft", report, {})  # #3202

    def test_fired_then_regeneration_exception_retains_the_original_draft(self, monkeypatch):
        retain = MagicMock()
        monkeypatch.setattr(ai_calls, "_retain_coach_brief_flag", retain)
        client = _lambda_client_returning({"passed": False, "score": 62})
        ai_calls._enforce_quality_gate(client, "training_coach", "first draft", {}, MagicMock(side_effect=RuntimeError("timeout")))
        retain.assert_called_once()
        args = retain.call_args[0]
        assert args[0] == "training_coach"
        assert args[1] == "flagged_dropped"
        assert args[2] == "first draft"  # original draft — no regeneration ever produced a replacement
        assert args[3] == "first draft"  # output_text was never reassigned


class TestRetainCoachBriefFlag:
    """Pins the eval_retention wiring itself: findings translated from the gate
    report's own vocabulary, fail-soft on any error."""

    def test_translates_report_findings_and_calls_retain(self, monkeypatch):
        from experiment import eval_retention

        retained = {}

        def _fake_retain(surface, verdict, draft=None, final=None, findings=None, allowed=None, facts=None, extra=None):
            retained.update(surface=surface, verdict=verdict, draft=draft, final=final, findings=findings, extra=extra)
            return True

        monkeypatch.setattr(eval_retention, "retain", _fake_retain)
        report = {
            "score": 62,
            "anti_pattern_violations": [{"phrase": "As an AI coach"}],
            "decision_class_violations": [{"expected_max": "observational", "excerpt": "stop lifting"}],
            "cross_coach_similarity_flags": [{"similar_to": "mind_coach", "reason": "same opening line"}],
        }
        ai_calls._retain_coach_brief_flag("sleep_coach", "flagged_corrected", "draft text", "final text", report)
        assert retained["surface"] == "coach_brief"
        assert retained["verdict"] == "flagged_corrected"
        assert retained["draft"] == "draft text"
        assert retained["final"] == "final text"
        assert {"type": "anti_pattern", "detail": "As an AI coach"} in retained["findings"]
        assert {"type": "decision_class", "detail": "stop lifting"} in retained["findings"]
        assert {"type": "cross_coach_similarity", "detail": "same opening line"} in retained["findings"]
        assert retained["extra"] == {"coach_id": "sleep_coach", "score": 62}

    def test_never_raises_on_retention_failure(self, monkeypatch):
        from experiment import eval_retention

        def _boom(*a, **kw):
            raise RuntimeError("simulated DDB outage")

        monkeypatch.setattr(eval_retention, "retain", _boom)
        # Must not raise — retention is never load-bearing for the coach pipeline.
        ai_calls._retain_coach_brief_flag("sleep_coach", "flagged_dropped", "d", "f", {"score": 62})
