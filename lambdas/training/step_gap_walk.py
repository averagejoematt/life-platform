"""step_gap_walk.py — the walk that closes a day's projected gap to the steps floor (#5758). PURE: no AWS, no clock.

WHY THIS EXISTS

The block-1 retro (#5496) graded Walking F: 9 of 28 measured days at the charter floor, and the lifting days carried
the shortfall (the 2026-10-18 review saw the same). The steps ramp (#5082) and the one steps resolver (#5081) already
MEASURE and PRESCRIBE the floor; the plan only reported it. This module PLACES the walk: the plan (`plan_next_session`
stage 1, `constraint_block.steps_ramp.walk_to_close_gap`, and the drafted routine's stored record,
`inputs_snapshot.critics.steps_walk`) names a walk sized to close the day's projected gap, lifting days included
(charter `steps.lifting_days_included`). The weekly May tracker reads that stored offer back beside the walking
minutes he performed, so a day below the floor is attributable (`attribution`).

THE PROJECTION (stated on every output as `derivation`)
    goal       the steps ramp's `today_target` (`training.steps_ramp`) — the charter `steps.floor` once the trailing
               mean has reached it; below that, the ramp's step toward it (the #5082 overload guard), frozen by a
               lower-leg hold. Never a new number: no ramp target, no walk (state `unknown`).
    projected  the mean resolved steps over the ramp's own trailing window (`steps_ramp.window_days`, the same
               resolver read), counting only days of the SAME KIND as the planned day — a lifting day is a day with
               a LOADED Hevy session (`training_streaks.is_loaded_session`, the one definition), an off day has none.
               Fewer than MIN_KIND_DAYS measured days of that kind -> the mean over every measured day, and `basis`
               says so. A `partial_day` (the vendor cycle still open) is excluded, as the ramp excludes it.
    gap        goal - projected
    walk       `steps_nudge.walk_minutes(gap)`: gap / 100 steps per min, rounded up to 5 min — the evening nudge's
               one sizing, so the morning plan and the 19:00 nudge never size the same gap two ways.
STATES  `walk` (projected below the goal), `on_track` (projected at or over it), `unknown` (with its reason).

The walk is OUTSIDE the session: it is not a Hevy set, so it does not ride the Hevy wire (HEVY_NOTE_STANDARD §1.4,
§2: the set rows and their notes are for the set; the chat and the stored routine are for the rest).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from common.pacific_time import pacific_weekday

from training import steps_nudge, training_streaks, walking_volume

STEP_GAP_WALK_VERSION = "step-gap-walk@1.0.0"
MIN_KIND_DAYS = 3  # PLATFORM-CHOSEN (= steps_ramp.MIN_BASELINE_DAYS): fewer same-kind days is no same-kind mean
LIFTING, OFF, UNKNOWN_KIND = "lifting", "off", "unknown"
WALK, ON_TRACK, UNKNOWN = "walk", "on_track", "unknown"

DERIVATION = (
    "goal = the steps ramp's today_target (the charter floor once the trailing mean reaches it); projected = mean "
    "resolved steps over the ramp's trailing window, same-kind days only (lifting = a loaded Hevy session), all measured "
    f"days when fewer than {MIN_KIND_DAYS} of that kind; partial days excluded; walk = (goal - projected) / "
    f"{steps_nudge.CADENCE_SPM} steps/min rounded up to {steps_nudge.ROUND_WALK_MIN} min"
)

# The tracker's per-day verdicts (offered vs performed), each a plain reading, never a judgement of him.
NOT_OFFERED = "no_walk_offered"
NO_GAP_PROJECTED = "plan_projected_no_gap"
PERFORMED_UNKNOWN = "performed_unknown"
WALK_SHORT = "walked_less_than_offered"
WALK_DONE = "walked_the_offer_still_below"


def _day(row: Mapping[str, Any]) -> str:
    return str(row.get("date") or str(row.get("sk") or "").replace("DATE#", ""))[:10]


def lifting_dates(hevy_rows: Optional[Iterable[Mapping[str, Any]]]) -> Optional[set[str]]:
    """Days carrying a LOADED Hevy session; None when the Hevy rows were not read (kind unknown, never 'off')."""
    if hevy_rows is None:
        return None
    return {_day(w) for w in hevy_rows if training_streaks.is_loaded_session(dict(w))}


def planned_kind(session: Optional[Mapping[str, Any]]) -> str:
    """The planned day's kind from `constraint_block.session`: a served prescription is a lifting day."""
    if not session or session.get("source") in (None, "json", "unreadable", "sequence_unreadable"):
        return UNKNOWN_KIND
    return LIFTING if session.get("prescription") else OFF


def _mean(xs: list[float]) -> Optional[int]:
    return int(round(sum(xs) / len(xs))) if xs else None


def projection(
    window_days: Iterable[Mapping[str, Any]], kind: str, lifting: Optional[set[str]], covered_from: Optional[str] = None
) -> dict[str, Any]:
    """The projected steps for a day of `kind` from the resolver window's measured days; `covered_from` is the first
    day the Hevy rows cover (an earlier day's kind is unknown and leaves the same-kind mean)."""
    resolved = [d for d in window_days if d.get("degraded") != "partial_day"]
    measured = [d for d in resolved if d.get("steps") is not None]  # steps-truth: steps_resolver.steps_range output
    every = [float(d["steps"]) for d in measured]  # steps-truth: steps_resolver.steps_range output, already resolved
    same: list[float] = []
    if kind in (LIFTING, OFF) and lifting is not None:
        for d in measured:
            day = str(d.get("date"))
            if covered_from and day < covered_from:
                continue
            if (day in lifting) == (kind == LIFTING):
                same.append(float(d["steps"]))  # steps-truth: steps_resolver.steps_range output, already resolved
    if len(same) >= MIN_KIND_DAYS:
        return {"projected_steps": _mean(same), "basis": f"{kind}_days", "days_used": len(same)}
    why = "the Hevy record was not read" if lifting is None else f"fewer than {MIN_KIND_DAYS} measured {kind} days"
    if kind == UNKNOWN_KIND:
        why = "the planned day's kind is unknown"
    return {"projected_steps": _mean(every), "basis": "all_days", "days_used": len(every), "basis_note": why}


def walk_line(out: Mapping[str, Any]) -> str:
    """The one line the plan states: the walk, how long, and the numbers that sized it."""
    basis = {"lifting_days": "lifting days", "off_days": "off days"}.get(str(out.get("basis")), "recent days")
    where = ", outside the session" if out.get("day_kind") == LIFTING else ""
    line = (
        f"Walk {int(out['walk_minutes'])} min on {out.get('weekday')}{where}: {basis} have averaged "
        f"{int(out['projected_steps']):,} steps against the day's {int(out['goal']):,}"
    )
    floor = out.get("floor")
    if floor is not None and int(out["goal"]) < int(floor):
        line += f" (the ramp's step toward the {int(floor):,} floor)"
    return line + "."


def plan(
    date: str,
    *,
    ramp: Optional[Mapping[str, Any]],
    window: Optional[Mapping[str, Any]],
    session: Optional[Mapping[str, Any]],
    hevy_rows: Optional[list] = None,
    hevy_covered_from: Optional[str] = None,
) -> dict[str, Any]:
    """The day's walk: `steps_ramp.compute`'s output (`ramp`), the resolver window it was computed from (`window`), the
    planned session (`constraint_block.session`) and the Hevy rows that type the window's days."""
    out: dict[str, Any] = {"date": date, "weekday": pacific_weekday(date), "version": STEP_GAP_WALK_VERSION, "derivation": DERIVATION}
    goal = (ramp or {}).get("today_target")
    if not goal:
        why = (ramp or {}).get("reason") or "the steps ramp read no target for today"
        return {**out, "state": UNKNOWN, "reason": why, "line": None}
    kind = planned_kind(session)
    proj = projection((window or {}).get("days") or [], kind, lifting_dates(hevy_rows), hevy_covered_from)
    out.update(goal=int(goal), floor=(ramp or {}).get("floor"), ramp_state=(ramp or {}).get("state"), day_kind=kind, **proj)
    if proj["projected_steps"] is None:
        return {**out, "state": UNKNOWN, "reason": "no measured step day in the ramp's window", "line": None}
    gap = int(goal) - int(proj["projected_steps"])
    out["gap"] = max(0, gap)
    if gap <= 0:
        return {**out, "state": ON_TRACK, "walk_minutes": 0, "line": None}
    out.update(state=WALK, walk_minutes=steps_nudge.walk_minutes(gap))
    out["line"] = walk_line(out)
    return out


def attach(block: dict[str, Any], window: Optional[Mapping[str, Any]], hevy_rows: Optional[list]) -> None:
    """Stage 1 (#5758): put the day's walk on `constraint_block.steps_ramp.walk_to_close_gap`, from the ramp the block
    already carries, the SAME resolver window it was computed from, the block's served session and the Hevy
    prescription window (Monday three whole weeks back, so it covers the ramp's 14 days; `covered_from` is its start)."""
    from training import self_added_volume

    ramp = block.get("steps_ramp")
    if not isinstance(ramp, dict):
        return
    date = str(block.get("date") or ramp.get("date"))
    covered = self_added_volume.window_start(date) if hevy_rows is not None else None
    ramp["walk_to_close_gap"] = plan(
        date, ramp=ramp, window=window, session=block.get("session"), hevy_rows=hevy_rows, hevy_covered_from=covered
    )


# ── the tracker's read-back: offered vs performed ───────────────────────────────


def offers_by_date(routines: Optional[Iterable[Any]]) -> Optional[dict[str, dict[str, Any]]]:
    """{target_date: the stored offer} from drafted routines (`inputs_snapshot.critics.steps_walk`, stage 2's record);
    the newest stage-2 run wins per day. None when the routines were not read."""
    if routines is None:
        return None
    best: dict[str, tuple[str, dict[str, Any]]] = {}
    for ir in routines:
        rec = (getattr(ir, "inputs_snapshot", None) or {}).get("critics") or {}
        offer = rec.get("steps_walk")
        day = str(getattr(ir, "target_date", "") or "")[:10]
        if not isinstance(offer, Mapping) or not day:
            continue
        ran = str(rec.get("ran_at") or "")
        if day not in best or ran > best[day][0]:
            best[day] = (ran, dict(offer))
    return {d: o for d, (_r, o) in best.items()}


def performed_minutes(day: str, strava_items: Optional[list], hevy_rows: Optional[list]) -> Optional[float]:
    """His walking minutes that day — the walking layer's ONE definition (`walking_volume.walking_minutes_for_day`,
    Hevy treadmill blocks + Strava walks, counted once in time). None when either source was unread or neither has a
    record (unknown, never 0)."""
    if strava_items is None or hevy_rows is None:
        return None
    s = [r for r in strava_items if _day(r) == day]
    h = [r for r in hevy_rows if _day(r) == day]
    got = walking_volume.walking_minutes_for_day(day=day, strava_items=s, hevy_workouts=h)
    return None if got is None else float(got["minutes"])


def _verdict(offer: Optional[Mapping[str, Any]], performed: Optional[float]) -> str:
    if not offer:
        return NOT_OFFERED
    if offer.get("state") != WALK:
        return NO_GAP_PROJECTED
    if performed is None:
        return PERFORMED_UNKNOWN
    return WALK_DONE if performed >= float(offer.get("walk_minutes") or 0) else WALK_SHORT


def attribution(
    days_below: Iterable[str],
    steps_by_day: Mapping[str, Any],
    offers: Optional[Mapping[str, Mapping[str, Any]]],
    performed: Mapping[str, Optional[float]],
) -> list[dict[str, Any]]:
    """One row per day below the floor: its steps, the walk the plan offered (stored) and the walking minutes he did."""
    rows = []
    for day in days_below:
        offer = None if offers is None else offers.get(day)
        rows.append(
            {
                "date": day,
                "weekday": pacific_weekday(day),
                "steps": steps_by_day.get(day),
                "offered": (
                    {"state": "not_read"}
                    if offers is None
                    else (
                        {"state": "none_on_record"}
                        if not offer
                        else {k: offer.get(k) for k in ("state", "walk_minutes", "goal", "projected_steps", "basis", "line")}
                    )
                ),
                "performed_walk_minutes": performed.get(day),
                "verdict": "offers_not_read" if offers is None else _verdict(offer, performed.get(day)),
            }
        )
    return rows
