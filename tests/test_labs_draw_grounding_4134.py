"""#4134 — a served labs-coach narrative arranged a lab draw that is not on record.

The 2026-09-23 nightly FAILED `coach_labs:truth` on the stored labs-coach narrative
(`COACH#labs_coach / OUTPUT#2026-09-23#daily_brief_labs`): "Schedule the draw. Lock the
training calendar with your physical coach so the 48-hour window is protected." The owner had
ruled the day before (#4052) that no draw is booked. Two fixes, both proven here:

  1. GROUNDING — the labs prompt frame renders the owner's lab plan from its one home,
     `owner_redlines.REDLINES["medical_cover"]`, so the model is told no draw is booked.
  2. REFUSAL — the coach quality gate refuses a labs-coach draft that arranges a draw, via
     the nightly's own detector (`health.labs_draw_claims`), on the existing
     regenerate-or-hold path. A sentence naming the NEXT panel stays sayable.
"""

import os
import sys

import pytest

LAMBDAS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

from health import labs_draw_claims  # noqa: E402
from intelligence import labs_facts  # noqa: E402
from training import owner_redlines  # noqa: E402

# The served specimen, verbatim from the 2026-09-23 stored narrative.
SPECIMEN = (
    "Until the next draw results, every positive wearable reading is a hypothesis, not a finding.\n\n"
    "Schedule the draw. Lock the training calendar with your physical coach so the 48-hour window is protected. "
    "Collect the symptom baseline today — it takes five minutes."
)
HONEST = "Every positive wearable reading is a hypothesis until a panel confirms it. Whether to order the next panel is your call."


# ── 1. grounding: the owner's plan reaches the prompt frame ─────────────────────────────
def test_the_labs_frame_carries_the_owners_waived_baseline_ruling():
    cover = owner_redlines.REDLINES["medical_cover"]
    frame = labs_facts.labs_prompt_block({"draw_date": "2026-04-03", "total_draws": 8})
    assert "NO lab draw is booked" in frame
    assert cover["week0_reference"]["labs"]["date"] in frame
    assert cover["week0_reference"]["next_scan"]["approx_date"] in frame
    assert "not a blood draw" in frame


def test_the_plan_sentence_is_derived_not_restated(monkeypatch):
    """Mutation: un-waive the baseline and the sentence disappears; move the scan and it moves."""
    cover = dict(owner_redlines.REDLINES["medical_cover"])
    cover["week0_reference"] = {**cover["week0_reference"], "next_scan": {"week": 9, "approx_date": "2026-11-08"}}
    monkeypatch.setitem(owner_redlines.REDLINES, "medical_cover", cover)
    assert "~2026-11-08" in labs_facts.owner_draw_plan_block()

    monkeypatch.setitem(owner_redlines.REDLINES, "medical_cover", {**cover, "baseline_status": "booked for 2026-10-01"})
    assert labs_facts.owner_draw_plan_block() == ""


def test_an_unreadable_ruling_renders_nothing_rather_than_a_guess(monkeypatch):
    monkeypatch.setitem(owner_redlines.REDLINES, "medical_cover", {})
    assert labs_facts.owner_draw_plan_block() == ""
    assert "EVERY draw named above is in the PAST" in labs_facts.labs_prompt_block({"draw_date": "2026-04-03"})


# ── 2. refusal: the gate holds the draft the nightly failed ─────────────────────────────
@pytest.fixture()
def gate(monkeypatch):
    from coach import coach_quality_gate as g

    # The judge PASSES the draft at 95 — the deterministic finding must block regardless.
    monkeypatch.setattr(
        g,
        "_call_haiku",
        lambda **k: {"passed": True, "score": 95, "voice_distinctiveness_score": 90, "suggestions": []},
    )
    monkeypatch.setattr(g, "_query_begins_with", lambda *a, **k: [])
    return g


def _event(text, coach_id="labs_coach"):
    return {"coach_id": coach_id, "output_text": text, "voice_spec": {"persona": {"name": "t"}}, "skip_cross_coach": True}


def test_the_gate_refuses_the_served_specimen(gate):
    report = gate.lambda_handler(_event(SPECIMEN), None)
    assert report["passed"] is False, report
    assert [f["type"] for f in report["number_grounding"]["labs_draw_findings"]] == ["past_draw_scheduling"]
    assert any("past_draw_scheduling" in s and "Schedule the draw" in s for s in report["suggestions"]), report["suggestions"]


def test_naming_the_next_panel_stays_sayable(gate):
    report = gate.lambda_handler(_event(HONEST), None)
    assert report["passed"] is True, report
    assert report["number_grounding"]["labs_draw_findings"] == []


def test_only_the_labs_coach_is_held_to_it(gate):
    assert gate.lambda_handler(_event(SPECIMEN, coach_id="sleep_coach"), None)["passed"] is True


def test_the_refusal_rides_the_regenerate_or_hold_path(gate):
    """The finding reaches `suggestions`, which `ai_calls._quality_gate_correction_note` walks —
    so the corrective rewrite is told exactly which sentence to drop."""
    report = gate.lambda_handler(_event(SPECIMEN), None)
    from ai import ai_calls

    note = ai_calls._quality_gate_correction_note(report)
    assert "Schedule the draw" in note


# ── one detector, two consumers ──────────────────────────────────────────────────────────
def test_the_nightly_and_the_gate_share_one_detector():
    from operational import qa_check_coach_labs

    assert qa_check_coach_labs._schedules_a_past_draw is labs_draw_claims.schedules_a_past_draw
    assert labs_draw_claims.schedules_a_past_draw(SPECIMEN) == ["Schedule the draw"]
