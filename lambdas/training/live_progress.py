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
  3. THE FIRST SESSION BACK (`first_back`, FIRST_BACK; owner ruling 2026-11-13 #10). After ~10+ days without a logged session,
     each lift's FIRST session back stops at RPE 8 at its last same-role load (no automatic increase, no in-session step);
     normal progression resumes from that session's own performance. No week-long deload or reset because days elapsed.
     Familiarity is judged by movement pattern: a biomechanically similar lift gets no extra restriction after time away.
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
FIRST_BACK: dict[str, dict[str, Any]] = {
    "gap_days": {
        "value": 10,
        "label": HEURISTIC,
        "basis": "owner ruling 2026-11-13 (#10, fix round 8): after ~10+ days with no logged session, each lift's FIRST session back "
        "is conservative — no week-long deload or reset just because the days elapsed",
    },
    "rpe": {
        "value": 8,
        "label": HEURISTIC,
        "basis": "the first session back stops at RPE 8 (2 in reserve: technique and today's performance decide), at the last "
        "same-role load with no automatic increase; normal progression resumes from that session's own performance",
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
    as {mode: down (under the reference) | cap (a smaller step than the engine's), pct, why, cap_kg, second} — or None (not the second lift, no same-role reference, or the load already fits).
    """
    if e.get("live_lead") != "second" or ref is None or not rep_lo:
        return None
    from training.live_program import _floor_to_implement

    lo, hi = (float(x) for x in e.get("live_effort_band") or (7, 8))
    target_lb = _e1rm_lb(ref) / (1 + (int(rep_lo) + 10.0 - (lo + hi) / 2) / 30.0)
    cap_kg = _floor_to_implement(target_lb * KG_PER_LB, equipment)
    pct = max(0, round(100 * (1 - cap_kg / (float(ref["lb"]) * KG_PER_LB))))
    rpe = f" @ {float(ref['rpe']):g}" if ref.get("rpe") is not None else ""
    mode = "down" if pct > 0 else "cap"  # under the reference: a cut; over it: the step the cap allows, no more
    return {"mode": mode, "pct": pct, "why": f"last {ref['lb']:g}x{ref['reps']}{rpe}", "cap_kg": cap_kg, "second": True}


def second_clause(d: dict[str, Any]) -> str:
    """The capped lift's one reason line: its own day's last set (module doc 2)."""
    from training import session_block

    line = f"RPE 7–8 today: {d['why']}."
    return line if len(line) <= session_block.CLAUSE_MAX_CHARS else "RPE 7–8 today: the second lift."


def layoff_end(workouts: Any, target_date: str) -> dict[str, Any] | None:
    """FIRST_BACK (module doc 3): the latest gap of gap_days+ with no logged session before `target_date` — {gap_days, last, end}
    (`end` = the first session after it, or `target_date` when the gap runs to today) — or None."""
    from common.pacific_time import parse_day_key

    days = sorted(
        {_day(w) for w in workouts or [] if _day(w) and _day(w) < target_date and any(x.get("sets") for x in w.get("exercises") or [])}
    )
    points = days + [target_date]
    for a, b in reversed(list(zip(points, points[1:]))):
        da, db = parse_day_key(a), parse_day_key(b)
        if da is not None and db is not None and (db - da).days >= int(FIRST_BACK["gap_days"]["value"]):
            return {"gap_days": (db - da).days, "last": a, "end": b}
    return None


def first_back(rx: dict[str, Any], ctx: dict[str, Any], workouts: Any) -> list[str]:
    """IN PLACE (FIRST_BACK, module doc 3): each lift with no exposure since the latest 10+-day layoff is on its FIRST session back —
    capped at RPE 8, held at its same-role load (no automatic increase, no in-session step: `live_first_back`); a lift whose
    pattern he trained in the record is familiar (no novelty cap). Every other lift progresses as usual. Returns the lines."""
    gap = layoff_end(workouts, str(ctx.get("target_date") or ""))
    if not gap:
        return []
    ctx["layoff"] = gap  # read by `live_stimulus.hard_capable`: a first-back set at RPE 8 still counts as hard
    since = {str(x.get("template_id") or "").upper() for w in workouts or [] if gap["end"] <= _day(w) for x in w.get("exercises") or []}
    seen, lib, cat = _patterns_trained(workouts, ctx), ctx.get("lib") or {}, ctx.get("catalog") or {}
    rpe, names = int(FIRST_BACK["rpe"]["value"]), []
    for e in rx.get("exposures") or []:
        tid = str((cat.get(str(e.get("movement_key"))) or {}).get("hevy_template_id_hint") or "").upper()
        if not tid or tid in since or e.get("intensity") == "carry":
            continue
        e["live_effort"] = min(rpe, int(e.get("live_effort") or 99))
        e["live_load"] = {**(e.get("live_load") or {}), "hold": True}
        e["live_first_back"] = True
        entry = (lib.get("movements") or {}).get((ctx.get("idx") or {}).get("to_lib", {}).get(str(e.get("movement_key"))) or "") or {}
        if entry.get("pattern") in seen:
            e["live_familiar"] = True
        names.append(str((cat.get(str(e.get("movement_key"))) or {}).get("title") or e.get("movement_key")))
    if not names:
        return []
    return [
        f"first back (live): {gap['gap_days']} days without a session (last {gap['last']}) — {', '.join(names)}: first session back at "
        f"RPE <= {rpe}, no load increase; normal progression from its own performance next time (FIRST_BACK, heuristic)"
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
