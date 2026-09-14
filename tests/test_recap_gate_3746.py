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

THE THREE FAILURE MODES, EACH WITH ITS CONTROL
  1. the vocabulary cannot be read       → refuse (not "no blocked terms today")
  2. a blocked label appears in an item  → drop THAT template, keep the day
  3. banned content anywhere in the copy → hold the whole card
Each has a negative control, because a gate that refuses everything teaches its owner to
route around it, which is the same outcome as no gate.
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


# ── The compensating control for not running the semantic classifier ─────────
def test_no_card_field_is_sourced_from_free_text(clean_channel):
    """v1 draws numbers and fixed labels only — which is WHY the sensitivity classifier is
    not wired (with no classifier it holds everything, and its deterministic layer is
    already step 3). If a template ever draws journal prose or a food-item name, this
    test is the thing that should stop it and send the author back to #3749.
    """
    import ast

    templates = REPO / "lambdas" / "web" / "recap_templates.py"
    if not templates.exists():
        pytest.skip("the template deck has not landed yet (#3744/#3745) — the gate ships first, by design")

    src = templates.read_text()
    tree = ast.parse(src)
    forbidden = {"note_raw", "body", "content", "food_name", "journal_text", "entry_text"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in forbidden:
            raise AssertionError(
                f"a card template reads {node.value!r} — free text on a public card needs the semantic gate (#3749), "
                "which v1 deliberately does not run"
            )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
