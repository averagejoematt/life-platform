#!/usr/bin/env python3
"""
Strava historical backfill script.
Fetches all activities from START_DATE to today in 90-day batches.
Supports resume via checkpoint file and retries 429 rate-limit errors.
"""

import json
import boto3
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import time
import os
import sys


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
S3_BUCKET = "matthew-life-platform"
DYNAMODB_TABLE = "life-platform"
REGION = "us-west-2"

START_DATE = datetime(2000, 1, 1, tzinfo=timezone.utc)  # Extended to capture full history
BATCH_DAYS = 90
CHECKPOINT_FILE = os.path.join(os.path.dirname(__file__), ".strava_checkpoint")

# Retry settings for 429 rate-limit errors
MAX_RETRIES = 6
RETRY_BASE_SECONDS = 15  # doubles each retry: 15, 30, 60, 120, 240, 480

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
    print("Token refreshed.")
    return secret


def strava_get(url, secret):
    expires_at = secret.get("expires_at", 0)
    if datetime.now(timezone.utc).timestamp() >= expires_at - 300:
        secret = refresh_token(secret)

    for attempt in range(MAX_RETRIES):
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {secret['access_token']}"}
        )
        try:
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read()), secret
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = RETRY_BASE_SECONDS * (2 ** attempt)
                print(f"  [429 rate limited] waiting {wait}s before retry {attempt + 1}/{MAX_RETRIES}...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"Strava API still returning 429 after {MAX_RETRIES} retries on {url}")


def fetch_activities_in_window(secret, after_ts, before_ts):
    activities = []
    page = 1
    per_page = 100

    while True:
        url = f"https://www.strava.com/api/v3/athlete/activities?after={int(after_ts)}&before={int(before_ts)}&per_page={per_page}&page={page}"
        batch, secret = strava_get(url, secret)
        if not batch:
            break
        activities.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
        time.sleep(0.5)

    return activities, secret


def normalize_activity(activity):
    return {
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
    }


def save_to_s3(date_str, normalized, raw):
    key = f"raw/strava/activities/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"
    payload = {
        "date": date_str,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "activity_count": len(normalized),
        "activities": raw
    }
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=json.dumps(payload, default=str),
        ContentType="application/json"
    )


def save_to_dynamodb(date_str, activities):
    if not activities:
        return
    item = {
        "pk": "USER#matthew#SOURCE#strava",
        "sk": f"DATE#{date_str}",
        "date": date_str,
        "source": "strava",
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "activity_count": len(activities),
        "activities": activities,
        "total_distance_miles": round(sum(a.get("distance_miles") or 0 for a in activities), 2),
        "total_moving_time_seconds": sum(a.get("moving_time_seconds") or 0 for a in activities),
        "total_elevation_gain_feet": round(sum(a.get("total_elevation_gain_feet") or 0 for a in activities), 1),
        "sport_types": list(set(a.get("sport_type", "") for a in activities)),
    }
    table.put_item(Item=floats_to_decimal(item))


def save_checkpoint(dt):
    with open(CHECKPOINT_FILE, "w") as f:
        f.write(dt.isoformat())


def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            raw = f.read().strip()
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return None


def main():
    resume_from = load_checkpoint()
    if resume_from and resume_from > START_DATE:
        print(f"Resuming from checkpoint: {resume_from.date()}")
        current = resume_from
    else:
        print(f"Starting Strava backfill from {START_DATE.date()} to today")
        current = START_DATE

    secret = get_secret()
    end = datetime.now(timezone.utc)
    total_activities = 0
    total_dates = 0
    batch_num = 0

    while current < end:
        batch_end = min(current + timedelta(days=BATCH_DAYS), end)
        batch_num += 1
        print(f"\nBatch {batch_num}: {current.date()} → {batch_end.date()}")

        activities, secret = fetch_activities_in_window(
            secret, current.timestamp(), batch_end.timestamp()
        )

        if activities:
            by_date = {}
            for activity in activities:
                local_date = activity["start_date_local"][:10]
                if local_date not in by_date:
                    by_date[local_date] = []
                by_date[local_date].append(activity)

            for date_str, day_activities in sorted(by_date.items()):
                normalized = [normalize_activity(a) for a in day_activities]
                save_to_s3(date_str, normalized, day_activities)
                save_to_dynamodb(date_str, normalized)
                total_activities += len(day_activities)
                total_dates += 1

            print(f"  → {len(activities)} activities across {len(by_date)} days")
        else:
            print(f"  → No activities")

        save_checkpoint(batch_end)
        current = batch_end
        time.sleep(0.5)

    # Clean up checkpoint on successful completion
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
        print("Checkpoint cleared.")

    print(f"\n=== Backfill complete ===")
    print(f"Total activities: {total_activities}")
    print(f"Total active days: {total_dates}")
    print(f"Batches processed: {batch_num}")


if __name__ == "__main__":
    main()
