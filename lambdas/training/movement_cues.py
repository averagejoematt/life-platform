"""movement_cues.py — the one movement cue a lift note carries (#5428, standard §4).

The note on a lift is three lines at most: the effort, at most one reason, at most one cue. The cue is a
breathing / bracing / range cue for the movement's FAMILY, written on the first exercise of that family in a
session only — the second press of a session does not need to be told to breathe out again.

Owner ruling 2026-10-27 (#5428, verbatim in the issue): "when i meant warm up, i meant if it would recommend
resistance band or body stretch before warm up, but if overkill skip" — so the warm-up text is ONE prep-movement
clause per compound family, from #5049's table (band pull-aparts before bench, hip hinges before a hinge,
ankles + hips before a squat), and never a general warm-up block. It rides on the same cue line as the family cue
("Hip hinges first. Brace; breathe out on the way up."), and is the first thing dropped when the note already
carries a reason line (the phone-line budget, standard §7).

The literals are the standard's §4 table, word for word, so the style linter (Lane D, `hevy_note_grammar`) reads
the family a cue belongs to from the same text. Rules, not AI: no model writes a cue.
"""

from __future__ import annotations

from typing import Any

FAMILY_CUES: dict[str, str] = {
    "press": "Breathe out on the press.",
    "squat": "Brace each rep, breathe between reps.",
    "hinge": "Brace; breathe out on the way up.",
    "leg_press": "As deep as your hips stay on the pad.",
    "calf_press": "Full stretch at the bottom; knees soft.",
    "pull": "Breathe out on the pull.",
    "lying_extension": "Elbows still.",
    "crunch": "Breathe out on the crunch.",
    "carry": "Tall, ribs down, bells off your legs.",
}
"""Standard §4: one cue per family, applied to the first exercise of that family in a session."""

PREP_CUES: dict[str, str] = {
    "bench": "Band pull-aparts first.",
    "hinge": "Hip hinges first.",
    "squat": "Ankles + hips first.",
}
"""#5049's one prep movement per compound anchor family (owner ruling 2026-10-27: one clause, no warm-up block)."""

ANCHOR_TO_FAMILY: dict[str, str] = {
    "bench": "press",
    "overhead_press": "press",
    "squat": "squat",
    "hinge": "hinge",
    "row": "pull",
    "vertical_pull": "pull",
}

# (substring of the movement key or title, family) — checked BEFORE the anchor family, so a leg press (catalogued in the
# squat anchor family) reads its own cue, not the squat's brace cue
_NAME_FAMILIES: tuple[tuple[str, str], ...] = (
    ("leg press", "leg_press"),
    ("leg_press", "leg_press"),
    ("sled", "leg_press"),
    ("calf", "calf_press"),
    ("lying db tricep extension", "lying_extension"),
    ("lying_db_tricep_extension", "lying_extension"),
    ("skull", "lying_extension"),
    ("crunch", "crunch"),
    ("farmer", "carry"),
    ("carry", "carry"),
)


def family_of(movement_key: str, entry: dict[str, Any] | None) -> str | None:
    """The cue family of one movement (standard §4), or None when it has no cue."""
    e = entry or {}
    names = f"{str(movement_key or '').lower()} | {str(e.get('title') or '').lower()}"
    for needle, fam in _NAME_FAMILIES:
        if needle in names:
            return fam
    return ANCHOR_TO_FAMILY.get(str(e.get("anchor_family") or ""))


def cue_line(family: str | None, anchor_family: str | None, *, with_prep: bool = True) -> str:
    """The note's one cue line for the first exercise of `family`: the prep clause (a compound with one in #5049's
    table, when `with_prep`) and the family cue, as ONE line; "" when the family has no cue."""
    cue = FAMILY_CUES.get(family or "", "")
    if not cue:
        return ""
    prep = PREP_CUES.get(anchor_family or "", "") if with_prep and family in ("press", "squat", "hinge") else ""
    return f"{prep} {cue}".strip()
