"""lambdas/coach/prediction_point_grader.py — the `point` evaluation path (#3551).

A numeric LEVEL claim — "recovery will be approximately 53.5%" — is confirmed iff the
metric's reading on the target date lands within ±tolerance of the stated level,
refuted otherwise; only a missing reading is inconclusive. The tolerance and the
rule that produced it were frozen into the spec at emission
(prediction_emission.build_point_eval_spec: 1 SD of the metric's trailing 30-day
personal series, ADR-105 rule 4), so the served grade is reproducible from the
record: |actual − target| <= tolerance.

Lives beside coach_prediction_evaluator (which sits at its module-size baseline,
#1665) in the #1654 helper shape: the evaluator dispatches here; this module reads
the evaluator's shared source cache through the two helpers it is handed, so the
data path and the cache key stay the evaluator's own.
"""

from datetime import datetime, timedelta

from experiment.measurable_metrics import METRIC_SOURCES

# The reading ON the target date, else the latest within this many days before it (a
# missed weigh-in is not a refutation); the source fetch reaches back far enough that
# a domain-clamped window cannot push the target off the range.
POINT_GRACE_DAYS = 2
POINT_LOOKBACK_DAYS = 60

_AGGREGATE_SUFFIXES = (("_30day_avg", 30), ("_14day_avg", 14), ("_7day_avg", 7))


def evaluate_condition(actual, condition, threshold):
    """Evaluate a machine spec's condition against a threshold — None (inconclusive)
    when either side is missing. Shared by the evaluator's machine path; lives here
    because a threshold comparison and a tolerance comparison are the same family."""
    if actual is None or threshold is None:
        return None
    cond_map = {
        "gt": actual > threshold,
        "gte": actual >= threshold,
        "lt": actual < threshold,
        "lte": actual <= threshold,
        "eq": abs(actual - threshold) < 0.01,
    }
    return cond_map.get(condition)


def metric_value_on(metric_key, data_cache, today_str, target_date, *, get_source_data, extract_metric_series):
    """(value, date) of `metric_key` ON `target_date` — the reading that day, else the
    latest within POINT_GRACE_DAYS before it; an aggregate key (`_7day_avg`) is the
    mean of the last N readings on or before the target. (None, None) when nothing
    qualifies. Reads the shared source cache anchored on today (its key is
    source+lookback, never the end date), then filters by date itself."""
    base = metric_key
    agg_days = None
    for suffix, days in _AGGREGATE_SUFFIXES:
        if metric_key.endswith(suffix):
            base = metric_key[: -len(suffix)]
            agg_days = days
            break
    source = METRIC_SOURCES.get(base)
    if not source or not target_date:
        return None, None
    records = get_source_data(source, data_cache, today_str, lookback_days=POINT_LOOKBACK_DAYS)
    series = [(d, v) for d, v in extract_metric_series(records, base) if d <= target_date]
    if not series:
        return None, None
    if agg_days:
        recent = [v for _, v in series[-agg_days:]]
        return sum(recent) / len(recent), target_date
    try:
        floor = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=POINT_GRACE_DAYS)).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None, None
    d, v = series[-1]
    if d < floor:
        return None, None
    return v, d


def evaluate_point(pred, eval_spec, data_cache, today_str, *, get_source_data, extract_metric_series):
    """The point verdict — see the module docstring. Returns the evaluator's result
    shape ({status, reason, actual_value, beats_null}) or None for a malformed spec."""
    metric_key = eval_spec.get("metric")
    target = eval_spec.get("threshold")
    tolerance = eval_spec.get("tolerance")
    if not metric_key or target is None or tolerance is None:
        return None
    target_date = eval_spec.get("target_date")
    if not target_date:
        try:
            created = datetime.strptime(pred.get("created_date"), "%Y-%m-%d")
            target_date = (created + timedelta(days=int(eval_spec.get("evaluation_window_days") or 14))).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            return None
    actual, on_date = metric_value_on(
        metric_key, data_cache, today_str, target_date, get_source_data=get_source_data, extract_metric_series=extract_metric_series
    )
    if actual is None:
        return {
            "status": "inconclusive",
            "reason": f"No reading for '{metric_key}' on {target_date} (or within {POINT_GRACE_DAYS} days before it)",
            "actual_value": None,
            "beats_null": False,
        }
    target = float(target)
    tolerance = float(tolerance)
    delta = actual - target
    hit = abs(delta) <= tolerance
    rule = eval_spec.get("tolerance_rule") or f"±{tolerance}"
    return {
        "status": "confirmed" if hit else "refuted",
        "reason": (
            f"{metric_key}={actual:.2f} on {on_date} vs predicted {target:g} ±{tolerance:g} ({rule}); "
            f"|Δ|={abs(delta):.2f} → {'within' if hit else 'outside'} tolerance"
        ),
        "actual_value": round(actual, 4),
        "beats_null": hit,
    }
