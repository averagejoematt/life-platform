"""live_rulings.py — the owner's rulings of 2026-11-13 on the decision register, as LIVE-only programming rules (#5861 FIX6).

Configuration, not activation: every rule here runs only past `selection_engine.mode() == "live"` (the library is `proposed`
today, so nothing here runs — tests/test_no_live_change_5861_l6.py poisons each entry point and pins the proposed digests).
The rulings' values are library-carried (`programming_settings`, written by `deploy/build_exercise_library.py`
OWNER_RULED_SETTINGS) and their code defaults are `SETTINGS_DEFAULTS` below plus the earlier rounds' dicts.

  1. THE LEAD LIFT (`lead_lift`, ruling 5). Heavy squat and heavy deadlift share the lower-heavy morning (#5694), but both are
     never maximal in one session: one LEADS at the session's top effort and the other is capped one RPE band lower
     (LEAD_LIFT). The lead alternates by ISO week (`lead_lift_rule: alternate_weekly`): even weeks the squat leads, odd weeks
     the deadlift. Why alternation, not a fixed order: each lift gets a top-effort exposure every other week (the
     strength-preservation signal stays readable for both), the pairing stays, and the second lift's fatigue cost falls on
     the week it is not the lead. The deadlift's shape (top set + one back-off, ruling 5) is `live_shape.deadlift_shape`.
  2. PRIORITY BY STIMULUS AND PERFORMANCE (`stimulus_gate`, ruling 9). A priority muscle's ADDED isolation slot (the
     quadriceps slot) stays only when the stimulus and the performance both ask for it: when the week already holds the
     muscle at or over MEV AND its anchor is progressing, nothing is added (more volume is not the goal; a progressing lift
     at MEV is a working stimulus). A stalled, regressing or unread anchor, or a week under MEV, keeps the low-fatigue slot.
  3. THE SHORT WEEK'S ARMS AND SHOULDERS (`short_week_floor`, ruling 3). When a week drops shoulders+arms, the shoulders,
     biceps and triceps are COUNTED (direct sets 1.0, indirect 0.5 — the fatigue model's convention) over the sessions left;
     a muscle under its MEV takes sets on its isolation slots in those sessions until it reaches MEV (ARMS_FLOOR).
  4. PURPOSEFUL CARDIO (`purposeful_cardio`, ruling 4). Under `cardio_purpose_only` a gym cardio block exists only when it
     serves a named purpose — the week's conditioning dose on the conditioning host. No easy block fills a slot or a time
     gap; easy aerobic is the walking outside the gym, tracked apart (`cardio_model.recorded_aerobic`). Under the shared cap
     (ruling 1) the host's cardio room comes from supersets and from sets OVER a muscle's MAV only, never from strength work a
     muscle needs (`live_week.make_cardio_room`, `cardio_room_takes: over_mav_only`).
  5. EVIDENCE AND COMPLETENESS, VISIBLE (`evidence_line`, ruling 16). Each served movement's rationale line names its
     objective tier, its evidence confidence and its data completeness (the rubric inputs known / read), with `provisional`
     spelled out — missing information is never shown as proof of suitability.
  6. THE LOSS-RATE CEILING, ADVISORY (`rate_line`, ruling 11): `health.rate_policy.advisory_ceiling` once a week (the
     upper-heavy morning), never applied to a kcal target.

Every threshold is a labelled HEURISTIC (ruling 18), registered with the metric that should re-tune it at a block retro in
`HEURISTIC_HOOKS` (docs/coaching/ENGINE_ARCHITECTURE.md "Block-retro hooks")."""

from __future__ import annotations

from datetime import date
from typing import Any

ISSUE = "#5861"
HEURISTIC = "heuristic"

SETTINGS_DEFAULTS: dict[str, Any] = {
    "cardio_purpose_only": True,
    "cardio_room_takes": "over_mav_only",
    "lead_lift_rule": "alternate_weekly",
    "press_sets": 3,
    "priority_add_rule": "stimulus_and_performance",
    "rate_ceiling_pct_bw": 1.0,
}
"""The owner's rulings of 2026-11-13 that had no setting before (OWNER DECISIONS, ruled): `cardio_purpose_only` True (ruling
4) | False (the fifth round's easy-gap block); `cardio_room_takes` `over_mav_only` (ruling 1: no strength work a muscle needs is
cut for cardio) | `as_fix5`; `lead_lift_rule` `alternate_weekly` (ruling 5) | `off`; `press_sets` 3 (ruling 6: 2-3 sets; 1 = the
charter's one set); `priority_add_rule` `stimulus_and_performance` (ruling 9) | `volume`; `rate_ceiling_pct_bw` 1.0 (ruling 11,
advisory only)."""

LEAD_LIFT: dict[str, dict[str, Any]] = {
    "second_band": {
        "value": [7, 8],
        "label": HEURISTIC,
        "basis": "the lift that does not lead the heavy lower day is capped one RPE band under the session's 8-9 (owner ruling 5: "
        "never both maximal in one session); 7-8 keeps 2-3 reps in reserve — a strength-maintaining dose, not a test",
    },
}
ARMS_FLOOR: dict[str, dict[str, Any]] = {
    "muscles": {
        "value": ["shoulders", "biceps", "triceps"],
        "label": HEURISTIC,
        "basis": "the muscles the shoulders+arms morning trains directly (owner ruling 3): a week that drops it holds each at MEV, "
        "direct + indirect (secondary sets count half)",
    },
    "add_per_slot": {
        "value": 2,
        "label": HEURISTIC,
        "basis": "a remaining isolation slot takes at most two extra sets for the floor (a slot of 4+ sets is junk volume)",
    },
}
PRIORITY_ADD: dict[str, dict[str, Any]] = {
    "progressing": {
        "value": "progressing",
        "label": HEURISTIC,
        "basis": "a priority muscle at or over MEV whose anchor's e1RM trend reads `progressing` (fatigue_model.movement_signals) "
        "is getting a working stimulus: no slot is added (owner ruling 9, stimulus and performance, not volume maximisation)",
    },
}

ANCHOR_OF = {"quadriceps": ("squat",)}
"""Priority muscle -> the anchor patterns whose trend is its performance read."""


def _settings(lib: dict[str, Any] | None = None) -> dict[str, Any]:
    from training import live_program, selection_engine as se

    return live_program.settings(lib if lib is not None else se.load_library_failsoft())


# ── 1. the lead lift ──────────────────────────────────────────────────────────
def lead_of(target_date: str) -> str:
    """`squat` on an even ISO week, `hinge` on an odd one (`lead_lift_rule: alternate_weekly`)."""
    try:
        week = date.fromisoformat(str(target_date)[:10]).isocalendar()[1]
    except ValueError:
        return "squat"
    return "squat" if week % 2 == 0 else "hinge"


def lead_lift(rx: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    """IN PLACE, the lower-heavy morning holding both a squat and a hinge anchor: the non-lead lift is capped at LEAD_LIFT
    second_band. Returns the rationale lines."""
    if rx.get("session_role") != "lower_heavy" or _settings(ctx.get("lib")).get("lead_lift_rule") != "alternate_weekly":
        return []
    anchors = {e.get("pattern"): e for e in rx["exposures"] if e.get("kind") == "anchor" and e.get("pattern") in ("squat", "hinge")}
    if len(anchors) < 2:
        return []
    lead = lead_of(str(ctx.get("target_date") or ""))
    second = anchors["hinge" if lead == "squat" else "squat"]
    lo, hi = (int(x) for x in LEAD_LIFT["second_band"]["value"])
    second["live_effort"] = min(hi, int(second.get("live_effort") or 99))
    second["live_effort_band"] = [lo, hi]
    second["live_lead"] = "second"
    anchors[lead]["live_lead"] = "lead"
    names = {"squat": "the squat", "hinge": "the deadlift"}
    other = "hinge" if lead == "squat" else "squat"
    return [
        f"lead lift (live): {names[lead]} leads this week at the session's effort, {names[other]} capped at RPE {lo}-{hi} — never "
        f"both maximal in one session; the lead alternates by ISO week (LEAD_LIFT, heuristic; lead_lift_rule=alternate_weekly)"
    ]


# ── 2. priority by stimulus and performance ──────────────────────────────────
def stimulus_gate(rx: dict[str, Any], ctx: dict[str, Any], trends: dict[str, str]) -> list[str]:
    """IN PLACE: an added priority slot (`live_added == "quad_slot"`) leaves when the week already holds its muscle at or over
    MEV AND the muscle's anchor is progressing (`PRIORITY_ADD`). Returns the rationale lines."""
    if _settings(ctx.get("lib")).get("priority_add_rule") != "stimulus_and_performance":
        return []
    added = [e for e in rx["exposures"] if e.get("live_added") == "quad_slot"]
    if not added:
        return []
    from training import block_model

    plan_ = ctx.get("allocation") or {}
    mev = float(((block_model.load_landmarks() or {}).get("quadriceps") or {}).get("MEV") or 0)
    before = float((plan_.get("before") or {}).get("quadriceps") or 0)
    read = anchor_trends(ctx, trends, "quadriceps")
    progressing = bool(read) and all(t == PRIORITY_ADD["progressing"]["value"] for t in read.values())
    if before < mev or not progressing:
        why = "under MEV" if before < mev else f"its anchor reads {', '.join(sorted(set(read.values()))) or 'unread'}"
        return [f"priority (live): the quadriceps slot stays — {why} (priority_add_rule=stimulus_and_performance)"]
    rx["exposures"] = [e for e in rx["exposures"] if e not in added]
    return [
        f"priority (live): no quadriceps slot — the week holds {before:g} sets (MEV {mev:g}) and {', '.join(sorted(read))} is "
        "progressing: the stimulus works, more volume is not the goal (PRIORITY_ADD, heuristic; priority_add_rule=stimulus_and_performance)"
    ]


def anchor_trends(ctx: dict[str, Any], trends: dict[str, str], muscle: str) -> dict[str, str]:
    """{anchor title: trend} for the muscle's anchor patterns across the program templates, as `fatigue_model` read them."""
    from training import program_structure as ps, selection_engine as se

    lib, catalog = ctx.get("lib") or {}, ctx.get("catalog") or {}
    idx = ctx.get("idx") or se.key_index(lib, catalog)
    out: dict[str, str] = {}
    for role in ps.SPLIT_ROLES:
        for e in ps.session_prescription_for_role(role, catalog_movements=catalog)["exposures"]:
            if e.get("kind") != "anchor" or e.get("pattern") not in ANCHOR_OF.get(muscle, ()):
                continue
            entry = (lib.get("movements") or {}).get(idx["to_lib"].get(str(e.get("movement_key"))) or "") or {}
            tid = str(entry.get("template_id") or "").upper()
            if tid in trends:
                out[str(entry.get("title") or e.get("movement_key"))] = str(trends[tid])
    return out


# ── 3. the short week's arms and shoulders ───────────────────────────────────
def short_week_floor(env: dict[str, Any], adds: list[dict[str, Any]]) -> list[str]:
    """IN PLACE on env["deltas"] (`live_balance.allocation_plan`, only when a role is skipped): each ARMS_FLOOR muscle under its
    MEV over the sessions left takes sets on its isolation slots there (at most add_per_slot each, earliest slot first) until
    it reaches MEV. Returns the plan lines."""
    from training import live_balance as lb

    rows, deltas, marks = env["rows"], env["deltas"], env["marks"]
    cap = int(ARMS_FLOOR["add_per_slot"]["value"])
    lines = []
    for m in ARMS_FLOOR["muscles"]["value"]:
        lm = marks.get(m) or {}
        if not lm:
            continue
        for r in [r for r in rows if r["kind"] == "accessory" and r["muscle"] == m and r["intensity"] != "carry"]:
            have = lb._sum(rows, deltas)[m] + sum(a["sets"] for a in adds if a["muscle"] == m)
            if have >= float(lm["MEV"]):
                break
            k = (r["role"], str(r["slot"]))
            give = min(cap - max(deltas.get(k, 0), 0), int(-(-(float(lm["MEV"]) - have) // 1)))
            if give <= 0:
                continue
            deltas[k] = deltas.get(k, 0) + give
            lines.append(f"{r['role']}.{r['slot']} +{give} set(s): {m} held at MEV {lm['MEV']} in the short week (ARMS_FLOOR, heuristic)")
    return lines


def arms_count(after: dict[str, float], marks: dict[str, Any]) -> list[str]:
    """The counted check behind ruling 3: `muscle sets/MEV` for each ARMS_FLOOR muscle (the plan line on a short week)."""
    return [f"{m} {float(after.get(m) or 0):g}/{(marks.get(m) or {}).get('MEV')}" for m in ARMS_FLOOR["muscles"]["value"]]


def press_trade(rows: list[dict[str, Any]], lib: dict[str, Any] | None) -> dict[tuple[str, str], int]:
    """The week's opening deltas (`live_balance.allocation_plan`): the overhead press's sets above the template's one (`press_sets`,
    ruling 6) come off the LATERAL-raise slots first — one set at a time, the shoulders+arms slot first, never under two sets —
    so the trade lands on redundant lateral-delt work, not the rear delts. Any shoulder surplus left is the allocation's."""
    from training.live_balance import ALLOCATION

    press = next((r for r in rows if r["role"] == "shoulders_arms" and r["kind"] == "anchor" and "press" in str(r["key"] or "")), None)
    extra = (int(press["sets"]) - 1) if press else 0
    floor = int(ALLOCATION["over_mav_floor"]["value"])
    laterals = [r for r in rows if r["kind"] == "accessory" and "lateral_raise" in str(r["key"] or "")]
    laterals.sort(key=lambda r: r["role"] != "shoulders_arms")
    deltas: dict[tuple[str, str], int] = {}
    while extra > 0:
        open_ = [r for r in laterals if r["sets"] + deltas.get((r["role"], str(r["slot"])), 0) > floor]
        if not open_:
            break
        for r in open_:
            if extra <= 0:
                break
            k = (r["role"], str(r["slot"]))
            deltas[k] = deltas.get(k, 0) - 1
            extra -= 1
    return deltas


# ── 4. purposeful cardio ─────────────────────────────────────────────────────
def purposeful_cardio(kind: str, live: dict[str, Any], hard_kinds: tuple[str, ...]) -> tuple[bool, list[str]]:
    """(keep, lines) under `cardio_purpose_only`: a hard block on the conditioning host keeps its purpose (the week's
    conditioning dose); any other block — an easy kind, or a hard one turned easy — is not served. (True, []) when the setting
    is off (the fifth round's easy-gap rules then decide)."""
    if not (live.get("settings") or {}).get("cardio_purpose_only"):
        return True, []
    if kind in hard_kinds:
        return True, [f"cardio (live): {kind} — purpose: the week's conditioning dose (cardio_purpose_only)"]
    aer = live.get("aerobic") or {}
    tracked = aer.get("line") or "walking outside the gym is tracked apart"
    return False, [f"cardio (live): no {kind} block — no named purpose today; easy aerobic is the walking outside the gym ({tracked})"]


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
    "live_rulings.LEAD_LIFT.second_band": "the non-lead lift's e1RM trend over the block (held = right; sliding = raise the cap a half band)",
    "live_rulings.ARMS_FLOOR.add_per_slot": "short-week arm/shoulder e1RM and the next normal week's first-set reps",
    "live_rulings.PRIORITY_ADD.progressing": "quadriceps anchor e1RM slope in weeks with vs without the added slot",
    "cardio_model.MODERATE_METS": "Apple workout intensity vs the session RPE he logged, per modality",
    "cardio_model.CADENCE_MODERATE_SPM": "his own walking cadence at a logged talk-test / RPE (the ~100 spm figure is a population heuristic)",
    "cardio_model.RPE_MODERATE": "logged cardio RPE vs the talk test he notes",
    "rate_policy.CEILING_TAPER": "4-week loss rate vs anchor e1RM and lean-mass (DEXA) change at each block retro",
    "rate_policy.SUSTAINED_WEEKS": "weeks above the ceiling that preceded an anchor decline, across blocks",
    "rate_policy.SIGNAL_STEP_PCT": "loss rate in weeks with 1, 2, 3 slow signals vs strength the following week",
    "live_program.LOAD_POLICY": "e1RM trend after a hold / step down vs after a step up",
    "live_program.STALL_RULE": "e1RM over the 3 exposures after a stall reset",
    "live_program.PAIN_RULE": "pain-note recurrence within 2 sessions of a reduce / avoid",
    "live_program.DELOAD_SHAPE": "readiness and first-set reps the week after a deload",
    "live_program.TRUNK_FLOOR": "trunk-drill progression and back-discomfort notes",
    "live_balance.ALLOCATION": "weekly sets per muscle vs that muscle's e1RM / rep PRs",
    "live_balance.ADHERENCE_DIP": "sessions completed in the 2 weeks after a short-week response",
    "live_shape.VOLUME": "priority-muscle sets vs their anchor trend",
    "live_shape.QUAD_SLOT": "quadriceps anchor trend with the slot served",
    "live_shape.WALK_PROMPT": "walks logged after a prompt",
    "live_week.CARDIO_ROOM": "conditioning-block minutes delivered vs lifting minutes lost",
    "live_week.NOVEL_START": "RPE logged on a new movement's first 3 exposures",
    "fatigue_model.THRESHOLDS": "strain calls vs the next session's first-set reps / RPE",
    "quality_rubric.NEUTRAL": "how often a reviewed input moved a provisional row's tier",
}
"""Ruling 18: every labelled heuristic table the live engine reads -> the metric that should re-tune it at a block retro. The
doc's "Block-retro hooks" table lists each key (tests/test_owner_rulings_5861.py holds the doc and this dict to each other, and
each key to a real labelled table)."""
