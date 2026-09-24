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


def protein_window(target_date: str, today: str) -> dict[str, str]:
    """THE protein-gate window (#4161): the 7 COMPLETED Pacific days ending the earlier of the day before
    `target_date` and yesterday — MacroFactor lands ~24 h late, so today is never complete. The plan's
    gate (`tools_plan._protein_days_7d`) and the nutrition critics' deficit advocate both read this."""
    from common.pacific_time import shift_day_key

    end = min(shift_day_key(target_date, -1), shift_day_key(today, -1))
    return {"start": shift_day_key(end, -6), "end": end}


def gated_target_lb_wk(weight_lb: float) -> tuple[float, str]:
    """(the gated target, where it came from) — the ONE field `rate_protein_gate.gated_target` decides."""
    gt = _redlines()["rate_protein_gate"]["gated_target"]
    if gt.get("fixed_lb_wk") is not None:
        return float(gt["fixed_lb_wk"]), "rate_protein_gate.gated_target.fixed_lb_wk"
    return round(weight_lb * _redlines()["rate_band_pct_bw_per_wk"]["low"] / 100, 1), str(gt["source"])


def protein_gate(missed: int | None, measured: int | None, window: dict[str, str] | None = None) -> dict[str, Any]:
    """Ruling "B" (v3.3): is the served rate target the schedule step, or the gated target? `window` is echoed."""
    g = _redlines()["rate_protein_gate"]
    out = {"missed_7d": missed, "measured_7d": measured, "threshold": g["missed_days_threshold"], "min_measured": g["min_measured_days"]}
    out["window"] = window
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
    weight_lb: float | None,
    *,
    protein_missed_7d: int | None = None,
    protein_measured_7d: int | None = None,
    protein_window_days: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """The rate at a given bodyweight: the %BW envelope in pounds AND the scheduled absolute target —
    gated by protein adherence (v3.3 ruling "B", `protein_gate`): `target_lb_wk` is the SERVED target."""
    if not weight_lb:
        return None
    band = _redlines()["rate_band_pct_bw_per_wk"]
    step = rate_schedule_step(weight_lb)
    low = round(weight_lb * band["low"] / 100, 1)
    gate = protein_gate(protein_missed_7d, protein_measured_7d, protein_window_days)
    gated, gated_source = gated_target_lb_wk(weight_lb)
    gate["gated_target_lb_wk"], gate["gated_target_source"] = gated, gated_source
    served = gated if gate["applied"] else step["target"]
    return {
        "low_lb_wk": low,
        "high_lb_wk": round(weight_lb * band["high"] / 100, 1),
        "target_lb_wk": served,
        "step_target_lb_wk": step["target"],
        "protein_gate": gate,
        "cap_lb_wk": step["cap"],
        "dxa_gate": step.get("dxa_gate"),
        "target_pct_bw_wk": round(served / weight_lb * 100, 2),
        "schedule_step_above_lb": step["above_lb"],
        "landing_phase": weight_lb <= _redlines()["landing"]["deceleration_begins_lb"],
        "provenance": band["provenance"],
        "schedule_provenance": _redlines()["rate_schedule_lb_wk"]["provenance"],
        "stated": band["stated"],
        "owner_to_resolve": band.get("owner_to_resolve"),
        "resolution": band.get("resolution"),
    }
