"""program_structure.py — the training program as DATA the engine reads (#3755).

WHY THIS EXISTS

The owner reported little exercise diversity in week 1 of cycle 17. Repetition of anchor
lifts is by design — progressive overload needs the same bar back under you — but nobody
had ever decided WHICH movements are the anchors, whether the accessory layer rotates, or
whether the upper/lower/engine grid in the owner-private `TRAINING_PROGRAM.md` (v0.1,
marked "redline freely") is the right structure at all. The owner-private blueprint
documents a DIFFERENT structure working for him last time: high-frequency mixed training,
the big three several times a week, AM lift + PM easy cardio. Two documents sat side by
side and had never been argued against each other.

The prose half of that argument is not this file: the red-team record and the plan text
live in the owner-private coaching home (`s3://matthew-life-platform/config/coaching/`).
THIS file is the machine-readable half — the acceptance box that says the anchors and the
accessory layer must be "data the engine reads (not prose), so 'is the accessory layer
rotating' is a computed check in the constraint block".

WHY A MODULE AND NOT config/training_week.json

`config/*.json` is NOT staged into the Lambda bundle (`build_bundle.stage_tree` stages
food_vocabulary/personas/coaches only), so a repo-side edit to a config file is INERT at
runtime — #3675, #3671, and the same reason `owner_redlines.py` and
`training_context_registry.py` are modules. The engine read `training_week.json` from S3
at runtime until this program went ACTIVE. A program the engine must obey ships in the
bundle or it does not ship.

Both readers reach the week grid through ONE seam (`training.program_seam.
resolve_week_grid`), so there is exactly one place that decides module-vs-JSON and exactly
one answer. The seam names its source in its result; it never silently substitutes.

STATUS: ACTIVE since 2026-09-21 — the owner approved v0.3 (gate:owner, #3753/#3755;
"yes i approve it", ~20:05 PT). From that date the seam serves THIS module's week grid and
`plan_engine.constraint_block` reports the program as ACTIVE. v0.2 (PPL, six lifting days,
drafted 2026-09-20) was never approved; the owner's 2026-09-19 PPL ruling on #3755 is
superseded by his 2026-09-21 approval of v0.3 — see `SPLIT_DECISION`, which records both
dates. While it was False the seam served the live JSON grid unchanged and the block said
PROPOSED — the same posture #3753 and #3715 took, for the same reason: an unratified
program must not steer a prescription.

PROVENANCE VOCABULARY (ADR-105 — every number says where it came from)

  "owner"             — he chose it, on the date in `stated`.
  "owner-history"     — mined from his own logged history / the blueprint.
  "population-derived"— from training literature or a red-team seat's practice, NOT from
                        his own variance.
  "platform-proposed" — the PLATFORM picked this number and nobody has ratified it.
                        The weakest label on the board and it is used deliberately.

WHAT THIS FILE REFUSES TO DO

It does not restate the rate target, the protein floor, the walking floor or the load
rules. Those are `owner_redlines.REDLINES` and there is one home for each. What it DOES do
is name, in `summary()["conflicts"]` (computed by `program_conflicts.conflicts()`), where
this program contradicts something already stated — and a program that quietly overrode a
stated redline would be the worst possible outcome of this issue. Under v3 the
lifting-frequency conflict is gone by computation, not by deletion (three or four days
against a 3–4 redline); the barbell-anchors-vs-skill-ceiling conflict is likewise resolved
for the bench anchor — the owner ruled 2026-09-23 (#4080, option B) that the four core
anchor pattern families (squat, hinge, bench, row) are EXEMPT from the interim
`skill_ceiling` of 2 (`program_conflicts.ANCHOR_SKILL_CEILING_RULING`); accessories and
every non-exempt pattern stay capped, and `program_conflicts.conflicts()` still reports the
family-by-family state rather than asserting it.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from training import program_conflicts

ACTIVE = True
"""True since 2026-09-21: the owner approved v0.3 (#3753/#3755, gate:owner satisfied)."""

LAST_REVIEWED_BY_OWNER: str | None = "2026-09-21"
"""ISO date the owner last read this program. None means never."""

PROGRAM_VERSION = "0.3"
ISSUE = "#3755"
PROSE_HOME = "s3://matthew-life-platform/config/coaching/TRAINING_PROGRAM_v0.3.md"

SPLIT = "full_body"
"""Three full-body sessions a week (heavy / moderate / heavy-moderate) on non-consecutive
days, an optional fourth only after two green recovery days, walking every day.

The STRUCTURE decision is the owner's (v0.3 approved 2026-09-21, superseding his 2026-09-19
PPL ruling); the frequency NUMBER under each anchor below is population-derived and says so.
"""

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


# ── the anchors: six PATTERN FAMILIES, each 2×/wk ────────────────────────────
# A pattern, not a movement id, because the specific bar is substitutable and the pattern
# is not: `leg_press` and a safety-bar squat are the same anchor for the purpose of "did
# the squat pattern get trained twice this week", and treating them as two different
# movements is exactly how a program reports diversity it does not have.
#
# `hevy_title_hints` are lower-cased substrings matched against the exercise NAME on the
# performed Hevy record — that is the only identifier the wire carries (the DDB hevy row's
# `exercises[].name`). Catalog keys name curated movements; a key the catalog does not
# carry is reported by `program_conflicts.catalog_gaps()` rather than left for someone to
# discover at the rack (since #4108/#4124 every anchor key exists — the gap map is empty). The generator selects by `primary_muscle`, so `primary_muscles`
# here is how a pattern becomes REACHABLE on a given day (see `anchor_reachability()`).
_FREQ_NOTE = (
    "2x/wk per pattern is the red team's minimum-effective-dose frequency (S&C coach, 2026-09-22; Bickel 2011) at 6–10 hard "
    "sets/muscle/wk; it is NOT derived from Matthew's own session-to-session variance and must say so wherever it fires "
    "(ADR-105). Re-derive it from his own data once cycle 17 has enough anchor-lift sessions to estimate one."
)

ANCHORS: dict[str, dict[str, Any]] = {
    "squat": {
        "pattern": "knee-dominant squat (SSB / high-bar; leg press as the listed fallback at 316 lb)",
        "frequency_per_week": {"low": 2, "high": 2, "provenance": "population-derived", "note": _FREQ_NOTE},
        # #4108 catalog keys (2026-09-23): Squat (Barbell) ×85 and Front Squat ×7 are what he has trained; §3's SSB /
        # high-bar are not in his Hevy history. Barbell first per the owner's #4080 option B; machine/DB stay as fallbacks.
        "catalog_keys": ["squat_barbell", "front_squat", "leg_press", "goblet_squat"],
        "hevy_title_hints": ["squat", "leg press", "hack squat"],
        "primary_muscles": ["quadriceps", "glutes"],
        "provenance": "owner",
        "stated": "2026-09-21",
        "note": (
            "v0.3 anchor. §3's safety-bar / high-bar squat are not in his Hevy history, so the #4108 catalog carries neither; "
            "the barbell squat (tier 3) resolves first because the squat anchor is EXEMPT from the skill_ceiling of 2 (owner "
            "ruling 2026-09-23, #4080 — `program_conflicts.ANCHOR_SKILL_CEILING_RULING`). `leg_press` (tier 1) and "
            "`goblet_squat` (tier 2) stay listed as the fallbacks a non-exempt ceiling (the Minimum Viable Session) reaches."
        ),
    },
    "hinge": {
        "pattern": "hip hinge — TRAP BAR until ≤ 275 lb; the conventional pull is gated by bodyweight",
        "frequency_per_week": {"low": 2, "high": 2, "provenance": "population-derived", "note": _FREQ_NOTE},
        # #4108: the catalog key is `deadlift_trap_bar` (Deadlift (Trap bar) ×14); §3 keeps the trap bar until <= 275 lb.
        "catalog_keys": ["deadlift_trap_bar", "machine_hip_thrust", "leg_curl"],
        "hevy_title_hints": ["deadlift", "romanian deadlift", "rdl", "good morning", "back extension", "hip thrust", "trap bar"],
        "primary_muscles": ["hamstrings", "glutes"],
        "conventional_pull_gate_lb": 275,
        "provenance": "owner",
        "stated": "2026-09-21",
        "note": (
            "v0.3 anchor. `owner_redlines.REDLINES['load_anchoring']['trap_bar_until_lb']` is the one home for the 275 gate — the "
            "250–289 conventional pull in his record was set at 260-lb geometry. `deadlift_trap_bar` (tier 3) resolves first because "
            "the hinge anchor is EXEMPT from the skill_ceiling of 2 (owner ruling 2026-09-23, #4080 — "
            "`program_conflicts.ANCHOR_SKILL_CEILING_RULING`); `machine_hip_thrust` / `leg_curl` stay listed as the fallbacks."
        ),
    },
    "bench": {
        "pattern": "horizontal press",
        "frequency_per_week": {"low": 2, "high": 2, "provenance": "population-derived", "note": _FREQ_NOTE},
        "catalog_keys": ["barbell_bench_press", "db_bench_press_flat", "machine_chest_press", "incline_db_press"],
        "hevy_title_hints": ["bench press", "chest press"],
        "primary_muscles": ["chest"],
        "provenance": "owner",
        "stated": "2026-09-21",
        "note": (
            "v0.3 anchor. `barbell_bench_press` is skill_tier 3; the bench anchor is EXEMPT from the week grid's skill_ceiling of "
            "2 (owner ruling 2026-09-23, #4080) — see `program_conflicts.ANCHOR_SKILL_CEILING_RULING` and `.conflicts()`."
        ),
    },
    "row": {
        "pattern": "horizontal pull",
        "frequency_per_week": {"low": 2, "high": 2, "provenance": "population-derived", "note": _FREQ_NOTE},
        "catalog_keys": ["machine_row", "one_arm_db_row"],
        "hevy_title_hints": ["row"],
        "primary_muscles": ["back"],
        "provenance": "owner",
        "stated": "2026-09-21",
        "note": "v0.3 anchor (new — v0.2 had the big three only). 'Rowing machine' is cardio, not this pattern: `classify_movement` checks the cardio hints first.",
    },
    "overhead_press": {
        "pattern": "vertical press",
        "frequency_per_week": {"low": 2, "high": 2, "provenance": "population-derived", "note": _FREQ_NOTE},
        "catalog_keys": ["machine_shoulder_press", "db_shoulder_press"],
        "hevy_title_hints": ["overhead press", "shoulder press", "military press", "push press"],
        "primary_muscles": ["shoulders"],
        "provenance": "owner",
        "stated": "2026-09-21",
        "note": "v0.3 anchor (new).",
    },
    "vertical_pull": {
        "pattern": "vertical pull",
        "frequency_per_week": {"low": 2, "high": 2, "provenance": "population-derived", "note": _FREQ_NOTE},
        "catalog_keys": ["lat_pulldown"],
        "hevy_title_hints": ["pulldown", "pull-up", "pull up", "pullup", "chin-up", "chin up"],
        "primary_muscles": ["back"],
        "provenance": "owner",
        "stated": "2026-09-21",
        "note": "v0.3 anchor (new). Shares `back` with the row, so a back budget of 5 sets splits across two movements and can serve both patterns in one session.",
    },
}

CORE_ANCHORS: tuple[str, ...] = ("bench", "row", "squat", "hinge")
"""The four the strength tripwire reads (`owner_redlines` `anchor_lift_strength_drop`: 2 of 4 core anchors)."""


# ── the accessory layer: FIXED for the block ─────────────────────────────────
# v0.3 §3: "accessories 8–15 at RIR 1–2, 2–3 per session, machines/cables, none added
# after week 1, first thing dropped on a bad day". The v0.2 rule ("no accessory repeats
# within 14 days") is RETIRED — under this program an accessory that repeats week to week
# is the design, and an accessory that APPEARS mid-block is the defect. The computed check
# below (`accessory_rotation`, name kept for its callers) therefore measures drift —
# movements new to the trailing week that the prior week did not carry — rather than
# repeats. Repeats are still reported, as a measurement, not a verdict.
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

ROTATION_RULE: dict[str, Any] = {
    "rule": "accessories are FIXED for the 6-week block: 2–3 per session, 2 sets, machines/cables, none added after week 1; the set changes only at a block boundary",
    "window_days": 14,
    "block_weeks": 6,
    "per_session": [2, 3],
    "sets_each": 2,
    "anchors_exempt": True,
    "provenance": "population-derived",
    "window_provenance": "platform-proposed",
    "stated": "2026-09-22",
    "note": (
        "The RULE is the red team's (S&C coach, 2026-09-22; approved by the owner 2026-09-21) and replaces v0.2's platform-proposed "
        "14-day no-repeat rotation. The 14-day measurement WINDOW is still the platform's choice — two passes of the week, so a fixed "
        "set shows each accessory on two days and an addition shows as a movement the first week did not carry. Since #4064 the "
        "block calendar (`BLOCK_CALENDAR`) records the boundaries; an addition is still reported as drift, and the honesty line names "
        "a boundary that falls inside the window, where the addition is legitimate."
    ),
}


# ── the day shape ────────────────────────────────────────────────────────────
DAY_SHAPE: dict[str, Any] = {
    "am": "lift on the three (optionally four) full-body days — the hard, loaded work; ~55–70 min",
    "pm": "easy walking EVERY day (Zone 2, ≤ 105 bpm; 2–3 walks, none over 75 min; conversational, never intervals)",
    "optional_fourth": "a fourth full-body session only after two consecutive green recovery days; the first thing dropped in a bad week",
    "cardio_placement": "no walking in the 2 h before lifting; the lightest walking day follows the heavy session; cycling ≤ 2 h/wk as the knee-sparing substitute",
    "provenance": "owner-history",
    "stated": "2026-06-19",
    "note": (
        "The owner-private blueprint records AM lift + PM easy cardio as the pattern during the campaign that held, and the v0.3 "
        "historian shows the RATE was made by the walking (16–19 h/wk in the first nine weeks). The WALKING FLOOR and targets are not "
        "restated here — one home, owner_redlines.REDLINES['walking_floor_hr_wk']."
    ),
    "not_expressible_in_week_grid": (
        "training_week.json's `schedule` holds one archetype per day. The PM walking is therefore NOT in the grid — walking days carry "
        "the `aerobic` archetype and lifting days carry `full`; a consumer that wants the two-a-day shape must read DAY_SHAPE. Making "
        "it expressible is a schema change to the grid and to every reader of it, deliberately not smuggled into this issue."
    ),
}


# ── the week grid ────────────────────────────────────────────────────────────
# MUST return the same top-level shape `config/training_week.json` provides — the seam
# hands this dict to `routine_generator.generate_routines`, which indexes it directly.
# `tests/test_program_structure_3755.py::test_week_grid_keys_equal_the_json_keys` holds
# the two key sets equal so a drift here is a red test, not a KeyError in a Lambda.
_ARCHETYPE_TARGETS: dict[str, list[str]] = {
    "full": ["chest", "back", "shoulders", "quadriceps", "hamstrings", "glutes"],
    "aerobic": [],
    "mobility": [],
    "rest": [],
}

_SCHEDULE: dict[str, dict[str, Any]] = {
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

# Every value below that DIFFERS from the live JSON grid, and why. A changed ceiling with
# no recorded reason is a number nobody owns.
WEEK_GRID_PROVENANCE: dict[str, dict[str, Any]] = {
    "schedule": {
        "changed_from": "upper / aerobic / lower / mobility / upper / full / rest",
        "provenance": "owner",
        "stated": "2026-09-21",
        "note": "v0.3: three full-body sessions on non-consecutive days (Mon / Wed / Fri), an optional fourth flagged `optional` (Sat), walking every other day as `aerobic`.",
    },
    "session_set_ceiling": {
        "changed_from": 25,
        "value": 18,
        "provenance": "population-derived",
        "stated": "2026-09-22",
        "note": (
            "v0.3 §3: 12–18 hard sets per session (four anchor exposures at 3 sets + 2–3 accessories at 2 sets). Six landmark muscles at "
            "MEV//2 each would ask for ~23 sets on a fresh week, so the generator now trims budgets proportionally to this ceiling and "
            "records the trim in the rationale — the ceiling is enforced, not assumed."
        ),
    },
    "session_minutes_ceiling": {
        "changed_from": 75,
        "value": 70,
        "provenance": "population-derived",
        "stated": "2026-09-22",
        "note": "v0.3 §3: 55–70 min. The Minimum Viable Session (anchors only, ~25 min) is `floor_session_minutes`.",
    },
    "weekly_volume_cap_per_muscle": {
        "value": 22,
        "provenance": "unchanged",
        "note": (
            "The absolute fail-safe, unchanged. The v0.3 TARGET is 6–10 hard sets/muscle/wk and it has one home — "
            "owner_redlines.REDLINES['lifting_sessions_per_wk']['sets_per_muscle_wk'] — with `volume_ceiling` as its tripwire. Three "
            "sessions at ≤18 sets across six muscles bound the week at ~9/muscle by arithmetic; the cap never binds under this program."
        ),
    },
    "skill_ceiling": {
        "value": 2,
        "provenance": "unchanged",
        "note": (
            "Still 2 for accessories and every non-exempt pattern. The four core anchor pattern families (squat, hinge, bench, "
            "row) are EXEMPT from it (owner ruling 2026-09-23, #4080, option B) — see "
            "`program_conflicts.ANCHOR_SKILL_CEILING_RULING` and `program_conflicts.conflicts()`."
        ),
    },
    "floor_session_minutes": {
        "changed_from": 20,
        "value": 25,
        "provenance": "population-derived",
        "stated": "2026-09-22",
        "note": "v0.3 §3's Minimum Viable Session: anchors only, top set + one back-off, ~25 min.",
    },
    "z2_floor_minutes": {
        "value": 90,
        "provenance": "unchanged",
        "note": (
            "Deliberately NOT raised to match the walking floor. That floor has one home (owner_redlines) and this knob drives a "
            "different thing — the portfolio guard that caps the strength budget. Two numbers for the same concept in two files is the "
            "defect, not the fix."
        ),
    },
}


def week_grid() -> dict[str, Any]:
    """The v0.3 week, in the exact shape `config/training_week.json` provides.

    Served by `program_seam.resolve_week_grid` ONLY when `ACTIVE` is True. The schedule
    entries carry two keys the JSON never had — `session_role` and `optional` — which the
    generator reads for the routine's rationale and title; every other consumer indexes
    `archetype` and `label` only, as before.
    """
    return {
        "_comment": (
            f"TRAINING_PROGRAM v{PROGRAM_VERSION} ({SPLIT}: three full-body sessions + optional fourth, anchors 2x/wk, loads hold) "
            f"as the engine reads it. Generated by lambdas/training/program_structure.py ({ISSUE}); the prose lives at {PROSE_HOME}. "
            "day_of_week is 0=Monday .. 6=Sunday; archetype names are handled generically by routine_generator."
        ),
        "_version": 3,
        "schedule": {k: dict(v) for k, v in _SCHEDULE.items()},
        "archetype_targets": {k: list(v) for k, v in _ARCHETYPE_TARGETS.items()},
        "session_set_ceiling": 18,
        "session_minutes_ceiling": 70,  # drift-ok: MINUTES per lifting session, not the ADR-133 AI budget ceiling in dollars
        "weekly_volume_cap_per_muscle": 22,
        "skill_ceiling": 2,
        "re_entry_days_threshold": 7,
        "z2_floor_minutes": 90,
        "floor_session_set_count": 6,
        "floor_session_minutes": 25,
        "exercise_notes_mode": "one_best_line",
        "_exercise_notes_lookback_note": (
            "#3708: the runtime window is floored in code at exercise_history.FLOOR_LOOKBACK_DAYS — this value can "
            "widen it, never narrow it below the floor. Unchanged by v0.3."
        ),
        "exercise_notes_lookback_days": 3650,
        "_notes": [
            f"v{PROGRAM_VERSION}: split={SPLIT} (owner, approved 2026-09-21; supersedes the 2026-09-19 PPL ruling); six anchor patterns 2x/wk (population-derived, not his variance).",
            "Loads HOLD: start 60–65 % of band-anchored e1RM after the detraining discount, ramp ~5 %/wk to week 6, ≤ 85 % until week 8, then hold; gains taken only when offered. One home: owner_redlines.REDLINES['lifting_sessions_per_wk'].",
            "The PM walking is NOT in this grid — `schedule` holds one archetype per day; walking days are `aerobic`. Read program_structure.DAY_SHAPE.",
            "Saturday is the OPTIONAL fourth session (`optional: True`, gate: two consecutive green recovery days). The generator flags it in the title and rationale; it does not gate it.",
            "session_set_ceiling 25 -> 18 and session_minutes_ceiling 75 -> 70 are v0.3 §3 (12–18 sets, 55–70 min); the weekly cap of 22 is the unchanged fail-safe and never binds here.",
            "The generator selects by muscle, not by pattern: a `back` budget reaches row OR vertical pull. See program_structure.anchor_reachability() for what the grid can and cannot guarantee.",
            "RESOLVED against redlines v3 (approved 2026-09-21): 3–4 lifting days sits inside owner_redlines.REDLINES['lifting_sessions_per_wk'] (3–4); `program_conflicts.conflicts()` computes it rather than asserting it.",
        ],
    }


def lifting_days() -> list[str]:
    """Day-of-week keys ('0'..'6') carrying a lifting archetype, in order."""
    return [k for k, d in _SCHEDULE.items() if d["archetype"] not in ("rest", "aerobic", "mobility")]


def anchor_reachability() -> dict[str, dict[str, Any]]:
    """For each anchor pattern: the lifting days whose targets include one of its primary
    muscles — i.e. the days the generator CAN put that pattern on. 'Reachable' is not
    'guaranteed': selection is by muscle, and `back` reaches row or vertical pull."""
    out: dict[str, dict[str, Any]] = {}
    for name, anchor in ANCHORS.items():
        days = [k for k in lifting_days() if set(anchor["primary_muscles"]) & set(_ARCHETYPE_TARGETS[_SCHEDULE[k]["archetype"]])]
        required_days = [k for k in days if not _SCHEDULE[k].get("optional")]
        out[name] = {
            "reachable_days": days,
            "reachable_days_excluding_optional": required_days,
            "frequency_target": anchor["frequency_per_week"]["low"],
            "reachable_at_target": len(required_days) >= anchor["frequency_per_week"]["low"],
        }
    return out


# ── the full-body SESSION: what §3 prescribes on each role (#4064) ───────────
# Before #4064 the week grid carried `session_role` and the generator only printed it in
# the rationale: a v0.3 "heavy" day was built by the v0.1 muscle-budget selector (every
# landmark muscle at MEV//2, trimmed to the ceiling), with no top set, no back-offs, no
# heavy/moderate rep ranges and no fixed accessories. The role was a label on a session
# §3 did not describe. This is the machine-readable half of §3's session: which anchor
# patterns each role trains, at which intensity, and which accessories ride with it.
#
# The DISTRIBUTION below (which anchor lands on which role, heavy or moderate) is the
# platform's choice under three constraints §3 does state — each pattern 2x/wk, a heavy /
# moderate / heavy-moderate week, and squat and hinge never heavy on the same day — so it
# is labelled `platform-proposed` and `SESSION_DISTRIBUTION_PROVENANCE` says so wherever
# the plan is read.
HEVY_FOLDER = "Full Body"
"""The Hevy routine folder v0.3 sessions are filed in. `mcp.hevy_routine_commit_report.
FOLDER_BY_ARCHETYPE['full']` must name the same string (held by a test); the folder is
found-or-created at the first commit (`ensure_folder`), never created ahead of time."""

EXPOSURES: dict[str, dict[str, Any]] = {
    "heavy": {
        "top_sets": 1,
        "reps": [4, 6],
        "top_rpe": [7, 8],
        "back_off_sets": 2,
        "back_off_pct": -10,
        "rest_seconds": 180,
        "cue": "HEAVY: 1 top set of 4–6 @ RPE 7–8, then 2 back-offs at −10 % of the top set.",
    },
    "moderate": {"sets": 3, "reps": [6, 10], "rest_seconds": 120, "cue": "MODERATE: 3 sets of 6–10, leave 2–3 in the tank."},
    "accessory": {"sets": 2, "reps": [8, 15], "rir": [1, 2], "rest_seconds": 90, "cue": "ACCESSORY: 2 sets of 8–15 at RIR 1–2."},
}
"""v0.3 §3's rep scheme as numbers. The one PROSE home is `owner_redlines.REDLINES
['lifting_sessions_per_wk']['rep_scheme']`; a test holds every number here to that string."""

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

DELOAD_RULE: dict[str, Any] = {
    "rule": "every 6th week of the calendar: −30 % sets (rounded to whole sets, accessories and back-offs first), loads held",
    "provenance": "owner",
    "one_home": "owner_redlines.REDLINES['lifting_sessions_per_wk']['deload']",
}


def _deload_cfg() -> dict[str, Any]:
    from training import owner_redlines

    return dict(owner_redlines.REDLINES["lifting_sessions_per_wk"]["deload"])


# ── the BLOCK CALENDAR (#4064) ───────────────────────────────────────────────
# Owner, 2026-09-22 (#4064): block 1 starts Thursday 2026-09-24 — Thu 09-24, Sat 09-26,
# Mon 09-28 — and then runs Mon/Wed/Fri. The session SEQUENCE is continuous: after the
# opening three, the next Mon/Wed/Fri day is Wed 09-30, so every program week from week 2
# is Wed → Fri → Mon (heavy → moderate → heavy-moderate) and no session is skipped or
# doubled at the seam. A program week is three consecutive sessions; it runs from its first
# session to the day before the next week's first session (week 1: Thu 09-24 .. Tue 09-29;
# week 2: Wed 09-30 .. Tue 10-06). Deload every 6th week, from `owner_redlines` (one home).
#
# The weekday grid above (`_SCHEDULE`) still answers for any date BEFORE block 1 — and it is
# what the JSON-era v0.2 path never sees at all: this calendar is consulted only when the
# program is ACTIVE and the seam serves the module grid.
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
    "note": (
        "Dates are the owner's (#4064). Reading 'then Mon/Wed/Fri' as the CONTINUOUS sequence (Wed 09-30 follows Mon 09-28) rather "
        "than restarting on Mon 10-05 is the platform's reading — the alternative leaves a 7-day gap after week 1."
    ),
}

_WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_ROLE_LABEL = {"heavy": "HEAVY", "moderate": "MODERATE", "heavy_moderate": "HEAVY-MODERATE", "optional_fourth": "OPTIONAL 4th"}


def _day(day: str):
    from common.pacific_time import parse_day_key

    parsed = parse_day_key(day)
    if parsed is None:
        raise ValueError(f"not a YYYY-MM-DD day key: {day!r}")
    return parsed


def _session_dates(until: str | None = None, n_sessions: int | None = None) -> list[str]:
    """The calendar's session dates in order — every one on or before `until`, or the first
    `n_sessions`. Exactly one of the two bounds must be given."""
    if (until is None) == (n_sessions is None):
        raise ValueError("_session_dates needs exactly one of until / n_sessions")
    cal = BLOCK_CALENDAR
    out = list(cal["opening_sessions"])
    stop = _day(until) if until else None
    cursor = _day(out[-1])
    steady = set(cal["steady_weekdays"])
    while True:
        if n_sessions is not None and len(out) >= n_sessions:
            return out[:n_sessions]
        if stop is not None and cursor >= stop:
            return [d for d in out if _day(d) <= stop]
        cursor = cursor + _dt.timedelta(days=1)
        if cursor.weekday() in steady:
            out.append(cursor.isoformat())


def block_calendar(weeks: int = 13) -> list[dict[str, Any]]:
    """The first `weeks` program weeks: dates, roles, block number and deload flag.

    Pure arithmetic over `BLOCK_CALENDAR` and the redline's deload period — no I/O, no
    stored rows, so the calendar can never disagree with the program module it came from.
    """
    per = BLOCK_CALENDAR["sessions_per_week"]
    roles = BLOCK_CALENDAR["session_roles"]
    every = int(_deload_cfg()["every_nth_week"])
    dates = _session_dates(n_sessions=weeks * per + 1)
    out: list[dict[str, Any]] = []
    for w in range(weeks):
        wk = w + 1
        sess = dates[w * per : (w + 1) * per]
        out.append(
            {
                "week": wk,
                "block": (wk - 1) // BLOCK_CALENDAR["weeks_per_block"] + 1,
                "deload": wk % every == 0,
                "starts": sess[0],
                "ends": (_day(dates[(w + 1) * per]) - _dt.timedelta(days=1)).isoformat(),
                "sessions": [
                    {"date": d, "weekday": _WEEKDAY_NAMES[_day(d).weekday()], "session_role": roles[i]} for i, d in enumerate(sess)
                ],
            }
        )
    return out


def calendar_entry(day: str) -> dict[str, Any] | None:
    """The schedule entry the block calendar assigns to `day`, or None before block 1.

    Same shape as a `week_grid()['schedule']` entry (archetype / label / session_role /
    optional) plus `week`, `block`, `deload` and `source: "block_calendar"`, so the
    generator reads it exactly where it used to read the weekday grid.
    """
    target = _day(day)
    if target < _day(BLOCK_CALENDAR["block_1_start"]):
        return None
    per = BLOCK_CALENDAR["sessions_per_week"]
    roles = BLOCK_CALENDAR["session_roles"]
    every = int(_deload_cfg()["every_nth_week"])
    dates = _session_dates(until=day)
    # the session index of the last session on or before `day`
    idx = len(dates) - 1
    week = idx // per + 1
    block = (week - 1) // BLOCK_CALENDAR["weeks_per_block"] + 1
    deload = week % every == 0
    base = {"week": week, "block": block, "deload": deload, "source": "block_calendar"}
    wd = _WEEKDAY_NAMES[target.weekday()]
    if dates and dates[-1] == day:
        role = roles[idx % per]
        return {
            **base,
            "archetype": "full",
            "session_role": role,
            "label": f"{wd} full-body {_ROLE_LABEL[role]} — week {week}, block {block}" + (" (DELOAD)" if deload else ""),
        }
    if week >= 2 and not deload and target.weekday() == BLOCK_CALENDAR["optional_fourth_weekday"]:
        return {
            **base,
            "archetype": "full",
            "session_role": "optional_fourth",
            "optional": True,
            "gate": _SCHEDULE["5"]["gate"],
            "label": f"{wd} OPTIONAL 4th full-body (only after two green recovery days) — week {week}",
        }
    return {**base, "archetype": "aerobic", "label": f"{wd} walk — week {week}, block {block}" + (" (DELOAD week)" if deload else "")}


def _deload_trim(exposures: list[dict[str, Any]], pct: int) -> dict[str, Any]:
    """Remove |pct| % of the session's sets (rounded), IN PLACE; loads are never touched.

    Round-robin, one set per pass: accessories first, then moderate anchors, then heavy
    back-offs. A top set is never removed and no exposure drops below one set — so the
    deload keeps every anchor in the session and every top set at its load.
    """
    before = sum(len(e["sets"]) for e in exposures)
    target = before - int(round(before * abs(pct) / 100.0))
    order = [e for e in exposures if e["kind"] == "accessory"]
    order += [e for e in exposures if e["kind"] == "anchor" and e["intensity"] == "moderate"][::-1]
    order += [e for e in exposures if e["kind"] == "anchor" and e["intensity"] == "heavy"][::-1]
    total = before
    progressed = True
    while total > target and progressed:
        progressed = False
        for e in order:
            if total <= target:
                break
            removable = [i for i, s in enumerate(e["sets"]) if s["kind"] != "top"]
            if len(e["sets"]) > 1 and removable:
                e["sets"].pop(removable[-1])
                total -= 1
                progressed = True
    return {"sets_before": before, "sets_after": total, "pct": pct, "loads": "held"}


def _resolve_movement(
    keys: list[str],
    catalog_movements: dict[str, Any] | None,
    skill_ceiling: int,
    taken: set[str],
    *,
    family: str | None = None,
    allow_anchor_exemption: bool = True,
):
    """The first catalog key of a pattern the generator may prescribe, in the listed order.

    `family` is the anchor pattern name ("squat", "hinge", "bench", "row", …) when this call
    is resolving one anchor's `catalog_keys`; `None` for an accessory, which never qualifies
    for the exemption below regardless of `allow_anchor_exemption`.

    When `family` is one of `program_conflicts.ANCHOR_SKILL_CEILING_RULING["exempt_families"]`
    AND `allow_anchor_exemption` is True, THIS resolution uses that ruling's
    `effective_ceiling` instead of `skill_ceiling` (owner ruling 2026-09-23, #4080,
    option B) — every other pattern and every accessory still uses `skill_ceiling` unchanged.
    `allow_anchor_exemption=False` is how a deliberately-lower ceiling (the Minimum Viable
    Session's skill_ceiling=1) opts OUT of the exemption rather than being silently raised.
    """
    if catalog_movements is None:
        return None, "movement catalog not read — the pattern is prescribed, the movement is unresolved"
    ruling = program_conflicts.ANCHOR_SKILL_CEILING_RULING
    exempt = allow_anchor_exemption and family is not None and family in ruling["exempt_families"]
    ceiling = max(int(skill_ceiling), int(ruling["effective_ceiling"])) if exempt else skill_ceiling
    skipped: list[str] = []
    for k in keys:
        m = catalog_movements.get(k)
        if m is None:
            skipped.append(f"{k} (not in catalog)")
            continue
        tier = int(m.get("skill_tier", 99))
        if tier > ceiling:
            skipped.append(f"{k} (skill_tier {tier} > ceiling {ceiling}" + (", anchor-exempt" if exempt else "") + ")")
            continue
        if k in taken:
            skipped.append(f"{k} (already in this session)")
            continue
        return k, ("skipped: " + ", ".join(skipped)) if skipped else None
    return None, "no reachable member: " + ", ".join(skipped)


def session_prescription_for_role(
    role: str,
    *,
    deload: bool = False,
    catalog_movements: dict[str, Any] | None = None,
    skill_ceiling: int = 2,
    anchor_exempt: bool = True,
) -> dict[str, Any]:
    """§3's session for one role, as data: exposures, sets (top / back_off / working), reps.

    Pure. `catalog_movements` (the movement catalog's `movements` dict) resolves each
    pattern to the first member the generator may prescribe; without it the movements are
    `None` and the result says so rather than guessing.

    `anchor_exempt` (default True): whether the four core anchor pattern families get the
    owner's skill_ceiling exemption (#4080) when resolving their movement. The Minimum
    Viable Session floor (`full_body_session.full_body_routines`, skill_ceiling=1) passes
    False deliberately — that ceiling is a separate, lower, tired-day design choice, not an
    instance of the interim Sports-Medicine ceiling the exemption targets.
    """
    tmpl = SESSION_TEMPLATES[role]
    taken: set[str] = set()
    exposures: list[dict[str, Any]] = []
    for pattern, intensity in tmpl["anchors"]:
        spec = EXPOSURES[intensity]
        key, why = _resolve_movement(
            ANCHORS[pattern]["catalog_keys"],
            catalog_movements,
            skill_ceiling,
            taken,
            family=pattern,
            allow_anchor_exemption=anchor_exempt,
        )
        if key:
            taken.add(key)
        if intensity == "heavy":
            sets = [{"kind": "top", "reps": list(spec["reps"]), "rpe": list(spec["top_rpe"])}] + [
                {"kind": "back_off", "reps": list(spec["reps"]), "pct_of_top": 100 + spec["back_off_pct"]}
                for _ in range(spec["back_off_sets"])
            ]
        else:
            n_sets = int((tmpl.get("anchor_sets") or {}).get(pattern, spec["sets"]))
            sets = [{"kind": "working", "reps": list(spec["reps"])} for _ in range(n_sets)]
        exposures.append(
            {
                "kind": "anchor",
                "pattern": pattern,
                "intensity": intensity,
                "movement_key": key,
                "resolution_note": why,
                "sets": sets,
                "rest_seconds": spec["rest_seconds"],
                "cue": spec["cue"],
            }
        )
    acc = EXPOSURES["accessory"]
    for k in tmpl["accessories"]:
        # an accessory is named by its catalog key already; without the catalog it is still
        # prescribable by that key, it just has not been checked against the skill ceiling
        key, why = _resolve_movement([k], catalog_movements, skill_ceiling, taken) if catalog_movements is not None else (k, None)
        if key:
            taken.add(key)
        exposures.append(
            {
                "kind": "accessory",
                "pattern": None,
                "intensity": "accessory",
                "movement_key": key,
                "resolution_note": why,
                "sets": [{"kind": "working", "reps": list(acc["reps"])} for _ in range(acc["sets"])],
                "rest_seconds": acc["rest_seconds"],
                "cue": acc["cue"],
            }
        )
    deload_info = None
    if deload:
        deload_info = _deload_trim(exposures, int(_deload_cfg()["sets_pct"]))
    return {
        "archetype": "full",
        "session_role": role,
        "role_label": _ROLE_LABEL[role],
        "deload": deload,
        "deload_trim": deload_info,
        "exposures": exposures,
        "total_sets": sum(len(e["sets"]) for e in exposures),
        "hevy_folder": HEVY_FOLDER,
        "distribution": SESSION_DISTRIBUTION_PROVENANCE,
    }


def planned_session(day: str, *, catalog_movements: dict[str, Any] | None = None, skill_ceiling: int = 2) -> dict[str, Any]:
    """What the program schedules on `day`: the calendar entry, and — on a lifting day — the
    §3 session. Before block 1 the weekday grid answers, and the result says which did.

    Only meaningful when the program is ACTIVE; the caller (`plan_engine`) reports the
    JSON grid instead when it is not.
    """
    entry = calendar_entry(day)
    if entry is None:
        grid = dict(_SCHEDULE[str(_day(day).weekday())])
        entry = {
            **grid,
            "source": "week_grid",
            "note": f"before block 1 ({BLOCK_CALENDAR['block_1_start']}) — the weekday grid answers",
        }
    out: dict[str, Any] = {"date": day, "program_version": PROGRAM_VERSION, **entry}
    role = entry.get("session_role")
    if entry.get("archetype") == "full" and role in SESSION_TEMPLATES:
        out["prescription"] = session_prescription_for_role(
            role, deload=bool(entry.get("deload")), catalog_movements=catalog_movements, skill_ceiling=skill_ceiling
        )
    return out


def weekly_sets_by_pattern() -> dict[str, int]:
    """Anchor sets per pattern over the three REQUIRED roles (optional fourth excluded)."""
    out: dict[str, int] = {}
    for role in BLOCK_CALENDAR["session_roles"]:
        for e in session_prescription_for_role(role)["exposures"]:
            if e["kind"] == "anchor":
                out[e["pattern"]] = out.get(e["pattern"], 0) + len(e["sets"])
    return out


REDLINE_MUSCLE_GROUPS: dict[str, dict[str, Any]] = {
    "quads": {"primary_muscles": ["quadriceps"], "range_key": "sets_per_muscle_wk"},
    "hams_glutes": {"primary_muscles": ["hamstrings", "glutes"], "range_key": "sets_per_muscle_wk"},
    "chest": {"primary_muscles": ["chest"], "range_key": "sets_per_muscle_wk"},
    "back": {"primary_muscles": ["back"], "range_key": "sets_per_muscle_wk"},
    "delts": {"primary_muscles": ["shoulders"], "range_key": "sets_per_muscle_wk_small"},
    "biceps": {"primary_muscles": ["biceps"], "range_key": "sets_per_muscle_wk_small"},
    "triceps": {"primary_muscles": ["triceps"], "range_key": "sets_per_muscle_wk_small"},
}
"""§3's per-muscle set ranges, keyed to the catalog's `primary_muscle` (#4090): 6–10 for quads,
hams/glutes, chest, back; 4–6 for delts and arms. Counted as DIRECT sets (the movement's
primary muscle) — §3's 'mostly indirect' is the pressing and pulling on top of these."""


def weekly_sets_by_muscle(catalog_movements: dict[str, Any], skill_ceiling: int = 2) -> dict[str, dict[str, Any]]:
    """Hard sets per redline muscle group over the three REQUIRED roles, with the range each
    must sit in (`owner_redlines`). The optional fourth is excluded, as in the 2x/wk count."""
    from training import owner_redlines

    lift = owner_redlines.REDLINES["lifting_sessions_per_wk"]
    by_muscle: dict[str, int] = {}
    for role in BLOCK_CALENDAR["session_roles"]:
        rx = session_prescription_for_role(role, catalog_movements=catalog_movements, skill_ceiling=skill_ceiling)
        for e in rx["exposures"]:
            muscle = (catalog_movements.get(e.get("movement_key") or "") or {}).get("primary_muscle") or "unresolved"
            by_muscle[muscle] = by_muscle.get(muscle, 0) + len(e["sets"])
    return {
        g: {"sets": sum(by_muscle.get(m, 0) for m in spec["primary_muscles"]), "range": list(lift[spec["range_key"]])}
        for g, spec in REDLINE_MUSCLE_GROUPS.items()
    }


# ── the computed check: is the accessory layer holding still? ────────────────
# Cardio blocks logged inside a Hevy session are not lifting accessories, and counting
# them would report "diversity" that is really the same treadmill every day. This list is
# deliberately NOT `walking_volume.HEVY_COUNTED_NAMES`: that one answers "does this count
# toward the walking floor" (walking/cycling only, rowing and elliptical excluded on
# purpose), which is a DIFFERENT question from "is this a lifting accessory". Sharing one
# list would create a must-agree seam between two questions that legitimately disagree.
CARDIO_NAME_HINTS: tuple[str, ...] = (
    "treadmill",
    "walking",
    "rucking",
    "running",
    "cycling",
    "stationary bike",
    "air bike",
    "echo bike",
    "assault bike",
    "rowing",
    "elliptical",
    "stair",
    "stretching",
    "mobility",
    "foam roll",
)


def _lower(name: Any) -> str:
    return str(name or "").strip().lower()


def classify_movement(name: str) -> str:
    """`anchor:<family>` | `cardio` | `accessory` for one performed Hevy exercise name.

    Cardio is checked FIRST: the `row` anchor's hint is a substring of 'rowing machine'.
    """
    nl = _lower(name)
    if not nl:
        return "cardio"  # an unnamed block is not evidence of accessory diversity
    if any(hint in nl for hint in CARDIO_NAME_HINTS):
        return "cardio"
    for family, anchor in ANCHORS.items():
        if any(hint in nl for hint in anchor["hevy_title_hints"]):
            return f"anchor:{family}"
    return "accessory"


def _shift_day(day: str, delta_days: int) -> str:
    """Shift a DATE# day key by whole days — through THE calendar-day parse (#3609: the ISO-parse
    registry is shrink-only, so a day key is never parsed with `date.fromisoformat` here)."""
    from common.pacific_time import parse_day_key

    parsed = parse_day_key(day)
    if parsed is None:
        raise ValueError(f"not a YYYY-MM-DD day key: {day!r}")
    return (parsed + _dt.timedelta(days=delta_days)).isoformat()


def _boundary_honesty(window_start: str, window_end: str) -> str:
    """The honesty line about block boundaries, read from the block calendar (#4064)."""
    lead = f"the {ROTATION_RULE['window_days']}-day window is {ROTATION_RULE['window_provenance']}"
    try:
        weeks = block_calendar(weeks=60)
    except ValueError:
        weeks = []
    starts = [w["starts"] for w in weeks if w["week"] > 1 and (w["week"] - 1) % BLOCK_CALENDAR["weeks_per_block"] == 0]
    inside = [d for d in starts if window_start < d <= window_end]
    if inside:
        return (
            f"{lead}; the block calendar puts a block boundary on {inside[0]} inside it, so an accessory added from that day "
            "is legitimate, not drift"
        )
    return f"{lead}; the block calendar puts no block boundary inside it, so an addition here is drift"


def accessory_rotation(
    *,
    window_start: str,
    window_end: str,
    hevy_workouts: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """The accessory layer over a trailing window, computed from the Hevy record.

    v0.3 fixes accessories for the block, so the computed verdict is DRIFT: accessories
    performed in the window's trailing 7 days that its earlier days did not carry. `ok`
    is True when nothing was added ("fixed") and False when something was ("drifting").
    Repeats are still counted and reported — as a measurement, not a defect.

    ADR-105: the answer carries its `n` and its window. It is a measurement of what was
    PERFORMED, not a claim about what was programmed.

    `hevy_workouts` is the DDB `USER#matthew#SOURCE#hevy` row shape the MCP readers
    already return: `{"date": "YYYY-MM-DD", "exercises": [{"name": ..., "sets": [...]}]}`.
    Passed in, never fetched here — this module has no I/O, same contract as `plan_engine`.

    `None` means the read RAISED and the verdict is `unknown`. An empty list means the
    window genuinely holds no lifting sessions, which is ALSO `unknown` — a rule over zero
    sessions is vacuously satisfied, and reporting that as `ok` is the #3767 failure
    wearing gym clothes. A window whose earlier half holds no session is `unknown` too:
    there is no prior week to have added anything to.
    """
    window = {"start": window_start, "end": window_end, "days": ROTATION_RULE["window_days"]}
    base: dict[str, Any] = {
        "rule": ROTATION_RULE["rule"],
        "rule_provenance": ROTATION_RULE["provenance"],
        "window": window,
        "program_version": PROGRAM_VERSION,
        "program_active": ACTIVE,
    }
    if hevy_workouts is None:
        return {
            **base,
            "ok": None,
            "state": "unknown",
            "n_sessions": None,
            "detail": "the Hevy record could not be read for this window — the accessory layer is unmeasured, not clear",
            "honesty": ["the accessory layer is UNKNOWN: the read failed. Never report an unreadable rule as satisfied."],
        }

    try:
        split_day = _shift_day(window_end, -6)  # the trailing 7 days start here
    except ValueError:
        split_day = window_end
    days_by_movement: dict[str, set[str]] = {}
    anchor_days: dict[str, set[str]] = {}
    cardio_names: set[str] = set()
    sessions = 0
    session_days: set[str] = set()
    early_session_days: set[str] = set()
    for row in hevy_workouts:
        exercises = row.get("exercises") or []
        if not exercises:
            continue
        day = str(row.get("date") or "")[:10]
        if not (window_start <= day <= window_end):
            continue
        sessions += 1
        session_days.add(day)
        if day < split_day:
            early_session_days.add(day)
        for ex in exercises:
            name = _lower(ex.get("name"))
            if not name:
                continue
            kind = classify_movement(name)
            if kind.startswith("anchor:"):
                anchor_days.setdefault(kind.split(":", 1)[1], set()).add(day)
            elif kind == "cardio":
                cardio_names.add(name)
            else:
                days_by_movement.setdefault(name, set()).add(day)

    if sessions == 0:
        return {
            **base,
            "ok": None,
            "state": "unknown",
            "n_sessions": 0,
            "n_session_days": 0,
            "detail": "no lifting sessions in the window — the accessory rule is vacuous here, which is not the same as satisfied",
            "honesty": ["the accessory layer is UNKNOWN: n=0 sessions in the window. A rule with nothing to check is not a pass."],
        }

    repeats = sorted(
        ({"movement": name, "n_days": len(days), "days": sorted(days)} for name, days in days_by_movement.items() if len(days) > 1),
        key=lambda r: (-r["n_days"], r["movement"]),
    )
    added = sorted(name for name, days in days_by_movement.items() if all(d >= split_day for d in days))
    distinct_accessories = len(days_by_movement)
    measurable = bool(early_session_days)
    ok: bool | None = (not added) if measurable else None
    state = "unknown" if not measurable else ("fixed" if ok else "drifting")
    return {
        **base,
        "ok": ok,
        "state": state,
        "n_sessions": sessions,
        "n_session_days": len(session_days),
        "n_early_session_days": len(early_session_days),
        "split_day": split_day,
        "distinct_accessories": distinct_accessories,
        "distinct_movements_total": distinct_accessories + len(anchor_days) + len(cardio_names),
        "anchors_trained": {family: {"n_days": len(days), "days": sorted(days)} for family, days in sorted(anchor_days.items())},
        "anchor_families_missing": sorted(set(ANCHORS) - set(anchor_days)),
        "added_in_trailing_7d": added,
        "repeats_within_window": repeats,
        "cardio_blocks_excluded": sorted(cardio_names),
        "detail": (
            f"{distinct_accessories} distinct accessory movement(s) over n={sessions} session(s) ({window_start}..{window_end}); "
            + (
                f"{len(added)} added in the trailing 7 days that the prior days did not carry; {len(repeats)} repeated (by design under v0.3)"
                if measurable
                else "no session before the trailing 7 days, so 'added' cannot be measured"
            )
        ),
        "honesty": [
            s
            for s in [
                (
                    None
                    if ACTIVE
                    else f"the accessory rule is PROPOSED ({ISSUE}, gate:owner) — this is a measurement of what happened, not a compliance verdict against an approved program"
                ),
                _boundary_honesty(window_start, window_end),
                (
                    "anchor repeats are EXEMPT by design (progressive overload) — they are reported separately under anchors_trained"
                    if anchor_days
                    else "no anchor pattern was trained in this window at all"
                ),
            ]
            if s
        ],
    }


def summary() -> dict[str, Any]:
    """The block the planner embeds — the program, its provenance, and what it has not settled."""
    return {
        "active": ACTIVE,
        "last_reviewed_by_owner": LAST_REVIEWED_BY_OWNER,
        "program_version": PROGRAM_VERSION,
        "split": SPLIT,
        "split_decision": SPLIT_DECISION,
        "prose_home": PROSE_HOME,
        "status_note": (
            f"PROPOSED — v{PROGRAM_VERSION} is drafted from the red team and the owner's own blueprint, and he has not approved it. "
            f"The engine still runs on the live config/training_week.json grid; this program is reported so a plan is auditable, "
            f"never obeyed ({ISSUE}, gate:owner)."
            if not ACTIVE
            else f"ACTIVE — owner-approved {LAST_REVIEWED_BY_OWNER}; the engine reads this program's week grid (v{PROGRAM_VERSION}, {SPLIT})."
        ),
        "anchors": ANCHORS,
        "core_anchors": list(CORE_ANCHORS),
        "anchor_reachability": anchor_reachability(),
        "lifting_days": lifting_days(),
        "accessory_pool": ACCESSORY_POOL,
        "rotation_rule": ROTATION_RULE,
        # #4064: the calendar the sessions are placed on, and the weekly anchor dose it produces
        "block_calendar": BLOCK_CALENDAR,
        "session_distribution": SESSION_DISTRIBUTION_PROVENANCE,
        "weekly_anchor_sets": weekly_sets_by_pattern(),
        "day_shape": DAY_SHAPE,
        "week_grid_provenance": WEEK_GRID_PROVENANCE,
        "anchor_skill_ceiling_exemption": program_conflicts.ANCHOR_SKILL_CEILING_RULING,
        "conflicts": program_conflicts.conflicts(),
        "population_derived_numbers": [
            f"{name}.frequency_per_week" for name, a in ANCHORS.items() if a["frequency_per_week"]["provenance"] == "population-derived"
        ]
        + [f"week_grid.{k}" for k, v in WEEK_GRID_PROVENANCE.items() if v.get("provenance") == "population-derived"],
        "platform_proposed_numbers": sorted(
            [f"week_grid.{k}" for k, v in WEEK_GRID_PROVENANCE.items() if v.get("provenance") == "platform-proposed"]
            + (["rotation_rule.window_days"] if ROTATION_RULE.get("window_provenance") == "platform-proposed" else [])
        ),
    }
