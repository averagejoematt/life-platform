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

STATUS: v1.0 ACTIVE since 2026-10-18 (#5069) — THE FIVE-DAY SPLIT. Owner rulings 2026-10-18 (epic
#5067): ruling 5, "5 lifting days, 60-75 min of lifting. Sequence Upper-heavy, Lower-heavy,
Shoulders+arms, Upper-volume, Lower-volume. Delts 3x/week."; ruling 6, "the v0.4 lock to 2026-11-04 is
lifted now". The split, its order, the lifting-minute budget, the cardio and stretching caps and the
block length are READ from the training charter (`config/training_charter.json` `split.*`,
`rotation.anchors_fixed_weeks`; `training.training_charter.charter_value`) — this module holds no
private copy of them. The sessions are still served in ORDER (#4110, `training.session_sequence`):
the next undone session on whatever day he lifts.

v0.4 (four-session upper/lower, #4147, served 2026-09-24 .. 2026-10-18) is SUPERSEDED, not deleted:
its order, nominal week and block lock live in `training.program_v04` (`SUPERSEDED_PROGRAMS`). The
live block is NOT re-anchored: `SESSION_SEQUENCE['block_start']` is unchanged, every session
credited before the cut-over day keeps its v0.4 role, and the five-day order continues from the
role after the last credited v0.4 session (`SESSION_SEQUENCE['cutover']`). v0.4's four role
templates are unchanged and still defined here; the fifth (`shoulders_arms`) is new.

v0.3 (full body, approved 2026-09-21 on #3753) is SUPERSEDED likewise: its definitions live
verbatim in `training.program_v03`. v0.2 (PPL) was never approved. While `ACTIVE` is False the
seam serves the live JSON grid unchanged and the block says PROPOSED — an unratified program must
not steer a prescription.

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

from typing import Any

from training import effort_ceilings, in_block_variant, program_conflicts, program_v03, program_v04
from training.accessory_check import CARDIO_NAME_HINTS, accessory_rotation, classify_movement  # noqa: F401 — re-exported (#5069 split)
from training.program_v03 import BLOCK_CALENDAR  # noqa: F401 — v0.3 history; `load_ramp.block_1_start()` reads it (#4107)
from training.session_shape import (  # noqa: F401 — #5069: a session's length and shape (ruling 5), re-exported from here
    SESSION_TIME_MODEL,
    enforce_session_shape,
    lifting_minutes_cap,
    lifting_minutes_range,
    routine_minutes,
    session_minutes_estimate,
    session_shape_problems,
    trim_to_time,
)
from training.training_charter import charter_value, charter_version

ACTIVE = True
"""True since 2026-09-21 (v0.3, #3753); v0.4 replaced v0.3 on 2026-09-24 (#4147) and v1.0 replaced v0.4 on 2026-10-18 (#5069)."""

LAST_REVIEWED_BY_OWNER: str | None = "2026-10-18"
"""ISO date the owner last read this program. None means never. v1.0 is his rulings 5 and 6 of 2026-10-18 (#5067)."""

PROGRAM_VERSION = "1.0"
ISSUE = "#5069"
PROSE_HOME = "s3://matthew-life-platform/config/coaching/TRAINING_PROGRAM.md"
"""Owner-private (the v0.4 prose is `program_v04.SUPERSEDED['prose_home']`). Cited, never read by the engine; bringing it
to the five-day split is an owner act (#5069 PR)."""

DECISION_SK = "DECISION#2026-09-24T03:10:59"
"""The owner's v0.4 program-switch decision (2026-09-23 ~20:10 PT). The five-day split's ruling is `SPLIT_DECISION['ruling']`."""

CHARTER_VERSION = charter_version()
"""The training charter version this module's split was read from — stamped on the sequence and every prescription."""

SUPERSEDED_PROGRAMS: dict[str, dict[str, Any]] = {"0.3": program_v03.SUPERSEDED, "0.4": program_v04.SUPERSEDED}
"""Every program this one replaced, with the date and the decision. The definitions are in `training.program_v03` / `program_v04`."""


def role_id(sequence_name: str) -> str:
    """The engine's role id for one charter `split.sequence` name ('Upper-heavy' -> 'upper_heavy',
    'Shoulders+arms' -> 'shoulders_arms'). The charter names the sessions; this is the only spelling rule."""
    return "".join(c if c.isalnum() else "_" for c in str(sequence_name).strip().lower())


SPLIT_SEQUENCE_NAMES: list[str] = list(charter_value("split.sequence") or [])
"""The charter's session names, in its order (owner ruling 5, 2026-10-18). Read, never restated."""

SPLIT_ROLES: list[str] = [role_id(n) for n in SPLIT_SEQUENCE_NAMES]
"""The role ids of `SPLIT_SEQUENCE_NAMES`, same order — the keys of `SESSION_TEMPLATES` the sequence serves."""

SPLIT = "five_day"
"""Five sessions in the charter's ORDER (`split.sequence`) — each major muscle 2x/wk, delts 3x/wk, walking every
day. ORDER, not weekdays (#4110): a walk audible postpones, never skips.

The STRUCTURE decision is the owner's (2026-10-18, rulings 5 + 6, #5067); the per-pattern frequency NUMBER under
each anchor below is population-derived and says so.
"""

SPLIT_DECISION: dict[str, Any] = {
    "chosen": "five_day",
    "rejected": [
        "upper_lower (TRAINING_PROGRAM v0.4, four sessions in order, served 2026-09-24 .. 2026-10-18 — superseded by ruling 5)",
        "full_body (TRAINING_PROGRAM v0.3, approved 2026-09-21 — superseded 2026-09-24 before its first session)",
        "ppl (TRAINING_PROGRAM.md v0.2, six lifting days — never approved)",
    ],
    "provenance": "owner",
    "stated": "2026-10-18",
    "ruling": "owner rulings 2026-10-18 (epic #5067): 5 — five lifting days in the charter's order, delts 3x/week; 6 — the v0.4 lock is lifted now",
    "charter_paths": ["split.sequence", "split.lifting_days_per_wk", "split.frequency", "split.session_minutes"],
    "decision_sk": DECISION_SK,
    "override_signal": "program_split_full_body_v0.3",
    "supersedes": {
        "ruling": "v0.4 upper/lower, four sessions in order (#4147)",
        "stated": "2026-09-23",
        "where": "#4147 / #4161",
        "superseded_by": "the owner's 2026-10-18 rulings 5 + 6 (#5067; #5069)",
    },
    "note": (
        "v1.0 keeps v0.4's four role templates unchanged and adds the fifth, the aesthetic day (`shoulders_arms`: overhead press, "
        "side and rear delts, biceps, triceps, traps), so delts are trained on both upper days AND that day. It keeps v0.4's "
        "exclusions (`EXCLUDED_METHODS`) and every redline; those live in `owner_redlines`, not here. v0.4's structure is kept in "
        "`program_v04`, v0.3's split decision verbatim in `program_v03.SPLIT_DECISION`."
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
    "Owner ruling 5 (2026-10-18, #5067): each major muscle 2x/wk, delts 3x/wk — read from the charter (`split.frequency`). "
    "2x/wk per pattern was first the red team's minimum-effective-dose frequency (S&C coach, 2026-09-22; Bickel 2011) at 6–10 "
    "hard sets/muscle/wk; it is still NOT derived from Matthew's own session-to-session variance and must say so wherever it "
    "fires (ADR-105)."
)


def _frequency(charter_path: str) -> dict[str, Any]:
    """An anchor's weekly frequency band, read from the charter's `split.frequency` (one value -> low == high)."""
    n = int(charter_value(f"split.frequency.{charter_path}"))
    return {"low": n, "high": n, "provenance": "owner", "charter_path": f"split.frequency.{charter_path}", "note": _FREQ_NOTE}


ANCHORS: dict[str, dict[str, Any]] = {
    "squat": {
        "pattern": "knee-dominant squat (SSB / high-bar; leg press as the listed fallback at 316 lb)",
        "frequency_per_week": _frequency("each_major_muscle_per_wk"),
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
        "frequency_per_week": _frequency("each_major_muscle_per_wk"),
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
        "frequency_per_week": _frequency("each_major_muscle_per_wk"),
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
        "frequency_per_week": _frequency("each_major_muscle_per_wk"),
        "catalog_keys": ["machine_row", "one_arm_db_row"],
        "hevy_title_hints": ["row"],
        "primary_muscles": ["back"],
        "provenance": "owner",
        "stated": "2026-09-21",
        "note": "v0.3 anchor (new — v0.2 had the big three only). 'Rowing machine' is cardio, not this pattern: `classify_movement` checks the cardio hints first.",
    },
    "overhead_press": {
        "pattern": "vertical press",
        # ruling 5: delts 3x/wk — the press anchors the delts on both upper days and the shoulders+arms day
        "frequency_per_week": _frequency("delts_per_wk"),
        "catalog_keys": ["machine_shoulder_press", "db_shoulder_press"],
        "hevy_title_hints": ["overhead press", "shoulder press", "military press", "push press"],
        "primary_muscles": ["shoulders"],
        "provenance": "owner",
        "stated": "2026-09-21",
        "note": "v0.3 anchor (new).",
    },
    "vertical_pull": {
        "pattern": "vertical pull",
        "frequency_per_week": _frequency("each_major_muscle_per_wk"),
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
    # #5069: face_pull (rear delts, 93 logged sessions) and shrug_dumbbell (traps) join for the shoulders+arms day
    "upper": ["cable_chest_fly", "cable_tricep_pushdown", "db_curl", "reverse_pec_deck", "db_lateral_raise", "face_pull", "shrug_dumbbell"],
    "lower": ["leg_press", "leg_curl", "calf_raise_machine", "machine_crunch", "machine_hip_thrust"],
}
"""The pools, one per archetype, the block's accessories are chosen FROM at block start (v0.4's machines/cables, plus the
shoulders+arms day's face pull and dumbbell shrug, #5069); not a rotation menu (the rotation is #5075's). `leg_press` is a squat-family member used here as a lower ACCESSORY — the committed first v0.4
session carries it at 2 x 8–10 beside the barbell squat. v0.3's single `full` pool is `program_v03.ACCESSORY_POOL`."""

ROTATION_RULE: dict[str, Any] = {
    "rule": "accessories are FIXED for the block: 2–3 per session, 2 sets, machines/cables, none added after week 1; the set changes only at a block boundary",
    "window_days": 14,
    # #5077: the block's length is the charter's `rotation.anchors_fixed_weeks` (`block_model.block_weeks()`), not a copy here
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
    "am": (
        f"lift the next session in ORDER ({', '.join(n.lower() for n in SPLIT_SEQUENCE_NAMES)}) on a lifting day — the hard, loaded "
        f"work; {charter_value('split.session_minutes.lifting')[0]}–{charter_value('split.session_minutes.lifting')[1]} min of lifting "
        f"(charter `split.session_minutes`), one cardio block <= {charter_value('split.session_minutes.cardio_block_max')} min and "
        f"stretching <= {charter_value('split.session_minutes.stretching_max')} min on top"
    ),
    "pm": "easy walking EVERY day (HR avg ≤ 120 with the talk test, 105 the target; 2–3 walks, weekday none over 75 min, one long-walk slot a week; never intervals)",
    "order": "the sessions are a SEQUENCE, not weekdays (#4110): a walk or rest day postpones the next session, never skips it (#4147, #5069)",
    "cardio_placement": "no walking in the 2 h before lifting; the lightest walking day follows the heavy session; cycling is the knee-sparing substitute (OD2 deleted the ≤ 2 h cap)",
    "provenance": "owner-history",
    "stated": "2026-06-19",
    "minutes_provenance": "owner ruling 5, 2026-10-18 (#5067) — read from the charter",
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

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

NOMINAL_LIFTING_DAYS: tuple[str, ...] = ("0", "1", "2", "4", "5")
"""Where the five sessions sit on a NOMINAL week (Mon, Tue, Wed, Fri, Sat; Thu and Sun walk), in the charter's order.
Platform-placed (#5069): the only constraint it serves is a walk day between the shoulders+arms day and the next upper day.
The sequence, not this placement, decides what is served (#4110)."""


def _nominal_schedule() -> dict[str, dict[str, Any]]:
    """The nominal week from the charter's order: each lifting day carries its role, every other day is a walk."""
    if len(NOMINAL_LIFTING_DAYS) != len(SPLIT_ROLES):
        raise ValueError(f"{len(SPLIT_ROLES)} sessions in the charter's split but {len(NOMINAL_LIFTING_DAYS)} nominal lifting days")
    by_day = dict(zip(NOMINAL_LIFTING_DAYS, SPLIT_ROLES))
    out: dict[str, dict[str, Any]] = {}
    for i, name in enumerate(_WEEKDAYS):
        role = by_day.get(str(i))
        if role is None:
            out[str(i)] = {"archetype": "aerobic", "label": f"{name} walk"}
        else:
            out[str(i)] = {
                "archetype": SESSION_TEMPLATES[role]["archetype"],
                "session_role": role,
                "label": f"{name} {_ROLE_LABEL[role]} (nominal — the sequence decides) + walk (PM)",
            }
    return out


# Every value below that DIFFERS from the live JSON grid, and why. A changed ceiling with
# no recorded reason is a number nobody owns.
WEEK_GRID_PROVENANCE: dict[str, dict[str, Any]] = {
    "schedule": {
        "changed_from": "v0.4: four upper/lower sessions Mon / Tue / Thu / Fri (program_v04.NOMINAL_WEEK)",
        "provenance": "owner",
        "stated": "2026-10-18",
        "note": (
            "v1.0 (#5069, owner ruling 5): five sessions in the charter's ORDER. The weekday placement here is NOMINAL and the "
            "platform's (`NOMINAL_LIFTING_DAYS`) — the served session is the sequence's (#4110); the grid answers only when the "
            "Hevy record cannot be read, and says so."
        ),
    },
    "session_set_ceiling": {
        "changed_from": 18,
        "value": 20,
        "provenance": "owner",
        "stated": "2026-09-30",
        "note": (
            "v0.5 OD4 (#4503): 20 base / 24 with 🟢 (`green_block`); was 18 (v0.3 §3). The five sessions run 12–17 and no template "
            "carries a 🟢 tail, so no session gains a set. The muscle-budget path trims budgets to this ceiling and records the trim."
        ),
    },
    "session_minutes_ceiling": {
        "changed_from": "70 (v0.3 §3's band top)",
        "value": "the charter's `split.session_minutes.lifting` top",
        "provenance": "owner",
        "stated": "2026-10-18",
        "note": (
            "Owner ruling 5 (#5067): the LIFTING minutes, read from the charter; cardio and stretching are capped separately "
            "(`split.session_minutes.cardio_block_max` / `stretching_max`). `session_minutes_estimate` is the one estimate and "
            "`session_prescription_for_role` trims accessories first to fit it. The Minimum Viable Session is `floor_session_minutes`."
        ),
    },
    "weekly_volume_cap_per_muscle": {
        "value": 22,
        "provenance": "unchanged",
        "note": (
            "The absolute fail-safe, unchanged. The v0.4 TARGET is ~10 hard sets/muscle/wk (8–12) and it has one home — "
            "owner_redlines.REDLINES['lifting_sessions_per_wk']['sets_per_muscle_wk'] — with `volume_ceiling` as its tripwire. "
            "`weekly_sets_by_muscle` sums the five sessions (a test holds every big group inside its band); the cap never binds."
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
    """The program's week, in the exact shape `config/training_week.json` provides (placement NOMINAL — the sequence serves).

    Served by `program_seam.resolve_week_grid` ONLY when `ACTIVE` is True. The schedule
    entries carry two keys the JSON never had — `session_role` and `optional` — which the
    generator reads for the routine's rationale and title; every other consumer indexes
    `archetype` and `label` only, as before.
    """
    return {
        "_comment": (
            f"TRAINING_PROGRAM v{PROGRAM_VERSION} ({SPLIT}: {len(SPLIT_ROLES)} sessions in ORDER, each major muscle "
            f"{charter_value('split.frequency.each_major_muscle_per_wk')}x/wk, delts {charter_value('split.frequency.delts_per_wk')}x/wk, "
            f"loads hold; charter v{CHARTER_VERSION}) "
            f"as the engine reads it. Generated by lambdas/training/program_structure.py ({ISSUE}); the prose lives at {PROSE_HOME}. "
            "day_of_week is 0=Monday .. 6=Sunday; archetype names are handled generically by routine_generator."
        ),
        "_version": 3,
        "schedule": {k: dict(v) for k, v in _SCHEDULE.items()},
        "archetype_targets": {k: list(v) for k, v in _ARCHETYPE_TARGETS.items()},
        "session_set_ceiling": 20,
        "session_minutes_ceiling": lifting_minutes_cap(),  # drift-ok: MINUTES per lifting session, not the ADR-133 AI budget ceiling in dollars
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
            f"v{PROGRAM_VERSION}: split={SPLIT} (owner rulings 5 + 6, 2026-10-18, #5067; supersedes v0.4 upper/lower — program_v04 — "
            f"and v0.3 full body — program_v03); each anchor pattern at the charter's split.frequency (owner, not his variance).",
            "Loads HOLD: start 60–65 % of band-anchored e1RM after the detraining discount, ramp ~5 %/wk to week 6, ≤ 85 % until week 8, then hold; gains rep-triggered (double progression, v0.5 OD5). One home: owner_redlines.REDLINES['lifting_sessions_per_wk'].",
            "The PM walking is NOT in this grid — `schedule` holds one archetype per day; walking days are `aerobic`. Read program_structure.DAY_SHAPE.",
            f"The weekday placement is NOMINAL: the sessions are served in ORDER ({', '.join(n.lower() for n in SPLIT_SEQUENCE_NAMES)}) — "
            "the next one after the last PERFORMED lift, whatever the date (#4110). This grid answers only when the Hevy record cannot be read.",
            "session_set_ceiling 18 -> 20 base / 24 with 🟢 is v0.5 OD4 (#4503, training.green_block); session_minutes_ceiling is the "
            "charter's lifting-minute top (owner ruling 5, #5069); the weekly cap of 22 is the unchanged fail-safe and never binds here.",
            "The generator selects by muscle, not by pattern: a `back` budget reaches row OR vertical pull. See program_structure.anchor_reachability() for what the grid can and cannot guarantee.",
            "Lifting days vs owner_redlines.REDLINES['lifting_sessions_per_wk']: the redline reads the charter's split.lifting_days_per_wk "
            "(owner ruling 5); `program_conflicts.conflicts()` computes the agreement rather than asserting it.",
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


# ── the SESSIONS: what each role prescribes (#4064 shape, #4147 content, #5069 the fifth role) ─
# The machine-readable half of the session: which anchor patterns each role trains, at which
# intensity, and which accessories ride with it. Since #4064 the generator builds THIS (top
# set, back-offs, rep ranges, fixed accessories), not a muscle-budget session with a role label.
#
# Lower-heavy is the committed first v0.4 session, owner-authored in chat on 2026-09-23
# (platform routine b1b9960468f374e30dcdeca8630dd18f, Hevy 4b743f67, target 2026-09-25): barbell
# squat heavy, RDL moderate, leg press / leg curl / calf 2 sets each. The other three v0.4 roles
# were the PLATFORM's placement, ratified by the owner on 2026-09-25. The fifth role (#5069, owner
# ruling 5: the aesthetic day) is the platform's placement under his named contents.
HEVY_FOLDERS: dict[str, str] = {"upper": "Upper", "lower": "Lower"}
"""The Hevy routine folder per v0.4 archetype. `mcp.hevy_routine_commit_report.FOLDER_BY_ARCHETYPE`
must name the same strings (held by a test); a folder is found-or-created at the first commit
(`ensure_folder`), never created ahead of time. v0.3's "Full Body" is `program_v03.HEVY_FOLDER`."""

# #5058: every RPE here is the charter's — `effort_ceilings.by_movement_class` (the ruled bands, read through
# `training.effort_ceilings`); the pre-charter `top_rpe` [7, 8] and the accessories' RIR are retired. A compound set
# (top set, moderate, volume) reads the compounds band, an accessory's earlier sets the compounds band and its LAST set
# the last-isolation-set band. Back-offs are prescribed by % of the top set only — the charter rules no back-off RPE.
_EFFORT = effort_ceilings.class_bands()
_C, _L = (f"{_EFFORT[k][0]:g}–{_EFFORT[k][1]:g}" for k in (effort_ceilings.COMPOUNDS, effort_ceilings.LAST_ISOLATION_SET))

EXPOSURES: dict[str, dict[str, Any]] = {
    "heavy": {
        "top_sets": 1,
        "reps": [4, 6],
        "effort": effort_ceilings.COMPOUNDS,
        "back_off_sets": 2,
        "back_off_pct": -10,
        "rest_seconds": 180,
        "cue": f"HEAVY: 1 top set of 4–6 @ RPE {_C}, then 2 back-offs at −10 % of the top set (charter ceilings).",
    },
    "moderate": {
        "sets": 3,
        "reps": [6, 10],
        "effort": effort_ceilings.COMPOUNDS,
        "rest_seconds": 120,
        "cue": f"MODERATE: 3 sets of 6–10 @ RPE {_C} (charter compound ceiling).",
    },
    # #4147 v0.4: the volume days' anchor exposure (owner: "Volume days: 8–12 reps").
    "volume": {
        "sets": 3,
        "reps": [8, 12],
        "effort": effort_ceilings.COMPOUNDS,
        "rest_seconds": 120,
        "cue": f"VOLUME: 3 sets of 8–12 @ RPE {_C} (charter compound ceiling).",
    },
    "accessory": {
        "sets": 2,
        "reps": [8, 15],
        "effort": effort_ceilings.COMPOUNDS,
        "last_set_effort": effort_ceilings.LAST_ISOLATION_SET,
        "rest_seconds": 90,
        "cue": f"ACCESSORY: 2 sets of 8–15 @ RPE {_C}; last set RPE {_L} (charter ceilings).",
    },
}
"""The rep scheme as numbers (v0.3 §3's heavy / moderate / accessory, plus v0.4's volume). The one PROSE home is `owner_redlines.REDLINES
['lifting_sessions_per_wk']['rep_scheme']`; a test holds every number here to that string. The effort keys name a charter class band
(`training.effort_ceilings`, #5058) — the RPE numbers themselves live only in the charter."""

SESSION_TEMPLATES: dict[str, dict[str, Any]] = {
    "upper_heavy": {
        "archetype": "upper",
        "anchors": [["bench", "heavy"], ["row", "heavy"], ["overhead_press", "moderate"], ["vertical_pull", "moderate"]],
        "anchor_sets": {"vertical_pull": 2},
        # #5053: the rear-delt slot (delts 14–18/wk, charter `volume_priorities`) — the upper heavy day carries the pec deck
        "accessories": ["cable_tricep_pushdown", "db_curl", "reverse_pec_deck"],
    },
    "lower_heavy": {
        "archetype": "lower",
        "anchors": [["squat", "heavy"], ["hinge", "moderate"]],
        "accessories": ["leg_press", "leg_curl", "calf_raise_machine"],
        "accessory_sets": {"calf_raise_machine": 4},  # #5053: calves at their MEV floor (8/wk) across the two lower days
    },
    # #5069 (owner ruling 5, 2026-10-18): the aesthetic day — overhead press, side + rear delts, biceps, triceps, traps.
    # Archetype `upper` (the Upper folder; the sequence credits it like any upper session whose sets reach the delts).
    "shoulders_arms": {
        "archetype": "upper",
        "anchors": [["overhead_press", "moderate"]],
        "accessories": ["db_lateral_raise", "face_pull", "db_curl", "cable_tricep_pushdown", "shrug_dumbbell"],
        "accessory_rule": (
            "the aesthetic day's accessories ARE the session (owner ruling 5): five of them, not 2–3 — `ROTATION_RULE`'s per-session "
            "count binds the other roles; every one is still fixed for the block"
        ),
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
        # #5053: core and calves reach their MEV floors (4 and 8 sets/wk) here; the second leg curl is the week's trade — the
        # redline's 75-set week is full (`owner_redlines` total_hard_sets_wk) and hamstrings still sit at the 8-set floor
        "accessories": ["calf_raise_machine", "machine_crunch"],
        "accessory_sets": {"calf_raise_machine": 4, "machine_crunch": 4},
    },
}
"""Per role: its archetype, the anchor exposures (pattern, intensity) and the block-fixed accessories, in the charter's order.

Every anchor pattern is trained at least twice across the five roles, the overhead press three times (delts 3x/wk, owner
ruling 5); every big redline muscle group sits inside its weekly band and each group's weekly FREQUENCY meets the charter's
`split.frequency` (`weekly_sets_by_muscle`, held by tests). Accessories come from `ACCESSORY_POOL[archetype]`, fixed per
role for the block (`ROTATION_RULE`). `anchor_sets` overrides an exposure's set count for one pattern: vertical pull runs
2 sets so back (row + pulldown, twice) sits at 10. The four v0.4 roles are unchanged (#4147); v0.3's are
`program_v03.SESSION_TEMPLATES`."""

SESSION_DISTRIBUTION_PROVENANCE: dict[str, Any] = {
    # Owner ratification 2026-09-25 (session AU, answering "ratify the three platform-proposed sessions":
    # "approved"). The three placements were the platform's; they are now the owner's, unchanged.
    "provenance": "owner",
    "owner_committed_roles": ["lower_heavy"],
    "owner_ratified_roles": ["upper_heavy", "upper_volume", "lower_volume"],
    # #5069: the fifth role's CONTENTS are the owner's (ruling 5 names them); the movement choice is the platform's
    "platform_placed_roles": ["shoulders_arms"],
    "placed_by": (
        "platform (2026-09-24, #4147); ratified by the owner 2026-09-25 (#4161, PR #4162 ruling); the fifth role placed by the "
        "platform 2026-10-18 under owner ruling 5 (#5069)"
    ),
    "stated": "2026-10-18",
    "issue": "#5069 (v0.4: #4147)",
    "note": (
        "The owner fixed the SPLIT and its ORDER (the charter's `split.sequence`, ruling 5), the heavy scheme (top set + 2 back-offs "
        "at −10 %), the volume reps (8–12), each major muscle 2x/wk and delts 3x/wk, the trap bar until the charter's gate and the "
        "RDL as the moderate hinge. `lower_heavy` is the session he committed on 2026-09-23 (routine b1b9960468f374e30dcdeca8630dd18f). "
        "Three v0.4 placements are the platform's, owner-ratified unchanged on 2026-09-25. The `shoulders_arms` day's movements "
        "(overhead press, lateral raise, face pull, curl, pushdown, dumbbell shrug) are the platform's choice from his logged "
        "history under the contents ruling 5 names. The v0.4 block lock is lifted (ruling 6; history: `program_v04.BLOCK_LOCK`)."
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

BLOCK_LOCK_HISTORY: dict[str, Any] = program_v04.BLOCK_LOCK
"""The owner's v0.4 block lock (#4161) — HISTORY since owner ruling 6 (2026-10-18): "the v0.4 lock to 2026-11-04 is lifted
now". Nothing reads it to refuse an edit; `session_sequence.structure_fingerprint()` is a measurement, never a guard."""


def _deload_cfg() -> dict[str, Any]:
    # The deload's RESPONSE (−40 % sets, 7 days, loads held), one home in `owner_redlines`. No schedule (#5070): it applies
    # only on the owner's recorded word (`deload_word`).
    from training import owner_redlines

    return dict(owner_redlines.REDLINES["lifting_sessions_per_wk"]["deload"])


# ── the SESSION SEQUENCE (#4110) — the charter's order (#5069) ─────────────
# Owner, 2026-09-23 (#4110): "more just focusing on planned sequence and not forgetting next if
# I audible a change" — the sessions are an ORDER, not dates. Owner ruling 5, 2026-10-18: five
# sessions in the charter's `split.sequence`, repeating. The position advances only on a completed
# LOADED Hevy session (a walk or an Engine day postpones, never skips). A program week is the
# charter's lifting days completed AND >= 7 days (#4161); the deload is the owner's recorded word
# (`deload_word`, #5070). The arithmetic and its rulings live in `training.session_sequence`.
#
# THE CUT-OVER (#5069 — the live block is NOT re-anchored). `block_start` stays 2026-09-24. Every
# session credited on a day BEFORE `cutover.on` keeps the v0.4 role it was served as
# (`program_v04.SESSION_SEQUENCE`, from lower-heavy, four a week). From `cutover.on` the five-day
# order runs, continuing from the role AFTER the last credited v0.4 session (so a last v0.4 session
# of lower-heavy serves shoulders+arms next; upper-volume serves lower-volume). Weeks opened before the
# cut-over counted v0.4's four sessions; sessions on/after it count five.
SESSION_SEQUENCE: dict[str, Any] = {
    "program_version": PROGRAM_VERSION,
    "charter_version": CHARTER_VERSION,
    "block_start": "2026-09-24",
    "session_roles": list(SPLIT_ROLES),
    # only when no v0.4 session was credited before the cut-over (otherwise the order continues from the last one)
    "first_role": SPLIT_ROLES[0] if SPLIT_ROLES else None,
    "sessions_per_week": int(charter_value("split.lifting_days_per_wk") or 0),
    "cutover": {
        "on": "2026-10-19",
        "from_program": "0.4",
        "from_sequence": "program_v04.SESSION_SEQUENCE",
        "rule": (
            "a session credited on a day before `on` keeps its v0.4 role and counts toward a v0.4 week (four sessions); from `on` "
            "the five-day order serves the role after the last credited v0.4 session, and a week counts the charter's lifting days"
        ),
        "why_this_day": "the first Pacific day after the rulings (2026-10-18); block_start is not re-anchored",
        "ruling": "owner rulings 5 + 6, 2026-10-18 (#5067)",
        "issue": "#5069",
    },
    # #5077: no `weeks_per_block` copy — `session_sequence._seq()` adds it from the charter (`block_model.block_weeks()`)
    "advances_on": "a loaded Hevy session (training_streaks.is_loaded_session), one per Pacific day, dated on/after block_start, whose routine archetype is a program archetype and whose loaded sets reach the role's anchor muscles (session_sequence.classify_sessions, #4312) — an off-program complement (Flex) never advances it",
    "provenance": "owner",
    "stated": "2026-10-18",
    "decision_sk": DECISION_SK,
    "issue": "#5069 (order: #4110; v0.4: #4147)",
    "note": (
        "The order is the owner's (ruling 5, read from the charter); serving by order rather than weekday is the owner's (#4110). "
        "The cut-over day is the platform's: the first day after the rulings. The weekday calendar v0.3 shipped "
        "(`program_v03.BLOCK_CALENDAR`) stays retired — two answers to 'what is next' was the defect."
    ),
}

_ROLE_LABEL = {
    # the charter's names, upper-cased (titles: "SHOULDERS+ARMS — W5 — 2026-10-21"); v0.4's four roles are among them
    **{role: name.upper() for name, role in zip(SPLIT_SEQUENCE_NAMES, SPLIT_ROLES)},
    # v0.3 (program_v03) — kept so a v0.3 routine's role still renders
    "heavy": "HEAVY",
    "moderate": "MODERATE",
    "heavy_moderate": "HEAVY-MODERATE",
    "optional_fourth": "OPTIONAL 4th",
}

_SCHEDULE: dict[str, dict[str, Any]] = _nominal_schedule()
"""The NOMINAL week — the shape `training_week.json` requires, and the answer only when the Hevy record cannot be read (the
result then says the sequence was UNREADABLE). What is served is the SEQUENCE (`SESSION_SEQUENCE`, `session_sequence.
next_session`), never this weekday. v0.4's nominal week is `program_v04.NOMINAL_WEEK`."""


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
    in_block: list[dict[str, Any]] | None = None,
    deload_sets_pct: int | None = None,
) -> dict[str, Any]:
    """The session for one role, as data: exposures, sets (top / back_off / working), reps, and its lifting minutes.

    #5069 (owner ruling 5): the session fits the charter's lifting-minute cap — `trim_to_time` drops accessories, last-listed
    first, and records what it dropped (`time_trim`); anchors are never cut for time. `session_minutes` is the estimate after
    every trim (`session_minutes_estimate`).

    `in_block` (#4409): `in_block_variant.performed_in_block` — a slot keeps its in-block variant.

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
        pref = in_block_variant.prefer(in_block, role, pattern, intensity, keys, ANCHORS[pattern].get("moderate_catalog_keys"))
        keys = pref["keys"] if pref else keys
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
            sets = [{"kind": "top", "reps": list(spec["reps"]), "rpe": list(_EFFORT[spec["effort"]])}] + [
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
                **in_block_variant.exposure_fields(pref, key),
            }
        )
    acc = EXPOSURES["accessory"]
    for k in tmpl["accessories"]:
        n_acc = int((tmpl.get("accessory_sets") or {}).get(k, acc["sets"]))  # #5053: a floor slot may run more than 2 sets
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
                "sets": [{"kind": "working", "reps": list(acc["reps"])} for _ in range(n_acc)],
                "rest_seconds": acc["rest_seconds"],
                "cue": acc["cue"],
            }
        )
    time_trim = trim_to_time(exposures)  # #5069: the charter's lifting-minute cap, accessories first
    in_block_variant.stamp_template_ids(exposures, catalog_movements, in_block)  # #4431: the one slot-template resolver
    deload_info = None
    if deload:
        deload_info = _deload_trim(exposures, int(deload_sets_pct if deload_sets_pct is not None else _deload_cfg()["sets_pct"]))
    return {
        "archetype": tmpl["archetype"],
        "program_version": PROGRAM_VERSION,
        "session_role": role,
        "role_label": _ROLE_LABEL[role],
        "deload": deload,
        "deload_trim": deload_info,
        "exposures": exposures,
        "total_sets": sum(len(e["sets"]) for e in exposures),
        "session_minutes": session_minutes_estimate(exposures),
        "time_trim": time_trim,
        "charter_version": CHARTER_VERSION,
        "hevy_folder": HEVY_FOLDERS[tmpl["archetype"]],
        "distribution": SESSION_DISTRIBUTION_PROVENANCE,
    }


def planned_session(
    day: str,
    *,
    block_workouts: list[dict[str, Any]] | None = None,
    catalog_movements: dict[str, Any] | None = None,
    skill_ceiling: int = 2,
    deload_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """What the program serves on `day`: the next UNDONE session of the sequence (#4110), and
    its §3 prescription. Before the block start the weekday grid answers, and the result says
    which did. `block_workouts` is the Hevy record since the block start (None = not read).

    Only meaningful when the program is ACTIVE; the caller (`plan_engine`) reports the
    JSON grid instead when it is not.
    """
    from training import session_sequence

    entry = session_sequence.next_session(day, block_workouts, deload_records)
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
        ib = in_block_variant.performed_in_block(block_workouts, catalog_movements, day)  # #4409
        applied = ((entry.get("deload_recommendation") or {}).get("applied_on")) or {}  # #5070: his recorded word's own cut
        out["prescription"] = session_prescription_for_role(
            role,
            deload=bool(entry.get("deload")),
            catalog_movements=catalog_movements,
            skill_ceiling=skill_ceiling,
            in_block=ib,
            deload_sets_pct=applied.get("sets_pct"),
        )
    return out


def weekly_sets_by_pattern() -> dict[str, int]:
    """Anchor sets per pattern over one program week — the five roles of the charter's split."""
    out: dict[str, int] = {}
    for role in SESSION_SEQUENCE["session_roles"]:
        for e in session_prescription_for_role(role)["exposures"]:
            if e["kind"] == "anchor":
                out[e["pattern"]] = out.get(e["pattern"], 0) + len(e["sets"])
    return out


REDLINE_MUSCLE_GROUPS: dict[str, dict[str, Any]] = {
    "quads": {"primary_muscles": ["quadriceps"], "range_key": "sets_per_muscle_wk", "frequency_key": "each_major_muscle_per_wk"},
    "hams_glutes": {
        "primary_muscles": ["hamstrings", "glutes"],
        "range_key": "sets_per_muscle_wk",
        "frequency_key": "each_major_muscle_per_wk",
    },
    "chest": {"primary_muscles": ["chest"], "range_key": "sets_per_muscle_wk", "frequency_key": "each_major_muscle_per_wk"},
    "back": {"primary_muscles": ["back"], "range_key": "sets_per_muscle_wk", "frequency_key": "each_major_muscle_per_wk"},
    # #5069: the shoulders+arms day lifts delts and arms ABOVE v0.4's 4–6 by ruling 5 — that band is their FLOOR now; the
    # charter's `volume_priorities` bands for them land with the volume-floor lane (#5053), not here
    "delts": {
        "primary_muscles": ["shoulders"],
        "range_key": "sets_per_muscle_wk_small",
        "frequency_key": "delts_per_wk",
        "band_top_binds": False,
    },
    "biceps": {
        "primary_muscles": ["biceps"],
        "range_key": "sets_per_muscle_wk_small",
        "frequency_key": "each_major_muscle_per_wk",
        "band_top_binds": False,
    },
    "triceps": {
        "primary_muscles": ["triceps"],
        "range_key": "sets_per_muscle_wk_small",
        "frequency_key": "each_major_muscle_per_wk",
        "band_top_binds": False,
    },
}
"""The per-muscle set ranges, keyed to the catalog's `primary_muscle` (#4090): v0.4's 8–12 (~10, #4147) for quads,
hams/glutes, chest, back; 4–6 for delts and arms, which since the shoulders+arms day (#5069) is a floor, not a ceiling
(`band_top_binds: False`). Counted as DIRECT sets (the movement's primary muscle) — §3's 'mostly indirect' is the pressing
and pulling on top of these. `frequency_key` names the charter's `split.frequency` target each group is held to."""


def weekly_sets_by_muscle(catalog_movements: dict[str, Any], skill_ceiling: int = 2) -> dict[str, dict[str, Any]]:
    """Hard sets AND sessions per redline muscle group over one program week (the five roles), with the set range each must
    sit in (`owner_redlines`) and the weekly frequency the charter asks of it (`split.frequency`, owner ruling 5)."""
    from training import owner_redlines

    lift = owner_redlines.REDLINES["lifting_sessions_per_wk"]
    by_muscle, sessions_by_muscle = _week_tallies(catalog_movements, skill_ceiling)
    out: dict[str, dict[str, Any]] = {}
    for g, spec in REDLINE_MUSCLE_GROUPS.items():
        roles = set().union(*(sessions_by_muscle.get(m, set()) for m in spec["primary_muscles"]))
        out[g] = {
            "sets": sum(by_muscle.get(m, 0) for m in spec["primary_muscles"]),
            "range": list(lift[spec["range_key"]]),
            "band_top_binds": bool(spec.get("band_top_binds", True)),
            "frequency_per_wk": len(roles),
            "frequency_target": int(charter_value(f"split.frequency.{spec['frequency_key']}")),
            "sessions": [r for r in SESSION_SEQUENCE["session_roles"] if r in roles],
        }
    return out


def _week_tallies(catalog_movements: dict[str, Any], skill_ceiling: int = 2) -> tuple[dict[str, int], dict[str, set[str]]]:
    """({primary muscle: hard sets}, {primary muscle: roles}) over the five roles — the one tally under every weekly view."""
    by_muscle: dict[str, int] = {}
    sessions_by_muscle: dict[str, set[str]] = {}
    for role in SESSION_SEQUENCE["session_roles"]:
        rx = session_prescription_for_role(role, catalog_movements=catalog_movements, skill_ceiling=skill_ceiling)
        for e in rx["exposures"]:
            muscle = (catalog_movements.get(e.get("movement_key") or "") or {}).get("primary_muscle") or "unresolved"
            by_muscle[muscle] = by_muscle.get(muscle, 0) + len(e["sets"])
            sessions_by_muscle.setdefault(muscle, set()).add(role)
    return by_muscle, sessions_by_muscle


def _week_movement_sets(catalog_movements: dict[str, Any], skill_ceiling: int = 2) -> dict[str, int]:
    """{movement key: hard sets} over the five roles — the per-movement view the movement-counted floors read (#5053)."""
    out: dict[str, int] = {}
    for role in SESSION_SEQUENCE["session_roles"]:
        rx = session_prescription_for_role(role, catalog_movements=catalog_movements, skill_ceiling=skill_ceiling)
        for e in rx["exposures"]:
            k = e.get("movement_key") or ""
            out[k] = out.get(k, 0) + len(e["sets"])
    return out


def volume_floor_coverage(catalog_movements: dict[str, Any], skill_ceiling: int = 2) -> dict[str, Any]:
    """#5053: the charter's MEV floors and `sets_per_wk` bands against the five roles' weekly sets (`training.volume_floors`)."""
    from training import volume_floors

    by_muscle, _ = _week_tallies(catalog_movements, skill_ceiling)
    by_movement = _week_movement_sets(catalog_movements, skill_ceiling)
    by_muscle = volume_floors.movement_counts(by_muscle, by_movement)
    accs = {r: list(t["accessories"]) for r, t in SESSION_TEMPLATES.items()}
    return {
        "floors": volume_floors.floor_coverage(by_muscle, accs),
        "bands": volume_floors.charter_band_rows(by_muscle),
        "sets_by_muscle": dict(sorted(by_muscle.items())),
        "charter_version": CHARTER_VERSION,
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
        "block_lock_history": BLOCK_LOCK_HISTORY,  # #5069: lifted by owner ruling 6 — history, never a guard
        "session_time_model": SESSION_TIME_MODEL,
        "lifting_minutes_range": lifting_minutes_range(),
        "charter_version": CHARTER_VERSION,
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
