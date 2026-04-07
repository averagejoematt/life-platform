"""
Sleep Reconciler Lambda — v1.0.0
BS-08: Unified Sleep Record — merge Whoop, Eight Sleep, Apple Health into one
canonical nightly sleep record per DDB date.

Schedule: daily at 7:00 AM PT (cron(0 14 * * ? *) UTC) — runs after all
  ingestion sources have synced (typically complete by 6 AM PT).

Conflict resolution rules (Omar / Huberman — Sprint 1 prereq doc):
  total_duration_hours   → Apple Health (most accurate clock time)
  sleep_stages (REM/deep/light/awake_pct) → Whoop (best staging algorithm)
  hrv_ms                 → Whoop (proprietary HRV algorithm during sleep)
  recovery_score         → Whoop (proprietary)
  bed_temp_c             → Eight Sleep (direct measurement)
  room_temp_c            → Eight Sleep
  hrv_score (env-based)  → Eight Sleep
  respiratory_rate       → Whoop preferred, Eight Sleep fallback
  sleep_score (env)      → Eight Sleep
  sleep_onset (time)     → Whoop preferred (detects actual sleep vs lying in bed)
  wake_time              → Whoop preferred
  sleep_efficiency_pct   → Whoop

Writes to: SOURCE#sleep_unified | DATE#<date>
  canonical fields + source_map (which source won each field)

v1.0.0 — 2026-03-17 (BS-08)
"""

import json
import os
import time
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3

try:
    from platform_logger import get_logger
    logger = get_logger("sleep-reconciler")
except ImportError:
    logger = logging.getLogger("sleep-reconciler")
    logger.setLevel(logging.INFO)

# ── Config ─────────────────────────────────────────────────────────────────────
_REGION    = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID    = os.environ.get("USER_ID", "matthew")

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)

# How many days back to reconcile (default: yesterday only; backfill via date param)
DEFAULT_LOOKBACK = int(os.environ.get("SLEEP_RECONCILER_LOOKBACK", "1"))


# ==============================================================================
# HELPERS
# ==============================================================================

def _sf(rec, field, default=None):
    """Safe float extraction."""
    if not rec or field not in rec:
        return default
    try:
        return float(rec[field])
    except (TypeError, ValueError):
        return default


def _to_dec(val):
    if val is None:
        return None
    try:
        return Decimal(str(round(float(val), 4)))
    except Exception:
        return None


def d2f(obj):
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def fetch_source_date(source, date_str):
    """Fetch a single DDB record for source + date."""
    try:
        r = table.get_item(
            Key={"pk": USER_PREFIX + source, "sk": "DATE#" + date_str}
        )
        return d2f(r.get("Item"))
    except Exception as e:
        logger.warning("fetch_source_date(%s, %s): %s", source, date_str, e)
        return None


# ==============================================================================
# RECONCILIATION LOGIC
# ==============================================================================

def reconcile_sleep(date_str):
    """
    Fetch Whoop, Eight Sleep, Apple Health records for date_str,
    apply conflict resolution rules, return canonical unified record.
    """
    whoop  = fetch_source_date("whoop",        date_str)
    eight  = fetch_source_date("eightsleep",   date_str)
    apple  = fetch_source_date("apple_health", date_str)

    if not whoop and not eight and not apple:
        return None, {}

    canonical  = {}
    source_map = {}  # field → winning source

    def _set(field, value, source):
        if value is not None:
            canonical[field]  = value
            source_map[field] = source

    # ── Total duration: Apple Health wins ───────────────────────────────────────
    apple_duration = _sf(apple, "sleep_duration_hours") or _sf(apple, "total_sleep_hours")
    whoop_duration = _sf(whoop, "sleep_duration_hours")
    duration_src   = "apple_health" if apple_duration else "whoop"
    _set("total_duration_hours", apple_duration or whoop_duration, duration_src)

    # ── Sleep staging: Whoop wins ───────────────────────────────────────────────
    for field, alias in [
        ("rem_pct",   "rem_percentage"),
        ("deep_pct",  "slow_wave_sleep_percentage"),
        ("light_pct", "light_sleep_percentage"),
        ("awake_pct", "awake_percentage"),
    ]:
        val = _sf(whoop, alias) or _sf(whoop, field)
        _set(field, val, "whoop")

    # ── HRV: Whoop wins ─────────────────────────────────────────────────────────
    _set("hrv_ms", _sf(whoop, "hrv"), "whoop")

    # ── Recovery: Whoop ─────────────────────────────────────────────────────────
    _set("recovery_score",       _sf(whoop, "recovery_score"), "whoop")
    _set("sleep_quality_score",  _sf(whoop, "sleep_quality_score") or _sf(whoop, "sleep_score"), "whoop")
    _set("sleep_efficiency_pct", _sf(whoop, "sleep_efficiency_percentage"), "whoop")

    # ── Respiratory rate: Whoop preferred, Eight Sleep fallback ─────────────────
    rr     = _sf(whoop, "respiratory_rate") or _sf(eight, "respiratory_rate")
    rr_src = "whoop" if whoop and whoop.get("respiratory_rate") else "eightsleep"
    _set("respiratory_rate", rr, rr_src)

    # ── Sleep onset / wake: Whoop preferred ─────────────────────────────────────
    for field, aliases in [
        ("sleep_onset", ["sleep_start", "bedtime_start"]),
        ("wake_time",   ["sleep_end",   "bedtime_end"]),
    ]:
        val = None
        for alias in aliases:
            val = (whoop or {}).get(alias)
            if val:
                break
        if not val and eight:
            for alias in aliases:
                val = eight.get(alias)
                if val:
                    break
        src = "whoop" if whoop and any((whoop or {}).get(a) for a in aliases) else "eightsleep"
        _set(field, val, src)

    # ── Eight Sleep environment fields ──────────────────────────────────────────
    if eight:
        _set("bed_temp_c",      _sf(eight, "bed_temp_c")    or _sf(eight, "avg_bed_temp_c"),   "eightsleep")
        _set("room_temp_c",     _sf(eight, "room_temp_c")   or _sf(eight, "avg_room_temp_c"),  "eightsleep")
        _set("sleep_score_env", _sf(eight, "sleep_score")   or _sf(eight, "sleep_fitness_score"), "eightsleep")
        _set("hrv_score_env",   _sf(eight, "hrv_score"),    "eightsleep")
        _set("toss_and_turns",  _sf(eight, "toss_and_turns"), "eightsleep")

    # ── Sources present ────────────────────────────────────────────────────────
    sources_present = []
    if whoop: sources_present.append("whoop")
    if eight: sources_present.append("eightsleep")
    if apple: sources_present.append("apple_health")

    canonical["sources_present"] = sources_present
    canonical["source_map"]      = json.dumps(source_map)
    canonical["date"]            = date_str
    canonical["reconciled_at"]   = datetime.now(timezone.utc).isoformat()

    return canonical, source_map


def store_unified_sleep(date_str, canonical):
    """Write unified sleep record to SOURCE#sleep_unified."""
    item = {
        "pk": USER_PREFIX + "sleep_unified",
        "sk": "DATE#" + date_str,
    }
    for k, v in canonical.items():
        if isinstance(v, float):
            item[k] = _to_dec(v) or Decimal("0")
        elif isinstance(v, list):
            item[k] = v
        elif v is not None:
            item[k] = v
    table.put_item(Item=item)
    logger.info("BS-08: Stored sleep_unified for %s (sources: %s)",
                date_str, canonical.get("sources_present", []))


# ==============================================================================
# LAMBDA HANDLER
# ==============================================================================

def lambda_handler(event, context):
    t0 = time.time()
    logger.info("Sleep Reconciler v1.0.0 starting...")

    if event.get("date"):
        dates = [event["date"]]
    elif event.get("start_date") and event.get("end_date"):
        start = datetime.strptime(event["start_date"], "%Y-%m-%d")
        end   = datetime.strptime(event["end_date"],   "%Y-%m-%d")
        dates = []
        d = start
        while d <= end:
            dates.append(d.strftime("%Y-%m-%d"))
            d += timedelta(days=1)
    else:
        today = datetime.now(timezone.utc).date()
        dates = [(today - timedelta(days=i)).isoformat()
                 for i in range(1, DEFAULT_LOOKBACK + 1)]

    stored  = 0
    skipped = 0
    errors  = 0

    for date_str in dates:
        try:
            canonical, source_map = reconcile_sleep(date_str)
            if canonical:
                store_unified_sleep(date_str, canonical)
                stored += 1
            else:
                logger.info("BS-08: No sleep data for %s — skipping", date_str)
                skipped += 1
        except Exception as e:
            logger.error("BS-08: Failed for %s: %s", date_str, e)
            errors += 1

    elapsed = time.time() - t0
    logger.info("Done in %.1fs — %d stored, %d skipped, %d errors",
                elapsed, stored, skipped, errors)

    return {
        "statusCode":   200,
        "body":         f"Sleep reconciler complete: {stored} stored, {skipped} skipped, {errors} errors",
        "dates":        dates,
        "stored":       stored,
        "skipped":      skipped,
        "errors":       errors,
        "elapsed_secs": round(elapsed, 1),
    }
