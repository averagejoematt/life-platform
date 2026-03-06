"""
Freshness Checker Lambda — monitors data source staleness.
Fires via EventBridge schedule. Alerts via SNS when sources are stale.
"""
import json
import os
import logging
import boto3
from datetime import datetime, timezone, timedelta

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Config (env vars with backwards-compatible defaults) ──
REGION      = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME  = os.environ.get("TABLE_NAME", "life-platform")
USER_ID     = os.environ.get("USER_ID", "matthew")
SNS_ARN     = os.environ.get("SNS_ARN", "arn:aws:sns:us-west-2:205930651321:life-platform-alerts")
STALE_HOURS = int(os.environ.get("STALE_HOURS", "48"))

dynamodb = boto3.resource("dynamodb", region_name=REGION)
sns      = boto3.client("sns", region_name=REGION)

SOURCES = {
    "whoop":        "Whoop recovery/sleep",
    "withings":     "Withings weight/body comp",
    "strava":       "Strava activities",
    "todoist":      "Todoist tasks",
    "apple_health": "Apple Health",
    "eightsleep":   "Eight Sleep",
    "macrofactor":  "MacroFactor nutrition",
    "garmin":       "Garmin biometrics",
    "habitify":     "Habitify habits",
}

def lambda_handler(event, context):
    table = dynamodb.Table(TABLE_NAME)
    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(hours=STALE_HOURS)

    stale_sources = []
    source_status = []

    for source_key, source_name in SOURCES.items():
        pk = f"USER#{USER_ID}#SOURCE#{source_key}"

        try:
            response = table.query(
                KeyConditionExpression="pk = :pk",
                ExpressionAttributeValues={":pk": pk},
                ScanIndexForward=False,
                Limit=1,
                ProjectionExpression="sk",
            )
        except Exception as e:
            logger.error("DynamoDB query failed for %s: %s", source_key, e)
            stale_sources.append((source_name, f"Query error: {e}"))
            source_status.append(f"  ❌ {source_name}: QUERY ERROR")
            continue

        items = response.get("Items", [])
        if not items:
            stale_sources.append((source_name, "No data found"))
            source_status.append(f"  ❌ {source_name}: NO DATA")
            continue

        sk = items[0]["sk"]
        date_str = sk.replace("DATE#", "")[:10]  # Take only YYYY-MM-DD, ignore sub-record suffixes

        try:
            last_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            age_hours = (now - last_date).total_seconds() / 3600

            if last_date < stale_threshold:
                stale_sources.append((source_name, f"Last update: {date_str} ({age_hours:.0f}h ago)"))
                source_status.append(f"  ⚠️  {source_name}: {date_str} ({age_hours:.0f}h ago)")
            else:
                source_status.append(f"  ✅ {source_name}: {date_str} ({age_hours:.0f}h ago)")
        except ValueError:
            stale_sources.append((source_name, f"Invalid date format: {date_str}"))
            source_status.append(f"  ❌ {source_name}: Invalid date {date_str}")

    if stale_sources:
        stale_list = "\n".join([f"  - {name}: {detail}" for name, detail in stale_sources])
        status_list = "\n".join(source_status)
        message = (
            f"⚠️ Life Platform: Stale Data Detected\n\n"
            f"The following sources have not updated in over {STALE_HOURS} hours:\n\n"
            f"{stale_list}\n\n"
            f"Full source status:\n{status_list}\n\n"
            f"Checked at: {now.strftime('%Y-%m-%d %H:%M UTC')}"
        )
        try:
            sns.publish(
                TopicArn=SNS_ARN,
                Subject=f"⚠️ Life Platform: {len(stale_sources)} stale source(s)",
                Message=message,
            )
            logger.info("Alert sent for %d stale source(s)", len(stale_sources))
        except Exception as e:
            logger.error("SNS publish failed: %s", e)
    else:
        status_list = "\n".join(source_status)
        logger.info("All sources fresh.\n%s", status_list)

    return {
        "statusCode": 200,
        "stale_count": len(stale_sources),
        "stale_sources": [s[0] for s in stale_sources],
        "checked_at": now.isoformat(),
    }
