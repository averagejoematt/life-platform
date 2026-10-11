"""lambdas/coach/prediction_direction_window.py — a direction call graded across its OWN window (#4617).

THE DEFECT
----------
A direction call ("weight will trend downward over the first 14 days") was graded by
``coach_prediction_evaluator._get_ewma_trend``: the smoothed level of the LATEST readings
against the smoothed level seven readings earlier, inside a fixed ±2% band, on whatever day
the grader ran. It never looked at the start of the call's window. Two calls sealed before
day one that weight would trend down were graded flat, and so wrong, on 2026-10-04 while
the served weigh-ins fell from 327.3 lb (September 6) to 312.1 lb (October 4): the window
had moved a long way, the last week had not.

THE RULE
--------
A dated direction call is graded on the change from the START of its window to its END —
the readings a reader can find on the site's own chart:

  * **The window** is ``[created_date, created_date + the call's STATED window]``
    (``evaluation_window_days``; the domain-clamped window only when none is stated). "Over
    the first 14 days" is graded on days 1 to 15's readings — the sentence's own window —
    even though the domain minimum (``coach.prediction_windows``) holds the GRADE back until
    the longer clamped window has passed. A sealed call's ``created_date`` is genesis.
    Readings after the window's last day are never read, however late the grader runs.
  * **First and last.** The first reading on or after the start and the last reading on or
    before the end. Each must sit within ``EDGE_GRACE_DAYS`` of its edge (a missed weigh-in
    is not a missing window; a fortnight's gap is). An ``_Nday_avg`` call compares the mean
    of the first k readings with the mean of the last k (k = min(N, readings // 2)).
  * **The noise band is the metric's own.** ``band = median |day-to-day change|`` of the
    window's readings, divided by sqrt(k) for an averaged call. For white noise of SD s the
    median absolute step is ~1.35 s and the SD of a first-minus-last difference is ~1.41 s,
    so the band is about one standard deviation of the change "nothing happened" would
    produce — a band derived from the subject's own variance (ADR-105), not a fixed
    editorial percentage. Fewer than ``WINDOW_MIN_READINGS`` readings → no verdict.
  * **The verdict.** change > band → up; change < −band → down; else flat. A call is
    confirmed when the measured direction is the called one, refuted otherwise (#801: a
    flat window refutes a direction call).

``actual_value`` stays the FRACTIONAL change (change / |first|) — the slope unit every
consumer of a direction call's ``actual_value`` already reads (``coach_baseline``,
``web.prediction_reason``, ``web.site_api_foresight``) — and ``noise_band`` rides beside it
in the same unit so the "nothing changes" comparison is scored against THIS call's band.
``window`` carries the start/end days and the first/last readings in the metric's own units
so a page can print the rule a reader can check.

A row with no parseable ``created_date`` has no window; it keeps the legacy EWMA path
(``legacy_trend``), unchanged, so no grade is invented.

Pure: the evaluator hands in its own data path (``get_source_data`` / ``extract_metric_series``),
so the cache key and the phase filter stay the evaluator's.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Callable

from experiment.measurable_metrics import METRIC_SOURCES

from coach.prediction_point_grader import POINT_GRACE_DAYS, POINT_LOOKBACK_DAYS

#: A first/last reading may sit this many days inside its edge of the window.
EDGE_GRACE_DAYS = POINT_GRACE_DAYS
#: Fewer readings than this inside the window → no verdict (three day-to-day steps minimum
#: for a median that is not one step).
WINDOW_MIN_READINGS = 4
#: The grader's own marker for a flat verdict — ``web.prediction_reason`` reads it.
FLAT_MARKER = "metric flat"
#: The reason prefix every window-graded row carries, so a reader of the raw row can tell
#: the two methods apart.
WINDOW_MARKER = "[window]"
BAND_RULE = "the median day-to-day change of the readings inside the window"

_AGG = (("_30day_avg", 30), ("_14day_avg", 14), ("_7day_avg", 7))


def _day(text: Any) -> datetime | None:
    try:
        return datetime.strptime(str(text or "")[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def split_metric(metric_key: str) -> tuple[str, int]:
    """('hrv_7day_avg') -> ('hrv', 7); a raw key -> (key, 1)."""
    for suffix, days in _AGG:
        if metric_key.endswith(suffix):
            return metric_key[: -len(suffix)], days
    return metric_key, 1


def window_bounds(created_date: Any, window_days: Any, today_str: str) -> tuple[str, str] | None:
    """``(start, end)`` ISO days, the end never after ``today_str``; None when undated."""
    start = _day(created_date)
    today = _day(today_str)
    try:
        days = int(window_days)
    except (TypeError, ValueError):
        return None
    if start is None or today is None or days <= 0:
        return None
    end = min(start + timedelta(days=days), today)
    if end <= start:
        return None
    return _iso(start), _iso(end)


def day_to_day_swing(values: list[float]) -> float | None:
    """Median absolute change between consecutive readings; None below the floor."""
    if len(values) < WINDOW_MIN_READINGS:
        return None
    steps = sorted(abs(b - a) for a, b in zip(values, values[1:]))
    mid = len(steps) // 2
    return steps[mid] if len(steps) % 2 else (steps[mid - 1] + steps[mid]) / 2


def measure(series: list[tuple[str, float]], start: str, end: str, metric_key: str) -> tuple[dict | None, str | None]:
    """``(window, None)`` — the measured change across [start, end] — or ``(None, why_not)``.

    ``series`` is the base metric's chronological ``(date, value)`` list (any range)."""
    inside = [(d[:10], float(v)) for d, v in series or [] if start <= str(d)[:10] <= end and v is not None]
    if len(inside) < WINDOW_MIN_READINGS:
        return None, f"{len(inside)} reading(s) inside the window {start}..{end}, fewer than {WINDOW_MIN_READINGS}"
    first_day, last_day = inside[0][0], inside[-1][0]
    if (_day(first_day) - _day(start)).days > EDGE_GRACE_DAYS:
        return None, f"no reading within {EDGE_GRACE_DAYS} days of the window's start {start} (first is {first_day})"
    if (_day(end) - _day(last_day)).days > EDGE_GRACE_DAYS:
        return None, f"no reading within {EDGE_GRACE_DAYS} days of the window's end {end} (last is {last_day})"
    values = [v for _, v in inside]
    _base, agg = split_metric(metric_key)
    k = max(1, min(agg, len(values) // 2))
    first = sum(values[:k]) / k
    last = sum(values[-k:]) / k
    swing = day_to_day_swing(values)
    band = swing / math.sqrt(k)
    change = last - first
    direction = "up" if change > band else "down" if change < -band else "flat"
    return {
        "start": start,
        "end": end,
        "first_date": first_day,
        "first_value": round(first, 4),
        "last_date": last_day,
        "last_value": round(last, 4),
        "averaged_over": k,
        "readings": len(values),
        "change": round(change, 4),
        "band": round(band, 4),
        "band_rule": BAND_RULE + (f", over the square root of {k} readings averaged" if k > 1 else ""),
        "direction": direction,
    }, None


def verdict(predicted: str, window: dict, metric_key: str) -> dict:
    """The graded result for a measured window (pure)."""
    first = window["first_value"]
    if not first:
        return {
            "status": "inconclusive",
            "reason": f"{WINDOW_MARKER} {metric_key}: the window's first reading is zero, so no fractional change",
            "actual_value": None,
            "beats_null": False,
        }
    frac = window["change"] / abs(first)
    band = window["band"] / abs(first)
    actual = window["direction"]
    span = (
        f"{metric_key} {window['first_value']:g} on {window['first_date']} -> {window['last_value']:g} on {window['last_date']} "
        f"(change {window['change']:+g}, band ±{window['band']:g}, window {window['start']}..{window['end']})"
    )
    if actual == predicted:
        status, reason = "confirmed", f"{WINDOW_MARKER} {span}: trend={actual}, predicted={predicted}"
    elif actual == "flat":
        status, reason = "refuted", f"{WINDOW_MARKER} predicted {predicted}, {FLAT_MARKER} — {span}"
    else:
        status, reason = "refuted", f"{WINDOW_MARKER} {span}: trend={actual}, predicted={predicted}"
    return {
        "status": status,
        "reason": reason,
        "actual_value": round(frac, 6),
        "noise_band": round(band, 6),
        "beats_null": status == "confirmed",
        "window": window,
    }


def legacy_trend(predicted: str, actual_direction: str, slope: float, metric_key: str, noise_threshold: float) -> dict:
    """The pre-#4617 verdict over ``_get_ewma_trend`` — kept for an undated row only."""
    if actual_direction == predicted and slope and abs(slope) > noise_threshold:
        return {
            "status": "confirmed",
            "reason": f"{metric_key} trend={actual_direction} (slope={slope:.4f}), predicted={predicted}",
            "actual_value": slope,
            "beats_null": True,
        }
    if actual_direction == "flat":
        # #801: a direction call is refuted whether the metric moved the other way or not at all.
        reason = (
            f"predicted {predicted}, {FLAT_MARKER} (slope={slope:.4f}, "
            f"within ±{noise_threshold} noise band) — no movement to confirm the call"
        )
    else:
        reason = f"{metric_key} trend={actual_direction} (slope={slope:.4f}), predicted={predicted}"
    return {"status": "refuted", "reason": reason, "actual_value": slope, "beats_null": False}


def _inconclusive(reason: str) -> dict:
    return {"status": "inconclusive", "reason": reason, "actual_value": None, "beats_null": False}


def evaluate(
    pred: dict,
    eval_spec: dict,
    data_cache: dict,
    today_str: str,
    *,
    window_days: Any,
    get_source_data: Callable,
    extract_metric_series: Callable,
    ewma_trend: Callable,
    noise_threshold: float,
    include_pilot: bool = False,
) -> dict | None:
    """Grade one direction call. None for a malformed spec (the evaluator skips it)."""
    metric_key = eval_spec.get("metric")
    predicted = eval_spec.get("condition")
    if not metric_key or not predicted:
        return None
    pred_dir = str(predicted).lower().strip()
    bounds = window_bounds((pred or {}).get("created_date"), window_days, today_str)
    if bounds is None:
        actual_direction, slope = ewma_trend(metric_key, data_cache, today_str, include_pilot)
        if actual_direction is None:
            return _inconclusive(f"Insufficient data to determine trend for '{metric_key}'")
        if pred_dir not in ("up", "down"):
            return _inconclusive(f"Invalid predicted direction: '{predicted}'")
        return legacy_trend(pred_dir, actual_direction, slope, metric_key, noise_threshold)
    if pred_dir not in ("up", "down"):
        return _inconclusive(f"Invalid predicted direction: '{predicted}'")
    base, _agg = split_metric(metric_key)
    source = METRIC_SOURCES.get(base)
    if not source:
        return _inconclusive(f"Insufficient data to determine trend for '{metric_key}'")
    start, end = bounds
    lookback = max(POINT_LOOKBACK_DAYS, (_day(today_str) - _day(start)).days)
    records = get_source_data(source, data_cache, today_str, lookback_days=lookback, include_pilot=include_pilot)
    window, why = measure(extract_metric_series(records, base), start, end, metric_key)
    if window is None:
        return _inconclusive(f"{WINDOW_MARKER} Insufficient data to grade '{metric_key}' across its window: {why}")
    return verdict(pred_dir, window, metric_key)
