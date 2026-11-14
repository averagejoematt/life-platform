"""live_rulings.py — the owner's rulings that remain their own rules (#5861). LIVE only; their values are library-carried
through the ONE settings table (`live_settings`).

  1. THE LEAD LIFT (`lead_lift`, `lead_of`, `lead_blocked`; ruling 5): squat and deadlift share the heavy lower morning but are
     never both maximal — one leads at the session's top effort, the other runs at `second_lift_band` (RPE 7-8). The lead
     alternates by ISO week; a lift that is cut, regressing or pain-capped cannot lead (the lead by state).
  2. PURPOSEFUL CARDIO (`purposeful_cardio`, ruling 4): a gym block only for a named purpose — the week's conditioning dose, or the
     RECORD's aerobic gap.
  3. EVIDENCE AND COMPLETENESS, VISIBLE (`evidence_line`, ruling 16).
  4. THE LOSS-RATE CEILING, ADVISORY (`rate_line`, ruling 11), never applied to a kcal target.
  5. The hard-conditioning hosts (`conditioning_hosts`, `hard_conditioning_doses`).

Ruling 18: every labelled table is registered with its block-retro metric in `HEURISTIC_HOOKS`."""

from __future__ import annotations

from typing import Any

ISSUE = "#5861"
HEURISTIC = "heuristic"

SECOND_HOST = "upper_volume"
"""The second hard dose's morning under `hard_conditioning_doses` 2: never the heavy lower day nor the session before it (the
shoulders+arms host is the first)."""


def conditioning_hosts(host: str, lib: dict[str, Any] | None = None) -> list[str]:
    """The mornings that may hold HARD conditioning this week: the host, plus SECOND_HOST at `hard_conditioning_doses` 2."""
    n = int(_settings(lib).get("hard_conditioning_doses") or 1)
    return [host] + ([SECOND_HOST] if n >= 2 and SECOND_HOST != host else [])


def _settings(lib: dict[str, Any] | None = None) -> dict[str, Any]:
    from training import live_settings, selection_engine as se

    return live_settings.settings(lib if lib is not None else se.load_library_failsoft())


# ── 1. the lead lift ──────────────────────────────────────────────────────────
def lead_of(target_date: str) -> str:
    """`squat` on an even ISO week, `hinge` on an odd one (`lead_lift_rule: alternate_weekly`)."""
    from common.pacific_time import parse_day_key

    d = parse_day_key(str(target_date)[:10])
    if d is None:
        return "squat"
    return "squat" if d.isocalendar()[1] % 2 == 0 else "hinge"


def lead_blocked(e: dict[str, Any], trend: str | None) -> str | None:
    """#5861 FIX7 (sixth red team: a −10% reset 'led' while the squat was capped — no top-effort lift on the heavy day): why this
    anchor cannot lead today — a load cut or reset on it (`live_load` pct), a rebuild after a reset, a regressing trend, a held
    retreat, or a pain/discomfort effort cap at or under RPE 7 — else None."""
    if e.get("live_stop"):  # fix round 10: a pain-touched lift (held, stop line) never leads
        return str((e.get("live_load") or {}).get("why") or "pain flag")
    if trend == "regressing":
        return "regressing"
    if e.get("live_effort") is not None and int(e["live_effort"]) <= 7:
        return "effort capped"
    return None


def lead_lift(rx: dict[str, Any], ctx: dict[str, Any], trends: dict[str, str] | None = None) -> list[str]:
    """IN PLACE, the lower-heavy morning holding both a squat and a hinge anchor: the non-lead lift is capped at LEAD_LIFT
    second_band. #5861 FIX7: the lead is chosen by STATE — a lift that is cut, reset, rebuilding, regressing or pain-capped
    (`lead_blocked`) cannot lead, so the other leads at the session's RPE 8-9; the ISO-week alternation is the tie-break when
    both or neither are blocked. Returns the rationale lines."""
    if rx.get("session_role") != "lower_heavy":
        return []
    from training import live_balance

    idx, movs = ctx.get("idx") or {}, (ctx.get("lib") or {}).get("movements") or {}
    anchors = {
        e.get("pattern"): e
        for e in rx["exposures"]
        if e.get("kind") == "anchor"
        and e.get("pattern") in ("squat", "hinge")
        and live_balance.spine_loading(movs.get((idx.get("to_lib") or {}).get(str(e.get("movement_key"))) or ""))
    }
    if len(anchors) < 2:  # a swapped-out deadlift (a hip thrust under discomfort) is not a second maximal lift
        return []
    lead = lead_of(str(ctx.get("target_date") or ""))
    tid = {p: str(_lib_entry(e, ctx).get("template_id") or "").upper() for p, e in anchors.items()}
    blocked = {p: lead_blocked(e, (trends or {}).get(tid[p])) for p, e in anchors.items()}
    by_state = None
    if bool(blocked["squat"]) != bool(blocked["hinge"]):  # exactly one cannot lead: the other leads, whatever the week
        by_state = "hinge" if blocked["squat"] else "squat"
        lead = by_state
    second = anchors["hinge" if lead == "squat" else "squat"]
    from training import live_settings

    lo, hi = (int(x) for x in live_settings.value("second_lift_band"))
    second["live_effort"] = min(hi, int(second.get("live_effort") or 99))
    second["live_effort_band"] = [lo, hi]
    second["live_lead"] = "second"
    anchors[lead]["live_lead"] = "lead"
    names = {"squat": "the squat", "hinge": "the deadlift"}
    other = "hinge" if lead == "squat" else "squat"
    how = (
        f"by state: {names[other]} is {blocked[other]}, so {names[lead]} carries the top effort"
        if by_state
        else "the lead alternates by ISO week (the tie-break)"
    )
    return [
        f"lead lift (live): {names[lead]} leads this week at the session's full effort, {names[other]} capped at RPE {lo}-{hi} — "
        f"never both maximal in one session; {how} (second_lift_band, heuristic)"
    ]


def _lib_entry(e: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    idx, movs = ctx.get("idx") or {}, (ctx.get("lib") or {}).get("movements") or {}
    return movs.get((idx.get("to_lib") or {}).get(str(e.get("movement_key"))) or "") or {}


# ── 2. priority by stimulus and performance ──────────────────────────────────


# ── 3. the short week's arms and shoulders ───────────────────────────────────


# ── 4. purposeful cardio ─────────────────────────────────────────────────────
def purposeful_cardio(kind: str, live: dict[str, Any], hard_kinds: tuple[str, ...]) -> tuple[bool, list[str]]:
    """(keep, lines) under `cardio_purpose_only`: a hard block on the conditioning host keeps its purpose (the week's
    conditioning dose); any other block — an easy kind, or a hard one turned easy — is not served. (True, []) when the setting
    is off (the fifth round's easy-gap rules then decide)."""
    if kind in hard_kinds:
        return True, [f"cardio (live): {kind} — purpose: the week's conditioning dose (cardio_purpose_only)"]
    from training import live_shape  # #5861 FIX7: the RECORD names the purpose — a week short of its aerobic floor

    aer = live.get("aerobic") or {}
    gap = live_shape.aerobic_gap(live)
    if gap is not None and gap >= int(live_shape.WALK_PROMPT["min_minutes"]["value"]):
        return True, [
            f"cardio (live): {kind} — purpose: the week's aerobic floor, ~{gap} min short after the recorded, credited minutes "
            "(cardio_purpose_only; the record names the purpose)"
        ]
    tracked = aer.get("line") or "walking outside the gym is tracked apart"
    why = "the recorded aerobic minutes cover the week" if gap is not None else "no aerobic record read — nothing is assumed"
    if gap is None and live_shape.intensity_unknown(aer):  # FIX8 (ruling 12): steps reported, intensity unknown, no deficit
        why = f"steps ~{aer.get('steps_per_day')}/day, intensity unknown — reported, not a deficit"
    return False, [f"cardio (live): no {kind} block — no named purpose today: {why} ({tracked})"]


# ── 5. evidence and completeness, visible ───────────────────────────────────
def evidence_line(rx: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    """One compact rationale line for the session: each served movement's tier on its slot's objective, evidence confidence
    and data completeness (`quality_rubric.completeness`); `provisional` spelled out. Read only — nothing ranks on it."""
    from training import quality_rubric as qr

    lib, idx = ctx.get("lib") or {}, ctx.get("idx") or {}
    parts = []
    for e in rx.get("exposures") or []:
        lid = (idx.get("to_lib") or {}).get(str(e.get("movement_key")))
        entry = (lib.get("movements") or {}).get(lid or "") or {}
        if not entry:
            continue
        objective = "strength" if e.get("kind") == "anchor" and e.get("intensity") == "heavy" else "hypertrophy"
        tier, conf, prov = qr.served_rating(entry, objective)
        for other in ("functional", "conditioning", "mobility", "strength"):  # a trunk drill, a carry: the objective it is rated on
            if tier is None:
                objective = other
                tier, conf, prov = qr.served_rating(entry, other)
        known, read = qr.completeness(entry)
        parts.append(
            f"{entry.get('title') or lid} {objective} {tier or '-'}{' (provisional)' if prov else ''}, {conf}, data {known}/{read}"
        )
    return [f"evidence (live): {'; '.join(parts)}"] if parts else []


# ── 6. the loss-rate ceiling, advisory ───────────────────────────────────────
def rate_line(inputs: Any, fatigue: dict[str, Any] | None, role: str | None, lib: dict[str, Any] | None = None) -> str | None:
    """Once a week (the upper-heavy morning): `rate_policy.advisory_ceiling` over the weigh-ins the cron read, as an advisory
    line. Never applied (`calorie_target` is untouched). None on any other morning, or with no weigh-in read."""
    if role != "upper_heavy":
        return None
    from health import rate_policy

    weights = getattr(inputs, "weights_by_day", None) or {}
    if not weights:
        return "loss rate (advisory, not applied): no weigh-ins read — no ceiling stated"
    fat = (fatigue or {}).get("fatigue_level")
    sleep = getattr(inputs, "sleep_hours", None)
    out = rate_policy.advisory_ceiling(
        weights,
        pct_bw=float(_settings(lib).get("rate_ceiling_pct_bw") or 1.0),
        strength_regressing="strength" in ((fatigue or {}).get("strain_signals") or []),
        fatigue_level=fat,
        recovery_low=(sleep is not None and float(sleep) < 6.5) or None,
    )
    return f"loss rate (advisory, not applied): {out['line']}"


# ── ruling 18: every heuristic, with the metric a block retro re-tunes it on ──
HEURISTIC_HOOKS: dict[str, str] = {
    "live_settings.HEURISTICS": 'each row\'s own "Re-tuned on" column above',
    "cardio_model.MODERATE_METS": "Apple workout intensity vs the session RPE he logged, per modality",
    "cardio_model.CADENCE_MODERATE_SPM": "his own walking cadence at a logged talk-test / RPE (the ~100 spm figure is a population heuristic)",
    "cardio_model.RPE_MODERATE": "logged cardio RPE vs the talk test he notes",
    "rate_policy.CEILING_TAPER": "4-week loss rate vs anchor e1RM and lean-mass (DEXA) change at each block retro",
    "rate_policy.SUSTAINED_WEEKS": "weeks above the ceiling that preceded an anchor decline, across blocks",
    "rate_policy.SIGNAL_STEP_PCT": "loss rate in weeks with 1, 2, 3 slow signals vs strength the following week",
    "live_program.PAIN_RULE": "pain-note recurrence within 2 sessions of a hold / route, and the flagged muscle's hard sets",
    "live_program.DELOAD_SHAPE": "readiness and first-set reps the week after a deload",
    "live_program.STACK_RULE": "low-back discomfort notes and squat/hinge e1RM in weeks at the cap",
    "live_shape.WALK_PROMPT": "walks logged after a prompt",
    "fatigue_model.THRESHOLDS": "strain calls vs the next session's first-set reps / RPE",
    "quality_rubric.NEUTRAL": "how often a reviewed input moved a provisional row's tier",
}
"""Ruling 18: every labelled heuristic table the live engine reads -> the metric that should re-tune it at a block retro (fix
round 9: the consolidated rules' rows live in `live_settings.HEURISTICS`, each with its own metric).
Provenance (owner rulings 2026-11-13, FIX7 follow-up): `hard_conditioning_doses` = 1 is ruled (a setting, re-tuned on
the conditioning-block minutes delivered), and ruling 17 is clarified — glute stretch credit only for genuinely lengthened loading
(`quality_rubric.STRETCH_CAPS` empty, rubric 3.5.0), not a heuristic and so not a hook. The
doc's "Block-retro hooks" table lists each key (tests/test_owner_rulings_5861.py holds the doc and this dict to each other, and
each key to a real labelled table)."""
