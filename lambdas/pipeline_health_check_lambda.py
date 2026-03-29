"""
Pipeline Health Check Lambda — active probe of all ingestion pipelines.

Invokes each ingestion Lambda and checks if it starts without crashing.
Catches: dead secrets, expired tokens, missing modules, auth failures.
Writes results to DynamoDB for status page consumption.

Schedule: Daily at 6:00 AM PT (13:00 UTC) — before morning ingestion crons.
"""

import json
import os
import logging
import time
import boto3
from datetime import datetime, timezone

try:
    from platform_logger import get_logger
    logger = get_logger("pipeline-health-check")
except ImportError:
    logger = logging.getLogger("pipeline-health-check")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
lambda_client = boto3.client("lambda", region_name=REGION)

PIPELINES = [
    # (lambda_function_name, display_name, source_id)
    ("whoop-data-ingestion", "Whoop", "whoop"),
    ("withings-data-ingestion", "Withings", "withings"),
    ("eightsleep-data-ingestion", "Eight Sleep", "eightsleep"),
    ("garmin-data-ingestion", "Garmin", "garmin"),
    ("strava-data-ingestion", "Strava", "strava"),
    ("habitify-data-ingestion", "Habitify", "habitify"),
    ("todoist-data-ingestion", "Todoist", "todoist"),
    ("notion-journal-ingestion", "Notion", "notion"),
    ("weather-data-ingestion", "Weather", "weather"),
    ("dropbox-poll", "Dropbox Poll", "dropbox"),
    ("health-auto-export-webhook", "Health Auto Export", "apple_health"),
    ("character-sheet-compute", "Character Sheet", "character_sheet"),
    ("daily-metrics-compute", "Daily Metrics", "computed_metrics"),
    ("daily-insight-compute", "Daily Insights", "insights"),
    ("adaptive-mode-compute", "Adaptive Mode", "adaptive_mode"),
    ("daily-brief", "Daily Brief", "daily_brief"),
    ("anomaly-detector", "Anomaly Detector", "anomaly_detector"),
]


def _probe_lambda(fn_name: str) -> dict:
    """Invoke a Lambda and check if it crashes. Returns result dict."""
    try:
        resp = lambda_client.invoke(
            FunctionName=fn_name,
            InvocationType="RequestResponse",
            Payload=b"{}",
        )
        status_code = resp.get("StatusCode", 0)
        has_error = "FunctionError" in resp

        if has_error:
            payload = json.loads(resp["Payload"].read())
            error_type = payload.get("errorType", "Unknown")
            error_msg = payload.get("errorMessage", "")[:120]
            return {
                "healthy": False,
                "error_type": error_type,
                "error_message": error_msg,
            }
        else:
            return {"healthy": True}

    except Exception as e:
        return {
            "healthy": False,
            "error_type": "InvocationError",
            "error_message": str(e)[:120],
        }


def lambda_handler(event, context):
    if hasattr(logger, 'set_date'):
        logger.set_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    now = datetime.now(timezone.utc)
    results = []
    pass_count = 0
    fail_count = 0

    for fn_name, display_name, source_id in PIPELINES:
        logger.info(f"Probing {display_name} ({fn_name})...")
        result = _probe_lambda(fn_name)
        result["function_name"] = fn_name
        result["display_name"] = display_name
        result["source_id"] = source_id
        results.append(result)

        if result["healthy"]:
            pass_count += 1
        else:
            fail_count += 1
            logger.warning(f"FAIL: {display_name} — {result.get('error_type')}: {result.get('error_message')}")

        # Rate limit — don't hammer Lambda concurrency
        time.sleep(0.5)

    # Write results to DynamoDB
    try:
        table.put_item(Item={
            "pk": f"USER#{USER_ID}#SOURCE#health_check",
            "sk": f"DATE#{now.strftime('%Y-%m-%d')}",
            "date": now.strftime("%Y-%m-%d"),
            "checked_at": now.isoformat(),
            "total": len(PIPELINES),
            "passed": pass_count,
            "failed": fail_count,
            "results": json.dumps(results),
            "failures": json.dumps([r for r in results if not r["healthy"]]),
        })
        logger.info(f"Health check stored: {pass_count} pass, {fail_count} fail")
    except Exception as e:
        logger.error(f"Failed to store health check: {e}")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "passed": pass_count,
            "failed": fail_count,
            "total": len(PIPELINES),
            "failures": [
                {"name": r["display_name"], "error": r.get("error_message", "")}
                for r in results if not r["healthy"]
            ],
        }),
    }
