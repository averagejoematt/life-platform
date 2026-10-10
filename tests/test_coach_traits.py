"""tests/test_coach_traits.py — #1113 authored trait scores structure.

The scores themselves are authored character design (a human judgment call, not
testable); what IS enforceable is the structure: exactly the public cast — the
8 operational coaches plus the head coach (lead tier, #1112) — every coach
scored on every shared axis, scores in-bounds, and the honesty disclosure
present so the front-end can never render the cast sheet as measured behavior.
"""

import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from coach import (
    coach_traits,  # noqa: E402
    persona_registry,  # noqa: E402
)

AXIS_KEYS = [a["key"] for a in coach_traits.TRAIT_AXES]


def test_every_cast_coach_is_scored_and_nobody_else():
    # The public cast = the 8 operational coaches + the head coach (#1112).
    cast = set(persona_registry.OPERATIONAL_COACH_IDS) | {persona_registry.LEAD_PERSONA_ID}
    assert set(coach_traits.COACH_TRAITS) == cast


def test_every_coach_scores_every_shared_axis_in_bounds():
    for cid, entry in coach_traits.COACH_TRAITS.items():
        assert set(entry["scores"]) == set(AXIS_KEYS), f"{cid} axis mismatch"
        for k, v in entry["scores"].items():
            assert isinstance(v, int) and 0 <= v <= 100, f"{cid}.{k}={v!r}"
        assert isinstance(entry["note"], str) and entry["note"].strip(), f"{cid} missing authored note"


def test_axes_carry_both_pole_labels():
    for a in coach_traits.TRAIT_AXES:
        for f in ("key", "label", "low", "high"):
            assert isinstance(a.get(f), str) and a[f].strip(), f"axis {a} missing {f}"


def test_traits_for_shape_and_order():
    t = coach_traits.traits_for("sleep_coach")
    assert [a["key"] for a in t["axes"]] == AXIS_KEYS  # render order = axis order
    for a in t["axes"]:
        assert set(a) == {"key", "label", "low", "high", "score"}
    assert t["note"]
    # ADR-104-adjacent honesty: the disclosure must say these are authored, not measured
    assert "uthored" in t["disclosure"] and "not" in t["disclosure"]


def test_traits_for_unknown_coach_is_none():
    assert coach_traits.traits_for("the_chair") is None
    assert coach_traits.traits_for("") is None


def test_no_trait_note_uses_a_gendered_pronoun_for_an_ai_persona():
    # #4649: a coach is software. /api/coach/<id> served "quick to say she was wrong" under
    # trait_scores.note; the note says what the character does, with no she/he/his/her.
    pronoun = re.compile(r"\b(she|he|her|hers|herself|him|his|himself)\b", re.I)
    offenders = {cid: pronoun.findall(entry["note"]) for cid, entry in coach_traits.COACH_TRAITS.items() if pronoun.search(entry["note"])}
    assert not offenders, f"trait note(s) with a gendered pronoun: {offenders}"
    for cid in coach_traits.COACH_TRAITS:
        assert not pronoun.search(coach_traits.traits_for(cid)["note"]), cid
