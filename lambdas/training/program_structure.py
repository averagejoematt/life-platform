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

STATUS: v0.4 ACTIVE since 2026-09-24 (#4147). The owner switched programs on 2026-09-23
(~20:10 PT; decision `DECISION#2026-09-24T03:10:59`, corrections-ledger override signal
`program_split_full_body_v0.3`): v0.3 full-body -> v0.4 UPPER/LOWER, served in ORDER —
Upper-heavy -> Lower-heavy -> Upper-volume -> Lower-volume, repeating, the next session being
the one after the last PERFORMED lift whatever the date (#4110, `training.session_sequence`).
The prose home is the owner-private `TRAINING_PROGRAM_v0.4.md` (`PROSE_HOME`, written by the
driver, never in this repo); THIS module is its machine-readable half.

v0.3 (full body, approved 2026-09-21 on #3753) is SUPERSEDED, not deleted: its definitions
live verbatim in `training.program_v03` (`SUPERSEDED_PROGRAMS`), so anything written under
it stays readable against the program it was written for. v0.2 (PPL) was never approved.
While `ACTIVE` is False the seam serves the live JSON grid unchanged and the block says
PROPOSED — an unratified program must not steer a prescription.

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

from training import program_conflicts, program_v03
from training.program_v03 import BLOCK_CALENDAR  # noqa: F401 — v0.3 history; `load_ramp.block_1_start()` reads it (#4107)

ACTIVE = True
"""True since 2026-09-21 (v0.3, #3753); v0.4 replaced v0.3 on 2026-09-24 without a gap (#4147)."""

LAST_REVIEWED_BY_OWNER: str | None = "2026-09-23"
"""ISO date the owner last read this program. None means never. v0.4 is his own switch (2026-09-23)."""

PROGRAM_VERSION = "0.4"
ISSUE = "#4147"
PROSE_HOME = "s3://matthew-life-platform/config/coaching/TRAINING_PROGRAM_v0.4.md"
"""Owner-private; the driver writes it beside v0.3's. Cited, never read by the engine."""

DECISION_SK = "DECISION#2026-09-24T03:10:59"
"""The owner's program-switch decision (2026-09-23 ~20:10 PT)."""

SUPERSEDED_PROGRAMS: dict[str, dict[str, Any]] = {"0.3": program_v03.SUPERSEDED}
"""Every program this one replaced, with the date and the decision. The definitions are in `training.program_v03`."""

SPLIT = "upper_lower"
"""Four sessions in ORDER — Upper-heavy, Lower-heavy, Upper-volume, Lower-volume — each muscle
2x/wk, walking every day. ORDER, not weekdays (#4110): a walk audible postpones, never skips.

The STRUCTURE decision is the owner's (2026-09-23, #4147); the frequency NUMBER under each
anchor below is population-derived and says so.
"""

SPLIT_DECISION: dict[str, Any] = {
    "chosen": "upper_lower",
    "rejected": [
        "full_body (TRAINING_PROGRAM v0.3, approved 2026-09-21 — superseded 2026-09-24 before its first session)",
        "ppl (TRAINING_PROGRAM.md v0.2, six lifting days — never approved)",
    ],
    "provenance": "owner",
    "stated": "2026-09-23",
    "decision_sk": DECISION_SK,
    "override_signal": "program_split_full_body_v0.3",
    "supersedes": {
        "ruling": "v0.3 full body (heavy / moderate / heavy-moderate)",
        "stated": "2026-09-21",
        "where": "#3753 / #3755",
        "superseded_by": "the owner's 2026-09-23 switch to v0.4 Upper/Lower (#4147, " + DECISION_SK + ")",
    },
    "note": (
        "v0.4 is the WS4SB3 upper/lower structure MINUS its max-effort and dynamic-effort work (`EXCLUDED_METHODS`): heavy days "
        "are a top set of 4–6 at RPE 7–8 plus two back-offs at −10 %, volume days are 8–12. Every v0.3/v3.1 redline is kept — "
        "protein, energy floor, walking floor, rate schedule, tripwires, subtract-only authoring, band-matched anchoring, the "
        "novel-again rule and the 10 % detraining discount; they live in `owner_redlines`, not here. v0.3's split decision is "
        "kept verbatim in `program_v03.SPLIT_DECISION`."
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
        # #4147 v0.4 (owner 2026-09-23): the RDL is allowed as the MODERATE hinge — it is what the committed first v0.4
        # session (Lower-heavy, 2026-09-25) carries. A moderate hinge exposure tries these first, then `catalog_keys`.
        "moderate_catalog_keys": ["romanian_deadlift_barbell", "romanian_deadlift_dumbbell"],
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
    "upper": ["cable_chest_fly", "cable_tricep_pushdown", "db_curl", "reverse_pec_deck", "db_lateral_raise"],
    "lower": ["leg_press", "leg_curl", "calf_raise_machine", "machine_crunch", "machine_hip_thrust"],
}
"""v0.4's pools, one per archetype, the block's 2–3 accessories per session are chosen FROM at block start (machines/cables
only); not a rotation menu. `leg_press` is a squat-family member used here as a lower ACCESSORY — the committed first v0.4
session carries it at 2 x 8–10 beside the barbell squat. v0.3's single `full` pool is `program_v03.ACCESSORY_POOL`."""

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
        "set shows each accessory on two days and an addition shows as a movement the first week did not carry. Since #4110 the "
        "session sequence (`SESSION_SEQUENCE`) records the boundaries — a block opens on the day its first session is COMPLETED; an "
        "addition is still reported as drift, and the honesty line names a boundary that falls inside the window, where the addition "
        "is legitimate."
    ),
}


# ── the day shape ────────────────────────────────────────────────────────────
DAY_SHAPE: dict[str, Any] = {
    "am": "lift the next session in ORDER (upper-heavy, lower-heavy, upper-volume, lower-volume) on a lifting day — the hard, loaded work; ~55–70 min",
    "pm": "easy walking EVERY day (Zone 2, ≤ 105 bpm; 2–3 walks, none over 75 min; conversational, never intervals)",
    "order": "the sessions are a SEQUENCE, not weekdays (#4110): a walk or rest day postpones the next session, never skips it (v0.4, #4147)",
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
        "the `aerobic` archetype and lifting days carry `upper` / `lower`; a consumer that wants the two-a-day shape must read DAY_SHAPE. Making "
        "it expressible is a schema change to the grid and to every reader of it, deliberately not smuggled into this issue."
    ),
}


# ── the week grid ────────────────────────────────────────────────────────────
# MUST return the same top-level shape `config/training_week.json` provides — the seam
# hands this dict to `routine_generator.generate_routines`, which indexes it directly.
# `tests/test_program_structure_3755.py::test_week_grid_keys_equal_the_json_keys` holds
# the two key sets equal so a drift here is a red test, not a KeyError in a Lambda.
_ARCHETYPE_TARGETS: dict[str, list[str]] = {
    "upper": ["chest", "back", "shoulders", "biceps", "triceps"],
    "lower": ["quadriceps", "hamstrings", "glutes", "calves"],
    "aerobic": [],
    "mobility": [],
    "rest": [],
}

_SCHEDULE: dict[str, dict[str, Any]] = {
    "0": {"archetype": "upper", "session_role": "upper_heavy", "label": "Monday UPPER-HEAVY (nominal — the sequence decides) + walk (PM)"},
    "1": {"archetype": "lower", "session_role": "lower_heavy", "label": "Tuesday LOWER-HEAVY (nominal — the sequence decides) + walk (PM)"},
    "2": {"archetype": "aerobic", "label": "Wednesday walk"},
    "3": {
        "archetype": "upper",
        "session_role": "upper_volume",
        "label": "Thursday UPPER-VOLUME (nominal — the sequence decides) + walk (PM)",
    },
    "4": {
        "archetype": "lower",
        "session_role": "lower_volume",
        "label": "Friday LOWER-VOLUME (nominal — the sequence decides) + walk (PM)",
    },
    "5": {"archetype": "aerobic", "label": "Saturday walk"},
    "6": {"archetype": "aerobic", "label": "Sunday walk"},
}
"""v0.4's NOMINAL week — the shape `training_week.json` requires, and the answer only when the Hevy
record cannot be read (the result then says the sequence was UNREADABLE). What is served is the
SEQUENCE (`SESSION_SEQUENCE`, `session_sequence.next_session`), never this weekday."""


# Every value below that DIFFERS from the live JSON grid, and why. A changed ceiling with
# no recorded reason is a number nobody owns.
WEEK_GRID_PROVENANCE: dict[str, dict[str, Any]] = {
    "schedule": {
        "changed_from": "v0.3: full-body Mon / Wed / Fri + optional Sat (program_v03.SCHEDULE)",
        "provenance": "owner",
        "stated": "2026-09-23",
        "note": (
            "v0.4 (#4147): four upper/lower sessions in ORDER. The weekday placement here is NOMINAL — the served session is the "
            "sequence's (#4110); the grid answers only when the Hevy record cannot be read, and says so."
        ),
    },
    "session_set_ceiling": {
        "changed_from": 25,
        "value": 18,
        "provenance": "population-derived",
        "stated": "2026-09-22",
        "note": (
            "v0.3 §3: 12–18 hard sets per session, unchanged in v0.4 (its four sessions run 12–17). The muscle-budget path trims "
            "budgets proportionally to this ceiling and records the trim in the rationale — the ceiling is enforced, not assumed."
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
            "The absolute fail-safe, unchanged. The v0.4 TARGET is ~10 hard sets/muscle/wk (8–12) and it has one home — "
            "owner_redlines.REDLINES['lifting_sessions_per_wk']['sets_per_muscle_wk'] — with `volume_ceiling` as its tripwire. "
            "`weekly_sets_by_muscle` sums the four sessions (a test holds every group inside its band); the cap never binds."
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
    """The v0.4 week, in the exact shape `config/training_week.json` provides (placement NOMINAL — the sequence serves).

    Served by `program_seam.resolve_week_grid` ONLY when `ACTIVE` is True. The schedule
    entries carry two keys the JSON never had — `session_role` and `optional` — which the
    generator reads for the routine's rationale and title; every other consumer indexes
    `archetype` and `label` only, as before.
    """
    return {
        "_comment": (
            f"TRAINING_PROGRAM v{PROGRAM_VERSION} ({SPLIT}: four upper/lower sessions in ORDER, each muscle 2x/wk, loads hold) "
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
            f"v{PROGRAM_VERSION}: split={SPLIT} (owner, 2026-09-23, {DECISION_SK}; supersedes v0.3 full body — program_v03); six anchor patterns 2x/wk (population-derived, not his variance).",
            "Loads HOLD: start 60–65 % of band-anchored e1RM after the detraining discount, ramp ~5 %/wk to week 6, ≤ 85 % until week 8, then hold; gains taken only when offered. One home: owner_redlines.REDLINES['lifting_sessions_per_wk'].",
            "The PM walking is NOT in this grid — `schedule` holds one archetype per day; walking days are `aerobic`. Read program_structure.DAY_SHAPE.",
            "The weekday placement is NOMINAL: the sessions are served in ORDER (upper-heavy, lower-heavy, upper-volume, lower-volume) — the next one after the last PERFORMED lift, whatever the date (#4110). This grid answers only when the Hevy record cannot be read.",
            "session_set_ceiling 25 -> 18 and session_minutes_ceiling 75 -> 70 are §3 (12–18 sets, 55–70 min), unchanged in v0.4; the weekly cap of 22 is the unchanged fail-safe and never binds here.",
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


# ── the v0.4 SESSIONS: what each role prescribes (#4064 shape, #4147 content) ─
# The machine-readable half of the session: which anchor patterns each role trains, at which
# intensity, and which accessories ride with it. Since #4064 the generator builds THIS (top
# set, back-offs, rep ranges, fixed accessories), not a muscle-budget session with a role label.
#
# Lower-heavy is the committed first v0.4 session, owner-authored in chat on 2026-09-23
# (platform routine b1b9960468f374e30dcdeca8630dd18f, Hevy 4b743f67, target 2026-09-25): barbell
# squat heavy, RDL moderate, leg press / leg curl / calf 2 sets each. The other three roles are
# the PLATFORM's placement under the owner's constraints (each muscle 2x/wk, heavy 4–6 + back-offs,
# volume 8–12, ~10 sets/muscle/wk) and `SESSION_DISTRIBUTION_PROVENANCE` says so.
HEVY_FOLDERS: dict[str, str] = {"upper": "Upper", "lower": "Lower"}
"""The Hevy routine folder per v0.4 archetype. `mcp.hevy_routine_commit_report.FOLDER_BY_ARCHETYPE`
must name the same strings (held by a test); a folder is found-or-created at the first commit
(`ensure_folder`), never created ahead of time. v0.3's "Full Body" is `program_v03.HEVY_FOLDER`."""

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
    # #4147 v0.4: the volume days' anchor exposure (owner: "Volume days: 8–12 reps").
    "volume": {"sets": 3, "reps": [8, 12], "rest_seconds": 120, "cue": "VOLUME: 3 sets of 8–12, leave 1–3 in the tank."},
    "accessory": {"sets": 2, "reps": [8, 15], "rir": [1, 2], "rest_seconds": 90, "cue": "ACCESSORY: 2 sets of 8–15 at RIR 1–2."},
}
"""The rep scheme as numbers (v0.3 §3's heavy / moderate / accessory, plus v0.4's volume). The one PROSE home is `owner_redlines.REDLINES
['lifting_sessions_per_wk']['rep_scheme']`; a test holds every number here to that string."""

SESSION_TEMPLATES: dict[str, dict[str, Any]] = {
    "upper_heavy": {
        "archetype": "upper",
        "anchors": [["bench", "heavy"], ["row", "heavy"], ["overhead_press", "moderate"], ["vertical_pull", "moderate"]],
        "anchor_sets": {"vertical_pull": 2},
        "accessories": ["cable_tricep_pushdown", "db_curl"],
    },
    "lower_heavy": {
        "archetype": "lower",
        "anchors": [["squat", "heavy"], ["hinge", "moderate"]],
        "accessories": ["leg_press", "leg_curl", "calf_raise_machine"],
    },
    "upper_volume": {
        "archetype": "upper",
        "anchors": [["bench", "volume"], ["row", "volume"], ["overhead_press", "volume"], ["vertical_pull", "volume"]],
        "anchor_sets": {"vertical_pull": 2},
        "accessories": ["cable_chest_fly", "cable_tricep_pushdown", "db_curl"],
    },
    "lower_volume": {
        "archetype": "lower",
        "anchors": [["hinge", "volume"], ["squat", "volume"]],
        "accessories": ["leg_curl", "calf_raise_machine", "machine_crunch"],
    },
}
"""Per v0.4 role: its archetype, the anchor exposures (pattern, intensity) and the block-fixed accessories.

Every anchor pattern is trained exactly twice across the four roles and every redline muscle
group sits inside its weekly band (`weekly_sets_by_muscle`, held by a test). Accessories come
from `ACCESSORY_POOL[archetype]`, fixed per role for the block (`ROTATION_RULE`).
`anchor_sets` overrides an exposure's set count for one pattern: vertical pull runs 2 sets so
back (row + pulldown, twice) sits at 10. v0.3's four roles are `program_v03.SESSION_TEMPLATES`."""

SESSION_DISTRIBUTION_PROVENANCE: dict[str, Any] = {
    # Owner ratification 2026-09-25 (session AU, answering "ratify the three platform-proposed sessions":
    # "approved"). The three placements were the platform's; they are now the owner's, unchanged.
    "provenance": "owner",
    "owner_committed_roles": ["lower_heavy"],
    "owner_ratified_roles": ["upper_heavy", "upper_volume", "lower_volume"],
    "placed_by": "platform (2026-09-24, #4147); ratified by the owner 2026-09-25 (#4161, PR #4162 ruling)",
    "stated": "2026-09-25",
    "issue": "#4147",
    "note": (
        "The owner fixed the SPLIT and its ORDER (Upper-heavy -> Lower-heavy -> Upper-volume -> Lower-volume), the heavy scheme "
        "(top 4–6 @ RPE 7–8 + 2 back-offs at −10 %), the volume reps (8–12), each muscle 2x/wk, ~10 sets/muscle/wk, the trap "
        "bar until ≤ 275 lb and the RDL as the moderate hinge. Lower-heavy is the session he committed on 2026-09-23 (routine "
        "b1b9960468f374e30dcdeca8630dd18f). The other three placements are the platform's: 15 / 17 / 12 sets, 56 hard sets/wk "
        "(inside §3's 50–65), every group inside its band. The owner ratified them unchanged on 2026-09-25; the block is owner-locked until 2026-11-04."
    ),
}

EXCLUDED_METHODS: dict[str, Any] = {
    "methods": ["plyometrics", "max_effort_singles", "dynamic_effort"],
    "min_reps_any_exposure": 4,
    "provenance": "owner",
    "stated": "2026-09-23",
    "note": "v0.4 is WS4SB3's upper/lower structure MINUS its max-effort and dynamic-effort work: no plyometrics, no max-effort singles.",
}
"""What v0.4 refuses. A test holds every exposure's rep floor at >= 4 and no catalog key in a template names a jump/plyo."""

BLOCK_LOCK: dict[str, Any] = {
    "weeks": 6,
    "block_start": "2026-09-24",
    "locked_until": "2026-11-04",
    "rule": "no STRUCTURAL edits to v0.4 (split, order, templates, accessories) before this date; loads and deloads run as written",
    # #4161: enforced — `session_sequence.block_lock_state` compares the live structure with this, recorded at the lock
    "structure_fingerprint": "000ffceefa732c6e",
    # every re-record carries this note — `session_sequence.fingerprint_record_problems` reds a bare edit (#4161 review)
    "structure_fingerprint_record": {
        "fingerprint": "000ffceefa732c6e",
        "provenance": "owner",
        "stated": "2026-09-24",
        "ref": "#4161 (owner-approved red team: enforce the lock) over origin/main 7218b187, the block as locked by DECISION#2026-09-24T03:10:59",
    },
    "provenance": "owner",
    "stated": "2026-09-23",
    "decision_sk": DECISION_SK,
}
"""The owner's 6-week lock on the v0.4 block (~2026-11-04). A test holds the date; since #4161 the engine reads it as a guard."""

DELOAD_RULE: dict[str, Any] = {
    "rule": (
        "one pre-planned deload at the LATER of program week 6 (hybrid weeks: 4 sessions AND >= 7 days, #4161) or the block lock "
        "(2026-11-04): −40 % sets for 7 days (rounded to whole sets, accessories and back-offs first), loads held, never a week off"
    ),
    "provenance": "owner",
    "one_home": "owner_redlines.REDLINES['lifting_sessions_per_wk']['deload']",
}


def _deload_cfg() -> dict[str, Any]:
    from training import owner_redlines

    return dict(owner_redlines.REDLINES["lifting_sessions_per_wk"]["deload"])


# ── the SESSION SEQUENCE (#4110) — v0.4's order (#4147) ────────────────────
# Owner, 2026-09-23 (#4110): "more just focusing on planned sequence and not forgetting next if
# I audible a change" — the sessions are an ORDER, not dates. Owner, 2026-09-23 (#4147): v0.4
# is Upper-heavy -> Lower-heavy -> Upper-volume -> Lower-volume, repeating. The position advances
# only on a completed LOADED Hevy session (a walk or an Engine day postpones, never skips). Four
# completed sessions AND >= 7 days are one program week (#4161); the deload is `owner_redlines` (later of week 6 / the lock).
#
# The sequence STARTS at Lower-heavy: that is the first v0.4 session, already committed from chat
# (`first_session`). Counting starts on `block_start`, the first Pacific day after the decision
# (2026-09-23 ~20:10 PT), so a lift on 09-24 or later advances it whatever the day; a pre-switch
# v0.3/v0.2 lift never does. The arithmetic and its rulings live in `training.session_sequence`.
SESSION_SEQUENCE: dict[str, Any] = {
    "program_version": PROGRAM_VERSION,
    "block_start": "2026-09-24",
    "session_roles": ["upper_heavy", "lower_heavy", "upper_volume", "lower_volume"],
    "first_role": "lower_heavy",
    "first_session": {
        "role": "lower_heavy",
        "routine_id": "b1b9960468f374e30dcdeca8630dd18f",
        "hevy_routine_id": "4b743f67",
        "target_date": "2026-09-25",
        "committed": "from chat, 2026-09-23",
    },
    "sessions_per_week": 4,
    "weeks_per_block": 6,
    "advances_on": "a loaded Hevy session (training_streaks.is_loaded_session), one per Pacific day, dated on/after block_start",
    "provenance": "owner",
    "stated": "2026-09-23",
    "decision_sk": DECISION_SK,
    "issue": "#4147 (order: #4110)",
    "note": (
        "The order and the first session are the owner's (#4147); serving by order rather than weekday is the owner's (#4110). "
        "The weekday calendar v0.3 shipped (`program_v03.BLOCK_CALENDAR`) is retired, not kept as a display suggestion — two "
        "answers to 'what is next' was the defect."
    ),
}

_ROLE_LABEL = {
    "upper_heavy": "UPPER-HEAVY",
    "lower_heavy": "LOWER-HEAVY",
    "upper_volume": "UPPER-VOLUME",
    "lower_volume": "LOWER-VOLUME",
    # v0.3 (program_v03) — kept so a v0.3 routine's role still renders
    "heavy": "HEAVY",
    "moderate": "MODERATE",
    "heavy_moderate": "HEAVY-MODERATE",
    "optional_fourth": "OPTIONAL 4th",
}


def _day(day: str):
    from common.pacific_time import parse_day_key

    parsed = parse_day_key(day)
    if parsed is None:
        raise ValueError(f"not a YYYY-MM-DD day key: {day!r}")
    return parsed


def _deload_trim(exposures: list[dict[str, Any]], pct: int) -> dict[str, Any]:
    """Remove |pct| % of the session's sets (rounded), IN PLACE; loads are never touched.

    Round-robin, one set per pass: accessories first, then moderate/volume anchors, then heavy
    back-offs. A top set is never removed and no exposure drops below one set — so the
    deload keeps every anchor in the session and every top set at its load.
    """
    before = sum(len(e["sets"]) for e in exposures)
    target = before - int(round(before * abs(pct) / 100.0))
    order = [e for e in exposures if e["kind"] == "accessory"]
    order += [e for e in exposures if e["kind"] == "anchor" and e["intensity"] in ("moderate", "volume")][::-1]  # #4147: volume too
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
    """The session for one v0.4 role, as data: exposures, sets (top / back_off / working), reps.

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
        keys = list(ANCHORS[pattern]["catalog_keys"])
        if intensity == "moderate":
            # #4147: a pattern may name members allowed ONLY at moderate (the RDL as the moderate hinge)
            keys = list(ANCHORS[pattern].get("moderate_catalog_keys") or []) + keys
        key, why = _resolve_movement(
            keys,
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
        "archetype": tmpl["archetype"],
        "program_version": PROGRAM_VERSION,
        "session_role": role,
        "role_label": _ROLE_LABEL[role],
        "deload": deload,
        "deload_trim": deload_info,
        "exposures": exposures,
        "total_sets": sum(len(e["sets"]) for e in exposures),
        "hevy_folder": HEVY_FOLDERS[tmpl["archetype"]],
        "distribution": SESSION_DISTRIBUTION_PROVENANCE,
    }


def planned_session(
    day: str,
    *,
    block_workouts: list[dict[str, Any]] | None = None,
    catalog_movements: dict[str, Any] | None = None,
    skill_ceiling: int = 2,
) -> dict[str, Any]:
    """What the program serves on `day`: the next UNDONE session of the sequence (#4110), and
    its §3 prescription. Before the block start the weekday grid answers, and the result says
    which did. `block_workouts` is the Hevy record since the block start (None = not read).

    Only meaningful when the program is ACTIVE; the caller (`plan_engine`) reports the
    JSON grid instead when it is not.
    """
    from training import session_sequence

    entry = session_sequence.next_session(day, block_workouts)
    if entry is None:
        grid = dict(_SCHEDULE[str(_day(day).weekday())])
        entry = {
            **grid,
            "source": "week_grid",
            "note": f"before the block start ({SESSION_SEQUENCE['block_start']}) — the weekday grid answers",
        }
    out: dict[str, Any] = {"date": day, "program_version": PROGRAM_VERSION, **entry}
    role = entry.get("session_role")
    if role in SESSION_TEMPLATES:
        out["prescription"] = session_prescription_for_role(
            role, deload=bool(entry.get("deload")), catalog_movements=catalog_movements, skill_ceiling=skill_ceiling
        )
    return out


def weekly_sets_by_pattern() -> dict[str, int]:
    """Anchor sets per pattern over one program week — the four v0.4 roles."""
    out: dict[str, int] = {}
    for role in SESSION_SEQUENCE["session_roles"]:
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
"""The per-muscle set ranges, keyed to the catalog's `primary_muscle` (#4090): v0.4's 8–12 (~10, #4147)
for quads, hams/glutes, chest, back; 4–6 for delts and arms. Counted as DIRECT sets (the movement's
primary muscle) — §3's 'mostly indirect' is the pressing and pulling on top of these."""


def weekly_sets_by_muscle(catalog_movements: dict[str, Any], skill_ceiling: int = 2) -> dict[str, dict[str, Any]]:
    """Hard sets per redline muscle group over one program week (the four v0.4 roles), with the
    range each must sit in (`owner_redlines`)."""
    from training import owner_redlines

    lift = owner_redlines.REDLINES["lifting_sessions_per_wk"]
    by_muscle: dict[str, int] = {}
    for role in SESSION_SEQUENCE["session_roles"]:
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


def _boundary_honesty(window_start: str, window_end: str, block_boundaries: list[str] | None) -> str:
    """The honesty line about block boundaries — the days a block's first session was COMPLETED
    (`session_sequence.block_boundaries`, #4110). None = the sequence was not read."""
    lead = f"the {ROTATION_RULE['window_days']}-day window is {ROTATION_RULE['window_provenance']}"
    if block_boundaries is None:
        return f"{lead}; the session sequence was not read, so a block boundary inside it is unknown and an addition is reported as drift"
    inside = [d for d in block_boundaries if window_start < d <= window_end]
    if inside:
        return (
            f"{lead}; the session sequence opened a new block on {inside[0]} inside it, so an accessory added from that day "
            "is legitimate, not drift"
        )
    return f"{lead}; the session sequence opened no new block inside it, so an addition here is drift"


def accessory_rotation(
    *,
    window_start: str,
    window_end: str,
    hevy_workouts: list[dict[str, Any]] | None,
    block_boundaries: list[str] | None = None,
) -> dict[str, Any]:
    """The accessory layer over a trailing window, computed from the Hevy record.

    v0.3/v0.4 fix accessories for the block, so the computed verdict is DRIFT: accessories
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
                f"{len(added)} added in the trailing 7 days that the prior days did not carry; {len(repeats)} repeated (by design — accessories are fixed for the block)"
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
                _boundary_honesty(window_start, window_end, block_boundaries),
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
        # #4110/#4147: the session sequence (order, not weekdays), and the weekly anchor dose it produces
        "session_sequence": SESSION_SEQUENCE,
        "decision_sk": DECISION_SK,
        "block_lock": BLOCK_LOCK,
        "excluded_methods": EXCLUDED_METHODS,
        "superseded_programs": SUPERSEDED_PROGRAMS,
        "hevy_folders": HEVY_FOLDERS,
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
