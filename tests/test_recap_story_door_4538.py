"""tests/test_recap_story_door_4538.py — the recap CARDS face the shared story door (#4538).

The chronicle handler, the chronicle recap and the Panel each call ``story_checks.reader_surface`` at their own
chokepoint (tests/test_story_desk*.py). The cards held ADR-157 point 5 with a literal rule that lived only in a test;
the card publish gate (``recap_gate.gate``) now calls the same check in its ``constructed`` mode, so the cards cannot
publish what the other three paths would hold. Fixtures: an attempt-count caption and an off-record caption, each
held; ordinary card copy passes; mutation control: with the shared check removed, the same fixtures publish.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from content import recap_gate, story_checks  # noqa: E402

_VOCAB = {"blocked_vices": ["Placeholder Habit"], "blocked_vice_keywords": ["placeholderterm"]}
CLEAN = ["DAY 8  ·  THE EXPERIMENT", "proof, not promises", "Day 9 tomorrow  ·  week 2 closes in 6 days", "most moved so far"]
COUNTED = ["Day 7 · attempt #17", "16 lost · 0 kept", "the Fifteenth Reset", "most moved this attempt"]
OFF_RECORD = ["a hard night after his wife left", "his boss moved the meeting"]


@pytest.fixture(autouse=True)
def channel(monkeypatch):
    from privacy import content_filter_channel as cfc, privacy_guard

    monkeypatch.setattr(cfc, "load", lambda require=False: _VOCAB)
    monkeypatch.setattr(privacy_guard, "_vice_keywords", lambda: ["placeholderterm"])
    privacy_guard.reset_vocabulary_cache()
    yield
    privacy_guard.reset_vocabulary_cache()


def test_ordinary_card_copy_passes():
    assert recap_gate.gate(CLEAN).verdict == recap_gate.VERDICT_CLEARED


@pytest.mark.parametrize("held", [COUNTED, OFF_RECORD], ids=["attempt-count", "off-record"])
def test_a_count_or_an_off_record_specific_holds_the_card(held):
    """One test per class, iterating every fixture and naming each offender."""
    leaked = [t for t in held if recap_gate.gate([*CLEAN, t]).may_send]
    assert leaked == []
    assert recap_gate.gate([*CLEAN, held[0]]).to_dict()["hit_kinds"] == ["story-door"]


def test_the_caption_is_screened_too():
    assert recap_gate.gate([*CLEAN, "caption: attempt #17 starts"]).may_send is False


def test_mutation_control_without_the_shared_check_the_same_fixtures_publish(monkeypatch):
    """Proves the fixtures bite: neuter the shared check and the counted caption goes out."""
    monkeypatch.setattr(story_checks, "reader_surface", lambda text, constructed=False: [])
    assert recap_gate.gate([*CLEAN, COUNTED[0]]).may_send is True
