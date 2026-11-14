"""live_load.py — THE one progression model of the live engine (#5861, fix round 9: consolidation). LIVE only.

Fix rounds 1-8 stacked eight load rules on the engine's template-keyed progression (a regression cut, an overshoot cut, a grind
hold, an evidence rule, one-retreat-a-week, a stall reset with a rep-scheme change, reset detection with a rebuild window, a
deficit hold) — and each one compensated for another. The eighth red team still found a ratchet (one Hevy template on a heavy
AND a volume day: 160 -> 140 -> 125 -> 160 on real data), a collapse under unreliable RPE (RPE 10 logged on every set: bench
185 -> 105 in five weeks) and a cascade of six 10% cuts in one week on a lifter losing 0.5% a week. Round 9 replaces all of
them with ONE model, keyed by SESSION ROLE (a heavy day and a volume day are two lifts, even on one template):

  1. DOUBLE PROGRESSION. The load is the lift's last same-role top load. When every set at that load reached the top of the
     rep range (at or under the target RPE, or with effort unknown), it steps up one implement step; otherwise it HOLDS and the
     reps climb. Nothing else moves a load up.
  2. ONE EVIDENCE-GATED STEP-DOWN. Three same-role exposures in a row each under the previous best e1RM AND each with its sets
     logged above the target RPE -> 5% down, once. Any set at or under the target RPE vetoes it. After a step-down the next
     three exposures are new evidence, so a lift steps down at most once per three exposures.
  3. EFFORT UNKNOWN. RPE missing on every set, or >= 9.5 on every set while reps at the load rise: the lift progresses on reps
     and load only and NEVER steps down on effort.
  4. SYSTEMIC SLUMP. Four or more anchors declining together (or, in a deficit, half or more): every load HOLDS (no step either
     way) and accessories lose about a third of their sets (`slump_trim`). Never a cut on every anchor.
  5. FIRST SESSION BACK (owner ruling #10). 10+ days with no session: each lift's first session back runs at RPE 8 at its last
     same-role load, no step.
  6. THE SECOND LIFT (owner ruling 5). The heavy-lower lift that does not lead runs at RPE 7-8, loaded from its own same-role
     e1RM at that band.
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
TARGET_RPE = 9.0
"""The top of the working effort band (RPE 8-9, last set 9-10 on isolation): a set logged ABOVE it is a grind."""


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
    """The exposures of today's session role in the window (most recent first). A row whose role the title does not name counts
    only when its top set's reps sit in today's band (two under its floor at most, never over its top)."""
    from common.pacific_time import shift_day_key

    since = shift_day_key(target_date, -int(cfg.value("history_days")))
    rows = [r for r in rows if since <= r["date"] < target_date]
    same = [r for r in rows if role and r["role"] == role]
    if same:
        return same
    return [r for r in rows if not r["role"] and rep_lo - 2 <= _top(r)["reps"] <= max(rep_hi, rep_lo)]


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


def step_down_due(rows: list[dict[str, Any]], target_rpe: float = TARGET_RPE) -> bool:
    """Rule 2: the last `step_down_exposures` same-role exposures, all at ONE load (a step-down or any load change restarts the
    count), each with fewer top-set reps than the best done at that same load before them AND each with every set logged ABOVE the
    target RPE. One set at or under it vetoes; effort unknown vetoes."""
    n = int(cfg.value("step_down_exposures"))
    if len(rows) < n + 1 or effort_unknown(rows):
        return False
    load = _top(rows[0])["kg"]
    if any(abs(_top(r)["kg"] - load) > 0.2 for r in rows[:n]):
        return False
    base = [b for b in rows[n:] if abs(_top(b)["kg"] - load) <= 0.2]  # the best done AT THIS LOAD before the three
    if not base:
        return False
    best = max(_top(b)["reps"] for b in base)
    for i in range(n):
        r = rows[i]
        if _top(r)["reps"] >= best:
            return False
        if any(s["rpe"] is None or s["rpe"] <= target_rpe for s in r["sets"]):
            return False
    return True


def topped(r: dict[str, Any], rep_hi: int, target_rpe: float, unknown: bool) -> bool:
    """Rule 1: every set at the exposure's top load reached the top of the range, at or under the target RPE (or effort unknown)."""
    load = _top(r)["kg"]
    at = [s for s in r["sets"] if s["kg"] >= load - 0.2]
    return all(s["reps"] >= rep_hi for s in at) and (unknown or all(s["rpe"] is None or s["rpe"] <= target_rpe for s in at))


def declining(rows: list[dict[str, Any]]) -> bool:
    """A lift whose same-role e1RM fell `decline_pct`+ over its last three exposures and did not recover in between."""
    if len(rows) < 3:
        return False
    drop = float(cfg.value("decline_pct"))
    return read_e1rm(rows[0]) <= read_e1rm(rows[1]) and read_e1rm(rows[0]) < read_e1rm(rows[2]) * (1 - drop)


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


def lead_rows(rows: list[dict[str, Any]], e: dict[str, Any]) -> list[dict[str, Any]]:
    """The heavy-lower exposures in which this lift LED (owner ruling 5: the lead alternates by ISO week, `live_rulings.lead_of`):
    a lead's load progresses from its own lead days, never from the capped second-lift day before it. All rows when none led."""
    from training.live_rulings import lead_of

    pattern = str(e.get("pattern") or "")
    own = [r for r in rows if lead_of(r["date"]) == pattern]
    return own or rows


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
    hold_all: str | None = None,
    second_band: tuple[int, int] | None = None,
    first_back: bool = False,
    cut: tuple[int, str] | None = None,
) -> dict[str, Any] | None:
    """One lift's load: {kg, mode: up|hold|down|second, why, clause} from its same-role exposures (most recent first), or None
    (no exposure in the window: the engine's own load stands). `hold_all`: the day's reason every load holds (a slump, a strained
    day); `cut` (pct, why): a joint flag's reduction (the pain rule, not progression). Pure."""
    if not rows:
        return None
    last = _top(rows[0])["kg"]
    if cut:
        return {
            "kg": _floor_to_implement(last * (1 - cut[0] / 100.0), equipment),
            "mode": "down",
            "why": cut[1],
            "clause": f"Lighter today: {cut[1]}.",
        }
    unknown = effort_unknown(rows)
    if second_band:  # rule 6: its own e1RM at the lower band (a logged 9.5-10 read as 9: never a collapse on unreliable RPE)
        lo, hi = second_band
        t = _top(rows[0])
        best = t["kg"] * (1 + (t["reps"] + 10.0 - min(9.0, max(6.0, t["rpe"] if t["rpe"] is not None else 8.0))) / 30.0)
        kg = min(_floor_to_implement(best / (1 + (rep_lo + 10.0 - (lo + hi) / 2) / 30.0), equipment), last)
        return {"kg": kg, "mode": "second", "why": f"the second lift: RPE {lo}-{hi}", "clause": f"RPE {lo}–{hi} today: the second lift."}
    if first_back:
        return {"kg": last, "mode": "hold", "why": "first session back", "clause": "Same load: first session back."}
    if hold_all:
        return {"kg": last, "mode": "hold", "why": hold_all, "clause": f"Same load: {hold_all}."}
    if step_down_due(rows):
        kg = _floor_to_implement(last * (1 - float(cfg.value("step_down_pct")) / 100.0), equipment)
        n = int(cfg.value("step_down_exposures"))
        return {"kg": kg, "mode": "down", "why": f"{n} sessions under best, all grinds", "clause": f"Lighter today: {n} grinding sessions."}
    if topped(rows[0], rep_hi, TARGET_RPE, unknown):
        return {
            "kg": _step_up(last, equipment),
            "mode": "up",
            "why": f"{rep_hi} reps reached",
            "clause": f"Heavier: {rep_hi} reps reached.",
        }
    return {"kg": last, "mode": "hold", "why": "reps first", "clause": f"Same load: build to {rep_hi} reps."}


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
    since = {
        str(x.get("template_id") or "").upper() for w in workouts or [] if gap and gap["end"] <= _day(w) for x in w.get("exercises") or []
    }
    logged = {str(x.get("template_id") or "").upper() for w in workouts or [] for x in w.get("exercises") or [] if x.get("sets")}
    for e in rx.get("exposures") or []:
        if e.get("intensity") == "carry":
            continue
        entry = _lib(e, ctx)
        tid = tid_of(e.get("movement_key"), ctx["catalog"], ctx.get("lib"), ctx.get("idx"))
        if gap and tid and tid in logged and tid not in since:
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
    """The movement keys whose re-entry (OD1) cap and layoff-return line the note composer drops under live (rule 7); None in
    shadow (the composer is then exactly as before)."""
    from training import live_session as ls

    if not rx or ls.MARK not in rx:
        return None
    return {str(e.get("movement_key")) for e in rx.get("exposures") or [] if e.get("live_familiar") and not e.get("live_first_back")}


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
        rows = same_role(hist.get(tid) or [], role, target_date, lo, hi)
        if not rows and hold_all:  # a hold day holds a lift with no same-role exposure at its latest load of any role
            rows = same_role([r | {"role": ""} for r in hist.get(tid) or []], "", target_date, 0, 99)
        band = tuple(e["live_effort_band"]) if e.get("live_lead") == "second" and e.get("live_effort_band") else None
        led = lead_rows(rows, e) if e.get("live_lead") else rows  # rule 6: a lead progresses from its own LEAD exposures
        flag = e.get("live_load") or {}
        cut = (int(flag["pct"]), str(flag.get("why") or "joint flag")) if flag.get("pct") else None
        d = decide(
            rows if band else led,
            lo,
            hi,
            entry.get("equipment"),
            hold_all=hold_all or flag.get("why") if flag.get("hold") else hold_all,
            second_band=band,
            first_back=bool(e.get("live_first_back")),
            cut=cut,
        )
        if d is None:
            continue
        engine = max(float(s.weight_kg) for s in work)
        for s in work:
            s.weight_kg = d["kg"]
        # the note's reason line only where it changes what he reads: the engine's own load and reason stand when they agree
        quiet = abs(engine - float(d["kg"])) < 0.2 and d["mode"] in ("up", "hold") and not e.get("live_first_back")
        d = d | ({"clause": None} if quiet else {})
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


def slump_trim(rx: dict[str, Any]) -> list[str]:
    """IN PLACE, rule 4's volume answer: each accessory loses about a third of its working sets (never under 2). Returns the line."""
    cut = float(cfg.value("slump_accessory_cut"))
    floor = int(cfg.value("slot_min_sets"))
    taken = 0
    for e in rx["exposures"]:
        if e.get("kind") != "accessory":
            continue
        n = len(e.get("sets") or [])
        keep = max(floor, n - int(round(n * cut)))
        taken += max(0, n - keep)
        e["sets"] = list(e["sets"])[:keep] if n > keep else e["sets"]
    return [f"slump (live): accessories -{taken} set(s) (about a third), every load held"] if taken else []
