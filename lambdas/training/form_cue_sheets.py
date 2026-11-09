"""form_cue_sheets.py — the general cue sheet a `form_guidance` request is answered with (#5573).

When Matthew asks in a Hevy note for help with form ("I may need research or youtube emailed me on form"), the reply
is a short cue sheet for THAT movement: setup, three cues, the common fault, and what "right" feels like. The sheet
is general guidance about the movement, never an assessment of his form: nothing here has seen him lift.

WHAT THIS IS AND IS NOT

  * Static, hand-written text kept in this module, keyed by movement PATTERN and matched by the catalog title
    (`config/movement_catalog.json`). Nothing is fetched, generated or invented at run time — no model writes a
    sheet (ADR-105: deterministic first; no AI verdict on form exists anywhere in this path).
  * Not owner-reviewed. The sheets are standard coaching cues, labelled `reviewed: False` the way the catalog
    labels its generated entries, until he says otherwise.
  * A movement with no sheet gets NO reply from code — its request stays open for the coach chat to answer.
    A guessed sheet for the wrong pattern is worse than an honest "no sheet for this movement".
  * Video links are never here. The only link a reply may carry is a curated, owner-approved one on the catalog
    entry's `form_reference_urls` (see `training.note_requests.approved_reference_urls`). None exist yet.
"""

from __future__ import annotations

import re
from typing import Any

SHEETS_VERSION = "form-cue-sheets@1.0.0"
REVIEWED = False  # hand-written general cues; no owner review recorded yet

# (pattern id, title regex). Order matters: the first match wins, so the narrower patterns come first
# ("overhead triceps extension" before any "extension"; "rear delt" before "fly"; "leg curl" never reads as a curl).
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("rear_delt_fly", re.compile(r"rear\s+delt|reverse\s+fly|bent\s+over\s+lateral")),
    ("lateral_raise", re.compile(r"lateral\s+raise|lat\s+raise|laterals\b")),
    ("overhead_triceps_extension", re.compile(r"overhead.*(?:tricep|extension)|(?:tricep|triceps)\s+extension.*overhead")),
    ("triceps_pushdown", re.compile(r"push\s*-?\s*down")),
    ("carry", re.compile(r"farmer|suitcase\s+carry|\bcarry\b")),
    ("biceps_curl", re.compile(r"(?<!leg\s)(?<!hamstring\s)(?<!wrist\s)\bcurl\b|\b21s\b")),
)

# Each sheet: setup, exactly three cues, the common fault, what right feels like. Short — a phone screen.
_SHEETS: dict[str, dict[str, Any]] = {
    "lateral_raise": {
        "setup": "Stand or sit tall, a slight bend in the elbows that stays fixed; on a machine, line the shoulder joint up with the pivot.",
        "cues": [
            "Lead with the elbows, not the hands — push them out to the sides.",
            "Raise to about shoulder height, the hands no higher than the elbows.",
            "Lower slowly, about two seconds, without letting the weight touch down between reps.",
        ],
        "common_fault": "Shrugging and swinging the torso to get the weight up — the traps and momentum do the work.",
        "feels_right": "A burn on the side of the shoulder, with the neck and upper traps staying quiet.",
    },
    "rear_delt_fly": {
        "setup": "Chest against the pad (or hinged forward), arms long with a soft elbow; set the handles so the start is a comfortable stretch.",
        "cues": [
            "Sweep the arms out and back in a wide arc, thinking 'hands to the walls'.",
            "Keep the shoulder blades from pinching together hard — the rear delts move the arm, not the mid-back.",
            "Pause briefly at the end, then return under control.",
        ],
        "common_fault": "Turning it into a row: elbows bend, blades squeeze, and the load moves to the upper back.",
        "feels_right": "Work at the back of the shoulder, with the arms moving in one smooth arc.",
    },
    "triceps_pushdown": {
        "setup": "Stand close to the cable, slight forward lean, upper arms pinned at the sides.",
        "cues": [
            "Only the forearms move — the elbows stay at your sides.",
            "Press all the way to straight arms; with a rope, spread the ends apart at the bottom.",
            "Let the forearms come back up to about parallel under control before the next rep.",
        ],
        "common_fault": "Elbows drifting forward and the body leaning in, so the shoulders and bodyweight push the load.",
        "feels_right": "The back of the upper arm working hard at full extension, the shoulders still.",
    },
    "overhead_triceps_extension": {
        "setup": "Face away from the cable (or hold the dumbbell overhead), ribs down, elbows pointing forward and close to the head.",
        "cues": [
            "Keep the upper arms still and let the hands travel behind the head into a deep stretch.",
            "Extend until the arms are straight without arching the lower back.",
            "Lower slowly — the stretched position is the point of this variation.",
        ],
        "common_fault": "Elbows flaring wide and the lower back arching to finish the rep.",
        "feels_right": "A strong stretch in the back of the arm at the bottom, and the work staying in the triceps.",
    },
    "carry": {
        "setup": "Pick the weights up with a hinge (flat back), stand tall, shoulders down and back.",
        "cues": [
            "Walk tall — ribs down, chin level, eyes forward.",
            "Short, steady steps; don't let the weights swing.",
            "Grip hard and keep the shoulders from rolling forward.",
        ],
        "common_fault": "Leaning or hunching under the load, or rushing the steps so the weights swing.",
        "feels_right": "Grip, upper back and trunk all working to keep you upright and still.",
    },
    "biceps_curl": {
        "setup": "Stand or sit tall, elbows by the sides, a full grip on the handle.",
        "cues": [
            "Keep the elbows in place — only the forearms travel.",
            "Curl up without swinging the torso.",
            "Lower all the way to straight arms under control.",
        ],
        "common_fault": "Swinging the body and letting the elbows drift forward to lift more than the biceps can.",
        "feels_right": "The front of the upper arm doing the work through the whole range, not the lower back.",
    },
}


def pattern_of(title: str) -> str | None:
    """The cue-sheet pattern a movement title belongs to, or None (no sheet — an honest gap, never a guess)."""
    t = " ".join(str(title or "").lower().split())
    if not t:
        return None
    for pid, rx in _PATTERNS:
        if rx.search(t):
            return pid
    return None


def sheet_for(title: str) -> dict[str, Any] | None:
    """The cue sheet for a movement title, or None. A copy, so a caller can never edit the table."""
    pid = pattern_of(title)
    if pid is None:
        return None
    s = _SHEETS[pid]
    return {
        "pattern": pid,
        "setup": s["setup"],
        "cues": list(s["cues"]),
        "common_fault": s["common_fault"],
        "feels_right": s["feels_right"],
        "sheets_version": SHEETS_VERSION,
        "reviewed": REVIEWED,
    }


def patterns() -> tuple[str, ...]:
    """Every pattern with a sheet — the test reads it to hold each sheet's shape."""
    return tuple(_SHEETS)
