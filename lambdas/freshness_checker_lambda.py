"""
Freshness Checker Lambda — monitors data source staleness.
Fires via EventBridge schedule. Alerts via SNS when sources are stale.
"""
import json
import os
import logging
import boto3
from datetime import datetime, timezone, timedelta

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger
    logger = get_logger("freshness-checker")
except ImportError:
    logger = logging.getLogger("freshness-checker")
    logger.setLevel(logging.INFO)

# ── Config (env vars with backwards-compatible defaults) ──
REGION      = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME  = os.environ.get("TABLE_NAME", "life-platform")
USER_ID     = os.environ.get("USER_ID", "matthew")
SNS_ARN     = os.environ.get("SNS_ARN", "arn:aws:sns:us-west-2:205930651321:life-platform-alerts")
STALE_HOURS = int(os.environ.get("STALE_HOURS", "48"))

dynamodb = boto3.resource("dynamodb", region_name=REGION)
sns      = boto3.client("sns", region_name=REGION)
cw       = boto3.client("cloudwatch", region_name=REGION)

SOURCES = {
    "whoop":           "Whoop recovery/sleep",
    "withings":        "Withings weight/body comp",
    "strava":          "Strava activities",
    "todoist":         "Todoist tasks",
    "apple_health":    "Apple Health",
    "eightsleep":      "Eight Sleep",
    "macrofactor":     "MacroFactor nutrition",
    "garmin":          "Garmin biometrics",
    "habitify":        "Habitify habits",
    "food_delivery":   "Food delivery behavioral signal",
    "measurements":    "Tape measure check-ins",
    # google_calendar retired v3.7.46 — see ADR-030 in DECISIONS.md
}

# R18-F04: Per-source stale threshold overrides (hours). Sources not listed use STALE_HOURS default.
# food_delivery is a quarterly CSV import — 90 days before stale alert.
SOURCE_STALE_HOURS = {
    "food_delivery": 90 * 24,   # 90 days
    "measurements": 60 * 24,    # 60 days — one missed session before alert
}

# Field-level completeness checks — key fields that should be non-null in a healthy record.
# A source can be "fresh" (recent date) but have partial data (missing key metrics).
# Missing fields here emit a PartialCompletenessCount metric and include source in alert.
# Added v3.7.27 (item 11 — Omar / Jin board recommendation).
FIELD_COMPLETENESS_CHECKS: dict[str, list[str]] = {
    "whoop":           ["hrv", "recovery_score", "sleep_duration_hours"],
    "garmin":          ["steps", "resting_heart_rate", "body_battery_highest"],
    "apple_health":    ["steps", "active_energy_kcal"],
    "macrofactor":     ["total_calories_kcal", "total_protein_g"],
    "strava":          ["activity_count"],
    "eightsleep":      ["sleep_efficiency_pct", "sleep_duration_hours"],
    "withings":        ["weight_lbs"],
    "habitify":        ["total_completed"],
    "measurements":    ["waist_navel_in", "waist_narrowest_in", "thigh_left_in"],
    "todoist":         ["tasks_completed"],
    # google_calendar removed — ADR-030
}

def lambda_handler(event, context):
    table = dynamodb.Table(TABLE_NAME)
    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(hours=STALE_HOURS)

    # ── Sick day check: suppress stale alerts if yesterday was a sick/rest day ──
    # Stale data on a sick day is expected — user is not tracking anything.
    yesterday_str = (now.date() - timedelta(days=1)).isoformat()
    _sick_suppress = False
    try:
        from sick_day_checker import check_sick_day as _check_fresh_sick
        _sick_fr = _check_fresh_sick(table, USER_ID, yesterday_str)
        if _sick_fr:
            _sick_suppress = True
            _sick_r = _sick_fr.get("reason") or "sick day"
            logger.info(
                "Sick day flagged for %s (%s) — freshness alerts suppressed",
                yesterday_str, _sick_r,
            )
    except ImportError:
        pass

    stale_sources = []
    partial_sources = []   # fresh but missing expected fields
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

            source_stale_hrs = SOURCE_STALE_HOURS.get(source_key, STALE_HOURS)
            source_stale_threshold = now - timedelta(hours=source_stale_hrs)
            if last_date < source_stale_threshold:
                stale_sources.append((source_name, f"Last update: {date_str} ({age_hours:.0f}h ago)"))
                source_status.append(f"  ⚠️  {source_name}: {date_str} ({age_hours:.0f}h ago)")
            else:
                # Source is fresh — now spot-check field completeness
                completeness_flag = ""
                expected_fields = FIELD_COMPLETENESS_CHECKS.get(source_key, [])
                if expected_fields:
                    try:
                        item_resp = table.get_item(
                            Key={"pk": pk, "sk": sk},
                            ProjectionExpression=", ".join(expected_fields),
                        )
                        item = item_resp.get("Item", {})
                        missing = [f for f in expected_fields if item.get(f) is None]
                        if missing:
                            partial_sources.append((source_name, missing))
                            completeness_flag = f" ⚠️ PARTIAL: {missing}"
                    except Exception as _ce:
                        logger.warning("Field completeness check failed for %s: %s", source_key, _ce)

                source_status.append(f"  ✅ {source_name}: {date_str} ({age_hours:.0f}h ago){completeness_flag}")
        except ValueError:
            stale_sources.append((source_name, f"Invalid date format: {date_str}"))
            source_status.append(f"  ❌ {source_name}: Invalid date {date_str}")

    if stale_sources:
        stale_list = "\n".join([f"  - {name}: {detail}" for name, detail in stale_sources])
        status_list = "\n".join(source_status)

        if _sick_suppress:
            # Sick day — expected data gap, no alert needed
            logger.info(
                "Stale sources detected (%d) but suppressed — sick day (%s)",
                len(stale_sources), yesterday_str,
            )
        else:
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

    # Partial completeness alert (separate from staleness alert)
    if partial_sources and not _sick_suppress:
        partial_list = "\n".join(
            [f"  - {name}: missing {', '.join(fields)}" for name, fields in partial_sources]
        )
        try:
            sns.publish(
                TopicArn=SNS_ARN,
                Subject=f"⚠️ Life Platform: {len(partial_sources)} partial record(s)",
                Message=(
                    f"⚠️ Life Platform: Partial Data Detected\n\n"
                    f"The following sources have fresh records but are missing expected fields:\n\n"
                    f"{partial_list}\n\n"
                    f"Checked at: {now.strftime('%Y-%m-%d %H:%M UTC')}"
                ),
            )
            logger.info("Partial completeness alert sent for %d source(s)", len(partial_sources))
        except Exception as e:
            logger.error("Partial completeness SNS publish failed: %s", e)

    # OBS-3: Emit SLO metrics to CloudWatch
    try:
        fresh_count = len(SOURCES) - len(stale_sources)
        cw.put_metric_data(
            Namespace="LifePlatform/Freshness",
            MetricData=[
                {
                    "MetricName": "StaleSourceCount",
                    "Value": len(stale_sources),
                    "Unit": "Count",
                },
                {
                    "MetricName": "FreshSourceCount",
                    "Value": fresh_count,
                    "Unit": "Count",
                },
                {
                    "MetricName": "PartialCompletenessCount",
                    "Value": float(len(partial_sources)),
                    "Unit": "Count",
                },
            ],
        )
        logger.info("SLO metrics emitted: %d stale, %d fresh, %d partial",
                    len(stale_sources), fresh_count, len(partial_sources))
    except Exception as e:
        logger.error("CloudWatch SLO metric emit failed (non-fatal): %s", e)

    # R8-ST4: OAuth token health check — alert if any OAuth refresh token not updated >60 days.
    # Prevents silent cascade failure if tokens expire during extended absence.
    OAUTH_SECRETS = [
        "life-platform/whoop",
        "life-platform/withings",
        "life-platform/strava",
        "life-platform/garmin",
    ]
    OAUTH_STALE_DAYS = int(os.environ.get("OAUTH_STALE_DAYS", "60"))
    try:
        sm = boto3.client("secretsmanager", region_name=REGION)
        oauth_stale = []
        for secret_name in OAUTH_SECRETS:
            try:
                meta = sm.describe_secret(SecretId=secret_name)
                last_changed = meta.get("LastChangedDate")
                if last_changed:
                    age_days = (now - last_changed.replace(tzinfo=timezone.utc)).days
                    if age_days > OAUTH_STALE_DAYS:
                        oauth_stale.append((secret_name, age_days))
                        logger.warning(
                            "OAuth token stale: %s last updated %d days ago",
                            secret_name, age_days,
                        )
            except Exception as _se:
                logger.warning("Could not check OAuth secret %s: %s", secret_name, _se)

        if oauth_stale:
            stale_list = "\n".join(
                [f"  - {name}: {days} days since last update" for name, days in oauth_stale]
            )
            try:
                sns.publish(
                    TopicArn=SNS_ARN,
                    Subject=f"⚠️ Life Platform: {len(oauth_stale)} OAuth token(s) may be expiring",
                    Message=(
                        f"⚠️ Life Platform: OAuth Token Health Warning\n\n"
                        f"The following OAuth secrets have not been updated in over {OAUTH_STALE_DAYS} days.\n"
                        f"Tokens may be at risk of expiring during extended absence:\n\n"
                        f"{stale_list}\n\n"
                        f"Action: trigger a manual data pull for each source to force a token refresh,\n"
                        f"or verify tokens are still valid in AWS Secrets Manager.\n\n"
                        f"Checked at: {now.strftime('%Y-%m-%d %H:%M UTC')}"
                    ),
                )
                logger.info("OAuth token health alert sent for %d secret(s)", len(oauth_stale))
            except Exception as _sns_e:
                logger.error("OAuth alert SNS publish failed: %s", _sns_e)

        # Emit CloudWatch metric for OAuth token staleness
        cw.put_metric_data(
            Namespace="LifePlatform/Freshness",
            MetricData=[{
                "MetricName": "OAuthTokenStaleCount",
                "Value": float(len(oauth_stale)),
                "Unit": "Count",
            }],
        )

    except Exception as _oauth_e:
        logger.error("OAuth token health check failed (non-fatal): %s", _oauth_e)

    return {
        "statusCode": 200,
        "stale_count": len(stale_sources),
        "stale_sources": [s[0] for s in stale_sources],
        "partial_count": len(partial_sources),
        "partial_sources": [s[0] for s in partial_sources],
        "checked_at": now.isoformat(),
    }
