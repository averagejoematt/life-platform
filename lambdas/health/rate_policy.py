"""rate_policy.py — an adaptive loss-rate BAND proposal (#5861 L5, owner brief §10). Pure; interface only; read by NO live path.

WHAT IT DOES. Given the signals the platform already computes — the body-fat tier, the observed rolling loss rate, the
core-anchor e1RM trend, recovery, adherence, hunger and an injected fatigue level — it proposes a target loss-rate band in
percent of bodyweight per week, names the signal that drove it, and says why. It never proposes a kcal number, never
reads or writes DynamoDB/S3, never reads the clock, and nothing on the live path imports it: the live rate is still
`governing_goal.rate_band_lb_per_wk` (`training.rate_band`) and the landing schedule (`training.redline_rate`), and the
live kcal is still `health.calorie_target.resolve` with the #5794 owner floors. Wiring it in is an owner decision
(`docs/coaching/WEEKLY_STRUCTURE.md` §"Rate policy interface" names the one seam: `health.titration.band_for`).

THE RULES (every number below is a labelled PRACTITIONER HEURISTIC unless it is read from `owner_redlines`; none is a
validated threshold for this person):

1. Start rung by the platform's EXISTING body-fat tier (`training.redline_rate.body_fat_tier`, tiers configured in
   `owner_redlines` rate_protein_gate.body_fat_tiers, which carries its own evidence notes — Hall 2007's re-reading of
   Forbes: the fat-free share of a loss falls as starting fat rises). Tier -> start rung (the rung numbers are heuristic):
   `report_only` (the highest body-fat tier) -> 0.75-1.25 %BW/wk; `brake` -> 0.5-1.0; `full` (the lowest) -> 0.5-0.75;
   `unknown` -> 0.5-1.0. The "about 0.5-1.0 %BW/wk" range is the common practitioner range for losing fat while keeping
   lean mass. Unknown never helps: it starts at the middle rung, never the fast one.
2. Each SLOW signal moves the band down one rung, never below the "slow" rung (0.25-0.5). No signal ever moves it UP:
   the start rung is the ceiling, and an observed rate BELOW the band is reported, never answered with a faster band.
3. SLOW signals, in driver precedence (the owner's priority order: strength and muscle first):
   - strength: 2+ core anchors below the trend threshold, or one anchor below twice it. The threshold is
     `owner_redlines` anchor_lift_strength_drop.threshold_pct (read, not restated); the caller passes nothing before
     that tripwire's own `not_before_week`.
   - fatigue: the injected fatigue level is "high" (L3's fatigue model; "elevated" is a watch, not a step).
   - recovery: the caller's recovery-low flag (the sleep or readiness_floor tripwire state). While the post-2026-10-10
     HR regime holds, an HR/HRV-derived readiness is NOT effort evidence; sleep is the HR-free input.
   - adherence: protein-floor days missed in 7 >= `owner_redlines` protein_floor_missed.threshold_days (read), or intake
     inside the prescribed band on fewer than 60 % of logged days in 14 (heuristic).
   - hunger: high hunger reported on 4+ of 7 check-ins (heuristic).
4. Three or more SLOW signals at once also return an `owner_decision` line: a maintenance phase or diet break is the
   owner's call, made elsewhere — this module never proposes zero.

Deterministic: same inputs, same output (no clock, no randomness, fixed precedence and rounding)."""

from __future__ import annotations

from typing import Any, Mapping, Optional

POLICY_VERSION = "rate_policy@0.1.0"

RUNGS: tuple[tuple[str, float, float], ...] = (
    ("slow", 0.25, 0.5),
    ("moderate", 0.5, 0.75),
    ("typical", 0.5, 1.0),
    ("high_mass", 0.75, 1.25),
)
"""The band ladder, slowest first: (name, low, high) in %BW/wk. PRACTITIONER HEURISTIC — no rung is validated for one person."""

HEURISTIC_MAX_PCT_BW_WK = RUNGS[-1][2]
"""No proposal's upper edge ever exceeds this (heuristic). An observed rate below the band never lifts a band past it."""

START_RUNG_BY_TIER: dict[str, str] = {"report_only": "high_mass", "brake": "typical", "full": "moderate", "unknown": "typical"}
"""`redline_rate.body_fat_tier` tier -> starting rung (heuristic). An unknown or unrecognised tier starts at `typical`:
unknowns never speed the band. A test holds every configured tier name to a key here."""

INTAKE_ADHERENCE_MIN_PCT = 60.0
"""Heuristic: intake inside the prescribed band on fewer than this share of logged days (14 d) reads as an adherence break."""

HUNGER_HIGH_DAYS_MIN = 4
"""Heuristic: high hunger on at least this many of the last 7 check-ins is a SLOW signal."""

OWNER_DECISION_SIGNALS = 3
"""Three or more SLOW signals at once surface an owner decision (maintenance phase / diet break) — never applied here."""

DRIVER_PRECEDENCE: tuple[str, ...] = ("strength", "fatigue", "recovery", "adherence", "hunger")
"""Which SLOW signal is named as the driver when several fire: the owner's priority order (muscle and strength first)."""


def _tripwire(tid: str) -> dict[str, Any]:
    from training import owner_redlines  # noqa: PLC0415 — lazy: the thresholds' one home

    return next(t for t in owner_redlines.TRIPWIRES if t["id"] == tid)


def _strength(changes: Optional[Mapping[str, float]]) -> dict[str, Any]:
    if not changes:
        return {"name": "strength", "state": "unknown", "detail": "no anchor e1RM trend passed"}
    pct = float(_tripwire("anchor_lift_strength_drop")["threshold_pct"])
    down = sorted(k for k, v in changes.items() if v is not None and float(v) <= -pct)
    severe = sorted(k for k, v in changes.items() if v is not None and float(v) <= -2 * pct)
    slow = len(down) >= 2 or bool(severe)
    detail = f"{len(down)} of {len(changes)} anchors at or below -{pct:g} % ({', '.join(down) or 'none'})"
    if severe:
        detail += f"; at or below -{2 * pct:g} %: {', '.join(severe)}"
    return {"name": "strength", "state": "slow" if slow else ("watch" if down else "ok"), "detail": detail}


def _fatigue(level: Optional[str]) -> dict[str, Any]:
    if level is None:
        return {"name": "fatigue", "state": "unknown", "detail": "no fatigue level passed"}
    state = {"high": "slow", "elevated": "watch"}.get(level, "ok")
    return {"name": "fatigue", "state": state, "detail": f"fatigue level {level}"}


def _recovery(low: Optional[bool]) -> dict[str, Any]:
    if low is None:
        return {"name": "recovery", "state": "unknown", "detail": "no recovery flag passed"}
    return {"name": "recovery", "state": "slow" if low else "ok", "detail": "recovery tripwire " + ("tripped" if low else "clear")}


def _adherence(protein_missed_7d: Optional[int], intake_adherence_pct: Optional[float]) -> dict[str, Any]:
    if protein_missed_7d is None and intake_adherence_pct is None:
        return {"name": "adherence", "state": "unknown", "detail": "no adherence signal passed"}
    need = int(_tripwire("protein_floor_missed")["threshold_days"])
    why: list[str] = []
    if protein_missed_7d is not None and protein_missed_7d >= need:
        why.append(f"protein floor missed {protein_missed_7d} of 7 days (tripwire: {need})")
    if intake_adherence_pct is not None and intake_adherence_pct < INTAKE_ADHERENCE_MIN_PCT:
        why.append(f"intake in band on {intake_adherence_pct:g} % of logged days (heuristic floor {INTAKE_ADHERENCE_MIN_PCT:g} %)")
    return {"name": "adherence", "state": "slow" if why else "ok", "detail": "; ".join(why) or "adherence holding"}


def _hunger(high_days_7d: Optional[int]) -> dict[str, Any]:
    if high_days_7d is None:
        return {"name": "hunger", "state": "unknown", "detail": "no check-in hunger passed"}
    slow = high_days_7d >= HUNGER_HIGH_DAYS_MIN
    return {"name": "hunger", "state": "slow" if slow else "ok", "detail": f"high hunger on {high_days_7d} of 7 check-ins"}


def _observed_vs(observed: Optional[float], lo: float, hi: float) -> str:
    if observed is None:
        return "unknown"
    return "below" if observed < lo else ("above" if observed > hi else "inside")


def propose_band(
    *,
    body_fat_tier: Optional[str] = None,
    observed_pct_bw_per_wk: Optional[float] = None,
    anchor_e1rm_change_pct: Optional[Mapping[str, float]] = None,
    fatigue_level: Optional[str] = None,
    recovery_low: Optional[bool] = None,
    protein_floor_days_missed_7d: Optional[int] = None,
    intake_adherence_pct: Optional[float] = None,
    hunger_high_days_7d: Optional[int] = None,
) -> dict[str, Any]:
    """The proposed loss-rate band (%BW/wk), its driver and its reasons. Pure and deterministic; see the module rules."""
    start = START_RUNG_BY_TIER.get(body_fat_tier or "unknown", "typical")
    names = [r[0] for r in RUNGS]
    signals = [
        _strength(anchor_e1rm_change_pct),
        _fatigue(fatigue_level),
        _recovery(recovery_low),
        _adherence(protein_floor_days_missed_7d, intake_adherence_pct),
        _hunger(hunger_high_days_7d),
    ]
    slow = [s["name"] for s in signals if s["state"] == "slow"]
    idx = max(0, names.index(start) - len(slow))
    name, lo, hi = RUNGS[idx]
    driver = next((d for d in DRIVER_PRECEDENCE if d in slow), "body_fat_tier")
    if slow:
        reason = f"{len(slow)} slow signal(s) ({', '.join(slow)}) moved the band down from '{start}' to '{name}'"
    else:
        reason = f"no slow signal: the band is the '{start}' rung for body-fat tier {body_fat_tier or 'unknown'}"
    return {
        "policy_version": POLICY_VERSION,
        "status": "proposal",
        "applied": False,
        "band_name": name,
        "band_pct_bw_per_wk": [lo, hi],
        "start_rung": start,
        "rungs_down": names.index(start) - idx,
        "driver": driver,
        "reason": reason,
        "signals": signals,
        "observed_pct_bw_per_wk": observed_pct_bw_per_wk,
        "observed_vs_band": _observed_vs(observed_pct_bw_per_wk, lo, hi),
        "owner_decision": (
            "several slow signals at once: whether to take a maintenance phase or diet break is the owner's call (not proposed here)"
            if len(slow) >= OWNER_DECISION_SIGNALS
            else None
        ),
        "labels": {
            "rungs": "practitioner heuristic",
            "start_tier": "redline_rate.body_fat_tier (owner_redlines rate_protein_gate.body_fat_tiers)",
            "strength_threshold": "owner_redlines anchor_lift_strength_drop.threshold_pct",
            "protein_threshold": "owner_redlines protein_floor_missed.threshold_days",
            "intake_adherence_min_pct": "heuristic",
            "hunger_high_days_min": "heuristic",
        },
    }


def dry_run(profiles: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """{profile name: `propose_band(**signals)`} over named signal profiles, in name order. Writes nothing."""
    return {name: propose_band(**dict(profiles[name])) for name in sorted(profiles)}


# ── #5861 FIX6, owner ruling 11 (2026-11-13): the ADVISORY loss-rate ceiling ──────────────────────────────────────────────
# "~1 % of current bodyweight a week as an ADVISORY upper planning reference, not an absolute rule; taper the absolute weekly
# target as weight falls; adjust for training performance, recovery, adherence and context; one unusually fast week is NOT
# automatic evidence of muscle loss." Pure, like `propose_band`; nothing on the live path applies it (the draft prints it as
# one advisory line a week, `training.live_rulings.rate_line`; `health.calorie_target` is untouched).
CEILING_PCT_BW = 1.0
"""The owner-ruled reference: ~1 % of CURRENT bodyweight a week (so the absolute ceiling tapers as weight falls)."""
SIGNAL_STEP_PCT = 0.25
"""HEURISTIC (labelled): each slow signal (strength, fatigue, recovery, adherence) lowers the ceiling by this many points of %BW."""
CEILING_FLOOR_PCT = 0.5
"""HEURISTIC (labelled): the ceiling never drops under this (the bottom of the common 0.5-1.0 %BW range) — slowing further is a
maintenance-phase decision (owner), not a ceiling."""
CEILING_TAPER = {"pct_bw": CEILING_PCT_BW, "step_pct": SIGNAL_STEP_PCT, "floor_pct": CEILING_FLOOR_PCT, "label": "heuristic"}
"""The taper as one labelled table: % of current weight (the absolute falls with it), less SIGNAL_STEP_PCT per slow signal."""
SUSTAINED_WEEKS = 3
"""HEURISTIC (labelled): weeks over the ceiling, of the last RATE_WEEKS, before a sustained trend is named. One fast week is
water, glycogen or scale noise until the trend and the strength read agree (owner ruling 11)."""
RATE_WEEKS = 4


def weekly_rates(weights_by_day: Mapping[str, Any], weeks: int = RATE_WEEKS) -> list[dict[str, float]]:
    """Weekly loss rates, newest first: each week's mean weigh-in against the week before's (weeks end at the latest weigh-in).
    A week with no weigh-in ends the series. Loss is positive."""
    from datetime import date, timedelta

    days = {date.fromisoformat(str(k)[:10]): float(v) for k, v in (weights_by_day or {}).items() if v is not None}
    if not days:
        return []
    end = max(days)

    def mean(k: int) -> float | None:
        vals = [w for d, w in days.items() if end - timedelta(days=7 * k + 6) <= d <= end - timedelta(days=7 * k)]
        return sum(vals) / len(vals) if vals else None

    out = []
    for k in range(weeks):
        now, before = mean(k), mean(k + 1)
        if now is None or before is None:
            break
        out.append({"lb_per_wk": round(before - now, 2), "pct_bw": round((before - now) / now * 100, 2), "mean_lb": round(now, 1)})
    return out


def advisory_ceiling(
    weights_by_day: Mapping[str, Any],
    *,
    pct_bw: float = CEILING_PCT_BW,
    anchor_e1rm_change_pct: Optional[Mapping[str, float]] = None,
    fatigue_level: Optional[str] = None,
    recovery_low: Optional[bool] = None,
    protein_floor_days_missed_7d: Optional[int] = None,
    intake_adherence_pct: Optional[float] = None,
    strength_regressing: Optional[bool] = None,
) -> dict[str, Any]:
    """The ADVISORY upper planning reference (ruling 11): `pct_bw` of the current 7-day mean weight, less SIGNAL_STEP_PCT per
    slow signal (floor CEILING_FLOOR_PCT) — the forward planning ceiling; the observed weekly rates against the BASE reference
    (`pct_bw`: past weeks are never judged by today's signals); and the single-fast-week guard — muscle-loss RISK is named
    only when the rate sat over the reference for SUSTAINED_WEEKS of the last RATE_WEEKS AND the strength signal is slow.
    Never a kcal number, never applied."""
    rates = weekly_rates(weights_by_day)
    strength = _strength(anchor_e1rm_change_pct)
    if anchor_e1rm_change_pct is None and strength_regressing is not None:  # the draft's read: the fatigue model's anchor trends
        strength = {"name": "strength", "state": "slow" if strength_regressing else "ok", "detail": "anchor e1RM trend (fatigue model)"}
    signals = [strength, _fatigue(fatigue_level), _recovery(recovery_low), _adherence(protein_floor_days_missed_7d, intake_adherence_pct)]
    slow = [s["name"] for s in signals if s["state"] == "slow"]
    pct = max(CEILING_FLOOR_PCT, float(pct_bw) - SIGNAL_STEP_PCT * len(slow))
    latest = [float(v) for _k, v in sorted((weights_by_day or {}).items())[-7:] if v is not None]
    current = rates[0]["mean_lb"] if rates else (sum(latest) / len(latest) if latest else None)
    ceiling = round(current * pct / 100, 2) if current else None
    over = [r for r in rates if r["pct_bw"] > float(pct_bw)]  # the PAST weeks against the base reference, never today's signals
    strength_slow = "strength" in slow
    if not rates:
        verdict = "too few weigh-ins for a weekly rate"
    elif len(over) >= SUSTAINED_WEEKS and strength_slow:
        verdict = f"over the ceiling {len(over)} of {len(rates)} weeks AND strength sliding: muscle-loss risk — slow the deficit (owner)"
    elif len(over) >= SUSTAINED_WEEKS:
        verdict = f"over the ceiling {len(over)} of {len(rates)} weeks, strength holding: watch, not a muscle-loss call"
    elif rates[0]["pct_bw"] > float(pct_bw):
        verdict = "one fast week: not evidence of muscle loss (water, glycogen, scale noise) until the trend and strength agree"
    elif rates[0]["pct_bw"] > pct:
        verdict = f"inside the {float(pct_bw):g} %BW reference; today's slow signals put the planning ceiling under last week's rate"
    else:
        verdict = "inside the ceiling"
    line = (
        f"ceiling ~{ceiling} lb/wk ({pct:g} %BW of the 7-day mean, tapering as weight falls)"
        if ceiling is not None
        else "no current weight: no ceiling stated"
    )
    if rates:
        line += f"; last week {rates[0]['lb_per_wk']:g} lb ({rates[0]['pct_bw']:g} %BW); {verdict}"
    line += f"; slow signals: {', '.join(slow)}" if slow else ""
    return {
        "policy_version": POLICY_VERSION,
        "status": "advisory",
        "applied": False,
        "ceiling_pct_bw": pct,
        "ceiling_lb_per_wk": ceiling,
        "current_lb": round(current, 1) if current else None,
        "weekly_rates": rates,
        "weeks_over": len(over),
        "muscle_loss_risk": bool(rates) and len(over) >= SUSTAINED_WEEKS and strength_slow,
        "slow_signals": slow,
        "signals": signals,
        "verdict": verdict,
        "line": line,
        "labels": {"ceiling": "owner-ruled advisory reference (ruling 11)", "step/floor/sustained": "heuristic"},
    }
