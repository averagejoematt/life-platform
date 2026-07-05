"""tests/test_margaret_editor_pass.py — #548: Margaret Calloway's red pen.

Pins the critique -> conditional revision -> optional editor's note contract:

  M1  the critique JSON parser handles raw and fenced JSON, and sanitizes/clamps
      an untrusted LLM payload into a bounded shape
  M2  needs_revision fires on a low craft score OR concrete cut/callback-debt
      findings, never on a clean high-scoring critique
  M3  apply_revision never regresses: a failed/empty/degenerate/ungrounded/
      privacy-violating revision keeps Elena's original draft
  M4  a good revision replaces the original and is reported as applied
  M5  the editor's note is gated to <=1/month (deterministic, not model judgement)
      and to the same grounding + privacy checks as any other narrative surface
  M6  splice_editors_note inserts before the closing signature, or appends
  M7  run_pass makes at most 2 model calls and is fully fail-soft
  M8  the chronicle lambda wires the pass in: budget-gated, post-ADR-104,
      pre-AI-3-validation, and the shared layer carries the new module
  M9  budget_guard pauses the editor pass at tier 1, same as coach_narrative
"""

import os
import sys

LAMBDAS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas")
sys.path.insert(0, os.path.abspath(LAMBDAS_DIR))

import margaret_editor_pass as mep  # noqa: E402
from grounded_generation import allowed_numbers as _allowed_numbers  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHRONICLE_SRC = open(os.path.join(ROOT, "lambdas/emails/wednesday_chronicle_lambda.py")).read()
BUDGET_SRC = open(os.path.join(ROOT, "lambdas/budget_guard.py")).read()
LAYER_SRC = open(os.path.join(ROOT, "deploy/build_layer.sh")).read()

SAMPLE_INSTALLMENT = (
    '"The Week the Numbers Argued With Him"\n\n'
    "[Weight: 240.1 lbs | Week Grade: avg 71 | T0 Streak: 12 days]\n\n"
    "Matthew logged every meal this week, the way he always does.\n\n"
    "---\n"
    "*Week 8 of The Measured Life*"
)


# ── M1: JSON extraction + sanitization ────────────────────────────────────────


def test_extract_json_handles_raw_and_fenced():
    assert mep._extract_json('{"craft_score": 8}') == {"craft_score": 8}
    fenced = '```json\n{"craft_score": 5}\n```'
    assert mep._extract_json(fenced) == {"craft_score": 5}
    assert mep._extract_json("not json at all") is None
    assert mep._extract_json("") is None


def test_sanitize_critique_clamps_score_and_bounds_lists():
    raw = {
        "craft_score": 99,
        "works": [f"w{i}" for i in range(10)],
        "cut_or_tighten": [{"issue": f"i{i}", "detail": "d"} for i in range(10)],
        "callback_debt": [f"c{i}" for i in range(10)],
        "editors_note": "x" * 2000,
    }
    out = mep._sanitize_critique(raw)
    assert out["craft_score"] == 10  # clamped to [0, 10]
    assert len(out["works"]) == mep.MAX_WORKS_ITEMS
    assert len(out["cut_or_tighten"]) == mep.MAX_CUT_ITEMS
    assert len(out["callback_debt"]) == mep.MAX_DUE_CALLBACKS_IN_PROMPT
    assert len(out["editors_note"]) == mep.EDITORS_NOTE_MAX_CHARS


def test_sanitize_critique_rejects_non_dict():
    assert mep._sanitize_critique(None) is None
    assert mep._sanitize_critique("a string") is None


def test_sanitize_critique_bad_score_defaults_safe():
    out = mep._sanitize_critique({"craft_score": "not a number"})
    assert out["craft_score"] == 10  # defaults to "ship as-is", never crashes


# ── M2: the revision trigger ──────────────────────────────────────────────────


def test_needs_revision_none_critique():
    assert mep.needs_revision(None) is False


def test_needs_revision_high_score_clean_critique_skips():
    critique = {"craft_score": 9, "cut_or_tighten": [], "callback_debt": []}
    assert mep.needs_revision(critique) is False


def test_needs_revision_low_score_triggers():
    critique = {"craft_score": 4, "cut_or_tighten": [], "callback_debt": []}
    assert mep.needs_revision(critique) is True


def test_needs_revision_cut_findings_trigger_even_with_high_score():
    critique = {"craft_score": 9, "cut_or_tighten": [{"issue": "padding", "detail": "d"}], "callback_debt": []}
    assert mep.needs_revision(critique) is True


def test_needs_revision_callback_debt_triggers():
    critique = {"craft_score": 9, "cut_or_tighten": [], "callback_debt": ["the bloodwork promise"]}
    assert mep.needs_revision(critique) is True


# ── M3/M4: apply_revision never regresses ─────────────────────────────────────

CLEAN_CRITIQUE = {"craft_score": 4, "works": [], "cut_or_tighten": [], "missing_addition": "", "callback_debt": [], "editors_note": ""}


def test_apply_revision_skips_when_not_needed():
    critique = {"craft_score": 9, "cut_or_tighten": [], "callback_debt": []}
    text, applied, reason = mep.apply_revision(SAMPLE_INSTALLMENT, critique, set(), revise_fn=lambda s, u: "should not be called")
    assert text == SAMPLE_INSTALLMENT
    assert applied is False
    assert reason == "no_revision_needed"


def test_apply_revision_keeps_original_on_call_failure():
    def _boom(system, user):
        raise RuntimeError("bedrock down")

    text, applied, reason = mep.apply_revision(SAMPLE_INSTALLMENT, CLEAN_CRITIQUE, set(), revise_fn=_boom)
    assert text == SAMPLE_INSTALLMENT
    assert applied is False
    assert "revise_call_failed" in reason


def test_apply_revision_keeps_original_on_empty_revision():
    text, applied, reason = mep.apply_revision(SAMPLE_INSTALLMENT, CLEAN_CRITIQUE, set(), revise_fn=lambda s, u: "   ")
    assert text == SAMPLE_INSTALLMENT
    assert applied is False
    assert reason == "empty_revision"


def test_apply_revision_rejects_degenerate_truncation():
    truncated = "A single short line."
    text, applied, reason = mep.apply_revision(SAMPLE_INSTALLMENT, CLEAN_CRITIQUE, set(), revise_fn=lambda s, u: truncated)
    assert text == SAMPLE_INSTALLMENT
    assert applied is False
    assert reason == "word_count_degenerate"


def test_apply_revision_rejects_fabricated_numbers():
    # SAMPLE_INSTALLMENT's real numbers (240.1, 71, 12, 8) form the allow-list;
    # a revision inventing a new one must be rejected, original kept.
    from grounded_generation import allowed_numbers

    allowed = allowed_numbers(SAMPLE_INSTALLMENT)
    fabricated = SAMPLE_INSTALLMENT.replace("240.1 lbs", "196.4 lbs")  # invented, not in allow-list
    text, applied, reason = mep.apply_revision(SAMPLE_INSTALLMENT, CLEAN_CRITIQUE, allowed, revise_fn=lambda s, u: fabricated)
    assert text == SAMPLE_INSTALLMENT
    assert applied is False
    assert "fabricated_numbers" in reason


def test_apply_revision_rejects_privacy_violation():
    leaking = SAMPLE_INSTALLMENT.replace("Matthew logged", "Matthew smoked marijuana and logged")
    allowed = _allowed_numbers(SAMPLE_INSTALLMENT)  # the revision keeps all the same numbers — only privacy should trip
    text, applied, reason = mep.apply_revision(SAMPLE_INSTALLMENT, CLEAN_CRITIQUE, allowed, revise_fn=lambda s, u: leaking)
    assert text == SAMPLE_INSTALLMENT
    assert applied is False
    assert reason == "privacy_violation"


def test_apply_revision_accepts_a_clean_tightened_revision():
    revised = SAMPLE_INSTALLMENT.replace("Matthew logged every meal this week, the way he always does.", "He logged every meal.")
    allowed = _allowed_numbers(SAMPLE_INSTALLMENT)  # the revision introduces no new numbers
    text, applied, reason = mep.apply_revision(SAMPLE_INSTALLMENT, CLEAN_CRITIQUE, allowed, revise_fn=lambda s, u: revised)
    assert text == revised
    assert applied is True
    assert reason == "revised"


# ── M5: the editor's note gate ────────────────────────────────────────────────


def test_editors_note_eligible_no_prior_note():
    assert mep.editors_note_eligible(None, "2026-07-05") is True


def test_editors_note_eligible_respects_min_days():
    assert mep.editors_note_eligible("2026-07-01", "2026-07-05") is False  # 4 days
    assert mep.editors_note_eligible("2026-06-01", "2026-07-05") is True  # 34 days


def test_editors_note_eligible_bad_date_fails_open():
    assert mep.editors_note_eligible("not-a-date", "2026-07-05") is True


def test_extract_editors_note_requires_eligibility():
    critique = {"editors_note": "A note about craft."}
    assert mep.extract_editors_note(critique, note_eligible=False, allowed_numbers=set()) is None


def test_extract_editors_note_empty_string_is_none():
    critique = {"editors_note": ""}
    assert mep.extract_editors_note(critique, note_eligible=True, allowed_numbers=set()) is None


def test_extract_editors_note_grounding_gate():
    critique = {"editors_note": "This week the reader count climbed past 58,204."}
    assert mep.extract_editors_note(critique, note_eligible=True, allowed_numbers=set()) is None


def test_extract_editors_note_privacy_gate():
    critique = {"editors_note": "Matthew's marijuana use came up in the draft and I cut it."}
    assert mep.extract_editors_note(critique, note_eligible=True, allowed_numbers=set()) is None


def test_extract_editors_note_clean_note_passes():
    critique = {"editors_note": "This week's draft buried its own lede for three paragraphs before finding it."}
    note = mep.extract_editors_note(critique, note_eligible=True, allowed_numbers=set())
    assert note == critique["editors_note"]


# ── M6: splicing ──────────────────────────────────────────────────────────────


def test_splice_editors_note_before_signature():
    out = mep.splice_editors_note(SAMPLE_INSTALLMENT, "A note.")
    assert "> **Editor's note — Margaret Calloway:** A note." in out
    # inserted BEFORE the closing signature, not after
    assert out.index("Editor's note") < out.index("*Week 8 of The Measured Life*")


def test_splice_editors_note_appends_when_no_signature_found():
    text = "No signature line here at all."
    out = mep.splice_editors_note(text, "A note.")
    assert out.startswith(text)
    assert "Editor's note" in out


def test_splice_editors_note_noop_on_empty_note():
    assert mep.splice_editors_note(SAMPLE_INSTALLMENT, "") == SAMPLE_INSTALLMENT
    assert mep.splice_editors_note(SAMPLE_INSTALLMENT, None) == SAMPLE_INSTALLMENT


# ── M7: run_pass call budget + fail-soft ──────────────────────────────────────


def test_run_pass_no_critique_is_untouched_and_makes_one_call():
    calls = {"critique": 0, "revise": 0}

    def _critique_fn(system, user):
        calls["critique"] += 1
        return "not valid json"

    def _revise_fn(system, user):
        calls["revise"] += 1
        return "should not be reached"

    out = mep.run_pass(SAMPLE_INSTALLMENT, 8, [], set(), True, mep.build_narrator(None), _critique_fn, _revise_fn)
    assert out["final_text"] == SAMPLE_INSTALLMENT
    assert out["critique"] is None
    assert calls == {"critique": 1, "revise": 0}


def test_run_pass_clean_critique_skips_revision_makes_one_call():
    calls = {"critique": 0, "revise": 0}
    critique_json = '{"craft_score": 9, "works": ["good opening"], "cut_or_tighten": [], "callback_debt": [], "editors_note": ""}'

    def _critique_fn(system, user):
        calls["critique"] += 1
        return critique_json

    def _revise_fn(system, user):
        calls["revise"] += 1
        return "unused"

    out = mep.run_pass(SAMPLE_INSTALLMENT, 8, [], set(), False, mep.build_narrator(None), _critique_fn, _revise_fn)
    assert out["final_text"] == SAMPLE_INSTALLMENT
    assert out["revised"] is False
    assert calls == {"critique": 1, "revise": 0}


def test_run_pass_low_score_triggers_exactly_two_calls_and_applies_revision():
    calls = {"critique": 0, "revise": 0}
    critique_json = (
        '{"craft_score": 4, "works": [], "cut_or_tighten": '
        '[{"issue": "padding", "detail": "the second paragraph repeats the first"}], '
        '"callback_debt": [], "editors_note": ""}'
    )
    revised = SAMPLE_INSTALLMENT.replace("Matthew logged every meal this week, the way he always does.", "He logged every meal.")
    allowed = _allowed_numbers(SAMPLE_INSTALLMENT)

    def _critique_fn(system, user):
        calls["critique"] += 1
        return critique_json

    def _revise_fn(system, user):
        calls["revise"] += 1
        return revised

    out = mep.run_pass(
        SAMPLE_INSTALLMENT, 8, ["the bloodwork follow-up"], allowed, False, mep.build_narrator(None), _critique_fn, _revise_fn
    )
    assert calls == {"critique": 1, "revise": 1}
    assert out["revised"] is True
    assert out["final_text"] == revised


def test_run_pass_due_callbacks_flow_into_critique_prompt():
    seen = {}

    def _critique_fn(system, user):
        seen["user"] = user
        return '{"craft_score": 9, "cut_or_tighten": [], "callback_debt": [], "editors_note": ""}'

    mep.run_pass(
        SAMPLE_INSTALLMENT,
        8,
        ["the bloodwork follow-up he promised"],
        set(),
        False,
        mep.build_narrator(None),
        _critique_fn,
        lambda s, u: "",
    )
    assert "the bloodwork follow-up he promised" in seen["user"]


# ── narrator building ──────────────────────────────────────────────────────


def test_build_narrator_fallback_when_no_config():
    narrator = mep.build_narrator(None)
    assert narrator["name"] == "Margaret Calloway"
    assert "voice" in narrator


def test_build_narrator_uses_board_config_when_present():
    config = {
        "members": {
            "margaret_calloway": {
                "name": "Margaret Calloway",
                "title": "Senior Editor — Longform & Narrative",
                "active": True,
                "voice": {"tone": "Exacting", "style": "Cuts hard."},
                "principles": ["Every piece needs a spine."],
                "relationship_to_matthew": "She edits Elena's work.",
                "focus_areas": [],
                "features": {},
            }
        }
    }
    narrator = mep.build_narrator(config)
    assert narrator["name"] == "Margaret Calloway"
    assert narrator["voice"]["tone"] == "Exacting"


def test_critique_prompt_carries_privacy_rules():
    system = mep.build_critique_system_prompt(mep.build_narrator(None))
    assert "marijuana" in system.lower()
    assert "gene name" in system.lower() or "rsid" in system.lower()


# ── M8: the chronicle lambda wires the pass in ────────────────────────────────


def test_chronicle_invokes_margaret_pass_after_adr104_before_ai3():
    assert "_run_margaret_edit_pass(" in CHRONICLE_SRC
    adr104_idx = CHRONICLE_SRC.index("chronicle grounding gate error (fail-open)")
    margaret_call_idx = CHRONICLE_SRC.index("raw_installment = _run_margaret_edit_pass(raw_installment")
    ai3_idx = CHRONICLE_SRC.index("AI-3: Validate output before rendering")
    assert adr104_idx < margaret_call_idx < ai3_idx


def test_chronicle_margaret_pass_is_budget_gated():
    block = CHRONICLE_SRC[CHRONICLE_SRC.index("def _run_margaret_edit_pass") : CHRONICLE_SRC.index("def lambda_handler")]
    assert 'allow("chronicle_editor")' in block


def test_chronicle_uses_haiku_for_margaret_not_sonnet():
    block = CHRONICLE_SRC[CHRONICLE_SRC.index("def _margaret_haiku_call") : CHRONICLE_SRC.index("def _run_margaret_edit_pass")]
    assert "AI_MODEL_HAIKU" in block


def test_has_board_detection_excludes_editors_note():
    idx = CHRONICLE_SRC.index("Detect Board interview")
    block = CHRONICLE_SRC[idx : idx + 400]
    assert "editor's note" in block.lower()


def test_layer_carries_the_new_module():
    assert "margaret_editor_pass.py" in LAYER_SRC


# ── M9: budget_guard tier-1 pause ─────────────────────────────────────────────


def test_budget_guard_pauses_chronicle_editor_at_tier_one():
    assert '"chronicle_editor": 1' in BUDGET_SRC
