"""#2535 — the deterministic style ceiling: em-dash alternation + banned openers.

Both habits were already banned in the prompt (#2481) and both survived it. The
2026-08-10 sweep measured 23 uses of "Honest answer" in 536 replies and an em-dash in
77% of them, with no separation between the coach whose spec permits the character and
the coach whose spec forbids it. So the rule becomes a gate, exactly as
`enforce_emoji_policy` already is for emoji.

What these tests actually defend, in order of what would hurt most if it broke:

  1. THE SAFETY CONTRACT. The gate runs before the grounding gate, so a transform that
     damaged a number would either be caught downstream (a spurious hold) or, worse,
     silently change a figure the coach then states. Every transform here is
     punctuation-only; `test_never_alters_*` proves it over the real corpus shapes.
  2. THE LEGITIMATE-USE CARVE-OUT. "that's worth a quick honest answer from you" is a
     real sentence from the corpus and must survive untouched — a gate that mangles
     honest prose to catch a stock phrase has made the reply worse.
  3. THE ALTERNATION. 63% of replies carry exactly ONE em-dash, so a per-reply cap
     alone cannot move the headline rate. The cross-reply rule is the mechanism; if it
     regresses to a per-reply cap the measured effect disappears while every test that
     only checks "≤1 per reply" still passes.
"""

import re

import pytest
from coach import coach_chat
from coach.coach_style_gate import MAX_EM_DASHES, demote_em_dashes, enforce_style, has_em_dash, strip_banned_openers

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_WORDS = re.compile(r"[A-Za-z']+")


# ── The safety contract ───────────────────────────────────────────────────────

CORPUS_SHAPES = [
    "On the night of 2026-08-07, recovery came in at 31%, HRV at 32 ms — not a great night.",
    "1872 kcal is the target — that's your maintenance minus a 500 kcal deficit.",
    "Last night came in at 6.8 hours — noticeably shorter than your 7-night average of 7.8 h.",
    "Sleep quantity and HRV can come apart for a bunch of reasons — duration is only one input.",
    "Pick one stream this week — whichever feels least annoying — and I'll make sure you see something back.",
    "Honest answer: I don't have your 170 g protein floor in the facts in front of me.",
    "No — I'm a fictional composite. Not a real human.",
    "Day 1 of cycle 13 starts today, so the thread is genuinely empty.",
]


@pytest.mark.parametrize("text", CORPUS_SHAPES)
def test_never_alters_numbers(text):
    """Punctuation only. A changed figure here would be a fabrication the gate invented
    AFTER the model was grounded on the original."""
    out = "\n\n".join(enforce_style([text]))
    assert _NUMBER.findall(out) == _NUMBER.findall(text), f"numbers changed: {text!r} -> {out!r}"


@pytest.mark.parametrize("text", CORPUS_SHAPES)
def test_never_alters_words(text):
    """Word sequence is preserved except for the deliberately-removed banned openers."""
    out = "\n\n".join(enforce_style([text]))
    before, after = _WORDS.findall(text.lower()), _WORDS.findall(out.lower())
    assert after == [w for w in before if w not in ("honest", "answer")] or after == before


def test_dates_survive_the_em_dash_demotion():
    text = "Recovery on 2026-08-07 was 31% — and on 2026-08-08 it was 44% — both below your baseline."
    out = "\n\n".join(enforce_style([text]))
    assert "2026-08-07" in out and "2026-08-08" in out
    assert "31%" in out and "44%" in out


# ── The em-dash ceiling ───────────────────────────────────────────────────────


def test_first_em_dash_is_kept_and_the_rest_become_commas():
    text = "A — b — c — d"
    out, used = demote_em_dashes(text, allowance=1)
    assert used == 1
    assert out.count("—") == 1
    assert out == "A — b, c, d"


def test_zero_allowance_removes_every_em_dash():
    out, used = demote_em_dashes("A — b — c", allowance=0)
    assert used == 0
    assert "—" not in out


def test_demotion_never_produces_a_double_comma():
    out, _ = demote_em_dashes("Not the meetings, — the wired-at-9 that follows.", allowance=0)
    assert ",," not in out and " ," not in out


def test_ceiling_is_per_reply_not_per_bubble():
    """Two bubbles each with one em-dash: the reply's allowance is one, so the second
    bubble's dash is demoted. A per-bubble cap would let a 3-bubble burst carry three."""
    out = enforce_style(["First — one.", "Second — two.", "Third — three."])
    assert sum(b.count("—") for b in out) == MAX_EM_DASHES


def test_alternation_zeroes_the_allowance_after_a_dashed_reply():
    """The mechanism the measured distribution requires — 63% carry exactly one, so a
    per-reply cap alone moves nothing."""
    assert sum(b.count("—") for b in enforce_style(["A — b"], last_reply_had_em_dash=False)) == 1
    assert sum(b.count("—") for b in enforce_style(["A — b"], last_reply_had_em_dash=True)) == 0


def test_reply_without_em_dashes_is_untouched():
    bubbles = ["Hey", "How'd it go?"]
    assert enforce_style(list(bubbles)) == bubbles


# ── Banned openers ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected_start",
    [
        ("Honest answer: it's close to a void.", "It's close"),
        ("Honest answer is I don't have your data yet.", "I don't have"),
        ("The honest answer is that the evidence is thin.", "The evidence is thin"),
        ("Honestly the honest answer is I don't know.", "I don't know"),
        ("Great question. Your HRV is suppressed.", "Your HRV"),
        ("Good question — the answer is duration.", "The answer is duration"),
        ("To be honest, I'd rest today.", "I'd rest today"),
    ],
)
def test_banned_openers_are_removed_and_recapitalized(text, expected_start):
    out = strip_banned_openers(text)
    assert out.startswith(expected_start), f"{text!r} -> {out!r}"
    assert "honest answer" not in out.lower()


def test_legitimate_mid_sentence_use_survives():
    """From the real corpus. A noun phrase is not an assistant-ism."""
    text = "Genuinely don't know yet — that's worth a quick honest answer from you."
    assert "honest answer" in strip_banned_openers(text).lower()


def test_banned_opener_after_a_sentence_boundary_is_removed():
    text = "I looked at the week. Honest answer: not many yet."
    out = strip_banned_openers(text)
    assert "honest answer" not in out.lower()
    assert "Not many yet." in out


def test_bubble_that_was_only_a_banned_phrase_does_not_go_out_empty():
    """Dropping it is right; sending a blank bubble is not. If EVERY bubble empties,
    the original stands — silence is a worse failure than a stock phrase."""
    out = enforce_style(["Great question.", "Your HRV is 32 ms."])
    assert all(b.strip() for b in out)
    assert any("32 ms" in b for b in out)
    assert enforce_style(["Great question."]) == ["Great question."]


# ── Wiring ────────────────────────────────────────────────────────────────────


def test_run_turn_applies_the_style_gate_before_grounding():
    """The ordering invariant: the grounder must adjudicate exactly the text that will
    be sent. If the gate ran after, it would edit a reply behind the gate's back."""
    seen = {}

    def caller(_body):
        return {"content": [{"type": "text", "text": "Honest answer: your HRV is 32 ms — down — again."}]}

    def grounder(text):
        seen["text"] = text
        return []

    result = coach_chat.run_turn(
        coach_id="sleep",
        coach_name="Dr. Lisa Park",
        persona_block="p",
        memory_block="m",
        facts_block="f",
        thread=[],
        inbound="how'd i sleep",
        model="m",
        caller=caller,
        grounder=grounder,
        last_reply_had_em_dash=False,
    )
    assert seen["text"] == result.text, "the grounder saw text other than what was returned"
    assert "honest answer" not in result.text.lower()
    assert result.text.count("—") <= MAX_EM_DASHES
    assert "32 ms" in result.text


def test_run_turn_alternation_flows_through():
    def caller(_body):
        return {"content": [{"type": "text", "text": "Down — again."}]}

    out = coach_chat.run_turn(
        coach_id="sleep",
        coach_name="Dr. Lisa Park",
        persona_block="p",
        memory_block="m",
        facts_block="f",
        thread=[],
        inbound="x",
        model="m",
        caller=caller,
        grounder=lambda t: [],
        last_reply_had_em_dash=True,
    )
    assert not has_em_dash(out.text)
