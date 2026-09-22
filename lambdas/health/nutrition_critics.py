"""nutrition_critics.py — three adversarial reviewers over the nutrition plan (#3754 boxes 3+4, epic #3742).

WHY THIS EXISTS

The 2026-09-20 red-team read `get_deficit_sustainability` saying SUSTAINABLE on a measured
1,533 kcal/day at 317 lb, protein 146 g mean with the 180 g floor hit on 3 of 14 days. Four
of five personas named that line as the most dangerous in the packet. Box 2 (#3998) made
the tool label its cutoffs; this module is box 3 — the nutrition plan runs through the SAME
critic structure the training draft does (`coach.critics`, #3752): three critics holding
DIFFERENT evidence built from the same measured inputs, each forced to name a number.

THE THREE CRITICS AND WHAT EACH ONE HOLDS

  deficit_advocate   argues FOR the owner's scheduled rate: the 14-day trend vs
                     `rate_target_lb_per_wk(weight)`, the overshoot rule, the IC-29 flag
  muscle_defense     the energy floor, the protein floor and target, the 7-day mean intake
                     vs the prescribed band, the deficit tool's own composite severity
  adherence          logging dark, walking collapse week-over-week, self-added volume

The packets are pairwise-disjoint by metric name (`tests/test_nutrition_critics_3754.py`
holds them apart): two critics reading the same number agree by construction.

ONE VERDICT RULE IN THE CODEBASE

`coach.critics.deterministic_verdict` and `coach.critics.reconcile` are imported and
reused, never copied. `coach.critics.run_critics` is NOT reused: it iterates the training
`CRITIC_IDS` by name, so this module runs the same two functions over its own ids. v1 is
deterministic only (ADR-105: computation before any LLM verdict) — every verdict records
`model = {"paused": MODEL_PAUSED_REASON}`; a critic that did not run a model says so.

WHERE EVERY THRESHOLD COMES FROM

`training.owner_redlines` (#3753), read BY ID AT CALL TIME — never a literal here — with
its `provenance` carried onto every flag. While `owner_redlines.ACTIVE` is False the
redlines are PROPOSED: a redline breach is a `change`, not a `veto`, and the reason says
so (the posture `coach/critics.py` documents). When ACTIVE is True the same breach is a
`veto`. The two thresholds this module owns itself (`STALL_FLAT_LB_WK`, the IC-29 bands it
reads off the tool's severity) are labelled population-derived at the point of use.

BOX 4 — DECISIONS, NEVER SILENT

`decisions_offered()` returns a PENDING decision record per tripped trigger, each carrying
the EXACT `log_decision` args. This module NEVER writes: no table handle, no import of
the decision-logging tool — the owner logs the decision himself and sets `followed`.

This module is PURE. Inputs are a plain dict resolved by the caller (the MCP layer,
`mcp/nutrition_critics_inputs.py`); an absent input is NAMED in `unknown`, never skipped.
"""

from __future__ import annotations

from typing import Any

from coach.critics import deterministic_verdict, reconcile
from training import owner_redlines

from health import deficit_disclosures

CRITICS_VERSION = "nutrition-critics@1.0.0"
CRITIC_IDS = ("deficit_advocate", "muscle_defense", "adherence")
MODEL_PAUSED_REASON = "not wired for nutrition (v1)"
DECISION_SOURCE = "nutrition_critics"
DECISION_PILLARS = ["nutrition"]

# The ONE cutoff this module owns: "flat" for the weight-stall trigger. The platform's own
# `get_weight_loss_progress` already calls a weekly rate under 0.25 lb/wk "very slow";
# reused here so the stall decision and the progress tool agree on what flat means.
STALL_FLAT_LB_WK = 0.25
STALL_FLAT_PROVENANCE = (
    "population-derived (the platform's own 0.25 lb/wk 'very slow' cutoff in get_weight_loss_progress — not his variance)"
)
IC29_PROVENANCE = "population-derived (IC-29 adaptation-ratio bands 0.60 / 0.35, Trexler/McDonald/Norton — not his variance)"
IC29_FLAG_SEVERITIES = ("MODERATE", "SEVERE")

# The inputs this module reads. Every key is optional; an absent one lands in `unknown`.
INPUT_KEYS = (
    "window_end",  # YYYY-MM-DD, the last day of the 14-day series (informational)
    "intake_kcal_by_day",  # 14 entries oldest->newest, None for an unlogged day
    "protein_g_by_day",  # 14 entries oldest->newest, None for an unlogged day
    "lifting_day_flags",  # 14 entries oldest->newest, True/False/None
    "weight_lb",  # latest weigh-in
    "weight_trend_lb_wk",  # SIGNED 14-day trend, negative = losing (health.tdee.weight_trend_lb_per_wk)
    "weighin_count",
    "weighin_span_days",
    "rate_provisional",  # bool: the trend window is too short to argue from
    "weekly_loss_rates_lb_wk",  # POSITIVE = loss, one per trailing week, oldest->newest
    "weeks_since_genesis",
    "walking_hr_this_wk",
    "walking_hr_last_wk",
    "deficit_severity",  # tool_get_deficit_sustainability's composite verdict
    "degraded_count",
    "metabolic_adaptation_severity",  # IC-29 severity string, or None
    "metabolic_adaptation_flag",  # bool derived from the severity by the caller, or None
    "training_above_prescription_weeks",  # int, or None when the platform has no such read yet
    "estimated_maintenance_kcal",  # optional, for sizing a diet break
)


# ── helpers ────────────────────────────────────────────────────────────────────────────
def _redline(rid: str) -> dict[str, Any]:
    return owner_redlines.REDLINES[rid]


def _tripwire(tid: str) -> dict[str, Any]:
    return next(t for t in owner_redlines.TRIPWIRES if t["id"] == tid)


def _flag(metric: str, severity: str, reason: str, *, provenance: str, field: str | None = None, to: Any = None) -> dict[str, Any]:
    return {"metric": metric, "severity": severity, "reason": reason, "provenance": provenance, "field": field, "to": to}


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _series(inputs: dict[str, Any], key: str, n: int = 14) -> list[Any] | None:
    s = inputs.get(key)
    if not isinstance(s, (list, tuple)):
        return None
    s = list(s)
    return s[-n:] if len(s) >= n else [None] * (n - len(s)) + s


def _logged(values: list[Any] | None) -> list[float]:
    return [x for x in (_num(v) for v in (values or [])) if x is not None]


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 0) if values else None


def _redline_breach(
    packet: dict[str, Any],
    *,
    redline: str,
    metric: str,
    reason: str,
    provenance: str,
    field: str | None,
    to: Any,
) -> None:
    """A breach of an owner redline. `veto` when the owner has signed (#3753 ACTIVE); while
    the redlines are PROPOSED it is a `change` whose reason says so — a plan is not refused
    on a rule he has not yet signed (the posture coach/critics.py documents)."""
    if owner_redlines.ACTIVE:
        packet["violations"].append(
            {"redline": redline, "metric": metric, "reason": reason, "field": field, "to": to, "provenance": provenance}
        )
        return
    packet["flags"].append(
        _flag(
            metric,
            "change",
            f"{reason} [redline `{redline}` is PROPOSED — #3753 unsigned (v{owner_redlines.REDLINES_VERSION}): a breach is a change, not a veto, until the owner flips ACTIVE]",
            provenance=provenance,
            field=field,
            to=to,
        )
    )


def _new_packet(critic: str) -> dict[str, Any]:
    return {"critic": critic, "numbers": {}, "flags": [], "unknown": [], "violations": []}


def _loss_rate(inputs: dict[str, Any]) -> float | None:
    trend = _num(inputs.get("weight_trend_lb_wk"))
    return None if trend is None else round(-trend, 2)


# ── critic 1: the deficit advocate ─────────────────────────────────────────────────────
def build_deficit_advocate_packet(inputs: dict[str, Any]) -> dict[str, Any]:
    """Argues FOR the owner's scheduled rate. Below target is an ADHERENCE AUDIT, never
    "eat less" — unless mean intake sits above the prescribed band's top. Above the cap
    for two consecutive weeks after week 4 is the schedule's own overshoot rule."""
    p = _new_packet("deficit_advocate")
    n, flags, unknown = p["numbers"], p["flags"], p["unknown"]
    sched = _redline("rate_schedule_lb_wk")
    energy = _redline("energy_floor_kcal")
    overshoot_t = _tripwire("rate_overshoot")
    weight = _num(inputs.get("weight_lb"))
    target = owner_redlines.rate_target_lb_per_wk(weight)
    loss = _loss_rate(inputs)
    intake14 = _logged(_series(inputs, "intake_kcal_by_day"))
    mean14 = _mean(intake14)
    weeks = inputs.get("weeks_since_genesis")
    rates = [r for r in (_num(x) for x in (inputs.get("weekly_loss_rates_lb_wk") or [])) if r is not None]
    lo, hi = energy["prescribed"]
    n.update(
        {
            "weight_lb": weight,
            "loss_rate_14d_lb_wk": loss,
            "weighin_count": inputs.get("weighin_count"),
            "weighin_span_days": inputs.get("weighin_span_days"),
            "rate_provisional": inputs.get("rate_provisional"),
            "rate_target_lb_wk": (target or {}).get("target_lb_wk"),
            "rate_cap_lb_wk": (target or {}).get("cap_lb_wk"),
            "rate_band_low_lb_wk": (target or {}).get("low_lb_wk"),
            "rate_band_high_lb_wk": (target or {}).get("high_lb_wk"),
            "mean_intake_kcal_14d": mean14,
            "prescribed_band_kcal": [lo, hi],
            "weeks_since_genesis": weeks,
            "weekly_loss_rates_lb_wk": rates or None,
            "metabolic_adaptation_severity": inputs.get("metabolic_adaptation_severity"),
        }
    )
    if weight is None or target is None:
        unknown.append("weight_lb")
    if loss is None:
        unknown.append("loss_rate_14d_lb_wk")
    if mean14 is None:
        unknown.append("mean_intake_kcal_14d")
    if weeks is None:
        unknown.append("weeks_since_genesis")
    if not rates:
        unknown.append("weekly_loss_rates_lb_wk")
    if inputs.get("metabolic_adaptation_severity") is None:
        unknown.append("metabolic_adaptation_severity")

    sched_prov = f"{sched['provenance']} ({sched['derived_by']})"
    if target is not None and loss is not None:
        tgt, cap = target["target_lb_wk"], target["cap_lb_wk"]
        n_str = f"n={inputs.get('weighin_count')} weigh-ins over {inputs.get('weighin_span_days')} d"
        if inputs.get("rate_provisional"):
            flags.append(
                _flag(
                    "loss_rate_14d_lb_wk",
                    "info",
                    f"trend {loss} lb/wk is PROVISIONAL ({n_str}) — no change is argued from it; the schedule's target at {weight:.0f} lb is {tgt} lb/wk",
                    provenance=sched_prov,
                )
            )
        elif loss < tgt:
            if mean14 is not None and mean14 > hi:
                flags.append(
                    _flag(
                        "loss_rate_14d_lb_wk",
                        "change",
                        f"losing {loss} lb/wk against the scheduled {tgt} lb/wk at {weight:.0f} lb ({n_str}), and mean intake {mean14:.0f} kcal "
                        f"is ABOVE the prescribed {lo}-{hi} band — bring intake to the band's top ({hi}), not below it",
                        provenance=sched_prov,
                        field="intake_kcal_per_day",
                        to=hi,
                    )
                )
            else:
                flags.append(
                    _flag(
                        "loss_rate_14d_lb_wk",
                        "change",
                        f"losing {loss} lb/wk against the scheduled {tgt} lb/wk at {weight:.0f} lb ({n_str}) with mean intake "
                        f"{'unknown' if mean14 is None else f'{mean14:.0f} kcal'} inside or below the prescribed {lo}-{hi} band — "
                        "an ADHERENCE AUDIT (gram-scale logging week), never 'eat less': the redline is eat MORE, not less",
                        provenance=sched_prov,
                        field="logging",
                        to="adherence_audit",
                    )
                )
        elif loss > cap:
            flags.append(
                _flag(
                    "loss_rate_14d_lb_wk",
                    "info",
                    f"losing {loss} lb/wk, above the {cap} lb/wk cap at {weight:.0f} lb ({n_str}) — the overshoot rule counts consecutive weeks, below",
                    provenance=sched_prov,
                )
            )
        else:
            flags.append(
                _flag(
                    "loss_rate_14d_lb_wk",
                    "info",
                    f"losing {loss} lb/wk, on the schedule ({tgt} target, {cap} cap at {weight:.0f} lb; {n_str})",
                    provenance=sched_prov,
                )
            )
        # the overshoot rule — the redline's own words, quoted
        need = int(overshoot_t["threshold_weeks"])
        over = [r > cap for r in rates[-need:]] if len(rates) >= need else []
        n["rate_over_cap_consecutive_weeks"] = sum(1 for r in reversed(rates) if r > cap) if rates else None
        if over and all(over) and weeks is not None and weeks > 4:
            to = (mean14 + 250) if mean14 is not None else None
            flags.append(
                _flag(
                    "rate_over_cap_consecutive_weeks",
                    "change",
                    f"trend above the {cap} lb/wk cap for {need} consecutive weeks ({', '.join(str(r) for r in rates[-need:])}) in week {weeks} — "
                    f"'{sched['overshoot_rule']}'",
                    provenance=overshoot_t["provenance"],
                    field="intake_kcal_per_day",
                    to=to,
                )
            )
    sev = inputs.get("metabolic_adaptation_severity")
    if sev in IC29_FLAG_SEVERITIES:
        flags.append(
            _flag(
                "metabolic_adaptation_severity",
                "change",
                f"IC-29 reads {sev} adaptation (actual loss well under expected) — a diet-break decision for the owner, not a push-harder",
                provenance=IC29_PROVENANCE,
                field="diet_break",
                to="decision",
            )
        )
    elif sev is not None:
        flags.append(_flag("metabolic_adaptation_severity", "info", f"IC-29 adaptation {sev}", provenance=IC29_PROVENANCE))
    return p


# ── critic 2: muscle defense ───────────────────────────────────────────────────────────
def _energy_floor_days(intake7: list[Any], lifting7: list[Any] | None, energy: dict[str, Any]) -> tuple[int | None, int, list[float]]:
    """(days below the day's floor, days measured, the breaching intakes). An unlogged day
    is unmeasured, never a breach; a lifting flag of None takes the any-day floor."""
    below, measured, breaches = 0, 0, []
    for i, raw in enumerate(intake7):
        kcal = _num(raw)
        if kcal is None:
            continue
        measured += 1
        lifting = bool(lifting7[i]) if lifting7 is not None and i < len(lifting7) and lifting7[i] is not None else False
        floor = energy["floor_lifting_day"] if lifting else energy["floor_any_day"]
        if kcal < floor:
            below += 1
            breaches.append(kcal)
    return (below if measured else None), measured, breaches


def build_muscle_defense_packet(inputs: dict[str, Any]) -> dict[str, Any]:
    """The energy floor and the protein floor — the two redlines whose breach is where lean
    mass goes. Trailing 7 days, measured days only."""
    p = _new_packet("muscle_defense")
    n, flags, unknown = p["numbers"], p["flags"], p["unknown"]
    energy = _redline("energy_floor_kcal")
    protein = _redline("protein_floor_g")
    floor_t = _tripwire("intake_floor_breached")
    prot_t = _tripwire("protein_floor_missed")
    intake14 = _series(inputs, "intake_kcal_by_day")
    protein14 = _series(inputs, "protein_g_by_day")
    lifting14 = _series(inputs, "lifting_day_flags")
    intake7 = intake14[-7:] if intake14 is not None else None
    protein7 = protein14[-7:] if protein14 is not None else None
    lifting7 = lifting14[-7:] if lifting14 is not None else None
    lo, hi = energy["prescribed"]
    energy_prov = f"{energy['provenance']} ({energy['derived_by']})"
    n.update(
        {
            "energy_floor_any_day_kcal": energy["floor_any_day"],
            "energy_floor_lifting_day_kcal": energy["floor_lifting_day"],
            "prescribed_low_kcal": lo,
            "protein_floor_g": protein["value"],
            "protein_target_g": protein["target_g"],
            "protein_target_days_of_7": protein["days_of_7"],
            "lifting_days_7d": (sum(1 for f in lifting7 if f) if lifting7 is not None else None),
            "deficit_tool_severity": inputs.get("deficit_severity"),
            "deficit_tool_degraded_count": inputs.get("degraded_count"),
        }
    )
    if lifting7 is None:
        unknown.append("lifting_days_7d")
        flags.append(
            _flag(
                "lifting_days_7d",
                "info",
                "lifting-day flags unreadable — every day is graded against the any-day floor, which UNDER-counts breaches on lifting days",
                provenance="owner",
            )
        )

    # energy floor
    if intake7 is None:
        n["energy_floor_days_below_7d"] = None
        n["mean_intake_kcal_7d"] = None
        unknown += ["energy_floor_days_below_7d", "mean_intake_kcal_7d"]
    else:
        below, measured, breaches = _energy_floor_days(intake7, lifting7, energy)
        mean7 = _mean(_logged(intake7))
        n["energy_floor_days_below_7d"] = below
        n["intake_days_measured_7d"] = measured
        n["mean_intake_kcal_7d"] = mean7
        if below is None:
            unknown += ["energy_floor_days_below_7d", "mean_intake_kcal_7d"]
        else:
            if below >= floor_t["threshold_days"]:
                _redline_breach(
                    p,
                    redline="energy_floor_kcal",
                    metric="energy_floor_days_below_7d",
                    reason=(
                        f"{below} of {measured} measured days below the energy floor ({energy['floor_any_day']} kcal; {energy['floor_lifting_day']} on a lifting day) — "
                        f"lowest {min(breaches):.0f} kcal; tripwire `{floor_t['id']}` threshold {floor_t['threshold_days']} days — {floor_t['action']}"
                    ),
                    provenance=energy_prov,
                    field="intake_kcal_per_day",
                    to=lo,
                )
            elif below > 0:
                flags.append(
                    _flag(
                        "energy_floor_days_below_7d",
                        "info",
                        f"{below} of {measured} measured days below the energy floor ({min(breaches):.0f} kcal) — one more is the tripwire",
                        provenance=energy_prov,
                    )
                )
            if mean7 is not None and mean7 < lo:
                flags.append(
                    _flag(
                        "mean_intake_kcal_7d",
                        "change",
                        f"mean intake {mean7:.0f} kcal over {measured} measured days is {lo - mean7:.0f} kcal BELOW the prescribed {lo}-{hi} band — eat more, not less",
                        provenance=energy_prov,
                        field="intake_kcal_per_day",
                        to=lo,
                    )
                )

    # protein floor + target
    if protein7 is None:
        n["protein_days_missed_7d"] = None
        n["protein_target_days_7d"] = None
        unknown += ["protein_days_missed_7d", "protein_target_days_7d"]
    else:
        grams = _logged(protein7)
        measured_p = len(grams)
        n["protein_days_measured_7d"] = measured_p
        if not grams:
            n["protein_days_missed_7d"] = None
            n["protein_target_days_7d"] = None
            unknown += ["protein_days_missed_7d", "protein_target_days_7d"]
        else:
            missed = sum(1 for g in grams if g < protein["value"])
            at_target = sum(1 for g in grams if g >= protein["target_g"])
            n["protein_days_missed_7d"] = missed
            n["protein_target_days_7d"] = at_target
            n["mean_protein_g_7d"] = _mean(grams)
            if missed >= prot_t["threshold_days"]:
                _redline_breach(
                    p,
                    redline="protein_floor_g",
                    metric="protein_days_missed_7d",
                    reason=(
                        f"{missed} of {measured_p} measured days below the {protein['value']} g floor (mean {n['mean_protein_g_7d']:.0f} g); "
                        f"tripwire `{prot_t['id']}` threshold {prot_t['threshold_days']} — {prot_t['action']}"
                    ),
                    provenance=prot_t["provenance"],
                    field="protein_g_per_day",
                    to=protein["value"],
                )
            elif missed > 0:
                flags.append(
                    _flag(
                        "protein_days_missed_7d",
                        "info",
                        f"{missed} of {measured_p} measured days below the {protein['value']} g floor",
                        provenance=prot_t["provenance"],
                    )
                )
            # the target is judged over 7 calendar days: an unmeasured day did not hit 200 g
            if at_target < protein["days_of_7"]:
                flags.append(
                    _flag(
                        "protein_target_days_7d",
                        "change",
                        f"{protein['target_g']} g reached on {at_target} of 7 days ({measured_p} measured) — the redline asks >= {protein['days_of_7']} of 7 in {protein['feedings']} feedings",
                        provenance=protein["provenance"],
                        field="protein_g_per_day",
                        to=protein["target_g"],
                    )
                )

    # the deficit tool's composite — its OWN recommendation, labelled with its provenance
    sev = inputs.get("deficit_severity")
    bands = deficit_disclosures.CONCURRENT_DEGRADATION_BANDS
    if sev is None:
        unknown.append("deficit_tool_severity")
    elif sev == "CRITICAL":
        flags.append(
            _flag(
                "deficit_tool_severity",
                "change",
                f"get_deficit_sustainability reads CRITICAL ({inputs.get('degraded_count')} of 5 channels degraded, band >= {bands['critical']['min_channels']}) — "
                "its own recommendation is +300-400 kcal for 5-7 days; a decision for the owner",
                provenance=bands["critical"]["provenance"],
                field="intake_kcal_per_day",
                to="refeed_decision",
            )
        )
    elif sev == "WARNING":
        flags.append(
            _flag(
                "deficit_tool_severity",
                "info",
                f"get_deficit_sustainability reads WARNING ({inputs.get('degraded_count')} of 5 channels) — {deficit_disclosures.DEFICIT_SUSTAINABILITY_HONESTY[:80]}...",
                provenance=bands["warning"]["provenance"],
            )
        )
    return p


# ── critic 3: adherence ────────────────────────────────────────────────────────────────
def _trailing_none_run(values: list[Any]) -> int:
    run = 0
    for v in reversed(values):
        if v is None:
            run += 1
        else:
            break
    return run


def _max_none_run(values: list[Any]) -> int:
    best = run = 0
    for v in values:
        run = run + 1 if v is None else 0
        best = max(best, run)
    return best


def build_adherence_packet(inputs: dict[str, Any]) -> dict[str, Any]:
    """The behavioural prodromes: logging goes dark before the walks do, the walks go before
    the weight does. A check-in, not a scolding."""
    p = _new_packet("adherence")
    n, flags, unknown = p["numbers"], p["flags"], p["unknown"]
    dark_t = _tripwire("logging_dark")
    walk_t = _tripwire("walking_collapse")
    vol_t = _tripwire("self_added_volume")
    intake14 = _series(inputs, "intake_kcal_by_day")
    this_wk, last_wk = _num(inputs.get("walking_hr_this_wk")), _num(inputs.get("walking_hr_last_wk"))
    above = inputs.get("training_above_prescription_weeks")
    n.update(
        {
            "logging_dark_trailing_days": None if intake14 is None else _trailing_none_run(intake14),
            "logging_dark_longest_run_14d": None if intake14 is None else _max_none_run(intake14),
            "logged_days_14d": None if intake14 is None else sum(1 for v in intake14 if v is not None),
            "walking_hr_this_wk": this_wk,
            "walking_hr_last_wk": last_wk,
            "walking_wow_pct": None,
            "training_above_prescription_weeks": above,
        }
    )
    if intake14 is None:
        unknown += ["logging_dark_trailing_days", "logged_days_14d"]
    else:
        trailing, longest = n["logging_dark_trailing_days"], n["logging_dark_longest_run_14d"]
        if trailing >= dark_t["threshold_days"]:
            flags.append(
                _flag(
                    "logging_dark_trailing_days",
                    "change",
                    f"no food log for the last {trailing} days (tripwire `{dark_t['id']}`, threshold {dark_t['threshold_days']}) — {dark_t['action']}",
                    provenance=dark_t["provenance"],
                    field="logging",
                    to="check_in",
                )
            )
        elif longest >= dark_t["threshold_days"]:
            flags.append(
                _flag(
                    "logging_dark_longest_run_14d",
                    "info",
                    f"a {longest}-day gap in the food log inside the trailing 14, since resumed — logged as a mood signal, not a current change",
                    provenance=dark_t["provenance"],
                )
            )
    if this_wk is None or last_wk is None:
        unknown.append("walking_wow_pct")
    elif last_wk > 0:
        wow = round((this_wk - last_wk) / last_wk * 100, 1)
        n["walking_wow_pct"] = wow
        if wow < -walk_t["threshold_pct"]:
            flags.append(
                _flag(
                    "walking_wow_pct",
                    "change",
                    f"walking+cycling {this_wk} hr vs {last_wk} hr last week ({wow}%, tripwire `{walk_t['id']}` at -{walk_t['threshold_pct']}%) — {walk_t['action']}",
                    provenance=walk_t["provenance"],
                    field="walking",
                    to="human_contact_and_mode_review",
                )
            )
        else:
            flags.append(
                _flag(
                    "walking_wow_pct",
                    "info",
                    f"walking+cycling {this_wk} hr vs {last_wk} hr last week ({wow:+}%)",
                    provenance=walk_t["provenance"],
                )
            )
    else:
        n["walking_wow_pct"] = None
        flags.append(
            _flag(
                "walking_wow_pct",
                "info",
                f"last week's walking read 0 hr — no week-over-week ratio; this week {this_wk} hr",
                provenance=walk_t["provenance"],
            )
        )
    if above is None:
        unknown.append("training_above_prescription_weeks")
    elif int(above) >= vol_t["threshold_weeks"]:
        flags.append(
            _flag(
                "training_above_prescription_weeks",
                "change",
                f"training above the prescription {above} weeks running (tripwire `{vol_t['id']}`) — {vol_t['action']}",
                provenance=vol_t["provenance"],
                field="training",
                to="subtract_only",
            )
        )
    return p


BUILDERS = {
    "deficit_advocate": build_deficit_advocate_packet,
    "muscle_defense": build_muscle_defense_packet,
    "adherence": build_adherence_packet,
}


def build_packets(inputs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {cid: BUILDERS[cid](inputs or {}) for cid in CRITIC_IDS}


# ── verdicts ───────────────────────────────────────────────────────────────────────────
def run(inputs: dict[str, Any], *, model_allowed: bool = False) -> dict[str, Any]:
    """Three verdicts over three packets, through `coach.critics`' deterministic layer and
    `reconcile` (the ONE verdict rule). v1 never runs a model: `model_allowed` is accepted
    for shape parity and refused — a critic that did not run a model says so."""
    inputs = inputs or {}
    packets = build_packets(inputs)
    verdicts: list[dict[str, Any]] = []
    for cid in CRITIC_IDS:
        packet = packets[cid]
        det = deterministic_verdict(packet)
        v = reconcile(det, None, packet)
        v["model"] = {"paused": MODEL_PAUSED_REASON}
        v["unknown"] = list(packet.get("unknown", []))
        if v.get("verdict") == "veto":
            # ADR-105: a population-derived redline keeps its label even once it is a veto —
            # coach.critics stamps violations "owner" (his calibration doc); ours carry their own.
            for viol in packet.get("violations", []):
                if viol["metric"] == v.get("metric") and viol.get("provenance"):
                    v["provenance"] = viol["provenance"]
        verdicts.append(v)
    return {
        "engine": CRITICS_VERSION,
        "critic_ids": list(CRITIC_IDS),
        "model_ran": False,
        "model_paused_reason": MODEL_PAUSED_REASON,
        "redlines_active": bool(owner_redlines.ACTIVE),
        "redlines_version": owner_redlines.REDLINES_VERSION,
        "verdicts": verdicts,
        "veto": any(v.get("verdict") == "veto" for v in verdicts),
        "packet_numbers": {cid: p["numbers"] for cid, p in packets.items()},
        "unknown": {cid: p["unknown"] for cid, p in packets.items() if p["unknown"]},
    }


# ── box 4: decisions the owner sees, never silent ──────────────────────────────────────
def _decision(trigger_id: str, values: dict[str, Any], *, provenance: str, options: list[str], decision: str) -> dict[str, Any]:
    note = f"trigger={trigger_id}; " + "; ".join(f"{k}={v}" for k, v in values.items())
    return {
        "state": "pending",
        "trigger": {"id": trigger_id, "values": values, "provenance": provenance},
        "options": options,
        "log_decision_payload": {
            "decision": f"[{trigger_id}] {decision}"[:500],
            "source": DECISION_SOURCE,
            "pillars": list(DECISION_PILLARS),
            "note": note[:500],
            "followed": None,
        },
        "owner_sets": ["followed (True = accepted, False = declined)", "override_reason (when declined)"],
        "how": "log_decision with `log_decision_payload` exactly — this module never writes it for you",
    }


def _already(trigger_id: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": "already_decided",
        "trigger": {"id": trigger_id},
        "already_decided": row.get("sk") or row.get("date"),
        "decided_on": row.get("date"),
        "followed": row.get("followed"),
        "decision": row.get("decision"),
    }


def _find_logged(trigger_id: str, already_logged: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in already_logged or []:
        if not isinstance(row, dict) or row.get("source") != DECISION_SOURCE:
            continue
        if f"trigger={trigger_id}" in str(row.get("note") or "") or f"[{trigger_id}]" in str(row.get("decision") or ""):
            return row
    return None


def _break_options(inputs: dict[str, Any]) -> list[str]:
    maint = _num(inputs.get("estimated_maintenance_kcal"))
    at = (
        f"~{maint:.0f} kcal"
        if maint is not None
        else "estimated maintenance (TDEE unpublished — derive it from the 14-day trend first, #3931)"
    )
    energy = _redline("energy_floor_kcal")
    return [
        f"diet break: 7-14 days at {at} (IC-29's own MODERATE recommendation)",
        f"refeed: 2 days at {at}, then resume the prescribed {energy['prescribed'][0]}-{energy['prescribed'][1]} band",
        "hold: no change this week",
    ]


def decisions_offered(
    verdicts: list[dict[str, Any]], inputs: dict[str, Any], *, already_logged: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """A PENDING decision record per tripped trigger, or `already_decided` when a
    `nutrition_critics` decision naming that trigger sits in `already_logged`. A trigger
    whose inputs cannot be read is returned `unevaluable` with the missing names."""
    inputs = inputs or {}
    out: list[dict[str, Any]] = []
    energy = _redline("energy_floor_kcal")
    protein = _redline("protein_floor_g")
    lifts = _redline("lifting_sessions_per_wk")
    stall_t = _tripwire("weight_stall_with_adherence")
    over_t = _tripwire("rate_overshoot")
    loss = _loss_rate(inputs)
    intake14 = _series(inputs, "intake_kcal_by_day")
    protein14 = _series(inputs, "protein_g_by_day")
    lifting14 = _series(inputs, "lifting_day_flags")
    lo, hi = energy["prescribed"]

    def emit(trigger_id: str, record: dict[str, Any]) -> None:
        prior = _find_logged(trigger_id, already_logged)
        out.append(_already(trigger_id, prior) if prior else record)

    # 1. weight stall WITH adherence — the diet-break / refeed decision
    missing = [
        k
        for k, v in (
            ("weight_trend_lb_wk", loss),
            ("intake_kcal_by_day", intake14),
            ("protein_g_by_day", protein14),
            ("lifting_day_flags", lifting14),
        )
        if v is None
    ]
    if missing or loss is None or intake14 is None or protein14 is None or lifting14 is None:
        out.append({"state": "unevaluable", "trigger": {"id": stall_t["id"]}, "unknown": missing})
    else:
        logged14 = _logged(intake14)
        mean14 = _mean(logged14)
        grams7 = _logged(protein14[-7:])
        prot_ok_days = sum(1 for g in grams7 if g >= protein["value"])
        lift_days = sum(1 for f in lifting14[-7:] if f)
        flat = loss < STALL_FLAT_LB_WK
        in_band = mean14 is not None and lo <= mean14 <= hi
        adherent = in_band and prot_ok_days >= protein["days_of_7"] and lift_days >= lifts["low"]
        values = {
            "loss_rate_14d_lb_wk": loss,
            "flat_below_lb_wk": STALL_FLAT_LB_WK,
            "mean_intake_kcal_14d": mean14,
            "logged_days_14d": len(logged14),
            "prescribed_band_kcal": f"{lo}-{hi}",
            "protein_floor_days_7d": prot_ok_days,
            "lifting_days_7d": lift_days,
        }
        if flat and adherent:
            emit(
                stall_t["id"],
                _decision(
                    stall_t["id"],
                    values,
                    provenance=f"{stall_t['provenance']}; flat = {STALL_FLAT_PROVENANCE}",
                    options=["audit first: a gram-scale logging week (the redline: 'an unaudited stall is a logging problem first')"]
                    + _break_options(inputs),
                    decision=f"14-day trend {loss} lb/wk with intake {mean14:.0f} kcal in band, protein floor {prot_ok_days}/7, lifting {lift_days}/7 — {stall_t['action']}",
                ),
            )

    # 2. rate overshoot — the schedule's own +250 rule
    weight = _num(inputs.get("weight_lb"))
    target = owner_redlines.rate_target_lb_per_wk(weight)
    rates = [r for r in (_num(x) for x in (inputs.get("weekly_loss_rates_lb_wk") or [])) if r is not None]
    weeks = inputs.get("weeks_since_genesis")
    need = int(over_t["threshold_weeks"])
    if target is None or len(rates) < need or weeks is None:
        out.append(
            {
                "state": "unevaluable",
                "trigger": {"id": over_t["id"]},
                "unknown": [
                    k
                    for k, ok in (
                        ("weight_lb", target is not None),
                        ("weekly_loss_rates_lb_wk", len(rates) >= need),
                        ("weeks_since_genesis", weeks is not None),
                    )
                    if not ok
                ],
            }
        )
    elif weeks > 4 and all(r > target["cap_lb_wk"] for r in rates[-need:]):
        mean14 = _mean(_logged(intake14)) if intake14 is not None else None
        emit(
            over_t["id"],
            _decision(
                over_t["id"],
                {
                    "weekly_loss_rates_lb_wk": rates[-need:],
                    "cap_lb_wk": target["cap_lb_wk"],
                    "weeks_since_genesis": weeks,
                    "mean_intake_kcal_14d": mean14,
                },
                provenance=over_t["provenance"],
                options=[
                    f"+250 kcal/day ({'to ' + format(mean14 + 250, '.0f') if mean14 is not None else 'from an unknown mean'}) — '{over_t['action']}'",
                    "hold",
                ],
                decision=f"trend over the {target['cap_lb_wk']} lb/wk cap {need} weeks running ({', '.join(str(r) for r in rates[-need:])}) — {over_t['action']}",
            ),
        )

    # 3. IC-29 adaptation
    sev = inputs.get("metabolic_adaptation_severity")
    flag = inputs.get("metabolic_adaptation_flag")
    if flag is None and sev is None:
        out.append({"state": "unevaluable", "trigger": {"id": "metabolic_adaptation"}, "unknown": ["metabolic_adaptation_severity"]})
    elif flag or sev in IC29_FLAG_SEVERITIES:
        emit(
            "metabolic_adaptation",
            _decision(
                "metabolic_adaptation",
                {"severity": sev},
                provenance=IC29_PROVENANCE,
                options=_break_options(inputs),
                decision=f"IC-29 adaptation {sev} — diet break or refeed, the owner's call",
            ),
        )

    # 4. the deficit tool's CRITICAL composite
    dsev = inputs.get("deficit_severity")
    if dsev is None:
        out.append({"state": "unevaluable", "trigger": {"id": "deficit_critical"}, "unknown": ["deficit_severity"]})
    elif dsev == "CRITICAL":
        emit(
            "deficit_critical",
            _decision(
                "deficit_critical",
                {"severity": dsev, "degraded_count": inputs.get("degraded_count")},
                provenance=deficit_disclosures.CONCURRENT_DEGRADATION_BANDS["critical"]["provenance"],
                options=["refeed: +300-400 kcal/day for 5-7 days (the tool's own recommendation)"] + _break_options(inputs)[:1] + ["hold"],
                decision=f"get_deficit_sustainability CRITICAL ({inputs.get('degraded_count')} of 5 channels) — refeed or diet break, the owner's call",
            ),
        )
    return out


def block(inputs: dict[str, Any], *, already_logged: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The whole owner-facing block: verdicts + decisions, one call."""
    res = run(inputs)
    res["decisions_offered"] = decisions_offered(res["verdicts"], inputs, already_logged=already_logged or [])
    return res
