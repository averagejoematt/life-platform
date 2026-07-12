"""tests/test_daily_brief_grounding_and_hold.py — #966 (ai-content-2).

ADR-104's "grounded generation on every AI narrative surface" had a coverage
hole at the highest-frequency surface: the daily brief's 4 legacy AI calls
(Board of Directors, training+nutrition, journal coach, TL;DR) had no
allow-list number gate, and the legacy training/nutrition call was the
automatic fallback whenever a v2 draft was HELD by the quality or presence-ack
gate — so a deliberate hold still published an ungated narrative.

Two contracts are pinned here:

  1. Each of the 4 legacy calls routes its output through
     `ai_calls._ground_legacy_output` — the existing pure
     `grounded_generation` allow-list + `regen_once` harness (one corrective
     rewrite, kept only if findings strictly decrease). The AI-3 validator is
     untouched: this ADDS the deterministic gate, it doesn't replace validation.
  2. A quality-gate/presence-ack HOLD is TERMINAL for its domain:
     `_run_coach_v2_pipeline` returns an `ai_calls.CoachHold` sentinel
     (distinct from error-caused None), and `_run_ai_coach_pipeline` skips the
     legacy training/nutrition fallback for held domains — while an
     error-caused None still falls back (an infra failure carries no gate
     judgment).

No AWS credentials or network access required: `call_anthropic` (and the
coach v2 functions on the daily-brief side) are monkeypatched.

Wall-clock trap (golden-test lesson): all fixture dates are pinned far past
(2024) so no now-minus-date math can flip an assertion as real time advances.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "lambdas" / "emails"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

import ai_calls  # noqa: E402

# Far-past fixture dates on purpose (see module docstring).
PROFILE = {
    "calorie_target": 1500,
    "protein_target_g": 190,
    "fat_target_g": 60,
    "carb_target_g": 125,
    "goal_weight_lbs": 185,
    "journey_start_date": "2024-06-08",
    "journey_start_weight_lbs": 311.62,
    "primary_obstacles": ["late-night snacking"],
}

DATA = {
    "date": "2024-06-10",
    "whoop": {"recovery_score": 68, "hrv": 41.2, "resting_heart_rate": 58},
    "sleep": {"sleep_efficiency_pct": 89.0},
    "macrofactor": {"calories": 1480, "protein_g": 185, "fat_g": 55, "carbs_g": 120},
    "journal_entries": [{"raw_text": "Quiet day. Walked after dinner and skipped the snack."}],
}

COMPONENT_SCORES = {"sleep_quality": 84, "recovery": 68, "nutrition": 91, "movement": 77}

# Deliberately weird decimals that appear nowhere in any fixture/prompt text —
# the fabricated-number class the allow-list gate exists to catch.
FABRICATED = "66.6"
FABRICATED_2 = "47.3"


def _correction_capture(clean_response):
    """A regen callable that records the correction prompt it was handed."""
    calls = []

    def _regen(correction):
        calls.append(correction)
        return clean_response

    return _regen, calls


# ══════════════════════════════════════════════════════════════════════════════
# 1. _ground_legacy_output — the harness reuse itself
# ══════════════════════════════════════════════════════════════════════════════


def test_ground_legacy_output_corrects_fabricated_number():
    regen, calls = _correction_capture("Recovery was strong yesterday — keep the streak alive.")
    out = ai_calls._ground_legacy_output(
        "unit_test",
        f"Recovery hit {FABRICATED}% overnight — push hard today.",
        regen,
        "AUTHORITATIVE DATA: recovery 68, hrv 41.2",
    )
    assert out == "Recovery was strong yesterday — keep the streak alive."
    assert len(calls) == 1
    assert "CORRECTION REQUIRED" in calls[0]
    assert FABRICATED in calls[0]


def test_ground_legacy_output_passes_grounded_draft_untouched():
    regen, calls = _correction_capture("should never be used")
    draft = "Recovery hit 68% with HRV at 41.2 ms — solid base for today."
    out = ai_calls._ground_legacy_output("unit_test", draft, regen, "recovery 68, hrv 41.2")
    assert out == draft
    assert calls == []  # no findings ⇒ no regeneration call (no extra AI spend)


def test_ground_legacy_output_keeps_original_when_rewrite_not_better():
    # Rewrite fabricates just as much — regen_once must keep the original draft
    # (never regresses, never loops).
    regen, calls = _correction_capture(f"Recovery hit {FABRICATED_2}% overnight.")
    draft = f"Recovery hit {FABRICATED}% overnight."
    out = ai_calls._ground_legacy_output("unit_test", draft, regen, "recovery 68")
    assert out == draft
    assert len(calls) == 1


def test_ground_legacy_output_passes_outage_sentinel_through():
    regen, calls = _correction_capture("should never be used")
    out = ai_calls._ground_legacy_output("unit_test", ai_calls.AI_UNAVAILABLE_SENTINEL, regen, "recovery 68")
    assert out == ai_calls.AI_UNAVAILABLE_SENTINEL
    assert calls == []


def test_ground_legacy_output_passes_empty_and_none_through():
    regen, calls = _correction_capture("should never be used")
    assert ai_calls._ground_legacy_output("unit_test", "", regen, "x 1") == ""
    assert ai_calls._ground_legacy_output("unit_test", None, regen, "x 1") is None
    assert calls == []


# ══════════════════════════════════════════════════════════════════════════════
# 2. The 4 legacy call sites are actually WIRED through the gate
# ══════════════════════════════════════════════════════════════════════════════


def _mock_call_anthropic(monkeypatch, responses):
    """Replace ai_calls.call_anthropic with a scripted mock; returns the mock.
    Every regen path in the legacy calls also routes through call_anthropic,
    so `side_effect` order is generation → corrective rewrite."""
    mock = MagicMock(side_effect=list(responses))
    monkeypatch.setattr(ai_calls, "call_anthropic", mock)
    # BoD + TL;DR run the IC-3 analysis pass (its own call_anthropic call) first;
    # neutralize it so the scripted responses map 1:1 to generation/regen.
    monkeypatch.setattr(ai_calls, "_run_analysis_pass", lambda *a, **k: None)
    return mock


def test_journal_coach_regenerates_on_fabricated_number(monkeypatch):
    clean = "You keep circling the same worry without naming it. || Take a 20-minute walk before noon."
    mock = _mock_call_anthropic(
        monkeypatch,
        [f"Your HRV of {FABRICATED} ms says otherwise. || Breathe.", clean],
    )
    out = ai_calls.call_journal_coach(DATA, PROFILE)
    assert out == clean
    assert mock.call_count == 2
    regen_prompt = mock.call_args_list[1].args[0]
    assert "CORRECTION REQUIRED" in regen_prompt
    assert FABRICATED in regen_prompt


def test_journal_coach_single_call_when_grounded(monkeypatch):
    grounded = "You walked instead of snacking — that is the pattern shifting. || Repeat it tonight."
    mock = _mock_call_anthropic(monkeypatch, [grounded])
    out = ai_calls.call_journal_coach(DATA, PROFILE)
    assert out == grounded
    assert mock.call_count == 1


def test_training_nutrition_coach_regenerates_on_fabricated_number(monkeypatch):
    fabricated_json = f'{{"training": "You pushed {FABRICATED}% intensity.", "nutrition": "Protein landed at {FABRICATED_2}g."}}'
    clean_json = '{"training": "Recovery at 68 supports a normal session.", "nutrition": "Protein at 185g beat the floor."}'
    mock = _mock_call_anthropic(monkeypatch, [fabricated_json, clean_json])
    out = ai_calls.call_training_nutrition_coach(DATA, PROFILE)
    assert out == {
        "training": "Recovery at 68 supports a normal session.",
        "nutrition": "Protein at 185g beat the floor.",
    }
    assert mock.call_count == 2
    assert "CORRECTION REQUIRED" in mock.call_args_list[1].args[0]


def test_board_of_directors_regenerates_on_fabricated_number(monkeypatch):
    clean = "Recovery at 68 and protein at 185g say the base held — protect the streak with an early wind-down."
    mock = _mock_call_anthropic(
        monkeypatch,
        [f"Recovery climbed from {FABRICATED}% to 68% — the trend is real.", clean],
    )
    out = ai_calls.call_board_of_directors(DATA, PROFILE, 82, "B", COMPONENT_SCORES)
    assert out == clean
    assert mock.call_count == 2
    regen_prompt = mock.call_args_list[1].args[0]
    assert "CORRECTION REQUIRED" in regen_prompt
    # The AI-3 validator stays wired on the corrective rewrite too.
    assert mock.call_args_list[1].kwargs.get("output_type") is not None or not ai_calls._AI_VALIDATOR_AVAILABLE


def test_tldr_and_guidance_regenerates_on_fabricated_number(monkeypatch):
    fabricated_json = f'{{"tldr": "Recovery {FABRICATED}% — coast today.", "guidance": ["walk"]}}'
    clean_json = '{"tldr": "Recovery 68 + protein 185g — hold the line today.", "guidance": ["walk after dinner"]}'
    mock = _mock_call_anthropic(monkeypatch, [fabricated_json, clean_json])
    out = ai_calls.call_tldr_and_guidance(DATA, PROFILE, 82, "B", COMPONENT_SCORES, {}, 72, "green", "")
    assert out == {"tldr": "Recovery 68 + protein 185g — hold the line today.", "guidance": ["walk after dinner"]}
    assert mock.call_count == 2
    assert "CORRECTION REQUIRED" in mock.call_args_list[1].args[0]


# ══════════════════════════════════════════════════════════════════════════════
# 3. CoachHold — a deliberate hold is terminal; an error still falls back
# ══════════════════════════════════════════════════════════════════════════════

_PIPELINE_KWARGS = dict(
    data={"date": "2024-06-10", "journal_entries": [{"raw_text": "quiet day"}]},
    profile={"goal_weight_lbs": 185},
    day_grade_score=79,
    grade="B+",
    component_scores={},
    component_details={},
    readiness_score=72,
    readiness_colour="#059669",
    character_sheet=None,
    brief_mode="standard",
)

_COACH_FN_NAMES = [
    "call_sleep_coach_v2",
    "call_nutrition_coach_v2",
    "call_training_coach_v2",
    "call_mind_coach_v2",
    "call_physical_coach_v2",
    "call_glucose_coach_v2",
    "call_labs_coach_v2",
    "call_explorer_coach_v2",
]

_LEGACY_TN = {"training": "legacy training text", "nutrition": "legacy nutrition text"}


def _mock_brief_ai(monkeypatch, m, v2_returns=None):
    """Mock every ai_calls.* function the pipeline calls. `v2_returns` maps a
    coach-fn name to its return value (default: real text)."""
    v2_returns = v2_returns or {}
    for name in _COACH_FN_NAMES:
        monkeypatch.setattr(m.ai_calls, name, MagicMock(return_value=v2_returns.get(name, "v2 text")))
    for name in ["call_board_of_directors", "call_journal_coach", "daily_brief_shared_system"]:
        monkeypatch.setattr(m.ai_calls, name, MagicMock(return_value="mock text"))
    monkeypatch.setattr(m.ai_calls, "call_tldr_and_guidance", MagicMock(return_value={"tldr": "t", "guidance": []}))
    # Fresh dict per test — the pipeline mutates it when a domain is held.
    monkeypatch.setattr(m.ai_calls, "call_training_nutrition_coach", MagicMock(return_value=dict(_LEGACY_TN)))
    monkeypatch.setattr(m, "boto3", MagicMock())
    monkeypatch.setattr(m, "_daily_brief_ai_allowed", lambda: True)


def test_quality_hold_on_training_drops_legacy_training_only(monkeypatch):
    import daily_brief_lambda as m

    _mock_brief_ai(
        monkeypatch,
        m,
        v2_returns={"call_training_coach_v2": ai_calls.CoachHold("training_coach", "quality_gate")},
    )
    result = m._run_ai_coach_pipeline(**_PIPELINE_KWARGS)

    # The held sentinel is never rendered as coach text.
    assert result["training_coach_v2_text"] == ""
    # Legacy call still runs (nutrition is not held) but the held domain's
    # ungated narrative is dropped: hold, don't publish — actually holds.
    m.ai_calls.call_training_nutrition_coach.assert_called_once()
    assert result["training_nutrition"] == {"nutrition": "legacy nutrition text"}


def test_presence_ack_hold_on_nutrition_drops_legacy_nutrition_only(monkeypatch):
    import daily_brief_lambda as m

    _mock_brief_ai(
        monkeypatch,
        m,
        v2_returns={"call_nutrition_coach_v2": ai_calls.CoachHold("nutrition_coach", "presence_ack")},
    )
    result = m._run_ai_coach_pipeline(**_PIPELINE_KWARGS)

    assert result["nutrition_coach_v2_text"] == ""
    assert result["training_nutrition"] == {"training": "legacy training text"}


def test_both_domains_held_skips_legacy_call_entirely(monkeypatch):
    import daily_brief_lambda as m

    _mock_brief_ai(
        monkeypatch,
        m,
        v2_returns={
            "call_training_coach_v2": ai_calls.CoachHold("training_coach", "quality_gate"),
            "call_nutrition_coach_v2": ai_calls.CoachHold("nutrition_coach", "quality_gate"),
        },
    )
    result = m._run_ai_coach_pipeline(**_PIPELINE_KWARGS)

    # Both domains held ⇒ the ungated legacy call is never even made.
    m.ai_calls.call_training_nutrition_coach.assert_not_called()
    assert result["training_nutrition"] == {}


def test_error_caused_none_still_falls_back_to_legacy(monkeypatch):
    """Infra failure (None, not CoachHold) keeps the legacy fallback — a broken
    orchestrator is not a gate judgment, and the reader should still get a brief."""
    import daily_brief_lambda as m

    _mock_brief_ai(monkeypatch, m, v2_returns={"call_training_coach_v2": None})
    result = m._run_ai_coach_pipeline(**_PIPELINE_KWARGS)

    m.ai_calls.call_training_nutrition_coach.assert_called_once()
    assert result["training_nutrition"] == _LEGACY_TN
    assert result["training_coach_v2_text"] == ""


def test_hold_on_unrelated_domain_leaves_legacy_intact(monkeypatch):
    """A hold in a domain with no legacy fallback (sleep) must not disturb the
    training/nutrition legacy path."""
    import daily_brief_lambda as m

    _mock_brief_ai(
        monkeypatch,
        m,
        v2_returns={"call_sleep_coach_v2": ai_calls.CoachHold("sleep_coach", "quality_gate")},
    )
    result = m._run_ai_coach_pipeline(**_PIPELINE_KWARGS)

    assert result["sleep_coach_v2_text"] == ""
    assert result["training_nutrition"] == _LEGACY_TN


def test_pipeline_hold_points_return_coach_hold_sentinel():
    """Source-level pin: both blocking-gate hold paths in _run_coach_v2_pipeline
    return CoachHold (not bare None), so the daily brief can tell a deliberate
    hold from an infra failure. Guards against a refactor silently reverting
    the distinction."""
    import inspect

    src = inspect.getsource(ai_calls._run_coach_v2_pipeline)
    assert 'CoachHold(coach_id, "quality_gate")' in src
    assert 'CoachHold(coach_id, "presence_ack")' in src
