"""tests/test_cardio_model_no_live_change_5861.py — epic #5861 lane L4: the cardio model changes nothing live.

The live cardio wire is `cardio_menu` (the kind, the machine, the dose) and `cardio_note` / `hevy_note_grammar` (the
note). Lane L4 moved ONE value into protocol data: `hevy_note_grammar.INTERVAL_HARD_STEP` (owner ruling 2026-11-08,
#5428: an interval's hard minutes sit two levels over his steady level) is now READ from
`cardio_model.PROTOCOLS["structured_intervals"]`. Its value and every output built on it must be byte-identical to
before. The fingerprint below was computed on `origin/issue-5857-quality-tiers` (c97168868) BEFORE the lane's edit;
a change to any of these outputs reds this test.
"""

from __future__ import annotations

import hashlib
import json

from training import cardio_menu, cardio_note, hevy_note_grammar

# sha256 of `_fingerprint()` on the base commit, before the lane touched any live module.
BASE_FINGERPRINT = "18cba1609be62b974d7d70e8f8505b674a41509bad4b9b0a2ace358cffdaadd0"


def _fingerprint() -> dict:
    out: dict = {
        "INTERVAL_HARD_STEP": hevy_note_grammar.INTERVAL_HARD_STEP,
        "INTERVAL_ESCAPE_STEP": hevy_note_grammar.INTERVAL_ESCAPE_STEP,
        "cardio_note.INTERVAL_LEVEL_STEP": cardio_note.INTERVAL_LEVEL_STEP,
        "interval_set": list(cardio_menu.interval_set()),
    }
    shapes = []
    for kind in ("easy", "tempo", "hills", "intervals", "incline_treadmill_walk"):
        for steady in (None, 8, 11, 14):
            for minutes in (20, 30):
                walk = kind == "incline_treadmill_walk"
                dose = {"level": steady, "steady": steady, "incline_pct": 8.0 if walk else None}
                clauses, unit, line = cardio_note.clock_shape(kind, minutes, dose, walk=walk)
                shapes.append(
                    [
                        kind,
                        steady,
                        minutes,
                        clauses,
                        unit,
                        line,
                        cardio_note.levels_text(kind, dose, walk=walk),
                        cardio_note.interval_escape(kind, dose, minutes, walk=walk),
                    ]
                )
    out["shapes"] = shapes
    out["prescriptions"] = [
        cardio_menu.prescription(k, m) for k in cardio_menu.KINDS for m in ("cycling", "treadmill", "elliptical", "rowing_machine")
    ]
    week = [
        {"date": "2026-11-16", "archetype": "Upper-heavy"},
        {"date": "2026-11-17", "archetype": "Lower-heavy"},
        {"date": "2026-11-18", "archetype": "Shoulders+arms"},
        {"date": "2026-11-19", "archetype": None},
        {"date": "2026-11-20", "archetype": "Upper-volume"},
        {"date": "2026-11-21", "archetype": "Lower-volume"},
        {"date": "2026-11-22", "archetype": None},
    ]
    out["week"] = cardio_menu.place_week(week, last_tempo_or_hills="tempo")
    out["escape_line"] = hevy_note_grammar.interval_escape_line(14, 12)
    return out


def _digest() -> str:
    return hashlib.sha256(json.dumps(_fingerprint(), sort_keys=True, default=str).encode()).hexdigest()


def test_the_live_cardio_wire_is_byte_identical_to_the_base():
    assert _digest() == BASE_FINGERPRINT, "a live cardio output moved: cardio_menu / cardio_note / hevy_note_grammar must not change"


def test_the_interval_hard_step_keeps_its_ruled_value():
    assert hevy_note_grammar.INTERVAL_HARD_STEP == 2 and cardio_note.INTERVAL_LEVEL_STEP == 2
