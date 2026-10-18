"""
hevy_note_types.py — Hevy's three note types, each with one declared owner and one platform behaviour (#5047).

Hevy 3.2.0 (iOS, October 2026) shows three notes on an exercise. The evidence for every row is
in docs/integrations/hevy-changes-2026-10.md §6 (the live spec captured under
tests/fixtures/hevy_openapi_5010/ plus read-only GETs of routines and workouts, 2026-10-18):

  * PINNED EXERCISE NOTE ("appears every time you log this exercise") — Matthew's standing
    equipment setup. NOT in the public API: no schema declares it and no route reaches it.
    The platform neither reads nor writes it, and it cannot (PINNED_EXERCISE_NOTE_FIELD is None).
  * PINNED ROUTINE NOTE ("appears every time you log this routine") — the routine's
    `exercises[].notes`. The platform WRITES its coaching cues here (hevy_compiler). The
    routine-level `routine.notes` the spec declares on POST/PUT is not on the Routine read
    schema and has never read back (#3938, 12 of 12 routines; every routine GET on
    2026-10-18 too), so session-level cues ride on the FIRST exercise's pinned routine note.
  * WORKOUT NOTE ("appears only in this workout") — the performed workout's
    `exercises[].notes`. This is Matthew's session feedback; the platform READS it
    (training_notes parses it for RPE / pain / context) and stores it by name as
    `owner_session_note` on the session record. The platform never writes a workout.

Pure and dependency-free apart from the #5024 setup-marker split, so the compiler (write side)
and hevy_common (read side) can both import it without pulling the other's I/O.
"""

from __future__ import annotations

from typing import Any

from training.pinned_setup import split_setup

# Write side — the one field the routine writer fills: routine `exercises[].notes`, which the
# app shows as the Pinned Routine Note (the clipboard icon).
PINNED_ROUTINE_NOTE_FIELD = "notes"

# Read side — the performed workout's `exercises[].notes`, the Workout Note.
WORKOUT_NOTE_FIELD = "notes"

# Neither side — Hevy exposes no field for the Pinned Exercise Note. None is the declaration:
# no code path can name a field that does not exist.
PINNED_EXERCISE_NOTE_FIELD = None

# The session record's one named field for Matthew's workout-note feedback.
OWNER_SESSION_NOTE_FIELD = "owner_session_note"

# The declared map. `platform` is the only behaviour any module may have toward that note.
NOTE_TYPES: dict[str, dict[str, Any]] = {
    "pinned_exercise_note": {
        "app_label": "Pinned Exercise Note",
        "owner": "matthew",
        "api_field": PINNED_EXERCISE_NOTE_FIELD,
        "readable": False,
        "writable": False,
        "platform": "never touches",
    },
    "pinned_routine_note": {
        "app_label": "Pinned Routine Note",
        "owner": "platform",
        "api_field": f"routine.exercises[].{PINNED_ROUTINE_NOTE_FIELD}",
        "readable": True,
        "writable": True,
        "platform": "writes coaching cues",
    },
    "workout_note": {
        "app_label": "Workout Note",
        "owner": "matthew",
        "api_field": f"workout.exercises[].{WORKOUT_NOTE_FIELD}",
        "readable": True,
        "writable": False,  # writable only by creating a workout (POST /v1/workouts), which the platform never calls
        "platform": "reads as feedback",
    },
}


def owner_session_note(exercises: list[dict[str, Any]] | None) -> str:
    """Matthew's workout notes for one session, one line per noted exercise: "<exercise>: <text>".

    `exercises` are the NORMALIZED exercises (`name`, `notes`). Owner-marked setup lines
    (#5024's `📌` / `Setup:` / `Pinned:` — a pinned exercise note, if Hevy ever copies one into
    the workout) are separated out first, so the field holds session feedback only. The raw
    `exercises[].notes` stays verbatim on the record; this field is a projection of it.
    Returns "" when the session has no workout note.
    """
    lines: list[str] = []
    for ex in exercises or []:
        session, _setup = split_setup(ex.get(WORKOUT_NOTE_FIELD))
        text = (session or "").strip()
        if not text:
            continue
        name = (ex.get("name") or "").strip()
        lines.append(f"{name}: {text}" if name else text)
    return "\n".join(lines)
