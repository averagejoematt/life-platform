"""lambdas/coach/metric_trailing_series.py — a metric's trailing personal series and
the point-spec tolerance derived from it (#3551, ADR-105 rule 4).

The writer (coach_state_updater, at its module-size ceiling — #1665) calls
`point_tolerance` for a numeric LEVEL claim: 1 sample SD of the metric's readings
over the last `lookback_days`, with the rule string (n, SD) frozen into the spec.
A read error derives NO tolerance — liveness may fail open (a dead read must not
stall emission), a tolerance never does: an invented tolerance would grade a claim
nobody priced. The caller then emits the claim as an observation.
"""

import logging
from datetime import datetime, timedelta, timezone

from experiment.measurable_metrics import METRIC_SOURCES, base_metric
from experiment.phase_filter import with_phase_filter

from coach.prediction_emission import point_tolerance_from_series

logger = logging.getLogger(__name__)


def trailing_values(table, user_id, metric_key, lookback_days):
    """The metric's numeric readings over the last `lookback_days` days (cross-phase,
    oldest first). Empty on any read error — never a fabricated series."""
    base = base_metric(metric_key or "")
    source = METRIC_SOURCES.get(base)
    if not source:
        return []
    try:
        # utc-exempt(#2815): the same widened DATE#-keyed bound the liveness gate uses.
        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        kwargs = {
            "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
            "ExpressionAttributeValues": {
                ":pk": f"USER#{user_id}#SOURCE#{source}",
                ":s": "DATE#" + start,
                ":e": "DATE#" + end,
            },
        }
        rows = []
        while True:
            resp = table.query(**with_phase_filter(kwargs, include_pilot=True))
            for item in resp.get("Items", []):
                val = item.get(base)
                if val is None:
                    continue
                try:
                    rows.append((str(item.get("sk", "")), float(val)))
                except (TypeError, ValueError):
                    pass
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        rows.sort(key=lambda r: r[0])
        return [v for _, v in rows]
    except Exception as e:
        logger.warning("Trailing-series read failed for %s (%s) — no tolerance derived: %s", metric_key, source, e)
        return []


def point_tolerance(table, user_id, metric_key, tolerance_cache, lookback_days):
    """(tolerance, rule, n) for a point spec from the subject's OWN trailing variance,
    or None when it cannot be derived. Cached per metric per run."""
    if metric_key in tolerance_cache:
        return tolerance_cache[metric_key]
    tol = point_tolerance_from_series(trailing_values(table, user_id, metric_key, lookback_days), lookback_days=lookback_days)
    tolerance_cache[metric_key] = tol
    return tol
