"""#3202 — stale_phase is a SELF-LOCATION check, not a "Day N" token ban.

Two reader-facing coach narratives (nutrition_coach, mind_coach) were held dark every
cycle at `score=28 / number_grounding=ungrounded`, and the corrective-rewrite loop
reproduced its own verdict: attempt 2 failed identically to attempt 1.

The discriminating experiment (2026-08-26 17:00Z, the REAL held drafts — retained by
`ai_calls._retain_coach_brief_flag` at DDB `EVALRET#coach_brief`, replayed offline
through `coach_quality_gate._number_grounding_report`) returned:

    mind_coach      attempt 1  ->  ['stale_phase']   "We're at day 9"        (Day 10)
    mind_coach      attempt 2  ->  ['stale_phase']   "...than it did at Day 1"
    nutrition_coach attempt 2  ->  ['stale_phase']   "...silent since Day 1"

Not `fabricated_number`. Attempt 1 is a TRUE positive — the draft mis-located itself by
a day. Attempts 2 are FALSE positives: one names the CORRECT day ("you're at Day 10")
and is held for the comparative clause that follows it; the other uses "since Day 1" as
a span anchor. Neither is fixable, which is the non-convergence: the correction note
says "use Day 10", the model complies, and any sentence naming an earlier day re-trips
the gate.

The narrative text below is deliberately reduced to the grammatical FORM that carries
the finding — this repo is public and the real drafts are personal.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from ai.baseline_freshness import baseline_freshness_findings  # noqa: E402

GENESIS = "2026-08-17"
GEN_DATE = "2026-08-26"  # Day 10


def _phase_findings(text, generation_date_iso=GEN_DATE):
    return [
        f
        for f in baseline_freshness_findings(text, generation_date_iso=generation_date_iso, start_date_iso=GENESIS, baseline_lbs=None)
        if f["type"] == "stale_phase"
    ]


# ── the TRUE positive must survive (this is the whole point of the gate) ──────
def test_mislocated_day_still_fires():
    """mind_coach attempt 1's form: the narrative says it is on a day it is not."""
    findings = _phase_findings("We're at day 9. The novelty window has closed.")
    assert len(findings) == 1, findings
    assert findings[0]["claimed_day"] == 9
    assert findings[0]["expected_day"] == 10


def test_mislocated_day_fires_even_next_to_a_span_anchor_elsewhere():
    """A reference anchor somewhere else in the text does not license a wrong claim."""
    findings = _phase_findings("Nothing since Day 1. We're at day 9 now.")
    assert [f["claimed_day"] for f in findings] == [9], findings


def test_pre_start_day_claim_still_fires():
    """The #1691 incident: any "Day N" before genesis is a mis-location, and the
    correct-day exclusion is inert pre-start (there is no correct day to cite)."""
    findings = _phase_findings("This is Day 1 of the experiment.", generation_date_iso="2026-08-15")
    assert len(findings) == 1, findings
    assert "pre-start" in findings[0]["detail"]


def test_pre_start_reference_anchor_still_fires_when_the_text_only_mislocates():
    findings = _phase_findings("Day 3 of the experiment and going strong.", generation_date_iso="2026-08-15")
    assert [f["claimed_day"] for f in findings] == [3], findings


# ── the FALSE positives that held two coaches dark every cycle ────────────────
def test_correct_day_cited_makes_an_EARLIER_day_token_a_back_reference():
    """mind_coach attempt 2's form. It located itself CORRECTLY ("Day 10") and was
    held for the comparative clause naming an EARLIER day.

    Note this case needs exclusion 1 specifically: the span-anchor rule does not
    reach it, because "it did at " sits between "than" and the token."""
    text = "You're at Day 10. That distinction matters more at Day 10 than it did at Day 1."
    assert _phase_findings(text) == []


def test_correct_day_cited_does_NOT_clear_a_wrong_FUTURE_day():
    """The blind spot in the first cut of exclusion 1: it cleared the ENTIRE text as
    soon as the correct day appeared anywhere, so a self-contradicting narrative that
    ALSO claimed a future day passed silently — a real #1691 mis-location. Nothing in
    a narrative can refer FORWARD to a day that has not happened, so a future token is
    never a back-reference. Measured before the fix: this returned [] (clean)."""
    text = "You're at Day 10 of the experiment. We're now on Day 12 and the trend holds."
    assert [f["claimed_day"] for f in _phase_findings(text)] == [12], _phase_findings(text)


def test_wrong_future_day_alone_still_fires_the_control():
    """The same claim with no correct day present — exclusion 1 is off entirely and
    the finding was never in doubt. Pinned so the case above cannot pass for the
    wrong reason (e.g. the gate silently disarming)."""
    assert [f["claimed_day"] for f in _phase_findings("We're now on Day 12 and the trend holds.")] == [12]


def test_backward_mislocation_beside_the_correct_day_is_KNOWN_UNCOVERED():
    """Stated, not papered over: "You're at Day 10 … we're on Day 3" is cleared,
    because it is genuinely ambiguous with the back-reference exclusion 1 exists to
    permit ("at Day 3 you were still ramping"). The deterministic layer cannot
    separate those without reading intent, and ADR-105 sends a semantic question to
    the judge rather than a regex. This test documents the hole so a future change
    that closes it has to delete this pin deliberately."""
    text = "You're at Day 10 of the experiment. We're now on Day 3 and the trend holds."
    assert _phase_findings(text) == []
    # …and the same claim WITHOUT the correct day present is still caught.
    assert [f["claimed_day"] for f in _phase_findings("We're now on Day 3 and the trend holds.")] == [3]


def test_span_anchor_day_reference_is_not_a_self_location_claim():
    """nutrition_coach attempt 2's form: "since Day 1" anchors a span, and English
    cannot state a present location after it ("we are since Day 1" is not a sentence)."""
    assert _phase_findings("The food layer has been silent since Day 1.") == []


def test_other_reference_anchors():
    for text in (
        "Recovery is up compared to Day 2.",
        "That is a real change from Day 3.",
        "Back on Day 4 you were still ramping.",
        "Protein held better than Day 5.",
        "Somewhere between Day 2 and the weekend it slipped.",
    ):
        assert _phase_findings(text) == [], text


def test_self_location_prepositions_are_not_treated_as_references():
    """ "on"/"at" are exactly how a self-location IS stated — excluding them would
    disarm the gate rather than scope it."""
    assert [f["claimed_day"] for f in _phase_findings("We're on Day 6 and the pattern is holding.")] == [6]
    assert [f["claimed_day"] for f in _phase_findings("At Day 4 the routine should be forming.")] == [4]


# ── the gate/generation asymmetry the finding types exposed ───────────────────
def test_generation_and_quality_gate_arm_the_same_freshness_classes():
    """coach_quality_gate._number_grounding_report's docstring says the generation
    gate and the quality gate "cannot disagree by construction". They did: only the
    quality gate spread **cycle_gate_params, so a stale_phase finding reached the
    BLOCKING gate having never been offered a corrective rewrite. Pinned at the
    source, because the disagreement is a wiring fact, not a value."""
    import re

    here = os.path.dirname(__file__)
    src = open(os.path.join(here, "..", "lambdas", "ai", "ai_calls.py")).read()
    # The COACH-V2 pipeline's own loop — ai_calls defines a second `_findings_fn`
    # for the legacy surface, which is armed separately (see grounding_wiring.py).
    v2 = src[src.index("def _run_coach_v2_pipeline") :]
    body = v2[v2.index("def _findings_fn(_t):") :][:400]
    assert "_fresh_kwargs" in body, "coach-v2 corrective-rewrite loop no longer arms the cycle-freshness classes (#3202)"
    gate = open(os.path.join(here, "..", "lambdas", "coach", "coach_quality_gate.py")).read()
    assert re.search(r"grounding_findings\(.*cycle_gate_params", gate, re.S), "quality gate no longer arms cycle_gate_params"


# ── the observability half ────────────────────────────────────────────────────
def test_complete_log_names_the_finding_type_and_detail():
    from coach import coach_quality_gate as qg

    summary = qg._grounding_findings_summary(
        {
            "status": "measured",
            "verdict": "ungrounded",
            "findings": [{"type": "stale_phase", "detail": 'the narrative cites "Day 1", but generation date 2026-08-26 is Day 10'}],
        }
    )
    assert "stale_phase" in summary and "Day 1" in summary


def test_clean_verdict_leaves_the_complete_line_unchanged():
    from coach import coach_quality_gate as qg

    assert qg._grounding_findings_summary({"status": "measured", "verdict": "clean", "findings": []}) == ""


def test_absent_grounding_context_is_named_not_silent():
    from coach import coach_quality_gate as qg

    summary = qg._grounding_findings_summary({"status": "no_grounding_context", "verdict": None, "detail": "caller supplied no allow-list"})
    assert "no_grounding_context" in summary


def test_non_numeric_findings_are_not_labelled_ungrounded_number():
    """The correction note told a coach its PHASE FRAMING was an ungrounded NUMBER,
    which sent every rewrite hunting a figure that was never wrong."""
    from coach import coach_quality_gate as qg

    result = qg._apply_number_grounding_verdict(
        {"passed": True, "suggestions": []},
        {
            "status": "measured",
            "findings": [{"type": "stale_phase", "detail": "cites Day 1"}, {"type": "fabricated_number", "detail": "326.3"}],
        },
    )
    assert result["passed"] is False  # #2573 / ADR-104 — unchanged, the judge cannot overrule
    joined = "\n".join(result["suggestions"])
    assert "Grounding violation (stale_phase)" in joined
    assert "Ungrounded number (fabricated_number)" in joined


def test_retention_carries_the_grounding_findings_and_allowlist(monkeypatch):
    """The class that actually held two coaches dark was the one `_retain_coach_brief_flag`
    dropped: the retained record had the draft text and not the reason. That is why this
    root-cause dig needed the drafts reconstructed and the grounder re-run offline."""
    from ai import ai_calls
    from experiment import eval_retention

    captured = {}

    def _fake_retain(surface, verdict, **kw):
        captured.update(kw)
        captured["surface"] = surface
        return True

    monkeypatch.setattr(eval_retention, "retain", _fake_retain)
    ai_calls._retain_coach_brief_flag(
        "nutrition_coach",
        "flagged_dropped",
        "draft",
        "final",
        {
            "score": 28,
            "number_grounding": {
                "status": "measured",
                "verdict": "ungrounded",
                "findings": [{"type": "stale_phase", "detail": 'cites "Day 1"'}],
            },
        },
        {"grounding_allowlist": [72.0, 45.4], "authoritative_facts": {"recovery_pct": 72}},
    )

    assert captured["surface"] == "coach_brief"
    assert {"type": "stale_phase", "detail": 'cites "Day 1"'} in captured["findings"]
    assert captured["allowed"] == {72.0, 45.4}
    assert captured["facts"] == {"recovery_pct": 72}
