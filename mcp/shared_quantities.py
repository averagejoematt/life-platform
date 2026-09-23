"""mcp/shared_quantities.py — ONE definition of weekly walking hours and of the loss rate (#4068).

WHY THIS EXISTS

On 2026-09-22 the owner read two numbers for one quantity, twice, on one screen:

  * weekly walking hours — 12.82 from the walking-volume layer on `plan_next_session`,
    15.82 from the adherence critic beside it;
  * loss rate — 4.52 lb/wk from `rate_advocate`, 2.99 lb/wk from the deficit critic;

and on 09-19 `get_benchmark` disagreed with `plan_next_session` on walking by 2.7x. Nothing
was mis-added. Each reader chose its own window, its own sources and its own estimator:

  walking  12.82 = the layer over 09-17..09-23 — the plan's TARGET day (not yet lived) and a
                   half-lived 09-22 counted as two of the seven days;
           15.82 = the layer over 09-15..09-21 — seven completed days, the right window, but
                   5.75 h of it were WHOOP walks recorded INSIDE Hevy treadmill sessions that
                   the Hevy blocks already counted (see `training.walking_volume`, #4068);
           get_benchmark = Strava `Walk`/`Hike` only, 28 days — no Hevy blocks at all.
  loss     4.52  = `get_benchmark`'s 28-day least-squares slope, cross-phase: it read the
                   pre-genesis weigh-ins (326-328 lb, 08-24..09-05) and both water weeks;
           2.99  = the nutrition resolver's 14-day FIRST-vs-LAST endpoint slope ending 09-21
                   (09-12 319.68 -> 09-21 315.84) — inside water weeks 1-2.

THE DEFINITIONS (each stated once, here, and imported by every critic and tool)

  WEEKLY WALKING HOURS
    window   the 7 COMPLETED Pacific days ending `completed_end(day)` — never a day that has
             not finished (a plan for tomorrow reads through yesterday);
    sources  Strava Walk/Hike/Ride UNION Hevy treadmill/walking/cycling blocks
             (`training.walking_volume`, #3930);
    de-dup   in TIME, across devices and against Hevy sessions (`walking_volume.dedup_strava`).
    A longer window (get_benchmark's 28-day chronic read, which its bands are measured in) is
    the SAME definition over more days, divided by weeks — never a different source set.

  LOSS RATE (lb/wk, positive = losing)
    window    the trailing `LOSS_RATE_WINDOW_DAYS` (14) days ending `completed_end(day)` — v0.3
              §1: "the 14-day weigh-in average is the number; single days are noise";
    exclusion experiment weeks 1-2 are water (`owner_redlines.REDLINES["rate_schedule_lb_wk"]`
              step note "weeks 1–2 excluded (water)"), so the window never starts before
              genesis + 14 days;
    estimator the least-squares slope over every weigh-in in the window
              (`health.weight_trend`'s estimator — robust to one noisy morning, which the
              first-vs-last endpoint is not);
    honesty   a window spanning fewer than `tdee.MIN_TREND_DAYS` days is `provisional`: the
              number is reported, and no critic argues a change from it.

  The TDEE back-solve's endpoint trend (`health.tdee.weight_trend_lb_per_wk`, #3931) is a
  DIFFERENT quantity — "could this intake have produced this much change" — and is left alone.

`tests/test_shared_quantities_4068.py` holds the AST derivation guard: every critic/tool call
site that reports either quantity must reach it through this module.
"""

from __future__ import annotations

from typing import Any, Callable

from common.pacific_time import pacific_today, shift_day_key
from health.tdee import MIN_TREND_DAYS
from health.weight_trend import _ols_slope
from training import walking_volume

from mcp import core as _core

SHARED_QUANTITIES_VERSION = "shared-quantities@1.0.0"

WALK_WINDOW_DAYS = 7
LOSS_RATE_WINDOW_DAYS = 14
WATER_WEEKS_EXCLUDED = 2  # v0.3 §1 — owner_redlines rate_schedule_lb_wk: "weeks 1–2 excluded (water)"


def _genesis() -> str:
    from common.constants import EXPERIMENT_START_DATE

    return str(EXPERIMENT_START_DATE)


def completed_end(day: str, today: str | None = None) -> str:
    """The last COMPLETED Pacific day on or before `day`: min(day, today - 1).

    Both quantities are read over completed days only. A day still in progress under-reads a
    week by construction — that is how `plan_next_session` read 12.82 h."""
    yesterday = shift_day_key(today or pacific_today(), -1)
    return min(str(day)[:10], yesterday)


# ── weekly walking hours ─────────────────────────────────────────────────────────────
def walking_layer(
    end_day: str,
    *,
    days: int = WALK_WINDOW_DAYS,
    today: str | None = None,
    read: Callable[[str, str, str], list[dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    """THE walking read: the de-duplicated union over the `days` completed days ending
    `completed_end(end_day)`. None only for an unparseable day key. A partition read that
    RAISES reaches the layer as None — unreadable, never zero hours. `read(source, start, end)`
    is the caller's partition reader (default `mcp.core.query_source_range`); the DEFINITION
    — window, sources, de-dup — is not injectable."""
    end = completed_end(end_day, today)
    start = shift_day_key(end, -(days - 1))
    if start == end and days > 1:  # unparseable day key — shift_day_key returns it unchanged
        return None

    def _read(source: str) -> list[dict[str, Any]] | None:
        try:
            return (read or _core.query_source_range)(source, start, end)
        except Exception:  # noqa: BLE001 — unreadable is reported by the layer, never raised past it
            return None

    layer = walking_volume.build(window_start=start, window_end=end, strava_items=_read("strava"), hevy_workouts=_read("hevy"))
    layer["window"] = {"start": start, "end": end, "days": days}
    total = layer.get("total_hr")
    layer["hr_wk"] = round(float(total) * 7.0 / days, 2) if total is not None else None
    layer["definition"] = SHARED_QUANTITIES_VERSION + ": weekly walking hours (see mcp/shared_quantities.py)"
    return layer


def weekly_walking_hours(end_day: str, *, today: str | None = None) -> float | None:
    """Hours in the 7 completed days ending `completed_end(end_day)`. None = unknown."""
    layer = walking_layer(end_day, today=today)
    return None if not layer else layer.get("total_hr")


# ── loss rate ────────────────────────────────────────────────────────────────────────
def _weighins(rows: list[dict[str, Any]] | None) -> list[tuple[str, float]]:
    pts: list[tuple[str, float]] = []
    for r in rows or []:
        try:
            w = float(r.get("weight_lbs"))
        except (TypeError, ValueError):
            continue
        if w <= 0:
            continue
        d = str(r.get("date") or str(r.get("sk") or "").replace("DATE#", ""))[:10]
        if len(d) == 10:
            pts.append((d, w))
    return sorted(pts)


def _days(a: str, b: str) -> int:
    from common.pacific_time import parse_day_key

    da, db = parse_day_key(a), parse_day_key(b)
    return (db - da).days if da and db else 0


def loss_rate_from_rows(
    rows: list[dict[str, Any]] | None,
    end: str,
    *,
    window_days: int = LOSS_RATE_WINDOW_DAYS,
    genesis: str | None = None,
) -> dict[str, Any]:
    """PURE: the loss rate over the `window_days` ending `end` (inclusive), water weeks excluded.

    `rate_lb_wk` is POSITIVE when losing. `provisional` is True when the weigh-ins in the
    window span fewer than MIN_TREND_DAYS days. `rate_lb_wk` is None with fewer than two
    weigh-ins — unknown, never 0."""
    g = genesis or _genesis()
    water_through = shift_day_key(g, 7 * WATER_WEEKS_EXCLUDED - 1)
    start = shift_day_key(end, -(window_days - 1))
    if end >= g:  # a window reaching into the campaign never starts inside its water weeks
        start = max(start, shift_day_key(water_through, 1))
    pts = [(d, w) for d, w in _weighins(rows) if start <= d <= end]
    out: dict[str, Any] = {
        "rate_lb_wk": None,
        "provisional": True,
        "window": {"start": start, "end": end, "days": window_days},
        "water_weeks_excluded_through": water_through,
        "n_weighins": len(pts),
        "span_days": 0,
        "estimator": "least-squares slope of every weigh-in in the window (health.weight_trend)",
        "definition": SHARED_QUANTITIES_VERSION + ": loss rate (see mcp/shared_quantities.py)",
    }
    if start > end:
        out["reason"] = f"the window ends inside water weeks 1-2 (through {water_through}) — no rate is measured yet"
        return out
    if len(pts) < 2:
        out["reason"] = f"{len(pts)} weigh-in(s) in {start}..{end} — a rate needs two"
        return out
    xs = [_days(pts[0][0], d) for d, _ in pts]
    slope = _ols_slope(xs, [w for _, w in pts])
    span = xs[-1] - xs[0]
    out["span_days"] = span
    if slope is None:
        out["reason"] = "degenerate window (every weigh-in on one day)"
        return out
    out["rate_lb_wk"] = round(-slope * 7.0, 2)
    out["provisional"] = span < MIN_TREND_DAYS
    if out["provisional"]:
        out["reason"] = f"weigh-ins span {span} day(s), under the {MIN_TREND_DAYS}-day minimum — reported, not argued from"
    return out


def weekly_loss_rates_from_rows(rows: list[dict[str, Any]] | None, end: str, *, weeks: int = 2) -> list[float] | None:
    """PURE: one rate per trailing 7-day week, oldest -> newest, same estimator and water floor.
    A week with fewer than two post-water weigh-ins is skipped. None when no week has a rate."""
    rates: list[float] = []
    for k in range(weeks - 1, -1, -1):
        r = loss_rate_from_rows(rows, shift_day_key(end, -7 * k), window_days=7)
        if r["rate_lb_wk"] is not None:
            rates.append(r["rate_lb_wk"])
    return rates or None
