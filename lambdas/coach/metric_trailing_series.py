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

from common.metric_truth import resolved_metric, resolved_rows, sources_for  # #4630: resolved pseudo-sources
from common.strava_read_seam import strava_read_seam  # #4419: multi-device duplicates removed at the read
from experiment.measurable_metrics import METRIC_SOURCES, base_metric
from experiment.phase_filter import with_phase_filter

from coach.prediction_emission import point_tolerance_from_series

logger = logging.getLogger(__name__)


def source_items(table, user_id, source, start, end):
    """Every DATE# item of `source` in [start, end] (cross-phase, paginated) — raises on a read error.

    #4630: a resolved pseudo-source (`resolved:<metric>`, which measurable_metrics maps steps
    to) reads each source in the registry's METRIC_TRUTH facet and returns the resolved day
    rows, so a caller that reads `item[<metric>]` reads the one truth."""
    metric = resolved_metric(source)
    if metric:
        return resolved_rows(metric, {s: source_items(table, user_id, s, start, end) for s in sources_for(metric)})
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {
            ":pk": f"USER#{user_id}#SOURCE#{source}",
            ":s": "DATE#" + start,
            ":e": "DATE#" + end + "~",
        },
    }
    items = []
    while True:
        resp = table.query(**with_phase_filter(kwargs, include_pilot=True))
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return strava_read_seam(source, items)  # #4419: a no-op for every source but strava


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
        rows = []
        for item in source_items(table, user_id, source, start, end):
            val = item.get(base)
            if val is None:
                continue
            try:
                rows.append((str(item.get("sk", "")), float(val)))
            except (TypeError, ValueError):
                pass
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
