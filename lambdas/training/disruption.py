"""disruption.py — the minimum viable day, disruption mode and the travel templates (#5088, epic #5067).

Owner ruling 2026-10-18: a late-December trip. The templates are ready before mid-December — a
resort/hotel gym variant and a bodyweight variant of every session type, steps held, two or
three short sessions a week, then a step back up on return. A rigid plan fails in a busy or a
travel week and one miss cascades; this module is the mode that keeps the HABIT instead.

THREE THINGS, all pure (the DDB read and write live in `mcp/tools_training_notes.py`, exactly
like the deload word, #5070):

  1. THE MINIMUM SESSION per role — the charter's `split.minimum_session` (anchors only, top
     set + one back-off, at most `max_movements` so the estimate fits `minutes`). The roles are
     the charter's `split.sequence`, slugged (`role_keys()`); a role's anchor patterns come from
     `program_structure.SESSION_TEMPLATES` when the program carries it, else from
     `FALLBACK_ROLE_ANCHORS` (the shoulders-and-arms day until #5069 lands its template).
  2. THE POOLS — `gym_minimum` (the role's own anchors at the club), `hotel` (dumbbell-only) and
     `bodyweight`. Every movement resolves through the catalog's `generator_eligible`, first
     eligible member in the listed order, never a key the catalog does not carry.
  3. DISRUPTION MODE — an OWNER-ONLY record he switches on from chat
     (`USER#matthew#SOURCE#training_constraints / MODE#disruption#<start>`, with `until`,
     `template` travel|busy, `words` VERBATIM — Tier 2, CROSS_PHASE). While it is on the plan
     HOLDS habits (the charter step floor, the protein floor, the sleep floor, one short
     session; on `travel` two or three a week) instead of targets. When it ends, one
     STEP-BACK-UP window serves the minimum session at the club, then the full split again.
     The coach OFFERS the mode (`offer()`: a charter travel window near the day, or a
     missed-session streak) and never applies it — only his record does.

A travel window whose dates are null (the charter's late-December entry today) is read as
"dates pending the owner": it is listed, never offered and never guessed.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

from common.pacific_time import parse_day_key, shift_day_key

logger = logging.getLogger(__name__)
ISSUE = "#5088"
DISRUPTION_SOURCE = "training_constraints"
DISRUPTION_PK = f"USER#matthew#SOURCE#{DISRUPTION_SOURCE}"
DISRUPTION_SK_PREFIX = "MODE#disruption#"
DISRUPTION_STORE = f"{DISRUPTION_PK} / {DISRUPTION_SK_PREFIX}<YYYY-MM-DD> — CROSS_PHASE (ADR-077), Tier 2 owner-only"

PRIMARY_VARIANT = "disruption"
"""The variant the generator persists as the served disruption session (the second pool rides as `floor`).
A reduced session by design: no load floor is asserted on it (`mcp.hevy_prescription_gate.NO_LOAD_VARIANTS`)."""

PHASE_OFF, PHASE_ACTIVE, PHASE_STEP_BACK_UP = "off", "active", "step_back_up"

# The anchor exposures of a charter role the program does not carry yet. #5069 builds the
# shoulders-and-arms template; until it lands this is the minimum's shape for that day, and
# once it lands `role_patterns` reads the program's own template instead.
FALLBACK_ROLE_ANCHORS: dict[str, list[tuple[str, str]]] = {
    "shoulders_arms": [("overhead_press", "moderate"), ("delts", "volume"), ("biceps", "volume"), ("triceps", "volume")],
}
FALLBACK_ROLE_ARCHETYPE = {"shoulders_arms": "upper"}

# Extras a VARIANT appends after the anchors while it stays under `max_movements` — a lower day
# away from the club has two anchors, so a single-leg slot and a carry fill the time it saves.
VARIANT_EXTRAS: dict[str, list[str]] = {"lower": ["single_leg", "carry"]}

# pattern -> pool -> catalog keys in preference order. `gym` for the six program anchor patterns is
# NOT listed here: it is `program_structure.ANCHORS[p]` (the moderate members first on a moderate
# exposure), so the club minimum is the same lifts the full session prescribes.
POOLS: dict[str, dict[str, list[str]]] = {
    "bench": {"hotel": ["floor_press_dumbbell", "db_bench_press_flat"], "bodyweight": ["push_up", "knee_push_up"]},
    "row": {"hotel": ["one_arm_db_row", "db_chest_supported_rows"], "bodyweight": ["inverted_row"]},
    "overhead_press": {"hotel": ["overhead_press_dumbbell", "seated_overhead_press_dumbbell"], "bodyweight": ["pike_pushup"]},
    "vertical_pull": {"hotel": ["pullover_dumbbell"], "bodyweight": ["doorway_face_pulls", "superman"]},
    "squat": {"hotel": ["goblet_squat", "squat_dumbbell"], "bodyweight": ["squat_bodyweight", "reverse_lunge"]},
    "hinge": {
        "hotel": ["romanian_deadlift_dumbbell", "db_stiff_legged_deadlift"],
        "bodyweight": ["single_leg_glute_bridge", "glute_bridge"],
    },
    "delts": {
        "gym": ["lateral_raise_machine", "db_lateral_raise"],
        "hotel": ["db_lateral_raise"],
        "bodyweight": ["pike_pushup", "prone_w_raise"],
    },
    "biceps": {"gym": ["db_curl"], "hotel": ["db_curl", "hammer_curl_dumbbell"], "bodyweight": ["inverted_chin_curls"]},
    "triceps": {
        "gym": ["cable_tricep_pushdown"],
        "hotel": ["triceps_extension_dumbbell", "lying_db_tricep_extension"],
        "bodyweight": ["push_up_close_grip"],
    },
    "single_leg": {"hotel": ["bulgarian_split_squat_dumbbell", "reverse_lunge_dumbbell"], "bodyweight": ["reverse_lunge"]},
    "carry": {"hotel": ["farmers_walk_8d414b80"], "bodyweight": []},
}
POOL_NAMES = ("gym_minimum", "hotel", "bodyweight")
POOL_LABEL = {"gym_minimum": "minimum", "hotel": "hotel gym", "bodyweight": "bodyweight"}


# ── the charter reads ───────────────────────────────────────────────────────────────────────
def _charter(path: str, default: Any = None) -> Any:
    from training.training_charter import charter_value

    return charter_value(path, default)


def minimum_shape() -> dict[str, Any]:
    """The charter's `split.minimum_session` (the shape every minimum and variant is built to)."""
    return dict(_charter("split.minimum_session", {}) or {})


def policy() -> dict[str, Any]:
    """The charter's disruption block, as read — the templates, the step-back-up window and the offer triggers."""
    return dict(_charter("disruption", {}) or {})


def role_keys() -> list[str]:
    """The charter's session sequence as role keys (the five session types)."""
    return [re.sub(r"[^a-z]+", "_", str(s).lower()).strip("_") for s in (_charter("split.sequence", []) or [])]


def holds(template: str | None) -> list[dict[str, Any]]:
    """What the mode HOLDS instead of targets, each value read from its one home."""
    from training import owner_redlines

    sleep = next((t for t in owner_redlines.TRIPWIRES if t.get("id") == "sleep"), {})
    pol = policy()
    tmpl = (pol.get("templates") or {}).get(template or "") or {}
    return [
        {"habit": "steps", "floor": _charter("steps.floor"), "source": "charter steps.floor", "every_day": _charter("steps.every_day")},
        {"habit": "protein", "floor_g": owner_redlines.REDLINES["protein_floor_g"]["value"], "source": "owner_redlines protein_floor_g"},
        {"habit": "sleep", "floor_h": sleep.get("threshold_hours"), "source": "owner_redlines TRIPWIRES sleep"},
        {
            "habit": "session",
            "what": "one short session",
            "minutes": minimum_shape().get("minutes"),
            "sessions_per_wk": tmpl.get("sessions_per_wk"),
            "source": "charter split.minimum_session + disruption.templates",
        },
    ] + (
        [{"habit": "core", "held": list((pol.get("whole_day") or {}).get("held_habits") or []), "source": "charter disruption.whole_day"}]
        if tmpl.get("whole_day")
        else []
    )


# ── the record (pure; the write is mcp/tools_training_notes.py) ─────────────────────────────
def disruption_sk(start_date: str) -> str:
    return f"{DISRUPTION_SK_PREFIX}{str(start_date)[:10]}"


def _day(s: Any):
    return parse_day_key(str(s or "")[:10]) if s else None


def build_disruption_record(*, start_date: str, until: str, words: str, template: str, recorded_at: str) -> dict[str, Any]:
    """Validate his word and return the DDB item body (strings only — Decimal-safe). Raises ValueError.

    `words` is VERBATIM — the mode is his statement, not a paraphrase. `until` is the last day it covers."""
    words = str(words or "").strip()
    if not words:
        raise ValueError("words is required and must be VERBATIM — disruption mode switches on only on the owner's recorded word")
    templates = sorted((policy().get("templates") or {}).keys())
    if template not in templates:
        raise ValueError(f"template must be one of {templates}")
    s, u = _day(start_date), _day(until)
    if s is None or u is None:
        raise ValueError("start_date and until must be YYYY-MM-DD")
    max_days = template_max_days(template)
    if not 0 <= (u - s).days < max_days:
        raise ValueError(f"until must be on/after start_date and within {max_days} days of it")
    return {
        "sk": disruption_sk(start_date),
        "start_date": str(start_date)[:10],
        "until": str(until)[:10],
        "template": template,
        "words": words,
        "recorded_at": str(recorded_at),
        "recorded_via": "chat",
        "issue": ISSUE,
    }


def template_max_days(template: str | None) -> int:
    """The most days one record of `template` may cover: the template's own `max_days` (life, #5122), the lapse
    protocol's hours in whole days (lapse), else the block's `max_days` (travel, busy)."""
    pol = policy()
    tmpl = (pol.get("templates") or {}).get(template or "") or {}
    if tmpl.get("max_days"):
        return int(tmpl["max_days"])
    if tmpl.get("lapse"):
        return -(-int((pol.get("lapse_protocol") or {}).get("hours") or 0) // 24)
    return int(pol.get("max_days") or 0)


def end_record(record: dict[str, Any], *, ended_on: str, words: str, recorded_at: str) -> dict[str, Any]:
    """His word that the mode is OFF from `ended_on` (the first day back). Raises ValueError."""
    words = str(words or "").strip()
    if not words:
        raise ValueError("words is required and must be VERBATIM")
    e, s = _day(ended_on), _day(record.get("start_date"))
    if e is None or s is None or e < s:
        raise ValueError("ended_on must be YYYY-MM-DD, on/after the record's start_date")
    return {**record, "ended_on": str(ended_on)[:10], "end_words": words, "ended_recorded_at": str(recorded_at)}


def _last_day(r: dict[str, Any]):
    """The last day a record covers: `until`, or the day before `ended_on` when he switched it off early."""
    u, e = _day(r.get("until")), _day(r.get("ended_on"))
    if u is None:
        return None
    if e is not None:
        return min(u, e - timedelta(days=1))
    return u


def active_record(records: list[dict[str, Any]] | None, day: str) -> dict[str, Any] | None:
    """The record whose `[start_date, last day]` covers `day`, newest start first."""
    d = _day(day)
    if d is None:
        return None
    for r in sorted(records or [], key=lambda x: str(x.get("start_date")), reverse=True):
        s, last = _day(r.get("start_date")), _last_day(r)
        if s is not None and last is not None and s <= d <= last:
            return r
    return None


def _stepping_back_from(records: list[dict[str, Any]] | None, day: str) -> dict[str, Any] | None:
    d = _day(day)
    days = int((policy().get("step_back_up") or {}).get("days") or 0)
    templates = policy().get("templates") or {}
    for r in sorted(records or [], key=lambda x: str(x.get("start_date")), reverse=True):
        if (templates.get(r.get("template")) or {}).get("step_back_up") is False:
            continue  # #5122: the lapse protocol resumes the full plan the next morning
        last = _last_day(r)
        if d is not None and last is not None and 0 < (d - last).days <= days:
            return r
    return None


def state(records: list[dict[str, Any]] | None, day: str) -> dict[str, Any]:
    """off | active | step_back_up for `day`, with the record that decides it and the pools it serves."""
    pol = policy()
    rec = active_record(records, day)
    if rec is not None:
        tmpl = (pol.get("templates") or {}).get(rec.get("template")) or {}
        last = _last_day(rec)
        return {
            "phase": PHASE_ACTIVE,
            "template": rec.get("template"),
            "start_date": rec.get("start_date"),
            "until": last.isoformat() if last else rec.get("until"),
            "words": rec.get("words"),
            "pools": list(tmpl.get("pools") or []),
            "sessions_per_wk": tmpl.get("sessions_per_wk"),
        }
    back = _stepping_back_from(records, day)
    if back is not None:
        last = _last_day(back)
        sbu = pol.get("step_back_up") or {}
        return {
            "phase": PHASE_STEP_BACK_UP,
            "template": back.get("template"),
            "start_date": back.get("start_date"),
            "until": last.isoformat() if last else back.get("until"),
            "step_back_up_through": shift_day_key(last.isoformat(), int(sbu.get("days") or 0)) if last else None,
            "words": back.get("words"),
            "pools": ["gym_minimum", "bodyweight"],
            "sessions_per_wk": None,
            "then": sbu.get("then"),
        }
    return {"phase": PHASE_OFF, "template": None, "pools": [], "sessions_per_wk": None}


# ── the offer (never applied) ───────────────────────────────────────────────────────────────
def _session_days(block_workouts: list[dict[str, Any]] | None) -> list[str]:
    """The Pacific days carrying any logged set — a bodyweight session counts (it has reps, not load)."""
    out = set()
    for w in block_workouts or []:
        if any((ex or {}).get("sets") for ex in (w.get("exercises") or [])):
            out.add(str(w.get("date") or str(w.get("sk") or "").replace("DATE#", ""))[:10])
    return sorted(d for d in out if parse_day_key(d) is not None)


def offer(day: str, *, block_workouts: list[dict[str, Any]] | None, windows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Whether the coach should OFFER the mode on `day`. `applies` is always False: only his record applies it."""
    pol = policy()
    trig = pol.get("offer") or {}
    d = _day(day)
    reasons: list[str] = []
    template = None
    pending: list[str] = []
    for w in windows if windows is not None else (_charter("travel.windows", []) or []):
        s, e = _day(w.get("start")), _day(w.get("end"))
        if s is None or e is None:
            pending.append(f"{w.get('label')}: dates pending the owner")
            continue
        if d is not None and (s - d).days <= int(trig.get("travel_lead_days") or 0) and d <= e:
            reasons.append(f"travel window {w.get('label')} ({s.isoformat()}..{e.isoformat()})")
            template = "travel"
    days = _session_days(block_workouts)
    if block_workouts is not None and days and d is not None:
        gap = (d - parse_day_key(days[-1])).days
        if gap >= int(trig.get("missed_session_days") or 0):
            reasons.append(f"{gap} days since the last logged session ({days[-1]})")
            template = template or "busy"
    return {
        "offered": bool(reasons),
        "applies": False,
        "template": template,
        "reasons": reasons,
        "pending_windows": pending,
        "missed_session_read": block_workouts is not None,
        "how": (
            "his word switches it on: get_exercise_notes action='disruption' (words verbatim, template, until) — "
            "the coach offers, never imposes"
        ),
    }


def sessions_due(st: dict[str, Any], day: str, block_workouts: list[dict[str, Any]] | None) -> dict[str, Any]:
    """On an active mode: the sessions logged in the 7 days before `day` (`[day-7, day)`) against the template's weekly band."""
    band = st.get("sessions_per_wk") or []
    if st.get("phase") != PHASE_ACTIVE or not band or block_workouts is None:
        return {"due": True, "done_7d": None, "band": band or None}
    start = shift_day_key(day, -7)
    done = sum(1 for x in _session_days(block_workouts) if start <= x < day)
    return {"due": done < int(band[-1]), "done_7d": done, "band": band}


def constraint(
    day: str,
    records: list[dict[str, Any]] | None,
    block_workouts: list[dict[str, Any]] | None = None,
    windows: list[dict[str, Any]] | None = None,
    records_state: str | None = None,
) -> dict[str, Any]:
    """`constraint_block.disruption` — `{active, phase, template, until, offer, food, ...}`. `food` (#5104) is the travel
    food playbook (`health.travel_food.mode_view`) on an active travel template or an offered travel window, else None."""
    from health import travel_food  # noqa: PLC0415 — #5104: the hotel/restaurant playbook rides the travel template

    st = state(records, day)
    on = st["phase"] != PHASE_OFF
    off = None if on else offer(day, block_workouts=block_workouts, windows=windows)
    if st["phase"] == PHASE_ACTIVE:
        food = travel_food.mode_view(st.get("template"))
    else:
        food = travel_food.mode_view((off or {}).get("template"), offered=True) if off and off.get("offered") else None
    return {
        "active": st["phase"] == PHASE_ACTIVE,
        "phase": st["phase"],
        "template": st.get("template"),
        "until": st.get("until"),
        "step_back_up_through": st.get("step_back_up_through"),
        "words": st.get("words"),
        "pools": st.get("pools"),
        "sessions": sessions_due(st, day, block_workouts),
        "holds": holds(st.get("template")) if on else None,
        "offer": off,
        "food": food,
        "minimum_session": minimum_shape(),
        "records_read": records is not None,
        "records_state": records_state,
        "rule": f"the owner switches it on; the coach offers, never imposes ({DISRUPTION_STORE}) — {ISSUE}",
    }


# ── the sessions ────────────────────────────────────────────────────────────────────────────
def role_patterns(role: str) -> list[tuple[str, str]]:
    """The role's anchor exposures `(pattern, intensity)` — the program's template, else the fallback."""
    from training import program_structure

    tmpl = program_structure.SESSION_TEMPLATES.get(role)
    if tmpl:
        return [(str(p), str(i)) for p, i in tmpl["anchors"]]
    return list(FALLBACK_ROLE_ANCHORS.get(role) or [])


def role_archetype(role: str) -> str:
    from training import program_structure

    tmpl = program_structure.SESSION_TEMPLATES.get(role)
    return str(tmpl["archetype"]) if tmpl else FALLBACK_ROLE_ARCHETYPE.get(role, "upper")


def _pool_keys(pattern: str, intensity: str, pool: str) -> tuple[list[str], int | None]:
    """(catalog keys in order, the skill ceiling override) for one slot."""
    from training import program_conflicts, program_structure

    if pool == "gym_minimum":
        anchor = program_structure.ANCHORS.get(pattern)
        if anchor:
            keys = list(anchor["catalog_keys"])
            if intensity == "moderate":
                keys = list(anchor.get("moderate_catalog_keys") or []) + keys
            ruling = program_conflicts.ANCHOR_SKILL_CEILING_RULING
            return keys, (int(ruling["effective_ceiling"]) if pattern in ruling["exempt_families"] else None)
        return list((POOLS.get(pattern) or {}).get("gym") or []), None
    return list((POOLS.get(pattern) or {}).get(pool) or []), None


def resolve(keys: list[str], movements: dict[str, Any], skill_ceiling: int, taken: set[str]) -> tuple[str | None, str | None]:
    """The first key the catalog carries AND `generator_eligible` allows, not already in the session."""
    from training.movement_catalog import generator_eligible

    skipped = []
    for k in keys:
        m = movements.get(k)
        if m is None:
            skipped.append(f"{k} (not in catalog)")
        elif not generator_eligible(m, skill_ceiling, key=k):
            skipped.append(f"{k} (not generator_eligible at ceiling {skill_ceiling})")
        elif k in taken:
            skipped.append(f"{k} (already in this session)")
        else:
            return k, ("skipped: " + ", ".join(skipped)) if skipped else None
    return None, "no eligible member: " + (", ".join(skipped) or "the pool is empty")


def _slot_sets(intensity: str, movement: dict[str, Any], pool: str) -> list[dict[str, Any]]:
    """Top set + one back-off. The rep range is the exposure's at the club, the movement's own away from it."""
    from training import program_structure

    shape = minimum_shape()
    spec = program_structure.EXPOSURES.get(intensity) or program_structure.EXPOSURES["volume"]
    rr = movement.get("default_rep_range") or {}
    reps = list(spec["reps"]) if pool == "gym_minimum" or not rr else [int(rr["start"]), int(rr["end"])]
    from training import effort_ceilings  # #5058: the charter's ruled compounds band

    rpe = list(effort_ceilings.class_bands(_charter).get(effort_ceilings.COMPOUNDS) or [])
    sets: list[dict[str, Any]] = [
        {"kind": "top", "reps": reps, "rpe": rpe},
        {"kind": "back_off", "reps": reps, "pct_of_top": 100 + int(shape.get("back_off_pct") or 0)},
    ][: int(shape.get("sets_per_movement") or 2)]
    return sets


def session(role: str, pool: str, movements: dict[str, Any], skill_ceiling: int = 2) -> dict[str, Any]:
    """The minimum session (`gym_minimum`) or a variant (`hotel` / `bodyweight`) for one role, as data."""
    if pool not in POOL_NAMES:
        raise ValueError(f"pool must be one of {POOL_NAMES}")
    shape = minimum_shape()
    cap = int(shape.get("max_movements") or 0)
    slots = [(p, i, "anchor") for p, i in role_patterns(role)]
    if pool != "gym_minimum":
        slots += [(p, "volume", "extra") for p in VARIANT_EXTRAS.get(role_archetype(role), [])]
    taken: set[str] = set()
    exposures: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for pattern, intensity, kind in slots:
        if len(exposures) >= cap:
            break
        keys, ceiling = _pool_keys(pattern, intensity, pool)
        key, why = resolve(keys, movements, max(skill_ceiling, ceiling or 0), taken)
        if key is None:
            if kind == "anchor":
                unresolved.append(f"{pattern}: {why}")
            continue
        taken.add(key)
        exposures.append(
            {"kind": kind, "pattern": pattern, "intensity": intensity, "movement_key": key, "resolution_note": why}
            | {"sets": _slot_sets(intensity, movements[key], pool)}
        )
    n_sets = sum(len(e["sets"]) for e in exposures)
    return {
        "role": role,
        "pool": pool,
        "archetype": role_archetype(role),
        "exposures": exposures,
        "unresolved": unresolved,
        "total_sets": n_sets,
        "est_minutes": n_sets * float(shape.get("est_minutes_per_set") or 0),
        "minutes": shape.get("minutes"),
    }


def templates_preview(movements: dict[str, Any], skill_ceiling: int = 2) -> dict[str, dict[str, Any]]:
    """Every charter role x pool: the movements it resolves to and what did not resolve (the owner's 'are the
    travel templates ready' read, `get_exercise_notes action='disruptions'`)."""
    out: dict[str, dict[str, Any]] = {}
    for role in role_keys():
        out[role] = {}
        for pool in POOL_NAMES:
            rx = session(role, pool, movements, skill_ceiling)
            out[role][pool] = {"movements": [e["movement_key"] for e in rx["exposures"]], "unresolved": rx["unresolved"]}
    return out


def _cue(e: dict[str, Any]) -> str:
    """A short exercise note that carries its reason (Hevy renders exercise notes in full)."""
    top, back = e["sets"][0], (e["sets"][1] if len(e["sets"]) > 1 else None)
    rpe = "-".join(str(x) for x in top.get("rpe") or [])
    line = f"Minimum: top set {top['reps'][0]}-{top['reps'][1]}" + (f" @ RPE {rpe}" if rpe else "")
    if back:
        line += f", then one back-off at {back['pct_of_top'] - 100}%"
    return line + " — keeps the habit on a short day (#5088)."


def to_routine(rx: dict[str, Any], *, target_date: str, variant: str, mode: dict[str, Any], catalog: dict[str, Any]) -> Any:
    """One session as a `RoutineSpec` (no loads: a reduced session asserts no load floor, like the floor variant)."""
    from training.routine_generator import _new_routine_id, _now_iso
    from training.routine_ir import ExerciseBlock, RoutineSpec, Set

    movements = catalog.get("movements") or {}
    blocks = [
        ExerciseBlock(
            movement_key=e["movement_key"],
            sets=[Set(type="normal", rep_range_start=s["reps"][0], rep_range_end=s["reps"][1]) for s in e["sets"]],
            rest_seconds=90,
            notes=_cue(e),
            joint_friendly_score=int(movements.get(e["movement_key"], {}).get("joint_friendly_score", 3)),
            skill_tier=int(movements.get(e["movement_key"], {}).get("skill_tier", 1)),
            rationale_tag=f"{e['kind']}:{e['pattern']}:{rx['pool']}",
        )
        for e in rx["exposures"]
    ]
    label = POOL_LABEL[rx["pool"]]
    why = "stepping back up" if mode.get("phase") == PHASE_STEP_BACK_UP else f"{mode.get('template')} mode"
    rationale = [
        f"disruption ({why}, {ISSUE}): {rx['role']} as the {label} session — anchors only, top set + one back-off",
        f"{rx['total_sets']} sets, ~{rx['est_minutes']:.0f} of {rx['minutes']} min; habits held, not targets",
    ] + [f"UNRESOLVED — {u}" for u in rx["unresolved"]]
    return RoutineSpec(
        routine_id=_new_routine_id(target_date, rx["archetype"], variant),
        target_date=target_date,
        archetype=rx["archetype"],
        variant=variant,
        title=f"{rx['role'].replace('_', ' ').upper()} — {label.upper()} — {target_date}",
        notes=f"{label.capitalize()} session, {why}: habits held, not targets. Step back up on return.",
        version=1,
        created_at=_now_iso(),
        created_by="cron",
        source_action="disruption",
        status="draft",
        exercises=blocks,
        budget_used={b.movement_key: len(b.sets) for b in blocks},
        inputs_snapshot={
            "variant": variant,
            "session_role": rx["role"],
            "disruption": {k: mode.get(k) for k in ("phase", "template", "until", "step_back_up_through")} | {"pool": rx["pool"]},
            "session_prescription": rx,
            "charter_version": _charter_version(),
        },
        rationale=rationale,
        caps={"total_sets": max(1, rx["total_sets"]), "session_minutes": int(rx["minutes"] or 0)},
    )


def _charter_version() -> str | None:
    from training.training_charter import charter_version

    return charter_version()


def routines(target_date: str, role: str, mode: dict[str, Any], catalog: dict[str, Any], skill_ceiling: int = 2) -> list[Any]:
    """The generator's draft path under the mode: the first pool as the served session, the second as its floor."""
    pools = [p for p in (mode.get("pools") or []) if p in POOL_NAMES][:2] or ["gym_minimum"]
    movements = catalog.get("movements") or {}
    out = [
        to_routine(session(role, p, movements, skill_ceiling), target_date=target_date, variant=v, mode=mode, catalog=catalog)
        for p, v in zip(pools, (PRIMARY_VARIANT, "floor"))
    ]
    if len(out) == 2:
        out[0].sibling_routine_id, out[1].sibling_routine_id = out[1].routine_id, out[0].routine_id
    return out


# ── the generator path's own read (MCP reads through mcp/tools_training_notes.py) ───────────
def load_records(table: Any = None) -> list[dict[str, Any]]:
    """Every disruption record, newest first, from `table` (default: the generator's own). Raises on a failed read."""
    from training import exercise_history

    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {  # the string form: the same query, readable by every table double the coach tests use
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
        "ExpressionAttributeValues": {":pk": DISRUPTION_PK, ":prefix": DISRUPTION_SK_PREFIX},
        "ScanIndexForward": False,
    }
    while True:
        resp = (table if table is not None else exercise_history._table()).query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def load_records_failsoft(table: Any = None) -> list[dict[str, Any]]:
    """`load_records`, or [] when the read fails — SAFE: no record means the full plan, never a mode he did not ask for."""
    try:
        return load_records(table)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"disruption: the record read failed ({type(e).__name__}: {e}) — no disruption mode applied")
        return []
