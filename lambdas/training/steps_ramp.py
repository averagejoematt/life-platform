"""steps_ramp.py — the ramp to the charter's steps floor, and the lower-leg hold on it (#5082).

WHY: jumping straight to the charter floor from a low trailing average is an overload risk, so the
daily target climbs from where he actually is. Pure — no AWS, no clock; the caller passes values it
already fetched (the resolver's `steps_range`, the plan's pain flags and dismissals, the DELOAD# records).

THE BASE: `steps_resolver.steps_range` over the `steps.ramp.ramp_window_days` days before `date` (charter,
owner-adjustable, default 14). Only days with a MEASURED count enter the mean; a no-source day is excluded
and counted (`excluded_days.no_source`); a `partial_day` (the vendor cycle is still open, the count is a
floor) is excluded and counted too; a `fallback`-source day is a real count and stays in.
`walking_volume.derived_steps_estimate` never feeds the ramp (it is a labelled estimate, not a count).

THE RAMP (derived, stated on every output as `derivation`):
  step_per_week = max(RAMP_PCT_PER_WEEK x trailing_avg, (floor - trailing_avg) / RAMP_MAX_WEEKS)
  level         = min(floor, trailing_avg + step_per_week), rounded up to the next 100
The first term is +10 %/week; the second is the cap that guarantees the floor is reached in at most
RAMP_MAX_WEEKS (6) weeks. `RAMP_PCT_PER_WEEK` and `RAMP_MAX_WEEKS` are the owner-adjustable fields besides the
charter's `ramp_window_days` (they live here, named, until an owner ruling moves them into the charter).
The level re-bases on the trailing mean each day, so it follows what he really walked: a week he undershoots does
not run the target away from him.

STATES
  ramping   — below the floor, no hold: today_target = level
  holding   — a lower-leg strain hold is on (or there is no baseline): the level is frozen at the current step
              (`prior_level` when the caller carries one, else the trailing mean), never raised
  at_floor  — the trailing mean is at the floor but the floor has not yet held 7 measured days in a row
  at_target — the floor held the last 7 days: the charter's 15,000 target is live as `stretch_target`

THE LOWER-LEG HOLD (`held_by`, every cause named)
  * `strain_flag:<site>`    — a foot / ankle / knee / calf / shin / heel / achilles / toe flag on a lift's note
                              (the plan's `pain_flag_instances`; the site is the dismissal's site key or named in
                              the note's own words). Held while the latest such note is within RELEASE_QUIET_DAYS.
  * `standing_constraint:<id>` — an ACTIVE lower-leg entry in `training_context_registry` (the standing calf entry
                              is read every time; it is `resolved` since the owner's 2026-09-20 word, so it holds
                              nothing and is reported under `standing_constraints_read`).
  * `deload_record:<start>` — an owner DELOAD# record covers the day (a deload cuts load; the ramp does not climb).
RELEASE: the hold ends when the owner dismisses the site (`released_on` = his dismissal date; a later note re-arms
it, `training_context_registry.resolve_flag` is the one comparison) or after RELEASE_QUIET_DAYS (14) days without
a new note (`released_on` = last note + 14). `released_on` is also set when a past hold has ended.

Stamped with `charter_version`. The nudge (#5056) reads `compute`'s output.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional

from common.pacific_time import parse_day_key, shift_day_key

from training import deload_word, training_charter, training_context_registry

RAMP_PCT_PER_WEEK = 0.10
RAMP_MAX_WEEKS = 6
RELEASE_QUIET_DAYS = 14
FLOOR_HOLD_DAYS = 7
MIN_BASELINE_DAYS = 3  # fewer measured days than this is no baseline: hold, never invent a level
ROUND_TO = 100

# Body sites the lower-leg hold covers (tokens of a site key / a note's own words).
LOWER_LEG_TOKENS = frozenset(
    {"foot", "feet", "toe", "toes", "ankle", "calf", "calves", "shin", "shins", "heel", "achilles", "knee", "knees", "plantar", "arch"}
)

STATES = ("ramping", "holding", "at_floor", "at_target")


def _tokens(text: Any) -> set[str]:
    return set(training_context_registry.normalize_dismissal_key(str(text or "")).split("_")) - {""}


def is_lower_leg(text: Any) -> bool:
    return bool(_tokens(text) & LOWER_LEG_TOKENS)


def _round_up(x: float) -> int:
    return int(math.ceil(x / ROUND_TO) * ROUND_TO)


def window_days(date: str) -> tuple[str, str]:
    """[start, end] the base is read over: the `ramp_window_days` completed days before `date`."""
    n = int(training_charter.charter_value("steps.ramp.ramp_window_days", 14) or 14)
    return shift_day_key(date, -n), shift_day_key(date, -1)


def baseline(days: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Trailing mean over the resolver's days: measured ones only, the rest counted by reason."""
    counted, excluded = [], {"no_source": 0, "partial_day": 0}
    for d in days:
        if d.get("steps") is None:  # steps-truth: resolve_daily_steps output (training.steps_resolver), already resolved
            excluded["no_source"] += 1
        elif d.get("degraded") == "partial_day":
            excluded["partial_day"] += 1
        else:
            counted.append(float(d["steps"]))  # steps-truth: resolve_daily_steps output (training.steps_resolver), already resolved
    return {
        "trailing_avg": round(sum(counted) / len(counted)) if counted else None,
        "days_counted": len(counted),
        "excluded_days": excluded,
    }


def floor_held_days(days: list[Mapping[str, Any]], floor: int) -> int:
    """Consecutive most-recent days (newest first) whose measured count reached the floor."""
    run = 0
    for d in sorted(days, key=lambda x: str(x.get("date")), reverse=True):
        steps = d.get("steps")  # steps-truth: resolve_daily_steps output (training.steps_resolver), already resolved
        if steps is None or float(steps) < floor or d.get("degraded") == "partial_day":
            break
        run += 1
    return run


def _strain_events(date: str, instances: Any, dismissals: Any) -> list[dict[str, Any]]:
    """One row per lower-leg flag instance: site, latest note date, whether the owner dismissed it, and the hold verdict."""
    out: list[dict[str, Any]] = []
    for inst in training_context_registry.expand_instances(instances, dismissals):
        site = inst.get("site")
        notes = inst.get("notes") or [{"date": d} for d in (inst.get("note_dates") or [])]
        site_hit = is_lower_leg(site)
        dates = sorted(str(n.get("date"))[:10] for n in notes if (site_hit or is_lower_leg(n.get("text"))) and n.get("date"))
        dates = [d for d in dates if parse_day_key(d) is not None and d <= date]
        if not dates:
            continue
        res = training_context_registry.resolve_flag(
            movement=inst.get("movement"),
            note_dates=dates,
            site=site,
            exercise=inst.get("exercise"),
            movement_key=inst.get("movement_key"),
            dismissals=dismissals,
        )
        last = dates[-1]
        quiet_on = shift_day_key(last, RELEASE_QUIET_DAYS)
        label = str(site or inst.get("movement") or "lower_leg")
        if res and res.get("state") == "dismissed_by_owner":
            out.append({"site": label, "last_note": last, "holds": False, "released_on": res["dismissed_on"], "by": "owner_dismissal"})
        elif quiet_on <= date:
            out.append({"site": label, "last_note": last, "holds": False, "released_on": quiet_on, "by": "quiet_period"})
        else:
            out.append({"site": label, "last_note": last, "holds": True, "released_on": None, "by": None})
    return out


def _standing_lower_leg() -> tuple[list[str], list[dict[str, Any]]]:
    """(active lower-leg constraint ids, every lower-leg entry as read — resolved ones included, by name)."""
    read = [
        {"id": c["id"], "status": c.get("status", "active"), "resolved_on": c.get("resolved_on")}
        for c in training_context_registry.RECORDED_CONSTRAINTS
        if is_lower_leg(c.get("id")) or is_lower_leg(c.get("detail"))
    ]
    active = {c["id"] for c in training_context_registry.active_constraints()}
    return [r["id"] for r in read if r["id"] in active], read


def lower_leg_holds(date: str, pain_flag_instances: Any, pain_dismissals: Any = None) -> list[str]:
    """The lower-leg causes alone — the strain flags that hold on `date` and the active standing lower-leg constraints,
    named as `compute` names them in `held_by` (no deload or baseline cause). The run on-ramp and the lower-leg prep
    read this (#5090)."""
    events = _strain_events(date, pain_flag_instances, pain_dismissals)
    return [f"strain_flag:{e['site']}" for e in events if e["holds"]] + [f"standing_constraint:{i}" for i in _standing_lower_leg()[0]]


def compute(
    date: str,
    window: Mapping[str, Any],
    *,
    pain_flag_instances: Optional[list] = None,
    pain_dismissals: Optional[list] = None,
    deload_records: Optional[list] = None,
    prior_level: Optional[int] = None,
) -> dict[str, Any]:
    """The ramp for `date`. `window` is `steps_resolver.steps_range(*window_days(date), fetch=...)`'s return."""
    floor, target = training_charter.charter_value("steps.floor"), training_charter.charter_value("steps.target")
    if not (floor and target):  # the charter did not load (fail-soft loader): state it, never ramp to an invented floor
        return {"date": date, "state": "unknown", "reason": "the training charter did not load", "charter_version": None}
    floor, target = int(floor), int(target)
    days = list(window.get("days") or [])
    base = baseline(days)
    avg = base["trailing_avg"]
    events = _strain_events(date, pain_flag_instances, pain_dismissals)
    standing_active, standing_read = _standing_lower_leg()
    deload = deload_word.active_record(deload_records, date)

    held_by = [f"strain_flag:{e['site']}" for e in events if e["holds"]]
    held_by += [f"standing_constraint:{i}" for i in standing_active]
    if deload:
        held_by.append(f"deload_record:{deload.get('start_date')}")
    no_baseline = avg is None or base["days_counted"] < MIN_BASELINE_DAYS
    if no_baseline:
        held_by.append("no_baseline")
    releases = [e["released_on"] for e in events if not e["holds"] and e["released_on"]]
    released_on = max(releases) if releases and not held_by else None

    held_days = floor_held_days(days, floor)
    out: dict[str, Any] = {
        "date": date,
        "window_days": len(days),
        "trailing_avg": avg,
        "days_counted": base["days_counted"],
        "excluded_days": base["excluded_days"],
        "floor": floor,
        "floor_held_days": held_days,
        "step_per_week": None,
        "weeks_to_floor": None,
        "level": None,
        "today_target": None,
        "stretch_target": None,
        "state": "holding",
        "held_by": held_by,
        "released_on": released_on,
        "standing_constraints_read": standing_read,
        "owner_adjustable": ["steps.ramp.ramp_window_days", "RAMP_PCT_PER_WEEK", "RAMP_MAX_WEEKS", "RELEASE_QUIET_DAYS"],
        "derivation": (
            f"step_per_week = max({RAMP_PCT_PER_WEEK:.0%} x trailing_avg, (floor - trailing_avg) / {RAMP_MAX_WEEKS}); "
            f"level = min(floor, trailing_avg + step_per_week) rounded up to {ROUND_TO}; the mean covers measured days only"
        ),
        "charter_version": training_charter.charter_version(),
    }
    if no_baseline:
        out["derivation"] += f"; fewer than {MIN_BASELINE_DAYS} measured days -> no baseline, no level invented"
        return out
    assert avg is not None
    if avg >= floor:
        step = 0
        out["step_per_week"], out["weeks_to_floor"] = 0, 0
    else:
        step = max(RAMP_PCT_PER_WEEK * avg, (floor - avg) / RAMP_MAX_WEEKS)
        out["step_per_week"] = _round_up(step)
        out["weeks_to_floor"] = int(math.ceil((floor - avg) / step))
    if held_by:
        level = min(floor, int(prior_level) if prior_level else avg)
        out.update(level=level, today_target=level, state="holding")
        return out
    level = floor if avg >= floor else min(floor, _round_up(avg + step))
    out.update(level=level, today_target=min(floor, level))
    if avg < floor:
        out["state"] = "ramping"
    elif held_days >= FLOOR_HOLD_DAYS:
        out.update(state="at_target", stretch_target=target)
    else:
        out["state"] = "at_floor"
    return out
