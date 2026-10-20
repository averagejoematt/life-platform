"""training_calendar.py — the per-date training calendar: each day of the week typed lifting or rest (#5191).

WHY THIS EXISTS

The split runs as a SEQUENCE (`session_sequence`, #4110): the plan serves the next undone session every day, and a
rest day only postpones it. That is right for WHAT to lift, and it can never say WHICH dates are lifting days — so
the training-day fuel block (#5101, `health.calorie_target`) could only state the lifting uplift and the rest-day
offset as conditional readings at the base target. This module is the missing calendar. It does not change what is
served; it types the dates of the current week so the one calorie resolver can fuel them.

THE RULE (pure — no clock, no I/O; the credited dates and the count are injected)

  week        Monday to Sunday (Pacific day keys) of the week holding `day`.
  count       the charter's `split.lifting_days_per_wk` (owner ruling 5, 2026-10-18). Unreadable -> the calendar
              says so (`state: "unreadable"`, `planned_dates: None`) and every caller keeps the untyped reading.
  credited    the week's dates carrying a CREDITED program session — `session_sequence.completed_sessions`, the ONE
              credit rule (#4312: a loaded program log whose sets reach the role's anchors). A credited date is a
              lifting day, past or present. A past date without one is a rest day: it already happened.
  remaining   max(0, count - credited this week): the sessions still to lay.
  candidates  the dates from `today` on that carry no credited session and are not unavailable (an active travel
              window — `calorie_target.classify_day_type` types those travel anyway).
  laid        the first `remaining` candidates, the NOMINAL lifting weekdays first (`program_structure.
              NOMINAL_LIFTING_DAYS`: the platform's placement, a walk day between shoulders+arms and the next upper
              day), then the earliest other candidates. Every other candidate is a rest day.

So a rest-day postponement moves a session to a later date in the SAME week and leaves the typed week's lifting
count where it was, as long as enough days remain; only a week that runs out of days types fewer lifting days, and
the calendar says so (`reaches_count: False`). An extra session (a sixth lift) is credited as it happens. The one
resolver balances whatever mix the calendar types (a rest day takes -(uplift x lifting days / rest days)), so the
typed week averages the base target either way.

KNOWN LIMIT: the balance is recomputed from the CURRENT typing. A past rest day was fuelled under the week's earlier
typing; when a postponement changes the count, the past day's offset and the remaining days' offsets can differ.
"""

from __future__ import annotations

from datetime import date as _date, timedelta
from typing import Any, Iterable

from common.pacific_time import parse_day_key, shift_day_key

ISSUE = "#5191"
COUNT_PATH = "split.lifting_days_per_wk"
WEEK_DAYS = 7

RULE = (
    "the week is Monday to Sunday (Pacific); a date with a credited program session is a lifting day; a past date "
    "without one is a rest day; the sessions still owed to the charter's lifting-days count are laid on the remaining "
    "dates, the nominal lifting weekdays first, then the earliest other dates; every other date is a rest day — so a "
    f"rest-day postponement moves a session inside the week and never changes the week's count while days remain ({ISSUE})"
)


def week_dates(day: str) -> list[str]:
    """The Monday-to-Sunday Pacific day keys of the week holding `day`."""
    d = parse_day_key(day)
    if d is None:
        raise ValueError(f"not a YYYY-MM-DD day key: {day!r}")
    monday = d - timedelta(days=d.weekday())
    return [(monday + timedelta(days=i)).isoformat() for i in range(WEEK_DAYS)]


def lifting_days_per_wk() -> int | None:
    """The charter's lifting-days count, or None when the charter cannot be read (never a remembered 5)."""
    from training.training_charter import charter_value  # noqa: PLC0415 — lazy: import-safe offline

    v = charter_value(COUNT_PATH)
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None


def _nominal_weekdays() -> set[int]:
    from training import program_structure  # noqa: PLC0415 — lazy: the template module is heavy

    return {int(x) for x in program_structure.NOMINAL_LIFTING_DAYS}


def credited_dates(block_workouts: Iterable[dict[str, Any]] | None, day: str) -> list[str] | None:
    """The dates carrying a credited program session up to and including `day` (the one credit rule,
    `session_sequence.completed_sessions`). None when the Hevy record was not read — never an empty week."""
    if block_workouts is None:
        return None
    from training import session_sequence  # noqa: PLC0415

    return [c["date"] for c in session_sequence.completed_sessions(block_workouts, shift_day_key(day, 1))]


def week_calendar(
    day: str,
    credited: Iterable[str] | None,
    *,
    today: str | None = None,
    lifting_days: int | None = None,
    unavailable_dates: Iterable[str] = (),
    nominal_weekdays: Iterable[int] | None = None,
) -> dict[str, Any]:
    """The typed week holding `day`: `{state, dates, days:[{date, day_type, basis}], planned_dates, ...}`.

    `credited` is the credited-session dates (None = the Hevy record was not read). `today` (default `day`) splits the
    week into what happened and what is planned. `lifting_days` defaults to the charter's count."""
    dates = week_dates(day)
    today = today or day
    count = lifting_days if lifting_days is not None else lifting_days_per_wk()
    out: dict[str, Any] = {"state": "typed", "dates": dates, "today": today, "lifting_days_per_wk": count, "rule": RULE, "issue": ISSUE}
    if credited is None or count is None:
        why = "the Hevy record was not read" if credited is None else f"the charter's {COUNT_PATH} is unreadable"
        return {**out, "state": "unreadable", "reason": why, "days": None, "planned_dates": None}
    done = sorted({str(c)[:10] for c in credited} & set(dates))
    away = {str(x)[:10] for x in unavailable_dates}
    remaining = max(0, count - len(done))
    nominal = set(_nominal_weekdays() if nominal_weekdays is None else nominal_weekdays)
    candidates = [d for d in dates if d >= today and d not in done and d not in away]
    laid = set(sorted(candidates, key=lambda d: (_date.fromisoformat(d).weekday() not in nominal, d))[:remaining])
    days = []
    for d in dates:
        if d in done:
            t, basis = "lifting", "a credited program session (Hevy)"
        elif d < today:
            t, basis = "rest", "past, no credited program session"
        elif d in laid:
            t, basis = "lifting", f"planned: one of the {remaining} session(s) still owed to the week's {count}"
        elif d in away:
            t, basis = "rest", "unavailable (a travel window): no session laid"
        else:
            t, basis = "rest", f"planned rest: the week's {count} sessions sit on the other dates"
        days.append({"date": d, "day_type": t, "basis": basis})
    planned = [x["date"] for x in days if x["day_type"] == "lifting"]
    return {
        **out,
        "days": days,
        "planned_dates": planned,
        "credited_this_week": len(done),
        "remaining_sessions": remaining,
        "typed_lifting_days": len(planned),
        "reaches_count": len(planned) >= count,
    }


def planned_dates_over(dates: Iterable[str], credited: Iterable[str] | None, today: str) -> list[str] | None:
    """The lifting dates among `dates` (a window that may straddle two weeks), each week typed by `week_calendar`."""
    if credited is None:
        return None
    window = sorted({str(d)[:10] for d in dates})
    cred = list(credited)
    out: set[str] = set()
    for monday in sorted({week_dates(d)[0] for d in window}):
        cal = week_calendar(monday, cred, today=today)
        if cal["planned_dates"] is None:
            return None
        out.update(cal["planned_dates"])
    return [d for d in window if d in out]


def plan_fuel(date: str, disruption_state: dict[str, Any] | None, block_workouts: Iterable[dict[str, Any]] | None) -> dict[str, Any]:
    """The plan's `training_day_fuel` block (#5101) typed by this calendar: the travel-window dates are kept off the
    laying, the week is typed, and the one resolver fuels the date against the typed week. An unread Hevy record or
    charter count keeps the untyped reading (`unknown` at the base, the conditional readings) and names why."""
    from health import calorie_target  # noqa: PLC0415

    rows = list(block_workouts) if block_workouts is not None else None
    away = [d for d in week_dates(date) if calorie_target.classify_day_type(d, disruption=disruption_state)["day_type"] == "travel"]
    cal = week_calendar(date, credited_dates(rows, date), unavailable_dates=away)
    return calorie_target.plan_block(date, disruption_state, calendar=cal)
