#!/usr/bin/env python3
"""tests/test_coach_quality_gate_behavior.py — behavioral contracts of
`lambdas/coach/coach_quality_gate.py`.

Part of #1658 tranche 2, and squarely on that issue's stated priority: the AI
honesty/grounding gates. Since N-06 (#390) this scorer is **blocking** at the
caller (`ai_calls._enforce_quality_gate` regenerates-or-holds on `passed=False`),
so the contracts that matter are:

  * a real sub-threshold verdict must be non-negotiable — the score override
    must beat a `passed: true` the model asserted anyway,
  * a gate that could not evaluate must fail OPEN but **visibly** (`_fallback`),
    never silently — the ADR-125/#1927 class is a gate reporting green while dark,
  * bad input must never block publication,
  * the cross-coach comparison must cover the whole operational roster, derived
    from the canonical registry rather than a literal.

Nothing here reaches Bedrock, DynamoDB or S3: every boundary is a hand-rolled
fake wired onto the module attribute the code looks the name up on.
"""

import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_import_err = None
try:
    from coach import coach_quality_gate as gate, persona_registry
except ImportError as _e:  # pragma: no cover — only when the bundle layout changes
    _import_err = _e
    gate = None  # type: ignore

if _import_err is not None:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason=f"coach_quality_gate unavailable: {_import_err}")  # type: ignore


# ──────────────────────────────────────────────────────────────────────────────
# Test doubles
# ──────────────────────────────────────────────────────────────────────────────


class _NoSuchKey(Exception):
    pass


class FakeS3:
    exceptions = type("_E", (), {"NoSuchKey": _NoSuchKey})()

    def __init__(self, objects=None, error=None):
        self.objects = dict(objects or {})
        self.error = error
        self.gets = []

    def get_object(self, Bucket=None, Key=None, **kw):
        self.gets.append(Key)
        if self.error is not None:
            raise self.error
        if Key not in self.objects:
            raise _NoSuchKey(Key)
        return {"Body": _Body(json.dumps(self.objects[Key]))}


class _Body:
    def __init__(self, text):
        self._t = text

    def read(self):
        return self._t.encode()


class FakeTable:
    """Bounded fake — `pages` is a finite list, never an unbounded generator."""

    def __init__(self, items=None):
        self.items = list(items or [])
        self.queries = []
        self.gets = []
        self.get_error = None
        self.query_error = None
        self.pages = None

    def get_item(self, Key=None, **kw):
        self.gets.append(Key)
        if self.get_error is not None:
            raise self.get_error
        for it in self.items:
            if it.get("pk") == Key["pk"] and it.get("sk") == Key["sk"]:
                return {"Item": it}
        return {}

    def query(self, **kwargs):
        self.queries.append(kwargs)
        if self.query_error is not None:
            raise self.query_error
        if self.pages:
            return self.pages.pop(0)
        # The module builds boto3 Key() conditions, so match on the serialized
        # condition's operand values rather than re-implementing the DSL.
        cond = kwargs["KeyConditionExpression"]
        pk, prefix = _condition_operands(cond)
        rows = [i for i in self.items if i.get("pk") == pk and str(i.get("sk", "")).startswith(prefix)]
        rows.sort(key=lambda r: r["sk"], reverse=not kwargs.get("ScanIndexForward", True))
        limit = kwargs.get("Limit")
        return {"Items": rows[:limit] if limit else rows}


def _condition_operands(cond):
    """Pull (pk, sk_prefix) out of a boto3 `Key(...).eq(...) & Key(...).begins_with(...)`."""
    values = []

    def walk(node):
        for v in getattr(node, "_values", ()):
            if hasattr(v, "_values"):
                walk(v)
            elif not hasattr(v, "name"):
                values.append(v)

    walk(cond)
    pk = values[0] if values else ""
    prefix = values[1] if len(values) > 1 else ""
    return pk, prefix


@pytest.fixture
def wired(monkeypatch):
    s3 = FakeS3()
    table = FakeTable()
    monkeypatch.setattr(gate, "s3", s3)
    monkeypatch.setattr(gate, "table", table)
    return s3, table


@pytest.fixture
def haiku(monkeypatch):
    """Replace the model call with a scripted responder + a call log."""
    calls = []

    class _Responder:
        def __init__(self):
            self.result = {"passed": True, "score": 90}
            self.error = None

        def __call__(self, system=None, user_message=None, **kw):
            calls.append({"system": system, "user_message": user_message, **kw})
            if self.error is not None:
                raise self.error
            return self.result

    responder = _Responder()
    responder.calls = calls
    monkeypatch.setattr(gate, "_call_haiku", responder)
    return responder


# ──────────────────────────────────────────────────────────────────────────────
# The verdict contract — what the blocking caller acts on
# ──────────────────────────────────────────────────────────────────────────────


def _run(**kw):
    args = {"coach_id": "sleep_coach", "output_text": "draft", "voice_spec": {}, "generation_brief": None}
    args.update(kw)
    return gate._run_quality_gate(args["coach_id"], args["output_text"], args["voice_spec"], args["generation_brief"])


class TestVerdict:
    def test_a_sub_threshold_score_fails_even_when_the_model_asserted_it_passed(self, haiku):
        """The deterministic threshold beats the model's own claim — otherwise a
        confident model could publish a known-failing draft (ADR-105)."""
        haiku.result = {"passed": True, "score": gate.PASS_SCORE_THRESHOLD - 1}
        assert _run()["passed"] is False

    def test_a_score_exactly_at_the_threshold_passes(self, haiku):
        haiku.result = {"passed": True, "score": gate.PASS_SCORE_THRESHOLD}
        assert _run()["passed"] is True

    def test_a_models_fail_verdict_is_never_upgraded_by_a_high_score(self, haiku):
        haiku.result = {"passed": False, "score": 95}
        assert _run()["passed"] is False

    def test_a_non_numeric_score_leaves_the_models_verdict_standing(self, haiku):
        haiku.result = {"passed": True, "score": "excellent"}
        assert _run()["passed"] is True

    def test_every_report_field_the_caller_reads_is_always_present(self, haiku):
        """The caller indexes these directly; a missing key would crash the
        brief pipeline, not just skip a check."""
        haiku.result = {}
        report = _run()
        for field in (
            "passed",
            "score",
            "anti_pattern_violations",
            "decision_class_violations",
            "voice_distinctiveness_score",
            "cross_coach_similarity_flags",
            "suggestions",
        ):
            assert field in report

    def test_low_voice_distinctiveness_adds_a_corrective_suggestion(self, haiku):
        haiku.result = {"passed": True, "score": 90, "voice_distinctiveness_score": gate.VOICE_DISTINCTIVENESS_MINIMUM - 1}
        assert "Voice distinctiveness below minimum threshold" in _run()["suggestions"]

    def test_the_distinctiveness_suggestion_is_not_duplicated(self, haiku):
        haiku.result = {
            "passed": True,
            "score": 90,
            "voice_distinctiveness_score": 10,
            "suggestions": ["Voice distinctiveness below minimum threshold"],
        }
        suggestions = _run()["suggestions"]
        assert suggestions.count("Voice distinctiveness below minimum threshold") == 1

    def test_distinctiveness_at_the_minimum_adds_no_suggestion(self, haiku):
        haiku.result = {"passed": True, "score": 90, "voice_distinctiveness_score": gate.VOICE_DISTINCTIVENESS_MINIMUM}
        assert _run()["suggestions"] == []

    def test_the_models_findings_are_carried_through_untouched(self, haiku):
        haiku.result = {
            "passed": False,
            "score": 30,
            "anti_pattern_violations": ["used 'circling back'"],
            "decision_class_violations": ["claimed causation from n=2"],
            "cross_coach_similarity_flags": ["mind_coach"],
        }
        report = _run()
        assert report["anti_pattern_violations"] == ["used 'circling back'"]
        assert report["decision_class_violations"] == ["claimed causation from n=2"]
        assert report["cross_coach_similarity_flags"] == ["mind_coach"]


class TestFailOpenIsVisible:
    def test_a_model_error_passes_the_draft_but_marks_the_report_as_a_fallback(self, haiku):
        """Fail-open is the deliberate contract for gate INFRA errors — but the
        #1927 lesson is that a gate which is dark must say so. `_fallback` is
        the only signal that distinguishes 'evaluated and passed' from 'could
        not evaluate'."""
        haiku.error = RuntimeError("bedrock timeout")
        report = _run()
        assert report["passed"] is True
        assert report["_fallback"] is True

    def test_the_fallback_report_names_the_failure_in_its_suggestions(self, haiku):
        haiku.error = RuntimeError("bedrock timeout")
        assert any("bedrock timeout" in s for s in _run()["suggestions"])

    def test_a_non_dict_model_response_is_treated_as_an_evaluation_failure(self, haiku):
        haiku.result = "I think the output looks fine!"
        report = _run()
        assert report["_fallback"] is True
        assert report["passed"] is True

    def test_the_fallback_score_is_the_neutral_midpoint_not_a_perfect_score(self, haiku):
        """A fail-open must not be indistinguishable from a great draft."""
        haiku.error = RuntimeError("down")
        assert _run()["score"] == 50

    def test_a_real_verdict_never_carries_the_fallback_marker(self, haiku):
        haiku.result = {"passed": True, "score": 88}
        assert "_fallback" not in _run()


# ──────────────────────────────────────────────────────────────────────────────
# The prompt actually carries what the gate claims to check
# ──────────────────────────────────────────────────────────────────────────────


class TestQualityGateMessage:
    def test_the_output_under_evaluation_is_in_the_message(self):
        msg = gate._build_quality_gate_message("sleep_coach", "THE DRAFT TEXT", {}, None)
        assert "THE DRAFT TEXT" in msg
        assert "sleep_coach" in msg

    def test_blacklisted_phrases_reach_the_model(self):
        spec = {"anti_pattern_detection": {"phrase_blacklist": ["circle back"], "structural_blacklist": ["three bullets"]}}
        msg = gate._build_quality_gate_message("sleep_coach", "draft", spec, None)
        assert "circle back" in msg
        assert "three bullets" in msg

    def test_an_empty_voice_spec_still_inherits_the_shared_avoid_list(self):
        """Since the MOS substrate (coaching-team v2, 2026-08-09) every coach —
        even one with a bare spec — inherits the shared banned-phrase floor; the
        checklist section only disappears when the shared standard is ALSO
        unavailable (fail-soft)."""
        msg = gate._build_quality_gate_message("sleep_coach", "draft", {}, None)
        assert "Anti-Pattern Checklist" in msg
        assert "keep up the good work" in msg

    def test_no_spec_and_no_shared_standard_omits_the_section(self, monkeypatch):
        monkeypatch.setattr(gate, "_shared_blacklists", lambda: ([], []))
        msg = gate._build_quality_gate_message("sleep_coach", "draft", {}, None)
        assert "Anti-Pattern Checklist" not in msg

    def test_the_decision_class_ceiling_reaches_the_model(self):
        """Check 2 is 'does the output exceed the evidence ceiling' — the
        ceiling has to be in the prompt for that check to be real."""
        msg = gate._build_quality_gate_message("sleep_coach", "draft", {}, {"decision_class_ceiling": "observation_only"})
        assert "observation_only" in msg

    def test_data_quality_and_guardrails_reach_the_model(self):
        brief = {"data_quality": {"n": 3}, "guardrails": {"no_causal_claims": True}}
        msg = gate._build_quality_gate_message("sleep_coach", "draft", {}, brief)
        assert "no_causal_claims" in msg
        assert '"n": 3' in msg

    def test_a_plain_string_brief_is_included_verbatim(self):
        msg = gate._build_quality_gate_message("sleep_coach", "draft", {}, "keep it observational")
        assert "keep it observational" in msg

    def test_the_persona_and_structural_signature_reach_the_model(self):
        spec = {"persona": {"tone": "clinical"}, "structural_signature": {"opens_with": "a number"}}
        msg = gate._build_quality_gate_message("sleep_coach", "draft", spec, None)
        assert "clinical" in msg
        assert "opens_with" in msg

    def test_other_coach_outputs_are_included_for_the_similarity_check(self):
        msg = gate._build_quality_gate_message("sleep_coach", "draft", {}, None, {"mind_coach": "their draft"})
        assert "mind_coach" in msg
        assert "their draft" in msg

    def test_an_empty_peer_output_is_not_rendered_as_a_blank_comparison(self):
        msg = gate._build_quality_gate_message("sleep_coach", "draft", {}, None, {"mind_coach": ""})
        assert "### mind_coach" not in msg

    def test_the_message_ends_by_demanding_json_only(self):
        msg = gate._build_quality_gate_message("sleep_coach", "draft", {}, None)
        assert msg.rstrip().endswith("Return ONLY valid JSON with the quality report.")


# ──────────────────────────────────────────────────────────────────────────────
# Cross-coach comparison — guard the SET
# ──────────────────────────────────────────────────────────────────────────────


class TestCrossCoachComparison:
    def test_the_comparison_covers_the_whole_operational_roster_except_self(self, wired):
        """Guard the SET, not the instance: the expectation is derived from the
        canonical persona registry, so adding a ninth operational coach fails
        here instead of silently dropping out of the similarity check."""
        _, table = wired
        expected = {c for c in persona_registry.OPERATIONAL_COACH_IDS if c != "sleep_coach"}
        table.items = [{"pk": f"COACH#{c}", "sk": "OUTPUT#2026-05-09", "content": f"{c} draft"} for c in expected]
        out = gate._fetch_other_coaches_recent_outputs("sleep_coach")
        assert set(out) == expected

    def test_the_coach_under_evaluation_is_never_compared_against_itself(self, wired):
        _, table = wired
        table.items = [{"pk": "COACH#sleep_coach", "sk": "OUTPUT#2026-05-09", "content": "own draft"}]
        assert gate._fetch_other_coaches_recent_outputs("sleep_coach") == {}

    def test_an_explicit_comparison_list_overrides_the_default_roster(self, wired):
        _, table = wired
        table.items = [{"pk": "COACH#mind_coach", "sk": "OUTPUT#2026-05-09", "content": "x"}]
        out = gate._fetch_other_coaches_recent_outputs("sleep_coach", other_coach_ids=["mind_coach"])
        assert set(out) == {"mind_coach"}

    def test_only_the_most_recent_output_per_coach_is_compared(self, wired):
        _, table = wired
        table.items = [
            {"pk": "COACH#mind_coach", "sk": "OUTPUT#2026-05-01", "content": "old"},
            {"pk": "COACH#mind_coach", "sk": "OUTPUT#2026-05-09", "content": "new"},
        ]
        out = gate._fetch_other_coaches_recent_outputs("sleep_coach", other_coach_ids=["mind_coach"])
        assert out["mind_coach"] == "new"

    def test_peer_output_is_truncated_so_the_prompt_cannot_blow_up(self, wired):
        _, table = wired
        table.items = [{"pk": "COACH#mind_coach", "sk": "OUTPUT#2026-05-09", "content": "x" * 5000}]
        out = gate._fetch_other_coaches_recent_outputs("sleep_coach", other_coach_ids=["mind_coach"])
        assert len(out["mind_coach"]) == 500

    def test_a_coach_with_no_stored_output_is_simply_absent(self, wired):
        assert gate._fetch_other_coaches_recent_outputs("sleep_coach", other_coach_ids=["mind_coach"]) == {}


# ──────────────────────────────────────────────────────────────────────────────
# Storage boundaries
# ──────────────────────────────────────────────────────────────────────────────


class TestVoiceSpecLoad:
    def test_a_stored_spec_is_returned_parsed(self, wired):
        s3, _ = wired
        s3.objects["config/coaches/sleep_coach.json"] = {"persona": {"tone": "clinical"}}
        assert gate._load_voice_spec("sleep_coach") == {"persona": {"tone": "clinical"}}

    def test_a_missing_spec_degrades_to_an_empty_spec_not_an_exception(self, wired):
        assert gate._load_voice_spec("sleep_coach") == {}

    def test_an_s3_outage_degrades_to_an_empty_spec(self, wired):
        s3, _ = wired
        s3.error = RuntimeError("503 SlowDown")
        assert gate._load_voice_spec("sleep_coach") == {}


class TestDynamoReads:
    def test_a_visible_singleton_is_returned_with_decimals_converted(self, wired):
        from decimal import Decimal

        _, table = wired
        table.items = [{"pk": "COACH#sleep_coach", "sk": "VOICE#state", "score": Decimal("4.5")}]
        item = gate._get_item("COACH#sleep_coach", "VOICE#state")
        assert item["score"] == 4.5

    def test_a_tombstoned_singleton_reads_as_absent(self, wired):
        """#946/#1969: a reset's tombstone must not keep serving the wiped
        cycle through a get_item that bypasses the query filter."""
        _, table = wired
        table.items = [{"pk": "COACH#sleep_coach", "sk": "VOICE#state", "tombstone": True}]
        assert gate._get_item("COACH#sleep_coach", "VOICE#state") is None

    def test_a_prior_phase_singleton_reads_as_absent(self, wired):
        _, table = wired
        table.items = [{"pk": "COACH#sleep_coach", "sk": "VOICE#state", "phase": "pilot"}]
        assert gate._get_item("COACH#sleep_coach", "VOICE#state") is None

    def test_a_missing_singleton_reads_as_none(self, wired):
        assert gate._get_item("COACH#sleep_coach", "VOICE#state") is None

    def test_a_failed_singleton_read_degrades_to_none(self, wired):
        _, table = wired
        table.get_error = RuntimeError("throttled")
        assert gate._get_item("COACH#sleep_coach", "VOICE#state") is None

    def test_the_phase_filter_is_applied_to_every_prefix_query(self, wired):
        _, table = wired
        gate._query_begins_with("COACH#mind_coach", "OUTPUT#")
        assert "FilterExpression" in table.queries[-1]

    def test_a_paginated_query_returns_every_page(self, wired):
        _, table = wired
        table.pages = [
            {"Items": [{"pk": "COACH#x", "sk": "OUTPUT#1"}], "LastEvaluatedKey": {"pk": "COACH#x", "sk": "OUTPUT#1"}},
            {"Items": [{"pk": "COACH#x", "sk": "OUTPUT#2"}]},
        ]
        assert len(gate._query_begins_with("COACH#x", "OUTPUT#")) == 2

    def test_a_limit_stops_pagination_rather_than_walking_the_partition(self, wired):
        _, table = wired
        table.pages = [
            {
                "Items": [{"pk": "COACH#x", "sk": f"OUTPUT#{i}"} for i in range(5)],
                "LastEvaluatedKey": {"pk": "COACH#x", "sk": "OUTPUT#4"},
            },
        ]
        assert len(gate._query_begins_with("COACH#x", "OUTPUT#", limit=3)) == 3

    def test_a_failed_query_degrades_to_an_empty_list(self, wired):
        _, table = wired
        table.query_error = RuntimeError("throttled")
        assert gate._query_begins_with("COACH#x", "OUTPUT#") == []


# ──────────────────────────────────────────────────────────────────────────────
# Model response parsing
# ──────────────────────────────────────────────────────────────────────────────


class TestCallHaikuParsing:
    @pytest.fixture
    def raw(self, monkeypatch):
        """Script `call_anthropic_raw` where `_call_haiku` looks it up.

        It is imported INSIDE the function from `common.retry_utils`, so the
        patch target is that module's attribute — patching a re-export would
        silently no-op.
        """
        import common.retry_utils as retry_utils

        holder = {"text": "{}"}

        def _fake(req):
            return {"content": [{"text": holder["text"]}]}

        monkeypatch.setattr(retry_utils, "call_anthropic_raw", _fake)
        return holder

    def test_a_clean_json_response_is_parsed(self, raw):
        raw["text"] = '{"passed": false, "score": 22}'
        assert gate._call_haiku("sys", "msg") == {"passed": False, "score": 22}

    def test_json_wrapped_in_a_labelled_code_fence_is_recovered(self, raw):
        raw["text"] = 'Here you go:\n```json\n{"passed": true, "score": 80}\n```'
        assert gate._call_haiku("sys", "msg") == {"passed": True, "score": 80}

    def test_json_wrapped_in_a_bare_code_fence_is_recovered(self, raw):
        raw["text"] = '```\n{"passed": true, "score": 80}\n```'
        assert gate._call_haiku("sys", "msg") == {"passed": True, "score": 80}

    def test_unparseable_prose_is_returned_as_text_for_the_caller_to_reject(self, raw):
        """Returning the raw string is what lets `_run_quality_gate` recognise a
        non-dict and fail open visibly rather than crash."""
        raw["text"] = "The output looks good to me."
        assert gate._call_haiku("sys", "msg") == "The output looks good to me."

    def test_a_broken_fence_falls_back_to_text_rather_than_raising(self, raw):
        raw["text"] = "```json\n{not valid json\n```"
        assert isinstance(gate._call_haiku("sys", "msg"), str)


# ──────────────────────────────────────────────────────────────────────────────
# Handler
# ──────────────────────────────────────────────────────────────────────────────


class TestHandler:
    def test_a_missing_coach_id_is_rejected_without_blocking_publication(self, wired, haiku):
        resp = gate.lambda_handler({"output_text": "draft"}, None)
        assert resp["statusCode"] == 400
        assert resp["passed"] is True

    def test_a_missing_output_text_is_rejected_without_blocking_publication(self, wired, haiku):
        resp = gate.lambda_handler({"coach_id": "sleep_coach"}, None)
        assert resp["statusCode"] == 400
        assert resp["passed"] is True

    def test_an_empty_output_text_is_treated_as_missing(self, wired, haiku):
        assert gate.lambda_handler({"coach_id": "sleep_coach", "output_text": ""}, None)["statusCode"] == 400

    def test_a_successful_run_returns_the_report_alongside_the_coach_id(self, wired, haiku):
        haiku.result = {"passed": False, "score": 31, "anti_pattern_violations": ["x"]}
        resp = gate.lambda_handler({"coach_id": "sleep_coach", "output_text": "draft", "skip_cross_coach": True}, None)
        assert resp["statusCode"] == 200
        assert resp["coach_id"] == "sleep_coach"
        assert resp["passed"] is False
        assert resp["score"] == 31

    def test_a_voice_spec_supplied_in_the_event_is_used_without_touching_s3(self, wired, haiku):
        s3, _ = wired
        gate.lambda_handler(
            {"coach_id": "sleep_coach", "output_text": "draft", "voice_spec": {"persona": {"tone": "wry"}}, "skip_cross_coach": True},
            None,
        )
        assert s3.gets == []
        assert "wry" in haiku.calls[0]["user_message"]

    def test_a_missing_voice_spec_is_loaded_from_the_coaches_config_prefix(self, wired, haiku):
        s3, _ = wired
        gate.lambda_handler({"coach_id": "sleep_coach", "output_text": "draft", "skip_cross_coach": True}, None)
        assert s3.gets == ["config/coaches/sleep_coach.json"]

    def test_skip_cross_coach_avoids_the_peer_output_queries(self, wired, haiku):
        _, table = wired
        gate.lambda_handler({"coach_id": "sleep_coach", "output_text": "draft", "skip_cross_coach": True}, None)
        assert table.queries == []

    def test_peer_outputs_are_fetched_when_not_supplied(self, wired, haiku):
        _, table = wired
        gate.lambda_handler({"coach_id": "sleep_coach", "output_text": "draft"}, None)
        assert table.queries, "expected the cross-coach comparison to query peer outputs"

    def test_peer_outputs_supplied_in_the_event_are_used_without_querying(self, wired, haiku):
        _, table = wired
        gate.lambda_handler(
            {"coach_id": "sleep_coach", "output_text": "draft", "other_coach_outputs": {"mind_coach": "their draft"}},
            None,
        )
        assert table.queries == []
        assert "their draft" in haiku.calls[0]["user_message"]

    def test_an_unexpected_crash_returns_a_permissive_report_not_a_hard_failure(self, wired, monkeypatch):
        """A gate that crashes must never take the daily brief down with it."""

        def _boom(*a, **kw):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(gate, "_run_quality_gate", _boom)
        resp = gate.lambda_handler({"coach_id": "sleep_coach", "output_text": "draft", "skip_cross_coach": True}, None)
        assert resp["statusCode"] == 500
        assert resp["passed"] is True
        assert any("crashed" in s for s in resp["suggestions"])

    def test_a_model_outage_still_returns_a_two_hundred_with_the_fallback_marker(self, wired, haiku):
        haiku.error = RuntimeError("bedrock down")
        resp = gate.lambda_handler({"coach_id": "sleep_coach", "output_text": "draft", "skip_cross_coach": True}, None)
        assert resp["statusCode"] == 200
        assert resp["_fallback"] is True
