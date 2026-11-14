"""selection_cue_sheets.py — the cue sheets the SELECTION reads before it may serve a movement that is new to him (#5861 L6).

The selection engine serves a new-to-him movement only with a cue sheet (#5773: `selection_engine._exclusion`'s novelty rule,
and the sheet rides `novel_terms`). `form_cue_sheets` holds the sheets a `form_guidance` note request is ANSWERED with — six
accessory patterns and the four anchor lifts. The library expansion (#5861 L2) and its movement-catalog entries (L6) made
loadable movements prescribable that no sheet covered (hip abduction and adduction, the crunches, the Y raise, the single-leg
lower-body machines, ...), so the novelty rule kept every one of them out of every slot.

This module adds those sheets FOR THE SELECTION ONLY: `sheet_for` answers with `form_cue_sheets.sheet_for` first, then its
own table. The form-guidance reply path is untouched (it still reads `form_cue_sheets`), so nothing a note request returns
today changes; folding these into the reply set is the owner's call.

Same rules as `form_cue_sheets`: static, hand-written, standard coaching cues (practitioner consensus), matched by a title
pattern (narrow first), `reviewed: False` until the owner says otherwise, no claim to prevent injury, no links.
"""

from __future__ import annotations

import re
from typing import Any

SHEETS_VERSION = "selection-cue-sheets@1.0.0"
REVIEWED = False

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("hip_abduction", re.compile(r"hip\s+abduction|abductor|lateral\s+(?:band\s+)?steps?|band\s+walk")),
    ("hip_adduction", re.compile(r"hip\s+adduction|adductor\s+machine")),
    ("y_raise", re.compile(r"\by\s+raise|trap\s*3|prone\s+y\b")),
    ("crunch", re.compile(r"crunch")),
    ("leg_extension", re.compile(r"leg\s+extension")),
    ("calf_raise", re.compile(r"calf\s+raise|calf\s+press")),
    ("split_squat", re.compile(r"split\s+squat|lunge")),
    ("leg_press_machine", re.compile(r"leg\s+press|belt\s+squat|pendulum\s+squat")),
    ("chest_fly", re.compile(r"\bfly\b|flyes|crossover")),
    ("supported_row", re.compile(r"chest\s+supported.*row|t\s*bar\s+row")),
    ("vertical_pull", re.compile(r"chin\s*-?\s*up|pull\s*-?\s*up|pullover")),
    ("incline_press_machine", re.compile(r"incline\s+chest\s+press")),
    ("wrist_extension", re.compile(r"reverse\s+wrist\s+curl|wrist\s+extension")),
)

_SHEETS: dict[str, dict[str, Any]] = {
    "hip_abduction": {
        "setup": "Sit tall against the pad (or stand side-on to the cable), pads on the outside of the knees, feet flat.",
        "cues": [
            "Push the knees out against the pads in a smooth arc; the trunk stays still.",
            "Pause briefly at the widest point you can control.",
            "Return slowly — two seconds — without letting the stack touch down.",
        ],
        "common_fault": "Rocking the torso and bouncing out of the bottom so momentum opens the legs.",
        "feels_right": "Work on the side of the hip, under the belt line, not in the lower back.",
    },
    "hip_adduction": {
        "setup": "Sit tall, pads on the inside of the knees, set the start at a stretch you can control.",
        "cues": [
            "Squeeze the knees together in a smooth arc; keep the hips on the seat.",
            "Pause briefly when the pads meet.",
            "Open slowly into the stretch — the stretched half is the useful half.",
        ],
        "common_fault": "Setting the start wider than you can control and slamming the pads together.",
        "feels_right": "The inner thigh working through the whole range, no pinch in the groin.",
    },
    "y_raise": {
        "setup": "Chest on an incline bench (or bent over), arms hanging, thumbs up, a light weight.",
        "cues": [
            "Raise the arms up and out in a Y, in line with the body, to about ear height.",
            "Draw the shoulder blades down and back as the arms rise — no shrug.",
            "Lower slowly; the weight should feel light for the first sets.",
        ],
        "common_fault": "Shrugging toward the ears and arching the back to get the hands higher.",
        "feels_right": "Work between and below the shoulder blades, the neck quiet.",
    },
    "crunch": {
        "setup": "Set the load so the trunk, not the arms or hips, does the moving; ribs and pelvis are the two ends of the rep.",
        "cues": [
            "Curl the ribs toward the pelvis (or the pelvis toward the ribs) — round the spine, don't hinge at the hips.",
            "Breathe out as you curl in.",
            "Return under control to a long, stretched position.",
        ],
        "common_fault": "Pulling with the arms or swinging the legs, so the hips do the work and the abs only hold.",
        "feels_right": "A strong squeeze through the front of the trunk, nothing in the neck or lower back.",
    },
    "leg_extension": {
        "setup": "Back against the pad, knee joint in line with the machine's pivot, pad on the lower shin.",
        "cues": [
            "Extend to straight knees without lifting the hips off the seat.",
            "Pause at the top for a beat.",
            "Lower slowly to a deep bend — control the bottom.",
        ],
        "common_fault": "Kicking the weight up and dropping it, the hips sliding forward on the seat.",
        "feels_right": "The front of the thigh burning, the knee comfortable.",
    },
    "calf_raise": {
        "setup": "Balls of the feet on the edge, heels free, knees as the machine sets them (straight or bent).",
        "cues": [
            "Lower into a full stretch and hold it a second.",
            "Drive up onto the big toe as high as you can.",
            "No bouncing — the stretch is not a rebound.",
        ],
        "common_fault": "Short, bouncy reps that never reach the stretch or the top.",
        "feels_right": "A deep stretch at the bottom and a hard squeeze at the top in the calf.",
    },
    "split_squat": {
        "setup": "Long split stance, weights at the sides, most of the weight on the front foot.",
        "cues": [
            "Lower straight down until the back knee is just off the floor.",
            "Front knee travels forward over the foot; the heel stays down.",
            "Drive up through the front foot, trunk tall or slightly forward.",
        ],
        "common_fault": "A short stance that pushes the work into the back leg, or the front heel lifting.",
        "feels_right": "The front thigh and glute doing the work, balance steady.",
    },
    "leg_press_machine": {
        "setup": "Back and hips flat on the pad, feet where the knees track over the toes; set the stops before loading.",
        "cues": [
            "Lower until the hips are about to lift off the pad — no further.",
            "Press through the whole foot, knees in line with the toes.",
            "Stop just short of locking the knees.",
        ],
        "common_fault": "Going so deep the lower back rounds off the pad, or snapping the knees straight.",
        "feels_right": "The thighs and glutes working, the lower back pinned and quiet.",
    },
    "chest_fly": {
        "setup": "A soft, fixed bend in the elbows; set the start so the chest is stretched, not the shoulder.",
        "cues": [
            "Bring the hands together in a wide arc — hug a big tree.",
            "Keep the elbow angle fixed; it is not a press.",
            "Open slowly into the stretch you can control.",
        ],
        "common_fault": "Bending the elbows into a press, or opening past a comfortable shoulder stretch.",
        "feels_right": "The chest working through the arc, the front of the shoulder comfortable.",
    },
    "supported_row": {
        "setup": "Chest firmly on the pad, arms long, a neutral grip if the handle allows.",
        "cues": [
            "Pull the elbows back toward the hips, chest staying on the pad.",
            "Pause with the shoulder blades back.",
            "Lower to a full stretch without lifting off the pad.",
        ],
        "common_fault": "Lifting the chest off the pad to heave the weight with the lower back.",
        "feels_right": "The upper and mid back working; the lower back has nothing to do.",
    },
    "vertical_pull": {
        "setup": "Full grip, shoulders set down before the pull; on a negative, step or jump to the top position.",
        "cues": [
            "Lead with the chest and drive the elbows down to the ribs.",
            "Control the lowering — three or four seconds on a negative.",
            "Reach a full hang at the bottom without dropping into it.",
        ],
        "common_fault": "Kipping, half reps, or dropping from the top on a negative.",
        "feels_right": "The lats doing the work, the grip firm, the descent slow.",
    },
    "incline_press_machine": {
        "setup": "Seat set so the handles start at upper-chest height, back and head on the pad.",
        "cues": [
            "Press up and slightly in, shoulder blades staying on the pad.",
            "Stop just short of locking the elbows.",
            "Lower under control to a comfortable stretch.",
        ],
        "common_fault": "The shoulders rolling forward off the pad at the top of every rep.",
        "feels_right": "The upper chest and the front of the shoulders working evenly.",
    },
    "wrist_extension": {
        "setup": "Forearms on the thighs or a bench, palms down, wrists just past the edge, a light weight.",
        "cues": [
            "Lift the back of the hand toward you; the forearm stays down.",
            "Pause at the top.",
            "Lower slowly through the full range.",
        ],
        "common_fault": "Using the arm or a heavy weight that shortens the range to a twitch.",
        "feels_right": "Work on the top of the forearm, the elbow comfortable.",
    },
}


def pattern_of(title: str) -> str | None:
    """The selection sheet pattern a title belongs to (first match wins), or None."""
    t = " ".join(str(title or "").lower().split())
    return next((pid for pid, rx in _PATTERNS if t and rx.search(t)), None)


def sheet_for(title: str) -> dict[str, Any] | None:
    """The sheet the selection reads for a new-to-him movement: the form-guidance sheet when one exists, else this table's,
    else None (the movement stays out of every slot, as before). A copy."""
    from training import form_cue_sheets

    own = form_cue_sheets.sheet_for(title)
    if own is not None:
        return own
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
