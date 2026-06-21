"""
strava_lambda.py — Strava ingestion via SIMP-2 framework (P4.1, 2026-05-17).

5th of 8. OAuth-refresh-on-expiry. Fetches activities per day (framework's
per-date loop); enriches with HR zones + recovery streams for activities
that have heartrate data.

Source-specific concerns preserved:
  - OAuth refresh with 5-min expiry buffer
  - Activity HR zone fetch (Phase 2 enrichment)
  - HR recovery streams for ≥10-min activities (Feature #8)
  - Multi-device dedup (Whoop + Garmin + Apple Watch overlap)
  - Field presence validation logging (F2.5)
  - Daily aggregates: total_distance, moving_time, elevation, zone2

DDB shape unchanged from pre-migration.
"""

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import boto3

try:
    from platform_logger import get_logger

    logger = get_logger("strava")
except ImportError:
    logger = logging.getLogger("strava")
    logger.setLevel(logging.INFO)

from ingestion_framework import IngestionConfig, run_ingestion

SECRET_NAME = os.environ.get("SECRET_NAME", "life-platform/strava")
REGION = os.environ.get("AWS_REGION", "us-west-2")
USER_ID = os.environ.get("USER_ID", "matthew")

# Module-level CloudWatch client for writeback-failure metric (P3.6 pattern)
_cw = boto3.client("cloudwatch", region_name=REGION)


# ── Strava API helpers ────────────────────────────────────────────────────────


def _refresh_oauth(secret: dict) -> dict:
    """Refresh the access token using the refresh_token grant. Mutates+returns secret."""
    logger.info("Refreshing Strava access token...")
    data = urllib.parse.urlencode(
        {
            "client_id": secret["client_id"],
            "client_secret": secret["client_secret"],
            "refresh_token": secret["refresh_token"],
            "grant_type": "refresh_token",
        }
    ).encode()
    req = urllib.request.Request("https://www.strava.com/oauth/token", data=data, method="POST")
    from http_retry import urlopen_with_retry

    with urlopen_with_retry(req, timeout=30) as resp:
        result = json.loads(resp.read())
    secret["access_token"] = result["access_token"]
    secret["refresh_token"] = result["refresh_token"]
    secret["expires_at"] = result["expires_at"]
    return secret


def _strava_get(url: str, secret: dict) -> tuple:
    """GET with Bearer token; auto-refresh if token within 5 min of expiry."""
    if datetime.now(timezone.utc).timestamp() >= secret.get("expires_at", 0) - 300:
        secret = _refresh_oauth(secret)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {secret['access_token']}"})
    from http_retry import urlopen_with_retry

    with urlopen_with_retry(req, timeout=30) as resp:
        return json.loads(resp.read()), secret


def _fetch_activities_in_range(secret: dict, after_ts: float, before_ts: float):
    """Page through all activities in a time window."""
    activities, page = [], 1
    while True:
        url = f"https://www.strava.com/api/v3/athlete/activities" f"?after={int(after_ts)}&before={int(before_ts)}&per_page=100&page={page}"
        batch, secret = _strava_get(url, secret)
        if not batch:
            break
        activities.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return activities, secret


def _fetch_activity_zones(strava_id: str, secret: dict) -> tuple:
    """HR zones for a single activity. Returns ({zone1_sec, zone2_sec, ...}, secret)."""
    url = f"https://www.strava.com/api/v3/activities/{strava_id}/zones"
    try:
        result, secret = _strava_get(url, secret)
    except urllib.error.HTTPError as e:
        # Degrade gracefully — a missing/gated enrichment must NOT drop the activity.
        # 404/422 = no zones; 402 = Strava gates detailed data for this app/activity;
        # 429 = rate-limited. In all cases keep the summary activity.
        if e.code in (402, 404, 422, 429):
            logger.info("Strava zones skipped for %s (HTTP %s) — keeping summary", strava_id, e.code)
            return {}, secret
        raise
    zones = {}
    for z in result:
        if z.get("type") != "heartrate":
            continue
        for i, bucket in enumerate(z.get("distribution_buckets", []), start=1):
            zones[f"zone{i}_seconds"] = bucket.get("time", 0)
    return zones, secret


def _fetch_activity_streams(strava_id: str, secret: dict) -> tuple:
    """HR streams for recovery metric (60s drop after exercise)."""
    url = f"https://www.strava.com/api/v3/activities/{strava_id}/streams" f"?keys=heartrate,time&key_by_type=true"
    try:
        result, secret = _strava_get(url, secret)
    except urllib.error.HTTPError as e:
        # Same graceful degradation as zones — 402 (gated detailed data) / 429
        # (rate limit) / 404 / 422 must not drop the activity; keep the summary.
        if e.code in (402, 404, 422, 429):
            logger.info("Strava streams skipped for %s (HTTP %s) — keeping summary", strava_id, e.code)
            return {}, secret
        raise
    hr = result.get("heartrate", {}).get("data") if isinstance(result, dict) else None
    if not hr:
        return {}, secret
    peak = max(hr)
    peak_idx = hr.index(peak)
    after = hr[peak_idx : peak_idx + 60]
    if len(after) < 30:
        return {}, secret
    return {
        "hr_peak": peak,
        "hr_30s_recovery": peak - hr[peak_idx + 29],
        "hr_60s_recovery": peak - hr[peak_idx + 59] if len(after) >= 60 else None,
    }, secret


def _normalize(activity: dict, zone_data: dict = None, hr_recovery: dict = None) -> dict:
    result = {
        "strava_id": str(activity.get("id", "")),
        "name": activity.get("name", ""),
        "type": activity.get("type", ""),
        "sport_type": activity.get("sport_type", ""),
        "start_date": activity.get("start_date", ""),
        "start_date_local": activity.get("start_date_local", ""),
        "timezone": activity.get("timezone", ""),
        "moving_time_seconds": activity.get("moving_time"),
        "elapsed_time_seconds": activity.get("elapsed_time"),
        "distance_meters": activity.get("distance"),
        "distance_miles": round(activity["distance"] * 0.000621371, 2) if activity.get("distance") else None,
        "total_elevation_gain_meters": activity.get("total_elevation_gain"),
        "total_elevation_gain_feet": round(activity["total_elevation_gain"] * 3.28084, 1) if activity.get("total_elevation_gain") else None,
        "elev_high_meters": activity.get("elev_high"),
        "elev_low_meters": activity.get("elev_low"),
        "average_speed_ms": activity.get("average_speed"),
        "max_speed_ms": activity.get("max_speed"),
        "average_heartrate": activity.get("average_heartrate"),
        "max_heartrate": activity.get("max_heartrate"),
        "has_heartrate": activity.get("has_heartrate", False),
        "average_watts": activity.get("average_watts"),
        "max_watts": activity.get("max_watts"),
        "weighted_average_watts": activity.get("weighted_average_watts"),
        "kilojoules": activity.get("kilojoules"),
        "device_watts": activity.get("device_watts", False),
        "average_cadence": activity.get("average_cadence"),
        "pr_count": activity.get("pr_count", 0),
        "achievement_count": activity.get("achievement_count", 0),
        "kudos_count": activity.get("kudos_count", 0),
        "trainer": activity.get("trainer", False),
        "commute": activity.get("commute", False),
        "manual": activity.get("manual", False),
        "private": activity.get("private", False),
        "gear_id": activity.get("gear_id"),
        "device_name": activity.get("device_name"),
        "summary_polyline": activity.get("map", {}).get("summary_polyline", ""),
        "location_city": activity.get("location_city"),
        "location_state": activity.get("location_state"),
        "location_country": activity.get("location_country"),
    }
    if zone_data:
        result.update(zone_data)
    if hr_recovery:
        result["hr_recovery"] = hr_recovery
    return result


def _dedup(activities: list) -> list:
    """Dedup multi-device records — keep richest record per overlap window."""
    if len(activities) <= 1:
        return activities
    sorted_a = sorted(activities, key=lambda x: x.get("start_date", ""))
    kept = []
    for act in sorted_a:
        replaced = False
        for i, existing in enumerate(kept):
            try:
                t_existing = datetime.strptime(existing.get("start_date", "")[:19], "%Y-%m-%dT%H:%M:%S")
                t_new = datetime.strptime(act.get("start_date", "")[:19], "%Y-%m-%dT%H:%M:%S")
                if abs((t_new - t_existing).total_seconds()) > 120:
                    continue

                # Within 2-min window — overlap. Keep richer (has HR, watts, polyline)
                def richness(a):
                    return sum(
                        [
                            bool(a.get("has_heartrate")),
                            bool(a.get("device_watts")),
                            bool(a.get("map", {}).get("summary_polyline")),
                            bool(a.get("kilojoules")),
                        ]
                    )

                if richness(act) > richness(existing):
                    kept[i] = act
                replaced = True
                break
            except Exception:
                continue
        if not replaced:
            kept.append(act)
    return kept


# ── SIMP-2 callbacks ──────────────────────────────────────────────────────────

_secret_cache = {"secret": None}


def authenticate(secret_data: dict) -> dict:
    """Refresh on every invocation if within 5-min expiry buffer (matches old)."""
    secret = dict(secret_data)
    if datetime.now(timezone.utc).timestamp() >= secret.get("expires_at", 0) - 300:
        secret = _refresh_oauth(secret)
    _secret_cache["secret"] = secret
    return secret


def fetch_day(credentials: dict, date_str: str) -> dict | None:
    """Fetch one local day of Strava activities, keyed by the activity's local date.

    A record is keyed by the activity's local calendar date (``start_date_local``)
    so the day matches how the platform reports it (Pacific). But Strava's
    ``/athlete/activities`` window is expressed in UTC *instants*, and the two
    clocks disagree at the day boundary: an evening-PT activity (e.g. a 17:00
    walk) has a UTC start on the *next* calendar day. A naive same-day UTC window
    therefore loses it both ways — it falls just past the end of its own local
    day's window, and is rejected by the local-date filter on the next day's
    window. (This silently dropped every post-17:00-PT activity; see the Jun 2026
    Walk-ingestion gap.)

    Fix: bracket the UTC window by ±1 day so it is a strict superset of every
    instant that can map to ``date_str`` in any timezone (offsets span UTC-12..+14,
    well within ±24h). The ``start_date_local`` filter below then assigns each
    activity to exactly one local date — no gap, no double-count, and correct even
    when traveling (we trust the activity's own local clock, not a fixed offset).
    Over-fetching the activity *list* is cheap; per-activity HR enrichment stays
    gated by the filter, so it is not multiplied.
    """
    secret = _secret_cache["secret"] or credentials
    day = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    window_start = day - timedelta(days=1)
    window_end = day + timedelta(days=2)
    activities, secret = _fetch_activities_in_range(
        secret,
        window_start.timestamp(),
        window_end.timestamp(),
    )
    _secret_cache["secret"] = secret
    if not activities:
        return None
    activities = _dedup(activities)
    enriched = []
    for a in activities:
        if a.get("start_date_local", "")[:10] != date_str:
            continue  # ±1-day window over-fetches by design; keep only this local date
        zone_data, hr_recovery = {}, {}
        if a.get("has_heartrate") and a.get("id"):
            zone_data, secret = _fetch_activity_zones(str(a["id"]), secret)
            if (a.get("elapsed_time") or 0) >= 600:
                hr_recovery, secret = _fetch_activity_streams(str(a["id"]), secret)
        enriched.append(_normalize(a, zone_data, hr_recovery if a.get("has_heartrate") else None))
    _secret_cache["secret"] = secret
    return {"activities": enriched} if enriched else None


def transform(raw: dict, date_str: str) -> list[dict]:
    """Aggregate the day's activities into a single record."""
    if not raw or not raw.get("activities"):
        return []
    activities = raw["activities"]
    return [
        {
            "source": "strava",
            "date": date_str,
            "activity_count": len(activities),
            "activities": activities,
            "total_distance_miles": round(sum(a.get("distance_miles") or 0 for a in activities), 2),
            "total_moving_time_seconds": sum(a.get("moving_time_seconds") or 0 for a in activities),
            "total_elevation_gain_feet": round(sum(a.get("total_elevation_gain_feet") or 0 for a in activities), 1),
            "sport_types": sorted(set(a.get("sport_type", "") for a in activities)),
            "total_zone2_seconds": sum(a.get("zone2_seconds") or 0 for a in activities),
        }
    ]


# ── Framework config ──────────────────────────────────────────────────────────

_config = IngestionConfig(
    source_name="strava",
    secret_id=SECRET_NAME,
    s3_archive_prefix=f"raw/{USER_ID}/strava/activities",
    schema_version=1,
    enable_gap_detection=True,
    lookback_days=int(os.environ.get("LOOKBACK_DAYS", "7")),
    enable_secret_writeback=True,
    enable_item_size_guard=True,
    refresh_today=True,
)


def lambda_handler(event: dict, context) -> dict:
    try:
        if event.get("healthcheck"):
            return {"statusCode": 200, "body": "ok"}
        return run_ingestion(_config, authenticate, fetch_day, transform, event, context)
    except Exception as e:
        logger.error("strava ingestion failed: %s", e, exc_info=True)
        raise
