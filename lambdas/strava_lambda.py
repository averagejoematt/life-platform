import json
import logging
import boto3
import urllib.request
import urllib.parse
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger
    logger = get_logger("strava")
except ImportError:
    logger = logging.getLogger("strava")
    logger.setLevel(logging.INFO)


def floats_to_decimal(obj):
    """Recursively convert floats to Decimal for DynamoDB compatibility."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: floats_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [floats_to_decimal(v) for v in obj]
    return obj


SECRET_NAME = "life-platform/strava"
# ── Config (env vars with backwards-compatible defaults) ──
REGION         = os.environ.get("AWS_REGION", "us-west-2")
S3_BUCKET      = os.environ["S3_BUCKET"]
DYNAMODB_TABLE = os.environ.get("TABLE_NAME", "life-platform")
USER_ID        = os.environ["USER_ID"]
LOOKBACK_DAYS  = int(os.environ.get("LOOKBACK_DAYS", "7"))

secrets_client = boto3.client("secretsmanager", region_name=REGION)
s3_client = boto3.client("s3", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(DYNAMODB_TABLE)


def get_secret():
    response = secrets_client.get_secret_value(SecretId=SECRET_NAME)
    return json.loads(response["SecretString"])


def save_secret(secret):
    secrets_client.put_secret_value(
        SecretId=SECRET_NAME,
        SecretString=json.dumps(secret)
    )


def refresh_token(secret):
    print("Refreshing Strava access token...")
    data = urllib.parse.urlencode({
        "client_id": secret["client_id"],
        "client_secret": secret["client_secret"],
        "refresh_token": secret["refresh_token"],
        "grant_type": "refresh_token"
    }).encode()

    req = urllib.request.Request(
        "https://www.strava.com/oauth/token",
        data=data,
        method="POST"
    )
    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read())

    secret["access_token"] = result["access_token"]
    secret["refresh_token"] = result["refresh_token"]
    secret["expires_at"] = result["expires_at"]
    save_secret(secret)
    print("Token refreshed and saved.")
    return secret


def strava_get(url, secret):
    """Make a GET request, refreshing token if expired."""
    expires_at = secret.get("expires_at", 0)
    if datetime.now(timezone.utc).timestamp() >= expires_at - 300:
        secret = refresh_token(secret)

    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {secret['access_token']}"}
    )
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read()), secret


def fetch_activity_zones(strava_id: str, secret: dict) -> tuple:
    """
    Fetch HR zone distribution for a single activity.

    GET /activities/{id}/zones returns time in each HR zone.
    Only called for activities with has_heartrate=True.

    Returns:
        (zone_data dict, updated secret)
        zone_data: {
            "hr_zone_seconds": [z1_secs, z2_secs, z3_secs, z4_secs, z5_secs],
            "zone2_seconds": int,
            "zone_sensor_based": bool,
            "zone_boundaries": [z1_max, z2_max, z3_max, z4_max]
        }
        Returns empty dict if zones not available.
    """
    try:
        url = f"https://www.strava.com/api/v3/activities/{strava_id}/zones"
        data, secret = strava_get(url, secret)

        if not data:
            return {}, secret

        # Find heartrate zone data
        hr_zones = None
        for zone_set in data:
            if zone_set.get("type") == "heartrate":
                hr_zones = zone_set
                break

        if not hr_zones:
            return {}, secret

        buckets = hr_zones.get("distribution_buckets") or []
        if len(buckets) < 2:
            return {}, secret

        zone_seconds = [int(b.get("time", 0)) for b in buckets]
        # Zone boundaries (max HR of each zone except last)
        boundaries = [int(b.get("max", 0)) for b in buckets[:-1]]

        result = {
            "hr_zone_seconds": zone_seconds,
            "zone_sensor_based": hr_zones.get("sensor_based", False),
        }

        # Zone boundaries for reference
        if boundaries:
            result["zone_boundaries"] = boundaries

        # Zone 2 is typically index 1 (0-indexed: Z1=recovery, Z2=aerobic, Z3=tempo, Z4=threshold, Z5=anaerobic)
        if len(zone_seconds) > 1:
            result["zone2_seconds"] = zone_seconds[1]

        print(f"  Zones for {strava_id}: {[f'Z{i+1}={s//60}m' for i, s in enumerate(zone_seconds)]}")
        return result, secret

    except Exception as e:
        print(f"  Warning: zones fetch failed for {strava_id}: {e}")
        return {}, secret




def fetch_activity_streams(strava_id: str, secret: dict) -> tuple:
    """
    Fetch HR + time streams for an activity. Computes HR recovery metrics.
    Returns (hr_recovery_dict, secret).
    """
    try:
        url = f"https://www.strava.com/api/v3/activities/{strava_id}/streams?keys=heartrate,time&key_type=time"
        data, secret = strava_get(url, secret)

        hr_data = None
        time_data = None
        for stream in data:
            if stream.get("type") == "heartrate":
                hr_data = stream.get("data", [])
            elif stream.get("type") == "time":
                time_data = stream.get("data", [])

        if not hr_data or not time_data or len(hr_data) < 60:
            return {}, secret

        # Rolling 30s average for peak detection
        rolling_avgs = []
        for i in range(len(hr_data)):
            start_idx = i
            while start_idx > 0 and time_data[i] - time_data[start_idx] < 30:
                start_idx -= 1
            window_vals = hr_data[start_idx:i+1]
            rolling_avgs.append(sum(window_vals) / len(window_vals) if window_vals else hr_data[i])

        peak_rolling = max(rolling_avgs)
        peak_rolling_idx = rolling_avgs.index(peak_rolling)
        peak_instant = max(hr_data)
        peak_time = time_data[peak_rolling_idx]
        total_time = time_data[-1]

        # Last 60s average
        last_60s_vals = [hr_data[i] for i in range(len(time_data))
                         if time_data[-1] - time_data[i] <= 60]
        end_60s = sum(last_60s_vals) / len(last_60s_vals) if last_60s_vals else None

        recovery_intra = round(peak_rolling - end_60s, 1) if end_60s else None
        has_cooldown = end_60s is not None and end_60s < peak_rolling * 0.85

        result = {
            "hr_peak": round(peak_rolling, 1),
            "hr_peak_instant": round(peak_instant, 1),
            "hr_end_60s": round(end_60s, 1) if end_60s else None,
            "hr_recovery_intra": recovery_intra,
            "has_cooldown": has_cooldown,
            "stream_duration_s": total_time,
            "stream_samples": len(hr_data),
        }

        remaining_time = total_time - peak_time
        if remaining_time >= 60:
            target_60 = peak_time + 60
            idx_60 = min(range(len(time_data)), key=lambda i: abs(time_data[i] - target_60))
            window_vals = [hr_data[j] for j in range(max(0, idx_60-5), min(len(hr_data), idx_60+5))]
            hr_at_60 = sum(window_vals) / len(window_vals) if window_vals else None
            if hr_at_60:
                result["hr_at_peak_plus_60s"] = round(hr_at_60, 1)
                result["hr_recovery_60s"] = round(peak_rolling - hr_at_60, 1)

        if remaining_time >= 120:
            target_120 = peak_time + 120
            idx_120 = min(range(len(time_data)), key=lambda i: abs(time_data[i] - target_120))
            window_vals = [hr_data[j] for j in range(max(0, idx_120-5), min(len(hr_data), idx_120+5))]
            hr_at_120 = sum(window_vals) / len(window_vals) if window_vals else None
            if hr_at_120:
                result["hr_at_peak_plus_120s"] = round(hr_at_120, 1)
                result["hr_recovery_120s"] = round(peak_rolling - hr_at_120, 1)

        print(f"  HR recovery: peak={result['hr_peak']}, end_60s={result.get('hr_end_60s')}, "
              f"recovery_intra={result.get('hr_recovery_intra')}, cooldown={has_cooldown}")
        return result, secret

    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"  No stream data for activity {strava_id}")
        elif e.code == 429:
            print(f"  Rate limited on stream fetch for {strava_id}")
        else:
            print(f"  Stream fetch error for {strava_id}: {e.code}")
        return {}, secret
    except Exception as e:
        print(f"  Stream fetch exception for {strava_id}: {e}")
        return {}, secret

def fetch_activities(secret, after_ts, before_ts=None):
    """Fetch all activities in a time window, handling pagination."""
    activities = []
    page = 1
    per_page = 100

    while True:
        url = f"https://www.strava.com/api/v3/athlete/activities?after={int(after_ts)}&per_page={per_page}&page={page}"
        if before_ts:
            url += f"&before={int(before_ts)}"

        batch, secret = strava_get(url, secret)
        if not batch:
            break

        activities.extend(batch)
        if len(batch) < per_page:
            break
        page += 1

    return activities, secret


def normalize_activity(activity, zone_data=None, hr_recovery=None):
    """Extract the fields we care about from a Strava activity summary + zones."""
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

    # Merge HR zone data if available (Phase 2 enhancement)
    if zone_data:
        result.update(zone_data)

    # Merge HR recovery data if available (Feature #8)
    if hr_recovery:
        result["hr_recovery"] = hr_recovery

    return result




def dedup_activities(activities):
    """Remove duplicate activities from multi-device Strava sync at ingestion time.

    When multiple devices (WHOOP, Garmin, Apple Watch) record the same workout,
    Strava stores each as a separate activity. This detects overlaps and keeps
    the richer record.

    Overlap = same sport_type AND start times within 15 minutes.
    Keep = prefer has-distance over no-distance, then longer duration.
    """
    if len(activities) <= 1:
        return activities

    def parse_start(a):
        s = a.get("start_date_local") or a.get("start_date") or ""
        try:
            return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def richness(a):
        """Score how much data an activity has. Higher = keep."""
        score = 0
        dist = float(a.get("distance_meters") or a.get("distance") or 0)
        if dist > 0:
            score += 1000  # GPS data is strong signal
        score += float(a.get("moving_time_seconds") or a.get("moving_time") or 0)
        polyline = a.get("summary_polyline") or (a.get("map") or {}).get("summary_polyline", "")
        if polyline:
            score += 500  # has route
        if a.get("average_cadence") is not None:
            score += 100  # has cadence
        return score

    # Sort by start time
    indexed = [(i, a, parse_start(a)) for i, a in enumerate(activities)]
    indexed_valid = [(i, a, t) for i, a, t in indexed if t is not None]
    indexed_valid.sort(key=lambda x: x[2])

    remove = set()
    for j in range(len(indexed_valid)):
        if j in remove:
            continue
        i_j, a_j, t_j = indexed_valid[j]
        sport_j = (a_j.get("sport_type") or a_j.get("type") or "").lower()
        for k in range(j + 1, len(indexed_valid)):
            if k in remove:
                continue
            i_k, a_k, t_k = indexed_valid[k]
            sport_k = (a_k.get("sport_type") or a_k.get("type") or "").lower()

            if sport_j != sport_k:
                continue

            gap_min = abs((t_k - t_j).total_seconds()) / 60
            if gap_min > 15:
                break  # sorted by time, no more overlaps

            # Overlap detected — remove the less rich one
            if richness(a_j) >= richness(a_k):
                remove.add(k)
                dev_drop = a_k.get("device_name", "?")
                dev_keep = a_j.get("device_name", "?")
            else:
                remove.add(j)
                dev_drop = a_j.get("device_name", "?")
                dev_keep = a_k.get("device_name", "?")
            print(f"  [DEDUP] {sport_j} overlap — kept {dev_keep}, dropped {dev_drop}")

    kept = [a for idx, (i, a, t) in enumerate(indexed_valid) if idx not in remove]
    # Also include any activities with no parseable start time
    no_time = [a for a in activities if parse_start(a) is None]
    result = kept + no_time
    if len(result) < len(activities):
        print(f"  [DEDUP] {len(activities)} → {len(result)} activities (removed {len(activities) - len(result)} duplicates)")
    return result


def save_to_s3(date_str, activities, raw_activities):
    key = f"raw/{USER_ID}/strava/activities/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"
    payload = {
        "date": date_str,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "activity_count": len(activities),
        "activities": raw_activities
    }
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=json.dumps(payload, default=str),
        ContentType="application/json"
    )
    print(f"Saved {len(activities)} activities to S3: {key}")


def save_to_dynamodb(date_str, activities):
    if not activities:
        return

    item = {
        "pk": f"USER#{USER_ID}#SOURCE#strava",
        "sk": f"DATE#{date_str}",
        "date": date_str,
        "source": "strava",
        "schema_version": 1,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "activity_count": len(activities),
        "activities": activities,
        "total_distance_miles": round(sum(a.get("distance_miles") or 0 for a in activities), 2),
        "total_moving_time_seconds": sum(a.get("moving_time_seconds") or 0 for a in activities),
        "total_elevation_gain_feet": round(sum(a.get("total_elevation_gain_feet") or 0 for a in activities), 1),
        "sport_types": list(set(a.get("sport_type", "") for a in activities)),
        # Phase 2: aggregate zone data across all activities for the day
        "total_zone2_seconds": sum(a.get("zone2_seconds") or 0 for a in activities),
    }

    _strava_item = floats_to_decimal(item)
    # ── DATA-2: Validate before write ──
    try:
        from ingestion_validator import validate_item as _validate_item
        _vr = _validate_item("strava", _strava_item, date_str)
        if _vr.should_skip_ddb:
            print(f"[DATA-2] CRITICAL: Skipping strava DDB write for {date_str}: {_vr.errors}")
            _vr.archive_to_s3(s3_client, bucket=S3_BUCKET, item=_strava_item)
            return
        if _vr.warnings:
            print(f"[DATA-2] Validation warnings for strava/{date_str}: {_vr.warnings}")
    except ImportError:
        pass  # validator not bundled — proceed

    # ── REL-3: safe_put_item handles 400KB limit, CW metrics, and truncation ──
    try:
        from item_size_guard import safe_put_item
        safe_put_item(table, _strava_item, source="strava", date_str=date_str)
    except ImportError:
        print(f"[WARN] item_size_guard not available — falling back to direct put_item")
        table.put_item(Item=_strava_item)
    print(f"Saved {len(activities)} activities to DynamoDB for {date_str}")


def lambda_handler(event, context):
    logger.set_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))  # OBS-1
    if "start_date" in event and "end_date" in event:
        start_date = datetime.strptime(event["start_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_date = datetime.strptime(event["end_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    elif "date" in event:
        target = datetime.strptime(event["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        start_date = target
        end_date = target + timedelta(days=1)
    else:
        # Gap-aware: fetch last LOOKBACK_DAYS days to catch any missed syncs
        # Strava API returns all activities in the window; put_item upserts safely
        now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        start_date = now - timedelta(days=LOOKBACK_DAYS)
        end_date = now
        print(f"[GAP-FILL] Strava lookback: fetching last {LOOKBACK_DAYS} days")

    print(f"Fetching Strava activities from {start_date.date()} to {end_date.date()}")

    secret = get_secret()
    after_ts = start_date.timestamp()
    before_ts = (end_date + timedelta(days=1)).timestamp()

    activities, secret = fetch_activities(secret, after_ts, before_ts)
    print(f"Found {len(activities)} total activities in range")

    if not activities:
        return {"statusCode": 200, "body": json.dumps({"activities_found": 0})}

    # Deduplicate multi-device recordings at ingestion time (v2.34.0)
    orig_count = len(activities)
    activities = dedup_activities(activities)
    if len(activities) < orig_count:
        print(f"[DEDUP] Global dedup: {orig_count} → {len(activities)} activities")

    by_date = {}
    for activity in activities:
        local_date = activity["start_date_local"][:10]
        if local_date not in by_date:
            by_date[local_date] = []
        by_date[local_date].append(activity)

    for date_str, day_activities in sorted(by_date.items()):
        normalized = []
        for a in day_activities:
            # Fetch HR zones for activities with heart rate data (Phase 2)
            zone_data = {}
            hr_recovery = {}
            if a.get("has_heartrate") and a.get("id"):
                zone_data, secret = fetch_activity_zones(str(a["id"]), secret)
                # Fetch HR streams for recovery metrics (>= 10 min activities)
                elapsed = a.get("elapsed_time") or 0
                if elapsed >= 600:
                    hr_recovery, secret = fetch_activity_streams(str(a["id"]), secret)
            normalized.append(normalize_activity(a, zone_data, hr_recovery if a.get("has_heartrate") else None))
        # ── Field presence validation (F2.5) ──────────────────────────────────────
        for act in normalized:
            STRAVA_CRITICAL = ["strava_id", "name", "type", "start_date_local",
                               "moving_time_seconds", "distance_meters"]
            STRAVA_EXPECTED = ["average_heartrate", "total_elevation_gain_feet",
                               "kilojoules"]
            missing_crit = [f for f in STRAVA_CRITICAL if not act.get(f)]
            missing_exp = [f for f in STRAVA_EXPECTED if act.get(f) is None]
            if missing_crit:
                print(f"[VALIDATION] ⚠️ CRITICAL fields missing for activity {act.get('strava_id','?')}: {missing_crit}")
            if missing_exp:
                print(f"[VALIDATION] Expected fields missing for activity {act.get('strava_id','?')}: {missing_exp}")

        save_to_s3(date_str, normalized, day_activities)
        save_to_dynamodb(date_str, normalized)

    return {
        "statusCode": 200,
        "body": json.dumps({
            "activities_found": len(activities),
            "dates_covered": len(by_date)
        })
    }
