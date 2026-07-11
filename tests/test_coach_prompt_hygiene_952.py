"""tests/test_coach_prompt_hygiene_952.py — #952: three coach-prompt hygiene fixes.

1. ai-content-3 — few-shot voice-calibration examples must NOT poison the ADR-104
   fabrication allow-list: `_allowlist_prompt` strips the few-shot block before
   `allowed_numbers` is derived, so a coach that parrots a calibration-example
   number ("18.2% deep sleep") as Matthew's current data is flagged as fabricating.
2. ai-content-6 — the R17-16 '[AI_UNAVAILABLE]' outage sentinel is held (pipeline
   returns None → existing legacy-fallback contract) instead of passing the
   number-free grounding gate, being cached under the brief fingerprint, and
   rendered in the brief.
3. ai-content-4 — the Board of Directors intro derives identity/phase facts from
   the profile's weight_loss_phases registry (and drops the chronological-age
   token entirely) instead of the hardcoded 'Matthew, 36yo ... Phase 1 Ignition:
   3 lbs/week, 1500 kcal deficit, 1800 cal daily'.

No Bedrock/AWS in any test: boto3 and call_anthropic are fakes.

Run with:   python3 -m pytest tests/test_coach_prompt_hygiene_952.py -v
"""

import inspect
import json
import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import ai_calls  # noqa: E402
from grounded_generation import allowed_numbers, fabricated_numbers  # noqa: E402

# ── fixtures ──

FEW_SHOT_BLOCK = (
    "\n\nVOICE CALIBRATION EXAMPLES (write in this style):\n"
    "\nExample 1:\nYour deep sleep hit 18.2% last night — efficiency dipped from 89% to 86% over week two.\n"
    "\nExample 2:\nHRV sat 6-8ms below your 30-day EWMA; wind-down slid from 10:45pm to 11:15pm.\n"
)

SYSTEM_PROMPT_TAIL = "\n\nWrite 2-4 paragraphs of sleep coaching for Matthew."

REAL_FACTS_LINE = "\nAUTHORITATIVE FACTS:\n  - Recovery is 62% | HRV 25.2 ms | RHR 64 bpm | weight 297.2 lbs\n"

PROFILE = {
    "weight_loss_phases": [
        {"phase": 1, "end_lbs": 250, "weekly_target_lbs": 3, "name": "Ignition", "start_lbs": 302, "deficit_target_kcal": 1500},
        {"phase": 2, "end_lbs": 220, "weekly_target_lbs": 2.5, "name": "Push", "start_lbs": 250, "deficit_target_kcal": 1250},
        {"phase": 3, "end_lbs": 200, "weekly_target_lbs": 2, "name": "Grind", "start_lbs": 220, "deficit_target_kcal": 1000},
        {"phase": 4, "end_lbs": 185, "weekly_target_lbs": 1, "name": "Chisel", "start_lbs": 200, "deficit_target_kcal": 500},
    ],
    "calorie_target": 1800,
    "journey_start_weight_lbs": 300.8,
    "goal_weight_lbs": 185,
    "age": 36,  # present in the profile — must never reach a prompt
}


# ── 1. allow-list derivation excludes the few-shot block (ai-content-3) ──


class TestAllowlistExcludesFewShot:
    def test_few_shot_numbers_are_stripped_from_the_allow_list(self):
        system_prompt = "You are Dr. Sarah." + REAL_FACTS_LINE + FEW_SHOT_BLOCK + SYSTEM_PROMPT_TAIL
        allowed = allowed_numbers(ai_calls._allowlist_prompt(system_prompt, FEW_SHOT_BLOCK), "SLEEP DATA: {}")
        for example_number in (18.2, 89.0, 86.0):
            assert example_number not in allowed, f"few-shot number {example_number} leaked into the allow-list"

    def test_parroted_example_number_is_now_flagged_as_fabricated(self):
        """The exact failure mode: a coach echoing a calibration-example vital as
        if it were Matthew's current data must fail the fabrication gate."""
        system_prompt = "You are Dr. Sarah." + REAL_FACTS_LINE + FEW_SHOT_BLOCK + SYSTEM_PROMPT_TAIL
        allowed = allowed_numbers(ai_calls._allowlist_prompt(system_prompt, FEW_SHOT_BLOCK), "SLEEP DATA: {}")
        assert 18.2 in fabricated_numbers("Your deep sleep hit 18.2% last night.", allowed)

    def test_pre_fix_behavior_would_have_passed_the_parrot(self):
        """Regression contrast: deriving from the FULL prompt (the old behavior)
        licenses the parroted number — the reason this fix exists."""
        system_prompt = "You are Dr. Sarah." + REAL_FACTS_LINE + FEW_SHOT_BLOCK + SYSTEM_PROMPT_TAIL
        allowed_old = allowed_numbers(system_prompt, "SLEEP DATA: {}")
        assert fabricated_numbers("Your deep sleep hit 18.2% last night.", allowed_old) == []

    def test_numbers_earned_elsewhere_in_the_prompt_stay_allowed(self):
        system_prompt = "You are Dr. Sarah." + REAL_FACTS_LINE + FEW_SHOT_BLOCK + SYSTEM_PROMPT_TAIL
        allowed = allowed_numbers(ai_calls._allowlist_prompt(system_prompt, FEW_SHOT_BLOCK), "SLEEP DATA: {}")
        assert {62.0, 25.2, 64.0, 297.2} <= allowed

    def test_number_in_both_few_shot_and_facts_stays_allowed(self):
        """Stripping the block's TEXT (not subtracting its numbers) keeps a value
        that also legitimately appears in the facts."""
        facts = "\nAUTHORITATIVE FACTS:\n  - Sleep efficiency last night: 86%\n"
        system_prompt = "You are Dr. Sarah." + facts + FEW_SHOT_BLOCK + SYSTEM_PROMPT_TAIL
        allowed = allowed_numbers(ai_calls._allowlist_prompt(system_prompt, FEW_SHOT_BLOCK), "SLEEP DATA: {}")
        assert 86.0 in allowed

    def test_empty_few_shot_block_is_a_no_op(self):
        prompt = "You are Dr. Sarah." + REAL_FACTS_LINE
        assert ai_calls._allowlist_prompt(prompt, "") == prompt
        assert ai_calls._allowlist_prompt(prompt, None) == prompt


# ── 2. the [AI_UNAVAILABLE] sentinel is held, never published/cached (ai-content-6) ──

VOICE_SPEC = {
    "display_name": "Dr. Sarah Chen",
    "domain": "sleep",
    "few_shot_examples": ["Your deep sleep hit 18.2% last night — efficiency dipped from 89% to 86%."],
    "structural_voice_rules": {},
    "decision_style": {},
    "anti_pattern_detection": {},
}


def _fake_pipeline_env(monkeypatch, generation_text):
    """Wire _run_coach_v2_pipeline to fakes: lambda invokes, S3 voice spec, a DDB
    table whose reads fail (facts + cache fail-soft), and a canned generation."""
    monkeypatch.setattr(ai_calls, "_comp_results_cache", {"trends": {}})

    fake_lambda = MagicMock()

    def _invoke(**kwargs):
        fn = kwargs["FunctionName"]
        payload_mock = MagicMock()
        if fn == "coach-narrative-orchestrator":
            brief = {"generation_brief": {"voice_guidance": {}, "decision_class_ceiling": "observational"}}
            payload_mock.read.return_value = json.dumps({"body": json.dumps(brief)}).encode()
        elif fn == "coach-quality-gate":
            payload_mock.read.return_value = json.dumps({"statusCode": 200, "passed": True, "score": 90}).encode()
        else:  # coach-state-updater (async, fire-and-forget)
            payload_mock.read.return_value = b"{}"
        return {"Payload": payload_mock}

    fake_lambda.invoke.side_effect = _invoke

    fake_s3 = MagicMock()
    body = MagicMock()
    body.read.return_value = json.dumps(VOICE_SPEC).encode()
    fake_s3.get_object.return_value = {"Body": body}

    fake_table = MagicMock()
    fake_table.query.side_effect = RuntimeError("no DDB in tests")
    fake_table.get_item.side_effect = RuntimeError("no DDB in tests")
    fake_table.put_item.side_effect = RuntimeError("no DDB in tests")
    fake_resource = MagicMock()
    fake_resource.Table.return_value = fake_table

    fake_boto3 = MagicMock()
    fake_boto3.client.side_effect = lambda service, **kw: fake_lambda if service == "lambda" else fake_s3
    fake_boto3.resource.return_value = fake_resource
    monkeypatch.setattr(ai_calls, "boto3", fake_boto3)
    monkeypatch.setattr(ai_calls, "call_anthropic", lambda *a, **kw: generation_text)
    return fake_lambda, fake_table


class TestAiUnavailableSentinelHeld:
    def test_is_ai_unavailable_truth_table(self):
        assert ai_calls._is_ai_unavailable("[AI_UNAVAILABLE]") is True
        assert ai_calls._is_ai_unavailable("prefix [AI_UNAVAILABLE] suffix") is True
        assert ai_calls._is_ai_unavailable("Real coaching text.") is False
        assert ai_calls._is_ai_unavailable("") is False
        assert ai_calls._is_ai_unavailable(None) is False

    def test_sentinel_generation_holds_and_never_publishes_or_caches(self, monkeypatch):
        fake_lambda, fake_table = _fake_pipeline_env(monkeypatch, "[AI_UNAVAILABLE]")
        result = ai_calls._run_coach_v2_pipeline("sleep_coach", {"whoop": {}}, "sleep", {}, "")
        assert result is None, "sentinel must hold (None) so the caller renders the honest legacy fallback"
        invoked = [c.kwargs["FunctionName"] for c in fake_lambda.invoke.call_args_list]
        assert "coach-state-updater" not in invoked, "sentinel must never be recorded as coach output"
        assert "coach-quality-gate" not in invoked, "held before the gate — no wasted gate invoke on an outage"
        fake_table.put_item.assert_not_called()  # never cached under the brief fingerprint

    def test_real_output_still_flows_through_the_pipeline(self, monkeypatch):
        """Control: the guard holds ONLY the sentinel — a normal generation still
        publishes (returns text + records via coach-state-updater)."""
        text = "Sleep looked steady this week. Keep the wind-down where it is."
        fake_lambda, _ = _fake_pipeline_env(monkeypatch, text)
        result = ai_calls._run_coach_v2_pipeline("sleep_coach", {"whoop": {}}, "sleep", {}, "")
        assert result == text
        invoked = [c.kwargs["FunctionName"] for c in fake_lambda.invoke.call_args_list]
        assert "coach-state-updater" in invoked


# ── 3. the BoD intro derives facts from the profile, no age token (ai-content-4) ──


class TestBodIntroFromProfile:
    def test_phase_targets_follow_the_registry_not_a_literal(self):
        line = ai_calls._bod_phase_targets({"latest_weight": 240}, PROFILE)
        assert line == "Phase 2 Push: 2.5 lbs/week, 1250 kcal deficit, 1800 cal daily."

    def test_phase_1_is_derived_not_hardcoded(self):
        line = ai_calls._bod_phase_targets({"latest_weight": 297.2}, PROFILE)
        assert line == "Phase 1 Ignition: 3 lbs/week, 1500 kcal deficit, 1800 cal daily."

    def test_final_phase_when_below_every_band(self):
        line = ai_calls._bod_phase_targets({"latest_weight": 180}, PROFILE)
        assert line.startswith("Phase 4 Chisel:")

    def test_ddb_decimals_are_handled(self):
        profile = {
            "weight_loss_phases": [
                {
                    "phase": Decimal("2"),
                    "end_lbs": Decimal("220"),
                    "weekly_target_lbs": Decimal("2.5"),
                    "name": "Push",
                    "deficit_target_kcal": Decimal("1250"),
                }
            ],
            "calorie_target": Decimal("1800"),
        }
        line = ai_calls._bod_phase_targets({"latest_weight": Decimal("240")}, profile)
        assert line == "Phase 2 Push: 2.5 lbs/week, 1250 kcal deficit, 1800 cal daily."

    def test_no_phase_registry_fails_soft_to_empty(self):
        assert ai_calls._bod_phase_targets({}, {}) == ""
        assert ai_calls._bod_phase_targets(None, None) == ""

    def test_identity_line_never_carries_the_age_token(self):
        line = ai_calls._bod_identity_line({"latest_weight": 240}, PROFILE)
        assert "36yo" not in line
        assert "36" not in line.split("(")[0]  # no age anywhere before the weight context

    def test_identity_line_fail_soft_without_data(self):
        line = ai_calls._bod_identity_line(None, None)
        assert "Speaking to Matthew" in line
        assert "36yo" not in line
        assert "Phase 1 Ignition" not in line  # no invented phase facts either

    def test_config_driven_intro_uses_derived_facts(self, monkeypatch):
        loader = MagicMock()
        loader.load_board.return_value = {"members": {}}
        loader.get_feature_members.return_value = [
            ("sarah_chen", {"name": "Dr. Sarah Chen", "title": "Sports Scientist"}, {"role": "unified_panel", "contribution": "training"})
        ]
        monkeypatch.setattr(ai_calls, "_HAS_BOARD_LOADER", True)
        monkeypatch.setattr(ai_calls, "_board_loader", loader)
        intro = ai_calls._build_daily_bod_intro_from_config({"latest_weight": 240}, PROFILE)
        assert intro is not None
        assert "36yo" not in intro
        assert "Phase 2 Push: 2.5 lbs/week, 1250 kcal deficit, 1800 cal daily." in intro
        assert "Phase 1 Ignition" not in intro

    def test_stale_literals_are_gone_from_the_module_source(self):
        """Regression pin for BOTH intro paths (config-driven + fallback): the
        hardcoded age and phase facts must not exist anywhere in ai_calls."""
        source = inspect.getsource(ai_calls)
        assert "36yo" not in source
        assert "Phase 1 Ignition: 3 lbs/week" not in source
