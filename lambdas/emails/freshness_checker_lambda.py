"""
Freshness Checker Lambda — monitors data source staleness.
Fires via EventBridge schedule. Alerts via SNS when sources are stale.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

import boto3

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger

    logger = get_logger("freshness-checker")
except ImportError:
    logger = logging.getLogger("freshness-checker")
    logger.setLevel(logging.INFO)

# ── Config (env vars with backwards-compatible defaults) ──
REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
SNS_ARN = os.environ.get("SNS_ARN", "arn:aws:sns:us-west-2:205930651321:life-platform-alerts")
STALE_HOURS = int(os.environ.get("STALE_HOURS", "48"))
# ADR-052: early-warning threshold. Sources between 24h and STALE_HOURS old
# emit a WarningSourceCount metric so degradation is visible on dashboards
# before it crosses the alarm threshold. No SNS alert from this tier.
WARNING_HOURS = int(os.environ.get("WARNING_HOURS", "24"))
# ADR-052: sick-day suppression looks back N days, not just yesterday.
# A multi-day illness or travel window shouldn't keep re-triggering staleness
# alerts day after day.
SICK_SUPPRESS_DAYS = int(os.environ.get("SICK_SUPPRESS_DAYS", "3"))

dynamodb = boto3.resource("dynamodb", region_name=REGION)
sns = boto3.client("sns", region_name=REGION)
cw = boto3.client("cloudwatch", region_name=REGION)

SOURCES = {
    "whoop": "Whoop recovery/sleep",
    "withings": "Withings weight/body comp",
    # "strava":        "Strava activities",  # PAUSED 2026-05-28 (API 402; Garmin covers activity)
    "todoist": "Todoist tasks",
    "apple_health": "Apple Health",
    "eightsleep": "Eight Sleep",
    # "macrofactor":   "MacroFactor nutrition",  # dead since 2026-04-11 (Tier 1 torn down)
    # "garmin":        "Garmin biometrics",  # PAUSED 2026-06-03 — Garmin's 2026 anti-automation
    #   crackdown 429-blocks server-side OAuth2 refresh from datacenter IPs (374 throttles vs 2
    #   successes / 14d). Unwinnable headless; re-auth only buys ~1 run. Revive = uncomment +
    #   re-auth from a residential IP (or if Garmin's official Health API is ever approved).
    "habitify": "Habitify habits",
    "food_delivery": "Food delivery behavioral signal",
    "measurements": "Tape measure check-ins",
    # google_calendar retired v3.7.46 — see ADR-030 in DECISIONS.md
}

# R18-F04: Per-source stale threshold overrides (hours). Sources not listed use STALE_HOURS default.
# food_delivery is a quarterly CSV import — 90 days before stale alert.
SOURCE_STALE_HOURS = {
    "food_delivery": 90 * 24,  # 90 days
    "measurements": 60 * 24,  # 60 days — one missed session before alert
    # 2026-05-29: weigh-ins are sporadic (often ~weekly), so the 48h default
    # false-fired "stale" constantly. A missed week before alerting.
    "withings": 7 * 24,  # 7 days
    # todoist records are dated by completed DAY and the freshest record is always
    # "yesterday" (today's completions aren't known until the day ends), so a 24h
    # default false-fires every afternoon. 48h still catches a genuine 2-day outage.
    "todoist": 48,
}

# S-06: Sources whose staleness means "no manual entry logged yet" rather than a
# broken pipeline. They still appear in the freshness report/email, but do NOT
# count toward StaleSourceCount — the metric the slo-source-freshness alarm
# watches — so only infra/OAuth/API breakage (actionable) pages. Device-synced
# (whoop/withings/eightsleep) and API/webhook (todoist/apple_health/habitify)
# sources stay infra. Zero new metrics/alarms: this only redefines what the
# existing StaleSourceCount counts.
BEHAVIORAL_SOURCES = {"measurements", "food_delivery"}

# Field-level completeness checks — key fields that should be non-null in a healthy record.
# A source can be "fresh" (recent date) but have partial data (missing key metrics).
# Missing fields here emit a PartialCompletenessCount metric and include source in alert.
# Added v3.7.27 (item 11 — Omar / Jin board recommendation).
FIELD_COMPLETENESS_CHECKS: dict[str, list[str]] = {
    "whoop": ["hrv", "recovery_score", "sleep_duration_hours"],
    "garmin": ["steps", "resting_heart_rate", "body_battery_highest"],
    "apple_health": ["steps", "active_energy_kcal"],
    # "macrofactor":   [...],  # dead since 2026-04-11 (Tier 1 torn down)
    # "strava":        ["activity_count"],  # PAUSED 2026-05-28
    "eightsleep": ["sleep_efficiency_pct", "sleep_duration_hours"],
    "withings": ["weight_lbs"],
    "habitify": ["total_completed"],
    "measurements": ["waist_navel_in", "waist_narrowest_in", "thigh_left_in"],
    "todoist": ["tasks_completed"],
    # google_calendar removed — ADR-030
}


def lambda_handler(event, context):
    table = dynamodb.Table(TABLE_NAME)
    now = datetime.now(timezone.utc)
    now - timedelta(hours=STALE_HOURS)

    # ── Sick day check: suppress stale alerts if any of the last N days was sick ──
    # ADR-052: extended from yesterday-only to a N-day lookback so multi-day
    # illness or travel doesn't keep re-triggering staleness alerts.
    # Stale data on a sick day is expected — user is not tracking anything.
    window_end = now.date() - timedelta(days=1)
    window_start = now.date() - timedelta(days=SICK_SUPPRESS_DAYS)
    _sick_suppress = False
    try:
        from sick_day_checker import get_sick_days_range

        sick_records = get_sick_days_range(
            table,
            USER_ID,
            window_start.isoformat(),
            window_end.isoformat(),
        )
        if sick_records:
            _sick_suppress = True
            _sick_dates = ", ".join(sorted(r.get("sk", "").replace("DATE#", "")[:10] for r in sick_records))
            logger.info(
                "Sick day(s) flagged in last %d days (%s) — freshness alerts suppressed",
                SICK_SUPPRESS_DAYS,
                _sick_dates,
            )
    except ImportError:
        pass

    stale_sources = []
    partial_sources = []  # fresh but missing expected fields
    warning_sources = []  # ADR-052: age > WARNING_HOURS but < stale threshold
    source_status = []

    for source_key, source_name in SOURCES.items():
        pk = f"USER#{USER_ID}#SOURCE#{source_key}"

        try:
            # Filter SK to DATE# prefix so non-date sentinel records (e.g.
            # REFRESH_RATELIMIT for garmin, YEAR#2026 for food_delivery) —
            # which sort lexicographically after DATE#YYYY-MM-DD — are never
            # returned as the "latest" record, causing a false-stale alarm.
            response = table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
                ExpressionAttributeValues={":pk": pk, ":pfx": "DATE#"},
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
            elif age_hours >= WARNING_HOURS:
                # ADR-052: early-warning tier — track but don't alert.
                # Visible on dashboards; helps spot degradation before it crosses
                # the alarm threshold.
                warning_sources.append((source_name, age_hours))
                source_status.append(f"  🟡 {source_name}: {date_str} ({age_hours:.0f}h ago) [warning]")
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
            yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            logger.info(
                "Stale sources detected (%d) but suppressed — sick day (%s)",
                len(stale_sources),
                yesterday_str,
            )
        else:
            # Actionable remediation hint, keyed off which stale sources are present.
            _stale_keys = {n for n, _ in stale_sources}
            _oauth_stale = {
                lbl
                for lbl in _stale_keys
                if lbl in (SOURCES.get("garmin"), SOURCES.get("whoop"), SOURCES.get("withings"), SOURCES.get("eightsleep"))
            }
            _input_stale = {lbl for lbl in _stale_keys if lbl in (SOURCES.get("measurements"), SOURCES.get("food_delivery"))}
            hints = []
            if _oauth_stale:
                hints.append(
                    f"• OAuth source(s) stale ({', '.join(sorted(_oauth_stale))}) → the token likely "
                    f"expired; re-auth (Garmin: `python3 setup_garmin_browser_auth.py`)."
                )
            if _input_stale:
                hints.append(
                    f"• Input source(s) stale ({', '.join(sorted(_input_stale))}) → no new entry logged; "
                    f"expected if you've paused that tracking."
                )
            remediation = ("\n\nWhat to do:\n" + "\n".join(hints)) if hints else ""
            message = (
                f"⚠️ Life Platform: Stale Data Detected\n\n"
                f"The following sources have not updated in over {STALE_HOURS} hours:\n\n"
                f"{stale_list}{remediation}\n\n"
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
        partial_list = "\n".join([f"  - {name}: missing {', '.join(fields)}" for name, fields in partial_sources])
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
        # S-06: StaleSourceCount counts only infra/pipeline staleness (actionable —
        # OAuth/API/webhook breakage), not behavioral input lapses. Behavioral
        # sources remain in stale_sources for the email report but don't trip the SLO.
        _behavioral_labels = {SOURCES[k] for k in BEHAVIORAL_SOURCES if k in SOURCES}
        infra_stale_count = sum(1 for name, _ in stale_sources if name not in _behavioral_labels)
        cw.put_metric_data(
            Namespace="LifePlatform/Freshness",
            MetricData=[
                {
                    "MetricName": "StaleSourceCount",
                    "Value": infra_stale_count,
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
                # ADR-052: early-warning metric (no alarm). Dashboards and
                # operators see degradation before it crosses the alarm threshold.
                {
                    "MetricName": "WarningSourceCount",
                    "Value": float(len(warning_sources)),
                    "Unit": "Count",
                },
            ],
        )
        logger.info(
            "SLO metrics emitted: %d stale, %d fresh, %d partial, %d warning",
            len(stale_sources),
            fresh_count,
            len(partial_sources),
            len(warning_sources),
        )
    except Exception as e:
        logger.error("CloudWatch SLO metric emit failed (non-fatal): %s", e)

    # R8-ST4: OAuth token health check — alert if any OAuth refresh token not updated >60 days.
    # Prevents silent cascade failure if tokens expire during extended absence.
    # Phase 2.6 (2026-05-16): also monitor manually-rotated secrets (Anthropic + 3rd-party
    # API tokens) at a longer 120-day threshold. These don't auto-refresh and need human
    # rotation; surfacing staleness lets the operator schedule rotation proactively.
    OAUTH_SECRETS = [
        "life-platform/whoop",
        "life-platform/withings",
        # "life-platform/strava",  # PAUSED 2026-05-28 (Strava API 402; Garmin covers activity)
        # "life-platform/garmin",  # PAUSED 2026-06-03 — see SOURCES note (server-side refresh 429-blocked)
    ]
    MANUAL_ROTATION_SECRETS = [
        "life-platform/ai-keys",  # Anthropic — no rotation API; manual every 90d
        "life-platform/site-api-ai-key",  # Anthropic — separate key for site API
        "life-platform/eightsleep-client",
        "life-platform/notion",
        # "life-platform/dropbox",  # removed 2026-05-28 — secret soft-deleted
        "life-platform/todoist",
        "life-platform/ingestion-keys",  # COST-B bundle: Notion + Habitify + Todoist + Dropbox + HAE
    ]
    OAUTH_STALE_DAYS = int(os.environ.get("OAUTH_STALE_DAYS", "60"))
    MANUAL_ROTATION_STALE_DAYS = int(os.environ.get("MANUAL_ROTATION_STALE_DAYS", "120"))
    try:
        sm = boto3.client("secretsmanager", region_name=REGION)
        oauth_stale = []
        manual_stale = []
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
                            secret_name,
                            age_days,
                        )
            except Exception as _se:
                logger.warning("Could not check OAuth secret %s: %s", secret_name, _se)
        # Phase 2.6 — manually-rotated secrets (Anthropic + 3rd-party API tokens)
        for secret_name in MANUAL_ROTATION_SECRETS:
            try:
                meta = sm.describe_secret(SecretId=secret_name)
                last_changed = meta.get("LastChangedDate")
                if last_changed:
                    age_days = (now - last_changed.replace(tzinfo=timezone.utc)).days
                    if age_days > MANUAL_ROTATION_STALE_DAYS:
                        manual_stale.append((secret_name, age_days))
                        logger.warning(
                            "Manual-rotation secret stale: %s last rotated %d days ago",
                            secret_name,
                            age_days,
                        )
            except Exception as _se:
                logger.warning("Could not check manual secret %s: %s", secret_name, _se)

        if oauth_stale:
            stale_list = "\n".join([f"  - {name}: {days} days since last update" for name, days in oauth_stale])
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

        # Phase 2.6: manual-rotation staleness alert (separate from OAuth)
        if manual_stale:
            stale_list = "\n".join([f"  - {name}: {days} days since last rotation" for name, days in manual_stale])
            try:
                sns.publish(
                    TopicArn=SNS_ARN,
                    Subject=f"⚠️ Life Platform: {len(manual_stale)} secret(s) due for manual rotation",
                    Message=(
                        f"⚠️ Life Platform: Manual Rotation Reminder\n\n"
                        f"The following secrets have not been rotated in over {MANUAL_ROTATION_STALE_DAYS} days.\n"
                        f"These are manually-rotated (no auto-rotation API available):\n\n"
                        f"{stale_list}\n\n"
                        f"Action: rotate via the source provider's portal, then update via\n"
                        f"`aws secretsmanager put-secret-value --secret-id <name> --secret-string ...`\n\n"
                        f"See docs/SECRETS_ROTATION.md for per-secret procedures.\n\n"
                        f"Checked at: {now.strftime('%Y-%m-%d %H:%M UTC')}"
                    ),
                )
                logger.info("Manual rotation alert sent for %d secret(s)", len(manual_stale))
            except Exception as _sns_e:
                logger.error("Manual rotation alert SNS publish failed: %s", _sns_e)

        # Emit CloudWatch metric for OAuth + manual-rotation token staleness
        cw.put_metric_data(
            Namespace="LifePlatform/Freshness",
            MetricData=[
                {"MetricName": "OAuthTokenStaleCount", "Value": float(len(oauth_stale)), "Unit": "Count"},
                {"MetricName": "ManualRotationStaleCount", "Value": float(len(manual_stale)), "Unit": "Count"},
            ],
        )

    except Exception as _oauth_e:
        logger.error("OAuth/manual token health check failed (non-fatal): %s", _oauth_e)

    return {
        "statusCode": 200,
        "stale_count": len(stale_sources),
        "stale_sources": [s[0] for s in stale_sources],
        "partial_count": len(partial_sources),
        "partial_sources": [s[0] for s in partial_sources],
        "warning_count": len(warning_sources),
        "warning_sources": [s[0] for s in warning_sources],
        "checked_at": now.isoformat(),
    }
