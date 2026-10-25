"""may_tracker.py — the weekly May tracker (#5073, C6, epic #5067). OWNER-ONLY.

One row per Monday-Sunday Pacific week answering "is he on pace for the target date, and which
lever does he pull when he is not". Every target is READ from the training charter
(`training_charter.charter_value`); every measured number comes from the one function that
already owns it — this module arranges and compares, it does not count:

  weight     the week's 7-day loss rate and the 4-week rate (`mcp.shared_quantities`' estimator,
             handed in), against the charter band through `training.rate_band` (lb/wk AND % of
             bodyweight; the clinical guidance record's cap wins where it is lower), weeks to the
             target date and the projected weight there at the 4-week rate vs the band;
  waist      the latest tape row from the measurements partition (absent until a tape exists —
             never 0);
  steps      the week's days resolved by `training.steps_resolver` (days at the floor / target);
  anchors    the four core anchors' e1RM trends through `plan_engine.anchor_e1rm_trend` (the one
             trend computation) and the redline's own threshold (`anchor_drop_tripped`);
  volume     the charter's `volume_priorities.sets_per_wk` rows over the week's
             `muscle_volume.working_sets_by_muscle` output, counted BY MOVEMENT through
             `volume_floors` (side/rear delts, upper chest, lats; presses excluded) with the charter
             band beside each count (`absent` only when the week carries no per-exercise counts);
  fitness    the battery's per-test trend and its cadence state (`training.fitness_tests`, #5078);
  running    the run gate through `training.run_onramp.gate_state` (#5090): closed / prep / held / open,
             lb to the prep and to the gate, and the walking weeks met / needed.

Then the TRIGGERS — each names its LEVER (the review's calibration table): the rate below the
floor two weeks running -> steps or food; above the ceiling -> the nutrition review; an anchor
down two weeks -> fatigue / under-eating before adding work; the steps floor missed -> the walk
prescription; a priority muscle below its floor two weeks -> a slot. A trigger whose input is not
measured is listed under `unevaluated`, never read as green (ADR-104).

PRIVACY. The target date and the band are owner-only by ruling (no May countdown on any published
surface). The row is stored at `USER#matthew#SOURCE#may_tracker / WEEK#<monday>` (Tier owner-only,
CROSS_PHASE); the only readers are the owner's MCP tool `get_may_tracker` and `latest_completed_row()`
for the coach-context assembly (#5071, read on every planning caller path since #5200). `tests/test_may_tracker_5073.py` holds that no `lambdas/web/`
or `lambdas/emails/` module imports this one.

Pure core (`build_week`, `evaluate_triggers`); the store helpers take an injected table.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Iterable, Mapping, Optional

TRACKER_VERSION = "may-tracker@1.0.0"
SOURCE = "may_tracker"
PK = f"USER#matthew#SOURCE#{SOURCE}"
SK_PREFIX = "WEEK#"

MEASURED, ABSENT, READ_FAILED = "measured", "absent", "read_failed"
AMBER, RED = "amber", "red"
_LEVEL_RANK = {None: 0, "green": 0, AMBER: 1, RED: 2}
WAIST_FIELDS = ("waist_navel_in", "waist_narrowest_in", "waist_iliac_crest_in")

# The calibration table (owner review 2026-10-18): trigger -> the lever it names.
LEVERS: dict[str, str] = {
    "rate_below_floor": "steps or food: the walk prescription to the steps target, or food adherence — never a new cut",
    "rate_above_ceiling": "the nutrition review: the loss is faster than the band allows",
    "anchor_down": "check fatigue and under-eating before adding any work",
    "steps_floor_missed": "the walk prescription: walks scheduled until every day clears the floor",
    "priority_volume_below_floor": "a slot: add the muscle's movement to a template slot",
}


def _cv(path: str, default: Any = None) -> Any:
    from training.training_charter import charter_value

    return charter_value(path, default)


def cell(state: str, value: Any, source: str, detail: Optional[str] = None, **extra: Any) -> dict[str, Any]:
    """One labelled value (ADR-104): its state, its value (None unless measured) and where it came from."""
    out: dict[str, Any] = {"state": state, "value": value if state == MEASURED else None, "source": source}
    if detail:
        out["detail"] = detail
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


# ── the calendar ────────────────────────────────────────────────────────────────


def _day(day: str) -> _dt.date:
    from common.pacific_time import parse_day_key

    d = parse_day_key(str(day)[:10])
    if d is None:
        raise ValueError(f"not a day key: {day!r}")
    return d


def week_bounds(day: str) -> tuple[str, str]:
    """(Monday, Sunday) of the Pacific week holding `day` (a YYYY-MM-DD key)."""
    d = _day(day)
    mon = d - _dt.timedelta(days=d.weekday())
    return mon.isoformat(), (mon + _dt.timedelta(days=6)).isoformat()


def last_completed_monday(today: str) -> str:
    """The Monday of the newest week whose Sunday is BEFORE `today` (the Pacific day)."""
    mon, _sun = week_bounds(today)
    return shift(mon, -7)


def shift(day: str, days: int) -> str:
    return (_day(day) + _dt.timedelta(days=days)).isoformat()


def _days_between(a: str, b: str) -> int:
    return (_day(b) - _day(a)).days


# ── sections ────────────────────────────────────────────────────────────────────


def weight_section(
    sunday: str,
    week_rate: Optional[Mapping[str, Any]],
    rate_4wk: Optional[Mapping[str, Any]],
    latest_weight: Optional[tuple[str, float]],
    guidance: Optional[Mapping[str, Any]] = None,
    read_error: Optional[str] = None,
) -> dict[str, Any]:
    """The week's rate vs the band in both units, and the target-date projection at the 4-week rate.

    `week_rate` is one `weekly_loss_rate_weeks_from_rows` row for the week; `rate_4wk` is a
    `loss_rate_from_rows(window_days=28)` result; `latest_weight` is (date, lb) on or before Sunday;
    `guidance` is `{"state": ..., "cap_lb_wk": float|None}` from the clinical record read."""
    from training import rate_band

    src = "mcp.shared_quantities (Withings partition) + training.rate_band"
    if read_error:
        return {"state": READ_FAILED, "source": src, "error": read_error}
    g = dict(guidance or {"state": ABSENT, "cap_lb_wk": None})
    w = latest_weight[1] if latest_weight else None
    rate = (week_rate or {}).get("rate_lb_wk")
    counted = bool((week_rate or {}).get("counted"))
    view = rate_band.band_view(w, rate if counted else None, g.get("cap_lb_wk"))
    rate_cell = cell(
        MEASURED if rate is not None else ABSENT,
        rate,
        "shared_quantities.weekly_loss_rate_weeks_from_rows (7 days ending Sunday)",
        None if rate is not None else (week_rate or {}).get("reason") or "no weekly rate",
        counted=counted,
        status=(week_rate or {}).get("status"),
        n_weighins=(week_rate or {}).get("n_weighins"),
        pct_bodyweight_per_wk=round(rate / w * 100, 2) if rate is not None and w else None,
    )
    r4 = (rate_4wk or {}).get("rate_lb_wk")
    r4_cell = cell(
        MEASURED if r4 is not None else ABSENT,
        r4,
        "shared_quantities.loss_rate_from_rows (28 days ending Sunday)",
        None if r4 is not None else (rate_4wk or {}).get("reason") or "no 4-week rate",
        provisional=(rate_4wk or {}).get("provisional"),
        pct_bodyweight_per_wk=round(r4 / w * 100, 2) if r4 is not None and w else None,
    )
    out: dict[str, Any] = {
        "state": MEASURED if w is not None else ABSENT,
        "source": src,
        "weight_lb": cell(
            MEASURED if w is not None else ABSENT,
            w,
            "withings",
            None if w else "no weigh-in",
            date=latest_weight[0] if latest_weight else None,
        ),
        "rate_week": rate_cell,
        "rate_4wk": r4_cell,
        "band": view,
        # Below the landing weight his landing schedule, not the band, is the target (`rate_band.governs`).
        "band_position_week": (view or {}).get("position") if counted and (view or {}).get("governs") else None,
        "guidance": {"state": g.get("state"), "capped": bool((view or {}).get("guidance_capped"))},
        "target": target_projection(sunday, w, r4, view),
    }
    return out


def target_projection(sunday: str, weight: Optional[float], rate_4wk: Optional[float], band: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Weeks to the charter's target date and the projected weight there — linear at the 4-week rate
    and at the band's floor and ceiling. OWNER-ONLY (the date is never published)."""
    target = _cv("governing_goal.target_date")
    if not target:
        return {"state": ABSENT, "detail": "the charter carries no governing_goal.target_date"}
    weeks = round(_days_between(sunday, str(target)) / 7.0, 1)
    out: dict[str, Any] = {"state": MEASURED, "target_date": target, "weeks_to_go": weeks, "source": "governing_goal.target_date"}
    if weight is None:
        out["projection"] = None
        out["detail"] = "no weigh-in, so no projection"
        return out

    def at(r: Optional[float]) -> Optional[float]:
        return None if r is None else round(weight - r * max(weeks, 0.0), 1)

    out["projection"] = {
        "at_4wk_rate_lb": at(rate_4wk),
        "at_band_floor_lb": at((band or {}).get("floor_lb_wk")),
        "at_band_ceiling_lb": at((band or {}).get("ceiling_lb_wk")),
        "method": "linear: weight - rate x weeks_to_go",
        "caveat": "the band governs only above the landing weight; below it the landing schedule steps the rate down, which this line does not model",
    }
    return out


def _tape_cadence(rows: Any, sunday: str) -> dict[str, Any]:
    """#5061: the tape cycle as of Sunday (`training.calibration_cadence`) — state, due date, missed cycles. Dates only."""
    from common.constants import EXPERIMENT_START_DATE

    from training import calibration_cadence as cc

    r = cc.tape_row(list(rows or ()), sunday, EXPERIMENT_START_DATE)
    return {k: r.get(k) for k in ("state", "last_logged", "due_on", "missed_cycles", "prompt")}


def waist_section(rows: Optional[Iterable[Mapping[str, Any]]], sunday: str, read_error: Optional[str] = None) -> dict[str, Any]:
    """The latest tape row on or before Sunday with any waist site. Absent until a tape exists — never 0."""
    rows = list(rows) if rows is not None else None
    src = "USER#matthew#SOURCE#measurements (waist_*_in)"
    if read_error:
        return cell(READ_FAILED, None, src, error=read_error)
    best: Optional[Mapping[str, Any]] = None
    for r in rows or ():
        d = str(r.get("date") or str(r.get("sk") or "").replace("DATE#", ""))[:10]
        if not d or d > sunday or not any(r.get(f) is not None for f in WAIST_FIELDS):
            continue
        if best is None or d > best["_d"]:
            best = {**r, "_d": d}
    every = _cv("calibration.tape_and_photos.every_weeks")
    if best is None:
        return cell(ABSENT, None, src, "no tape row with a waist site yet", every_weeks=every, cadence=_tape_cadence(rows, sunday))
    vals = {f: float(best[f]) for f in WAIST_FIELDS if best.get(f) is not None}
    age = _days_between(best["_d"], sunday)
    due = every is not None and age > int(every) * 7
    return cell(MEASURED, vals, src, date=best["_d"], age_days=age, every_weeks=every, tape_due=due, cadence=_tape_cadence(rows, sunday))


def _resolved(day_row: Mapping[str, Any]) -> Optional[int]:
    return day_row.get("steps")  # steps-truth: resolve_daily_steps output (training.steps_resolver), already resolved


def steps_section(days: Optional[list[Mapping[str, Any]]], read_error: Optional[str] = None) -> dict[str, Any]:
    """The week's resolved days (`steps_resolver.steps_range(...)["days"]`) against the charter floor/target."""
    src = "training.steps_resolver.steps_range"
    if read_error:
        return cell(READ_FAILED, None, src, error=read_error)
    floor, target = _cv("steps.floor"), _cv("steps.target")
    days = list(days or [])
    counts_by_day = {d.get("date"): _resolved(d) for d in days}
    measured = [d for d in days if counts_by_day[d.get("date")] is not None]
    if not measured:
        return cell(ABSENT, None, src, "no steps source has a count this week", floor=floor, target=target, days=len(days))
    counts = [int(counts_by_day[d.get("date")]) for d in measured]
    below = [d["date"] for d in measured if floor is not None and int(counts_by_day[d["date"]]) < int(floor)]
    return cell(
        MEASURED,
        round(sum(counts) / len(counts)),
        src,
        floor=floor,
        target=target,
        days=len(days),
        days_measured=len(measured),
        days_at_floor=sum(1 for c in counts if floor is not None and c >= int(floor)),
        days_at_target=sum(1 for c in counts if target is not None and c >= int(target)),
        days_below_floor=below,
        days_without_a_count=[d.get("date") for d in days if counts_by_day[d.get("date")] is None],
        partial_days=[d.get("date") for d in measured if d.get("degraded") == "partial_day"],
        unit="mean steps over measured days (an absent day is never a 0)",
    )


def anchors_section(
    series: Optional[Mapping[str, list[Mapping[str, Any]]]], sunday: str, read_error: Optional[str] = None
) -> dict[str, Any]:
    """Each core anchor's e1RM trend over sessions on or before Sunday, cut to the identity of its latest
    session (a variant switch starts a new series — never a drop). `series` = {family: [session]} where a
    session carries `date`, `best_1rm`, `identity` (`mcp.strength_helpers.extract_hevy_sessions` shape)."""
    from training import plan_engine, program_structure

    src = "training.plan_engine.anchor_e1rm_trend over mcp.strength_helpers.extract_hevy_sessions"
    if read_error:
        return {"state": READ_FAILED, "source": src, "error": read_error}
    out: dict[str, Any] = {"state": MEASURED, "source": src, "anchors": {}}
    any_measured = False
    for fam in program_structure.CORE_ANCHORS:
        sess = sorted(
            (s for s in (series or {}).get(fam) or [] if str(s.get("date") or "")[:10] <= sunday), key=lambda s: str(s.get("date"))
        )
        if not sess:
            out["anchors"][fam] = cell(ABSENT, None, src, "no logged session of this anchor")
            continue
        ident = str(sess[-1].get("identity") or "").upper()
        cut = [s for s in sess if str(s.get("identity") or "").upper() == ident]
        trend = plan_engine.anchor_e1rm_trend([s.get("best_1rm") for s in cut])
        if "drop_pct" not in trend:
            out["anchors"][fam] = cell(ABSENT, None, src, trend.get("insufficient"), identity=ident or None, trend=trend)
            continue
        any_measured = True
        down = (trend.get("drop_pct") or 0) > 0
        tripped = plan_engine.anchor_drop_tripped(trend.get("drop_pct"), trend.get("sessions_below"))
        out["anchors"][fam] = cell(
            MEASURED,
            trend.get("recent_median_e1rm_lb"),
            src,
            identity=ident or None,
            last_date=cut[-1].get("date"),
            trend=trend,
            down=down,
            tripped=tripped,
        )
    if not any_measured:
        out["state"] = ABSENT
    return out


def volume_section(vol: Optional[Mapping[str, Any]], read_error: Optional[str] = None) -> dict[str, Any]:
    """The charter's `volume_priorities.sets_per_wk` rows against the week's working sets, counted BY MOVEMENT (#5073/#5053).

    `vol` is `muscle_volume.working_sets_by_muscle` output. The movement-counted bands (side/rear delts, upper chest,
    lats) are summed through `volume_floors.FLOOR_MOVEMENTS`/`BAND_MOVEMENTS` over the week's per-exercise sets, so a
    press is never side/rear-delt work; legs and arms are per-member catalog-muscle sums. The row's `value` is the
    WORST member's sets (the band is per member); `member_sets` carries every member beside the charter `band`."""
    from training import volume_floors

    src = "training.volume_floors (movement counts) over training.muscle_volume.working_sets_by_muscle (Monday-Sunday)"
    if read_error:
        return {"state": READ_FAILED, "source": src, "error": read_error}
    bands = _cv("volume_priorities.sets_per_wk") or {}
    muscles = (vol or {}).get("muscles") or {}
    exercise_sets = (vol or {}).get("exercise_sets")
    by_movement = volume_floors.logged_movement_sets(exercise_sets) if exercise_sets is not None else None
    by_muscle = {m: int(round(float((r or {}).get("total_sets") or 0))) for m, r in muscles.items()}
    counted = volume_floors.movement_counts(by_muscle, by_movement or {})
    band_rows = volume_floors.charter_band_rows(counted)
    rows: dict[str, Any] = {}
    for key, band in bands.items():
        lo, hi = band
        members = volume_floors.BAND_MEMBERS.get(key, ())
        needs_movements = any(m.endswith("_direct") for member in members for m in member)
        if vol is None or not members or (needs_movements and by_movement is None):
            why = (
                "the week carried no per-exercise counts or the movement catalog is unreadable"
                if members
                else f"no member keys for `{key}`"
            )
            rows[key] = cell(ABSENT, None, src, why, band=[lo, hi])
            continue
        r = band_rows[key]
        member_sets = [int(n) for n in r["member_sets"]]
        rows[key] = cell(
            MEASURED,
            min(member_sets),
            src,
            band=[lo, hi],
            member_sets=member_sets,
            below_floor=bool(r["gap_to_floor"]),
            gap_to_floor=int(r["gap_to_floor"]),
        )
    state = MEASURED if any(r["state"] == MEASURED for r in rows.values()) else ABSENT
    return {"state": state, "source": src, "charter_path": "volume_priorities.sets_per_wk", "rows": rows}


def fitness_section(view: Optional[Mapping[str, Any]], sunday: Optional[str] = None, read_error: Optional[str] = None) -> dict[str, Any]:
    """The fitness-test battery as of Sunday (#5078): each test's latest / previous / delta in its better
    direction (`fitness_tests.trend`) and, when supplied, the cadence state (`fitness_tests.due`). `view` is
    `{"batteries": [...], "due": {...} | None}` (mcp.tools_fitness_tests.read_view); None = nothing read."""
    from training import fitness_tests

    src = "fitness-test battery (#5078: training.fitness_tests over the BATTERY# record + Hevy)"
    every = _cv("calibration.fitness_tests.every_weeks")
    if read_error:
        return cell(READ_FAILED, None, src, error=read_error)
    batts = [b for b in (view or {}).get("batteries") or [] if sunday is None or str(b.get("date")) <= sunday]
    cadence = (view or {}).get("due")
    if not batts:
        return cell(ABSENT, None, src, "no fitness-test battery is on file yet (#5078)", every_weeks=every, due=cadence)
    return cell(
        MEASURED,
        fitness_tests.trend(batts),
        src,
        latest_date=batts[-1]["date"],
        batteries=len(batts),
        every_weeks=every,
        due=cadence,
    )


def running_gate_section(
    weight: Optional[float],
    walking_weeks: Optional[list[Mapping[str, Any]]] = None,
    holds: Any = None,
    stage4_done: bool = False,
    onramp: Optional[Mapping[str, Any]] = None,
    held_since: Optional[str] = None,
    weight_date: Optional[str] = None,
) -> dict[str, Any]:
    """The run gate (`training.run_onramp.gate_state`, the one gate): `walking_weeks` are the tracked week's
    completed walking weeks (hours + a lower-leg pain flag each); `holds` the strain-hold causes, None = not read;
    `onramp` the Stage 4 progress (`run_onramp.stage_progress`) from his logged run/walks, None = not read;
    `held_since` the day a standing hold began (no run/walk counts from it)."""
    from training import run_onramp

    gate = _cv("gated_movements.running")
    if not isinstance(gate, Mapping) or gate.get("gate_lb") is None:
        return cell(ABSENT, None, "gated_movements.running", "the charter carries no running gate")
    gs = run_onramp.gate_state(weight, walking_weeks, holds, stage4_done, weight_date=weight_date)
    return cell(
        MEASURED if weight is not None else ABSENT,
        gs["lb_to_gate"],
        "training.run_onramp.gate_state over gated_movements.running",
        None if weight is not None else "no weigh-in",
        unit="lb to the gate weight",
        gate_lb=gs["gate_lb"],
        weight_lb=gs["weight_lb"],
        weight_date=gs["weight_date"],
        weight_cleared=None if weight is None else weight <= gs["gate_lb"],
        gate_state=gs["state"],
        reason=gs["reason"],
        line=run_onramp.gate_line(gs),
        prep_from_lb=gs["prep_from_lb"],
        lb_to_prep=gs["lb_to_prep"],
        walking=gs["walking"],
        holds_read=gs["holds_read"],
        holds=gs["holds"],
        held_since=held_since,
        onramp=dict(onramp) if onramp is not None else None,
        prerequisites=list(gate.get("prerequisites") or []),
        refs=gate.get("refs"),
    )


# ── triggers ────────────────────────────────────────────────────────────────────


def _trigger(tid: str, level: str, condition: str, evidence: Any) -> dict[str, Any]:
    return {"id": tid, "level": level, "condition": condition, "lever": LEVERS[tid], "evidence": evidence}


def _pos(row: Optional[Mapping[str, Any]]) -> Optional[str]:
    return ((row or {}).get("weight") or {}).get("band_position_week")


def evaluate_triggers(row: Mapping[str, Any], prior: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """AMBER/RED triggers for a week, each naming its lever; `prior` is the previous week's row (for the
    two-weeks-running conditions). An input that is not measured lands the trigger in `unevaluated`."""
    fired: list[dict[str, Any]] = []
    unevaluated: list[dict[str, str]] = []

    pos, prev = _pos(row), _pos(prior)
    if pos is None:
        governs = (((row.get("weight") or {}).get("band")) or {}).get("governs")
        why = "below the landing weight the landing schedule governs" if governs is False else "no counted weekly rate this week"
        unevaluated.append({"id": "rate_band", "why": why})
    elif pos == "below" and prev == "below":
        fired.append(
            _trigger("rate_below_floor", AMBER, "the weekly rate sat below the band floor two weeks running", {"this": pos, "prior": prev})
        )
    elif pos == "above":
        level = RED if prev == "above" else AMBER
        fired.append(_trigger("rate_above_ceiling", level, "the weekly rate is above the band ceiling", {"this": pos, "prior": prev}))

    anchors = ((row.get("anchors") or {}).get("anchors")) or {}
    prior_anchors = (((prior or {}).get("anchors") or {}).get("anchors")) or {}
    if not any(a.get("state") == MEASURED for a in anchors.values()):
        unevaluated.append({"id": "anchor_down", "why": "no core anchor has enough sessions for a trend"})
    else:
        tripped = [f for f, a in anchors.items() if a.get("tripped")]
        down2 = [f for f, a in anchors.items() if a.get("down") and (prior_anchors.get(f) or {}).get("down")]
        if tripped:
            fired.append(_trigger("anchor_down", RED, "a core anchor tripped the redline's own strength-drop threshold", tripped))
        elif down2:
            fired.append(
                _trigger("anchor_down", AMBER, "a core anchor's recent e1RM median sat below its baseline two weeks running", down2)
            )

    steps = row.get("steps") or {}  # steps-truth: the tracker's own steps SECTION (built from steps_resolver), not a source row
    if steps.get("state") != MEASURED:
        unevaluated.append({"id": "steps_floor_missed", "why": f"steps {steps.get('state') or 'absent'}"})
    elif steps.get("days_below_floor"):
        mean_below = steps.get("floor") is not None and steps["value"] < int(steps["floor"])
        fired.append(
            _trigger(
                "steps_floor_missed",
                RED if mean_below else AMBER,
                "the week's mean steps sat below the floor" if mean_below else "a measured day fell below the steps floor",
                steps.get("days_below_floor"),
            )
        )

    vrows = ((row.get("volume") or {}).get("rows")) or {}
    prior_v = (((prior or {}).get("volume") or {}).get("rows")) or {}
    absent_v = [k for k, r in vrows.items() if r.get("state") != MEASURED]
    if absent_v:
        unevaluated.append(
            {"id": "priority_volume_below_floor", "why": f"no movement-level count for {', '.join(sorted(absent_v))} (#5053)"}
        )
    low2 = [k for k, r in vrows.items() if r.get("below_floor") and (prior_v.get(k) or {}).get("below_floor")]
    if low2:
        fired.append(_trigger("priority_volume_below_floor", AMBER, "a priority muscle sat below its weekly floor two weeks running", low2))

    worst = max((t["level"] for t in fired), key=lambda lv: _LEVEL_RANK[lv], default=None)
    status = worst or ("green" if not unevaluated else "green_with_gaps")
    return {"status": status, "fired": fired, "unevaluated": unevaluated}


# ── the row ─────────────────────────────────────────────────────────────────────


def build_week(
    monday: str,
    *,
    weight: Mapping[str, Any],
    waist: Mapping[str, Any],
    steps: Mapping[str, Any],
    anchors: Mapping[str, Any],
    volume: Mapping[str, Any],
    fitness: Mapping[str, Any],
    prior: Optional[Mapping[str, Any]] = None,
    built_at: Optional[str] = None,
    running: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """The week's row from its sections (each built above), triggers evaluated against `prior`."""
    from training.training_charter import charter_version

    sunday = shift(monday, 6)
    w = ((weight.get("weight_lb") or {}).get("value")) if isinstance(weight, Mapping) else None
    w_date = ((weight.get("weight_lb") or {}).get("date")) if isinstance(weight, Mapping) else None  # #5314
    row: dict[str, Any] = {
        "pk": PK,
        "sk": SK_PREFIX + monday,
        "week_start": monday,
        "week_end": sunday,
        "charter_version": charter_version(),
        "version": TRACKER_VERSION,
        "weight": dict(weight),
        "waist": dict(waist),
        "steps": dict(steps),
        "anchors": dict(anchors),
        "volume": dict(volume),
        "fitness_tests": dict(fitness),
        "running_gate": running_gate_section(
            w, **{**dict(running or {}), "weight_date": w_date}
        ),  # #5090: walking_weeks / holds from the caller
        "tier": "owner_only",
    }
    if built_at:
        row["built_at"] = built_at
    row["triggers"] = evaluate_triggers(row, prior)
    return row


# ── the store (table injected) ──────────────────────────────────────────────────


def write_week(table: Any, row: Mapping[str, Any]) -> dict[str, str]:
    """Put the week's row (idempotent: one row per Monday, a re-run overwrites it). Raises on a failed write."""
    from common.numeric import floats_to_decimal

    if not str(row.get("sk") or "").startswith(SK_PREFIX) or row.get("pk") != PK:
        raise ValueError("not a may_tracker row")
    table.put_item(Item=floats_to_decimal(dict(row)))
    return {"pk": PK, "sk": str(row["sk"])}


def stored_rows(table: Any, limit: int = 1) -> list[dict[str, Any]]:
    """The newest stored rows, newest first. Raises on a failed read — a broken read is never 'no row'."""
    from common.numeric import decimals_to_float

    resp = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
        ExpressionAttributeValues={":pk": PK, ":pfx": SK_PREFIX},
        ScanIndexForward=False,
        Limit=max(1, int(limit)),
    )
    return [decimals_to_float(i) for i in (resp.get("Items") or [])]


def latest_row(table: Any) -> dict[str, Any]:
    """The newest stored week for the coach-context assembly (#5071): `{state, row}`; a failed read is
    `read_failed` with the exception class, never an empty tracker."""
    try:
        rows = stored_rows(table, 1)
    except Exception as e:  # noqa: BLE001 — reported by class; the caller states it
        return {"state": READ_FAILED, "row": None, "error": type(e).__name__}
    if not rows:
        return {"state": ABSENT, "row": None, "detail": "no May-tracker week is stored yet"}
    return {"state": MEASURED, "row": rows[0]}


STALE = "stale"


def latest_completed_row(table: Any, target_date: str) -> dict[str, Any]:
    """#5200: the newest stored week whose Sunday is BEFORE `target_date` — what every planning caller's coach
    context reads (plan_next_session, the nightly pre-draft, the session packet). `{state, row, expected_week_start}`:
    `measured` when it is the newest completed week, `stale` when an older week is the newest stored one (supplied,
    and said), `absent` with no stored week, `read_failed` with the exception class — never an empty tracker."""
    from common.numeric import decimals_to_float

    expected = last_completed_monday(target_date)
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :lo AND :hi",
            ExpressionAttributeValues={":pk": PK, ":lo": SK_PREFIX, ":hi": SK_PREFIX + expected},
            ScanIndexForward=False,
            Limit=1,
        )
    except Exception as e:  # noqa: BLE001 — reported by class; the context states it
        return {"state": READ_FAILED, "row": None, "error": type(e).__name__, "expected_week_start": expected}
    items = resp.get("Items") or []
    if not items:
        return {
            "state": ABSENT,
            "row": None,
            "detail": f"no May-tracker week through {expected} is stored",
            "expected_week_start": expected,
        }
    row = decimals_to_float(items[0])
    if row.get("week_start") == expected:
        return {"state": MEASURED, "row": row, "expected_week_start": expected}
    detail = f"the newest stored week is {row.get('week_start')}; the newest completed week is {expected} (the nightly leg writes it)"
    return {"state": STALE, "row": row, "detail": detail, "expected_week_start": expected}
