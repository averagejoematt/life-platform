#!/usr/bin/env python3
"""
Life Platform — Data Export & Portability Lambda (#19)

Monthly full DynamoDB table dump to S3 as partitioned JSON files.
One file per source partition for easy consumption.

Schedule: EventBridge — 1st of each month at 3:00 AM PT
Event: {"export_type": "full"} or {} for full export

Also supports:
  {"export_type": "source", "source": "whoop"} — single source export

Output: s3://matthew-life-platform/exports/YYYY-MM-DD/

Environment variables:
  TABLE_NAME  — DynamoDB table (default: life-platform)
  S3_BUCKET   — S3 bucket (default: matthew-life-platform)
  USER_ID     — User ID (default: matthew)
"""

import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger
    logger = get_logger("data-export")
except ImportError:
    logger = logging.getLogger("data-export")
    logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ["S3_BUCKET"]
USER_ID = os.environ["USER_ID"]
REGION = os.environ.get("AWS_REGION", "us-west-2")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3", region_name=REGION)

# All known source partitions
ALL_SOURCES = [
    "whoop", "withings", "strava", "todoist", "apple_health",
    "hevy", "eightsleep", "chronicling", "macrofactor", "garmin",
    "habitify", "notion", "labs", "dexa", "genome", "weather",
    "supplements", "state_of_mind", "habit_scores", "day_grade",
    "character_sheet", "insights", "experiments", "travel",
    "ruck_log", "life_events", "interactions", "temptations",
    "exposures", "chronicle", "food_responses", "rewards",
]


class DecimalEncoder(json.JSONEncoder):
    """Handle Decimal types from DynamoDB."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            if obj % 1 == 0:
                return int(obj)
            return float(obj)
        return super().default(obj)


def query_partition(source):
    """Query all items for a given source partition."""
    pk = f"USER#{USER_ID}#SOURCE#{source}"
    items = []
    kwargs = {"KeyConditionExpression": Key("pk").eq(pk)}

    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    return items


def export_to_s3(source, items, export_date):
    """Write items to S3 as JSON."""
    if not items:
        return 0

    key = f"exports/{export_date}/{source}.json"
    body = json.dumps(items, cls=DecimalEncoder, indent=2, default=str)

    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=body.encode("utf-8"),
        ContentType="application/json",
        StorageClass="STANDARD_IA",
    )

    return len(items)


def export_profile(export_date):
    """Export user profile separately."""
    pk = f"USER#{USER_ID}"
    sk = "PROFILE#v1"
    try:
        resp = table.get_item(Key={"pk": pk, "sk": sk})
        item = resp.get("Item")
        if item:
            key = f"exports/{export_date}/profile.json"
            body = json.dumps(item, cls=DecimalEncoder, indent=2, default=str)
            s3.put_object(
                Bucket=S3_BUCKET, Key=key,
                Body=body.encode("utf-8"),
                ContentType="application/json",
                StorageClass="STANDARD_IA",
            )
            return 1
    except Exception as e:
        logger.warning(f"Profile export failed: {e}")
    return 0


def lambda_handler(event, context):
    try:
        """
        Main handler.

        Event:
          {} or {"export_type": "full"} — full export of all partitions
          {"export_type": "source", "source": "whoop"} — single source
        """
        export_type = event.get("export_type", "full")
        export_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        logger.info(f"Starting {export_type} export for {export_date}")

        results = {}
        total_items = 0
        sources_exported = 0

        if export_type == "source":
            source = event.get("source")
            if not source:
                return {"statusCode": 400, "body": "Missing 'source' parameter"}
            sources_to_export = [source]
        else:
            sources_to_export = ALL_SOURCES

        for source in sources_to_export:
            try:
                items = query_partition(source)
                if items:
                    count = export_to_s3(source, items, export_date)
                    results[source] = count
                    total_items += count
                    sources_exported += 1
                    logger.info(f"  ✓ {source}: {count} items")
                else:
                    logger.info(f"  - {source}: empty")
            except Exception as e:
                results[source] = f"ERROR: {e}"
                logger.error(f"  ✗ {source}: {e}")

        # Export profile
        profile_count = export_profile(export_date)
        if profile_count:
            results["profile"] = profile_count
            total_items += profile_count

        # Write manifest
        manifest = {
            "export_date": export_date,
            "export_type": export_type,
            "total_items": total_items,
            "sources_exported": sources_exported,
            "s3_prefix": f"s3://{S3_BUCKET}/exports/{export_date}/",
            "results": results,
        }
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"exports/{export_date}/manifest.json",
            Body=json.dumps(manifest, indent=2).encode("utf-8"),
            ContentType="application/json",
        )

        logger.info(f"Export complete: {total_items} items across {sources_exported} sources")

        return {"statusCode": 200, "body": json.dumps(manifest)}
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
