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


#: #6156 (owner ruling 2026-11-22 §5): the frozen head-to-head rule of the rules-based platform forecast partition —
#: ``common.public_forecast_policy.SCORING_RULE``, repeated here as a literal so this grader imports nothing from the
#: producer side (tests/test_public_forecast_backtest_6156.py pins the two equal). A spec without it is graded exactly
#: as before.
HEAD_TO_HEAD = "closer_than_nothing_changes"


def forecast_closer(actual, forecast, guess):
    """True when ``forecast`` is STRICTLY closer to ``actual`` than ``guess`` is (a tie counts for the guess)."""
    return abs(float(actual) - float(forecast)) < abs(float(actual) - float(guess))


def head_to_head_result(metric_key, actual, on_date, forecast, guess):
    """The evaluator's result shape for a head-to-head spec: confirmed iff the forecast beat the frozen guess."""
    hit = forecast_closer(actual, forecast, guess)
    e_f, e_g = abs(actual - forecast), abs(actual - guess)
    return {
        "status": "confirmed" if hit else "refuted",
        "reason": (
            f"{metric_key}={actual:.2f} on {on_date}: the forecast {forecast:g} was {e_f:.2f} away, the guess that nothing "
            f"changes {guess:g} was {e_g:.2f} away → {'the forecast was closer' if hit else 'the guess was as close or closer'}"
        ),
        "actual_value": round(actual, 4),
        "beats_null": hit,
    }


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


def read_anchor(target_date, today_str):
    """The end day of the point grader's source read: the call's TARGET day, capped at the run day.

    Owner 2026-11-09 (manifest v3 §2.15): the read used to end on the run day with a 60-day
    look-back, so re-grading an old call read a window that no longer reached its target day —
    a September call re-run in November found "no reading" and expired although its reading is in
    the table (Whoop recovery 67 on 2026-09-08). Anchored on the target, the window always covers
    the readings the verdict is decided on, whenever the grade runs. For a call graded when it
    falls due the target is within days of the run day, so the readings on or before the target —
    the only ones the verdict reads — are the same either way (``tests/test_point_lookback_anchor.py``)."""
    target, today = str(target_date)[:10], str(today_str)[:10]
    return min(target, today) if today else target


def metric_value_on(metric_key, data_cache, today_str, target_date, *, get_source_data, extract_metric_series, after_day=None):
    """(value, date) of `metric_key` ON `target_date` — the reading that day, else the
    latest within POINT_GRACE_DAYS before it; an aggregate key (`_7day_avg`) is the
    mean of the last N readings on or before the target. (None, None) when nothing
    qualifies. Reads the shared source cache ANCHORED ON THE CALL'S OWN TARGET DAY (never
    on the run day — ``read_anchor``), then filters by date itself.

    `after_day` (#4618) is the day the call was filed: a reading on or before it can
    never settle the call — the coach had already seen it. Without this bound the grace
    look-back turned "about 61% tomorrow" with no reading tomorrow into a verdict on the
    filing day's own reading. #5533 (d): the bound applies to an AGGREGATE key too — the
    `_7day_avg` branch used to return before it, so a seven-day mean on the target day
    was built mostly from readings the coach had on the page when the call was filed."""
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
    records = get_source_data(source, data_cache, read_anchor(target_date, today_str), lookback_days=POINT_LOOKBACK_DAYS)
    filed = str(after_day)[:10] if after_day else None
    series = [(d, v) for d, v in extract_metric_series(records, base) if d <= target_date and not (filed and d <= filed)]
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
    if d < floor:  # the after_day bound was applied to the whole series above
        return None, None
    return v, d


def evaluate_point(pred, eval_spec, data_cache, today_str, *, get_source_data, extract_metric_series):
    """The point verdict — see the module docstring. Returns the evaluator's result
    shape ({status, reason, actual_value, beats_null}) or None for a malformed spec."""
    metric_key = eval_spec.get("metric")
    target = eval_spec.get("threshold")
    tolerance = eval_spec.get("tolerance")
    head_to_head = eval_spec.get("scoring") == HEAD_TO_HEAD  # #6156: the platform-forecast partition's frozen rule only
    if not metric_key or target is None or (tolerance is None and not head_to_head):
        return None
    if head_to_head and eval_spec.get("baseline_value") is None:
        return None
    target_date = eval_spec.get("target_date")
    if not target_date:
        try:
            created = datetime.strptime(pred.get("created_date"), "%Y-%m-%d")
            target_date = (created + timedelta(days=int(eval_spec.get("evaluation_window_days") or 14))).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            return None
    actual, on_date = metric_value_on(
        metric_key,
        data_cache,
        today_str,
        target_date,
        get_source_data=get_source_data,
        extract_metric_series=extract_metric_series,
        after_day=pred.get("created_date"),
    )
    if actual is None:
        return {
            "status": "inconclusive",
            "reason": f"No reading for '{metric_key}' on {target_date} (or within {POINT_GRACE_DAYS} days before it)",
            "actual_value": None,
            "beats_null": False,
        }
    if head_to_head:
        return head_to_head_result(metric_key, actual, on_date, float(target), float(eval_spec["baseline_value"]))
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
