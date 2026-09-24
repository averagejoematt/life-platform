"""program_v03.py — TRAINING_PROGRAM v0.3 (full body), SUPERSEDED 2026-09-24, kept readable.

The owner switched programs on 2026-09-23 (~20:10 PT): v0.3 full-body -> v0.4 Upper/Lower,
served in ORDER (#4147; decision `DECISION#2026-09-24T03:10:59`, corrections-ledger override
signal `program_split_full_body_v0.3`). v0.4 lives in `training.program_structure`; this
module keeps v0.3's definitions VERBATIM as history, so a routine, a plan or an adherence
row written under v0.3 can still be read against the program it was written for.

Nothing here steers a prescription. The ONE live reader is `load_ramp.block_1_start()`,
which reads `BLOCK_CALENDAR['block_1_start']` (re-exported by `program_structure`) as the
date the detraining-discount age is measured to; that date is 2026-09-24 for v0.3 and for
v0.4 alike, and a test holds the two equal (`load_ramp` belongs to another lane — #4148).
"""

from __future__ import annotations

from typing import Any

SUPERSEDED: dict[str, Any] = {
    "program_version": "0.3",
    "split": "full_body",
    "superseded_on": "2026-09-24",
    "superseded_by": "0.4",
    "decision_sk": "DECISION#2026-09-24T03:10:59",
    "override_signal": "program_split_full_body_v0.3",
    "issue": "#4147",
    "approved": "2026-09-21 (#3753)",
    "prose_home": "s3://matthew-life-platform/config/coaching/TRAINING_PROGRAM_v0.3.md",
    "note": "Owner switched to v0.4 Upper/Lower, order-based, on 2026-09-23 ~20:10 PT. v0.3 was never run as a block: its first session (Thu 2026-09-24) was superseded the evening before.",
}

SPLIT_DECISION: dict[str, Any] = {
    "chosen": "full_body",
    "rejected": ["ppl (TRAINING_PROGRAM.md v0.2, six lifting days — never approved)", "upper/lower/engine (TRAINING_PROGRAM.md v0.1)"],
    "provenance": "owner",
    "stated": "2026-09-21",
    "supersedes": {
        "ruling": "PPL with a high-frequency big-3",
        "stated": "2026-09-19",
        "where": "#3755",
        "superseded_by": "the owner's 2026-09-21 approval of v0.3 (#3753 ruling comment, ~20:05 PT)",
    },
    "note": (
        "Retention was excellent in 2024–25 (trough DEXA 160.9 lb lean at 15.6 %); the COST was 100–196 sets/wk with loads held "
        "flat. v0.3 keeps the retention and cuts the cost: the minimum effective dose (Bickel 2011 — one-third of building volume "
        "maintains strength, one-ninth maintains size), deficit-adjusted MEV–MAV never MRV, each anchor pattern 2×/wk, loads that "
        "HOLD. Six lifting days on a load wave (v0.2) manufactured failures that raised calories for the wrong reason. Both dates are "
        "recorded so a reader of #3755 sees the PPL ruling was real and was overtaken, not ignored."
    ),
}

ACCESSORY_POOL: dict[str, list[str]] = {
    "full": [
        "cable_chest_fly",
        "db_lateral_raise",
        "reverse_pec_deck",
        "cable_tricep_pushdown",
        "db_curl",
        "leg_curl",
        "calf_raise_machine",
        "machine_crunch",
    ],
}
"""The pool the block's 2–3 accessories per session are chosen FROM at block start (machines/cables only); not a rotation menu."""

SCHEDULE: dict[str, dict[str, Any]] = {
    "0": {"archetype": "full", "session_role": "heavy", "label": "Monday full-body HEAVY (AM) + walk (PM)"},
    "1": {"archetype": "aerobic", "label": "Tuesday walk — the lightest walking day, after the heavy session"},
    "2": {"archetype": "full", "session_role": "moderate", "label": "Wednesday full-body MODERATE (AM) + walk (PM)"},
    "3": {"archetype": "aerobic", "label": "Thursday walk"},
    "4": {"archetype": "full", "session_role": "heavy_moderate", "label": "Friday full-body HEAVY-MODERATE (AM) + walk (PM)"},
    "5": {
        "archetype": "full",
        "session_role": "optional_fourth",
        "optional": True,
        "gate": "only after two consecutive green recovery days; the first thing dropped in a bad week",
        "label": "Saturday OPTIONAL 4th full-body (only after two green recovery days) + walk",
    },
    "6": {"archetype": "aerobic", "label": "Sunday walk"},
}

HEVY_FOLDER = "Full Body"
"""The Hevy routine folder v0.3 sessions are filed in. `mcp.hevy_routine_commit_report.
FOLDER_BY_ARCHETYPE['full']` still names it, so a v0.3 routine re-committed from history files where it always did."""

SESSION_TEMPLATES: dict[str, dict[str, Any]] = {
    "heavy": {
        "anchors": [["squat", "heavy"], ["bench", "heavy"], ["row", "heavy"], ["vertical_pull", "moderate"]],
        "anchor_sets": {"vertical_pull": 2},
        "accessories": ["leg_curl", "cable_tricep_pushdown", "db_curl"],
    },
    "moderate": {
        "anchors": [["hinge", "moderate"], ["overhead_press", "moderate"], ["vertical_pull", "moderate"], ["squat", "moderate"]],
        "anchor_sets": {"vertical_pull": 2},
        "accessories": ["cable_tricep_pushdown", "db_curl", "calf_raise_machine"],
    },
    "heavy_moderate": {
        "anchors": [["hinge", "heavy"], ["overhead_press", "heavy"], ["bench", "moderate"], ["row", "moderate"]],
        "accessories": ["machine_crunch", "cable_chest_fly"],
    },
    "optional_fourth": {
        "anchors": [["squat", "moderate"], ["bench", "moderate"], ["row", "moderate"], ["vertical_pull", "moderate"]],
        "accessories": [],
    },
}
"""Per role: the anchor exposures (pattern, intensity) and the block-fixed accessories.

The three required roles train every pattern exactly twice (held by a test); the optional
fourth is anchors-only at moderate intensity and is EXTRA — it is never counted toward the
2x/wk, so skipping it costs nothing the program depends on. Accessories come from
`ACCESSORY_POOL['full']`, fixed per role for the block (`ROTATION_RULE`).

`anchor_sets` (#4090) overrides a MODERATE exposure's set count for one pattern. Vertical
pull runs 2 sets, not 3: row + pulldown at 3 each put back at 12 hard sets/wk against the
redline's 6–10. The lateral raise left the heavy day for the same reason (delts 8 vs 4–6 —
the overhead press already gives them 6); an arm pair took its place, which keeps the week
at 50 sets and puts arms at 4 each. `weekly_sets_by_muscle` is the sum a test holds."""

SESSION_DISTRIBUTION_PROVENANCE: dict[str, Any] = {
    "provenance": "platform-proposed",
    "stated": "2026-09-22",
    "issue": "#4064",
    "note": (
        "§3 fixes the ROLES (heavy / moderate / heavy-moderate), the 2x/wk per anchor and the rep scheme; it does not say which "
        "anchor lands on which day. This placement puts squat and hinge heavy on different days, gives each role four anchor "
        "exposures plus 2–3 accessories at 2 sets (16–17 sets, inside the 18-set ceiling), and totals 50 hard "
        "sets/wk — the floor of §3's 50–65. Vertical pull is never heavy (pulldowns rarely are) and runs 2 sets per exposure so "
        "back sits at 10, the top of the 6–10 redline (#4090). Nobody has ratified the placement."
    ),
}

# ── the BLOCK CALENDAR (#4064) — v0.3's weekday placement, never run ─────────
# Owner, 2026-09-22 (#4064): block 1 starts Thursday 2026-09-24 — Thu 09-24, Sat 09-26,
# Mon 09-28 — and then runs Mon/Wed/Fri. Retired twice: #4110 replaced weekday placement with
# an ORDER (a walk audible postpones, never skips), and #4147 replaced the program itself.
BLOCK_CALENDAR: dict[str, Any] = {
    "block_1_start": "2026-09-24",
    "opening_sessions": ["2026-09-24", "2026-09-26", "2026-09-28"],
    "steady_weekdays": [0, 2, 4],  # Mon / Wed / Fri, 0 = Monday
    "session_roles": ["heavy", "moderate", "heavy_moderate"],
    "sessions_per_week": 3,
    "weeks_per_block": 6,
    "optional_fourth_weekday": 5,  # Saturday, weeks >= 2, never in a deload week
    "provenance": "owner",
    "stated": "2026-09-22",
    "issue": "#4064",
    "superseded": SUPERSEDED,
    "note": (
        "Dates are the owner's (#4064). Reading 'then Mon/Wed/Fri' as the CONTINUOUS sequence (Wed 09-30 follows Mon 09-28) rather "
        "than restarting on Mon 10-05 is the platform's reading — the alternative leaves a 7-day gap after week 1. SUPERSEDED: "
        "weekday placement by #4110's order, the program by v0.4 (#4147). `block_1_start` is still read by `load_ramp` as the "
        "detraining-discount anchor date, and equals v0.4's sequence start."
    ),
}
