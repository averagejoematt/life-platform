"""metric_reading — WHICH reading a graded bet's number came from: the device and the days (#4580 B-14).

"It came in at 16.4%" (/api/calls, the deep-sleep bet settled 2026-10-16) reproduced only as Eight Sleep's
7-day deep-sleep share over Oct 9–15, while the Whoop share to Oct 16 was 22.9%; the served bet named neither.
`coach_prediction_evaluator._resolve_metric_value` grades on the most recent value (a raw metric) or the mean
of the last N series points (a `_<N>day_avg` metric) of ONE source's rows. This reads the SAME cached rows
through the evaluator's own `_extract_metric_series` and takes the same slice, so the label can never describe
a different window than the number — `tests/test_bet_reading_provenance_4580.py` pins the mean of the points
named here equal to the graded value.

Lives beside the evaluator, not in it: the evaluator is at its size ceiling (`test_module_size_guard`).
"""

from typing import Any, Optional

_AGGREGATES = (("_30day_avg", 30), ("_14day_avg", 14), ("_7day_avg", 7))
RAW_LOOKBACK_DAYS = 7  # the evaluator's raw-metric window (`_resolve_metric_value`)


def reading_points(ev: Any, metric_key: str, data_cache: dict, end_date: str) -> Optional[dict]:
    """The graded reading's points + provenance, from ONLY the cache slot `_resolve_metric_value` filled — never a
    second query; None when the slot is absent (a caller that did not resolve through the cache) or empty.

    ``ev`` is the loaded evaluator module (`dispute_docket._evaluator_module()`)."""
    from ingestion.source_registry import source_label

    base, aggregate, days = metric_key, "latest", RAW_LOOKBACK_DAYS
    for suffix, n in _AGGREGATES:
        if metric_key.endswith(suffix):
            base, aggregate, days = metric_key[: -len(suffix)], "mean", n
            break
    source = ev.METRIC_SOURCES.get(base)
    key = ev.source_cache_key(source, end_date, days) if source else None
    if key is None or key not in data_cache:
        return None
    series = ev._extract_metric_series(data_cache[key], base)
    points = series[-days:] if aggregate == "mean" else series[-1:]
    if not points:
        return None
    return {
        "source": source,
        "source_label": source_label(source) or source,
        "metric": base,
        "aggregate": aggregate,
        "days": days,
        "start": points[0][0],
        "end": points[-1][0],
        "n": len(points),
        "_values": [v for _d, v in points],
    }


def metric_reading_provenance(ev: Any, metric_key: str, data_cache: dict, end_date: str) -> Optional[dict]:
    """`reading_points` without the values — the shape a resolved docket stores as ``verdict.actual_reading``."""
    r = reading_points(ev, metric_key, data_cache, end_date)
    return {k: v for k, v in r.items() if k != "_values"} if r else None
