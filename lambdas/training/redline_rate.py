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


def _brake_lb_wk() -> float:
    return float(next(t for t in _redlines()["rate_protein_gate"]["body_fat_tiers"]["tiers"] if t.get("brake_lb_wk"))["brake_lb_wk"])


def gated_target_lb_wk(weight_lb: float) -> tuple[float, str]:
    """(the gated target, where it came from) — the ONE field `rate_protein_gate.gated_target` decides."""
    gt = _redlines()["rate_protein_gate"]["gated_target"]
    if gt.get("fixed_lb_wk") is not None:
        return float(gt["fixed_lb_wk"]), "rate_protein_gate.gated_target.fixed_lb_wk"
    return round(weight_lb * _redlines()["rate_band_pct_bw_per_wk"]["low"] / 100, 1), str(gt["source"])


def _num(v: Any) -> float | None:
    try:
        return None if v in (None, "") or isinstance(v, bool) else float(v)
    except (TypeError, ValueError):
        return None


def _dxa_point(row: dict[str, Any]) -> dict[str, Any] | None:
    """One scan's (date, fat-free mass, scan weight) — FFM = lean + bone mineral content, the ONE derivation (#4166).
    A row missing either component is unreadable, never a zero."""
    bc = (row or {}).get("body_composition") or {}
    lean, bmc = _num(bc.get("lean_mass_lb")), _num(bc.get("bone_mineral_content_lb"))
    if lean is None or bmc is None or not row.get("scan_date"):
        return None
    return {
        "scan_date": str(row["scan_date"]),
        "lean_lb": lean,
        "bmc_lb": bmc,
        "ffm_lb": round(lean + bmc, 1),
        "scan_weight_lb": _num(bc.get("total_mass_lb")),
    }


def dxa_override(points: list[dict[str, Any]]) -> dict[str, Any]:
    """The pre-registered override (#4166): dFFM / dW over the latest two readable scans > the threshold -> the full gate."""
    o = _redlines()["rate_protein_gate"]["body_fat_tiers"]["dxa_override"]
    out: dict[str, Any] = {"threshold": o["ffm_share_of_loss_above"], "triggered": False, "first_evaluation": o["first_evaluation"]}
    if len(points) < 2:
        return {**out, "state": "no_pair", "reason": f"{len(points)} readable DXA scan(s) — a pair is needed"}
    prev, last = points[-2], points[-1]
    out["pair"] = [prev["scan_date"], last["scan_date"]]
    if prev["scan_weight_lb"] is None or last["scan_weight_lb"] is None:
        return {**out, "state": "unreadable", "reason": "a scan in the pair carries no total_mass_lb"}
    d_w, d_ffm = round(prev["scan_weight_lb"] - last["scan_weight_lb"], 1), round(prev["ffm_lb"] - last["ffm_lb"], 1)
    out.update({"delta_weight_lb": d_w, "delta_ffm_lb": d_ffm})
    if d_w <= 0:
        return {
            **out,
            "state": "not_a_loss",
            "reason": f"weight did not fall between {prev['scan_date']} and {last['scan_date']} — the ratio is undefined",
        }
    ratio = round(d_ffm / d_w, 3)
    trig = ratio > o["ffm_share_of_loss_above"]
    reason = f"dFFM/dW = {d_ffm}/{d_w} = {ratio} {'>' if trig else '<='} {o['ffm_share_of_loss_above']}"
    return {**out, "state": "triggered" if trig else "clear", "triggered": trig, "ffm_share_of_loss": ratio, "reason": reason}


def body_fat_tier(weight_lb: float | None, dxa_scans: list[dict[str, Any]] | None) -> dict[str, Any]:
    """The protein gate's body-fat tier (owner 2026-09-25, #4166): the latest DXA's FFM re-based on today's
    weight. `dxa_scans` None = the read failed; [] = no scan exists; either (or no weight) -> tier `unknown`."""
    cfg = _redlines()["rate_protein_gate"]["body_fat_tiers"]
    points = sorted((p for p in (_dxa_point(r) for r in (dxa_scans or [])) if p), key=lambda p: p["scan_date"])
    out: dict[str, Any] = {"override": dxa_override(points)}
    if not points or not weight_lb:
        why = "the DXA read failed" if dxa_scans is None else ("no weight today" if points else "no readable DXA scan")
        return {**out, "tier": "unknown", "body_fat_pct": None, "source": None, "reason": f"{why} — {cfg['unknown']}"}
    last = points[-1]
    pct = round((weight_lb - last["ffm_lb"]) / weight_lb * 100, 1)
    tier = next(t for t in cfg["tiers"] if pct >= t["at_or_above_pct"])
    source = {**last, "rebased_on_weight_lb": weight_lb, "derivation": cfg["source"]}
    return {
        **out,
        "tier": tier["tier"],
        "body_fat_pct": pct,
        "source": source,
        "evidence": tier["evidence"],
        "brake_lb_wk": tier.get("brake_lb_wk"),
    }


def _effective_mode(g: dict[str, Any], bf: dict[str, Any]) -> tuple[str, str]:
    """(the mode the gate runs in, why) — a forced mode, else the DXA override, else the tier (unknown -> report_only)."""
    mode = g.get("mode", "by_body_fat")
    if mode in ("enforce", "report_only"):
        return mode, f"rate_protein_gate.mode forced '{mode}'"
    if bf["override"]["triggered"]:
        return "enforce", f"the DXA override: {bf['override']['reason']} — the full gate at any body fat (#4166)"
    tier = bf["tier"]
    if tier == "unknown":
        return "report_only", f"body-fat tier unknown ({bf['reason']})"
    return {"report_only": "report_only", "brake": "brake", "full": "enforce"}[tier], f"body fat {bf['body_fat_pct']} % -> tier {tier}"


def protein_gate(
    missed: int | None,
    measured: int | None,
    window: dict[str, str] | None = None,
    body_fat: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ruling "B" (v3.3): is the served rate target the schedule step, the braked step, or the gated target?
    The mode comes from the body-fat tier (#4166); `window` is echoed."""
    g = _redlines()["rate_protein_gate"]
    bf = body_fat or body_fat_tier(None, [])
    mode, mode_reason = _effective_mode(g, bf)
    out = {"missed_7d": missed, "measured_7d": measured, "threshold": g["missed_days_threshold"], "min_measured": g["min_measured_days"]}
    out.update({"window": window, "mode": mode, "mode_reason": mode_reason, "tier": bf["tier"], "body_fat_pct": bf["body_fat_pct"]})
    out.update({"body_fat_source": bf["source"], "tier_evidence": bf.get("evidence"), "dxa_override": bf["override"]})
    if missed is None or measured is None or measured < g["min_measured_days"]:
        return {
            **out,
            "state": "unknown",
            "would_apply": False,
            "applied": False,
            "reason": f"{measured or 0} measured day(s) < {g['min_measured_days']} — target unchanged",
        }
    would_apply = missed >= g["missed_days_threshold"]
    # report_only (owner 2026-09-25): the state is still read and reported; the served target never moves
    return {
        **out,
        "state": "gated" if would_apply else "clear",
        "would_apply": would_apply,
        "applied": would_apply and mode != "report_only",
    }


def rate_target_lb_per_wk(
    weight_lb: float | None,
    *,
    protein_missed_7d: int | None = None,
    protein_measured_7d: int | None = None,
    protein_window_days: dict[str, str] | None = None,
    dxa_scans: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """The rate at a given bodyweight: the %BW envelope in pounds AND the scheduled absolute target —
    gated by protein adherence (v3.3 ruling "B", `protein_gate`): `target_lb_wk` is the SERVED target.
    The gate's mode scales with body fat (#4166, `body_fat_tier` over `dxa_scans`): report-only, the step
    minus the brake, or the gated target — decided HERE, the one place the served target is computed."""
    if not weight_lb:
        return None
    band = _redlines()["rate_band_pct_bw_per_wk"]
    step = rate_schedule_step(weight_lb)
    low = round(weight_lb * band["low"] / 100, 1)
    bf = body_fat_tier(weight_lb, dxa_scans)
    gate = protein_gate(protein_missed_7d, protein_measured_7d, protein_window_days, bf)
    gated, gated_source = gated_target_lb_wk(weight_lb)
    gate["gated_target_lb_wk"], gate["gated_target_source"] = gated, gated_source
    brake = bf.get("brake_lb_wk") or _brake_lb_wk()
    gate["braked_target_lb_wk"] = round(step["target"] - brake, 2)
    if not gate["applied"]:
        served = step["target"]
    else:
        served = gate["braked_target_lb_wk"] if gate["mode"] == "brake" else gated
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
