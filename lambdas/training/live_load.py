"""live_load.py — THE one progression model of the live engine (#5861, fix round 9: consolidation). LIVE only.

Fix rounds 1-8 stacked eight load rules on the engine's template-keyed progression (a regression cut, an overshoot cut, a grind
hold, an evidence rule, one-retreat-a-week, a stall reset with a rep-scheme change, reset detection with a rebuild window, a
deficit hold) — and each one compensated for another. The eighth red team still found a ratchet (one Hevy template on a heavy
AND a volume day: 160 -> 140 -> 125 -> 160 on real data), a collapse under unreliable RPE (RPE 10 logged on every set: bench
185 -> 105 in five weeks) and a cascade of six 10% cuts in one week on a lifter losing 0.5% a week. Round 9 replaces all of
them with ONE model, keyed by SESSION ROLE (a heavy day and a volume day are two lifts, even on one template):

  1. DOUBLE PROGRESSION, UP. The load is the lift's last same-role top load. When every set at that load reached the top of the
     rep range (at or under the target RPE, or with effort unknown), it steps up one implement step; otherwise it HOLDS and the
     reps climb. Nothing else moves a load up. A HOLD (a slump, a strained or deload-recommended day, a pain flag on the lift, a
     first session back) blocks only this step up.
  2. DOWN, BELOW THE FLOOR (fix round 10, the ninth red team). The top set under the rep range's FLOOR in the last
     `below_floor_exposures` same-role exposures in a row -> down at least `step_down_pct`, and as far as the last exposure says
     reaches the floor with two in reserve (`floor_load`). Nothing blocks it: a hold may stop a step up, never a step down for reps
     under the floor, so a real decline is answered within two exposures and a lift never grinds under its floor for weeks. RPE
     never triggers it (it only sizes the step, read clamped like the slump's decline read).
  3. EFFORT UNKNOWN. RPE missing on every set, or >= 9.5 on every set: the step up rides on reps alone (rule 1); effort can never
     move a load down on its own (rule 2 reads reps only).
  4. SYSTEMIC SLUMP — THE ONE PERFORMANCE SIGNAL (fix round 11, the tenth red team: rep noise voted twice). Each anchor's
     same-role e1RM is read by ONE rule (`fatigue_model.declined`: the latest two exposures both under the median of the earlier
     ones by more than the noise band). Four or more anchors declined together (or, in a deficit, half or more): every load
     HOLDS (rule 1), non-priority accessories lose about a third of their sets (`slump_trim`), and the fatigue model counts it as
     its ONE performance strain vote (`strength`) — no separate effort-drift or per-lift regression vote reads the same series.
  5. FIRST SESSION BACK (owner ruling #10). 10-20 days with no session: each lift's first session back runs at RPE 8 at its last
     same-role load (a hold, rule 1). 21+ days (`long_layoff_days`, fix round 11): it starts `long_layoff_pct` under that load.
  6. THE HEAVY LOWER MORNING (owner ruling 5; fix round 11 — the tenth red team's ratchet): the squat always leads at the
     session's effort; the deadlift is a top set + one back-off capped at RPE 8 (`live_rulings.lead_lift`). Each is an ordinary
     lift of this model: loaded from its NEWEST same-role exposure, down only after two exposures under the floor, up at the top
     of the range at or under its own target (the deadlift's is its cap).
  7. NOVELTY (three rules). A NEW pattern (none logged in ~8 weeks) runs one exposure at RPE <= 7; a FAMILIAR pattern (a
     biomechanically similar swap included) works at normal effort with no re-entry cap; the layoff rule is 5.

Every number is a labelled heuristic in `live_settings.HEURISTICS`. The engine's own load (the v0.3 ramp) stands only for a lift
with no same-role exposure in the window. In shadow nothing here runs (the callers check the live mark first)."""

from __future__ import annotations

import math
from typing import Any

from training import live_settings as cfg

ISSUE = "#5861"
KG_PER_LB = 0.45359237


def effort_role(e: dict[str, Any]) -> str:
    """An exposure's row of the ONE effort table (`effort_targets`, fix round 12): a heavy-day anchor is a `heavy_compound`, any
    other anchor a `volume_compound`, every accessory slot (machine and isolation work) an `accessory`. The deadlift beside the
    squat takes its own row through its cap (`live_rulings.lead_lift`)."""
    if e.get("kind") != "anchor":
        return "accessory"
    return "heavy_compound" if e.get("intensity") == "heavy" else "volume_compound"


def step_rpe(e: dict[str, Any] | None = None) -> float:
    """The RPE at or under which the top of the rep range earns the step up: the role's working-set RPE, or the lift's own cap
    when that is lower (the deadlift, a pain hold, a strained day). No exposure: the accessory row's."""
    work = float(cfg.value("effort_targets")[effort_role(e or {})][0])
    cap = (e or {}).get("live_effort")
    return min(work, float(cap)) if cap else work


def effort_line(e: dict[str, Any]) -> str | None:
    """The note's effort line for a role whose target is not the composer's band: a heavy compound's `RPE 8, last set RPE 8–9`
    (None: the composer's line, or the lift's cap, stands)."""
    from training import hevy_note_grammar as g

    if effort_role(e) != "heavy_compound":
        return None
    work, last = cfg.value("effort_targets")["heavy_compound"]
    cap = e.get("live_effort")
    if cap and float(cap) < float(last):
        return None  # a capped lift reads its cap (`live_program._cap_effort`)
    return g.effort_line(work, (work, last))


def _day(w: dict[str, Any]) -> str:
    return str(w.get("date") or str(w.get("sk") or "")[5:15])[:10]


def history(workouts: Any, tids: set[str]) -> dict[str, list[dict[str, Any]]]:
    """Template id -> its logged exposures, most recent first: {date, role, sets: [{kg, reps, rpe}]} (working sets with a load)."""
    from training.fatigue_model import session_role

    out: dict[str, list[dict[str, Any]]] = {}
    for w in workouts or []:
        role, day = session_role(w), _day(w)
        for x in w.get("exercises") or []:
            tid = str(x.get("template_id") or "").upper()
            if tid not in tids:
                continue
            sets = [
                {"kg": float(s["weight_kg"]), "reps": int(s["reps"]), "rpe": float(s["rpe"]) if s.get("rpe") is not None else None}
                for s in x.get("sets") or []
                if str(s.get("type") or "normal") != "warmup" and s.get("weight_kg") and s.get("reps")
            ]
            if sets:
                out.setdefault(tid, []).append({"date": day, "role": role, "sets": sets})
    for rows in out.values():
        rows.sort(key=lambda r: r["date"], reverse=True)
    return out


def same_role(rows: list[dict[str, Any]], role: str, target_date: str, rep_lo: int, rep_hi: int) -> list[dict[str, Any]]:
    """The exposures of today's session role in the window, most recent first (fix round 10: explicit role, then the band, then
    recency). A row its title names today's role counts; a row whose title names NO role counts when its top set sits in today's
    band (one under the floor at most, never over the top; a heavy day has no lower band to leak from, so any reps under its top).
    Both kinds merge by date, so a new untitled session is never ignored for an older titled one."""
    from common.pacific_time import shift_day_key

    since = shift_day_key(target_date, -int(cfg.value("history_days")))
    heavy = "heavy" in str(role or "")
    out = []
    for r in rows:
        if not since <= r["date"] < target_date:
            continue
        reps = _top(r)["reps"]
        if (role and r["role"] == role) or (not r["role"] and reps <= max(rep_hi, rep_lo) and (heavy or reps >= rep_lo - 1)):
            out.append(r)
    return sorted(out, key=lambda r: (r["date"], bool(r["role"])), reverse=True)


def _top(r: dict[str, Any]) -> dict[str, Any]:
    return max(r["sets"], key=lambda s: (s["kg"], s["reps"]))


def e1rm(r: dict[str, Any]) -> float:
    """Effort-adjusted Epley of an exposure's top set (reps + reps in reserve, RPE clamped 6-10; unlogged reads as 8)."""
    t = _top(r)
    rpe = t["rpe"] if t["rpe"] is not None else 8.0
    return t["kg"] * (1 + (t["reps"] + 10.0 - min(10.0, max(6.0, rpe))) / 30.0)


def read_e1rm(r: dict[str, Any]) -> float:
    """The decline read (rule 4): effort-adjusted Epley with the logged RPE clamped to 6-9 — a set logged 9.5-10 reads as RPE 9, so
    an RPE-10 habit never manufactures a decline while the reps at the load hold; unlogged reads as 8."""
    t = _top(r)
    rpe = min(9.0, max(6.0, t["rpe"] if t["rpe"] is not None else 8.0))
    return t["kg"] * (1 + (t["reps"] + 10.0 - rpe) / 30.0)


def effort_unknown(rows: list[dict[str, Any]]) -> bool:
    """Rule 3: the logged RPE carries no information — no RPE on any set of the window's same-role exposures, or every logged
    set at >= implausible_rpe (a lifter who logs 10 on every set, whatever the reps). Progress then rides on reps and load only,
    and the lift never steps down on effort."""
    rpes = [s["rpe"] for r in rows for s in r["sets"]]
    known = [x for x in rpes if x is not None]
    return not known or all(x >= float(cfg.value("implausible_rpe")) for x in known)


def below_floor(rows: list[dict[str, Any]], rep_lo: int, n: int | None = None) -> bool:
    """Rule 2: each of the last `below_floor_exposures` (or `n`) same-role exposures had its top set under `rep_lo` (reps only)."""
    n = int(cfg.value("below_floor_exposures")) if n is None else n
    return len(rows) >= n and all(_top(r)["reps"] < rep_lo for r in rows[:n])


def floor_load(r: dict[str, Any], rep_lo: int) -> float:
    """The load exposure `r` says reaches `rep_lo` reps with three in reserve (its decline read, `read_e1rm`): the step-down's size
    when one 5% step would leave him under the floor again — the margin covers a week more of a fast decline (3 %/week is about
    one rep), so a declining lift is not under the floor again at the next exposure."""
    return read_e1rm(r) / (1 + (rep_lo + 3.0) / 30.0)


def topped(r: dict[str, Any], rep_hi: int, target_rpe: float, unknown: bool) -> bool:
    """Rule 1: every set at the exposure's top load reached the top of the range, at or under the target RPE (or effort unknown)."""
    load = _top(r)["kg"]
    at = [s for s in r["sets"] if s["kg"] >= load - 0.2]
    return all(s["reps"] >= rep_hi for s in at) and (unknown or all(s["rpe"] is None or s["rpe"] <= target_rpe for s in at))


def declining(rows: list[dict[str, Any]]) -> bool:
    """Rule 4: the ONE performance read (`fatigue_model.declined`) over this lift's same-role decline reads (most recent first)."""
    from training.fatigue_model import declined

    return declined([read_e1rm(r) for r in reversed(rows)])


def slump(hist: dict[str, list[dict[str, Any]]], anchor_tids: set[str], deficit: bool | None, target_date: str) -> dict[str, Any] | None:
    """Rule 4: {declining, judged} when the anchors decline together (`slump_anchors`, or half of them in a deficit), else None.
    Each anchor is judged per session role (the role of its latest exposure)."""
    from common.pacific_time import shift_day_key

    since = shift_day_key(target_date, -int(cfg.value("history_days")))
    judged, down = 0, []
    for tid in sorted(anchor_tids):
        rows = [r for r in hist.get(tid) or [] if since <= r["date"] < target_date]
        if len(rows) < 3:
            continue
        rows = [r for r in rows if r["role"] == rows[0]["role"]]
        judged += 1
        if declining(rows):
            down.append(tid)
    need = int(cfg.value("slump_anchors"))
    if len(down) >= need or (deficit and judged >= need and len(down) * 2 >= judged and len(down) >= 3):
        return {"declining": len(down), "judged": judged}
    return None


def layoff(workouts: Any, target_date: str) -> dict[str, Any] | None:
    """Rule 5: the latest gap of `layoff_days`+ with no logged session before `target_date` — {gap_days, last, end} — or None."""
    from common.pacific_time import parse_day_key

    days = sorted(
        {_day(w) for w in workouts or [] if _day(w) and _day(w) < target_date and any(x.get("sets") for x in w.get("exercises") or [])}
    )
    points = days + [target_date]
    for a, b in reversed(list(zip(points, points[1:]))):
        da, db = parse_day_key(a), parse_day_key(b)
        if da is not None and db is not None and (db - da).days >= int(cfg.value("layoff_days")):
            return {"gap_days": (db - da).days, "last": a, "end": b}
    return None


def _floor_to_implement(kg: float, equipment: str | None) -> float:
    from training.rep_scheme import implement_step_lb, load_step_kg

    lb = kg / KG_PER_LB
    step = implement_step_lb(equipment, lb)
    if not step:
        return load_step_kg(kg, down=True)
    return math.floor(lb / step + 1e-9) * step * KG_PER_LB


def _step_up(kg: float, equipment: str | None) -> float:
    from training.rep_scheme import implement_step_lb

    lb = kg / KG_PER_LB
    step = implement_step_lb(equipment, lb) or 5.0
    return (round(lb / step) * step + step) * KG_PER_LB


def decide(
    rows: list[dict[str, Any]],
    rep_lo: int,
    rep_hi: int,
    equipment: str | None,
    *,
    hold: str | None = None,
    target_rpe: float | None = None,
    layoff_days: int | None = None,
    top_set: bool = False,
) -> dict[str, Any] | None:
    """One lift's load: {kg, mode: up|hold|down, why, clause} from its same-role exposures (most recent first, the NEWEST is the
    reference), or None (no exposure in the window: the engine's own load stands). Two rules (module doc 1-2): DOWN when the top
    set sat under the floor in the last two exposures — first, so nothing blocks it; UP at the top of the range at or under
    `target_rpe` (the lift's own effort cap when it has one: the capped deadlift steps up after an easy top set) unless `hold`
    (the day's or the lift's reason: a slump, a strained day, a pain flag, a first session back) stops it. `layoff_days`: a first
    session back after `long_layoff_days`+ starts `long_layoff_pct` under the last load (rule 5). Pure."""
    if not rows:
        return None
    target_rpe = step_rpe() if target_rpe is None else target_rpe
    last = _top(rows[0])["kg"]
    if below_floor(rows, rep_lo):  # at least one step; enough to reach the floor again on the last exposure's own read
        kg = _floor_to_implement(min(last * (1 - float(cfg.value("step_down_pct")) / 100.0), floor_load(rows[0], rep_lo)), equipment)
        n = int(cfg.value("below_floor_exposures"))
        return {
            "kg": kg,
            "mode": "down",
            "why": f"under {rep_lo} reps {n} sessions running",
            "clause": f"Lighter today: under {rep_lo} reps {n} sessions running.",
        }
    if layoff_days is not None and layoff_days >= int(cfg.value("long_layoff_days")):  # rule 5: the dose scales with the gap
        pct = float(cfg.value("long_layoff_pct"))
        return {
            "kg": _floor_to_implement(last * (1 - pct / 100.0), equipment),
            "mode": "down",
            "why": f"first session back after {layoff_days} days off",
            "clause": f"Lighter today: first session back after {layoff_days} days off.",
        }
    if not hold and topped(rows[0], rep_hi, target_rpe, effort_unknown(rows)):
        return {
            "kg": _step_up(last, equipment),
            "mode": "up",
            "why": f"{rep_hi} reps reached",
            "clause": f"Heavier: {rep_hi} reps reached.",
        }
    if hold:
        return {"kg": last, "mode": "hold", "why": hold, "clause": f"Same load: {hold}."}
    top = _top(rows[0])
    at = [st for st in rows[0]["sets"] if st["kg"] >= top["kg"] - 0.2]
    if all(st["reps"] >= rep_hi for st in at):  # the top of the range reached, at too high an effort for the lift's target
        return {
            "kg": last,
            "mode": "hold",
            "why": f"the top at RPE {target_rpe:g} first",
            "clause": f"Same load: {rep_hi} reps at RPE {target_rpe:g} or less, then up.",
        }
    # fix round 12: every held lift says what moves it (the one load rule, on the lift's own note)
    which = "top set" if top_set else "all sets"  # `top_set`: a top set + back-offs — the top set alone earns the step
    return {"kg": last, "mode": "hold", "why": "reps first", "clause": f"Same load: {which} to {rep_hi} reps, then up."}


def previous_clause(d: dict[str, Any], rows: list[dict[str, Any]], all_rows: list[dict[str, Any]], kind: str, day: str) -> str | None:
    """Fix round 12 (a PREVIOUS load from another day quoted without saying so): Hevy's PREVIOUS column shows his LAST session of
    the template, whatever its day. When that is not the exposure this load was read from (a heavy day before a volume day of the
    same lift) and the row sits more than one implement step from it, the lift's one reason line says so — the standard's own
    `Lighter:` / `Heavier:` word, by the direction against PREVIOUS. A step-down keeps its own reason. None: nothing to say."""
    from training import hevy_note_grammar as g

    prev = next((r for r in all_rows if r["date"] < day), None)
    if prev is None or prev["date"] == rows[0]["date"] or d["mode"] == "down":
        return None
    row_lb, prev_lb = d["kg"] / KG_PER_LB, _top(prev)["kg"] / KG_PER_LB
    word = g.delta_word(row_lb, prev_lb, g.implement_step_lb(kind, prev_lb))
    if not word:
        return None
    return f"{word}: PREVIOUS was the {'heavy' if word == g.LIGHTER else 'volume'} day."


# ── novelty ──────────────────────────────────────────────────────────────────
def familiar_patterns(workouts: Any, lib: dict[str, Any] | None, target_date: str) -> set[str]:
    """The library patterns he logged in the last `familiar_days` (rule 7: familiar, a similar swap included)."""
    from common.pacific_time import shift_day_key

    from training import fatigue_model as fm

    idx = fm.library_index(lib)
    since = shift_day_key(target_date, -int(cfg.value("familiar_days")))
    out = set()
    for w in workouts or []:
        if since <= _day(w) < target_date:
            for x in w.get("exercises") or []:
                pat = (idx.get(str(x.get("template_id") or "").upper()) or {}).get("pattern")
                if pat and x.get("sets"):
                    out.add(str(pat))
    return out


def mark_novelty(rx: dict[str, Any], ctx: dict[str, Any], workouts: Any) -> None:
    """IN PLACE: each exposure's novelty state — `live_familiar` (a familiar pattern: normal effort, no re-entry cap), a NEW pattern
    capped at `new_pattern_rpe` for this one exposure, `live_first_back` (rule 5, RPE 8, no step). Stores the layoff on ctx."""
    target = str(ctx.get("target_date") or "")
    seen = familiar_patterns(workouts, ctx.get("lib"), target)
    gap = layoff(workouts, target)
    ctx["layoff"] = gap
    from training.fatigue_model import session_role

    role = str(rx.get("session_role") or "")
    since = {  # fix round 11: keyed by session role — a heavy and a volume day of one template are two lifts (rule 5 per lift)
        (str(x.get("template_id") or "").upper(), session_role(w))
        for w in workouts or []
        if gap and gap["end"] <= _day(w)
        for x in w.get("exercises") or []
    }
    logged = {str(x.get("template_id") or "").upper() for w in workouts or [] for x in w.get("exercises") or [] if x.get("sets")}
    for e in rx.get("exposures") or []:
        if e.get("intensity") == "carry":
            continue
        entry = _lib(e, ctx)
        tid = tid_of(e.get("movement_key"), ctx["catalog"], ctx.get("lib"), ctx.get("idx"))
        if gap and tid and tid in logged and (tid, role) not in since and (tid, "") not in since:
            e["live_first_back"] = True
            e["live_effort"] = min(int(cfg.value("first_back_rpe")), int(e.get("live_effort") or 99))
            e["live_familiar"] = True
        elif entry.get("pattern") in seen or (tid and tid in logged and not gap):
            e["live_familiar"] = True
        else:
            e["live_new"] = True
            e["live_effort"] = min(int(cfg.value("new_pattern_rpe")), int(e.get("live_effort") or 99))


def _lib(e: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    lid = ctx["idx"]["to_lib"].get(str(e.get("movement_key"))) if e.get("movement_key") else None
    return ((ctx["lib"].get("movements") or {}).get(lid) or {}) if lid else {}


def familiar_keys(rx: dict[str, Any] | None) -> set[str] | None:
    """The movement keys whose re-entry (OD1) cap and layoff-return line the note composer drops under live (rule 7: a familiar
    pattern works at normal effort; rule 5: a first session back is this model's RPE 8 at the last load, never the OD1 ladder);
    None in shadow (the composer is then exactly as before)."""
    from training import live_session as ls

    if not rx or ls.MARK not in rx:
        return None
    return {str(e.get("movement_key")) for e in rx.get("exposures") or [] if e.get("live_familiar") or e.get("live_first_back")}


# ── the draft hook ───────────────────────────────────────────────────────────
def set_loads(
    blocks: list[Any], rx: dict[str, Any], load_floors: dict[str, Any], movements: dict[str, Any], target_date: str, rationale: list[str]
) -> list[dict[str, Any]]:
    """IN PLACE, live only, after the engine's floor and BEFORE the back-offs and warm-ups (which follow the top set): every lift
    with a same-role exposure in the window takes `decide`'s load. The audit row the commit gate reuses gets the load and a
    `live_load` record. Returns the decisions (also on `rx[live_session.MARK]["load_guard"]`)."""
    from training import live_session as ls

    if ls.MARK not in (rx or {}):
        return []
    mark = rx[ls.MARK]
    hist = mark.get("hist") or {}
    role = str(rx.get("session_role") or "")
    fat = rx.get("fatigue") or {}
    hold_all = mark.get("hold_all") or (
        "recovery first" if fat.get("state") in ("strained", "overreached") or fat.get("action") == "deload_recommended" else None
    )
    by_key = {e.get("movement_key"): e for e in rx.get("exposures") or []}
    rows_out = (load_floors or {}).get("movements") or {}
    from training import selection_engine as se

    lib = se.load_library_failsoft() or {}
    idx = se.key_index(lib, movements)
    out = []
    for b in blocks:
        e = by_key.get(b.movement_key) or {}
        entry = movements.get(b.movement_key) or {}
        tid = tid_of(b.movement_key, movements, lib, idx)
        work = [s for s in b.sets if str(getattr(s, "type", "") or "normal") != "warmup" and getattr(s, "weight_kg", None) is not None]
        if not e or not tid or e.get("intensity") == "carry" or not work:
            continue
        lo = min(int(getattr(s, "rep_range_start", 0) or 0) or 99 for s in work)
        hi = max(int(getattr(s, "rep_range_end", 0) or 0) for s in work) or lo
        lo = lo if lo != 99 else hi
        tmpl = [r for r in (x.get("reps") for x in e.get("sets") or []) if isinstance(r, list | tuple) and r]
        if tmpl and (min(int(r[0]) for r in tmpl), max(int(r[-1]) for r in tmpl)) != (lo, hi):
            # fix round 11: the ONE model judges the prescription's own range — the engine's rep step ("+2 reps to 6", #5052)
            # moved the floor under it and the next session read 4 reps in a 4-6 range as "under 6" (a second rule, undone here)
            lo, hi = min(int(r[0]) for r in tmpl), max(int(r[-1]) for r in tmpl)
            for s in work:
                s.rep_range_start, s.rep_range_end = lo, hi
        lift_role = str(e.get("live_full_body") or role)  # fix round 12: a full-body guest is its partner role's lift
        rows = same_role(hist.get(tid) or [], lift_role, target_date, lo, hi)
        if not rows and hold_all:  # a hold day holds a lift with no same-role exposure at its latest load of any role
            rows = same_role([r | {"role": ""} for r in hist.get(tid) or []], "", target_date, 0, 99)
        flag = e.get("live_load") or {}
        hold = "first session back" if e.get("live_first_back") else (str(flag.get("why") or "held") if flag.get("hold") else hold_all)
        gap = int((mark.get("layoff") or {}).get("gap_days") or 0) if e.get("live_first_back") else None
        target = step_rpe(e)  # the role's working RPE (`effort_targets`), or the lift's own cap
        shaped = any(x.get("kind") == "top" for x in e.get("sets") or [])
        d = decide(rows, lo, hi, entry.get("equipment"), hold=hold, target_rpe=target, layoff_days=gap, top_set=shaped)
        if d is None:
            continue
        for s in work:
            s.weight_kg = d["kg"]
        from training import hevy_note_lint

        other = previous_clause(d, rows, hist.get(tid) or [], hevy_note_lint.kind_of(str(b.movement_key), entry), target_date)
        d = d | ({"clause": other} if other else {})
        rec = {"key": b.movement_key, **d, "last": {"date": rows[0]["date"], "role": rows[0]["role"], **_top(rows[0])}}
        out.append(rec)
        row = rows_out.get(b.movement_key)
        if row is not None:
            row["floor_kg"] = d["kg"]
            row["live_load"] = rec
            row["progression"] = {**(row.get("progression") or {}), "basis": d["mode"], "changes": [], "live_guard": True}
        t = rec["last"]
        mark.setdefault("lines", []).append(
            f"load (live): {entry.get('title') or b.movement_key} {_lb(d['kg'])} lb — {d['mode']}: {d['why']} (last "
            f"{(t['role'] or 'same band').replace('_', ' ')} {_lb(t['kg'])} lb x {t['reps']}"
            + (f" @ RPE {t['rpe']:g}" if t["rpe"] is not None else ", no RPE")
            + ")"
        )
    mark["load_guard"] = out
    if load_floors is not None:  # rule 7: the note composer drops the re-entry cap and layoff line on a familiar pattern
        load_floors["live_familiar"] = sorted(familiar_keys(rx) or ())
    return out


def tid_of(key: Any, movements: dict[str, Any], lib: dict[str, Any] | None, idx: dict[str, Any] | None = None) -> str:
    """A movement's Hevy template id: the catalog's hint, else (a title-only catalog entry) its library row's template."""
    hint = (movements.get(str(key)) or {}).get("hevy_template_id_hint")
    if hint:
        return str(hint).upper()
    lid = ((idx or {}).get("to_lib") or {}).get(str(key))
    return str((((lib or {}).get("movements") or {}).get(lid) or {}).get("template_id") or "").upper()


def _lb(kg: float) -> str:
    return f"{round(kg / KG_PER_LB * 2) / 2:g}"


def slump_trim(rx: dict[str, Any], keep: set[str] | None = None) -> list[str]:
    """IN PLACE, rule 4's volume answer: each NON-PRIORITY accessory loses about a third of its working sets (never under 2); an
    accessory for a priority muscle (`keep`, its movement keys) keeps its sets (fix round 10: the ninth red team's slump trimmed
    the priority chest fly harder than the curls). Returns the line."""
    cut = float(cfg.value("slump_accessory_cut"))
    floor = int(cfg.value("slot_min_sets"))
    taken = 0
    for e in rx["exposures"]:
        if e.get("kind") != "accessory" or str(e.get("movement_key")) in (keep or set()):
            continue
        n = len(e.get("sets") or [])
        keep_n = max(floor, n - int(round(n * cut)))
        taken += max(0, n - keep_n)
        e["sets"] = list(e["sets"])[:keep_n] if n > keep_n else e["sets"]
    return [f"slump (live): non-priority accessories -{taken} set(s) (about a third), no load steps up"] if taken else []
