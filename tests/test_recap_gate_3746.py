"""tests/test_recap_gate_3746.py — nothing reaches a public grid without passing (#3746).

WHY THE GATE LANDS BEFORE THE RENDERER

The daily recap card is bound for a dedicated public Instagram account. A grid is more
findable than the site — indexed, reshared, and a single frame survives in a screenshot
long after a page could be corrected. The card's copy will carry workout titles, habit
labels, food-derived numbers and whether he journaled; each of those comes from a
partition with rules about it, and the machinery that enforces those rules already exists
and is used by the site. What did not exist was a caller for a surface not yet written.

So the gate ships first, and these tests are what "ships first" means: the send path
cannot be built until they pass.

THE FOUR FAILURE MODES, EACH WITH ITS CONTROL
  1. the vocabulary cannot be read       → refuse (not "no blocked terms today")
  2. a blocked label appears in an item  → drop THAT template, keep the day
  3. banned content anywhere in the copy → hold the whole card
  4. the card's PROSE is unsafe          → hold the whole card (#3749)
Each has a negative control, because a gate that refuses everything teaches its owner to
route around it, which is the same outcome as no gate.

Step 4 arrived with the coach line and its controls live in
`tests/test_recap_coach_line_3749.py`, beside the selection they exist to protect. This
file keeps the one assertion that belongs to the GATE rather than to that feature: that
the free-text screen is wired at all, in both directions.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from content import recap_gate  # noqa: E402

# A stand-in vocabulary. Never the real list — it lives off-repo since #2503 precisely so
# a public repo cannot carry it, and a test fixture is still the public repo.
_VOCAB = {"blocked_vices": ["Placeholder Habit"], "blocked_vice_keywords": ["placeholderterm"]}


@pytest.fixture
def clean_channel(monkeypatch):
    from privacy import content_filter_channel as cfc, privacy_guard

    monkeypatch.setattr(cfc, "load", lambda require=False: _VOCAB)
    monkeypatch.setattr(privacy_guard, "_vice_keywords", lambda: ["placeholderterm"])
    privacy_guard.reset_vocabulary_cache()
    yield
    privacy_guard.reset_vocabulary_cache()


# ── 1. The vocabulary is required ─────────────────────────────────────────────
def test_an_unreadable_vocabulary_refuses_to_send(monkeypatch):
    """'Unavailable' is not 'nothing is blocked today'. The card does not go out."""
    from privacy import content_filter_channel as cfc

    def _boom(require=False):
        if require:
            raise cfc.ContentFilterUnavailable("no channel")
        return None

    monkeypatch.setattr(cfc, "load", _boom)
    result = recap_gate.gate(["Day 8", "3 workouts"])

    assert result.verdict == recap_gate.VERDICT_UNAVAILABLE
    assert result.may_send is False
    assert "failing closed" in result.reason


def test_an_unreadable_vocabulary_over_hides_individual_items(monkeypatch):
    """The site's own posture: when it cannot judge a name, it hides it."""
    from privacy import content_filter_channel as cfc

    monkeypatch.setattr(cfc, "load", lambda require=False: None)
    assert recap_gate.item_is_blocked("Squat (Barbell)") is True


def test_a_readable_vocabulary_lets_an_ordinary_card_through(clean_channel):
    """NEGATIVE CONTROL — the gate must be capable of passing."""
    result = recap_gate.gate(["Day 8 · 2026-09-13", "Squat (Barbell) — 5×5", "8/8 tier-0 habits"])
    assert result.verdict == recap_gate.VERDICT_CLEARED
    assert result.may_send is True
    assert result.blocked_templates == []


# ── 2. A blocked item costs its template, not the day ─────────────────────────
def test_a_blocked_label_drops_only_its_own_template(clean_channel):
    blocked = recap_gate.screen_items(
        [("workout", "Squat (Barbell)"), ("habits", "Placeholder Habit"), ("nutrition", "Protein 182 g")],
        vocabulary=_VOCAB,
    )
    assert blocked == ["habits"], "one blocked label should cost one card variant, not the post"


def test_the_item_screen_is_case_insensitive_and_matches_keywords(clean_channel):
    assert recap_gate.item_is_blocked("placeholder habit", vocabulary=_VOCAB) is True
    assert recap_gate.item_is_blocked("Evening PLACEHOLDERTERM session", vocabulary=_VOCAB) is True


def test_an_ordinary_exercise_name_is_not_blocked(clean_channel):
    """NEGATIVE CONTROL — over-blocking every label is not safety, it is a dead feature."""
    for name in ("Squat (Barbell)", "Leg Extension (Machine)", "Farmers Carry", ""):
        assert recap_gate.item_is_blocked(name, vocabulary=_VOCAB) is False


def test_a_blocked_item_alone_does_not_hold_the_whole_card(clean_channel):
    result = recap_gate.gate(["Day 8", "8/8 tier-0"], items=[("habits", "Placeholder Habit")])
    assert result.verdict == recap_gate.VERDICT_CLEARED
    assert result.blocked_templates == ["habits"]


# ── 3. Banned content in the copy holds the card ──────────────────────────────
def test_banned_copy_holds_the_card(clean_channel):
    result = recap_gate.gate(["Day 8", "a placeholderterm evening"], items=[])
    assert result.verdict == recap_gate.VERDICT_HELD
    assert result.may_send is False


def test_the_caption_is_screened_with_the_card_not_after_it(clean_channel):
    """A caption is published in the same breath as the image. One unit, one gate."""
    result = recap_gate.gate(["Day 8", "Squat 5×5", "caption: another placeholderterm night"])
    assert result.verdict == recap_gate.VERDICT_HELD


# ── The record the gate leaves behind must not itself leak ────────────────────
def test_the_gate_record_never_carries_the_vocabulary(clean_channel):
    result = recap_gate.gate(["Day 8", "a placeholderterm evening"])
    payload = result.to_dict()

    assert payload["status"] == recap_gate.VERDICT_HELD
    assert "placeholderterm" not in str(payload), "the privacy record copied the blocked term into itself"
    assert payload["hit_kinds"] == ["vice"], "the record should say the KIND, not the term"


# ── What replaced the compensating control (#3749) ───────────────────────────
# This slot held `test_no_card_field_is_sourced_from_free_text`: an AST scan asserting no
# card template read journal prose or a food-item name, standing in for the semantic gate
# v1 deliberately did not run. It was retired here for two reasons, and the second is the
# more important one.
#
# The stated reason is that its premise expired exactly as it predicted it would. #3749
# put a coach line on the card, so there IS free text now, and the answer is the gate
# itself — `recap_gate` step 4, with controls in `tests/test_recap_coach_line_3749.py`
# including one that fails if the step ever runs over an empty list and reports a pass.
#
# The reason worth recording is that the control had never once run. It opened with
# `if not templates.exists(): pytest.skip(...)` against `lambdas/web/recap_templates.py`,
# and the deck shipped as `recap_layouts.py` — so from the day #3744 landed, the
# compensating control for the unwired sensitivity gate was a silent skip. It is the
# #3200 shape: a guard whose subject moved, still counted in the passing total. Replacing
# a skip with a gate is the fix; saying so here is what keeps the next author from
# writing the same shape.
def test_the_free_text_screen_is_wired_and_named(clean_channel):
    """The successor claim, held to the module rather than to a filename that can move.

    Not an AST scan for forbidden field names — that is what missed. A direct assertion
    that prose reaching the gate is judged: a planted vice term inside a sentence holds
    the card, and the same call with no prose clears. Both halves, because a screen that
    holds everything and a screen that holds nothing are equally useless.
    """
    held = recap_gate.gate(["Day 8"], free_text=["he kept the placeholderterm streak"])
    cleared = recap_gate.gate(["Day 8"], free_text=["a clean sentence about his training"])

    assert held.verdict == recap_gate.VERDICT_HELD, "prose reached a public card unjudged"
    assert cleared.verdict == recap_gate.VERDICT_CLEARED, "the screen holds everything — it will be routed around"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
