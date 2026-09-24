"""redline_rate.py — the rate arithmetic over `owner_redlines`' data (#4161 extraction, #1665 size ratchet).

`owner_redlines` is the ONE home of every number used here; this module only computes with them
and is re-exported there under the same names. Ruling "B" (owner, 2026-09-24, v3.3): the SERVED rate
target is conditional on protein adherence — `protein_gate`.
"""

from __future__ import annotations

from typing import Any


def _redlines() -> dict[str, Any]:
    # lazy: `owner_redlines` re-exports this module at its end, so a module-level import would be circular
    from training import owner_redlines

    return owner_redlines.REDLINES


def rate_schedule_step(weight_lb: float) -> dict[str, Any]:
    """The scheduled step for a bodyweight — the first step whose `above_lb` the weight exceeds."""
    for step in _redlines()["rate_schedule_lb_wk"]["steps"]:
        if weight_lb > step["above_lb"]:
            return step
    return _redlines()["rate_schedule_lb_wk"]["steps"][-1]


def protein_days_missed(grams_by_day: list[Any] | None) -> tuple[int | None, int]:
    """(days below the protein floor, days MEASURED) over a series with None for an unlogged day.

    THE count (#4161): an unlogged day is unmeasured, never missed. `mcp.tools_plan._protein_days_7d`
    and `health.nutrition_critics` both read it, so the gate and the critics count one way."""
    floor = float(_redlines()["protein_floor_g"]["value"])
    grams = [float(g) for g in (grams_by_day or []) if g is not None]
    return (sum(1 for g in grams if g < floor) if grams else None), len(grams)


def protein_gate(missed: int | None, measured: int | None) -> dict[str, Any]:
    """Ruling "B" (v3.3): is the served rate target the schedule step, or the envelope's lower band?"""
    g = _redlines()["rate_protein_gate"]
    out = {"missed_7d": missed, "measured_7d": measured, "threshold": g["missed_days_threshold"], "min_measured": g["min_measured_days"]}
    if missed is None or measured is None or measured < g["min_measured_days"]:
        return {
            **out,
            "state": "unknown",
            "applied": False,
            "reason": f"{measured or 0} measured day(s) < {g['min_measured_days']} — target unchanged",
        }
    applied = missed >= g["missed_days_threshold"]
    return {**out, "state": "gated" if applied else "clear", "applied": applied}


def rate_target_lb_per_wk(
    weight_lb: float | None, *, protein_missed_7d: int | None = None, protein_measured_7d: int | None = None
) -> dict[str, Any] | None:
    """The rate at a given bodyweight: the %BW envelope in pounds AND the scheduled absolute target —
    gated by protein adherence (v3.3 ruling "B", `protein_gate`): `target_lb_wk` is the SERVED target."""
    if not weight_lb:
        return None
    band = _redlines()["rate_band_pct_bw_per_wk"]
    step = rate_schedule_step(weight_lb)
    low = round(weight_lb * band["low"] / 100, 1)
    gate = protein_gate(protein_missed_7d, protein_measured_7d)
    return {
        "low_lb_wk": low,
        "high_lb_wk": round(weight_lb * band["high"] / 100, 1),
        "target_lb_wk": low if gate["applied"] else step["target"],
        "step_target_lb_wk": step["target"],
        "protein_gate": gate,
        "cap_lb_wk": step["cap"],
        "dxa_gate": step.get("dxa_gate"),
        "target_pct_bw_wk": round((low if gate["applied"] else step["target"]) / weight_lb * 100, 2),
        "schedule_step_above_lb": step["above_lb"],
        "landing_phase": weight_lb <= _redlines()["landing"]["deceleration_begins_lb"],
        "provenance": band["provenance"],
        "schedule_provenance": _redlines()["rate_schedule_lb_wk"]["provenance"],
        "stated": band["stated"],
        "owner_to_resolve": band.get("owner_to_resolve"),
        "resolution": band.get("resolution"),
    }
