"""session_cues.py — a prescribed exposure's CUE, generated from its own sets (#5317), and the carry's dose (#5318).

#5317: the intensity cue's set count was a literal beside the sets array ('MODERATE: 3 sets of 6–10') while the
shoulders+arms press anchor prescribed ONE set (#5266); on 2026-10-24 a coach chat read the cue and drafted 3 x 80 lb,
against the owner's ruled once-a-week, one-set press. The cue is now a function of the sets — count, rep range and the
charter's effort band (`training.effort_ceilings`) — so the instruction he reads and the sets he is prescribed are one
thing. `program_structure.session_prescription_for_role` stamps every exposure's cue from here after every trim (time,
deload); `full_body_session` re-derives it for the sets a block actually carries (the Minimum Viable Session's two).

#5318 (owner ruling B3, 2026-10-24): the shoulders+arms farmer's carry is its own accessory shape (`CARRY_EXPOSURE`). #5372: it is
Hevy's standard distance-typed 'Farmers Walk' template (`short_distance_weight`, 50C613D0 — the one he logs), so its sets carry a
distance, not a duration. On a carry the distance field is his STEP COUNT (owner, 2026-10-25), so the dose is steps. #5373: the cue
says so in the note grammar's line ("Steps go in the yards box.", `hevy_note_grammar.CARRY_STEPS_LINE`) and, given his stride, adds the labelled estimated distance.

Split out of `training.program_structure` (which re-exports every public name here) so neither module crosses the
1000-line ceiling (#1665).
"""

from __future__ import annotations

from typing import Any

from training import effort_ceilings, hevy_note_grammar

_EFFORT = effort_ceilings.class_bands()

CARRY_CUE = hevy_note_grammar.CARRY_CUE
CARRY_STEPS_LINE = hevy_note_grammar.CARRY_STEPS_LINE


def effort_line(rpe: tuple[Any, Any] | Any, last_set_rpe: tuple[Any, Any] | Any | None = None) -> str:
    """#5428 (standard §3.2): line 1 of every lift note — `RPE a–b[, last set RPE c–d]`. Lane D's
    `hevy_note_grammar.effort_line`, so the producer and the linter read one grammar."""
    return hevy_note_grammar.effort_line(rpe, last_set_rpe)


def exposure_cue(intensity: str, sets: list[dict[str, Any]], stride: dict[str, Any] | None = None) -> str:
    """The exposure's note text — #5428 (the Hevy note standard): the EFFORT, never the sets.

    #5317 made the cue a function of the sets because a literal '3 sets of 6–10' sat beside a one-set prescription and a
    coach chat drafted 3 sets from it. #5428 retires the class: Hevy shows every set row (load x reps, W rows, PREVIOUS),
    so the note never restates a count, a rep range or a load — line 1 is the charter's effort band, the one thing a row
    cannot carry. A compound exposure reads the compounds band; an accessory reads it with the last isolation set's band
    (a one-set accessory IS its last set); a carry is the standard's §3.5 block (per hand from 2026-10-27, steps in the
    yards box). `stride` is accepted for the callers' signature (#5373) and no longer printed: the estimated distance is
    the chat's, not the set's."""
    del stride
    if intensity == "carry":
        # #5428 re-grade #3: the one adjust rule after set 1 rides with it (`lift_note.carry_note` adds his last load)
        adjust = hevy_note_grammar.carry_adjust_line(hevy_note_grammar.charter_step_lb())
        return "\n".join((hevy_note_grammar.carry_line1(_EFFORT[effort_ceilings.COMPOUNDS]), CARRY_CUE, adjust, CARRY_STEPS_LINE))
    if intensity == "accessory":
        if len(sets) == 1:
            return effort_line(_EFFORT[effort_ceilings.LAST_ISOLATION_SET])
        return effort_line(_EFFORT[effort_ceilings.COMPOUNDS], _EFFORT[effort_ceilings.LAST_ISOLATION_SET])
    return effort_line(_EFFORT[effort_ceilings.COMPOUNDS])


def _default_sets(spec: dict[str, Any], intensity: str) -> list[dict[str, Any]]:
    """The sets an exposure prescribes at its default count — what its default `cue` is generated from."""
    if intensity == "heavy":
        return [{"kind": "top", "reps": list(spec["reps"])}] + [
            {"kind": "back_off", "reps": list(spec["reps"]), "pct_of_top": 100 + spec["back_off_pct"]} for _ in range(spec["back_off_sets"])
        ]
    if intensity == "carry":
        return [{"kind": "working", "distance_meters": spec["carry_steps"]} for _ in range(spec["sets"])]
    return [{"kind": "working", "reps": list(spec["reps"])} for _ in range(spec["sets"])]


CARRY_EXPOSURE: dict[str, Any] = {
    "sets": 2,
    "carry_steps": 60,
    "effort": effort_ceilings.COMPOUNDS,
    "rest_seconds": 90,
    "carry_steps_provenance": "platform-proposed",
    "load": "owner-picked: the first exposure's load is his, logged; the engine anchors from that log and never from the shrug",
    "stated": "2026-10-24",
    "ruling": "owner ruling B3 2026-10-24 (#5318): 'Replace the 2 DB shrug sets on shoulders_arms with 2 sets of farmer's carry.'",
}
"""A loaded carry's dose (#5318, #5372): distance-typed sets, no rep range (Hevy's standard 'Farmers Walk' is `short_distance_weight`:
distance and load, no time), no load prescribed — the set count is the owner's (2, set-neutral with the shrug). `carry_steps` is the number
written to the set's `distance_meters` wire field: on a carry that field is his step count (he has no gym markings, owner 2026-10-25;
the step-to-distance estimate is `training.logging_conventions`, #5373). 60 steps replaces B3's 40 s per carry at a loaded cadence of ~1.5 steps/s;
the number is the platform's proposal and says so. Not in `EXPOSURES`: every reader of that table reads a rep range, and a carry has none."""
