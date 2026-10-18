"""
pinned_setup.py — tell the owner's standing equipment setup apart from a session note (#5010).

Hevy 3.2.0 (iOS, October 2026) shipped "pinned" exercise notes: a note tied to an exercise
that shows every time the exercise is added to a routine or a live workout. Matthew wants
them for equipment setup ("seat 5, back pad 6", "bike seat 7, level 11 warm-up").

What the evidence does and does not say (docs/integrations/hevy-changes-2026-10.md):

  * The public API exposes NO pinned-note field — not on exercise templates, routines or
    workouts (live spec captured as contracts/hevy_openapi_2026-10-18.json, and the live
    payloads read 2026-10-18 carry only the documented keys).
  * Whether Hevy copies the pinned text INTO a saved workout's `exercises[].notes` is not
    determinable from the API until Matthew has pinned a note and logged a session with it.

If it is copied, the same setup text would repeat in every session: its numbers ("level 11")
would parse as that day's progression level, the cycling cue would read it as a ride level,
and every session would count as "noted". Repetition is NOT a usable detector — his real
session notes repeat verbatim too ("Level 11 flat" on five consecutive rides, 2026-10-09 →
2026-10-16). So the split is by an explicit owner marker, and it is inert without one:

    a LINE whose first non-blank characters are a marker in SETUP_MARKERS is setup text.

Pure and dependency-free, so the extractor and the cardio reader can both import it without
pulling the other's I/O. The raw note is never altered — callers keep `note_raw` verbatim
and only route the setup lines away from the session parsers.
"""

from __future__ import annotations

# Owner-convention markers (owner decision box on #5010 — the owner picks the marker; these
# are the proposed defaults). Matched case-insensitively against the start of a line.
SETUP_MARKERS: tuple[str, ...] = ("\U0001f4cc", "setup:", "pinned:")


def _is_setup_line(line: str) -> bool:
    head = line.lstrip().lower()
    return bool(head) and any(head.startswith(m) for m in SETUP_MARKERS)


def split_setup(note: str | None) -> tuple[str, str]:
    """(session_text, setup_text) for one exercise note.

    Lines are classified one by one; each part is re-joined with newlines and stripped.
    A note with no marked line returns (note, "") UNCHANGED — byte-identical session text
    to what every reader saw before this module existed.
    """
    raw = note or ""
    session: list[str] = []
    setup: list[str] = []
    for line in raw.splitlines():
        (setup if _is_setup_line(line) else session).append(line)
    if not setup:
        return raw, ""
    return "\n".join(session).strip(), "\n".join(setup).strip()


def is_setup_only(note: str | None) -> bool:
    """True when the note is non-empty and EVERY non-blank line is marked setup text."""
    session, setup = split_setup(note)
    return bool(setup) and not session
