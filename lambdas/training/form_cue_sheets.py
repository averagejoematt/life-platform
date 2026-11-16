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

THE ANCHOR SHEETS (#5817, owner ruling 2026-11-11, #5779 D8)

  * Four lifts: barbell bench press, barbell back squat, conventional deadlift (barbell) and the one-arm dumbbell row.
    The barbell bent-over row has no sheet: no program role serves it (the row anchor resolves `machine_row`, then
    `one_arm_db_row` — `program_structure.ANCHORS["row"]`; no v0.4 template, charter pool or rotation names it).
  * Matched by catalog key, Hevy template id or exact catalog title only — never a regex — so an incline bench, a front
    squat, a Romanian deadlift or a cable row never reads an anchor's sheet.
  * Each sheet splits its cues into `still_visible` (checkable in one still frame: joint stack, bar position at a fixed
    point, angles) and `not_visible` (tempo, bracing timing, breath, anything that needs motion or sensation). The one
    clinical-context line is a breathing cue (breathe between reps, no long breath-hold), reference only: never an
    intensity statement, never rendered. No cue claims to prevent injury or to have a medical effect.
  * ONE still-visible cue per sheet (`note_cue`) rides on the lift's Hevy note beside the family breathing cue
    (`lift_note._cue_for`), regardless of filming (D8). The family breathing cue is never dropped for it (standard §6.1).
  * Every anchor sheet is `reviewed: False` until the owner approves THAT sheet; the approval is his edit to the
    literal below (a date), never a code path. No anchor carries a form-reference link (D11).
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


# ── the anchor sheets (#5817) ───────────────────────────────────────────────────────────────────────────────────────
ANCHOR_SHEETS_VERSION = "anchor-cue-sheets@0.1.0"

# Per sheet: `reviewed` is False until the owner approves THAT sheet (his edit: the approval date as a string). Cues are
# (id, text); `note_cue` names one still-visible id and the short form the Hevy note carries.
_ANCHOR_SHEETS: dict[str, dict[str, Any]] = {
    "bench_press_barbell": {
        "title": "Bench Press (Barbell)",
        "reviewed": False,
        "still_visible": (
            ("feet_planted", "Feet flat on the ground, knees bent, glutes on the bench."),
            ("blades_set", "Shoulder blades pulled back and down, upper back set into the bench, a small arch."),
            ("grip_width", "Grip a little wider than the shoulders; the forearms are vertical with the bar on the chest."),
            ("wrists_over_elbows", "Wrists stacked straight over the elbows, the bar in the heel of the hand."),
            ("elbow_angle", "Elbows angled under the bar, not flared straight out to the sides."),
            ("touch_point", "The bar touches the lower chest, around the nipple line."),
            ("lockout_over_shoulders", "At lockout the bar sits over the shoulders, arms straight."),
        ),
        "not_visible": (
            ("controlled_lower", "Lower under control to a light touch; no bounce off the chest."),
            ("leg_drive", "Push the feet into the ground as you press."),
            ("stay_tight", "Keep the upper back tight from the first rep to the last."),
            ("bar_path", "Press up and slightly back toward the shoulders."),
        ),
        "note_cue": ("wrists_over_elbows", "Stack wrists."),  # with the press cue: ONE phone line (fits exercise 1)
        "clinical_context": "Breathe between reps; no long breath-hold.",
    },
    "back_squat_barbell": {
        "title": "Squat (Barbell)",
        "reviewed": False,
        "still_visible": (
            ("bar_on_upper_back", "Bar across the upper back (the traps), not on the neck; hands just outside the shoulders."),
            ("stance", "Feet about shoulder width, toes turned out a little."),
            ("knees_track_toes", "Knees track in line with the toes, not caving in."),
            ("heels_down", "Whole foot on the ground, heels down, at the bottom."),
            ("bar_over_midfoot", "From the side, the bar sits over the middle of the foot, top and bottom."),
            ("neutral_back", "Back flat at the bottom, not rounding under; chest up over the bar."),
            ("depth", "Hip crease at or below the top of the knee, as deep as the back stays flat."),
        ),
        "not_visible": (
            ("brace_before_descent", "Brace before each descent and hold it to the bottom."),
            ("controlled_descent", "Sit down under control; no dropping into the bottom."),
            ("drive_whole_foot", "Drive up through the whole foot; hips and chest rise together."),
            ("stay_tight_bottom", "Stay tight at the bottom; no relaxing before the drive."),
        ),
        "note_cue": ("knees_track_toes", "Knees track the toes."),
        "clinical_context": "Breathe between reps; no long breath-hold.",
    },
    "conventional_deadlift_barbell": {
        "title": "Deadlift (Barbell)",
        "reviewed": False,
        "still_visible": (
            ("bar_over_midfoot", "At the start the bar is over the middle of the foot, about an inch from the shins."),
            ("grip_outside_legs", "Hands just outside the legs, arms straight."),
            ("shoulders_over_bar", "Shoulders just in front of the bar at the start."),
            ("hip_height", "Hips higher than the knees and lower than the shoulders at the start."),
            ("flat_back", "Back flat from hips to head at the start, not rounded."),
            ("bar_close", "Bar close to the legs as it passes the knees."),
            ("tall_lockout", "At lockout: standing tall, hips through, no leaning back."),
        ),
        "not_visible": (
            ("slack_out", "Pull the slack out of the bar before it leaves the ground."),
            ("push_the_ground", "Push the ground away; the bar stays in contact with the legs on the way up."),
            ("rise_together", "Hips and shoulders rise together off the ground."),
            ("lower_hips_first", "Lower it the way it came: hips back first, knees bend once the bar passes them."),
        ),
        "note_cue": ("bar_over_midfoot", "Bar over mid-foot."),
        "clinical_context": "Breathe at the top between reps; no long breath-hold.",
    },
    "one_arm_db_row": {
        "title": "Dumbbell Row",
        "reviewed": False,
        "still_visible": (
            ("supported_stance", "One hand and knee on the bench (or a hand on it, feet staggered), the free arm hanging straight."),
            ("flat_back", "Back flat and roughly level with the ground, not twisted toward the dumbbell."),
            ("square_shoulders", "Shoulders square to the ground at the top, not rotated open."),
            ("elbow_to_hip", "At the top the elbow is by the hip, close to the side."),
            ("neutral_head", "Head in line with the back, eyes down."),
        ),
        "not_visible": (
            ("pull_with_back", "Start the pull by drawing the shoulder blade back, then the elbow."),
            ("no_jerk", "No yanking or torso swing to start the rep."),
            ("controlled_lower", "Lower to a full stretch under control."),
        ),
        "note_cue": ("elbow_to_hip", "Elbow to hip."),
        "clinical_context": "Breathe between reps; no long breath-hold.",
    },
}

# catalog key, Hevy template id, or exact catalog title (lower-cased) -> sheet id. Exact only (module doc).
_ANCHOR_MATCH: dict[str, str] = {
    "barbell_bench_press": "bench_press_barbell",
    "tmpl:79D0BB3A": "bench_press_barbell",
    "squat_barbell": "back_squat_barbell",
    "tmpl:D04AC939": "back_squat_barbell",
    "deadlift_barbell": "conventional_deadlift_barbell",
    "tmpl:C6272009": "conventional_deadlift_barbell",
    "one_arm_db_row": "one_arm_db_row",
    "tmpl:F1E57334": "one_arm_db_row",
}
_ANCHOR_MATCH.update({s["title"].lower(): sid for sid, s in _ANCHOR_SHEETS.items()})


def anchor_of(movement_key: str, entry: dict[str, Any] | None = None) -> str | None:
    """The anchor sheet id for a movement (its catalog key, `tmpl:<id>` key, or exact catalog title), or None."""
    title = " ".join(str((entry or {}).get("title") or "").lower().split())
    return _ANCHOR_MATCH.get(str(movement_key or "")) or _ANCHOR_MATCH.get(title)


def _anchor_sheet(sheet_id: str) -> dict[str, Any] | None:
    """One anchor sheet as a fresh copy (a caller can never edit the table), or None."""
    s = _ANCHOR_SHEETS.get(sheet_id)
    if s is None:
        return None
    return {
        "sheet": sheet_id,
        "title": s["title"],
        "still_visible": [{"id": i, "cue": t} for i, t in s["still_visible"]],
        "not_visible": [{"id": i, "cue": t} for i, t in s["not_visible"]],
        "note_cue": {"id": s["note_cue"][0], "text": s["note_cue"][1]},
        "clinical_context": s["clinical_context"],
        "sheets_version": ANCHOR_SHEETS_VERSION,
        "reviewed": s["reviewed"],
    }


def _anchor_sheets() -> tuple[str, ...]:
    """Every anchor sheet id — the test reads it to hold each sheet's shape."""
    return tuple(_ANCHOR_SHEETS)


def anchor_note_cue(movement_key: str, entry: dict[str, Any] | None = None) -> str:
    """The one still-visible cue an anchor's Hevy note carries (#5817, D8: rendered regardless of filming and of
    `reviewed`), or "" for every other movement — which is what keeps every other note unchanged."""
    sid = anchor_of(movement_key, entry)
    return _ANCHOR_SHEETS[sid]["note_cue"][1] if sid else ""


def anchor_note_cues() -> tuple[str, ...]:
    """Every anchor's note cue text — `session_block._fit` drops one when a critic's clause overflows the note."""
    return tuple(s["note_cue"][1] for s in _ANCHOR_SHEETS.values())
