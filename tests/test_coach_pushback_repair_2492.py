"""#2492 — prompt-pass v3: grounded pushback + conversational repair, pinned.

Prompt rules are requests; these pins make the parts that must ALWAYS hold, hold:

  * The shared rules block carries the grounded-pushback rule (disagree from the
    facts block only, never a hunch) and the flat-repair rule (never thank him
    for a correction). Prompt-level pin: the rule text is asserted in the
    rendered system prompt, not in a copy.
  * The ceremonial-acknowledgment class is stripped DETERMINISTICALLY by
    coach_style_gate — table-driven over the class, with precision pins for the
    phrases that must survive (referential gratitude, load-bearing grammar).
  * The pushback rule licenses ONLY the facts block as a source — the same block
    the grounding gate already crosses (tests/grounding_wiring.py) — so the
    grounding chokepoint is structurally unrelaxed by this pass.
  * Every texting-configured coach carries a third few-shot (the pushback/repair
    register) and persona_core renders three.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from coach import coach_chat, coach_style_gate, persona_core  # noqa: E402

RULES_TEXT = coach_chat.build_system_prompt("P", "M", "F", "Coach")

# The five coaches that carry a texting_style (glucose/labs do not text — no
# voice config on this surface; the shared rule + gate still cover them).
TEXTING_COACHES = ("sleep_coach", "nutrition_coach", "mind_coach", "physical_coach", "explorer_coach")


def test_pushback_rule_present_and_grounded_only():
    assert "When the facts above contradict something he is planning or claiming, disagree" in RULES_TEXT
    assert "you don't have a case: say nothing rather than manufacture one" in RULES_TEXT
    assert "never agree just because he sounds decided" in RULES_TEXT


def test_repair_rule_still_bans_gratitude():
    assert "Never thank him for the correction" in RULES_TEXT


# ── the ceremonial class, stripped ────────────────────────────────────────────

_CEREMONIAL = [
    ("Thanks for the correction. It was Thursday, you're right about that.", "It was Thursday, you're right about that."),
    ("Thank you for the correction — updating my read.", "Updating my read."),
    ("Thank you for correcting me. Thursday it is.", "Thursday it is."),
    ("I appreciate the correction. The pattern still holds.", "The pattern still holds."),
    ("Thanks for pointing that out. I had the dates crossed.", "I had the dates crossed."),
    ("Thanks for flagging that. Fixed my notes.", "Fixed my notes."),
    ("You're absolutely right. It was one order, not two.", "It was one order, not two."),
]


def test_ceremonial_acknowledgment_class_is_stripped():
    for raw, expected in _CEREMONIAL:
        assert coach_style_gate.strip_banned_openers(raw) == expected, raw


# ── precision: what must SURVIVE ──────────────────────────────────────────────

_SURVIVORS = [
    "thanks for the coffee rec, trying it tomorrow",
    "You're absolutely right that duration matters more here.",
    "I appreciate the correction you're making to the plan, but the data says otherwise.",
    "Thanks for the heads up on the schedule.",
    "The correction was overdue anyway.",
]


def test_referential_and_load_bearing_phrases_survive():
    for text in _SURVIVORS:
        assert coach_style_gate.strip_banned_openers(text) == text, text


# ── few-shots landed, and render ──────────────────────────────────────────────


def test_texting_coaches_carry_the_third_shot():
    for cid in TEXTING_COACHES:
        d = json.load(open(os.path.join(_REPO, "config", "coaches", f"{cid}.json")))
        shots = d.get("texting_few_shots") or []
        assert len(shots) >= 3, f"{cid} lost its #2492 pushback/repair few-shot"
        assert all(len(s) <= 600 for s in shots), f"{cid} has a shot beyond the 600-char render clip"


def test_persona_core_renders_three_shots():
    src = open(os.path.join(_REPO, "lambdas", "coach", "persona_core.py")).read()
    assert "[:3]" in src.split("texting_few_shots", 1)[1][:120], "persona_core must render three few-shots (#2492)"
    assert persona_core is not None
