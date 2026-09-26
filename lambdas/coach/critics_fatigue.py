"""critics_fatigue.py — the joints/tendons critic's two rules the 2026-09-24 red team rewrote (#4161).

WHY THIS EXISTS

#4149 made every critic number deterministic. The evidence red team of 2026-09-24 (S&C coach,
tendon physio, obesity/body-composition researcher, sport scientist; ~28 opened sources) then
argued with two of those numbers, and the owner approved its recommendations the same day:

  (i)  THE STALE-LIFT CAP. #4149 capped a lift last performed >= 28 days ago at 2 working sets
       on its first session back, whatever the gap. The repeated-bout effect lasts >= 6 months
       (Nosaka 2001 MSSE 33(9):1490; Chen 2012 MSSE 44(11):2090): a lift trained within ~6
       months keeps most of its protection, one not trained for longer (or never) keeps none.
       So the cap now scales with the gap and runs over EXPOSURES, not one session:

         gap 28 d – 6 months          -> 2 working sets on exposure 1 only
         gap > 6 months, or never     -> 2 on exposures 1–2, 3 on exposure 3
         RPE <= 7 for the first 3 exposures — unchanged (`owner_redlines` gain_rule).

  (ii) THE FATIGUE TRIGGER. #4149's trigger was a consecutive-LOADED-day streak (the upper tail
       of his own 2024–25 record). A day count is not a validated fatigue signal (Kataoka 2022
       Sports Med 52(1):25; Yang 2018 Front Physiol 9:725); coaches trigger on PERFORMANCE or
       READINESS (Bell 2023 Sports Med Open 9:87, the deload Delphi; Rogerson 2024 Sports Med
       Open doi:10.1186/s40798-024-00691-y). The trigger is now either of:

         performance — the top-set load >= 5 % below the REFERENCE (the last same-session-role
                       exposure before the drop — so a volume day never reads as a drop from a
                       heavy day), at target RPE, on 2 consecutive exposures; a sustained drop fires;
         readiness   — the readiness floor (Whoop recovery, `owner_redlines` `readiness_floor`)
                       low on 2 consecutive days, OR a soreness/pain note on a drafted lift on
                       2 consecutive TRAINING days (the existing pain-flag dates).

       The response is unchanged — −30 % sets, loads held — for ONE session, then re-test (the
       trigger is re-evaluated from fresh data before the next session; nothing carries it).
       The loaded streak is still MEASURED and carried as context; it no longer flags.
       A >= 48 h same-region guard is kept: a region loaded the previous Pacific day draws the
       same one-session response.

INTERPRETATIONS RECORDED (not owner rulings — each is the smallest reading that makes the rule
computable; the owner can move any without touching the logic):
  * "6 months" = 183 days. A gap longer than the evidence window read (the caller's history
    lookback) is "> 6 months or never" — the conservative class.
  * "at target RPE" = the dropped exposure's top-set RPE is >= the heavy exposure's lower RPE
    (7). A top set with NO logged RPE counts, and the reason says it was unlogged — a fatigue
    trigger that needs a number he rarely logs would never fire.
  * "2 consecutive training days" for readiness = 2 consecutive calendar days below the floor
    (he walks every day, so every day is a training day); for soreness = two consecutive
    COMPLETED program sessions each carrying a pain note on a drafted lift.
  * The 48 h guard is at Pacific-day grain: a region loaded yesterday is < 48 h; two days ago
    is not. The region of a performed session is the region of the ANCHOR patterns it carried
    (`program_structure.classify_movement`); an accessory-only log claims no region.

Pure: every input is injected. `tools_plan` gathers them (`mcp.plan_draft_evidence`).
"""

from __future__ import annotations

from typing import Any, Iterable

from common.pacific_time import parse_day_key

ISSUE = "#4161"

# ── (i) the stale-lift cap ────────────────────────────────────────────────────────────
STALE_SHORT_GAP_DAYS = 28
STALE_LONG_GAP_DAYS = 183
STALE_CAPS: dict[str, dict[int, int]] = {"short": {1: 2}, "long": {1: 2, 2: 2, 3: 3}}
STALE_PROVENANCE: dict[str, Any] = {
    "provenance": "population-derived",
    "evidence": (
        "the repeated-bout effect lasts >= 6 months: Nosaka 2001 MSSE 33(9):1490; Chen 2012 MSSE 44(11):2090 — so a lift back "
        "inside 6 months needs one easy exposure, one back after longer (or never trained) needs three"
    ),
    "approved": "owner, 2026-09-24 (the red team's recommendation)",
    "short_gap_days": "28 = #4149's NOVEL_AGAIN_DAYS, unchanged",
    "long_gap_days": "183 = 6 months (interpretation recorded)",
    "issue": ISSUE,
}

# ── (ii) the fatigue trigger ──────────────────────────────────────────────────────────
PERF_DROP_PCT = 5.0
PERF_DROP_CONSECUTIVE = 2
TARGET_RPE_LOW = 7.0
READINESS_CONSECUTIVE_DAYS = 2
SORENESS_CONSECUTIVE_SESSIONS = 2
SAME_REGION_MIN_HOURS = 48
FATIGUE_RESPONSE: dict[str, Any] = {"sets_pct": -30, "loads": "held", "sessions": 1, "then": "re-test"}
FATIGUE_PROVENANCE: dict[str, Any] = {
    "provenance": "population-derived",
    "evidence": (
        "trigger on performance or readiness, not a day count: Bell 2023 Sports Med Open 9:87 (deload Delphi); Rogerson 2024 "
        "Sports Med Open doi:10.1186/s40798-024-00691-y; a loaded-day streak is not a validated fatigue signal (Kataoka 2022 "
        "Sports Med 52(1):25; Yang 2018 Front Physiol 9:725)"
    ),
    "response": "−30 % sets, loads held, ONE session, then re-test — the owner's signed cut (v3), unchanged",
    "approved": "owner, 2026-09-24 (the red team's recommendation)",
    "issue": ISSUE,
}


def _days(a: str, b: str) -> int | None:
    pa, pb = parse_day_key(str(a)[:10]), parse_day_key(str(b)[:10])
    return None if pa is None or pb is None else (pb - pa).days


# ── (i) ───────────────────────────────────────────────────────────────────────────────
def stale_exposure(dates: Iterable[str], target_date: str, *, window_start: str | None = None) -> dict[str, Any]:
    """Which exposure of a return from a gap the drafted session is, and the gap's class.

    `dates` are the days this lift (one identity) was performed, any order, before `target_date`.
    The run of exposures since the last gap >= STALE_SHORT_GAP_DAYS is walked back from the
    target; the drafted session is exposure len(run) + 1. `gap_class`: `short` (28 d – 6 mo),
    `long` (> 6 mo, never, or before `window_start` — unknowable here, so the conservative class),
    or `none` (no qualifying gap: the lift is current)."""
    ds = sorted({str(d)[:10] for d in dates if d and str(d)[:10] < target_date})
    run: list[str] = []
    cursor = target_date
    gap: int | None = None
    for d in reversed(ds):
        g = _days(d, cursor)
        if g is not None and g >= STALE_SHORT_GAP_DAYS:
            gap = g
            break
        run.insert(0, d)
        cursor = d
    else:
        # no gap inside what was read: never trained (run empty), or a run reaching back to the window's
        # edge — current for the whole window, so not a return at all
        edge = _days(window_start, run[0]) if (run and window_start) else None
        if edge is not None and edge < STALE_SHORT_GAP_DAYS:
            return {"exposure": len(run) + 1, "gap_days": None, "gap_class": "none", "run_start": run[0], "window_start": window_start}
    cls = "long" if gap is None or gap >= STALE_LONG_GAP_DAYS else "short"
    return {"exposure": len(run) + 1, "gap_days": gap, "gap_class": cls, "run_start": run[0] if run else None, "window_start": window_start}


def stale_cap(info: dict[str, Any] | None) -> int | None:
    """The working-set cap for the drafted exposure, or None when no cap applies."""
    if not info:
        return None
    return STALE_CAPS.get(str(info.get("gap_class")), {}).get(int(info.get("exposure") or 0))


# ── (ii) ──────────────────────────────────────────────────────────────────────────────
def _top(session: dict[str, Any]) -> tuple[float | None, float | None]:
    """(top-set load lb, that set's RPE) of one exercise-history session."""
    w = session.get("best_weight")
    rpe = None
    for s in session.get("sets") or []:
        if s.get("weight_lbs") is not None and w is not None and float(s["weight_lbs"]) == float(w) and s.get("rpe") is not None:
            rpe = float(s["rpe"])
    return (float(w) if w is not None else None), rpe


def performance_drop(sessions: list[dict[str, Any]], role_by_date: dict[str, str] | None, role: str | None) -> dict[str, Any]:
    """The top-set trend over this lift's exposures IN THE SAME SESSION ROLE (oldest first).

    `triggered` when each of the last PERF_DROP_CONSECUTIVE exposures has a top set >= PERF_DROP_PCT %
    below the REFERENCE — the last same-role exposure BEFORE them — at target RPE (or unlogged RPE,
    named). A SUSTAINED drop (200 -> 190 -> 190) fires; a dip and recovery (200 -> 198 -> 200) does not.
    (#4161 review: comparing each exposure with the one before it missed the sustained case.)
    Fewer exposures than the rule needs is `insufficient`, never a clear."""
    if not role or role_by_date is None:
        return {"state": "unknown", "reason": "the session role of past exposures is unknown (the session sequence was not read)"}
    same = [s for s in sessions if role_by_date.get(str(s.get("date"))[:10]) == role]
    tops = [(str(s.get("date"))[:10], *_top(s)) for s in same]
    tops = [t for t in tops if t[1]]
    need = PERF_DROP_CONSECUTIVE + 1
    out: dict[str, Any] = {"role": role, "exposures": [{"date": d, "top_lbs": w, "rpe": r} for d, w, r in tops[-need:]]}
    if len(tops) < need:
        return {**out, "state": "insufficient", "reason": f"{len(tops)} {role} exposure(s) with a top set — the rule needs {need}"}
    ref_date, ref, _ = tops[-need]
    out["reference"] = {"date": ref_date, "top_lbs": ref}
    drops, unlogged, pcts = [], [], []
    for _d1, w1, r1 in tops[-PERF_DROP_CONSECUTIVE:]:
        pct = round((ref - w1) / ref * 100.0, 1)
        drops.append(pct >= PERF_DROP_PCT and (r1 is None or r1 >= TARGET_RPE_LOW))
        if r1 is None:
            unlogged.append(_d1)
        pcts.append(pct)
    out.update(drop_pct=pcts, state="triggered" if all(drops) else "clear", rpe_unlogged_on=unlogged)
    return out


def soreness_consecutive(pain_dates: Iterable[str], session_dates: list[str]) -> list[str] | None:
    """The first pair of CONSECUTIVE completed sessions both carrying a pain note, newest pair first, or None."""
    notes = {str(d)[:10] for d in pain_dates or []}
    ds = sorted(session_dates or [])
    for a, b in reversed(list(zip(ds, ds[1:]))):
        if a in notes and b in notes:
            return [a, b]
    return None


def regions_of(workout: dict[str, Any]) -> set[str]:
    """The regions (upper / lower) of the ANCHOR patterns a performed Hevy session loaded."""
    from training import program_structure

    upper = set(program_structure._ARCHETYPE_TARGETS["upper"])
    out: set[str] = set()
    for ex in workout.get("exercises") or []:
        kind = program_structure.classify_movement(ex.get("name") or ex.get("exercise_name") or "")
        if not kind.startswith("anchor:"):
            continue
        muscles = set(program_structure.ANCHORS[kind.split(":", 1)[1]]["primary_muscles"])
        out.add("upper" if muscles & upper else "lower")
    return out


def same_region_recent(block_workouts: list[dict[str, Any]] | None, target_date: str, region: str | None) -> dict[str, Any]:
    """Was `region` loaded < SAME_REGION_MIN_HOURS before `target_date` (the previous Pacific day, or earlier the same day)?"""
    if block_workouts is None or not region:
        return {"state": "unknown", "region": region}
    from training import training_streaks

    def _recent(w: dict[str, Any]) -> bool:
        d = _days(str(w.get("date"))[:10], target_date)
        return d is not None and 0 <= d and d * 24 < SAME_REGION_MIN_HOURS

    hits = sorted(
        {
            str(w.get("date"))[:10]
            for w in block_workouts
            if not w.get("tombstone") and _recent(w) and training_streaks.is_loaded_session(w) and region in regions_of(w)
        }
    )
    return {"state": "triggered" if hits else "clear", "region": region, "loaded_on": hits}


def assess(
    *,
    readiness_low_streak_days: int | None,
    perf_by_idx: dict[int, dict[str, Any]] | None,
    soreness_by_idx: dict[int, list[str] | None] | None,
    same_region: dict[str, Any] | None,
    deload_sets_pct: int | None = None,
) -> dict[str, Any]:
    """The one fatigue verdict the joints packet reads: which trigger fired, on what, and the response.

    `deload_sets_pct` is the served session's deload cut when it sits inside the deload window (else None).
    The two cuts never STACK (#4161 review): the larger one is taken — inside the −40 % deload the −30 %
    fatigue response adds nothing (`response.superseded_by_deload`)."""
    fired: list[str] = []
    if readiness_low_streak_days is not None and readiness_low_streak_days >= READINESS_CONSECUTIVE_DAYS:
        fired.append(f"readiness below the floor on {readiness_low_streak_days} consecutive days (>= {READINESS_CONSECUTIVE_DAYS})")
    for i, p in sorted((perf_by_idx or {}).items()):
        if p.get("state") == "triggered":
            unlogged = f"; RPE unlogged on {', '.join(p['rpe_unlogged_on'])}" if p.get("rpe_unlogged_on") else ""
            fired.append(
                f"exercises[{i}]: top set down {p.get('drop_pct')} % on {PERF_DROP_CONSECUTIVE} consecutive {p['role']} exposures{unlogged}"
            )
    for i, pair in sorted((soreness_by_idx or {}).items()):
        if pair:
            fired.append(f"exercises[{i}]: a soreness/pain note on consecutive sessions {pair[0]} and {pair[1]}")
    unknown = []
    if readiness_low_streak_days is None:
        unknown.append("readiness_low_streak_days")
    if perf_by_idx is None:
        unknown.append("performance_drop")
    superseded = deload_sets_pct is not None and int(deload_sets_pct) <= int(FATIGUE_RESPONSE["sets_pct"])
    return {
        "triggered": bool(fired),
        "reasons": fired,
        "same_region_48h": same_region or {"state": "unknown"},
        "response": {**FATIGUE_RESPONSE, "superseded_by_deload": superseded, "deload_sets_pct": deload_sets_pct},
        "unknown": unknown,
    }
