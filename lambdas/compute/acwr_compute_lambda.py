"""
ACWR Compute Lambda — v2.0.0
BS-09: Acute:Chronic Workload Ratio from Whoop strain data.

Schedule: daily at 9:55 AM PT (cron(55 16 * * ? *) UTC) — runs after
  ingestion (7–9 AM) and before Daily Brief (11 AM), slotted between
  adaptive-mode-compute (9:50 AM) and freshness-checker (10:45 AM).

Computes (#543 — EWMA-ACWR, replacing v1's flat rolling means):
  Acute load   = EWMA of Whoop day strain, 7-day time-constant
  Chronic load = EWMA of Whoop day strain, 28-day time-constant
  ACWR         = acute / chronic

  Why EWMA (Williams et al. 2017): a flat rolling mean weights every day in its window
  equally and then drops days off a cliff at the window edge, so a single big/rest day
  step-changes the ratio when it enters or leaves. An exponentially-weighted average
  decays smoothly — recent load counts most, older load fades — which tracks physiological
  adaptation/decay more faithfully and removes the rolling window's edge artifacts. The
  EWMA math is the sanctioned `stats_core.ewma_series` (the same helper the MCP training
  tools use), warm-started at the first-week mean so a short lookback doesn't anchor the
  chronic average at zero.

Zone thresholds are the Gabbett (2016) zones (see _classify_acwr): a POPULATION-derived
constant kept deliberately (ADR-105 rule 4 explicitly sanctions population constants for
things like ACWR zones and clinical ranges — provided they are LABELLED as such where
used, which acwr_method / the interpretation strings now do). The estimator changed; the
zone semantics did not.

Ratio-coupling caveat (surfaced in the record + MCP tool + methods page): ACWR is a ratio
whose numerator (acute) is mathematically a component of its denominator (chronic), so the
two are coupled by construction (Lolli et al. 2019) — the ratio can move for reasons that
aren't a real change in the underlying spurious-correlation-inflating relationship. Read
ACWR as a directional recovery signal, not a precise injury predictor.

Writes to DynamoDB SOURCE#computed_metrics | DATE#<yesterday> via UpdateItem
(merges with day_grade / readiness fields already written by daily-metrics-compute):
  acwr                  float   (acute / chronic ratio)
  acute_load_7d         float   (EWMA-7 strain — field name kept for schema stability)
  chronic_load_28d      float   (EWMA-28 strain — field name kept for schema stability)
  acwr_zone             str     ("safe" | "caution" | "danger" | "detraining")
  acwr_alert            bool    (True if >1.3 or <0.8)
  acwr_alert_reason     str     (human-readable)
  acwr_days_acute       int     (days with actual Whoop data in trailing 7-day window)
  acwr_days_chronic     int     (days with actual Whoop data in trailing 28-day window)
  acwr_method           str     ("ewma" — the estimator, so consumers can label it)
  acwr_coupling_caveat  str     (the ratio-coupling note above)
  acwr_computed_at      str     (ISO timestamp)

The Daily Brief reads acwr / acwr_zone / acwr_alert from computed_metrics
and surfaces it in the Training Report section (no recomputation needed).
The MCP get_acwr_status tool also reads this record for on-demand queries.

v1.0.0 — 2026-03-16 (BS-09)
v2.0.0 — 2026-07-05 (#543): rolling means → EWMA-ACWR; ratio-coupling caveat surfaced.
"""

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
import stats_core  # #543: the sanctioned EWMA (stats_core.ewma_series), ADR-105

try:
    from platform_logger import get_logger

    logger = get_logger("acwr-compute")
except ImportError:
    logger = logging.getLogger("acwr-compute")
    logger.setLevel(logging.INFO)

_REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

# EWMA time-constants (days). Same window lengths as the v1 rolling means, so the zone
# semantics are re-derived over the smoother estimator rather than re-tuned (#543).
ACUTE_DECAY_DAYS = 7
CHRONIC_DECAY_DAYS = 28
# Lookback for the daily strain series. 84d (12 weeks) gives the 28-day chronic EWMA a
# long enough burn-in that the warm-start seed's residual weight is negligible.
LOOKBACK_DAYS = 84

# ADR-105 rule 4: the ratio-coupling critique, carried on the record so every surface that
# shows ACWR (daily brief, MCP tool, methods page) can display it.
COUPLING_CAVEAT = (
    "ACWR is a coupled ratio: the acute load (numerator) is mathematically a component of "
    "the chronic load (denominator), so the two move together by construction (Lolli et al. "
    "2019). Treat ACWR as a directional recovery signal, not a precise injury predictor."
)

dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table = dynamodb.Table(TABLE_NAME)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────


def _d2f(obj):
    """Recursively convert DynamoDB Decimal to float."""
    if isinstance(obj, list):
        return [_d2f(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def _fetch_range(source: str, start: str, end: str) -> list:
    """Query DDB for a date range of a source partition."""
    # ADR-058: physiological continuity — chronic-load math needs the full
    # trailing 28d regardless of experiment phase; filtering pilot workouts
    # causes false ACWR spikes for ~3 weeks after any restart (owner decision
    # 2026-06-06). include_pilot=True is a deliberate no-op annotation.
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
        logger.warning("_fetch_range(%s, %s to %s) failed: %s", source, start, end, exc)
    return records


def _rolling_avg(items: list, field: str, n_days: int, end_date: str):
    """
    Compute a rolling average of `field` over the last `n_days` calendar days
    ending on `end_date` (inclusive). Missing days contribute 0.0 (rest day).
    Returns (avg, n_with_data). Returns (None, 0) only if ALL days are missing.
    """
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    by_date = {item["date"]: item for item in items if item.get("date")}
    vals = []
    n_data = 0
    for i in range(n_days):
        d = (end_dt - timedelta(days=i)).strftime("%Y-%m-%d")
        rec = by_date.get(d)
        v = None
        if rec:
            raw = rec.get(field)
            try:
                v = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                v = None
        if v is not None:
            vals.append(v)
            n_data += 1
        else:
            vals.append(0.0)  # rest day = 0 strain
    if n_data == 0:
        return None, 0
    return round(sum(vals) / len(vals), 3), n_data


def _build_daily_strain(items, start_date, end_date):
    """Continuous chronological [(date, strain)] from start_date..end_date inclusive.

    Missing days = 0.0 strain (rest day) — the same convention v1's rolling mean used, so
    EWMA and the old rolling mean treat rest identically (only the weighting differs).
    Returns (series, n_data) where n_data is the count of days with actual Whoop strain.
    """
    by_date = {}
    for item in items:
        d = item.get("date")
        if not d:
            continue
        raw = item.get("strain")
        try:
            v = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            v = None
        if v is not None:
            by_date[d] = v

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    series = []
    n_data = 0
    d = start_dt
    while d <= end_dt:
        ds = d.strftime("%Y-%m-%d")
        if ds in by_date:
            series.append((ds, by_date[ds]))
            n_data += 1
        else:
            series.append((ds, 0.0))
        d += timedelta(days=1)
    return series, n_data


def _ewma_acwr(series):
    """EWMA-ACWR from a chronological (date, strain) series.

    Returns (acwr, acute_ewma, chronic_ewma). Warm-starts both EWMAs at the mean of the
    first week of the series so a short lookback doesn't anchor the chronic average at 0
    (which would spuriously inflate ACWR early). Returns (None, None, None) on empty input;
    acwr is None when the chronic EWMA is not positive.
    """
    if not series:
        return None, None, None
    vals = [v for _, v in series]
    warm = vals[: min(7, len(vals))]
    seed = sum(warm) / len(warm) if warm else 0.0
    acute = stats_core.ewma_series(series, ACUTE_DECAY_DAYS, seed=seed)[-1][1]
    chronic = stats_core.ewma_series(series, CHRONIC_DECAY_DAYS, seed=seed)[-1][1]
    acwr = round(acute / chronic, 3) if chronic and chronic > 0 else None
    return acwr, acute, chronic


def _classify_acwr(acwr):
    """
    Returns (zone, alert, reason).
    Thresholds: Gabbett et al. (2016), Hulin et al. (2014).
    """
    if acwr is None:
        return "unknown", False, "Insufficient Whoop strain data for ACWR computation"
    if acwr > 1.5:
        return (
            "danger",
            True,
            f"ACWR {acwr:.2f} is above 1.5 — very high injury risk. "
            "Reduce all non-essential training load immediately. Prioritise recovery this week.",
        )
    if acwr > 1.3:
        return (
            "caution",
            True,
            f"ACWR {acwr:.2f} is above 1.3 — elevated injury risk. " "Reduce training volume this week and increase recovery focus.",
        )
    if acwr >= 0.8:
        return (
            "safe",
            False,
            f"ACWR {acwr:.2f} is within the safe zone (0.8–1.3). " "Current training load is appropriate for continued adaptation.",
        )
    return (
        "detraining",
        True,
        f"ACWR {acwr:.2f} is below 0.8 — insufficient training stimulus. "
        "Chronic load exceeds acute load; fitness may decline without increased training.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# WRITE TO COMPUTED_METRICS
# ─────────────────────────────────────────────────────────────────────────────


def _write_acwr(date_str, acwr, acute_7d, chronic_28d, zone, alert, alert_reason, n_days_acute, n_days_chronic):
    """
    UpdateItem on computed_metrics — merges ACWR fields with existing record
    (day grade, readiness, streaks) written earlier by daily-metrics-compute.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    set_parts = []
    expr_vals = {
        ":zone": zone,
        ":alert": alert,
        ":reason": alert_reason,
        ":cat": now_iso,
        ":da": Decimal(str(n_days_acute)),
        ":dc": Decimal(str(n_days_chronic)),
        ":method": "ewma",
        ":caveat": COUPLING_CAVEAT,
    }

    set_parts += [
        "acwr_zone            = :zone",
        "acwr_alert           = :alert",
        "acwr_alert_reason    = :reason",
        "acwr_computed_at     = :cat",
        "acwr_days_acute      = :da",
        "acwr_days_chronic    = :dc",
        "acwr_method          = :method",
        "acwr_coupling_caveat = :caveat",
    ]

    if acwr is not None:
        set_parts.append("acwr = :acwr")
        expr_vals[":acwr"] = Decimal(str(acwr))
    if acute_7d is not None:
        set_parts.append("acute_load_7d = :a7")
        expr_vals[":a7"] = Decimal(str(round(acute_7d, 3)))
    if chronic_28d is not None:
        set_parts.append("chronic_load_28d = :c28")
        expr_vals[":c28"] = Decimal(str(round(chronic_28d, 3)))

    try:
        table.update_item(
            Key={
                "pk": USER_PREFIX + "computed_metrics",
                "sk": "DATE#" + date_str,
            },
            UpdateExpression="SET " + ", ".join(set_parts),
            ExpressionAttributeValues=expr_vals,
        )
        logger.info(
            "ACWR written for %s — acwr=%s zone=%s alert=%s acute=%.2f chronic=%.2f",
            date_str,
            f"{acwr:.3f}" if acwr is not None else "null",
            zone,
            alert,
            acute_7d if acute_7d is not None else 0,
            chronic_28d if chronic_28d is not None else 0,
        )
    except Exception as exc:
        logger.error("Failed to write ACWR for %s: %s", date_str, exc)
        raise


# ─────────────────────────────────────────────────────────────────────────────
# HANDLER
# ─────────────────────────────────────────────────────────────────────────────


def lambda_handler(event, context):
    try:
        return _lambda_handler_impl(event, context)
    except Exception as e:
        logger.error("Handler failed: %s", e, exc_info=True)
        raise


def _lambda_handler_impl(event, context):
    t0 = time.time()
    logger.info("ACWR Compute v1.0.0 starting")

    # Target date — default yesterday; override via event for backfill/testing
    if event.get("date"):
        target_date = event["date"]
        logger.info("Override date: %s", target_date)
    else:
        today = datetime.now(timezone.utc).date()
        target_date = (today - timedelta(days=1)).isoformat()

    # Fetch Whoop strain records — 84 days back gives the 28d chronic EWMA burn-in room
    fetch_start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    whoop_items = _fetch_range("whoop", fetch_start, target_date)
    logger.info(
        "Fetched %d Whoop records (%s to %s)",
        len(whoop_items),
        fetch_start,
        target_date,
    )

    # #543: EWMA-ACWR over the continuous daily strain series (rest days = 0).
    series, _ = _build_daily_strain(whoop_items, fetch_start, target_date)
    acwr, acute_7d, chronic_28d = _ewma_acwr(series)
    if acute_7d is not None:
        acute_7d = round(acute_7d, 3)
    if chronic_28d is not None:
        chronic_28d = round(chronic_28d, 3)

    # Data-coverage counts over the trailing 7d/28d windows (unchanged reporting).
    _, n_acute = _rolling_avg(whoop_items, "strain", 7, target_date)
    _, n_chronic = _rolling_avg(whoop_items, "strain", 28, target_date)

    zone, alert, reason = _classify_acwr(acwr)

    logger.info(
        "ACWR=%s zone=%s alert=%s | acute_7d=%s chronic_28d=%s " "(data coverage: %d/7d, %d/28d)",
        acwr,
        zone,
        alert,
        acute_7d,
        chronic_28d,
        n_acute,
        n_chronic,
    )

    _write_acwr(
        date_str=target_date,
        acwr=acwr,
        acute_7d=acute_7d,
        chronic_28d=chronic_28d,
        zone=zone,
        alert=alert,
        alert_reason=reason,
        n_days_acute=n_acute,
        n_days_chronic=n_chronic,
    )

    elapsed = round(time.time() - t0, 1)
    logger.info("Done in %ss", elapsed)

    return {
        "statusCode": 200,
        "body": f"ACWR computed for {target_date}: {acwr} ({zone})",
        "date": target_date,
        "acwr": acwr,
        "zone": zone,
        "alert": alert,
        "alert_reason": reason,
        "acute_load_7d": acute_7d,
        "chronic_load_28d": chronic_28d,
        "n_acute_data": n_acute,
        "n_chronic_data": n_chronic,
        "elapsed_seconds": elapsed,
    }
