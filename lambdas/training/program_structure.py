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

The prose half of that argument is not this file: the red-team record and the v0.2 text go
to the owner-private coaching home (`s3://matthew-life-platform/config/coaching/
TRAINING_PROGRAM.md`). THIS file is the machine-readable half — the acceptance box that
says the anchors and the accessory pool must be "data the engine reads (not prose), so 'is
the accessory layer rotating' is a computed check in the constraint block".

WHY A MODULE AND NOT config/training_week.json

`config/*.json` is NOT staged into the Lambda bundle (`build_bundle.stage_tree` stages
food_vocabulary/personas/coaches only), so a repo-side edit to a config file is INERT at
runtime — #3675, #3671, and the same reason `owner_redlines.py` and
`training_context_registry.py` are modules. The engine reads `training_week.json` from S3
at runtime today. A program the engine must obey ships in the bundle or it does not ship.

Both readers reach the week grid through ONE seam (`training.program_seam.
resolve_week_grid`), so there is exactly one place that decides module-vs-JSON and exactly
one answer. The seam names its source in its result; it never silently substitutes.

STATUS: NOT ACTIVE. `ACTIVE = False` until the owner has read v0.2 and said yes
(gate:owner, #3755). While it is False the seam serves the live JSON grid unchanged and
`plan_engine.constraint_block` reports this program as PROPOSED — the same posture #3753
and #3715 took, for the same reason: an unratified program must not steer a prescription.

PROVENANCE VOCABULARY (ADR-105 — every number says where it came from)

  "owner"             — he chose it, on the date in `stated`.
  "owner-history"     — mined from his own logged history / the blueprint.
  "population-derived"— from training literature, NOT from his own variance.
  "platform-proposed" — the PLATFORM picked this number and nobody has ratified it.
                        The weakest label on the board and it is used deliberately: a
                        rotation window of 14 days is not his, is not literature, and
                        calling it "population-derived" would dress a choice as evidence.

WHAT THIS FILE REFUSES TO DO

It does not restate the rate target, the protein floor or the walking floor. Those are
`owner_redlines.REDLINES` and there is one home for each. What it DOES do is name, in
`summary()["conflicts"]`, where this program contradicts a redline he has already stated —
a six-lifting-day PPL week is in direct tension with `lifting_sessions_per_wk` 2-3, and a
program that quietly overrode a stated redline would be the worst possible outcome of this
issue.
"""

from __future__ import annotations

from typing import Any, Iterable

ACTIVE = False
"""Flip to True only when the owner has approved v0.2. gate:owner (#3755)."""

LAST_REVIEWED_BY_OWNER: str | None = None
"""ISO date the owner last read this program. None means never."""

PROGRAM_VERSION = "0.2"
ISSUE = "#3755"
PROSE_HOME = "s3://matthew-life-platform/config/coaching/TRAINING_PROGRAM.md"

SPLIT = "ppl"
"""push / pull / legs, run at high frequency so each big-3 pattern lands 2x/wk.

Owner ruling, recorded on #3755 (2026-09-19): PPL with a high-frequency big-3, against the
v0.1 upper/lower/engine grid. That is the STRUCTURE decision; the frequency NUMBER under
each anchor below is population-derived and says so.
"""

SPLIT_DECISION: dict[str, Any] = {
    "chosen": "ppl",
    "rejected": "upper/lower/engine (TRAINING_PROGRAM.md v0.1)",
    "provenance": "owner",
    "stated": "2026-09-19",
    "note": (
        "The owner-private blueprint records high-frequency mixed training with the big three several times a week "
        "as the structure that worked for him during the campaign that held, and he ruled for it on #3755. PPL is the "
        "split that lets each big-3 pattern repeat 2x/wk without stacking the same joints on consecutive days."
    ),
}


# ── the anchors: the big three, as PATTERN FAMILIES ──────────────────────────
# A pattern, not a movement id, because the specific bar is substitutable and the pattern
# is not: `goblet_squat` and a barbell back squat are the same anchor for the purpose of
# "did the squat pattern get trained twice this week", and treating them as two different
# movements is exactly how a program reports diversity it does not have.
#
# `hevy_title_hints` are lower-cased substrings matched against the exercise NAME on the
# performed Hevy record — that is the only identifier the wire carries (the DDB hevy row's
# `exercises[].name`). Catalog keys are listed where a curated movement exists; several
# anchor members have NO catalog entry today and that gap is reported by
# `catalog_gaps()` rather than left for someone to discover at the rack.
ANCHORS: dict[str, dict[str, Any]] = {
    "squat": {
        "pattern": "knee-dominant squat",
        "frequency_per_week": {
            "low": 2,
            "high": 3,
            "provenance": "population-derived",
            "note": (
                "2-3x/wk per pattern is the training-literature frequency band for hypertrophy/strength at equated "
                "weekly volume; it is NOT derived from Matthew's own session-to-session variance and must say so "
                "wherever it fires (ADR-105). Re-derive it from his own data once cycle 17 has enough anchor-lift "
                "sessions to estimate one."
            ),
        },
        "catalog_keys": ["goblet_squat", "leg_press"],
        "hevy_title_hints": ["squat", "leg press", "hack squat"],
        "primary_muscles": ["quadriceps", "glutes"],
        "provenance": "owner",
        "stated": "2026-09-19",
        "note": "Big-3 member. The split choice is his; the frequency band above is not.",
    },
    "bench": {
        "pattern": "horizontal press",
        "frequency_per_week": {
            "low": 2,
            "high": 3,
            "provenance": "population-derived",
            "note": "Same literature band as the squat row; same caveat — not his variance.",
        },
        "catalog_keys": ["barbell_bench_press", "db_bench_press_flat", "machine_chest_press", "incline_db_press"],
        "hevy_title_hints": ["bench press", "chest press"],
        "primary_muscles": ["chest", "triceps", "shoulders"],
        "provenance": "owner",
        "stated": "2026-09-19",
        "note": "Big-3 member. `barbell_bench_press` is skill_tier 3 and the live week config's skill_ceiling is 2 — see `conflicts`.",
    },
    "deadlift": {
        "pattern": "hip hinge",
        "frequency_per_week": {
            "low": 2,
            "high": 2,
            "provenance": "population-derived",
            "note": (
                "The hinge band is set at the BOTTOM of the 2-3 range rather than the middle: the hinge is the "
                "highest systemic-fatigue pattern of the three and this is the one place the program is deliberately "
                "less aggressive than the split would allow. Literature-derived, not his."
            ),
        },
        "catalog_keys": ["machine_hip_thrust", "leg_curl"],
        "hevy_title_hints": ["deadlift", "romanian deadlift", "rdl", "good morning", "back extension"],
        "primary_muscles": ["hamstrings", "glutes", "back"],
        "provenance": "owner",
        "stated": "2026-09-19",
        "note": (
            "Big-3 member. Hinge is the pattern with the thinnest catalog coverage — the performed record shows "
            "'Romanian Deadlift (Barbell)' with no curated movement behind it (see `catalog_gaps()`)."
        ),
    },
}


# ── the accessory layer: what rotates ────────────────────────────────────────
# One pool per PPL day. These are the movements that are allowed — indeed required — to
# change week to week. The anchors repeat on purpose; the accessories are the diversity
# the owner reported missing, and the rotation rule below is what makes that a computed
# property rather than an intention.
ACCESSORY_POOL: dict[str, list[str]] = {
    "push": [
        "incline_db_press",
        "cable_chest_fly",
        "machine_shoulder_press",
        "db_shoulder_press",
        "db_lateral_raise",
        "cable_tricep_pushdown",
    ],
    "pull": ["lat_pulldown", "machine_row", "one_arm_db_row", "reverse_pec_deck", "db_curl", "db_wrist_curl"],
    "legs": ["leg_curl", "machine_hip_thrust", "calf_raise_machine", "goblet_squat", "machine_crunch"],
}

ROTATION_RULE: dict[str, Any] = {
    "rule": "no accessory movement repeats within 14 days unless it is an anchor",
    "window_days": 14,
    "anchors_exempt": True,
    "provenance": "platform-proposed",
    "stated": "2026-09-20",
    "note": (
        "The INTENT is the owner's — he reported too little exercise diversity in week 1 of cycle 17 (#3755). The "
        "14-day WINDOW is the platform's choice and nobody has ratified it: it is not from his history and it is not "
        "from literature. It is set to 14 so that at 2 sessions per PPL day per week the pool of 5-6 accessories per "
        "day is large enough to satisfy the rule without inventing movements. Treat the number as a proposal the "
        "owner may move, not as a finding."
    ),
}


# ── the day shape ────────────────────────────────────────────────────────────
# The week grid below cannot express a second session on one day: its `schedule` maps a
# day-of-week to exactly ONE archetype, and every consumer reads it that way. So the
# two-a-day pattern lives here, and `week_grid()["_notes"]` says so out loud rather than
# letting a reader of the grid conclude that PM cardio was dropped.
DAY_SHAPE: dict[str, Any] = {
    "am": "lift (the PPL session — the hard, loaded work)",
    "pm": "easy cardio (Zone 2 walk / bike; conversational, never intervals)",
    "provenance": "owner-history",
    "stated": "2026-06-19",
    "note": (
        "The owner-private blueprint records AM lift + PM easy cardio as the pattern during the campaign that held, "
        "with walking as 'the single most replicable, highest-confidence driver in the dataset'. The WALKING FLOOR "
        "itself is not restated here — it has one home, owner_redlines.REDLINES['walking_floor_hr_wk']."
    ),
    "not_expressible_in_week_grid": (
        "training_week.json's `schedule` holds one archetype per day. The PM session is therefore NOT in the grid; "
        "a consumer that wants it must read DAY_SHAPE. Making it expressible is a schema change to the grid and to "
        "every reader of it, deliberately not smuggled into this issue."
    ),
}


# ── the week grid ────────────────────────────────────────────────────────────
# MUST return the same top-level shape `config/training_week.json` provides — the seam
# hands this dict to `routine_generator.generate_routines`, which indexes it directly.
# `tests/test_program_structure_3755.py::test_week_grid_keys_equal_the_json_keys` holds
# the two key sets equal so a drift here is a red test, not a KeyError in a Lambda.
_ARCHETYPE_TARGETS: dict[str, list[str]] = {
    "push": ["chest", "shoulders", "triceps"],
    "pull": ["back", "biceps"],
    "legs": ["quadriceps", "hamstrings", "glutes", "calves"],
    "aerobic": [],
    "mobility": [],
    "rest": [],
}

_SCHEDULE: dict[str, dict[str, str]] = {
    "0": {"archetype": "push", "label": "Monday push (AM) + easy cardio (PM)"},
    "1": {"archetype": "pull", "label": "Tuesday pull (AM) + easy cardio (PM)"},
    "2": {"archetype": "legs", "label": "Wednesday legs (AM) + easy cardio (PM)"},
    "3": {"archetype": "push", "label": "Thursday push (AM) + easy cardio (PM)"},
    "4": {"archetype": "pull", "label": "Friday pull (AM) + easy cardio (PM)"},
    "5": {"archetype": "legs", "label": "Saturday legs (AM) + easy cardio (PM)"},
    "6": {"archetype": "rest", "label": "Sunday rest (easy walk optional)"},
}

# Every value below that DIFFERS from the live JSON grid, and why. A changed ceiling with
# no recorded reason is a number nobody owns.
WEEK_GRID_PROVENANCE: dict[str, dict[str, Any]] = {
    "schedule": {
        "changed_from": "upper / aerobic / lower / mobility / upper / full / rest",
        "provenance": "owner",
        "stated": "2026-09-19",
        "note": "The split ruling. Six lifting days so each big-3 pattern lands 2x/wk.",
    },
    "session_set_ceiling": {
        "changed_from": 25,
        "value": 18,
        "provenance": "platform-proposed",
        "note": (
            "Six sessions a week against the UNCHANGED weekly_volume_cap_per_muscle of 22 means the per-session "
            "ceiling has to come down or the week's cap is unreachable in practice. 18 is arithmetic from the cap, "
            "not a finding; the cap is the fail-safe and it did not move."
        ),
    },
    "session_minutes_ceiling": {
        "changed_from": 75,
        "value": 60,
        "provenance": "platform-proposed",
        "note": "An AM session that has to fit before work, with the PM cardio carrying the duration. Not measured.",
    },
    "weekly_volume_cap_per_muscle": {
        "value": 22,
        "provenance": "unchanged",
        "note": "The absolute fail-safe. This program does not raise it — a more aggressive plan earns volume by frequency, not by lifting the cap.",
    },
    "skill_ceiling": {
        "value": 2,
        "provenance": "unchanged",
        "note": "Still 2, which is why the barbell anchors are unreachable by the generator — see `conflicts`.",
    },
    "z2_floor_minutes": {
        "value": 90,
        "provenance": "unchanged",
        "note": (
            "Deliberately NOT raised to match the 8.5 hr/wk walking floor. That floor has one home "
            "(owner_redlines) and this knob drives a different thing — the portfolio guard that caps the strength "
            "budget. Two numbers for the same concept in two files is the defect, not the fix."
        ),
    },
}


def week_grid() -> dict[str, Any]:
    """The v0.2 week, in the exact shape `config/training_week.json` provides.

    Served by `program_seam.resolve_week_grid` ONLY when `ACTIVE` is True. While the
    program is PROPOSED this function is still callable (and tested) — it just is not what
    the engine runs on.
    """
    return {
        "_comment": (
            f"TRAINING_PROGRAM v{PROGRAM_VERSION} ({SPLIT.upper()}, high-frequency big-3) as the engine reads it. "
            f"Generated by lambdas/training/program_structure.py ({ISSUE}); the prose lives at {PROSE_HOME}. "
            "day_of_week is 0=Monday .. 6=Sunday; archetype names are handled generically by routine_generator."
        ),
        "_version": 2,
        "schedule": dict(_SCHEDULE),
        "archetype_targets": {k: list(v) for k, v in _ARCHETYPE_TARGETS.items()},
        "session_set_ceiling": 18,
        "session_minutes_ceiling": 60,
        "weekly_volume_cap_per_muscle": 22,
        "skill_ceiling": 2,
        "re_entry_days_threshold": 7,
        "z2_floor_minutes": 90,
        "floor_session_set_count": 6,
        "floor_session_minutes": 20,
        "exercise_notes_mode": "one_best_line",
        "_exercise_notes_lookback_note": (
            "#3708: the runtime window is floored in code at exercise_history.FLOOR_LOOKBACK_DAYS — this value can "
            "widen it, never narrow it below the floor. Unchanged by v0.2."
        ),
        "exercise_notes_lookback_days": 3650,
        "_notes": [
            f"v{PROGRAM_VERSION}: split={SPLIT} (owner, 2026-09-19); big-3 anchors 2-3x/wk (population-derived, not his variance).",
            "The PM easy-cardio session is NOT in this grid — `schedule` holds one archetype per day. Read program_structure.DAY_SHAPE.",
            "session_set_ceiling 25 -> 18 and session_minutes_ceiling 75 -> 60 are arithmetic from six sessions/wk against an UNCHANGED weekly cap of 22; both are platform-proposed, not measured.",
            "UNRESOLVED: six lifting days contradicts owner_redlines.REDLINES['lifting_sessions_per_wk'] (2-3). See program_structure.summary()['conflicts'].",
        ],
    }


# ── the conflicts this program has not resolved ──────────────────────────────
# Named here rather than discovered later. `summary()` carries them into every constraint
# block, so a plan built on this program cannot be built on a silent override.
def conflicts() -> list[dict[str, Any]]:
    """Where v0.2 contradicts something already stated. Computed against owner_redlines."""
    from training import owner_redlines

    lifting = owner_redlines.REDLINES["lifting_sessions_per_wk"]
    lift_days = sum(1 for d in _SCHEDULE.values() if d["archetype"] not in ("rest", "aerobic", "mobility"))
    out: list[dict[str, Any]] = []
    if lift_days > lifting["high"]:
        out.append(
            {
                "id": "lifting_frequency_vs_redline",
                "program_says": f"{lift_days} lifting days/wk ({SPLIT} with a high-frequency big-3)",
                "redline_says": f"{lifting['low']}-{lifting['high']} lifting sessions/wk ({lifting['provenance']}, stated {lifting['stated']})",
                "resolved": False,
                "note": (
                    "Both are the owner's. The redline's reasoning is that extra lifting volume beyond 2-3x/wk costs "
                    "recovery without adding fat loss and that his willingness to train long should be routed to "
                    "walking; the split ruling asks for the structure that worked last time. A six-day PPL week at "
                    "HALF the per-session volume is not obviously a violation of the redline's intent — but that is "
                    "an argument, not a fact, and he has not had it. The engine must not pick a side silently."
                ),
            }
        )
    tier3 = [k for k, v in ANCHORS.items() if any(c == "barbell_bench_press" for c in v["catalog_keys"])]
    if tier3:
        out.append(
            {
                "id": "barbell_anchors_vs_skill_ceiling",
                "program_says": "the big three as barbell patterns (squat / bench / deadlift)",
                "redline_says": "week grid skill_ceiling=2 excludes barbell tier-3 movements until the Sports Medicine seat is staffed",
                "resolved": False,
                "note": (
                    "The generator CANNOT select a tier-3 barbell movement while skill_ceiling is 2, so 'bench' "
                    "resolves to the dumbbell/machine members of the family today. That is a real substitution and "
                    "it is stated rather than hidden. Raising the ceiling is a separate owner decision."
                ),
            }
        )
    return out


def catalog_gaps(catalog_movement_keys: Iterable[str]) -> dict[str, list[str]]:
    """Anchor/accessory keys named here that the movement catalog does not carry.

    Injected, not loaded: this module does no I/O (the catalog is a config the caller
    already read). A gap means the generator cannot select that movement — the program
    names a lift the engine has no way to prescribe.
    """
    known = set(catalog_movement_keys)
    gaps: dict[str, list[str]] = {}
    for name, anchor in ANCHORS.items():
        missing = [k for k in anchor["catalog_keys"] if k not in known]
        if missing:
            gaps[f"anchor:{name}"] = missing
    for day, pool in ACCESSORY_POOL.items():
        missing = [k for k in pool if k not in known]
        if missing:
            gaps[f"accessory:{day}"] = missing
    return gaps


# ── the computed check: is the accessory layer actually rotating? ────────────
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
    """`anchor:<family>` | `cardio` | `accessory` for one performed Hevy exercise name."""
    nl = _lower(name)
    if not nl:
        return "cardio"  # an unnamed block is not evidence of accessory diversity
    for family, anchor in ANCHORS.items():
        if any(hint in nl for hint in anchor["hevy_title_hints"]):
            return f"anchor:{family}"
    if any(hint in nl for hint in CARDIO_NAME_HINTS):
        return "cardio"
    return "accessory"


def accessory_rotation(
    *,
    window_start: str,
    window_end: str,
    hevy_workouts: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Distinct accessory movements per trailing window, computed from the Hevy record.

    ADR-105: the answer carries its `n` and its window. It is a measurement of what was
    PERFORMED, not a claim about what was programmed.

    `hevy_workouts` is the DDB `USER#matthew#SOURCE#hevy` row shape the MCP readers
    already return: `{"date": "YYYY-MM-DD", "exercises": [{"name": ..., "sets": [...]}]}`.
    Passed in, never fetched here — this module has no I/O, same contract as `plan_engine`.

    `None` means the read RAISED and the verdict is `unknown`. An empty list means the
    window genuinely holds no lifting sessions, which is ALSO `unknown` — a rotation rule
    over zero sessions is vacuously satisfied, and reporting that as `ok` is the #3767
    failure wearing gym clothes.
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
            "detail": "the Hevy record could not be read for this window — rotation is unmeasured, not clear",
            "honesty": ["accessory rotation is UNKNOWN: the read failed. Never report an unreadable rule as satisfied."],
        }

    days_by_movement: dict[str, set[str]] = {}
    anchor_days: dict[str, set[str]] = {}
    cardio_names: set[str] = set()
    sessions = 0
    session_days: set[str] = set()
    for row in hevy_workouts:
        exercises = row.get("exercises") or []
        if not exercises:
            continue
        day = str(row.get("date") or "")[:10]
        if not (window_start <= day <= window_end):
            continue
        sessions += 1
        session_days.add(day)
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
            "detail": "no lifting sessions in the window — the rotation rule is vacuous here, which is not the same as satisfied",
            "honesty": ["accessory rotation is UNKNOWN: n=0 sessions in the window. A rule with nothing to check is not a pass."],
        }

    repeats = sorted(
        ({"movement": name, "n_days": len(days), "days": sorted(days)} for name, days in days_by_movement.items() if len(days) > 1),
        key=lambda r: (-r["n_days"], r["movement"]),
    )
    distinct_accessories = len(days_by_movement)
    ok = not repeats
    return {
        **base,
        "ok": ok,
        "state": "rotating" if ok else "repeating",
        "n_sessions": sessions,
        "n_session_days": len(session_days),
        "distinct_accessories": distinct_accessories,
        "distinct_movements_total": distinct_accessories + len(anchor_days) + len(cardio_names),
        "anchors_trained": {family: {"n_days": len(days), "days": sorted(days)} for family, days in sorted(anchor_days.items())},
        "anchor_families_missing": sorted(set(ANCHORS) - set(anchor_days)),
        "repeats_within_window": repeats,
        "cardio_blocks_excluded": sorted(cardio_names),
        "detail": (
            f"{distinct_accessories} distinct accessory movement(s) over n={sessions} session(s) "
            f"({window_start}..{window_end}); {len(repeats)} repeated within the window"
        ),
        "honesty": [
            s
            for s in [
                (
                    None
                    if ACTIVE
                    else f"the rotation rule is PROPOSED ({ISSUE}, gate:owner) — this is a measurement of what happened, not a compliance verdict against an approved program"
                ),
                (
                    f"the {ROTATION_RULE['window_days']}-day window is {ROTATION_RULE['provenance']}: not from his history, not from literature"
                ),
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
            f"PROPOSED — v{PROGRAM_VERSION} is drafted from the owner's #3755 rulings and his own blueprint, and he "
            f"has not approved it. The engine still runs on the live config/training_week.json grid; this program is "
            f"reported so a plan is auditable, never obeyed ({ISSUE}, gate:owner)."
            if not ACTIVE
            else f"ACTIVE — owner-approved {LAST_REVIEWED_BY_OWNER}; the engine reads this program's week grid."
        ),
        "anchors": ANCHORS,
        "accessory_pool": ACCESSORY_POOL,
        "rotation_rule": ROTATION_RULE,
        "day_shape": DAY_SHAPE,
        "week_grid_provenance": WEEK_GRID_PROVENANCE,
        "conflicts": conflicts(),
        "population_derived_numbers": [
            f"{name}.frequency_per_week" for name, a in ANCHORS.items() if a["frequency_per_week"]["provenance"] == "population-derived"
        ],
        "platform_proposed_numbers": sorted(
            [f"week_grid.{k}" for k, v in WEEK_GRID_PROVENANCE.items() if v.get("provenance") == "platform-proposed"]
            + (["rotation_rule.window_days"] if ROTATION_RULE["provenance"] == "platform-proposed" else [])
        ),
    }
