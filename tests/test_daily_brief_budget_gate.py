"""tests/test_daily_brief_budget_gate.py — #810 / R22-COST-04.

Proves the daily brief's AI generation is actually WIRED to the budget ladder,
not just coincidentally caught by bedrock_client's BudgetExceeded backstop
being swallowed by a generic `except Exception`. Two things are pinned:

  1. `_daily_brief_ai_allowed()` calls budget_guard.allow("daily_brief_ai")
     explicitly, and fails OPEN (never blocks AI) if budget_guard itself is
     unavailable or raises — the same convention every other gated feature
     (coach_narrative_orchestrator, state_of_matthew_lambda) follows.
  2. `_run_ai_coach_pipeline` — the extracted body of the brief's `if
     api_key:` branch — actually SKIPS every ai_calls.* call when the gate
     denies, and attempts them when it allows. This is the "wired" contract:
     a denial must produce zero calls into ai_calls/bedrock, not just an
     exception caught somewhere downstream.

No AWS credentials or network access required: budget_guard.allow, the
ai_calls coach functions, and the ensemble-digest boto3 invoke are all
monkeypatched.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

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

import budget_guard  # noqa: E402

_PIPELINE_KWARGS = dict(
    data={"date": "2026-07-06", "journal_entries": [{"text": "quiet day"}]},
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
_MAIN_AI_FN_NAMES = [
    "call_board_of_directors",
    "call_training_nutrition_coach",
    "call_journal_coach",
    "call_tldr_and_guidance",
]


def _mock_ai_calls(monkeypatch, m):
    """Replace every ai_calls.* function the pipeline can call with a Mock, so
    a call is unambiguous evidence of an attempted AI invocation."""
    for name in _COACH_FN_NAMES + _MAIN_AI_FN_NAMES + ["daily_brief_shared_system"]:
        monkeypatch.setattr(m.ai_calls, name, MagicMock(return_value="mock text"))
    # Prevent any real network/AWS call from the ensemble-digest kick-off.
    monkeypatch.setattr(m, "boto3", MagicMock())


# ══════════════════════════════════════════════════════════════════════════════
# _daily_brief_ai_allowed — the gate function itself
# ══════════════════════════════════════════════════════════════════════════════


def test_daily_brief_ai_allowed_true_at_tier_0(monkeypatch):
    import daily_brief_lambda as m

    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    assert m._daily_brief_ai_allowed() is True


def test_daily_brief_ai_allowed_false_at_hard_stop_tier_3(monkeypatch):
    import daily_brief_lambda as m

    monkeypatch.setattr(budget_guard, "current_tier", lambda: 3)
    assert m._daily_brief_ai_allowed() is False


def test_daily_brief_ai_allowed_still_true_at_tier_2(monkeypatch):
    """ADR-125 Band 3: daily_brief_ai is one of the two irreducible reader
    promises — it must survive tier 2 (reader-narrative pause) and only pause
    at the tier-3 hard stop."""
    import daily_brief_lambda as m

    monkeypatch.setattr(budget_guard, "current_tier", lambda: 2)
    assert m._daily_brief_ai_allowed() is True


def test_daily_brief_ai_allowed_fails_open_on_guard_error(monkeypatch):
    """A budget_guard exception (SSM blip, import error) must never take the
    brief's AI down — same fail-open convention as budget_guard.current_tier
    itself."""
    import daily_brief_lambda as m

    def _boom():
        raise RuntimeError("SSM unavailable")

    monkeypatch.setattr(budget_guard, "current_tier", _boom)
    assert m._daily_brief_ai_allowed() is True


# ══════════════════════════════════════════════════════════════════════════════
# _run_ai_coach_pipeline — the wiring: denied ⇒ zero ai_calls invocations
# ══════════════════════════════════════════════════════════════════════════════


def test_pipeline_takes_data_only_path_when_budget_denies(monkeypatch):
    import daily_brief_lambda as m

    _mock_ai_calls(monkeypatch, m)
    monkeypatch.setattr(m, "_daily_brief_ai_allowed", lambda: False)

    result = m._run_ai_coach_pipeline(api_key="fake-anthropic-key", **_PIPELINE_KWARGS)

    # The contract: at tier 3, NOT ONE ai_calls.* function is invoked — this is
    # the thing the issue says was previously unenforced (only a coincidental
    # BudgetExceeded catch deep inside a call that never even fires here).
    for name in _COACH_FN_NAMES + _MAIN_AI_FN_NAMES:
        getattr(m.ai_calls, name).assert_not_called()

    assert result == {
        "bod_insight": "",
        "training_nutrition": {},
        "journal_coach_text": "",
        "tldr_guidance": {},
        "sleep_coach_v2_text": "",
        "nutrition_coach_v2_text": "",
        "training_coach_v2_text": "",
        "mind_coach_v2_text": "",
        "physical_coach_v2_text": "",
        "glucose_coach_v2_text": "",
        "labs_coach_v2_text": "",
        "explorer_coach_v2_text": "",
    }


def test_pipeline_skips_gate_check_entirely_without_an_api_key(monkeypatch):
    """No api_key ⇒ short-circuits before even asking the budget guard (matches
    the pre-existing `if api_key:` behavior — no key, no AI, regardless of tier)."""
    import daily_brief_lambda as m

    _mock_ai_calls(monkeypatch, m)
    gate = MagicMock(return_value=True)
    monkeypatch.setattr(m, "_daily_brief_ai_allowed", gate)

    result = m._run_ai_coach_pipeline(api_key=None, **_PIPELINE_KWARGS)

    gate.assert_not_called()
    for name in _COACH_FN_NAMES + _MAIN_AI_FN_NAMES:
        getattr(m.ai_calls, name).assert_not_called()
    assert result["bod_insight"] == ""


def test_pipeline_attempts_ai_path_when_budget_allows(monkeypatch):
    import daily_brief_lambda as m

    _mock_ai_calls(monkeypatch, m)
    monkeypatch.setattr(m, "_daily_brief_ai_allowed", lambda: True)

    result = m._run_ai_coach_pipeline(api_key="fake-anthropic-key", **_PIPELINE_KWARGS)

    for name in _COACH_FN_NAMES + _MAIN_AI_FN_NAMES:
        getattr(m.ai_calls, name).assert_called_once()

    assert result["bod_insight"] == "mock text"
    assert result["sleep_coach_v2_text"] == "mock text"


def test_pipeline_journal_coach_only_called_with_journal_entries(monkeypatch):
    """Sanity check that the extraction preserved the pre-existing
    `if data.get("journal_entries"):` guard around the journal coach call."""
    import daily_brief_lambda as m

    _mock_ai_calls(monkeypatch, m)
    monkeypatch.setattr(m, "_daily_brief_ai_allowed", lambda: True)

    kwargs = dict(_PIPELINE_KWARGS)
    kwargs["data"] = {"date": "2026-07-06"}  # no journal_entries key
    m._run_ai_coach_pipeline(api_key="fake-anthropic-key", **kwargs)
    m.ai_calls.call_journal_coach.assert_not_called()


@pytest.mark.parametrize("tier", [0, 1, 2])
def test_end_to_end_gate_allows_below_hard_stop(monkeypatch, tier):
    """Full wiring, real budget_guard.allow (not the monkeypatched shortcut):
    tiers 0-2 must still run the brief's AI (Band 3 outlives everything else)."""
    import daily_brief_lambda as m

    _mock_ai_calls(monkeypatch, m)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: tier)

    result = m._run_ai_coach_pipeline(api_key="fake-anthropic-key", **_PIPELINE_KWARGS)
    assert result["bod_insight"] == "mock text"
    m.ai_calls.call_board_of_directors.assert_called_once()


def test_end_to_end_gate_denies_at_hard_stop_tier_3(monkeypatch):
    """Full wiring at the real hard-stop tier: zero ai_calls invocations."""
    import daily_brief_lambda as m

    _mock_ai_calls(monkeypatch, m)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 3)

    result = m._run_ai_coach_pipeline(api_key="fake-anthropic-key", **_PIPELINE_KWARGS)
    for name in _COACH_FN_NAMES + _MAIN_AI_FN_NAMES:
        getattr(m.ai_calls, name).assert_not_called()
    assert result["tldr_guidance"] == {}
