"""wake_consistency.py — THE wake-time consistency grade (#5133, epic #5120): pure, no DynamoDB, no clock, no model.

The rule is the charter's (`config/training_charter.json` `sleep.wake_time`, read through
`training_charter.charter_value`): out of bed within `tolerance_minutes` of the anchor EVERY day, weekends
included, where the anchor is his own median wake time over the trailing `anchor_window_days` (the days BEFORE
the graded day, so a day is never graded against itself). ONE hit definition: the coaches read it, and the
out-of-bed-on-time core habit (#5124, M4) is graded here, never by a second definition.

UNKNOWN, never a miss (ADR-104): a day with no main-sleep wake time is `unknown`; a window with fewer than
`min_days_for_anchor` readable days has no anchor, so the day is `unknown` too — no anchor is guessed.

The input is `{YYYY-MM-DD: "HH:MM"}` — the main sleep's end (nap=false) as a PACIFIC clock time, the caller's
read. The rule reads sleep TIMING only: the 2026-10-10 heart-rate regime marker (`health.hr_regime`, #4999)
does not touch it; the HR-derived sleep surfaces re-baseline under #5029, not here.

A known limit, stated: the median is taken on minutes after midnight, so a wake time that crosses midnight
(an all-nighter) reads as an outlier rather than wrapping. The distance itself is circular.
"""

from __future__ import annotations

import datetime as _dt
from statistics import median
from typing import Any, Mapping, Optional

from training import training_charter

MODULE_VERSION = "wake-consistency@1.0.0"
ON_TIME, OFF, UNKNOWN = "on_time", "off", "unknown"
_P = "sleep.wake_time."


def rule() -> dict[str, Any]:
    """The charter's numbers: tolerance_minutes, anchor_window_days, min_days_for_anchor (None when absent)."""
    return {k: training_charter.charter_value(_P + k) for k in ("tolerance_minutes", "anchor_window_days", "min_days_for_anchor")}


def _minutes(v: Any) -> Optional[int]:
    """'06:45' / '6:45' / '06:45:10' -> 405; anything else None."""
    if not isinstance(v, str):
        return None
    parts = v.strip().split(":")
    if len(parts) < 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else None


def _distance(a: float, b: float) -> float:
    d = abs(a - b) % 1440
    return min(d, 1440 - d)


def _day(v: str) -> Optional[_dt.date]:
    from common.pacific_time import parse_day_key  # THE calendar-day parse (#3609); no clock is read

    return parse_day_key(str(v)[:10])


def grade_day(day: str, wakes: Mapping[str, Any], *, settings: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """One day's verdict against the anchor of the `anchor_window_days` days before it."""
    s = dict(settings) if settings is not None else rule()
    tol, window, need = s.get("tolerance_minutes"), s.get("anchor_window_days"), s.get("min_days_for_anchor")
    base: dict[str, Any] = {"date": day, "rule": "sleep.wake_time", "tolerance_minutes": tol, "anchor_window_days": window}
    d = _day(day)
    if d is None or not tol or not window or not need:
        return {**base, "state": UNKNOWN, "reason": "rule_unreadable" if d is not None else "bad_date"}
    wake = _minutes(wakes.get(day))
    prior = [_minutes(wakes.get((d - _dt.timedelta(days=i)).isoformat())) for i in range(1, int(window) + 1)]
    known = [m for m in prior if m is not None]
    out = {**base, "wake_minutes": wake, "anchor_days": len(known)}
    if len(known) < int(need):
        return {**out, "state": UNKNOWN, "reason": "no_anchor", "anchor_minutes": None}
    anchor = float(median(known))
    out["anchor_minutes"] = anchor
    if wake is None:
        return {**out, "state": UNKNOWN, "reason": "no_wake_time"}
    delta = _distance(wake, anchor)
    return {**out, "delta_minutes": delta, "state": ON_TIME if delta <= float(tol) else OFF}


def grade_week(end: str, wakes: Mapping[str, Any], *, days: int = 7, settings: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """The `days` days ending on `end` (inclusive): each day's verdict and the counts. Unknown days are not misses."""
    d = _day(end)
    if d is None:
        return {"version": MODULE_VERSION, "end": end, "state": UNKNOWN, "reason": "bad_date", "days": []}
    rows = [grade_day((d - _dt.timedelta(days=i)).isoformat(), wakes, settings=settings) for i in range(days - 1, -1, -1)]
    on = sum(r["state"] == ON_TIME for r in rows)
    off = sum(r["state"] == OFF for r in rows)
    return {
        "version": MODULE_VERSION,
        "charter_version": training_charter.charter_version(),
        "end": end,
        "on_time": on,
        "off": off,
        "unknown": len(rows) - on - off,
        "days": rows,
    }
