"""program_v04.py — TRAINING_PROGRAM v0.4 (four-session upper/lower), SUPERSEDED 2026-10-18, kept readable.

Owner rulings 2026-10-18 (epic #5067, rulings 5 and 6): five lifting days in the charter's order
(`config/training_charter.json` `split.sequence`), and "the v0.4 lock to 2026-11-04 is lifted
now". The five-day program lives in `training.program_structure` (#5069); this module keeps
v0.4's structure as HISTORY, the way `training.program_v03` keeps v0.3's, so:

  * the session sequence can credit every session logged BEFORE the cut-over with the v0.4 role
    it was served as (`session_sequence` reads `SESSION_SEQUENCE` here for the days before
    `program_structure.SESSION_SEQUENCE['cutover']['on']`) — the live block is not re-anchored;
  * a routine, plan or adherence row written under v0.4 still reads against the program it was
    written for;
  * the owner's block lock (#4161) is a dated record of what was decided, not a guard. Nothing
    reads it to refuse anything.

The four v0.4 roles' TEMPLATES are not copied: the five-day program kept all four unchanged and
added the fifth, so `program_structure.SESSION_TEMPLATES` is still the definition of each of them.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from common.pacific_time import parse_day_key

SUPERSEDED: dict[str, Any] = {
    "program_version": "0.4",
    "split": "upper_lower",
    "superseded_on": "2026-10-18",
    "superseded_by": "1.0",
    "issue": "#5069",
    "ruling": "owner rulings 2026-10-18 (epic #5067): ruling 5 — the charter's lifting days in its order (`split`); ruling 6 — the v0.4 lock is lifted now",
    "approved": "2026-09-23 (#4147, DECISION#2026-09-24T03:10:59); ratified 2026-09-25 (#4161)",
    "prose_home": "s3://matthew-life-platform/config/coaching/TRAINING_PROGRAM_v0.4.md",
    "note": "v0.4 ran as a sequence from 2026-09-24; its credited sessions keep their v0.4 roles (session_sequence's cut-over).",
}

SESSION_SEQUENCE: dict[str, Any] = {
    "program_version": "0.4",
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
    "provenance": "owner",
    "stated": "2026-09-23",
    "decision_sk": "DECISION#2026-09-24T03:10:59",
    "issue": "#4147 (order: #4110)",
}
"""v0.4's order, exactly as it was served (#4147). The block start is shared with the live program."""

NOMINAL_WEEK: dict[str, str] = {"0": "upper_heavy", "1": "lower_heavy", "3": "upper_volume", "4": "lower_volume"}
"""v0.4's nominal weekday placement (lifting days only; every other day was a walk)."""

BLOCK_LOCK: dict[str, Any] = {
    "weeks": 6,
    "block_start": "2026-09-24",
    "locked_until": "2026-11-04",
    "rule": "no STRUCTURAL edits to v0.4 (split, order, templates, accessories) before this date; loads and deloads run as written",
    "structure_fingerprint": "000ffceefa732c6e",
    "provenance": "owner",
    "stated": "2026-09-23",
    "decision_sk": "DECISION#2026-09-24T03:10:59",
    "lifted": {
        "on": "2026-10-18",
        "by": "owner ruling 6, 2026-10-18 (epic #5067): 'the v0.4 lock to 2026-11-04 is lifted now'",
        "issue": "#5069",
    },
}
"""HISTORY. The owner's 6-week lock on v0.4 (#4161 enforced it as a guard); lifted by his ruling of 2026-10-18.
The fingerprint is the value recorded at the lock; `session_sequence.structure_fingerprint()` still measures the
live structure, and nothing compares the two to refuse an edit."""


# ── #5080: the FROZEN v0.4 builder — HISTORY, for the shadow run and the one-command revert ─────────────────────────
# The pre-charter engine no longer exists as code (wave 1 made the generator the charter engine), so "v0.4" can only be
# compared against, or reverted to, as a frozen definition. Everything below is v0.4 as it was SERVED (2026-09-24 ..
# 2026-10-18), recorded as data and never read from a live module: the four role templates with the movement each slot
# resolved to, the pre-charter rep scheme and RPE, v0.3 §3's entry ramp, and v3.3's one pre-planned deload (recorded,
# never applied — #5070: a deload is his recorded word, under a revert too). No
# progression, no rotation, no cardio dose, no steps target — v0.4 had none of them. A live module changing (the
# charter's templates, effort ceilings, ramp or deload) moves nothing here; that is the point of a frozen baseline.
V04_EXPOSURES: dict[str, dict[str, Any]] = {
    "heavy": {"top_sets": 1, "reps": [4, 6], "rpe": [7, 8], "back_off_sets": 2, "back_off_pct": -10, "rest_seconds": 180},
    "moderate": {"sets": 3, "reps": [6, 10], "rpe": [7, 8], "rest_seconds": 120},
    "volume": {"sets": 3, "reps": [8, 12], "rpe": [7, 8], "rest_seconds": 120},
    "accessory": {"sets": 2, "reps": [8, 15], "rir": [1, 2], "rest_seconds": 90},
}
"""v0.4's rep scheme as served: the pre-charter `top_rpe` [7, 8] on the compounds and v0.3 §3's accessories at RIR 1–2."""

V04_TEMPLATES: dict[str, dict[str, Any]] = {
    "upper_heavy": {
        "archetype": "upper",
        "anchors": [
            ["bench", "heavy", "barbell_bench_press", None],
            ["row", "heavy", "machine_row", None],
            ["overhead_press", "moderate", "machine_shoulder_press", None],
            ["vertical_pull", "moderate", "lat_pulldown", 2],
        ],
        "accessories": ["cable_tricep_pushdown", "db_curl"],
    },
    "lower_heavy": {
        "archetype": "lower",
        "anchors": [["squat", "heavy", "squat_barbell", None], ["hinge", "moderate", "romanian_deadlift_barbell", None]],
        "accessories": ["leg_press", "leg_curl", "calf_raise_machine"],
    },
    "upper_volume": {
        "archetype": "upper",
        "anchors": [
            ["bench", "volume", "barbell_bench_press", None],
            ["row", "volume", "machine_row", None],
            ["overhead_press", "volume", "machine_shoulder_press", None],
            ["vertical_pull", "volume", "lat_pulldown", 2],
        ],
        "accessories": ["cable_chest_fly", "cable_tricep_pushdown", "db_curl"],
    },
    "lower_volume": {
        "archetype": "lower",
        "anchors": [["hinge", "volume", "deadlift_trap_bar", None], ["squat", "volume", "squat_barbell", None]],
        "accessories": ["leg_curl", "calf_raise_machine", "machine_crunch"],
    },
}
"""Per v0.4 role: [pattern, intensity, the movement the slot resolved to, a set-count override]. The movement is FROZEN
(barbell bench and squat under the #4080 anchor exemption, the RDL as the moderate hinge, the trap bar as the volume
hinge) — the frozen builder never resolves against the live catalog."""

V04_RAMP: dict[str, Any] = {
    "start_pct": 60,
    "step_pct_per_wk": 5,
    "ramp_to_week": 6,
    "cap_pct": 85,
    "base": "e1RM",
    "rounding_lb": 5,
    "source": "TRAINING_PROGRAM v0.3 §3 entry ramp (#4090, #4388), the ramp v0.4 loads ran on",
}
"""The ramp's share of e1RM by program week: 60 % in week 1, +5 %/wk, held at 85 % from week 6. No progression above it."""

V04_DELOAD: dict[str, Any] = {
    "rule": "ONE pre-planned deload at the later of program week 6 or the block lock (v3.3, #4161)",
    "starts_on": "2026-11-04",
    "days": 7,
    "sets_pct": -40,
    "loads": "held",
}
"""v0.4's scheduled deload as recorded (owner_redlines v3.3) — INFORMATION ONLY. The builder never applies it: owner
ruling 2026-10-18 (#5070) is that no deload is scheduled or automatic, and that ruling outranks v0.4 under a revert
too. `build_session` reports `would_have_deloaded`; sets are cut only by a record of his word (`owner_deload`)."""

_LB_PER_KG = 2.20462


def v04_role(credited_sessions: int) -> str:
    """The v0.4 role served after `credited_sessions` loaded sessions since the block start, in v0.4's order."""
    roles = list(SESSION_SEQUENCE["session_roles"])
    first = roles.index(SESSION_SEQUENCE["first_role"])
    return roles[(first + max(0, int(credited_sessions))) % len(roles)]


def _day(date_str: str) -> date:
    """A YYYY-MM-DD day through THE calendar-day parse (#3609/#3741); an unparseable day raises, as before."""
    d = parse_day_key(date_str)
    if d is None:
        raise ValueError(f"not a YYYY-MM-DD day: {date_str!r}")
    return d


def v04_week(target_date: str, credited_sessions: int) -> int:
    """v0.4's program week: a week closes when its four sessions are done AND seven days have passed (#4161)."""
    days = (_day(target_date[:10]) - _day(SESSION_SEQUENCE["block_start"])).days
    return min(max(0, int(credited_sessions)) // int(SESSION_SEQUENCE["sessions_per_week"]), max(0, days) // 7) + 1


def _ramp_pct(week: int) -> int:
    r = V04_RAMP
    return min(r["start_pct"] + r["step_pct_per_wk"] * (max(1, week) - 1), r["cap_pct"])


def _load_lb(e1rm_kg: float | None, pct: int, bottom_reps: int, rpe_ceiling: float) -> float | None:
    """The ramp's share of e1RM, capped where the rep range's bottom at the RPE ceiling would land (Epley), rounded DOWN to 5 lb."""
    if not e1rm_kg or e1rm_kg <= 0:
        return None
    ramp_kg = e1rm_kg * pct / 100.0
    rep_cap_kg = e1rm_kg / (1 + (bottom_reps + (10 - rpe_ceiling)) / 30.0)
    step = V04_RAMP["rounding_lb"]
    lb = int(min(ramp_kg, rep_cap_kg) * _LB_PER_KG / step) * step
    return float(lb) if lb > 0 else None


def _deload_sets(n: int, sets_pct: int) -> int:
    return max(1, round(n * (100 + int(sets_pct)) / 100.0))


def v04_deload_on(target_date: str) -> bool:
    start = _day(V04_DELOAD["starts_on"])
    return start <= _day(target_date[:10]) < start + timedelta(days=int(V04_DELOAD["days"]))


def build_session(target_date: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """The session the FROZEN v0.4 program would serve on `target_date` — a pure function, HISTORY (#5080).

    `inputs` (all optional): `credited_sessions` (loaded sessions since the block start — picks the role and, with the
    calendar, the program week), `role` (overrides the order), `e1rm_kg` ({movement_key: kg} — without one a slot's load
    is None and says why), `owner_deload` (the owner's DELOAD# record covering the day, or None). Every set, rep and
    load comes from the frozen records above; nothing reads the charter or the store.

    THE DELOAD (owner ruling 2 of 2026-10-18, #5070): v0.4's calendar deload is NEVER applied — it is reported as
    `deload.would_have_deloaded` only. Sets are cut only when `owner_deload` (his recorded word) covers the day, by
    that record's `sets_pct` (v0.4's −40 % when the record carries none); loads are held either way."""
    inputs = dict(inputs or {})
    credited = int(inputs.get("credited_sessions") or 0)
    role = str(inputs.get("role") or v04_role(credited))
    week = v04_week(target_date, credited)
    pct = _ramp_pct(week)
    scheduled = v04_deload_on(target_date)
    word = inputs.get("owner_deload") or None
    cut_pct = int(word.get("sets_pct") or V04_DELOAD["sets_pct"]) if word else 0
    e1rm = dict(inputs.get("e1rm_kg") or {})
    tmpl = V04_TEMPLATES[role]
    exercises: list[dict[str, Any]] = []
    slots = [(p, i, k, n) for p, i, k, n in tmpl["anchors"]] + [(None, "accessory", k, None) for k in tmpl["accessories"]]
    for pattern, intensity, key, n_override in slots:
        spec = V04_EXPOSURES[intensity]
        lo, hi = spec["reps"]
        rpe_hi = float(spec["rpe"][1]) if "rpe" in spec else 10.0 - float(spec["rir"][0])
        load = _load_lb(e1rm.get(key), pct, lo, rpe_hi)
        if intensity == "heavy":
            back = None if load is None else float(int(load * (100 + spec["back_off_pct"]) / 100.0 / 5) * 5)
            sets = [{"kind": "top", "reps": [lo, hi], "load_lb": load}] + [
                {"kind": "back_off", "reps": [lo, hi], "load_lb": back} for _ in range(spec["back_off_sets"])
            ]
        else:
            sets = [{"kind": "working", "reps": [lo, hi], "load_lb": load} for _ in range(int(n_override or spec["sets"]))]
        if word:
            sets = sets[: _deload_sets(len(sets), cut_pct)]
        exercises.append(
            {
                "movement_key": key,
                "pattern": pattern,
                "intensity": intensity,
                "sets": sets,
                "rest_seconds": spec["rest_seconds"],
                "load_basis": f"{pct} % of e1RM (v0.4 ramp week {week})" if load is not None else "no e1RM supplied — load unprescribed",
            }
        )
    return {
        "program_version": SUPERSEDED["program_version"],
        "history": "FROZEN v0.4 (superseded 2026-10-18) — a shadow / revert baseline, never the charter",
        "target_date": target_date[:10],
        "session_role": role,
        "archetype": tmpl["archetype"],
        "week": week,
        "ramp_pct": pct,
        "exercises": exercises,
        "total_sets": sum(len(e["sets"]) for e in exercises),
        "cardio_block": None,
        "steps_target": None,
        "progression": None,
        "deload": {
            "on": bool(word),
            "applied_by": f"owner DELOAD# record from {word.get('start_date')}" if word else None,
            "sets_pct": cut_pct if word else None,
            "would_have_deloaded": scheduled,
            "v04_rule": f"{V04_DELOAD['rule']} — not applied: a deload is his recorded word (#5070)",
            "starts_on": V04_DELOAD["starts_on"],
        },
    }
