"""panel_rubric.py — the panel rubric's deterministic half: a fixed standard per seat, scored from the plan's own fields (#5072).

WHY THIS EXISTS

The 2026-10-18 elite-panel review of the training plan had no baseline to compare against: eight
schools of thought graded the plan once, in prose, and nothing could say next week whether the
plan got better or worse. Epic #5067 asks for a FIXED rubric — one seat per school in the
training charter's `concession_ledger` — graded on golden cases (a regression gate) and weekly
on the real committed plan.

THE SPLIT (ADR-105: deterministic computation before any LLM verdict)

`config/panel_rubric.json` holds the rubric as data: per seat, 4-6 criteria, each graded either
by CODE (a named check in `CHECKS` below, computed from the plan's own structured fields — the
routine IR, its `inputs_snapshot`, and the plan engine's constraint block) or by the JUDGE
(`panel_judge`, a model call) when no code can check it. This module is everything that does not
need a model: loading the rubric, extracting the plan's features, the checks, combining code and
judge scores into seat scores and an overall letter, the target verdict, the blinded rendering a
judge reads, and the negative-control mutations the weekly grade runs beside the real plan.

THE PLAN CASE (the one input shape — a golden fixture and the weekly real plan are both this):

    {"case_id": str, "week_start": "YYYY-MM-DD",
     "routines": [routine_ir.serialize()-shaped dicts — exercises, sets, notes, variant, inputs_snapshot],
     "constraint_block": plan_engine.constraint_block(...)'s dict, or the subset of it the checks read}

A check reads only fields that are ON the plan. A plan that does not carry its evidence (no
progression verdict, no dose on a cardio block, no fatigue signals) scores 0 on that criterion —
absence is not credit. Every check returns `(score 0-10, evidence)`; the evidence names what it
counted, so a grade can be audited without re-running it.

WHAT NO CHECK HERE KNOWS: which engine or version produced the plan. The checks read the plan;
the blinded rendering (`blind_text`) strips every engine, version, author and id field before a
judge sees it (the anti-Goodhart comment on #5072).
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
from typing import Any, Callable

from common import repo_config

from training import block_model, routine_ir, session_shape
from training.rep_scheme import LB_IN_KG
from training.training_charter import charter_value

logger = logging.getLogger(__name__)

RUBRIC_BASENAME = "panel_rubric.json"
BY_CODE = "code"
BY_JUDGE = "judge"

# ── title classifiers (the catalog's primary_muscle mislabels a few: shrugs read `back`, a Pallof press `shoulders`) ──
_SIDE_REAR_DELT = re.compile(r"lateral raise|rear delt|reverse fly|face pull", re.I)
_DELT = re.compile(r"lateral raise|rear delt|reverse fly|face pull|shoulder press|overhead press|upright row|arnold", re.I)
_TRAPS = re.compile(r"shrug", re.I)
_CORE = re.compile(r"crunch|pallof|dead bug|plank|leg raise|ab wheel|bird dog|carry", re.I)
_CARRY = re.compile(r"carry|farmer|suitcase", re.I)
_FARMERS = re.compile(r"farmer", re.I)
_KETTLEBELL = re.compile(r"kettlebell", re.I)
_UNILATERAL_LOWER = re.compile(r"split squat|lunge|single leg|step.?up|bulgarian|pistol", re.I)
_CORRECTIVE = re.compile(r"face pull|pallof|rear delt|reverse fly|external rotation|band pull|dead bug|bird dog|scap", re.I)
_HINGE = re.compile(r"deadlift|\brdl\b|hip thrust|good morning|swing", re.I)
_SQUAT = re.compile(r"squat|leg press|lunge", re.I)
_RPE = re.compile(r"\b(?:RPE|RIR)\s*(?:<=|≤|<|~)?\s*(\d+(?:\.\d)?)", re.I)
_TALK_TEST = re.compile(r"talk test|full sentences|short phrases|a few words", re.I)
_CARDIO_LEVEL = re.compile(r"\blevel\b|\bspeed\b|\bmph\b|incline|\bwatts?\b|resistance|\bpace\b|\bspm\b", re.I)
_HARD_SHAPE = re.compile(r"tempo|hills?|intervals?|hard flat", re.I)
_DELOAD_VARIANTS = ("deload",)

# Charter `volume_priorities.mev_floors_in_every_template` group -> the classifier that finds it in a session.
_MEV_FLOOR_MATCH: dict[str, Callable[[dict[str, Any]], bool]] = {
    "side_rear_delts": lambda b: bool(_SIDE_REAR_DELT.search(b["title"])),
    # #5318 (owner ruling B3, 2026-10-24): the farmer's carry replaced the shrug and covers traps (the shrug's job)
    "traps": lambda b: b["muscle"] == "traps" or bool(_FARMERS.search(b["title"])),
    "calves": lambda b: b["muscle"] == "calves",
    "core": lambda b: b["muscle"] == "abs",
}
_LEG_MUSCLES = block_model.GROUP_MUSCLES["legs"]
_OUTCOME_TRIPWIRES = ("anchor_lift_strength_drop", "rate_ceiling", "walking_collapse")
_RECOVERY_TRIPWIRES = ("readiness_floor", "protein_floor_missed", "anchor_lift_strength_drop", "weight_stall_with_adherence")
_UNEVALUATED_STATES = ("unknown", "read_failed", None)


# ── the rubric ────────────────────────────────────────────────────────────────────────────
def load_rubric(path: str | None = None) -> dict[str, Any] | None:
    """`config/panel_rubric.json` (bundled with every Lambda), or None when unreadable — a grade then says so."""
    p = path or repo_config.config_path(RUBRIC_BASENAME)
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        logger.warning("panel_rubric: %s unreadable (%s)", os.path.basename(p), type(e).__name__)
        return None
    return data if isinstance(data, dict) and isinstance(data.get("seats"), dict) else None


def judge_criteria(rubric: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Seat -> the criteria only a judge can grade (code cannot check them)."""
    return {s: [c for c in seat["criteria"] if c.get("by") == BY_JUDGE] for s, seat in rubric["seats"].items()}


def concession(seat: str) -> dict[str, Any] | None:
    """The seat's concession, READ from the charter's concession ledger at grade time (never copied into the rubric)."""
    entry = (charter_value("concession_ledger", {}) or {}).get(seat)
    return dict(entry) if isinstance(entry, dict) else None


def target() -> dict[str, Any]:
    """The charter's `panel_target` (overall letter, every-seat floor) — read, never restated."""
    return dict(charter_value("panel_target", {}) or {})


# ── the plan's features ───────────────────────────────────────────────────────────────────
def _load_catalog() -> dict[str, Any]:
    from training.routine_generator import _load_json  # noqa: PLC0415 — the generator's own catalog read (local, else S3)

    return dict(_load_json("movement_catalog.json").get("movements") or {})


def _muscle(entry: dict[str, Any], title: str) -> str:
    if _TRAPS.search(title):
        return "traps"
    if _CORE.search(title):
        return "abs"
    return str(entry.get("primary_muscle") or "other")


def _block_row(block: Any, catalog: dict[str, Any], routine_index: int, progression: dict[str, Any] | None) -> dict[str, Any]:
    entry = catalog.get(block.movement_key) or {}
    title = str(entry.get("title") or block.movement_key.replace("_", " "))
    sets = list(block.sets or [])
    working = [s for s in sets if str(s.type or "normal") != "warmup"]
    return {
        "routine": routine_index,
        "key": block.movement_key,
        "title": title,
        "muscle": _muscle(entry, title),
        "equipment": str(entry.get("equipment") or ""),
        "anchor_family": entry.get("anchor_family"),
        "working_sets": len(working),
        "ranged_sets": sum(1 for s in working if s.rep_range_start and s.rep_range_end and s.rep_range_end - s.rep_range_start >= 2),
        "notes": str(block.notes or ""),
        "progression": progression,
    }


def _cardio_row(block: Any, routine_index: int, minutes: float) -> dict[str, Any]:
    notes = str(block.notes or "")
    rpes = [float(m) for m in _RPE.findall(notes)]
    return {
        "routine": routine_index,
        "key": block.movement_key,
        "minutes": minutes,
        "notes": notes,
        "rpe_max": max(rpes) if rpes else None,
        "dosed": minutes > 0 and bool(_CARDIO_LEVEL.search(notes)) and (bool(rpes) or bool(_TALK_TEST.search(notes))),
        "by_rpe": bool(rpes) or bool(_TALK_TEST.search(notes)),
        "hard": (max(rpes) >= 6 if rpes else False) or bool(_HARD_SHAPE.search(notes)),
    }


def _is_unrecorded_deload(ir: Any, block: dict[str, Any]) -> bool:
    snap = (getattr(ir, "inputs_snapshot", None) or {}).get("deload") or {}
    deloaded = str(getattr(ir, "variant", "") or "").lower() in _DELOAD_VARIANTS or bool(snap.get("applied"))
    owner_word = bool(snap.get("owner_record")) or bool((block.get("deload_recommendation") or {}).get("applied"))
    return deloaded and not owner_word


def plan_features(case: dict[str, Any], catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """Everything the checks read, computed once from the plan case. Pure apart from the catalog read."""
    catalog = catalog if catalog is not None else _load_catalog()
    block = dict(case.get("constraint_block") or {})
    routines = [routine_ir.deserialize(copy.deepcopy(r)) for r in case.get("routines") or []]
    lifts: list[dict[str, Any]] = []
    cardio: list[dict[str, Any]] = []
    minutes: list[float] = []
    unrecorded_deloads = 0
    for i, ir in enumerate(routines):
        shape = session_shape.routine_minutes(ir.exercises, catalog)
        floors = ((ir.inputs_snapshot or {}).get("load_floors") or {}).get("movements") or {}
        cardio_minutes = {c["movement_key"]: c["minutes"] for c in shape["cardio_blocks"]}
        for b in ir.exercises:
            kind = session_shape._block_kind(b, catalog)
            if kind == "lifting":
                lifts.append(_block_row(b, catalog, i, (floors.get(b.movement_key) or {}).get("progression")))
            elif kind == "cardio":
                cardio.append(_cardio_row(b, i, float(cardio_minutes.get(b.movement_key) or 0)))
        if shape["lifting_minutes"] > 0:
            minutes.append(shape["lifting_minutes"])
        unrecorded_deloads += int(_is_unrecorded_deload(ir, block))
    sets_by_muscle: dict[str, int] = {}
    for row in lifts:
        sets_by_muscle[row["muscle"]] = sets_by_muscle.get(row["muscle"], 0) + row["working_sets"]
    lifting_routines = sorted({r["routine"] for r in lifts})
    return {
        "routines": len(routines),
        "lifting_routines": lifting_routines,
        "session_minutes": minutes,
        "lifts": lifts,
        "cardio": cardio,
        "sets_by_muscle": sets_by_muscle,
        "unrecorded_deloads": unrecorded_deloads,
        "block": block,
    }


# ── the checks: (features) -> (score 0-10, evidence) ──────────────────────────────────────
def _share(n: int, d: int) -> float:
    return round(10.0 * n / d, 1) if d else 0.0


def _tiered(n: int, full: int) -> float:
    """10 at `full` or more, 5 at one, 0 at none."""
    return 10.0 if n >= full else (5.0 if n >= 1 else 0.0)


def _landmarks() -> dict[str, Any]:
    return block_model.load_landmarks() or {}


def check_double_progression(f: dict[str, Any]) -> tuple[float, str]:
    from training import load_progression  # noqa: PLC0415

    ok = [
        r for r in f["lifts"] if (r["progression"] or {}).get("basis") in load_progression.BASES and (r["progression"] or {}).get("reason")
    ]
    return _share(len(ok), len(f["lifts"])), f"{len(ok)} of {len(f['lifts'])} lifting movements carry a progression verdict with its reason"


def check_rep_ranges(f: dict[str, Any]) -> tuple[float, str]:
    rows = [r for r in f["lifts"] if not _CARRY.search(r["title"])]  # a carry is dosed by distance/time, not a rep range
    working = sum(r["working_sets"] for r in rows)
    ranged = sum(r["ranged_sets"] for r in rows)
    return _share(ranged, working), f"{ranged} of {working} working sets carry a rep range at least 2 reps wide"


def check_accessory_rotation(f: dict[str, Any]) -> tuple[float, str]:
    ok = f["block"].get("accessory_rotation_ok")
    return (10.0 if ok is True else 0.0), f"constraint block accessory_rotation_ok = {ok!r}"


def check_priority_sets(f: dict[str, Any]) -> tuple[float, str]:
    lm = _landmarks()
    plan = block_model.muscle_plan(lm) if lm else {}
    priority = [m for m, row in plan.items() if row["priority"]]
    inside = [m for m in priority if lm[m]["MEV"] <= f["sets_by_muscle"].get(m, 0) <= lm[m]["MAV"]]
    detail = ", ".join(f"{m} {f['sets_by_muscle'].get(m, 0)} [{lm[m]['MEV']}-{lm[m]['MAV']}]" for m in priority)
    return _share(len(inside), len(priority)), f"{len(inside)} of {len(priority)} priority muscles inside MEV-MAV: {detail}"


def check_single_leg(f: dict[str, Any]) -> tuple[float, str]:
    n = sum(1 for r in f["lifts"] if _UNILATERAL_LOWER.search(r["title"]))
    return _tiered(n, 2), f"{n} single-leg lower-body movements this week"


def check_carries(f: dict[str, Any]) -> tuple[float, str]:
    n = sum(1 for r in f["lifts"] if _CARRY.search(r["title"]))
    return _tiered(n, 1), f"{n} loaded carries this week"


def check_corrective(f: dict[str, Any]) -> tuple[float, str]:
    n = sum(1 for r in f["lifts"] if _CORRECTIVE.search(r["title"]))
    return _tiered(n, 2), f"{n} corrective movements this week"


def check_pull_push(f: dict[str, Any]) -> tuple[float, str]:
    pull, push = f["sets_by_muscle"].get("back", 0), f["sets_by_muscle"].get("chest", 0)
    score = 10.0 if push == 0 and pull > 0 else (min(10.0, round(10.0 * pull / push, 1)) if push else 0.0)
    return score, f"back {pull} sets vs chest {push} sets"


def check_mev_floors(f: dict[str, Any]) -> tuple[float, str]:
    floors = [g for g in (charter_value("volume_priorities.mev_floors_in_every_template", []) or []) if g in _MEV_FLOOR_MATCH]
    hits, total, missing = 0, 0, []
    for i in f["lifting_routines"]:
        rows = [r for r in f["lifts"] if r["routine"] == i]
        for g in floors:
            total += 1
            if any(_MEV_FLOOR_MATCH[g](r) for r in rows):
                hits += 1
            else:
                missing.append(f"session {i + 1}: {g}")
    return _share(hits, total), f"{hits} of {total} (session x floor) present" + (f"; missing {missing[:6]}" if missing else "")


def check_legs_floor(f: dict[str, Any]) -> tuple[float, str]:
    lm = _landmarks()
    legs = [m for m in _LEG_MUSCLES if m in lm]
    ok = [m for m in legs if f["sets_by_muscle"].get(m, 0) >= lm[m]["MEV"]]
    detail = ", ".join(f"{m} {f['sets_by_muscle'].get(m, 0)}/MEV {lm[m]['MEV']}" for m in legs)
    return _share(len(ok), len(legs)), f"{len(ok)} of {len(legs)} leg muscles at or above MEV: {detail}"


def check_no_unrecorded_deload(f: dict[str, Any]) -> tuple[float, str]:
    scheduled = charter_value("deload.scheduled") is not False or charter_value("deload.automatic") is not False
    n = f["unrecorded_deloads"]
    score = 0.0 if (n or scheduled) else 10.0
    return score, f"{n} session(s) deloaded without the owner's recorded word; charter deload scheduled/automatic = {scheduled}"


def check_progression_coded(f: dict[str, Any]) -> tuple[float, str]:
    prog = f["block"].get("progression") or {}
    gain = (prog.get("gain_rule") or {}).get("kind") == charter_value("progression.gain_rule.kind")
    stall = bool(prog.get("stall_rule"))
    return (5.0 * gain + 5.0 * stall), f"gain rule coded = {gain}, stall rule coded = {stall}"


def check_anchors(f: dict[str, Any]) -> tuple[float, str]:
    with_anchor = {r["routine"] for r in f["lifts"] if r["anchor_family"]}
    n = len(f["lifting_routines"])
    return _share(len(with_anchor), n), f"{len(with_anchor)} of {n} lifting sessions carry an anchor lift"


def _tripwire_states(f: dict[str, Any]) -> dict[str, Any]:
    return {str(t.get("id")): t.get("state") for t in f["block"].get("tripwires") or [] if isinstance(t, dict)}


def check_strength_tripwire(f: dict[str, Any]) -> tuple[float, str]:
    states = _tripwire_states(f)
    st = states.get("anchor_lift_strength_drop", "absent")
    score = 0.0 if st == "absent" else (5.0 if st in _UNEVALUATED_STATES else 10.0)
    return score, f"anchor_lift_strength_drop: {st}"


def check_effort_by_rpe(f: dict[str, Any]) -> tuple[float, str]:
    n = sum(1 for r in f["lifts"] if _RPE.search(r["notes"]))
    return _share(n, len(f["lifts"])), f"{n} of {len(f['lifts'])} lifting movements prescribe effort by RPE/RIR"


def check_hard_easy(f: dict[str, Any]) -> tuple[float, str]:
    hard = sum(1 for c in f["cardio"] if c["hard"])
    easy = sum(1 for c in f["cardio"] if not c["hard"] and c["by_rpe"])
    want = charter_value("cardio_menu.conditioning_sessions_per_wk")
    if hard and easy:
        score = 10.0 if hard == want else 7.0
    else:
        score = 3.0 if (hard or easy) else 0.0
    return score, f"{hard} hard + {easy} easy cardio blocks (charter conditioning per week: {want})"


def check_cardio_dosed(f: dict[str, Any]) -> tuple[float, str]:
    n = sum(1 for c in f["cardio"] if c["dosed"])
    return _share(n, len(f["cardio"])), f"{n} of {len(f['cardio'])} cardio blocks carry minutes + level/speed/incline + RPE or talk test"


def check_conditioning_by_rpe(f: dict[str, Any]) -> tuple[float, str]:
    n = sum(1 for c in f["cardio"] if c["by_rpe"])
    return _share(n, len(f["cardio"])), f"{n} of {len(f['cardio'])} cardio blocks prescribed by RPE or talk test"


def check_fatigue_flags(f: dict[str, Any]) -> tuple[float, str]:
    rec = f["block"].get("deload_recommendation")
    if not isinstance(rec, dict):
        return 0.0, "no deload_recommendation on the plan"
    wired = list(rec.get("triggers_wired") or [])
    return (10.0 if wired else 5.0), f"deload_recommendation present; triggers wired: {wired}"


def check_steps_floor(f: dict[str, Any]) -> tuple[float, str]:
    ramp = f["block"].get("steps_ramp") or {}
    floor = charter_value("steps.floor")
    if ramp.get("floor") != floor:
        return 0.0, f"steps_ramp floor {ramp.get('floor')!r} is not the charter floor {floor}"
    return (5.0 if ramp.get("state") in _UNEVALUATED_STATES else 10.0), f"steps_ramp floor {floor}, state {ramp.get('state')!r}"


def check_carries_or_kb(f: dict[str, Any]) -> tuple[float, str]:
    n = sum(1 for r in f["lifts"] if _CARRY.search(r["title"]) or _KETTLEBELL.search(r["title"]) or r["equipment"] == "kettlebell")
    return _tiered(n, 1), f"{n} carry/kettlebell movements this week"


def check_patterns(f: dict[str, Any]) -> tuple[float, str]:
    rows = f["lifts"]
    seen = {
        "hinge": any(r["anchor_family"] == "hinge" or _HINGE.search(r["title"]) for r in rows),
        "squat": any(r["anchor_family"] == "squat" or _SQUAT.search(r["title"]) for r in rows),
        "push": any(r["anchor_family"] in ("bench", "overhead_press") or r["muscle"] == "chest" for r in rows),
        "pull": any(r["anchor_family"] in ("row", "vertical_pull") or r["muscle"] == "back" for r in rows),
        "carry": any(_CARRY.search(r["title"]) for r in rows),
    }
    return _share(sum(seen.values()), len(seen)), f"patterns covered: {sorted(k for k, v in seen.items() if v)}"


def check_within_cap(f: dict[str, Any]) -> tuple[float, str]:
    """All or nothing: one session past the cap is the defect (a 2.5 h day is not 'four-fifths sustainable')."""
    cap = session_shape.lifting_minutes_cap()
    over = [m for m in f["session_minutes"] if m > cap]
    score = 10.0 if f["session_minutes"] and not over else 0.0
    return score, f"{len(over)} of {len(f['session_minutes'])} sessions over the {cap}-min lifting cap: {over}"


def check_days(f: dict[str, Any]) -> tuple[float, str]:
    want, n = charter_value("split.lifting_days_per_wk"), len(f["lifting_routines"])
    gap = abs(n - int(want or 0))
    return (10.0 if gap == 0 else (6.0 if gap == 1 else 0.0)), f"{n} lifting sessions, charter {want}"


def check_minutes_under_ceiling(f: dict[str, Any]) -> tuple[float, str]:
    """Owner ruling A4 (2026-10-24, #5318): the lifting minutes are a CEILING, not a target — a shorter session is never
    marked down, only one past the charter's `split.session_minutes.lifting_ceiling` is."""
    cap = session_shape.lifting_minutes_cap()
    ok = [m for m in f["session_minutes"] if m <= cap]
    return (
        _share(len(ok), len(f["session_minutes"])),
        f"{len(ok)} of {len(f['session_minutes'])} sessions at or under the {cap}-min lifting ceiling (no floor): {f['session_minutes']}",
    )


def check_delts(f: dict[str, Any]) -> tuple[float, str]:
    want = int(charter_value("split.frequency.delts_per_wk") or 0)
    days = len({r["routine"] for r in f["lifts"] if _DELT.search(r["title"])})
    return (10.0 if want and days >= want else _share(days, want)), f"delts trained on {days} days, charter {want}"


def check_recovery_tripwires(f: dict[str, Any]) -> tuple[float, str]:
    states = _tripwire_states(f)
    ok = [t for t in _RECOVERY_TRIPWIRES if t in states and states[t] not in _UNEVALUATED_STATES]
    return _share(len(ok), len(_RECOVERY_TRIPWIRES)), f"evaluated: {ok} of {list(_RECOVERY_TRIPWIRES)}"


# The registry the rubric's `check` names resolve against (a name with no entry here is a test failure).
CHECKS: dict[str, Callable[[dict[str, Any]], tuple[float, str]]] = {
    "double_progression_with_reason": check_double_progression,
    "rep_ranges_stated": check_rep_ranges,
    "accessory_rotation_ok": check_accessory_rotation,
    "priority_sets_in_landmarks": check_priority_sets,
    "single_leg_work": check_single_leg,
    "carries_weekly": check_carries,
    "corrective_work": check_corrective,
    "pull_push_balance": check_pull_push,
    "mev_floors_every_template": check_mev_floors,
    "legs_at_maintenance_floor": check_legs_floor,
    "no_unrecorded_deload": check_no_unrecorded_deload,
    "progression_rule_coded": check_progression_coded,
    "anchors_every_lifting_day": check_anchors,
    "strength_tripwire_live": check_strength_tripwire,
    "effort_by_rpe": check_effort_by_rpe,
    "hard_easy_cardio_split": check_hard_easy,
    "cardio_dosed": check_cardio_dosed,
    "conditioning_by_rpe": check_conditioning_by_rpe,
    "fatigue_flags_present": check_fatigue_flags,
    "steps_floor_carried": check_steps_floor,
    "carries_or_kettlebell_weekly": check_carries_or_kb,
    "fundamental_patterns": check_patterns,
    "sessions_within_cap": check_within_cap,
    "lifting_days_match": check_days,
    "session_minutes_under_ceiling": check_minutes_under_ceiling,
    "delts_frequency": check_delts,
    "recovery_tripwires_wired": check_recovery_tripwires,
}


def prescore(case: dict[str, Any], rubric: dict[str, Any], catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every CODE criterion of every seat, scored from the plan. Seat -> criterion id -> {score, evidence}."""
    feats = plan_features(case, catalog)
    out: dict[str, dict[str, Any]] = {}
    for seat, spec in rubric["seats"].items():
        out[seat] = {}
        for c in spec["criteria"]:
            if c.get("by") == BY_CODE:
                score, evidence = CHECKS[c["check"]](feats)
                out[seat][c["id"]] = {"score": round(float(score), 1), "evidence": evidence, "by": BY_CODE}
    return out


# ── combining, the letter, the verdict ────────────────────────────────────────────────────
def letter_for(score: float, rubric: dict[str, Any]) -> str:
    for row in rubric["letters"]:
        if score >= float(row["min"]):
            return str(row["letter"])
    return str(rubric["letters"][-1]["letter"])


def _letter_rank(letter: str, rubric: dict[str, Any]) -> int:
    order = [row["letter"] for row in rubric["letters"]]
    return len(order) - order.index(letter) if letter in order else 0


def combine(
    code: dict[str, Any],
    judged: dict[str, Any] | None,
    rubric: dict[str, Any],
    concession_of: Callable[[str], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Seat scores (the mean of each seat's criteria), the overall score + letter, and the target verdict.

    `judged` is `panel_judge.parse_response`'s seat -> {scores, why, concession_held}, or None when the judge did
    not run — then each seat is the mean of its CODE criteria only and the grade is `degraded`. `concession_of`
    reads a seat's concession (default: the training ledger; the food panel passes its own, #5110). A seat with no
    concession NAMED fails the target ("every seat ... with its concession named")."""
    concession_of = concession_of or concession
    tgt = target()
    floor = float(tgt.get("every_seat_at_least") or 0)
    seats: dict[str, Any] = {}
    unscored: list[str] = []
    for seat, spec in rubric["seats"].items():
        crit: dict[str, Any] = dict(code.get(seat) or {})
        j = (judged or {}).get(seat) or {}
        for c in spec["criteria"]:
            if c.get("by") != BY_JUDGE:
                continue
            if c["id"] in (j.get("scores") or {}):
                crit[c["id"]] = {"score": float(j["scores"][c["id"]]), "evidence": str(j.get("why") or "")[:400], "by": BY_JUDGE}
            else:
                unscored.append(f"{seat}.{c['id']}")
        scores = [v["score"] for v in crit.values()]
        mean = round(sum(scores) / len(scores), 2) if scores else 0.0
        seats[seat] = {"score": mean, "criteria": crit, "concession": concession_of(seat), "concession_held": j.get("concession_held")}
    overall = round(sum(s["score"] for s in seats.values()) / len(seats), 2) if seats else 0.0
    letter = letter_for(overall, rubric)
    below = sorted(s for s, v in seats.items() if v["score"] < floor)
    broken = sorted(s for s, v in seats.items() if v["concession_held"] is False)
    unnamed = sorted(s for s, v in seats.items() if not v["concession"])
    met = _letter_rank(letter, rubric) >= _letter_rank(str(tgt.get("overall") or "A"), rubric) and not (below or broken or unnamed)
    return {
        "seats": seats,
        "overall": {"score": overall, "letter": letter},
        "target": tgt,
        "target_met": bool(met),
        "seats_below_floor": below,
        "concessions_not_held": broken,
        "concessions_unnamed": unnamed,
        "unscored": unscored,
        "degraded": bool(unscored),
    }


def outcome_disagreement(case: dict[str, Any], graded: dict[str, Any]) -> list[str]:
    """#5072's anti-Goodhart rule: outcome metrics outrank the rubric. A tripped outcome tripwire on a plan the
    rubric passes is named — the grade then reads `rubric_outranked`, never a clean A."""
    if not graded.get("target_met"):
        return []
    states = {t.get("id"): t.get("state") for t in (case.get("constraint_block") or {}).get("tripwires") or [] if isinstance(t, dict)}
    return [f"{t} is tripped" for t in _OUTCOME_TRIPWIRES if states.get(t) == "tripped"]


# ── what a judge may see: the plan, blinded ───────────────────────────────────────────────
_BLIND_SCRUB = re.compile(r"#\d{2,5}\b|plan-engine@\S+|\bv\d+(?:\.\d+)+\b|engine|generator|pre-?draft|nightly|critic\w*", re.I)


def _scrub(text: str) -> str:
    return re.sub(r"\s{2,}", " ", _BLIND_SCRUB.sub("", str(text or ""))).strip()


def _set_line(sets: list[Any], entry: dict[str, Any] | None = None) -> str:
    """'3 x 8-12 @ 50 lb per hand' — the sets as a judge reads them. #5373: a distance-dosed set renders its dose, never '? reps' —
    steps on a carry (`distance_unit_convention: steps`: his step count), metres otherwise; a timed set its seconds; a load is
    labelled by the entry's `load_convention` (per hand / total carried)."""
    from training import logging_conventions as lc  # noqa: PLC0415

    work = [s for s in sets if str(s.type or "normal") != "warmup"]
    warm = len(sets) - len(work)
    if not work:
        secs = sum(int(s.duration_seconds or 0) for s in sets)
        return f"{round(secs / 60)} min"
    s0 = work[0]
    if s0.rep_range_start and s0.rep_range_end:
        dose = f"{s0.rep_range_start}-{s0.rep_range_end}"
    elif s0.reps:
        dose = str(s0.reps)
    elif s0.distance_meters:
        unit = (
            "steps" if lc.distance_unit_of(entry or {"hevy_type": "short_distance_weight" if s0.weight_kg else None}) == lc.STEPS else "m"
        )
        dose = f"{int(s0.distance_meters)} {unit}"
    elif s0.duration_seconds:
        dose = f"{int(s0.duration_seconds)} s"
    else:
        dose = "?"
    label = lc.load_label(lc.current_load_convention_of(entry)) if entry else ""  # a plan is written in the current convention
    load = f" @ {round(float(s0.weight_kg) / LB_IN_KG)} lb{label}" if s0.weight_kg else ""
    return f"{len(work)} x {dose}{load}" + (f" (+{warm} warm-up)" if warm else "")


def blind_text(case: dict[str, Any], catalog: dict[str, Any] | None = None) -> str:
    """The plan as a judge reads it: sessions, movements, sets x reps @ load, rest, the notes and each
    progression verdict — and NOTHING that names the engine, its version, the plan's author, a routine id,
    a date-stamped build or an issue number. Every free-text field passes `_scrub`."""
    catalog = catalog if catalog is not None else _load_catalog()
    lines = []
    for i, raw in enumerate(case.get("routines") or []):
        ir = routine_ir.deserialize(copy.deepcopy(raw))
        floors = ((ir.inputs_snapshot or {}).get("load_floors") or {}).get("movements") or {}
        role = ((ir.inputs_snapshot or {}).get("calendar") or {}).get("session_role") or ir.archetype
        lines.append(f"SESSION {i + 1} — {_scrub(role)}" + (f" [{ir.variant}]" if ir.variant not in ("ideal", "") else ""))
        if ir.notes:
            lines.append(f"  note: {_scrub(ir.notes)[:300]}")
        for b in ir.exercises:
            title = str((catalog.get(b.movement_key) or {}).get("title") or b.movement_key.replace("_", " "))
            rest = f", rest {b.rest_seconds}s" if b.rest_seconds else ""
            lines.append(f"  - {title}: {_set_line(list(b.sets or []), catalog.get(b.movement_key))}{rest}")
            if b.notes:
                lines.append(f"      cue: {_scrub(b.notes)[:300]}")
            prog = (floors.get(b.movement_key) or {}).get("progression") or {}
            if prog.get("reason"):
                lines.append(f"      progression: {prog.get('basis')} — {_scrub(prog['reason'])[:200]}")
    block = case.get("constraint_block") or {}
    rec = block.get("deload_recommendation") or {}
    lines.append("WEEK CONTEXT")
    lines.append(f"  deload: applied={rec.get('applied')!r}; signals={list(rec.get('reasons') or [])[:4]}")
    lines.append(f"  steps floor carried: {(block.get('steps_ramp') or {}).get('floor')!r}")
    lines.append(f"  accessory rotation ok: {block.get('accessory_rotation_ok')!r}")
    return "\n".join(lines)


# ── the negative controls the weekly grade runs beside the real plan ──────────────────────
def _freeze_progression(case: dict[str, Any]) -> None:
    case["constraint_block"]["accessory_rotation_ok"] = False
    for r in case["routines"]:
        floors = (r.get("inputs_snapshot") or {}).get("load_floors") or {}
        for row in (floors.get("movements") or {}).values():
            row.pop("progression", None)


def _schedule_deload(case: dict[str, Any]) -> None:
    if case["routines"]:
        r = case["routines"][0]
        r["variant"] = "deload"
        r.setdefault("inputs_snapshot", {})["deload"] = {"applied": True, "source": "schedule"}
    case["constraint_block"].setdefault("deload_recommendation", {})["applied"] = False


def _stretch_session(case: dict[str, Any]) -> None:
    if case["routines"]:
        r = case["routines"][0]
        lifts = [e for e in r.get("exercises") or [] if any(s.get("reps") or s.get("rep_range_start") for s in e.get("sets") or [])]
        for e in lifts:
            e["sets"] = list(e["sets"]) * 2
        r["exercises"] = list(r.get("exercises") or []) + copy.deepcopy(lifts)


def _strip_cardio_dose(case: dict[str, Any]) -> None:
    for r in case["routines"]:
        for e in r.get("exercises") or []:
            sets = e.get("sets") or []
            if sets and all(s.get("duration_seconds") and not s.get("reps") and not s.get("weight_kg") for s in sets):
                e["notes"] = ""


# name -> (the mutation, the rubric criteria it MUST fail). The golden fixtures carry hand-built controls
# of the same four defects; tests hold that both paths fail the same criteria.
CONTROL_MUTATIONS: dict[str, tuple[Callable[[dict[str, Any]], None], tuple[str, ...]]] = {
    "frozen_no_progression": (_freeze_progression, ("nippard.double_progression", "nippard.accessory_rotation")),
    "scheduled_deload": (_schedule_deload, ("rp_israetel.no_unrecorded_deload", "clinical_exercise_physiologist.no_auto_deload")),
    "two_and_a_half_hour_session": (_stretch_session, ("hollywood_transformation_trainer.session_length", "dan_john.sustainable_length")),
    "cardio_no_dose": (_strip_cardio_dose, ("galpin.cardio_dosed", "clinical_exercise_physiologist.conditioning_by_rpe")),
}


def negative_controls(case: dict[str, Any]) -> list[dict[str, Any]]:
    """The real plan made bad four ways (copies — the plan itself is untouched). Each must FAIL the target."""
    out = []
    for name, (mutate, must_fail) in CONTROL_MUTATIONS.items():
        c = copy.deepcopy(case)
        c.setdefault("constraint_block", {})
        mutate(c)
        c["case_id"] = f"{case.get('case_id') or 'plan'}::control::{name}"
        c["expect_fail"] = list(must_fail)
        out.append(c)
    return out
