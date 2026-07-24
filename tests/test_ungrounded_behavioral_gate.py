"""#1699 (epic #1687) — the ungrounded-behavioral gate must catch the "hallucinated
behavior" class the DATA-grounding gates cannot see: a same-day COMPLETED-action claim
with no corresponding log.

The 2026-07-22 defect: the mind coach's "you maintained your eating window today" with
no eating-window log. `grounded:True` passed it — there is no NUMBER to check, so the
digit/date/baseline gates are all blind to an asserted BEHAVIOR that never happened.

Crux regression: `test_eating_window_no_log_flags` replays that exact claim (no log) and
asserts a finding; `test_eating_window_with_log_is_clean` replays the SAME claim with a
real log present and asserts ZERO findings. The scoping tests (past-tense, modal, no
same-day framing, third-person) are the false-positive guard.

Stdlib-only imports — no layer-only deps at module top (keeps pytest --collect-only clean).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import grounded_generation as gg  # noqa: E402


def _types(findings):
    return sorted(f["type"] for f in findings)


def _cats(findings):
    return sorted(f["category"] for f in findings)


# ── the crux: eating-window claim, log present vs. absent ────────────────────
def test_eating_window_no_log_flags():
    text = "Great work — you maintained your eating window today and it shows."
    findings = gg.ungrounded_behavioral_findings(text, available_logs=set())
    assert _types(findings) == ["ungrounded_behavioral"], findings
    f = findings[0]
    assert f["category"] == "eating_window"
    assert "eating window" in f["claim"].lower()


def test_eating_window_with_log_is_clean():
    """The SAME claim, but a real eating-window log is present → no finding."""
    text = "Great work — you maintained your eating window today and it shows."
    findings = gg.ungrounded_behavioral_findings(text, available_logs={"eating_window"})
    assert findings == [], findings


# ── other categories ─────────────────────────────────────────────────────────
def test_steps_claim_no_log_flags():
    text = "You hit your 8,000 steps today — nice."
    assert _cats(gg.ungrounded_behavioral_findings(text, available_logs=set())) == ["steps"]
    # a real step log present → clean
    assert gg.ungrounded_behavioral_findings(text, available_logs={"steps"}) == []


def test_journaled_claim_no_log_flags():
    text = "And you journaled today, which builds the habit."
    assert _cats(gg.ungrounded_behavioral_findings(text, available_logs=set())) == ["journal"]
    assert gg.ungrounded_behavioral_findings(text, available_logs={"journal"}) == []


def test_nutrition_logged_claim_no_log_flags():
    text = "You logged every meal today — the consistency is the win."
    assert _cats(gg.ungrounded_behavioral_findings(text, available_logs=set())) == ["nutrition"]
    assert gg.ungrounded_behavioral_findings(text, available_logs={"nutrition"}) == []


def test_workout_completed_claim_no_log_flags():
    text = "You completed your workout today, and that's the streak alive."
    assert _cats(gg.ungrounded_behavioral_findings(text, available_logs=set())) == ["workout"]
    assert gg.ungrounded_behavioral_findings(text, available_logs={"workout"}) == []


def test_stayed_under_calories_claim_no_log_flags():
    text = "You stayed under your calorie target today."
    assert _cats(gg.ungrounded_behavioral_findings(text, available_logs=set())) == ["nutrition"]


# ── false-positive guard ─────────────────────────────────────────────────────
def test_past_reference_not_scoped_to_today_is_clean():
    """A prior-period claim is out of scope — available_logs is a TODAY map."""
    text = "Last week you maintained your eating window most days."
    assert gg.ungrounded_behavioral_findings(text, available_logs=set()) == []


def test_modal_advice_is_not_a_completed_claim():
    text = "If you keep your eating window today, the deficit compounds."
    assert gg.ungrounded_behavioral_findings(text, available_logs=set()) == []
    text2 = "Try to hit your steps today and see how you feel."
    assert gg.ungrounded_behavioral_findings(text2, available_logs=set()) == []


def test_no_same_day_framing_is_clean():
    """A behavioral verb with no same-day framing token isn't a checkable claim."""
    text = "You maintained your eating window and that discipline matters."
    assert gg.ungrounded_behavioral_findings(text, available_logs=set()) == []


def test_third_person_or_no_you_is_clean():
    text = "Maintaining an eating window today is the goal for many people."
    assert gg.ungrounded_behavioral_findings(text, available_logs=set()) == []


def test_available_logs_none_returns_empty():
    """None means the caller opted out — pure back-compat escape hatch."""
    text = "You maintained your eating window today."
    assert gg.ungrounded_behavioral_findings(text, available_logs=None) == []


def test_stuck_to_window_verb_not_swallowed_by_modal_to():
    """The 'stuck to' completed-action verb must survive — the modal guard excludes a
    bare 'to' precisely so this legitimate claim still flags."""
    text = "You stuck to your eating window today."
    assert _cats(gg.ungrounded_behavioral_findings(text, available_logs=set())) == ["eating_window"]


def test_dedup_repeated_claim_flags_once():
    text = "You hit your steps today. You hit your steps today, again."
    findings = gg.ungrounded_behavioral_findings(text, available_logs=set())
    assert len(findings) == 1, findings


# ── composition through grounding_findings() ─────────────────────────────────
def test_grounding_findings_composes_when_available_logs_supplied():
    text = "You maintained your eating window today."
    findings = gg.grounding_findings(text, available_logs=set())
    assert "ungrounded_behavioral" in _types(findings)


def test_grounding_findings_without_available_logs_is_pre1699_behavior():
    """A caller that supplies no available_logs gets the exact pre-#1699 behavior —
    no ungrounded_behavioral class — identical to the allowed_dates / #1691 discipline."""
    text = "You maintained your eating window today. You hit your steps today."
    findings = gg.grounding_findings(text)  # no available_logs
    assert all(f["type"] != "ungrounded_behavioral" for f in findings)


def test_grounding_findings_log_present_suppresses_in_facade():
    text = "You maintained your eating window today."
    findings = gg.grounding_findings(text, available_logs={"eating_window"})
    assert all(f["type"] != "ungrounded_behavioral" for f in findings)


# ── correction_prompt composes the new class ─────────────────────────────────
def test_correction_prompt_renders_ungrounded_behavioral():
    text = "You maintained your eating window today."
    findings = gg.ungrounded_behavioral_findings(text, available_logs=set())
    prompt = gg.correction_prompt(findings)
    assert "no record behind it" in prompt
    assert "CORRECTION REQUIRED" in prompt
