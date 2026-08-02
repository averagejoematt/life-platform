"""tests/test_self_graded_verdict_1896.py — a coach may not grade a call that never resolved.

THE DEFECT (#1896). On 2026-07-27 the nutrition coach published, live:

    "I called lunch wrong … That's a prediction miss, and I'm logging it as one"

in the same analysis that admitted "I have zero food logs. No calories, no
macros… Nothing." Every stored PREDICTION# was status=pending. The fabricated
verdict was then persisted as THREAD#2026-07-27#lunch_protein_prediction_miss —
feeding forward into later generations — and baked into the committed noscript.

WHY NOTHING CAUGHT IT. Every deterministic gate checks claims about MATTHEW —
his numbers (fabricated_numbers), his dates, his logged behavior
(ungrounded_behavioral). None checked a claim the coach makes about ITSELF.
There is no digit in "that's a prediction miss" for the number gates to check,
and the prompt actively invites the sentence
(intelligence_common.build_thread_prompt_block: 'If a prediction resolved:
explicitly call it out. "I predicted [X]. I was [right/wrong]."'). ADR-105 says
deterministic computation comes before an LLM verdict — and "has anything
resolved?" is a count, not a judgment.

STILL LIVE WHEN THIS WAS WRITTEN. The original sentence regenerated away, but on
2026-08-01 the same coach was publishing "week-one protein consistency exceeded
predictions" while /api/predictions reported all 50 records `pending`. The
softer form is the same defect, so it is pinned here verbatim.
"""

import os
import sys

_LAMBDAS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas")
if _LAMBDAS not in sys.path:
    sys.path.insert(0, _LAMBDAS)

from ai import grounded_generation as gg  # noqa: E402

ORIGINAL = "I called lunch wrong. That's a prediction miss, and I'm logging it as one. I have zero food logs."
LIVE_SOFTER = (
    "The coach notes that week-one protein consistency exceeded predictions, but cannot yet "
    "determine if adherence is system-driven (prepped meals) or cognitively-driven."
)


def _claims(text, n_evaluated=0):
    return [f["claim"] for f in gg.self_graded_verdict_findings(text, evaluated_predictions=n_evaluated)]


# ── replay: both live fabrications ──────────────────────────────────────────


def test_replays_the_2026_07_27_fabricated_verdict():
    claims = _claims(ORIGINAL)
    assert claims, "the original published verdict must be caught"
    assert any("prediction miss" in c.lower() for c in claims)


def test_replays_the_2026_08_01_softer_form():
    """An outcome-framed comparison IS a verdict — this is the form that was
    still live five days later, and the form a whole-sentence modal test missed
    (the sentence's later 'if' is unrelated to the claim)."""
    assert _claims(LIVE_SOFTER) == ["exceeded predictions"]


# ── the gate is silent when a verdict is sayable ────────────────────────────


def test_no_finding_once_any_prediction_has_been_evaluated():
    """With graded records in hand, WHICH one the coach means is semantic — and
    this gate deliberately does not answer semantic questions (ADR-105)."""
    assert gg.self_graded_verdict_findings(ORIGINAL, evaluated_predictions=1) == []
    assert gg.self_graded_verdict_findings(LIVE_SOFTER, evaluated_predictions=42) == []


def test_none_is_an_explicit_opt_out():
    """A caller that does not supply the count gets no findings — the same
    contract ungrounded_behavioral_findings uses for available_logs, so an older
    brief cannot be silently treated as 'zero evaluated'."""
    assert gg.self_graded_verdict_findings(ORIGINAL, evaluated_predictions=None) == []
    assert gg.self_graded_verdict_findings(ORIGINAL, evaluated_predictions="not-a-number") == []


# ── what must NOT flag ──────────────────────────────────────────────────────


def test_conditional_and_future_framing_are_not_verdicts():
    for text in (
        "If I was wrong, I will log it as a miss.",
        "When it resolves I will report whether my call was right.",
        "I would be wrong if protein came in under 150g.",
        "That prediction is still open — nothing has resolved yet.",
        "I expect to be right about the 2 PM dip, but the window has not closed.",
    ):
        assert _claims(text) == [], text


def test_ordinary_analysis_never_flags():
    for text in (
        "Protein intake averaged 168g across four logged days.",
        "Recovery is 96% with HRV at 67.8 ms.",
        "Food logs stopped four days ago, which blocks hypothesis testing.",
        "The prediction I logged on Monday covers this coming Friday.",
    ):
        assert _claims(text) == [], text


def test_a_verdict_after_an_unrelated_conditional_still_flags():
    """The modal test is scoped to the clause GOVERNING the phrase, so a
    conditional elsewhere in the sentence cannot launder a verdict."""
    text = "Whether or not the CGM data holds up, I called lunch wrong."
    assert _claims(text) == ["I called lunch wrong"]


# ── composition with the shared finding pipeline ────────────────────────────


def test_findings_compose_with_grounding_findings_and_correction_prompt():
    findings = gg.grounding_findings(ORIGINAL, allowed=set(), evaluated_predictions=0)
    sgv = [f for f in findings if f["type"] == "self_graded_verdict"]
    assert sgv, "grounding_findings must route the new gate when the count is supplied"
    prompt = gg.correction_prompt(sgv)
    assert "no prediction has been evaluated" in prompt
    assert "still open" in prompt


def test_grounding_findings_skips_the_gate_without_the_count():
    findings = gg.grounding_findings(ORIGINAL, allowed=set())
    assert not [f for f in findings if f["type"] == "self_graded_verdict"]


# ── the brief carries the count (the wiring #1896 was missing) ──────────────


def test_orchestrator_declares_the_evaluated_count_and_excludes_open_calls():
    """`pending`/`confirming` are OPEN calls, not verdicts — if they counted as
    evaluated, the gate would go permanently silent, which is the failure mode
    a budget-paused check taught us to test for explicitly (ADR-147 §5)."""
    import ast

    src = open(os.path.join(_LAMBDAS, "coach", "coach_narrative_orchestrator.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    statuses = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_EVALUATED_PREDICTION_STATUSES" for t in node.targets):
            statuses = {e.value for e in node.value.elts}
    assert statuses, "_EVALUATED_PREDICTION_STATUSES must exist"
    assert "pending" not in statuses and "confirming" not in statuses, "an open call is not a verdict"
    assert {"confirmed", "refuted"} <= statuses
    assert '"evaluated_prediction_count": evaluated_prediction_count' in src, "the brief must carry the count"


def test_the_gate_is_wired_blocking_not_advisory():
    """#1699's behavioral gate is advisory by design; this one must HOLD, because
    its failure mode persists — a fabricated verdict becomes a stored grade."""
    src = open(os.path.join(_LAMBDAS, "ai", "ai_calls.py"), encoding="utf-8").read()
    assert "self_graded_verdict_findings" in src, "the gate must be called in the coach pipeline"
    assert 'CoachHold(coach_id, "self_graded_verdict")' in src, "the gate must be able to hold publication"
    assert "evaluated_prediction_count" in src, "the gate must read the count from the brief"
