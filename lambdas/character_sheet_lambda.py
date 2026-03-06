"""
Character Sheet Compute Lambda — v1.0.0
Scheduled daily at 9:35 AM PT (17:35 UTC via EventBridge).

Computes the character sheet for yesterday by:
  1. Querying all source data from DynamoDB (with rolling windows)
  2. Loading previous day's character sheet for level continuity
  3. Rebuilding 21-day raw_score histories from stored records
  4. Loading config from S3 via character_engine
  5. Calling compute_character_sheet()
  6. Storing the result to DynamoDB (SOURCE#character_sheet)

Separate from Daily Brief so any future consumer (gamification digest,
push notifications, Chronicle, buddy page) can read the pre-computed
record without re-engineering.

Must run AFTER:
  - Whoop refresh (9:30 AM PT) — ensures today's recovery data exists
  - Cache warmer (9:00 AM PT) — not a hard dependency but good ordering

Must run BEFORE:
  - Daily Brief (10:00 AM PT) — reads the stored record

v1.0.0 — 2026-03-02
"""

import json
import os
import time
import logging
import boto3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import character_engine

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Configuration from environment variables ──
_REGION    = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET  = os.environ.get("S3_BUCKET", "matthew-life-platform")
USER_ID    = os.environ.get("USER_ID", "matthew")

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
PILLAR_ORDER = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]

# ── AWS clients ──
dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)
s3       = boto3.client("s3", region_name=_REGION)


# ==============================================================================
# DDB QUERY HELPERS
# ==============================================================================

def d2f(obj):
    """Convert DynamoDB Decimal to float recursively."""
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def fetch_date(source, date_str):
    """Fetch a single record for a source on a given date."""
    try:
        resp = table.get_item(Key={
            "pk": USER_PREFIX + source,
            "sk": "DATE#" + date_str,
        })
        item = resp.get("Item")
        return d2f(item) if item else None
    except Exception as e:
        logger.warning("[character] fetch_date(%s, %s) failed: %s", source, date_str, e)
        return None


def fetch_range(source, start_date, end_date):
    """Fetch all records for a source within a date range."""
    try:
        records = []
        kwargs = {
            "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
            "ExpressionAttributeValues": {
                ":pk": USER_PREFIX + source,
                ":s": "DATE#" + start_date,
                ":e": "DATE#" + end_date,
            },
        }
        while True:
            resp = table.query(**kwargs)
            for item in resp.get("Items", []):
                records.append(d2f(item))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return records
    except Exception as e:
        logger.warning("[character] fetch_range(%s, %s→%s) failed: %s", source, start_date, end_date, e)
        return []


def fetch_journal_entries(date_str):
    """Fetch journal entries for a specific date."""
    try:
        pk = f"USER#{USER_ID}#SOURCE#notion"
        entries = []
        kwargs = {
            "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
            "ExpressionAttributeValues": {
                ":pk": pk,
                ":s": f"DATE#{date_str}#journal#",
                ":e": f"DATE#{date_str}#journal#zzz",
            },
        }
        while True:
            resp = table.query(**kwargs)
            for item in resp.get("Items", []):
                entries.append(d2f(item))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return entries
    except Exception as e:
        logger.warning("[character] fetch_journal_entries(%s) failed: %s", date_str, e)
        return []


def _safe_float(rec, field):
    """Extract a float from a record, returning None on failure."""
    if rec and field in rec:
        try:
            return float(rec[field])
        except (ValueError, TypeError):
            return None
    return None


# ==============================================================================
# DATA ASSEMBLY — mirrors retrocompute_character_sheet.assemble_data_for_date
# ==============================================================================

def assemble_data(yesterday_str):
    """Build the data dict that character_engine.compute_character_sheet() expects.

    Queries DDB directly for each source + rolling windows.
    """
    t0 = time.time()
    dt = datetime.strptime(yesterday_str, "%Y-%m-%d")
    data = {"date": yesterday_str}

    # ── Primary source records (yesterday) ──
    whoop = fetch_date("whoop", yesterday_str)
    data["sleep"] = whoop  # Whoop is SOT for sleep
    data["whoop"] = whoop
    data["macrofactor"] = fetch_date("macrofactor", yesterday_str)
    data["apple"] = fetch_date("apple_health", yesterday_str)
    data["journal"] = fetch_date("notion", yesterday_str)
    data["journal_entries"] = fetch_journal_entries(yesterday_str)
    data["habit_scores"] = fetch_date("habit_scores", yesterday_str)
    data["state_of_mind"] = fetch_date("state_of_mind", yesterday_str)

    # ── Rolling windows (batch queries for efficiency) ──

    # Sleep 14d (for onset consistency)
    sleep_14d_start = (dt - timedelta(days=13)).strftime("%Y-%m-%d")
    data["sleep_14d"] = fetch_range("whoop", sleep_14d_start, yesterday_str)

    # Strava 7d (training frequency, zone2, diversity)
    strava_7d_start = (dt - timedelta(days=6)).strftime("%Y-%m-%d")
    data["strava_7d"] = fetch_range("strava", strava_7d_start, yesterday_str)

    # Strava 42d (progressive overload / CTL trend)
    strava_42d_start = (dt - timedelta(days=41)).strftime("%Y-%m-%d")
    data["strava_42d"] = fetch_range("strava", strava_42d_start, yesterday_str)

    # MacroFactor 14d (nutrition consistency)
    mf_14d_start = (dt - timedelta(days=13)).strftime("%Y-%m-%d")
    data["macrofactor_14d"] = fetch_range("macrofactor", mf_14d_start, yesterday_str)

    # Withings 30d (body fat trajectory)
    withings_30d_start = (dt - timedelta(days=29)).strftime("%Y-%m-%d")
    data["withings_30d"] = fetch_range("withings", withings_30d_start, yesterday_str)

    # Latest weight — search backwards through withings 30d
    latest_weight = None
    for rec in reversed(data["withings_30d"]):
        w = _safe_float(rec, "weight_lbs")
        if w is None:
            w = _safe_float(rec, "weight_kg")
            if w is not None and w < 200:
                w = w * 2.20462
        if w is not None:
            latest_weight = w
            break
    data["latest_weight"] = latest_weight

    # Latest labs — search backwards from yesterday
    labs_all = fetch_range("labs", "2020-01-01", yesterday_str)
    data["labs_latest"] = d2f(labs_all[-1]) if labs_all else None

    # Blood pressure
    apple = data.get("apple") or {}
    bp_sys = _safe_float(apple, "blood_pressure_systolic")
    bp_dia = _safe_float(apple, "blood_pressure_diastolic")
    data["bp_data"] = {"systolic": bp_sys, "diastolic": bp_dia} if bp_sys and bp_dia else None

    # Journal 14d count — lightweight existence checks
    j14d_count = 0
    for i in range(14):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        try:
            pk = f"USER#{USER_ID}#SOURCE#notion"
            resp = table.query(
                KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
                ExpressionAttributeValues={
                    ":pk": pk,
                    ":s": f"DATE#{d}#journal#",
                    ":e": f"DATE#{d}#journal#zzz",
                },
                Select="COUNT",
            )
            if resp.get("Count", 0) > 0:
                j14d_count += 1
        except Exception:
            pass
    data["journal_14d_count"] = j14d_count

    # Data completeness — use already-fetched data where possible
    expected_count = 5  # whoop, macrofactor, apple_health, strava, habitify
    present = 0
    if data["whoop"]:
        present += 1
    if data["macrofactor"]:
        present += 1
    if data["apple"]:
        present += 1
    # Strava: check if yesterday is in our 7d window (avoids re-fetch)
    strava_dates = {r.get("date") or r.get("sk", "").replace("DATE#", "") for r in data["strava_7d"]}
    if yesterday_str in strava_dates:
        present += 1
    # Habitify: need a separate fetch (not queried elsewhere)
    if fetch_date("habitify", yesterday_str):
        present += 1
    data["data_completeness_pct"] = round((present / expected_count) * 100, 1)

    elapsed = time.time() - t0
    logger.info("[character] Data assembled for %s in %.1fs — sources: %s",
                yesterday_str, elapsed,
                ", ".join(k for k in ["whoop", "macrofactor", "apple", "habit_scores",
                                       "state_of_mind", "journal_entries"] if data.get(k)))
    return data


# ==============================================================================
# HISTORY LOADING — fetch prior character sheet records for continuity
# ==============================================================================

def load_previous_state(yesterday_str):
    """Load the character sheet record from the day before yesterday."""
    dt = datetime.strptime(yesterday_str, "%Y-%m-%d")
    day_before = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
    return fetch_date("character_sheet", day_before)


def load_raw_score_histories(yesterday_str, window=21):
    """Load up to `window` days of raw_score histories from stored character sheets.

    Returns dict of pillar_name -> list of raw_scores (oldest first).
    The engine uses these for EMA smoothing.
    """
    dt = datetime.strptime(yesterday_str, "%Y-%m-%d")
    start = (dt - timedelta(days=window)).strftime("%Y-%m-%d")
    end = (dt - timedelta(days=1)).strftime("%Y-%m-%d")

    records = fetch_range("character_sheet", start, end)

    histories = {p: [] for p in PILLAR_ORDER}
    # Records come back sorted by sk (DATE#...) which is chronological
    for rec in records:
        for p in PILLAR_ORDER:
            pdata = rec.get(f"pillar_{p}") or {}
            raw = pdata.get("raw_score")
            histories[p].append(float(raw) if raw is not None else 40.0)

    return histories


# ==============================================================================
# LAMBDA HANDLER
# ==============================================================================

def lambda_handler(event, context):
    t0 = time.time()
    logger.info("[character] Character Sheet Compute v1.0.0 starting...")

    # ── Determine target date ──
    # Default: yesterday. Can override via event for backfill/testing.
    if event.get("date"):
        yesterday_str = event["date"]
        logger.info("[character] Override date: %s", yesterday_str)
    else:
        today = datetime.now(timezone.utc).date()
        yesterday_str = (today - timedelta(days=1)).isoformat()

    # ── Check if already computed (idempotency) ──
    if not event.get("force"):
        existing = fetch_date("character_sheet", yesterday_str)
        if existing:
            logger.info("[character] Already computed for %s (level %s, tier %s) — skipping",
                        yesterday_str,
                        existing.get("character_level", "?"),
                        existing.get("character_tier", "?"))
            return {
                "statusCode": 200,
                "body": f"Already computed for {yesterday_str}",
                "character_level": existing.get("character_level"),
                "character_tier": existing.get("character_tier"),
            }

    # ── Load config from S3 ──
    config = character_engine.load_character_config(s3, S3_BUCKET)
    if not config:
        logger.error("[character] Failed to load config from S3 — aborting")
        return {"statusCode": 500, "body": "Config load failed"}

    logger.info("[character] Config loaded — %d pillars", len(config.get("pillars", {})))

    # ── Assemble data ──
    data = assemble_data(yesterday_str)

    # ── Load continuity state ──
    previous_state = load_previous_state(yesterday_str)
    if previous_state:
        logger.info("[character] Previous state loaded — Level %s (%s %s)",
                    previous_state.get("character_level", "?"),
                    previous_state.get("character_tier_emoji", ""),
                    previous_state.get("character_tier", "?"))
    else:
        logger.info("[character] No previous state — starting from baseline")

    raw_score_histories = load_raw_score_histories(yesterday_str)
    history_depth = max(len(v) for v in raw_score_histories.values()) if raw_score_histories else 0
    logger.info("[character] Raw score histories loaded — %d days of history", history_depth)

    # ── Compute ──
    try:
        record = character_engine.compute_character_sheet(
            data, previous_state, raw_score_histories, config
        )
    except Exception as e:
        logger.error("[character] compute_character_sheet failed: %s", e, exc_info=True)
        return {"statusCode": 500, "body": f"Computation failed: {e}"}

    char_level = record.get("character_level", 1)
    char_tier = record.get("character_tier", "Foundation")
    char_emoji = record.get("character_tier_emoji", "🔨")
    events = record.get("level_events", [])

    # Log pillar summary
    for p in PILLAR_ORDER:
        pd = record.get(f"pillar_{p}", {})
        logger.info("[character]   %s: raw=%s level=%s tier=%s (%s)",
                    p, pd.get("raw_score", "?"), pd.get("level", "?"),
                    pd.get("tier", "?"), pd.get("tier_emoji", "?"))

    # Log events
    if events:
        for ev in events:
            logger.info("[character]   EVENT: %s", json.dumps(ev, default=str))

    # Log active effects
    effects = record.get("active_effects", [])
    if effects:
        for eff in effects:
            logger.info("[character]   EFFECT: %s %s", eff.get("emoji", ""), eff.get("name", ""))

    # ── Store ──
    try:
        character_engine.store_character_sheet(table, USER_PREFIX, record)
        logger.info("[character] Stored: %s — Level %s (%s %s) — %d events",
                    yesterday_str, char_level, char_emoji, char_tier, len(events))
    except Exception as e:
        logger.error("[character] store_character_sheet failed: %s", e, exc_info=True)
        return {"statusCode": 500, "body": f"Store failed: {e}"}

    elapsed = time.time() - t0
    logger.info("[character] Done in %.1fs", elapsed)

    return {
        "statusCode": 200,
        "body": f"Character sheet computed for {yesterday_str}: Level {char_level} ({char_emoji} {char_tier})",
        "date": yesterday_str,
        "character_level": char_level,
        "character_tier": char_tier,
        "events": events,
        "elapsed_seconds": round(elapsed, 1),
    }
