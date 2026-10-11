"""health/training_output_channel.py — the ONE input for the deficit tracker's "Training
output" channel (#3754, the 2026-10-04 data-source-sweep extension).

WHY THIS EXISTS

Both deficit-sustainability readers — `mcp/tools_nutrition.tool_get_deficit_sustainability`
and the public `web/site_api_nutrition.deficit_sustainability` — scored channel 5 off the
Strava day row's `total_kilojoules`. Strava populates per-activity `kilojoules` only for
power-equipped activities, and the owner has none: the sweep measured the day-level rollup
at > 0 on **0 of 1,242 stored day rows all-time** (0 of 90 in 2026). So the series was
always `[0, 0, 0, ...]`, `first_avg == 0` short-circuited the trend to "stable", and the
channel could never read "degraded" — one of the five channels the composite verdict is
calibrated against was structurally dark, exactly as the habit channel was before #2221.

THE INPUT NOW

`training.training_load.daily_training_load` — the SAME per-day load model the ACWR /
training-load surfaces (`mcp/tools_training._get_training_load`) and computed_metrics' stored
TSB read (#4075 4A): HR-scored Strava activities (Banister TRIMP above the Zone-1 ceiling),
Hevy sessions charged on worked-set time, duration proxies where neither exists, kilojoules
where a power meter ever reports them. A day the owner trained therefore carries a non-zero
value whenever any of those inputs exists; `tests/test_training_output_channel_3754.py`
holds the negative control — the series must NOT be all-zero across a window that contains
logged sessions.

WHAT THE SERIES IS

One value per OBSERVED day — a day with at least one Strava or Hevy record — in date order.
A Zone-1 walk is an observed day at 0 (measured rest, the #4075 reading), not a gap; a day
with no record at all is absent, as it always was for this channel. The channel still
compares first-third vs last-third of that series, so a drop in per-session output is what
it sees; a drop in session COUNT (training less often at the same output) is not, and the
`input` block says so (`series: observed_training_days`).

PURE: no I/O, no clock. The callers hand in the rows they already read.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from training import training_load

#: What the channel reads, named on output so a caller never has to infer it (ADR-105).
MEASURE = "daily_training_load"
#: What it replaced, and why — carried on output because the replaced field still exists
#: on every stored row and a reader comparing old and new verdicts deserves the reason.
REPLACED = "strava.total_kilojoules (> 0 on 0 of 1,242 stored day rows all-time — 2026-10-04 sweep, #3754)"
SERIES = "observed_training_days"


def _records(rows: Optional[Iterable[Mapping[str, Any]]]) -> list[Mapping[str, Any]]:
    return [r for r in (rows or []) if isinstance(r, Mapping)]


def series(strava_rows: Optional[Iterable[Mapping[str, Any]]], hevy_rows: Optional[Iterable[Mapping[str, Any]]]) -> dict[str, Any]:
    """The channel's input over the rows given.

    Returns ``{"values": [...], "by_day": {day: load}, "input": {...}}`` — ``values`` is the
    date-ordered series the trend is computed on (one per observed day), ``input`` the
    provenance block the channel carries on output.
    """
    strava = _records(strava_rows)
    hevy = [r for r in _records(hevy_rows) if not r.get("tombstone")]  # #4030: a tombstoned Hevy row is a superseded aggregate
    load_by_day, basis = training_load.daily_training_load(strava, hevy)
    observed = {training_load.day_key(r) for r in strava + hevy}
    observed.discard("")
    by_day = {d: float(load_by_day.get(d, 0.0)) for d in observed}
    for d, v in load_by_day.items():  # a loaded day is observed by definition
        by_day.setdefault(d, float(v))
    values = [round(by_day[d], 1) for d in sorted(by_day)]
    sessions = sum(len(r.get("activities") or []) for r in strava) + len(hevy)
    return {
        "values": values,
        "by_day": {d: round(v, 1) for d, v in sorted(by_day.items())},
        "input": {
            "measure": MEASURE,
            "unit": basis.get("unit"),
            "model": basis.get("model"),
            "series": SERIES,
            "days_observed": len(values),
            "days_with_load": sum(1 for v in values if v > 0),
            "sessions": sessions,
            "confidence": basis.get("confidence"),
            "replaced": REPLACED,
        },
    }
