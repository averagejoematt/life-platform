"""live_rulings.py — the owner's rulings that remain their own rules (#5861). LIVE only; their values are library-carried
through the ONE settings table (`live_settings`).

  1. THE HEAVY LOWER MORNING (`lead_lift`, ruling 5): squat and deadlift share it but are never both maximal — the squat always
     leads at the session's effort, the deadlift is a top set + one back-off at its `effort_targets` RPE (fix round 11: the ISO-week
     alternation, the lead by state and the second-lift band are gone with the ratchet they made).
  2. PURPOSEFUL CARDIO (`purpose_line`, ruling 4): the one gym block is the week's conditioning dose; it carries its reason.
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
    """The mornings that may hold HARD conditioning this week: the host, plus SECOND_HOST at `hard_conditioning_doses` 2; none at
    0 (fix round 12: the owner's explicit trade — the dose's reserved minutes go back to lifting)."""
    n = doses(lib)
    return ([host] if n >= 1 else []) + ([SECOND_HOST] if n >= 2 and SECOND_HOST != host else [])


def doses(lib: dict[str, Any] | None = None) -> int:
    """`hard_conditioning_doses` (unset reads 1, the ruled default; 0 is a choice, not a missing value)."""
    n = _settings(lib).get("hard_conditioning_doses")
    return 1 if n is None else int(n)


def _settings(lib: dict[str, Any] | None = None) -> dict[str, Any]:
    from training import live_settings, selection_engine as se

    return live_settings.settings(lib if lib is not None else se.load_library_failsoft())


# ── 1. the lead lift ──────────────────────────────────────────────────────────
def lead_lift(rx: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    """IN PLACE, the lower-heavy morning holding both a spine-loading squat and a hinge anchor (owner ruling 5, fix round 11 — the
    tenth red team's simpler rule): the SQUAT always leads at the session's effort; the deadlift runs its top set + one back-off
    (`live_shape.deadlift_shape`) capped at its `effort_targets` row. No week-by-week alternation, no lead by state: each is an ordinary
    lift of the one load model (`live_load`), so a capped deadlift steps up after an easy top set and neither reads a stale lead
    day. A squat already capped (a pain flag) leaves both under the top effort — never both maximal. Returns the line."""
    if rx.get("session_role") != "lower_heavy":
        return []
    from training import live_balance, live_settings

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
    cap = int(live_settings.value("effort_targets")["deadlift"][0])
    dl = anchors["hinge"]
    dl["live_effort"] = min(cap, int(dl.get("live_effort") or 99))
    return [
        f"heavy lower (live): the squat leads at the session's effort; the deadlift is a top set + one back-off at RPE <= {cap} "
        "— never both maximal in one session (owner ruling 5; effort_targets, heuristic)"
    ]


def _lib_entry(e: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    idx, movs = ctx.get("idx") or {}, (ctx.get("lib") or {}).get("movements") or {}
    return movs.get((idx.get("to_lib") or {}).get(str(e.get("movement_key"))) or "") or {}


# ── 2. priority by stimulus and performance ──────────────────────────────────


# ── 3. the short week's arms and shoulders ───────────────────────────────────


# ── 4. purposeful cardio ─────────────────────────────────────────────────────
def purpose_line(kind: str) -> list[str]:
    """The served conditioning block's recorded reason (owner ruling 4: no block without one): the week's conditioning dose."""
    return [f"cardio (live): {kind} — purpose: the week's conditioning dose (hard_conditioning_doses)"]


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
