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

Character-engine target bands (#1412, v1.1.0 — personal_baselines.CHARACTER_TARGET_SPECS):
  sleep_duration_hours / deep_sleep_fraction / rem_sleep_fraction — from Matthew's whoop
      sleep history (mirrors character_engine's field fallbacks: hours, pct, or seconds).
  daily_steps — from apple_health steps history.
  Each band is {p25, p50, p75, n, window_days}; the character consumers take p75 as the
  target ("a good day by his own distribution"), guardrail-clamped + provenance-labeled
  by personal_baselines.apply_character_targets. Below MIN_N the authored config value
  survives, labeled "population prior, n<30".

NOT banded (ADR-105 rule 4 carve-out — population-derived constants kept + labelled):
  ACWR Gabbett zones, clinical lab ranges, protocol commitments (zone2 minutes,
  training/reading day targets), goal-derived macros — see personal_baselines docstring.

Writes to DynamoDB SOURCE#personal_baselines | SNAPSHOT#LATEST:
  bands              map    {metric: {anchors..., n[, window_days]} or absent when thin}
  computed_at        str    ISO timestamp
  lookback_days      int
  method_version     str

v1.0.0 — 2026-07-05 (#543)
v1.1.0 — 2026-07-19 (#1412: character-engine target bands)
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
METHOD_VERSION = "1.1.0"

dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table = dynamodb.Table(TABLE_NAME)


from digest_utils import d2f as _d2f  # shared bundled helpers (#970)


def _fetch_source(source, start, end):
    """Query one source's DATE# records in [start, end]. include_pilot=True: the
    personal distribution is physiological, not experiment-scoped (mirrors ACWR, ADR-058).
    """
    from phase_filter import with_phase_filter

    records = []
    kwargs = with_phase_filter(
        {
            "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
            "ExpressionAttributeValues": {
                ":pk": USER_PREFIX + source,
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
        logger.warning("_fetch_source(%s, %s..%s) failed: %s", source, start, end, exc)
    return records


def _fetch_computed_metrics(start, end):
    return _fetch_source("computed_metrics", start, end)


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


def _sleep_series(records):
    """Extract (durations_hours, deep_fractions, rem_fractions) from whoop history.

    Mirrors character_engine.compute_sleep_raw's field fallbacks exactly (#1412):
    hours fields first, then pct fields (normalized when given as 0-100), then
    seconds ratios — so the distribution the target derives from is the same
    quantity the component scores daily. Implausible values are dropped, never
    coerced (ADR-104: no fabricated observations).
    """
    durations, deep_fracs, rem_fracs = [], [], []
    for rec in records or []:
        dur = _sf(rec, "sleep_duration_hours") or _sf(rec, "total_sleep_seconds")
        if dur is not None and dur > 24:
            dur = dur / 3600.0
        if dur is None or not (0 < dur <= 24):
            continue
        durations.append(round(dur, 4))

        deep = _sf(rec, "deep_sleep_pct")
        if deep is None:
            deep_s, total_s = _sf(rec, "deep_sleep_seconds"), _sf(rec, "total_sleep_seconds")
            if deep_s and total_s and total_s > 0:
                deep = deep_s / total_s
        if deep is None:
            deep_h = _sf(rec, "slow_wave_sleep_hours")
            if deep_h and dur > 0:
                deep = deep_h / dur
        if deep is not None and deep > 1:
            deep = deep / 100.0
        if deep is not None and 0 < deep < 1:
            deep_fracs.append(deep)

        rem = _sf(rec, "rem_sleep_pct")
        if rem is None:
            rem_s, total_s = _sf(rec, "rem_sleep_seconds"), _sf(rec, "total_sleep_seconds")
            if rem_s and total_s and total_s > 0:
                rem = rem_s / total_s
        if rem is None:
            rem_h = _sf(rec, "rem_sleep_hours")
            if rem_h and dur > 0:
                rem = rem_h / dur
        if rem is not None and rem > 1:
            rem = rem / 100.0
        if rem is not None and 0 < rem < 1:
            rem_fracs.append(rem)
    return durations, deep_fracs, rem_fracs


def _steps_series(records):
    """Daily step counts from apple_health history — zero/absent days dropped (a
    wearable gap is not a 0-step day; ADR-104 measured-class semantics)."""
    out = []
    for rec in records or []:
        steps = _sf(rec, "steps")
        if steps and steps > 0:
            out.append(steps)
    return out


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

    # ── #1412: character-engine target bands from the same personal history ──
    whoop_records = _fetch_source("whoop", start, end)
    apple_records = _fetch_source("apple_health", start, end)
    durations, deep_fracs, rem_fracs = _sleep_series(whoop_records)
    steps = _steps_series(apple_records)
    logger.info(
        "Character series: sleep n=%d, deep n=%d, rem n=%d, steps n=%d (MIN_N=%d)",
        len(durations),
        len(deep_fracs),
        len(rem_fracs),
        len(steps),
        personal_baselines.MIN_N,
    )
    bands.update(
        personal_baselines.compute_character_target_bands(
            {
                "sleep_duration_hours": durations,
                "deep_sleep_fraction": deep_fracs,
                "rem_sleep_fraction": rem_fracs,
                "daily_steps": steps,
            },
            window_days=LOOKBACK_DAYS,
        )
    )

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
