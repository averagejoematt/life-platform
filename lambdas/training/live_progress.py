"""live_progress.py — progression that knows which day it is on (#5861 FIX8, the seventh red team). LIVE only: every entry
point is reached from `live_session.for_live_draft` or `live_program.guard_loads` / `annotate`, which run only past
`selection_engine.mode() == "live"` (the library `approved`).

WHY. The seventh red team ran a record-seeded athlete through eight simulated weeks and found the load guard role-blind: a hold,
a cut and the one-cut-a-week rule read the lift's LATEST exposure from any day, so a heavy squat day inherited the volume day's
lighter load (190 -> 155 lb for an athlete holding steady, performed at RPE 2.5). Three rules answer it, every number a labelled
heuristic registered for the block retro:

  1. ROLE-KEYED REFERENCES (`reference`, ROLE_REF). Every reference load the guard reads — the hold, the cut base, the effort
     evidence — is the latest top set of the SAME session role (a heavy day reads its last heavy day; a volume day its last
     volume day). A record row whose role is unreadable counts only when its top set sits in today's rep band (at most
     `band_below` reps under its floor, never over its top: a lighter, higher-rep volume set never qualifies for a heavy day).
     With no same-role or same-band exposure in `max_age_days`, the guard makes NO load change — the engine's own load stands.
  2. THE SECOND LIFT'S OWN LOAD (`second_lift`, SECOND_LIFT). The heavy lower day's capped (non-lead) anchor gets the load its
     own RPE 7-8 cap implies: its same-role e1RM (reps + reps in reserve, Epley) at the bottom of the rep range and the cap's
     mid-point — never a load computed for RPE 8-9 with a cap printed under it. Its reason line quotes its own day's last set.
  3. THE RETURN WEEK (`return_week`, RETURN_WEEK). After `gap_days` or more without a logged session (an illness, travel, a
     layoff), the first week back runs every lift at RPE <= 8 (the 7-8 band) with no load steps; the week after is normal.
     Familiarity is judged by movement PATTERN: a lift whose own template has a long gap but whose pattern he trained recently
     works at the return week's band, not the novel-again RPE 7 cap.
"""

from __future__ import annotations

from typing import Any

ISSUE = "#5861"
HEURISTIC = "heuristic"
KG_PER_LB = 0.45359237

ROLE_REF: dict[str, dict[str, Any]] = {
    "max_age_days": {
        "value": 28,
        "label": HEURISTIC,
        "basis": "a same-role reference older than four weeks (layoff_tiers.HOLD_MAX_GAP_DAYS, the OD1 hold window) is no "
        "reference: the guard then changes nothing and the engine's own load (the OD1 re-entry tiers) stands",
    },
    "band_below": {
        "value": 2,
        "label": HEURISTIC,
        "basis": "a record row with no readable session role counts only when its top set's reps sit in today's band, at most 2 "
        "under its floor (a heavier, lower-rep set of the same role) and never over its top (a lighter volume set never "
        "qualifies for a heavy day)",
    },
}
SECOND_LIFT: dict[str, dict[str, Any]] = {
    "rir_floor": {
        "value": 6.0,
        "label": HEURISTIC,
        "basis": "the logged RPE is read clamped to 6-10 (reps in reserve 0-4) when the e1RM is effort-adjusted — the convention "
        "of `fatigue_model._e1rm_rir`",
    },
}
RETURN_WEEK: dict[str, dict[str, Any]] = {
    "gap_days": {
        "value": 10,
        "label": HEURISTIC,
        "basis": "ten or more days with no logged session (an illness, travel) is detraining, not an adherence dip: the first "
        "week back is run lighter on effort (practitioner consensus; the seventh red team)",
    },
    "rpe_band": {
        "value": [7, 8],
        "label": HEURISTIC,
        "basis": "every lift of the return week stops at RPE 7-8 (2-3 in reserve) with no in-session load step: the hard-set line "
        "(RPE 8) is still reached, the grind is not",
    },
}


def _day(w: dict[str, Any]) -> str:
    return str(w.get("date") or str(w.get("sk") or "")[5:15])[:10]


def role_refs(workouts: Any, tids: set[str]) -> dict[str, list[dict[str, Any]]]:
    """Template id -> its top working sets in the record, most recent first: {date, role, kg, reps, rpe}. Only `tids`."""
    from training.fatigue_model import session_role

    out: dict[str, list[dict[str, Any]]] = {}
    for w in workouts or []:
        role, day = session_role(w), _day(w)
        for x in w.get("exercises") or []:
            tid = str(x.get("template_id") or "").upper()
            if tid not in tids:
                continue
            sets = [s for s in x.get("sets") or [] if str(s.get("type") or "normal") != "warmup" and s.get("weight_kg") and s.get("reps")]
            if not sets:
                continue
            top = max(sets, key=lambda s: (float(s["weight_kg"]), int(s["reps"])))
            rpe = top.get("rpe")
            out.setdefault(tid, []).append(
                {
                    "date": day,
                    "role": role,
                    "kg": round(float(top["weight_kg"]), 3),
                    "reps": int(top["reps"]),
                    "rpe": float(rpe) if rpe is not None else None,
                }
            )
    for rows in out.values():
        rows.sort(key=lambda r: r["date"], reverse=True)
    return out


def _from_index(history_index: dict[str, list] | None, tid: str) -> list[dict[str, Any]]:
    """`role_refs`' shape from the history index (no session role on its rows)."""
    out = []
    for s in (history_index or {}).get(tid) or []:
        sets = [x for x in s.get("sets") or [] if x.get("weight_kg") and x.get("reps")]
        if not sets:
            continue
        top = max(sets, key=lambda x: (float(x["weight_kg"]), int(x["reps"])))
        rpe = top.get("rpe")
        out.append({"date": str(s.get("date") or "")[:10], "role": "", "kg": float(top["weight_kg"]), "reps": int(top["reps"]), "rpe": rpe})
    return out


def reference(
    rx: dict[str, Any], history_index: dict[str, list] | None, tid: str, target_date: str, rep_lo: int | None, rep_hi: int | None
) -> dict[str, Any] | None:
    """ROLE_REF (module doc 1): the reference top set for today's exposure of `tid` — `exercise_history.previous_load`'s shape
    ({date, lb, reps, rpe}) plus its `role` — or None (no same-role or same-band exposure in max_age_days: no load change)."""
    from common.pacific_time import shift_day_key

    from training import live_session as ls

    refs = ((rx.get(ls.MARK) or {}).get("refs") or {}).get(tid)
    rows = refs if refs is not None else _from_index(history_index, tid)
    since = shift_day_key(target_date, -int(ROLE_REF["max_age_days"]["value"]))
    rows = [r for r in rows if since <= str(r.get("date") or "") < target_date]
    role = str(rx.get("session_role") or "")
    lo = int(rep_lo or 0) - int(ROLE_REF["band_below"]["value"])
    same = [r for r in rows if role and r.get("role") == role]
    band = [r for r in rows if not r.get("role") and rep_hi and lo <= int(r["reps"]) <= int(rep_hi)]
    pick = (same or band or [None])[0]
    if pick is None:
        return None
    rpe = pick.get("rpe")
    return {
        "date": pick["date"],
        "template_id": tid,
        "lb": round(float(pick["kg"]) / KG_PER_LB, 1),
        "reps": int(pick["reps"]),
        "rpe": float(rpe) if rpe is not None else None,
        "role": pick.get("role") or "",
    }


def _e1rm_lb(ref: dict[str, Any]) -> float:
    """Effort-adjusted Epley (reps + reps in reserve), RPE clamped to rir_floor-10; an unlogged RPE reads as 8."""
    rpe = float(ref["rpe"]) if ref.get("rpe") is not None else 8.0
    rir = 10.0 - min(10.0, max(float(SECOND_LIFT["rir_floor"]["value"]), rpe))
    return float(ref["lb"]) * (1 + (int(ref["reps"]) + rir) / 30.0)


def second_lift(e: dict[str, Any], ref: dict[str, Any] | None, rep_lo: int | None, equipment: str | None) -> dict[str, Any] | None:
    """SECOND_LIFT (module doc 2): the guard decision for a capped non-lead anchor whose engine load exceeds what its cap implies,
    as {mode: down, pct, why, cap_kg} — or None (not the second lift, no same-role reference, or the load already fits)."""
    if e.get("live_lead") != "second" or ref is None or not rep_lo:
        return None
    from training.live_program import _floor_to_implement

    lo, hi = (float(x) for x in e.get("live_effort_band") or (7, 8))
    target_lb = _e1rm_lb(ref) / (1 + (int(rep_lo) + 10.0 - (lo + hi) / 2) / 30.0)
    cap_kg = _floor_to_implement(target_lb * KG_PER_LB, equipment)
    pct = max(0, round(100 * (1 - cap_kg / (float(ref["lb"]) * KG_PER_LB))))
    rpe = f" @ {float(ref['rpe']):g}" if ref.get("rpe") is not None else ""
    return {"mode": "down", "pct": pct, "why": f"last {ref['lb']:g}x{ref['reps']}{rpe}", "cap_kg": cap_kg, "second": True}


def second_clause(d: dict[str, Any]) -> str:
    """The capped lift's one reason line: its own day's last set (module doc 2)."""
    from training import session_block

    line = f"RPE 7–8 today: {d['why']}."
    return line if len(line) <= session_block.CLAUSE_MAX_CHARS else "RPE 7–8 today: the second lift."


def return_week(workouts: Any, target_date: str) -> dict[str, Any] | None:
    """RETURN_WEEK (module doc 3): {gap_days, back_on} when this week is the first back after a gap of `gap_days`+ with no
    logged session (the gap ending inside this week, today counting as the first session back when none is logged yet)."""
    from common.pacific_time import parse_day_key

    from training.live_balance import week_start

    if not target_date:
        return None
    monday = week_start(target_date)
    days = sorted(
        {_day(w) for w in workouts or [] if _day(w) and _day(w) < target_date and any(x.get("sets") for x in w.get("exercises") or [])}
    )
    before = [d for d in days if d < monday]
    this_week = [d for d in days if d >= monday]
    back_on = this_week[0] if this_week else target_date
    if not before:
        return None
    a, b = parse_day_key(before[-1]), parse_day_key(back_on)
    gap = (b - a).days if a is not None and b is not None else 0
    if gap < int(RETURN_WEEK["gap_days"]["value"]):
        return None
    return {"gap_days": gap, "back_on": back_on, "last": before[-1]}


def apply_return_week(rx: dict[str, Any], ctx: dict[str, Any], workouts: Any) -> list[str]:
    """IN PLACE (module doc 3): the return week caps every lift at the RETURN_WEEK band, marks it `live_return` (no load step,
    `live_safety.no_step_keys`; the load guard holds at the same-role reference) and lifts the novel-again cap on a lift whose
    pattern he trained in the record (`live_familiar`). Returns the rationale lines."""
    back = return_week(workouts, str(ctx.get("target_date") or ""))
    if not back:
        return []
    lo, hi = (int(x) for x in RETURN_WEEK["rpe_band"]["value"])
    seen = _patterns_trained(workouts, ctx)
    for e in rx.get("exposures") or []:
        if e.get("intensity") == "carry":
            continue
        e["live_effort"] = min(hi, int(e.get("live_effort") or 99))
        e["live_effort_band"] = [lo, hi]
        e["live_return"] = True
        e["live_load"] = {**(e.get("live_load") or {}), "hold": True}
        entry = ((ctx.get("lib") or {}).get("movements") or {}).get(
            (ctx.get("idx") or {}).get("to_lib", {}).get(str(e.get("movement_key"))) or ""
        ) or {}
        if entry.get("pattern") in seen:
            e["live_familiar"] = True
    return [
        f"return week (live): {back['gap_days']} days without a session (last {back['last']}) — every lift at RPE {lo}-{hi}, no load "
        "steps this week, back to normal next week; familiarity read by movement pattern (RETURN_WEEK, heuristic)"
    ]


def _patterns_trained(workouts: Any, ctx: dict[str, Any]) -> set[str]:
    """The library patterns of every template he has logged in the record (familiarity by pattern, module doc 3)."""
    from training import fatigue_model as fm

    idx = fm.library_index(ctx.get("lib"))
    out = set()
    for w in workouts or []:
        for x in w.get("exercises") or []:
            row = idx.get(str(x.get("template_id") or "").upper()) or {}
            if row.get("pattern"):
                out.add(str(row["pattern"]))
    return out
