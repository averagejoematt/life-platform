"""live_stimulus.py — enough HARD training, kept (#5861 FIX7, the sixth red team). LIVE only: every entry point is reached from
`live_session.for_live_draft` / `live_program.plan`, which run only past `selection_engine.mode() == "live"`.

WHY. The sixth red team graded stimulus adequacy C: each rule cut a little effort or volume, and together they left too little hard
training. The owner's standard (2026-11-13): eliminate unproductive fatigue, NOT hard training — muscle retention in a big deficit
needs demanding resistance work. The rules here, every number a labelled heuristic registered for the block retro:

  1. A FAST CUT WITH BROAD REGRESSION (`fast_cut`, FAST_CUT). When the weigh-ins fall faster than `rate_pct_bw` AND most lifts
     regress together, the answer is VOLUME, not load: accessory sets come down about a third (never below one set a lift), loads
     and intensity are kept (no regression cut: `live_keep_intensity`, read by `live_program.load_decision`), and the advisory line
     names it — instead of the blanket −10% load at full volume.
  2. THE WEEK'S HARD-SET FLOOR (`week_floor`, WEEK_FLOOR). The week's LAST session counts each muscle's HARD sets (logged since
     Monday at RPE >= 8 or unlogged, direct 1.0 + indirect 0.5, plus today's) and a muscle under its MEV takes sets: first on
     today's own isolation slot for it (never past slot_max sets), else a low-fatigue isolation for it (a leg extension for the
     quadriceps at RPE 8-9 — the driver's preferred lever over cutting `press_sets`; a fly, a pushdown, a calf raise, a crunch),
     priority muscles first, while the session set cap and the weekly redline have room. A 3-day week's full-body day carries
     chest / triceps / calves / abs this way.
  4. PRIORITY PARITY (`parity`, PARITY). In the week's allocation a priority muscle never ends with fewer sets than a non-priority
     ISOLATION muscle (the sixth red team: chest 8 vs biceps 11): the donor's surplus isolation sets move to the priority muscle's
     own isolation slot (net zero, never past the 3-set slot maximum), else they are trimmed — never under the donor's MEV.
  3. THE UNCONFIRMED DELOAD (`deload_top_set`, DELOAD_TOP_SET). A deload the fatigue model RECOMMENDS is not yet his word (charter
     deload.owner_gated): until he confirms it, each anchor keeps one top set at RPE 8 — the deload's RPE-7 cap applies only once
     confirmed.
"""

from __future__ import annotations

from typing import Any

ISSUE = "#5861"
HEURISTIC = "heuristic"

FAST_CUT: dict[str, dict[str, Any]] = {
    "rate_pct_bw": {
        "value": 1.0,
        "label": HEURISTIC,
        "basis": "a weekly loss at or over 1 %BW (the owner's advisory reference, ruling 11) read from the weigh-ins the draft read",
    },
    "regressing_share": {
        "value": 0.5,
        "label": HEURISTIC,
        "basis": "half or more of the lifts with a read trend regressing together (and at least min_regressing): systemic, not one lift",
    },
    "min_regressing": {"value": 3, "label": HEURISTIC, "basis": "see regressing_share"},
    "accessory_cut": {
        "value": 0.33,
        "label": HEURISTIC,
        "basis": "about a third of the session's accessory sets come off and anchor intensity is held — dose-maintenance work keeps "
        "size and strength on ~1/3 of the prior volume while intensity is kept (the sixth red team, practitioner consensus)",
    },
}
WEEK_FLOOR: dict[str, dict[str, Any]] = {
    "muscles": {
        "value": ["quadriceps", "chest", "triceps", "calves", "abs", "biceps", "shoulders", "hamstrings", "glutes"],
        "label": HEURISTIC,
        "basis": "the muscles with an MEV landmark the week's last session can still top up with low-fatigue isolation (back is "
        "carried by the anchors); priority muscles (`priority_muscles`) go first",
    },
    "hard_rpe": {"value": 8.0, "label": HEURISTIC, "basis": "a hard set is a working set at RPE >= 8 (about 2 in reserve), or unlogged"},
    "add_sets": {"value": 2, "label": HEURISTIC, "basis": "an added low-fatigue isolation slot is two sets at RPE 8-9"},
    "slot_max": {"value": 3, "label": HEURISTIC, "basis": "an existing slot takes sets only up to 3 (4+ in one slot is junk volume)"},
    "keys": {
        "value": {
            "quadriceps": ["leg_extension_machine", "single_leg_extension"],
            "chest": ["pec_deck", "chest_fly_machine", "cable_chest_fly"],
            "triceps": ["triceps_rope_pushdown", "triceps_pushdown_cable", "overhead_triceps_extension_cable"],
            "calves": ["calf_raise_machine", "standing_calf_raise_machine", "seated_calf_raise"],
            "abs": ["cable_crunch", "ab_crunch_machine"],
        },
        "label": HEURISTIC,
        "basis": "the low-fatigue isolation preferred per muscle (machines and cables: low systemic and joint cost); else the most-logged "
        "isolation the library places on that muscle",
    },
}
DELOAD_TOP_SET: dict[str, dict[str, Any]] = {
    "rpe": {
        "value": 8,
        "label": HEURISTIC,
        "basis": "a RECOMMENDED (unconfirmed) deload keeps one top set per anchor at RPE 8 — strength exposure held until the owner "
        "confirms the deload; the deload's RPE-7 compound cap applies once confirmed",
    },
}


def fast_cut(rx: dict[str, Any], sig: dict[str, Any], inputs: Any) -> list[str]:
    """IN PLACE (FAST_CUT, module doc 1). Returns the rationale lines (empty when it does not apply)."""
    from training import fatigue_model as fm

    rate = fm.loss_rate_pct(getattr(inputs, "weights_by_day", None))
    read = [str(v.get("trend")) for v in (sig or {}).values() if v.get("trend") not in (None, "unknown")]
    reg = sum(1 for t in read if t == "regressing")
    if rate is None or rate < float(FAST_CUT["rate_pct_bw"]["value"]) or reg < int(FAST_CUT["min_regressing"]["value"]):
        return []
    if reg / max(1, len(read)) < float(FAST_CUT["regressing_share"]["value"]):
        return []
    for e in rx.get("exposures") or []:
        e["live_keep_intensity"] = True  # no regression cut anywhere: the volume is the lever
    acc = [e for e in rx.get("exposures") or [] if e.get("kind") == "accessory" and e.get("intensity") != "carry"]
    n = round(sum(len(e.get("sets") or []) for e in acc) * float(FAST_CUT["accessory_cut"]["value"]))
    removed = 0
    while removed < n:  # one set at a time off the fullest accessory (never below one set; the anchors untouched)
        pick = max((e for e in acc if len(e.get("sets") or []) > 1), key=lambda e: len(e["sets"]), default=None)
        if pick is None:
            break
        pick["sets"].pop()
        removed += 1
    rx["live_fast_cut"] = {"rate_pct_bw": round(rate, 2), "regressing": reg, "read": len(read), "sets_removed": removed}
    return [
        f"fast cut (live): ~{rate:.1f} %BW/week and {reg} of {len(read)} lifts regressing — accessory volume -{removed} set(s) "
        "(about a third), anchor intensity kept, no load cut (FAST_CUT, heuristic)"
    ]


def rate_suffix(rx: dict[str, Any]) -> str:
    """The loss-rate advisory line's FAST_CUT clause (module doc 1), or ''."""
    fc = rx.get("live_fast_cut")
    return "; broad strength regression in a fast cut: accessory volume cut ~1/3, anchor intensity kept (FAST_CUT)" if fc else ""


def _hard_logged(workouts: Any, ctx: dict[str, Any], since: str, day: str) -> dict[str, float]:
    """Landmark muscle -> HARD sets logged in [since, day): RPE >= hard_rpe or unlogged; direct 1.0, indirect 0.5."""
    from training import fatigue_model as fm, live_week

    idx = fm.library_index(ctx.get("lib"))
    out: dict[str, float] = {}
    for w in workouts or []:
        if not since <= str(w.get("date") or "")[:10] < day:
            continue
        for x in w.get("exercises") or []:
            row = idx.get(str(x.get("template_id") or "").upper()) or {}
            hard = [
                st
                for st in fm._working(x.get("sets"))
                if st.get("reps") and (st.get("rpe") is None or float(st["rpe"]) >= float(WEEK_FLOOR["hard_rpe"]["value"]))
            ]
            if not hard or not row.get("primary"):
                continue
            prim = live_week.LANDMARK_OF.get(str(row["primary"]), str(row["primary"]))
            out[prim] = out.get(prim, 0.0) + len(hard)
            for sec in {live_week.LANDMARK_OF.get(str(m), str(m)) for m in row.get("secondary") or []} - {prim}:
                out[sec] = out.get(sec, 0.0) + 0.5 * len(hard)
    return out


def _today(rx: dict[str, Any], ctx: dict[str, Any]) -> dict[str, float]:
    """Landmark muscle -> today's planned hard sets (an exposure capped under hard_rpe does not count)."""
    from training import live_week

    lib, cat = ctx.get("lib") or {}, ctx.get("catalog") or {}
    out: dict[str, float] = {}
    for e in rx.get("exposures") or []:
        if e.get("intensity") == "carry" or (
            e.get("live_effort") is not None and int(e["live_effort"]) < float(WEEK_FLOOR["hard_rpe"]["value"])
        ):
            continue
        n = len(e.get("sets") or [])
        prim = live_week.landmark_muscle(e.get("movement_key"), cat, lib)
        out[prim] = out.get(prim, 0.0) + n
        entry = (lib.get("movements") or {}).get((ctx.get("idx") or {}).get("to_lib", {}).get(str(e.get("movement_key"))) or "") or {}
        for sec in {live_week.LANDMARK_OF.get(str(m), str(m)) for m in (entry.get("target") or {}).get("secondary") or []} - {prim}:
            out[sec] = out.get(sec, 0.0) + 0.5 * n
    return out


def last_session(ctx: dict[str, Any], role: str | None) -> bool:
    """`role` is the week's last drafted session (the split order without the week's skipped roles)."""
    from training import program_structure as ps

    left = [r for r in ps.SPLIT_ROLES if r not in set(ctx.get("week_skip") or ())]
    return bool(left) and role == left[-1]


def _flagged(entry: dict[str, Any], flags: list[dict[str, Any]]) -> bool:
    """The candidate loads a pain/discomfort-flagged joint at moderate or more (the week floor never adds work a flag would reach)."""
    from training.live_program import _stress

    return any(_stress(entry, j) >= 1 for f in flags for j in f.get("joints") or [])


def _iso_for(muscle: str, ctx: dict[str, Any], taken: set[str], flags: list[dict[str, Any]] | None = None) -> str | None:
    """A servable low-fatigue isolation for `muscle`: WEEK_FLOOR keys first, then the most-logged isolation the library places
    on it (machine / cable first)."""
    from training import live_session, live_week, selection_engine as se

    lib, cat = ctx.get("lib") or {}, ctx.get("catalog") or {}
    to_lib = (ctx.get("idx") or {}).get("to_lib") or {}
    pref = list((WEEK_FLOOR["keys"]["value"] or {}).get(muscle) or [])
    rest = sorted((k for k in cat if k not in pref), key=lambda k: (-int((cat.get(k) or {}).get("sessions") or 0), k))
    for key in pref + rest:
        entry = (lib.get("movements") or {}).get(to_lib.get(key) or "") or {}
        c = cat.get(key) or {}
        if key in taken or not entry or entry.get("job") != "isolation" or c.get("hevy_type") in live_session.NOT_LIFTS:
            continue
        if live_week.landmark_muscle(key, cat, lib) != muscle or entry.get("pattern") in ("carry", "cardio", "other"):
            continue
        if key not in pref and entry.get("resistance_profile") not in ("machine_selectorized", "machine_plate_loaded", "cable"):
            continue
        if (
            se.availability(entry, lib, ctx.get("overlay"))
            or se.pain_exclusion(entry, ctx.get("overlay"))
            or live_session._servable(key, ctx)
            or _flagged(entry, flags or [])
        ):
            continue
        return key
    return None


def week_floor(rx: dict[str, Any], ctx: dict[str, Any], workouts: Any, set_cap: int | None) -> list[str]:
    """IN PLACE (WEEK_FLOOR, module doc 2), the week's last session only, never on a bad day. Returns the rationale lines."""
    from training import block_model, live_balance as lb, live_rules, live_shape, live_week
    from training.program_structure import EXPOSURES

    day = str(ctx.get("target_date") or "")
    if not day or not last_session(ctx, rx.get("session_role")) or live_rules.bad_day(rx):
        return []
    logged = _hard_logged(workouts, ctx, lb.week_start(day), day)
    from training import live_program

    flags = live_program.joint_flags(ctx, workouts, (ctx.get("discomfort") or set()) | (ctx.get("light_discomfort") or set()))
    marks = block_model.load_landmarks() or {}
    prio = [str(m) for m in live_shape._settings(ctx.get("lib")).get("priority_muscles") or []]
    order = sorted(WEEK_FLOOR["muscles"]["value"], key=lambda m: (m not in prio, WEEK_FLOOR["muscles"]["value"].index(m)))
    week_sets = sum(
        len(st)
        for st in [
            x.get("sets") or []
            for w in workouts or []
            if lb.week_start(day) <= str(w.get("date") or "")[:10] < day
            for x in w.get("exercises") or []
        ]
    )
    room = lambda add: (set_cap is None or sum(len(e.get("sets") or []) for e in rx["exposures"]) + add <= int(set_cap)) and (  # noqa: E731
        week_sets + sum(len(e.get("sets") or []) for e in rx["exposures"]) + add <= live_shape.week_redline()
    )
    cat, lib, lines = ctx.get("catalog") or {}, ctx.get("lib") or {}, []
    taken = {str(e.get("movement_key")) for e in rx["exposures"]}
    slot_max, add_n = int(WEEK_FLOOR["slot_max"]["value"]), int(WEEK_FLOOR["add_sets"]["value"])
    for m in order:
        mev = float((marks.get(m) or {}).get("MEV") or 0)
        have = logged.get(m, 0.0) + _today(rx, ctx).get(m, 0.0)
        if not mev or have >= mev:
            continue
        need = int(-(-(mev - have) // 1))
        slot = next(
            (
                e
                for e in rx["exposures"]
                if e.get("kind") == "accessory"
                and e.get("sets")
                and e.get("live_effort") is None
                and live_week.landmark_muscle(e.get("movement_key"), cat, lib) == m
            ),
            None,
        )
        if slot is not None and len(slot["sets"]) < slot_max:
            give = min(need, slot_max - len(slot["sets"]))
            if give > 0 and room(give):
                slot["sets"].extend(dict(slot["sets"][-1]) for _ in range(give))
                lines.append(
                    f"week floor (live): {m} {have:g} hard sets this week < MEV {mev:g} — {(cat.get(slot['movement_key']) or {}).get('title')} +{give} set(s) (WEEK_FLOOR, heuristic)"
                )
                continue
        key = _iso_for(m, ctx, taken, flags)
        if key is None:
            continue
        if not room(add_n):  # no room: a donor whose muscle stays at MEV without it gives its slot (a 3-day week's full-body day)
            donor = _donor(rx, ctx, logged, marks, m)
            if donor is None:
                continue
            taken.add(key)
            was = (cat.get(donor["movement_key"]) or {}).get("title") or donor["movement_key"]
            donor.update({"movement_key": key, "kind": "accessory", "pattern": None, "intensity": "accessory", "live_added": "week_floor"})
            donor["sets"] = [{"kind": "working", "reps": [10, 15]} for _ in donor.get("sets") or []]
            donor.pop("template_id", None)
            lines.append(
                f"week floor (live): {was} -> {(cat.get(key) or {}).get('title') or key} — {m} {have:g} hard sets this week < MEV {mev:g}; the donor's muscle stays at MEV (WEEK_FLOOR, heuristic)"
            )
            continue
        taken.add(key)
        rx["exposures"].append(
            {
                "kind": "accessory",
                "pattern": None,
                "slot": f"week_floor_{m}",
                "intensity": "accessory",
                "movement_key": key,
                "resolution_note": None,
                "sets": [{"kind": "working", "reps": [10, 15]} for _ in range(add_n)],
                "rest_seconds": int(EXPOSURES["accessory"]["rest_seconds"]),
                "live_added": "week_floor",
                "live_cost": "low",
            }
        )
        lines.append(
            f"added (live): {(cat.get(key) or {}).get('title') or key} {add_n} x 10-15 — {m} {have:g} hard sets this week < MEV {mev:g}: the week's last session carries it (WEEK_FLOOR, heuristic)"
        )
    return lines


def _donor(rx: dict[str, Any], ctx: dict[str, Any], logged: dict[str, float], marks: dict[str, Any], muscle: str) -> dict[str, Any] | None:
    """A partner anchor or accessory today whose landmark muscle stays at or over its MEV (and over the needy muscle's count)
    without it — the slot a muscle under MEV may take when the session has no room; the biggest surplus first."""
    from training import live_week

    lib, cat = ctx.get("lib") or {}, ctx.get("catalog") or {}
    today = _today(rx, ctx)
    best, surplus = None, 0.0
    for e in rx.get("exposures") or []:
        if not (e.get("live_full_body") or e.get("kind") == "accessory") or e.get("intensity") == "carry" or e.get("live_added"):
            continue
        d = live_week.landmark_muscle(e.get("movement_key"), cat, lib)
        mev = float((marks.get(d) or {}).get("MEV") or 0)
        left = logged.get(d, 0.0) + today.get(d, 0.0) - len(e.get("sets") or [])
        if d == muscle or not mev or left < mev or left - mev <= surplus:
            continue
        best, surplus = e, left - mev
    return best


PARITY: dict[str, dict[str, Any]] = {
    "donors": {
        "value": ["biceps", "triceps", "calves"],
        "label": HEURISTIC,
        "basis": "the non-priority muscles trained by isolation alone: a priority muscle never ends the week's allocation under any "
        "of them (the shoulders are pressed and their rear-delt work is kept: they stay out); a donor keeps MEV + donor_margin",
    },
    "donor_margin": {
        "value": 2,
        "label": HEURISTIC,
        "basis": "a donor keeps MEV + 2 on the plan: the served week loses sets to swaps and the time trim the plan cannot see",
    },
}


def parity(env: dict[str, Any], adds: list[dict[str, Any]]) -> list[str]:
    """IN PLACE on env["deltas"] (`live_balance.allocation_plan`, PARITY, module doc 4): returns the plan lines; the recipient slot
    keys go to env["parity"] (applied even when the stimulus gate holds the muscle — the move is net zero)."""
    from training import live_balance as lb

    rows, deltas, marks = env["rows"], env["deltas"], env["marks"]
    prio = [p for p in env.get("priority") or [] if p in marks]
    floor, lines = int(lb.ALLOCATION["over_mav_floor"]["value"]), []
    env.setdefault("parity", set())
    if not prio:
        return []

    def week() -> dict[str, float]:
        w = lb._sum(rows, deltas)
        for a in adds:
            w[a["muscle"]] += a["sets"]
        return w

    def slot_sets(r: dict[str, Any]) -> int:
        return int(r["sets"]) + deltas.get((r["role"], str(r["slot"])), 0)

    for d in PARITY["donors"]["value"]:
        mev = float((marks.get(d) or {}).get("MEV") or 0)
        while True:
            w = week()
            low = min(prio, key=lambda p: (w[p], prio.index(p)))
            if w[d] <= w[low] or w[d] - 1 < mev + float(PARITY["donor_margin"]["value"]):
                break
            mine = [r for r in rows if r["kind"] == "accessory" and r["muscle"] == d and r["intensity"] != "carry" and slot_sets(r) > 0]
            give = [r for r in mine if slot_sets(r) > floor]
            keep = mev + float(PARITY["donor_margin"]["value"])
            whole = [r for r in mine if slot_sets(r) <= floor and w[d] - slot_sets(r) >= keep]  # drop, don't shave
            if not give and not whole:
                break
            g = max(give, key=lambda r: (slot_sets(r), rows.index(r))) if give else max(whole, key=lambda r: rows.index(r))
            n = 1 if give else slot_sets(g)
            deltas[(g["role"], str(g["slot"]))] = deltas.get((g["role"], str(g["slot"])), 0) - n
            moved = 0
            for _ in range(n):
                take = [
                    r
                    for r in rows
                    if r["kind"] == "accessory" and r["muscle"] == low and r["intensity"] != "carry" and 0 < slot_sets(r) < lb.SLOT_MAX
                ]
                if not take or week()[low] >= week()[d]:
                    break
                t = min(take, key=lambda r: (slot_sets(r), rows.index(r)))
                deltas[(t["role"], str(t["slot"]))] = deltas.get((t["role"], str(t["slot"])), 0) + 1
                env["parity"].add((t["role"], str(t["slot"])))
                moved += 1
            lines.append(f"{g['role']}.{g['slot']} -{n}, {low} +{moved}: {low} (priority) never under {d} (PARITY, heuristic)")
    return lines
