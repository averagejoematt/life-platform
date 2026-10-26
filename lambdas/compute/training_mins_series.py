"""compute/training_mins_series.py — the correlation engine's `training_mins` series over THE session count (#5398).

`training_mins` (the day's training minutes) feeds a STORED correlation series: `training_mins_vs_recovery` in
`weekly_correlation_compute_lambda.CORRELATION_PAIRS`. It was the day's summed Strava `moving_time_seconds`, so on
a gym day it was the lift span plus the ride inside it (Hevy's whole-session push and the watch's own ride are both
Strava activities): 220 minutes for a 160-minute visit. From `TRAINING_MINS_CUTOVER_DATE` it reads
`training.session_count` — the visit's minutes, claimed once, with the Hevy rows the routine source anchors it on.

ADR-105 / the #5388 precedent: the series CHANGED DEFINITION on a date, and a change of definition is never silent.
The choice is per DAY and the date is a CONSTANT, not a clock read — a re-run recomputes every day under the definition
that day belongs to, whenever the engine runs, so a stored correlation is never a re-derivation of the old days under
the new rule. `SERIES_AMENDMENTS` is written onto each stored weekly record so a reader of the record sees the change.
Pure — no I/O.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from training import session_count

#: The first Pacific day `training_mins` is the visit's own minutes (set to the first full Pacific day after the
#: deploy of #5398; moving it later is a new amendment, never a silent edit). Before it: the summed Strava rows.
TRAINING_MINS_CUTOVER_DATE = "2026-10-28"

SERIES_AMENDMENTS: tuple[dict[str, Any], ...] = (
    {
        "amendment_id": "training_mins_session_count_5398",
        "effective_from": TRAINING_MINS_CUTOVER_DATE,
        "metrics": ["training_mins"],
        "pairs": ["training_mins_vs_recovery"],
        "issue": "#5398",
        "change": (
            "training_mins is the day's training minutes through THE session count (a gym visit once, its minutes claimed "
            "once, resolved with the Hevy rows) from this date; before it, the sum of the day's Strava activity times, "
            "which read a gym visit as the lift span plus the ride inside it. The series changed definition on this day: "
            "a correlation over a window spanning it mixes the two, and the pair's n and r are not comparable across it."
        ),
    },
)


def visit_minutes_by_date(strava_rows: Iterable[dict[str, Any]], hevy_rows: Iterable[dict[str, Any]]) -> dict[str, float]:
    """{date: the day's training minutes} from THE session count — a visit once, its minutes claimed once."""
    by_date = session_count.count(strava=list(strava_rows), hevy=list(hevy_rows))["by_date"]
    return {d: v["minutes"] for d, v in by_date.items()}


def training_mins(date: str, strava_day: Optional[dict[str, Any]], visit_minutes: dict[str, float]) -> Optional[float]:
    """The day's `training_mins`: None when the day has no Strava row (an absence, ADR-104); the summed rows before the
    cut-over; THE session count's minutes from it."""
    if not strava_day:
        return None
    if date < TRAINING_MINS_CUTOVER_DATE:
        return sum(  # session-count: the pre-cut-over definition, kept so the stored series is not re-derived
            float(a.get("moving_time_seconds") or 0) / 60 for a in strava_day.get("activities", [])
        )
    return visit_minutes.get(date, 0.0)
