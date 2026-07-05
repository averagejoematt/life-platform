"""
Personal Baselines Compute Lambda — v1.0.0 (#543, ADR-105 rule 4)

Schedule: monthly — cron(0 8 1 * ? *) UTC = 1st of every month, 08:00 UTC (fixed UTC,
  no DST drift). A slow-moving personal distribution doesn't need daily recompute; monthly
  keeps the bands stable within a month and cheap (zero AI cost — pure Python).

What it does: reads ~365 days of Matthew's own `computed_metrics` history and turns his
OWN distribution into percentile bands, then writes ONE snapshot record that the live
consumers (daily-metrics readiness, daily-insight momentum) read INSTEAD of hand-set
constants. When a metric has fewer than personal_baselines.MIN_N observations the band is
None and consumers fall back to today's exact constants (the floor-guard) — so behavior
is unchanged until enough data exists.

Metrics banded (the #543 inventory that is safely personalizable):
  readiness_hrv_ratio — the 7d/30d HRV ratio distribution → {p10, p50, p90} anchors that
      replace the hand-set 0.75/1.0/1.25 map in compute_readiness.
  grade_trend_pct     — the week-over-week day-grade swing distribution → {p25, p75} band
      that replaces the hand-set +-5% "improving/declining" cutoffs in compute_momentum.

NOT banded (ADR-105 rule 4 carve-out — population-derived constants kept + labelled):
  ACWR Gabbett zones, clinical lab ranges.

Writes to DynamoDB SOURCE#personal_baselines | SNAPSHOT#LATEST:
  bands              map    {metric: {anchors..., n} or absent when thin}
  computed_at        str    ISO timestamp
  lookback_days      int
  method_version     str

v1.0.0 — 2026-07-05 (#543)
"""

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
import personal_baselines

try:
    from platform_logger import get_logger

    logger = get_logger("personal-baselines-compute")
except ImportError:
    logger = logging.getLogger("personal-baselines-compute")
    logger.setLevel(logging.INFO)

_REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

LOOKBACK_DAYS = 365
METHOD_VERSION = "1.0.0"

dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table = dynamodb.Table(TABLE_NAME)


def _d2f(obj):
    if isinstance(obj, list):
        return [_d2f(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def _fetch_computed_metrics(start, end):
    """Query computed_metrics DATE# records in [start, end]. include_pilot=True: the
    personal distribution is physiological, not experiment-scoped (mirrors ACWR, ADR-058).
    """
    from phase_filter import with_phase_filter

    records = []
    kwargs = with_phase_filter(
        {
            "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
            "ExpressionAttributeValues": {
                ":pk": USER_PREFIX + "computed_metrics",
                ":s": "DATE#" + start,
                ":e": "DATE#" + end,
            },
        },
        include_pilot=True,
    )
    try:
        while True:
            resp = table.query(**kwargs)
            records.extend(_d2f(item) for item in resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    except Exception as exc:
        logger.warning("_fetch_computed_metrics(%s..%s) failed: %s", start, end, exc)
    return records


def _sf(rec, field):
    v = rec.get(field)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _hrv_ratios(records):
    """Per-day 7d/30d HRV ratio across history."""
    out = []
    for rec in records:
        h7 = _sf(rec, "hrv_7d")
        h30 = _sf(rec, "hrv_30d")
        if h7 is not None and h30 and h30 > 0:
            out.append(h7 / h30)
    return out


def _grade_trends(records):
    """Distribution of the week-over-week grade swing % — the exact statistic
    compute_momentum computes daily, sampled across all of history.

    For each day t with a full 14-day trailing window of grades, trend_pct =
    (mean(this 7d) - mean(prev 7d)) / max(mean(prev 7d), 1) * 100.
    """
    by_date = {}
    for rec in records:
        d = rec.get("date") or rec.get("sk", "").replace("DATE#", "")
        g = _sf(rec, "day_grade_score")
        if d and g is not None:
            by_date[d] = g
    if not by_date:
        return []

    dates = sorted(by_date)
    trends = []
    for anchor in dates:
        anchor_dt = datetime.strptime(anchor, "%Y-%m-%d")
        this_week, prev_week = [], []
        for i in range(0, 14):
            d = (anchor_dt - timedelta(days=i)).strftime("%Y-%m-%d")
            g = by_date.get(d)
            if g is None:
                continue
            (this_week if i < 7 else prev_week).append(g)
        if not this_week or not prev_week:
            continue
        this_avg = sum(this_week) / len(this_week)
        prev_avg = sum(prev_week) / len(prev_week)
        trends.append(round((this_avg - prev_avg) / max(prev_avg, 1) * 100, 3))
    return trends


def _write_snapshot(bands, lookback_days):
    now_iso = datetime.now(timezone.utc).isoformat()
    # Only store non-None bands; a thin metric is simply absent → consumer falls back.
    stored = {}
    for metric, band in bands.items():
        if band is None:
            continue
        stored[metric] = {k: Decimal(str(v)) for k, v in band.items()}
    table.put_item(
        Item={
            "pk": USER_PREFIX + personal_baselines.BASELINES_SOURCE,
            "sk": personal_baselines.BASELINES_SK,
            "bands": stored,
            "computed_at": now_iso,
            "lookback_days": Decimal(str(lookback_days)),
            "method_version": METHOD_VERSION,
        }
    )
    logger.info("Wrote personal_baselines snapshot: %s", {m: (b and b.get("n")) for m, b in bands.items()})


def lambda_handler(event, context):
    try:
        return _impl(event, context)
    except Exception as e:
        logger.error("Handler failed: %s", e, exc_info=True)
        raise


def _impl(event, context):
    t0 = time.time()
    logger.info("Personal Baselines Compute v%s starting", METHOD_VERSION)

    end = (event or {}).get("date") or datetime.now(timezone.utc).date().isoformat()
    start = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    records = _fetch_computed_metrics(start, end)
    logger.info("Fetched %d computed_metrics records (%s..%s)", len(records), start, end)

    hrv_ratios = _hrv_ratios(records)
    grade_trends = _grade_trends(records)
    logger.info("Series: hrv_ratios n=%d, grade_trends n=%d (MIN_N=%d)", len(hrv_ratios), len(grade_trends), personal_baselines.MIN_N)

    bands = personal_baselines.compute_bands(hrv_ratios, grade_trends)
    _write_snapshot(bands, LOOKBACK_DAYS)

    elapsed = round(time.time() - t0, 1)
    logger.info("Done in %ss", elapsed)
    return {
        "statusCode": 200,
        "body": f"personal_baselines computed ({start}..{end})",
        "bands": {m: (b if b else "thin->fallback") for m, b in bands.items()},
        "n_hrv_ratios": len(hrv_ratios),
        "n_grade_trends": len(grade_trends),
        "elapsed_seconds": elapsed,
    }
