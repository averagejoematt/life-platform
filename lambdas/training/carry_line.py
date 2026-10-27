"""carry_line.py — a loaded carry's own report line: load and steps, never weight x distance (#5372).

A farmer's walk is logged under Hevy's standard distance-typed template (`short_distance_weight`, 50C613D0): each set has a
load and a distance, no reps. Two facts make the usual arithmetic wrong, both the owner's (2026-10-25, attended):

  * the distance field on a carry is his STEP COUNT — there are no distance markings in the gym, so he counts steps and
    types the number into the yards field (Hevy's API passes it through unconverted as `distance_meters`);
  * so `weight x distance` is neither a tonnage nor a work figure, and a carry set has no reps to make a rep-tonnage.

So a carry stays OUT of the rep-tonnage sum (`weight x reps` is 0 for it by construction) and is reported on its own line as the
load as logged and the step count from the distance field.

#5373 (the definition layer, `training.logging_conventions`): the line names the exercise's `load_convention` ON THE SESSION'S DATE
(`per_hand` from the owner's one-hand rule of 2026-10-27 — the load is one dumbbell; `total_carried` before it — the sum of both
hands; the date is why `day` is a required argument) and `distance_unit: steps`, and — given his stride (`trailing_stride`) —
renders each set as "N steps (~X yd, est. from unloaded stride)"; with no measured stride, "N steps". The yards are an estimate
from his UNLOADED walking stride and are never compared to a true distance.

Pure: reads stored/normalized set dicts (`weight_kg` | `weight_lbs`, `reps`, `distance_m` | `distance_meters`, `type`); the stride is
passed in; the conventions resolve through the catalog (`logging_conventions.load_convention_for`).
"""

from __future__ import annotations

import re
from typing import Any

_KG_TO_LB = 2.20462
_CARRY_TITLE = re.compile(r"carry|farmer|suitcase", re.I)

STEPS_BASIS = (
    "the distance field on a carry is his step count (owner, 2026-10-25), not a distance. Carries are outside the rep-tonnage "
    "sum; no weight x distance is computed."
)
LOAD_BASIS = {
    "per_hand": "the load is ONE dumbbell's weight (per hand; owner's one-hand rule from 2026-10-27) — both hands carry it.",
    "total_carried": "the load is the TOTAL carried (the sum of both hands; a carry logged before 2026-10-27, or a one-object carry).",
}


def _num(v: Any) -> float | None:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _distance(s: dict[str, Any]) -> float:
    return _num(s.get("distance_m")) or _num(s.get("distance_meters")) or 0.0


def _load_lb(s: dict[str, Any]) -> float | None:
    kg = _num(s.get("weight_kg"))
    if kg:
        return round(kg * _KG_TO_LB, 1)
    lb = _num(s.get("weight_lbs"))
    return round(lb, 1) if lb else None


def _working(sets: Any) -> list[dict[str, Any]]:
    return [s for s in sets or [] if isinstance(s, dict) and str(s.get("set_type") or s.get("type") or "normal").lower() != "warmup"]


def is_carry(name: str, sets: Any) -> bool:
    """True for a loaded, distance-typed, reps-less exercise: no working set has reps, a working set has a distance, and the
    exercise is either loaded or titled as a carry. A timed cardio block (a duration and a distance, no load) is not a carry."""
    work = _working(sets)
    if not work or any((_num(s.get("reps")) or 0) > 0 for s in work):
        return False
    if not any(_distance(s) > 0 for s in work):
        return False
    return any(_load_lb(s) for s in work) or bool(_CARRY_TITLE.search(name or ""))


def carry_line(name: str, sets: Any, *, day: Any, template_id: Any = None, stride: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """`{sets, load_lb, load_convention, distance_unit, steps, steps_total, estimated_yd, rendered, stride, steps_basis,
    excluded_from_rep_tonnage}` for a carry exercise, else None. `load_lb`, `steps`, `estimated_yd` and `rendered` are per working
    set, in set order; a set with no load logged reads None, never 0. `estimated_yd` is None without a measured `stride`.
    `day` (required, keyword) is the session's Pacific date — the load convention is dated (#5373); a carry whose catalog entry
    carries a history raises `MissingSessionDate` without one."""
    from training import logging_conventions as lc  # noqa: PLC0415 — lazy: the catalog read stays off the import path

    if not is_carry(name, sets):
        return None
    work = _working(sets)
    steps = [int(round(_distance(s))) if _distance(s) else None for s in work]
    convention = lc.load_convention_for(name, template_id, sets, day=day)
    return {
        "sets": len(work),
        "load_lb": [_load_lb(s) for s in work],
        "load_convention": convention,
        "distance_unit": lc.STEPS,
        "steps": steps,
        "steps_total": sum(n for n in steps if n),
        "estimated_yd": [lc.estimated_yards(n, stride) if n else None for n in steps],
        "rendered": [lc.render_steps(n, stride) if n else None for n in steps],
        "stride": stride,
        "steps_basis": f"{STEPS_BASIS} {LOAD_BASIS.get(convention, '')}".strip(),
        "excluded_from_rep_tonnage": True,
    }
