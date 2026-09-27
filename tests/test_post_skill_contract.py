#!/usr/bin/env python3
"""tests/test_post_skill_contract.py — the /post skill and the special-card kit.

`/post` is a prose skill, so nothing compiles it. This file is what stops it decaying into
a nice paragraph that has stopped matching the code — the fate of `journey-review`, which
audited four of seven chat modes and hunted a string that no longer existed.

The assertions are the rules the first special (the 20-day nutrition carousel, 2026-09-26)
actually paid for, plus the pair the skill and the kit must agree on: the GROUND, which is
the one value a reader learns to read, and which would silently re-skin every special ever
posted if the two copies drifted apart.
"""

import pathlib
import re

import pytest
from skill_paths import require_skill

REPO = pathlib.Path(__file__).resolve().parent.parent
KIT = REPO / "deploy" / "lib" / "special_cards.py"
EXAMPLE = REPO / "deploy" / "build_nutrition_special_cards.py"


def body() -> str:
    return require_skill("post").read_text(encoding="utf-8").lower()


# ── the rules, each one a thing that went wrong once ─────────────────────────
RULES = [
    ("never posts", "the skill must state that nothing in it posts (ADR-140 rule 5, human selection only)"),
    ("cielab", "ground separation is measured perceptually — RGB distance read navy as plum at thumbnail"),
    ("b_neutral_bars", "a COUNT may not use the grade-banded bars; a tall bar would read as earned"),
    ("audience_guard", "a coach quote is a stored record, not a sentence the skill writes"),
    ("#3931", "no calorie target may be drawn on a publication surface"),
    ("tie-break", "two runs over identical data swapped two bars; rankings need an explicit order"),
    ("b_closing", "a rule drawn as its own block gets orphaned by stretch_last"),
    ("tofu", "the allowed glyph set is narrow and anything else renders as a box"),
    ("cannot see", "before a number becomes a headline, name the channels that do not feed it"),
]


@pytest.mark.parametrize("needle,why", RULES)
def test_post_skill_carries_its_rules(needle, why):
    assert needle in body(), f"/post must cover: {why}"


def test_post_skill_names_the_kit_and_the_worked_example():
    """A skill that does not name its starting files sends the next session to a blank page."""
    text = body()
    assert "deploy/lib/special_cards.py" in text
    assert "deploy/build_nutrition_special_cards.py" in text


def test_post_skill_says_to_look_at_the_rendered_png():
    """The #1193 lesson: a code-drawn asset is invisible to every page-level check."""
    assert "look at every png" in body()


# ── the ground: one value, two files, no drift ───────────────────────────────
def _ground_from(path: pathlib.Path) -> str:
    m = re.search(r"SPECIAL_GROUND\s*=\s*\((\s*\d+\s*,\s*\d+\s*,\s*\d+\s*)\)", path.read_text(encoding="utf-8"))
    assert m, f"{path.name} must define SPECIAL_GROUND as a literal triple"
    return re.sub(r"\s+", "", m.group(1))


def test_the_ground_is_one_value_in_the_kit():
    assert _ground_from(KIT) == "44,4,50"


def test_the_skill_quotes_the_ground_the_kit_actually_uses():
    """The skill's table teaches the reader which ground means which family. If the kit
    moves and the prose does not, the skill is teaching a colour nobody ships."""
    r, g, b = _ground_from(KIT).split(",")
    assert f"({r}, {g}, {b})" in require_skill("post").read_text(encoding="utf-8")


def test_the_ground_is_outside_the_semantic_vocabulary():
    """GREEN = earned and AMBER = an honest miss, so the ground must sit nearer the grounds
    it replaces than either accent — otherwise the container itself states a verdict."""
    import sys

    sys.path.insert(0, str(REPO / "deploy"))
    from lib.special_cards import SPECIAL_GROUND, audit_ground

    a = audit_ground(SPECIAL_GROUND)
    assert a["nearer_a_ground_than_an_accent"], a
    assert a["separated_from_both_grounds"], a
    assert a["faint_text_contrast"] >= 3.5, a


# ── the worked example stays the worked example ──────────────────────────────
def test_the_example_draws_through_the_kit():
    """If the reference implementation stops using the kit, the skill's instruction to copy
    it produces a second engine — the drift the shared card_engine exists to prevent."""
    src = EXAMPLE.read_text(encoding="utf-8")
    assert "from lib import special_cards as kit" in src
    assert "kit.render_pack(" in src


def test_the_example_refuses_to_invent_a_coach_quote():
    src = EXAMPLE.read_text(encoding="utf-8")
    assert "stored coach lines" in src, "the example must exit rather than compose a coach line it does not have"


def test_rankings_carry_an_explicit_tie_break():
    """`Counter.most_common` keeps insertion order for ties; two runs over identical data
    rendered two different cards. Every ranking that reaches a card sorts by name too."""
    src = EXAMPLE.read_text(encoding="utf-8")
    assert "most_common(5)" not in src, "top_foods must sort with an explicit tie-break, not most_common"
    assert src.count("key=lambda kv: (-kv[1], kv[0])") >= 2
