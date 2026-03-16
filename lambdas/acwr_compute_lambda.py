"""
ACWR Compute Lambda — v1.0.0
BS-09: Acute:Chronic Workload Ratio from Whoop strain data.

Schedule: daily at 9:55 AM PT (cron(55 16 * * ? *) UTC) — runs after
  ingestion (7–9 AM) and before Daily Brief (11 AM), slotted between
  adaptive-mode-compute (9:50 AM) and freshness-checker (10:45 AM).

Computes:
  Acute load   = 7-day rolling average of Whoop day strain
  Chronic load = 28-day rolling average of Whoop day strain
  ACWR         = acute / chronic

Writes to DynamoDB SOURCE#computed_metrics | DATE#<yesterday> via UpdateItem
(merges with day_grade / readiness fields already written by daily-metrics-compute):
  acwr                float   (acute / chronic ratio)
  acute_load_7d       float   (7-day avg strain)
  chronic_load_28d    float   (28-day avg strain)
  acwr_zone           str     ("safe" | "caution" | "danger" | "detraining")
  acwr_alert          bool    (True if >1.3 or <0.8)
  acwr_alert_reason   str     (human-readable)
  acwr_days_acute     int     (days with actual Whoop data in 7-day window)
  acwr_days_chronic   int     (days with actual Whoop data in 28-day window)
  acwr_computed_at    str     (ISO timestamp)

Alert thresholds (Gabbett et al., 2016 — standard athletic conditioning):
  > 1.5   DANGER      — very high injury risk; stop non-essential training load
  > 1.3   CAUTION     — elevated injury risk; reduce volume this week
  0.8-1.3 SAFE        — optimal training stimulus range
  < 0.8   DETRAINING  — insufficient load to maintain fitness

The Daily Brief reads acwr / acwr_zone / acwr_alert from computed_metrics
and surfaces it in the Training Report section (no recomputation needed).
The MCP get_acwr_status tool also reads this record for on-demand queries.

v1.0.0 — 2026-03-16 (BS-09)
"""

import os
import time
import logging
import boto3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

try:
    from platform_logger import get_logger
    logger = get_logger("acwr-compute")
except ImportError:
    logger = logging.getLogger("acwr-compute")
    logger.setLevel(logging.INFO)

_REGION    = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID    = os.environ["USER_ID"]

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _d2f(obj):
    """Recursively convert DynamoDB Decimal to float."""
    if isinstance(obj, list):    return [_d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: _d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def _fetch_range(source: str, start: str, end: str) -> list:
    """Query DDB for a date range of a source partition."""
    records = []
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {
            ":pk": USER_PREFIX + source,
            ":s":  "DATE#" + start,
            ":e":  "DATE#" + end,
        },
    }
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
    end_dt  = datetime.strptime(end_date, "%Y-%m-%d")
    by_date = {item["date"]: item for item in items if item.get("date")}
    vals    = []
    n_data  = 0
    for i in range(n_days):
        d   = (end_dt - timedelta(days=i)).strftime("%Y-%m-%d")
        rec = by_date.get(d)
        v   = None
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
            f"ACWR {acwr:.2f} is above 1.3 — elevated injury risk. "
            "Reduce training volume this week and increase recovery focus.",
        )
    if acwr >= 0.8:
        return (
            "safe",
            False,
            f"ACWR {acwr:.2f} is within the safe zone (0.8–1.3). "
            "Current training load is appropriate for continued adaptation.",
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

def _write_acwr(date_str, acwr, acute_7d, chronic_28d,
                zone, alert, alert_reason, n_days_acute, n_days_chronic):
    """
    UpdateItem on computed_metrics — merges ACWR fields with existing record
    (day grade, readiness, streaks) written earlier by daily-metrics-compute.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    set_parts  = []
    expr_vals  = {
        ":zone":   zone,
        ":alert":  alert,
        ":reason": alert_reason,
        ":cat":    now_iso,
        ":da":     Decimal(str(n_days_acute)),
        ":dc":     Decimal(str(n_days_chronic)),
    }

    set_parts += [
        "acwr_zone         = :zone",
        "acwr_alert        = :alert",
        "acwr_alert_reason = :reason",
        "acwr_computed_at  = :cat",
        "acwr_days_acute   = :da",
        "acwr_days_chronic = :dc",
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
            zone, alert,
            acute_7d    if acute_7d    is not None else 0,
            chronic_28d if chronic_28d is not None else 0,
        )
    except Exception as exc:
        logger.error("Failed to write ACWR for %s: %s", date_str, exc)
        raise


# ─────────────────────────────────────────────────────────────────────────────
# HANDLER
# ─────────────────────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    t0 = time.time()
    logger.info("ACWR Compute v1.0.0 starting")

    # Target date — default yesterday; override via event for backfill/testing
    if event.get("date"):
        target_date = event["date"]
        logger.info("Override date: %s", target_date)
    else:
        today       = datetime.now(timezone.utc).date()
        target_date = (today - timedelta(days=1)).isoformat()

    # Fetch Whoop strain records — 30 days back gives us full 28d chronic window
    fetch_start = (
        datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=30)
    ).strftime("%Y-%m-%d")

    whoop_items = _fetch_range("whoop", fetch_start, target_date)
    logger.info(
        "Fetched %d Whoop records (%s to %s)",
        len(whoop_items), fetch_start, target_date,
    )

    # Compute rolling averages
    acute_7d,    n_acute    = _rolling_avg(whoop_items, "strain", 7,  target_date)
    chronic_28d, n_chronic  = _rolling_avg(whoop_items, "strain", 28, target_date)

    # ACWR ratio
    acwr = None
    if acute_7d is not None and chronic_28d is not None and chronic_28d > 0:
        acwr = round(acute_7d / chronic_28d, 3)

    zone, alert, reason = _classify_acwr(acwr)

    logger.info(
        "ACWR=%s zone=%s alert=%s | acute_7d=%s chronic_28d=%s "
        "(data coverage: %d/7d, %d/28d)",
        acwr, zone, alert, acute_7d, chronic_28d, n_acute, n_chronic,
    )

    _write_acwr(
        date_str     = target_date,
        acwr         = acwr,
        acute_7d     = acute_7d,
        chronic_28d  = chronic_28d,
        zone         = zone,
        alert        = alert,
        alert_reason = reason,
        n_days_acute = n_acute,
        n_days_chronic = n_chronic,
    )

    elapsed = round(time.time() - t0, 1)
    logger.info("Done in %ss", elapsed)

    return {
        "statusCode":      200,
        "body":            f"ACWR computed for {target_date}: {acwr} ({zone})",
        "date":            target_date,
        "acwr":            acwr,
        "zone":            zone,
        "alert":           alert,
        "alert_reason":    reason,
        "acute_load_7d":   acute_7d,
        "chronic_load_28d": chronic_28d,
        "n_acute_data":    n_acute,
        "n_chronic_data":  n_chronic,
        "elapsed_seconds": elapsed,
    }
