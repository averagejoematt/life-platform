"""
Life Platform — Nightly Activity Enrichment Lambda

Schedule: EventBridge cron(30 15 * * ? *) — 15:30 UTC (08:30 PT / 07:30 PST),
declared in `cdk/stacks/ingestion_stack.py`. This is NOT "after all daily syncs
complete": Strava itself re-ingests hourly at :10 through 23:10 UTC, so the same
day record is rewritten several times AFTER this run. Enrichment survives that
because `strava_lambda.ENRICHMENT_CARRY_FORWARD_FIELDS` is merged forward by
`ingestion_framework._store_item` (#2250) — not because of the slot's timing.

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
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import boto3
from boto3.dynamodb.conditions import Key

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from common.platform_logger import get_logger

    logger = get_logger("enrichment")
except ImportError:
    logger = logging.getLogger("enrichment")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
DYNAMODB_TABLE = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

# The far edge of the archive. ONE constant for both the percentile-context read
# and the backfill default: they used to be 2000-01-01 and 2020-01-01, so a "full
# backfill" ranked against activities it then never enriched.
ARCHIVE_START = "2000-01-01"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(DYNAMODB_TABLE)


# ── Helpers ───────────────────────────────────────────────────────────────────


from common.digest_utils import d2f as decimal_to_float  # shared bundled helpers (#970)

# Phase 4.2 (2026-05-16): canonical impl in lambdas/numeric.py.
try:
    from common.numeric import floats_to_decimal  # noqa: F401
except ImportError:
    if not TYPE_CHECKING:  # mypy sees ONE signature (the import); runtime unchanged (#1656)

        def floats_to_decimal(obj):
            if isinstance(obj, bool):
                return obj
            if isinstance(obj, float):
                return Decimal(str(obj))
            if isinstance(obj, dict):
                return {k: floats_to_decimal(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [floats_to_decimal(v) for v in obj]
            return obj


def query_source(source, start_date, end_date):
    pk = f"{USER_PREFIX}{source}"
    kwargs = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{start_date}", f"DATE#{end_date}~")}
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
    "morning",
    "afternoon",
    "evening",
    "night",
    "lunch",
    "early",
    "late",
    "quick",
    "short",
    "long",
]
# Strava's auto-name is "{time of day} {sport display name}", and a sport display
# name is not always one token — "Trail Run", "Mountain Bike Ride", "Weight
# Training". Multi-word entries live here rather than in a second list so the
# GENERIC_TYPES × GENERIC_PREFIXES set-guard in the test suite covers them too.
GENERIC_TYPES = [
    "run",
    "ride",
    "walk",
    "hike",
    "workout",
    "swim",
    "yoga",
    "cycling",
    "rowing",
    "elliptical",
    "activity",
    "trail run",
    "virtual run",
    "virtual ride",
    "mountain bike ride",
    "gravel ride",
    "e-bike ride",
    "weight training",
    "open water swim",
    "stair stepper",
    "inline skate",
    "nordic ski",
    "alpine ski",
]


def is_generic_name(name: str) -> bool:
    """Return True if the activity name is a Strava auto-generated generic."""
    n = (name or "").lower().strip()
    if not n:
        return False
    # Pure type name: "Run", "Hike", "Trail Run", etc.
    if n in GENERIC_TYPES:
        return True
    # "Morning Run", "Afternoon Mountain Bike Ride", etc. The WHOLE remainder must
    # be a known type — "Long Walk to the Pier" is a name Matthew chose.
    for prefix in GENERIC_PREFIXES:
        if n.startswith(f"{prefix} ") and n[len(prefix) + 1 :].strip() in GENERIC_TYPES:
            return True
    return False


# ── Percentile rank helpers ───────────────────────────────────────────────────


def _as_float(value):
    """`float(value)` or None — never an exception.

    `build_percentile_lookup` runs over the ENTIRE Strava archive before any day
    is enriched, so an unguarded `float()` let one unparseable row anywhere in
    history abort the whole nightly run (lambda_handler re-raises) and leave
    every clean activity unenriched. The cost of a bad row is now that row.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_percentile_lookup(all_strava_items):
    """
    Build sorted lists of all-time elevation and distance values
    for percentile ranking individual activities.

    Membership is `is not None`, not truthiness: a measured 0 is a data point at
    the bottom of the distribution, and dropping the bottom shrinks the
    denominator, which understates every other activity's published rank
    (ADR-104).

    THE POPULATION these percentiles are percentiles OF (#2331) — `is not None` is
    exactly the writer's rule, so this denominator is:
      * distance  — distance-bearing activities recorded with a distance channel
      * elevation — land-locomotion activities recorded with an elevation channel
    i.e. gym/court/studio sessions and indoor-trainer or manually-entered records are
    NOT in it, because distance and elevation were never measured for them. Every
    "top N% ever" label built from these pools inherits that population; see
    `ingestion/strava_population.py` for the per-type decision table.
    """
    all_elevations = []
    all_distances = []
    for day in all_strava_items:
        for act in day.get("activities", []):
            elev = _as_float(act.get("total_elevation_gain_feet"))
            dist = _as_float(act.get("distance_miles"))
            if elev is not None:
                all_elevations.append(elev)
            if dist is not None:
                all_distances.append(dist)
    return sorted(all_elevations), sorted(all_distances)


def percentile(sorted_vals, val):
    """Return what percentile val falls at in sorted_vals (0–100)."""
    numeric = _as_float(val)
    if not sorted_vals or numeric is None:
        return None
    import bisect

    # bisect_LEFT — the share of the population STRICTLY BELOW. Deliberate, and
    # deliberately not bisect_right: "top 1% ever" is a rarity claim, and
    # at-or-below would award it to a value tied with the max even when that tie
    # group IS most of the archive (ADR-104). See the tie test in
    # tests/test_enrichment_lambda_behavior.py.
    pos = bisect.bisect_left(sorted_vals, numeric)
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
    "green": "🟢",
    "yellow": "🟡",
    "red": "🔴",
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
    # `or ""` not `get(k, "")`: a stored key whose VALUE is None defeats the
    # default, and .strip()/.title() on None raised out of the whole nightly run.
    name = (activity.get("name") or "").strip()
    # Strava's sport_type is a CamelCase token — TrailRun, MountainBikeRide,
    # WeightTraining. `.title()` rewrote it to "Trailrun", which is the spelling
    # that then reached the site, both digests and the MCP search index.
    sport = (activity.get("sport_type") or "").strip()
    city = activity.get("location_city")
    state = activity.get("location_state")
    dist = activity.get("distance_miles")
    elev = activity.get("total_elevation_gain_feet")
    hr = activity.get("average_heartrate")
    pr_count = activity.get("pr_count") or 0

    parts = []

    # Primary identifier: activity name, with location prepended if generic
    location_str = f"{city}, {state}" if city and state else (city or state or None)
    if is_generic_name(name) and location_str:
        # .strip(): with no sport_type this used to store "Seattle, WA " —
        # trailing whitespace rendered verbatim by every reader surface.
        parts.append(f"{location_str} {sport}".strip())
    elif name:
        parts.append(f"{name} — {location_str}" if location_str else name)
    elif location_str:
        parts.append(location_str)

    stats = []
    if dist:
        stats.append(f"{dist:.1f}mi")
    if elev:
        stats.append(f"{int(elev):,}ft")
    if hr:
        stats.append(f"{int(hr)}bpm avg")
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
    note = elev_note or dist_note  # elevation wins if both notable
    if note:
        parts.append(note)

    # PR flag
    if pr_count > 0:
        parts.append(f"{pr_count} PR{'s' if pr_count > 1 else ''}")

    return " · ".join(parts)


# ── Main enrichment logic ─────────────────────────────────────────────────────


def _day_date(day) -> str:
    """The calendar date of a stored day record — `date` first, else its own `sk`.

    The window filter used to read `d.get("date", "")` while the query that
    returned the record selected on `sk`. A record that arrived without a `date`
    attribute was therefore returned by the query and then silently dropped by
    the filter: two notions of "which day is this" that must not disagree.
    """
    date_str = day.get("date")
    if date_str:
        return str(date_str)
    sk = str(day.get("sk") or "")
    if "DATE#" in sk:
        return sk.split("DATE#", 1)[1][:10]
    return ""


def enrich_date_range(start_date: str, end_date: str):
    logger.info(f"[enrichment] Starting enrichment for {start_date} → {end_date}")

    # Load all Strava data (for percentile context) and target window
    logger.info("[enrichment] Loading all Strava data for percentile context...")
    all_strava = query_source("strava", ARCHIVE_START, end_date)
    sorted_elevations, sorted_distances = build_percentile_lookup(all_strava)
    logger.info(
        f"[enrichment] Percentile context: {len(sorted_elevations)} elevation datapoints, {len(sorted_distances)} distance datapoints"
    )

    # Filter to target window
    target_days = [d for d in all_strava if start_date <= _day_date(d) <= end_date]
    logger.info(f"[enrichment] Target days in window: {len(target_days)}")

    # Load Whoop for recovery context (same window)
    whoop_items = query_source("whoop", start_date, end_date)
    whoop_by_date = {w["date"]: w for w in whoop_items if w.get("date")}

    enriched_count = 0
    skipped_count = 0

    for day in target_days:
        date_str = _day_date(day)
        activities = day.get("activities", [])
        if not activities:
            continue

        # Recovery score for this day
        whoop_day = whoop_by_date.get(date_str, {})
        recovery = whoop_day.get("recovery_score")

        updated_activities = []
        day_changed = False

        for act in activities:
            name = act.get("name", "")

            # Per-activity error boundary. lambda_handler() re-raises, so without
            # one, a single malformed row aborted the batch and every LATER day
            # in the window went unenriched with no record of where it stopped.
            # The row is left exactly as stored and logged at ERROR.
            try:
                enriched = build_enriched_name(act, recovery, None, None, sorted_elevations, sorted_distances)
            except Exception as exc:  # noqa: BLE001 — one bad row must cost one bad row
                logger.error(f"[enrichment] {date_str} | skipping malformed activity '{name}': {exc}", exc_info=True)
                updated_activities.append(act)
                continue

            if not enriched:
                # Nothing to say about this activity — storing "" would be a
                # label that reads as content and would churn every night.
                skipped_count += 1
                updated_activities.append(act)
                continue

            if enriched != act.get("enriched_name"):
                act["enriched_name"] = enriched
                act["enriched_at"] = datetime.now(timezone.utc).isoformat()
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
                ExpressionAttributeValues=floats_to_decimal(
                    {
                        ":acts": updated_activities,
                        ":ts": datetime.now(timezone.utc).isoformat(),
                    }
                ),
            )

    logger.info(f"[enrichment] Complete — enriched={enriched_count} skipped={skipped_count}")
    return {"enriched": enriched_count, "skipped": skipped_count, "days_processed": len(target_days)}


# ── Lambda handler ────────────────────────────────────────────────────────────


def lambda_handler(event, context):
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if hasattr(logger, "set_date"):
            logger.set_date(today)  # OBS-1
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

        if event.get("backfill"):
            # ARCHIVE_START, not 2020-01-01: the percentile context already reads
            # back to ARCHIVE_START, so a "full backfill" that started in 2020
            # RANKED against activities it then never enriched.
            start_date = event.get("start_date", ARCHIVE_START)
            end_date = event.get("end_date", today)
            logger.info(f"[enrichment] Backfill mode: {start_date} → {end_date}")
        elif "start_date" in event or "end_date" in event:
            # A one-sided range used to fall through to the nightly branch and
            # enrich yesterday instead — the operator's window discarded with no
            # warning (#1917 window-honesty class). Honour what was asked and
            # report the window actually run.
            start_date = event.get("start_date") or event.get("end_date") or yesterday
            end_date = event.get("end_date") or today
            logger.info(f"[enrichment] Explicit range: {start_date} → {end_date}")
        else:
            # Default: yesterday (nightly run)
            start_date = yesterday
            end_date = yesterday

        result = enrich_date_range(start_date, end_date)

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "mode": "backfill" if event.get("backfill") else "nightly",
                    "start_date": start_date,
                    "end_date": end_date,
                    **result,
                }
            ),
        }
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
