"""
Life Platform — Nightly Activity Enrichment Lambda
Runs after all daily syncs complete (EventBridge: 06:00 UTC = 10pm PT).

For each Strava activity in the target date window, writes two fields
back to the activity record in DynamoDB:

  enriched_name  — human-readable label combining location, stats, recovery,
                   percentile rank, and PR flag
  enriched_at    — ISO timestamp of last enrichment

Enriched name format:
  {activity_name} — {city}, {state} · {dist}mi · {elev}ft · {hr}bpm · {recovery_emoji} · {percentile_note} · {pr_note}

Each component is omitted gracefully if data is missing.

Generic activity names (Morning Run, Afternoon Hike, etc.) are detected
and the location is prepended as the primary identifier.

Runs on:
  - Yesterday by default (EventBridge nightly)
  - Arbitrary date range via event payload: {"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}
  - Full backfill via event payload: {"backfill": true, "start_date": "YYYY-MM-DD"}
"""

import json
import os
import boto3
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION         = os.environ.get("AWS_REGION", "us-west-2")
DYNAMODB_TABLE = os.environ.get("TABLE_NAME", "life-platform")
USER_ID        = os.environ.get("USER_ID", "matthew")
USER_PREFIX    = f"USER#{USER_ID}#SOURCE#"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table    = dynamodb.Table(DYNAMODB_TABLE)


# ── Helpers ───────────────────────────────────────────────────────────────────

def decimal_to_float(obj):
    if isinstance(obj, list):  return [decimal_to_float(i) for i in obj]
    if isinstance(obj, dict):  return {k: decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj

def floats_to_decimal(obj):
    if isinstance(obj, float): return Decimal(str(obj))
    if isinstance(obj, dict):  return {k: floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):  return [floats_to_decimal(v) for v in obj]
    return obj

def query_source(source, start_date, end_date):
    pk = f"{USER_PREFIX}{source}"
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(
            f"DATE#{start_date}", f"DATE#{end_date}~"
        )
    }
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        lk = resp.get("LastEvaluatedKey")
        if not lk:
            break
        kwargs["ExclusiveStartKey"] = lk
    return decimal_to_float(items)


# ── Generic name detection ────────────────────────────────────────────────────

GENERIC_PREFIXES = [
    "morning", "afternoon", "evening", "night", "lunch",
    "early", "late", "quick", "short", "long",
]
GENERIC_TYPES = [
    "run", "ride", "walk", "hike", "workout", "ride", "swim",
    "yoga", "cycling", "rowing", "elliptical", "activity",
]

def is_generic_name(name: str) -> bool:
    """Return True if the activity name is a Strava auto-generated generic."""
    n = name.lower().strip()
    # Pure type name: "Run", "Hike", etc.
    if n in GENERIC_TYPES:
        return True
    # "Morning Run", "Afternoon Hike", etc.
    parts = n.split()
    if len(parts) == 2 and parts[0] in GENERIC_PREFIXES and parts[1] in GENERIC_TYPES:
        return True
    return False


# ── Percentile rank helpers ───────────────────────────────────────────────────

def build_percentile_lookup(all_strava_items):
    """
    Build sorted lists of all-time elevation and distance values
    for percentile ranking individual activities.
    """
    all_elevations = []
    all_distances  = []
    for day in all_strava_items:
        for act in day.get("activities", []):
            elev = act.get("total_elevation_gain_feet")
            dist = act.get("distance_miles")
            if elev: all_elevations.append(float(elev))
            if dist: all_distances.append(float(dist))
    return sorted(all_elevations), sorted(all_distances)

def percentile(sorted_vals, val):
    """Return what percentile val falls at in sorted_vals (0–100)."""
    if not sorted_vals or val is None:
        return None
    import bisect
    pos = bisect.bisect_left(sorted_vals, float(val))
    return round(100.0 * pos / len(sorted_vals), 1)

def percentile_label(pct, metric):
    """Convert a percentile to a human-readable note, or None if unremarkable."""
    if pct is None:
        return None
    if pct >= 99:
        return f"top 1% {metric} ever"
    if pct >= 95:
        return f"top 5% {metric} ever"
    if pct >= 90:
        return f"top 10% {metric} ever"
    return None  # not remarkable enough to surface


# ── Recovery context ──────────────────────────────────────────────────────────

RECOVERY_EMOJI = {
    "green":  "🟢",
    "yellow": "🟡",
    "red":    "🔴",
}

def recovery_emoji(recovery_score):
    if recovery_score is None:
        return None
    if recovery_score >= 67:
        return RECOVERY_EMOJI["green"]
    if recovery_score >= 34:
        return RECOVERY_EMOJI["yellow"]
    return RECOVERY_EMOJI["red"]


# ── Enriched name builder ─────────────────────────────────────────────────────

def build_enriched_name(activity, recovery_score, elev_pcts, dist_pcts, sorted_elevations, sorted_distances):
    name      = activity.get("name", "").strip()
    city      = activity.get("location_city")
    state     = activity.get("location_state")
    dist      = activity.get("distance_miles")
    elev      = activity.get("total_elevation_gain_feet")
    hr        = activity.get("average_heartrate")
    pr_count  = activity.get("pr_count") or 0

    parts = []

    # Primary identifier: activity name, with location prepended if generic
    location_str = f"{city}, {state}" if city and state else (city or state or None)
    if is_generic_name(name) and location_str:
        parts.append(f"{location_str} {activity.get('sport_type', '').title()}")
    else:
        parts.append(name)
        if location_str:
            parts[-1] = f"{parts[-1]} — {location_str}"

    stats = []
    if dist:   stats.append(f"{dist:.1f}mi")
    if elev:   stats.append(f"{int(elev):,}ft")
    if hr:     stats.append(f"{int(hr)}bpm avg")
    if stats:
        parts.append(" · ".join(stats))

    # Recovery emoji
    emoji = recovery_emoji(recovery_score)
    if emoji:
        parts.append(emoji)

    # Percentile — use the more remarkable of elevation vs distance
    elev_pct = percentile(sorted_elevations, elev)
    dist_pct = percentile(sorted_distances, dist)
    elev_note = percentile_label(elev_pct, "elevation")
    dist_note = percentile_label(dist_pct, "distance")
    note = elev_note or dist_note   # elevation wins if both notable
    if note:
        parts.append(note)

    # PR flag
    if pr_count > 0:
        parts.append(f"{pr_count} PR{'s' if pr_count > 1 else ''}")

    return " · ".join(parts)


# ── Main enrichment logic ─────────────────────────────────────────────────────

def enrich_date_range(start_date: str, end_date: str):
    logger.info(f"[enrichment] Starting enrichment for {start_date} → {end_date}")

    # Load all Strava data (for percentile context) and target window
    logger.info("[enrichment] Loading all Strava data for percentile context...")
    all_strava = query_source("strava", "2000-01-01", end_date)
    sorted_elevations, sorted_distances = build_percentile_lookup(all_strava)
    logger.info(f"[enrichment] Percentile context: {len(sorted_elevations)} elevation datapoints, {len(sorted_distances)} distance datapoints")

    # Filter to target window
    target_days = [d for d in all_strava if start_date <= d.get("date", "") <= end_date]
    logger.info(f"[enrichment] Target days in window: {len(target_days)}")

    # Load Whoop for recovery context (same window)
    whoop_items = query_source("whoop", start_date, end_date)
    whoop_by_date = {w["date"]: w for w in whoop_items if w.get("date")}

    enriched_count = 0
    skipped_count  = 0

    for day in target_days:
        date_str = day.get("date")
        activities = day.get("activities", [])
        if not activities:
            continue

        # Recovery score for this day
        whoop_day = whoop_by_date.get(date_str, {})
        recovery  = whoop_day.get("recovery_score")

        updated_activities = []
        day_changed = False

        for act in activities:
            name = act.get("name", "")
            enriched = build_enriched_name(
                act, recovery, None, None,
                sorted_elevations, sorted_distances
            )

            if enriched != act.get("enriched_name"):
                act["enriched_name"] = enriched
                act["enriched_at"]   = datetime.now(timezone.utc).isoformat()
                day_changed = True
                enriched_count += 1
                logger.info(f"[enrichment] {date_str} | '{name}' → '{enriched}'")
            else:
                skipped_count += 1

            updated_activities.append(act)

        if day_changed:
            # Write updated activities list back to DynamoDB
            # DATA-2 note: enrichment updates existing strava records — validator runs at strava ingestion time
            table.update_item(
                Key={
                    "pk": f"{USER_PREFIX}strava",
                    "sk": f"DATE#{date_str}",
                },
                UpdateExpression="SET activities = :acts, enriched_at = :ts",
                ExpressionAttributeValues=floats_to_decimal({
                    ":acts": updated_activities,
                    ":ts":   datetime.now(timezone.utc).isoformat(),
                }),
            )

    logger.info(f"[enrichment] Complete — enriched={enriched_count} skipped={skipped_count}")
    return {"enriched": enriched_count, "skipped": skipped_count, "days_processed": len(target_days)}


# ── Lambda handler ────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    today     = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    if event.get("backfill"):
        start_date = event.get("start_date", "2020-01-01")
        end_date   = event.get("end_date", today)
        logger.info(f"[enrichment] Backfill mode: {start_date} → {end_date}")
    elif "start_date" in event and "end_date" in event:
        start_date = event["start_date"]
        end_date   = event["end_date"]
    else:
        # Default: yesterday (nightly run)
        start_date = yesterday
        end_date   = yesterday

    result = enrich_date_range(start_date, end_date)

    return {
        "statusCode": 200,
        "body": json.dumps({
            "mode":       "backfill" if event.get("backfill") else "nightly",
            "start_date": start_date,
            "end_date":   end_date,
            **result,
        })
    }
