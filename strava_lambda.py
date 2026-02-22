import json
import boto3
import urllib.request
import urllib.parse
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal


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


def normalize_activity(activity):
    """Extract the fields we care about from a Strava activity summary."""
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


def save_to_s3(date_str, activities, raw_activities):
    key = f"raw/strava/activities/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"
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
    print(f"Saved {len(activities)} activities to DynamoDB for {date_str}")


def lambda_handler(event, context):
    if "start_date" in event and "end_date" in event:
        start_date = datetime.strptime(event["start_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_date = datetime.strptime(event["end_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    elif "date" in event:
        target = datetime.strptime(event["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        start_date = target
        end_date = target + timedelta(days=1)
    else:
        yesterday = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        start_date = yesterday
        end_date = yesterday + timedelta(days=1)

    print(f"Fetching Strava activities from {start_date.date()} to {end_date.date()}")

    secret = get_secret()
    after_ts = start_date.timestamp()
    before_ts = (end_date + timedelta(days=1)).timestamp()

    activities, secret = fetch_activities(secret, after_ts, before_ts)
    print(f"Found {len(activities)} total activities in range")

    if not activities:
        return {"statusCode": 200, "body": json.dumps({"activities_found": 0})}

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

    return {
        "statusCode": 200,
        "body": json.dumps({
            "activities_found": len(activities),
            "dates_covered": len(by_date)
        })
    }
