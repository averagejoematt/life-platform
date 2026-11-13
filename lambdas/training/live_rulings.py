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
     at MEV is a working stimulus). A stalled, regressing or unread anchor, or a week under MEV, keeps the low-fatigue slot —
     and so does a week whose squat is the SECOND lift (the lead-lift rule caps it at RPE 7-8: less stimulus, so the
     low-fatigue quadriceps work stands).
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
    "hard_conditioning_doses": 1,
}
"""The owner's rulings of 2026-11-13 that had no setting before (OWNER DECISIONS, ruled): `cardio_purpose_only` True (ruling
4) | False (the fifth round's easy-gap block); `cardio_room_takes` `over_mav_only` (ruling 1: no strength work a muscle needs is
cut for cardio) | `as_fix5`; `lead_lift_rule` `alternate_weekly` (ruling 5) | `off`; `press_sets` 3 (ruling 6: 2-3 sets; 1 = the
charter's one set); `priority_add_rule` `stimulus_and_performance` (ruling 9) | `volume`; `rate_ceiling_pct_bw` 1.0 (ruling 11,
advisory only); `hard_conditioning_doses` 1 (#5861 FIX7, owner ruling 2026-11-13: the shared cap's one hard dose a week, kept a setting; 2 adds a second
hard block on `SECOND_HOST`, never the heavy lower day or the session before it — the sixth red team's option, not the default)."""
SECOND_HOST = "upper_volume"
"""The second hard dose's morning under `hard_conditioning_doses` 2: never the heavy lower day nor the session before it (the
shoulders+arms host is the first)."""


def conditioning_hosts(host: str, lib: dict[str, Any] | None = None) -> list[str]:
    """The mornings that may hold HARD conditioning this week: the host, plus SECOND_HOST at `hard_conditioning_doses` 2."""
    n = int(_settings(lib).get("hard_conditioning_doses") or 1)
    return [host] + ([SECOND_HOST] if n >= 2 and SECOND_HOST != host else [])


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
        "basis": "the muscles the arms-and-delts day trains directly (owner ruling 3): a week that drops it holds each at MEV, "
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

ANCHOR_OF = {"quadriceps": ("squat",), "chest": ("bench",)}
"""Priority muscle -> the anchor patterns whose trend is its performance read."""


def _settings(lib: dict[str, Any] | None = None) -> dict[str, Any]:
    from training import live_program, selection_engine as se

    return live_program.settings(lib if lib is not None else se.load_library_failsoft())


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
    if (e.get("live_load") or {}).get("pct"):
        return str((e.get("live_load") or {}).get("why") or "cut")
    if e.get("live_rebuild") or trend == "rebuilding":  # a load drop with no reset scheme (`returning`) only defers the stall call
        return "rebuilding after a reset"
    if trend == "regressing":
        return "regressing"
    if e.get("live_retreated"):
        return "held after a cut"
    if e.get("live_effort") is not None and int(e["live_effort"]) <= 7:
        return "effort capped"
    return None


def lead_lift(rx: dict[str, Any], ctx: dict[str, Any], trends: dict[str, str] | None = None) -> list[str]:
    """IN PLACE, the lower-heavy morning holding both a squat and a hinge anchor: the non-lead lift is capped at LEAD_LIFT
    second_band. #5861 FIX7: the lead is chosen by STATE — a lift that is cut, reset, rebuilding, regressing or pain-capped
    (`lead_blocked`) cannot lead, so the other leads at the session's RPE 8-9; the ISO-week alternation is the tie-break when
    both or neither are blocked. Returns the rationale lines."""
    if rx.get("session_role") != "lower_heavy" or _settings(ctx.get("lib")).get("lead_lift_rule") != "alternate_weekly":
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
    lo, hi = (int(x) for x in LEAD_LIFT["second_band"]["value"])
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
        f"lead lift (live): {names[lead]} leads this week at the session's effort (RPE 8-9), {names[other]} capped at RPE {lo}-{hi} — "
        f"never both maximal in one session; {how} (LEAD_LIFT, heuristic; lead_lift_rule=alternate_weekly)"
    ]


def _lib_entry(e: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    idx, movs = ctx.get("idx") or {}, (ctx.get("lib") or {}).get("movements") or {}
    return movs.get((idx.get("to_lib") or {}).get(str(e.get("movement_key"))) or "") or {}


# ── 2. priority by stimulus and performance ──────────────────────────────────
def stimulus_gate(rx: dict[str, Any], ctx: dict[str, Any], trends: dict[str, str]) -> list[str]:
    """IN PLACE: each priority muscle (`priority_muscles`) the week already holds at or over MEV whose anchor is PROGRESSING
    (`PRIORITY_ADD`) is HELD — its added isolation slot (the quadriceps slot) leaves the session and the allocation's extra
    sets for it are not applied (`ctx["stimulus_hold"]`, read by `live_balance.allocate`). Under MEV, or with a stalled,
    regressing or unread anchor, the allocation stands (the low-fatigue slot first). Returns the rationale lines."""
    s = _settings(ctx.get("lib"))
    if s.get("priority_add_rule") != "stimulus_and_performance":
        return []
    from training import block_model, live_balance as lb

    plan_ = ctx.get("allocation") or lb.allocation_plan(ctx["catalog"], ctx["lib"], lb._skipped(ctx))
    ctx["allocation"] = plan_
    marks = block_model.load_landmarks() or {}
    hold: set[str] = set()
    lines = []
    for m in [str(x) for x in s.get("priority_muscles") or [] if str(x) in ANCHOR_OF]:
        mev = float((marks.get(m) or {}).get("MEV") or 0)
        before = float((plan_.get("before") or {}).get(m) or 0)
        added = after_add(plan_, m) > before
        read = anchor_trends(ctx, trends, m)
        progressing = bool(read) and all(t == PRIORITY_ADD["progressing"]["value"] for t in read.values())
        if not added or before < mev or not progressing:
            continue
        if m == "quadriceps" and s.get("lead_lift_rule") == "alternate_weekly" and lead_of(str(ctx.get("target_date") or "")) != "squat":
            continue  # the squat is the second lift this week (RPE 7-8): the low-fatigue quadriceps work stands (ruling 9 + 5)
        hold.add(m)
        if not _adds_here(plan_, m, str(rx.get("session_role") or ""), ctx):
            continue  # said once, on the session that would have taken the sets
        verb = "is" if len(read) == 1 else "are"
        lines.append(
            f"priority (live): {m} held at {before:g} sets (MEV {mev:g}) — {' and '.join(sorted(read))} {verb} progressing: the "
            "stimulus works, no sets or slot added (PRIORITY_ADD, heuristic; priority_add_rule=stimulus_and_performance)"
        )
    ctx["stimulus_hold"] = hold
    if "quadriceps" in hold:
        rx["exposures"] = [e for e in rx["exposures"] if e.get("live_added") != "quad_slot"]
    return lines


def _adds_here(plan_: dict[str, Any], muscle: str, role: str, ctx: dict[str, Any]) -> bool:
    """Whether the week's allocation gives `muscle` sets (or its added slot) in this session's role."""
    from training import live_week

    if any(a["role"] == role and a["muscle"] == muscle for a in plan_.get("adds") or []):
        return True
    return any(
        r == role and d > 0 and live_week.landmark_muscle(slot, ctx["catalog"], ctx["lib"]) == muscle
        for (r, slot), d in (plan_.get("deltas") or {}).items()
    )


def after_add(plan_: dict[str, Any], muscle: str) -> float:
    """The muscle's planned weekly sets after the allocation (its added slot included)."""
    return float((plan_.get("after") or {}).get(muscle) or 0)


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
    MEV over the sessions left takes sets on its isolation slots there (at most add_per_slot each; the session with the fewest
    planned sets first, so the floor does not push the heaviest morning past its time cap) until it reaches MEV. Returns the
    plan lines."""
    from training import live_balance as lb

    rows, deltas, marks = env["rows"], env["deltas"], env["marks"]
    cap = int(ARMS_FLOOR["add_per_slot"]["value"])
    lines = []
    for m in ARMS_FLOOR["muscles"]["value"]:
        lm = marks.get(m) or {}
        if not lm:
            continue
        slots = [r for r in rows if r["kind"] == "accessory" and r["muscle"] == m and r["intensity"] != "carry"]
        slots.sort(key=lambda r: (_role_sets(rows, deltas, r["role"]), rows.index(r)))  # the lightest session takes them first
        for r in slots:
            have = lb._sum(rows, deltas)[m] + sum(a["sets"] for a in adds if a["muscle"] == m)
            if have >= float(lm["MEV"]):
                break
            k = (r["role"], str(r["slot"]))
            from training.live_balance import SLOT_MAX  # #5861 FIX7: never past the 3-set slot maximum

            room = max(0, SLOT_MAX - int(r["sets"]) - max(deltas.get(k, 0), 0))
            give = min(cap - max(deltas.get(k, 0), 0), int(-(-(float(lm["MEV"]) - have) // 1)), room)
            if give <= 0:
                continue
            deltas[k] = deltas.get(k, 0) + give
            lines.append(f"{r['role']}.{r['slot']} +{give} set(s): {m} held at MEV {lm['MEV']} in the short week (ARMS_FLOOR, heuristic)")
    return lines


TOP_UP_ROLE = "upper_volume"
"""The short week's last upper session: where the arms floor is checked against what the week ACTUALLY logged."""


def arms_top_up(rx: dict[str, Any], ctx: dict[str, Any], workouts: Any) -> list[str]:
    """IN PLACE, a week that skips shoulders+arms, on its last upper session (TOP_UP_ROLE): each ARMS_FLOOR muscle is COUNTED —
    the hard sets the week has logged since Monday (`fatigue_model.hard_sets_by_muscle`, direct 1.0 + indirect 0.5) plus today's
    planned sets — and one under its MEV takes sets on today's isolation slot for it (at most ARMS_FLOOR add_per_slot). The plan
    count (`short_week_floor`) reads the templates; this reads the record, so an earlier morning's time trim is made up here.
    The floor is MEV in a short week (ruling 3) and MV (maintenance) in an adherence-dip week, a recovery week by ruling 2. It
    runs AFTER the dip's lighter week (`live_session.for_live_draft`), so nothing undoes it. Returns the rationale lines."""
    if "shoulders_arms" not in set(ctx.get("week_skip") or ()) or rx.get("session_role") != TOP_UP_ROLE:
        return []
    from training import block_model, fatigue_model as fm, live_balance as lb, live_week

    lib, cat, day = ctx.get("lib") or {}, ctx.get("catalog") or {}, str(ctx.get("target_date") or "")
    monday = lb.week_start(day)
    logged = [w for w in workouts or [] if monday <= str(w.get("date") or "")[:10] < day]
    done_raw = fm.hard_sets_by_muscle(logged, fm.library_index(lib), as_of=day, days=8) if logged else {}
    done: dict[str, float] = {}
    for m, n in done_raw.items():
        done[live_week.LANDMARK_OF.get(m, m)] = done.get(live_week.LANDMARK_OF.get(m, m), 0.0) + float(n)
    today: dict[str, float] = {}
    for e in rx["exposures"]:
        n = len(e.get("sets") or [])
        prim = live_week.landmark_muscle(e.get("movement_key"), cat, lib)
        today[prim] = today.get(prim, 0.0) + n
        entry = (lib.get("movements") or {}).get((ctx.get("idx") or {}).get("to_lib", {}).get(str(e.get("movement_key"))) or "") or {}
        for sec in {live_week.LANDMARK_OF.get(str(s), str(s)) for s in (entry.get("target") or {}).get("secondary") or []} - {prim}:
            today[sec] = today.get(sec, 0.0) + n * 0.5
    marks, cap, lines = block_model.load_landmarks() or {}, int(ARMS_FLOOR["add_per_slot"]["value"]), []
    level = "MEV" if ctx.get("week_mode") in (None, "short") else "MV"  # a dip week is a recovery week: maintenance is the floor
    for m in ARMS_FLOOR["muscles"]["value"]:
        mev = float((marks.get(m) or {}).get(level) or 0)
        have = done.get(m, 0.0) + today.get(m, 0.0)
        slot = next(
            (
                e
                for e in rx["exposures"]
                if e.get("kind") == "accessory" and e.get("sets") and live_week.landmark_muscle(e.get("movement_key"), cat, lib) == m
            ),
            None,
        )
        if have >= mev or slot is None:
            continue
        from training.live_balance import SLOT_MAX  # #5861 FIX7: the top-up respects the 3-set slot maximum

        add = min(cap, int(-(-(mev - have) // 1)), max(0, SLOT_MAX - len(slot["sets"])))
        if add <= 0:
            continue
        slot["sets"].extend(dict(slot["sets"][-1]) for _ in range(add))
        title = (cat.get(slot.get("movement_key")) or {}).get("title") or slot.get("movement_key")
        lines.append(
            f"top-up (live): {m} {done.get(m, 0.0):g} logged this week + {today.get(m, 0.0):g} today < {level} {mev:g} — {title} +{add} "
            "set(s), counted from the record (ARMS_FLOOR, heuristic)"
        )
    return lines


def _role_sets(rows: list[dict[str, Any]], deltas: dict[tuple[str, str], int], role: str) -> int:
    """The planned working sets of one session (its template + the deltas so far)."""
    return sum(int(r["sets"]) + deltas.get((r["role"], str(r["slot"])), 0) for r in rows if r["role"] == role)


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
    "live_program.STALL_RULE": "e1RM over the exposures after a stall reset",
    "live_program.PAIN_RULE": "pain-note recurrence within 2 sessions of a reduce / avoid",
    "live_program.DELOAD_SHAPE": "readiness and first-set reps the week after a deload",
    "live_program.TRUNK_FLOOR": "trunk-drill progression and back-discomfort notes",
    "live_balance.ALLOCATION": "weekly sets per muscle vs that muscle's e1RM / rep PRs",
    "live_balance.ADHERENCE_DIP": "sessions completed in the 2 weeks after a short-week response",
    "live_shape.VOLUME": "priority-muscle sets vs their anchor trend",
    "live_shape.QUAD_SLOT": "quadriceps anchor trend with the slot served",
    "live_shape.WALK_PROMPT": "walks logged after a prompt",
    "live_week.CARDIO_ROOM": "conditioning-block minutes delivered vs lifting minutes lost",
    "live_week.NOVEL_START": "RPE logged on a new movement's first exposures",
    "fatigue_model.THRESHOLDS": "strain calls vs the next session's first-set reps / RPE",
    "quality_rubric.NEUTRAL": "how often a reviewed input moved a provisional row's tier",
    "fatigue_model.THRESHOLDS.deficit_hold_pct": "anchor e1RM 3 and 6 weeks after a 'holding' read in a deficit vs after a reset (held = right; sliding = tighten the band)",
    "fatigue_model.THRESHOLDS.post_reset_min_exposures": "e1RM over the exposures after each reset; resets per lift per block",
    "fatigue_model.THRESHOLDS.reset_detect_pct": "resets the record shows vs the resets the engine prescribed (false reads = a volume day called a reset)",
    "live_pain.PAIN_SCOPE": "pain-note recurrence within 2 sessions of a lift-only / pattern / pain-free-route answer, and the flagged muscle's hard sets",
    "live_stimulus.FAST_CUT": "anchor e1RM in the 2 weeks after a fast-cut volume answer vs after a load cut",
    "live_stimulus.WEEK_FLOOR": "weekly HARD sets per muscle vs MEV, and the floor muscles' e1RM / rep PRs",
    "live_stimulus.DELOAD_TOP_SET": "readiness and first-set reps the week after an unconfirmed-deload week",
    "live_stimulus.PARITY": "priority-muscle sets vs the donors' and both muscles' rep PRs",
    "live_week.FAMILIAR_SWAP": "RPE logged on a familiar swap's first 2 exposures (over target = restore the novelty cap)",
}
"""Ruling 18: every labelled heuristic table the live engine reads -> the metric that should re-tune it at a block retro.
Provenance (owner rulings 2026-11-13, FIX7 follow-up): `hard_conditioning_doses` = 1 is ruled (a setting, re-tuned on
`live_week.CARDIO_ROOM`'s metric), and ruling 17 is clarified — glute stretch credit only for genuinely lengthened loading
(`quality_rubric.STRETCH_CAPS` empty, rubric 3.5.0), not a heuristic and so not a hook. The
doc's "Block-retro hooks" table lists each key (tests/test_owner_rulings_5861.py holds the doc and this dict to each other, and
each key to a real labelled table)."""
