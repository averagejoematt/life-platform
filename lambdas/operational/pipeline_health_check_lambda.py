"""
Pipeline Health Check Lambda — active probe of all ingestion pipelines + Phase 3.2
compute-output freshness check.

Two modes (selected by event):
  - default ({}):  invokes each Lambda with {"healthcheck":true} and checks it
                   doesn't crash. Catches dead secrets, expired tokens, missing
                   modules, auth failures. Schedule: 13:00 UTC daily (6 AM PT,
                   before morning ingestion crons).
  - {"check_compute_outputs": true}: queries DDB to verify today's compute
                   records exist (character_sheet, computed_metrics, daily_insight,
                   adaptive_mode). Phase 3.2 addition. Schedule: 16:58 UTC daily
                   (9:58 AM PT, after compute cascade completes by 9:55 PT,
                   before daily-brief at 10:00 PT). Emits metric + warning if any
                   today-record is missing so the brief reads stale data silently.

Writes results to DynamoDB for status page consumption.
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3

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

# ── ER-01 infra-liveness ──────────────────────────────────────────────────────
# Active OAuth/API *pull* sources that should run at least once per day. These are
# the sources whose silent auth-rot / de-scheduling is the 44-day-outage class.
# Webhook/push sources (apple_health/CGM, hevy) are excluded — they have no cron to
# go stale, so the attempt-staleness arm doesn't apply to them.
ACTIVE_API_SOURCES = [
    "whoop",
    "withings",
    "garmin",
    "strava",
    "eightsleep",
    "habitify",
    "todoist",
    "notion",
    "weather",
    "dropbox",
]

# Best-effort sources: known-brittle by an accepted, unfixable upstream cause. They are
# still EVALUATED and logged for visibility, but excluded from UnhealthySourceCount so a
# permanent expected failure can't keep `ingest-liveness-unhealthy` red or mask a real
# source death. Garmin (2026-06-19): datacenter-IP 429 defeats server-side OAuth refresh;
# sleep/HRV/recovery are covered by Whoop + Eight Sleep. Remove from here if it stabilizes.
BEST_EFFORT_SOURCES = {"garmin"}

# Per-source attempt-gap overrides (minutes). Unlisted sources use the default in
# ingest_health (~26h). Garmin runs only 4x/day but still attempts daily, so the
# default holds; this map exists for future sources with sparser-than-daily cadence.
SOURCE_MAX_GAP_MINUTES = {}

try:
    from ingest_health import SYSTEM_PK, evaluate_source_health

    _INGEST_HEALTH_AVAILABLE = True
except ImportError:  # pragma: no cover - layer-module fallback
    _INGEST_HEALTH_AVAILABLE = False

# DI-1.1: source-state legibility. A deliberately-paused source's healthcheck "ok"
# must NOT be reported as healthy (that masks a missing cron) nor alarmed as broken.
try:
    from source_state import is_paused

    _SOURCE_STATE_AVAILABLE = True
except ImportError:  # pragma: no cover - layer not yet rebuilt → old behaviour

    def is_paused(_source):
        return False

    _SOURCE_STATE_AVAILABLE = False


def _probe_lambda(fn_name: str) -> dict:
    """Invoke a Lambda and check if it crashes. Returns result dict."""
    try:
        resp = lambda_client.invoke(
            FunctionName=fn_name,
            InvocationType="RequestResponse",
            Payload=b'{"healthcheck": true}',
        )
        resp.get("StatusCode", 0)
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


def _check_compute_outputs(today_str: str) -> dict:
    """Phase 3.2: Verify the compute cascade wrote its expected records.

    Returns: {missing: [...source_ids...], present: [...], all_present: bool}.

    Designed to run at 9:58 AM PT (after compute cascade 9:30-9:55 PT completes).
    If any expected partition is missing its expected-date record, daily-brief
    will read older data silently. Flag it loudly here.

    Each compute Lambda writes for a different reference date — most write
    YESTERDAY's record (computing metrics for the completed day) but some
    write TODAY (e.g., adaptive_mode sets today's mode). The EXPECTED list
    encodes this per-partition.
    """
    from datetime import timedelta as _td

    yesterday_str = (datetime.strptime(today_str, "%Y-%m-%d") - _td(days=1)).strftime("%Y-%m-%d")

    EXPECTED = [
        # (partition_source_id, display_name, expected_date)
        ("character_sheet", "Character Sheet", yesterday_str),
        ("computed_metrics", "Daily Metrics", yesterday_str),
        ("computed_insights", "Daily Insights", yesterday_str),
        ("adaptive_mode", "Adaptive Mode", yesterday_str),
    ]
    missing, present = [], []
    for source_id, display, expected_date in EXPECTED:
        pk = f"USER#{USER_ID}#SOURCE#{source_id}"
        sk = f"DATE#{expected_date}"
        try:
            resp = table.get_item(Key={"pk": pk, "sk": sk}, ProjectionExpression="sk")
            if resp.get("Item"):
                present.append(source_id)
            else:
                missing.append({"source_id": source_id, "display": display, "pk": pk, "sk": sk, "expected_date": expected_date})
        except Exception as e:
            missing.append({"source_id": source_id, "display": display, "error": str(e)[:120]})

    # Emit CloudWatch metric so we can graph this over time
    try:
        cw = boto3.client("cloudwatch", region_name=REGION)
        cw.put_metric_data(
            Namespace="LifePlatform/Pipeline",
            MetricData=[
                {
                    "MetricName": "ComputeOutputsMissing",
                    "Value": float(len(missing)),
                    "Unit": "Count",
                }
            ],
        )
    except Exception as e:
        logger.warning(f"compute_outputs metric emit failed: {e}")

    return {"missing": missing, "present": present, "all_present": not missing}


def _check_ingest_liveness(now: datetime) -> dict:
    """ER-01: read the INGEST_HEALTH sentinels and assert per-source infra-liveness.

    Distinct from behavioral freshness: this fires when an ingestion Lambda has been
    running-but-erroring (failure streak) or has stopped running entirely (attempt
    staleness) — independent of whether the user logged any new data. Emits
    UnhealthySourceCount to LifePlatform/IngestLiveness and pushes a distinct-subject
    digest alert when any source is unhealthy.
    """
    if not _INGEST_HEALTH_AVAILABLE:
        logger.warning("ingest_liveness: ingest_health module unavailable (layer not rebuilt?) — skipping")
        return {"skipped": "ingest_health_unavailable"}

    # Pull every sentinel under the USER#system partition in one query.
    sentinels = {}
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
            ExpressionAttributeValues={":pk": SYSTEM_PK, ":pfx": "INGEST_HEALTH#"},
        )
        for item in resp.get("Items", []):
            src = item.get("source") or item.get("sk", "").replace("INGEST_HEALTH#", "")
            sentinels[src] = item
    except Exception as e:
        logger.error(f"ingest_liveness: sentinel query failed: {e}")
        return {"error": str(e)}

    verdicts = []
    for source in ACTIVE_API_SOURCES:
        verdict = evaluate_source_health(
            sentinels.get(source),
            now=now,
            max_gap_minutes=SOURCE_MAX_GAP_MINUTES.get(source, 1560),
            source=source,
        )
        verdicts.append(verdict)
        if verdict["alert"]:
            logger.warning(f"INGEST UNHEALTHY: {source} — {verdict['status']}: {verdict['reason']}")

    # Best-effort sources (e.g. Garmin) are logged above but excluded from the count/alert
    # so an accepted, unfixable upstream failure can't mask a real source death. DI-1.1:
    # declared-paused sources (Strava, off-by-design) are likewise excluded — a paused
    # source has no cron to be "stopped", so the attempt-staleness arm would false-fire.
    for v in verdicts:
        v["paused"] = is_paused(v["source"])
    alerting = [v for v in verdicts if v["alert"] and v["source"] not in BEST_EFFORT_SOURCES and not v["paused"]]
    unhealthy_count = len(alerting)

    # Emit the metric the ingest-liveness alarm watches.
    try:
        cw = boto3.client("cloudwatch", region_name=REGION)
        cw.put_metric_data(
            Namespace="LifePlatform/IngestLiveness",
            MetricData=[{"MetricName": "UnhealthySourceCount", "Value": unhealthy_count, "Unit": "Count"}],
        )
    except Exception as e:
        logger.warning(f"ingest_liveness metric emit failed: {e}")

    # Distinct-subject digest alert so a failing source is unmissable (no pager).
    if alerting:
        lines = [f"• {v['source']}: {v['status'].upper()} — {v['reason']} (last_error={v['last_error_class']})" for v in alerting]
        msg = (
            f"🔌 Ingestion infra-liveness: {unhealthy_count} source(s) unhealthy "
            f"(running-but-erroring or stopped running):\n\n"
            + "\n".join(lines)
            + "\n\nThis is infra-liveness, NOT data-freshness — these sources are failing "
            "their upstream fetch regardless of whether new data was expected."
        )
        try:
            sns = boto3.client("sns", region_name=REGION)
            digest_arn = os.environ.get("DIGEST_SNS_ARN", f"arn:aws:sns:{REGION}:205930651321:life-platform-alerts-digest")
            sns.publish(TopicArn=digest_arn, Subject=f"⚠️ Ingest-liveness: {unhealthy_count} source(s) failing", Message=msg)
        except Exception as e:
            logger.warning(f"ingest_liveness SNS publish failed: {e}")

    # Persist for the status page.
    try:
        table.put_item(
            Item={
                "pk": f"USER#{USER_ID}#SOURCE#ingest_liveness",
                "sk": f"DATE#{now.strftime('%Y-%m-%d')}",
                "date": now.strftime("%Y-%m-%d"),
                "checked_at": now.isoformat(),
                "unhealthy_count": unhealthy_count,
                "verdicts": json.dumps(verdicts, default=str),
            }
        )
    except Exception as e:
        logger.warning(f"ingest_liveness store failed: {e}")

    logger.info(f"ingest_liveness: {unhealthy_count} unhealthy of {len(ACTIVE_API_SOURCES)} active sources")
    return {"unhealthy_count": unhealthy_count, "verdicts": verdicts}


def lambda_handler(event: dict, context) -> dict:  # Phase 4.12 type hints
    if hasattr(logger, "set_date"):
        logger.set_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")

    # ER-01: infra-liveness mode — assert each active source's ingestion Lambda ran
    # and 200'd, independent of whether new data came back.
    if event.get("check_ingest_liveness"):
        return {"statusCode": 200, "body": json.dumps(_check_ingest_liveness(now), default=str)}

    # Phase 3.2: compute-output verification mode
    if event.get("check_compute_outputs"):
        result = _check_compute_outputs(today_str)
        if result["missing"]:
            missing_names = [m.get("display", m.get("source_id")) for m in result["missing"]]
            msg = (
                f"⚠️ Compute pipeline incomplete for {today_str}: "
                f"missing {len(result['missing'])} record(s) — {', '.join(missing_names)}. "
                f"Daily-brief will read yesterday's data for these."
            )
            logger.warning(msg)
            # Publish to digest SNS so it lands in tomorrow's 8 AM digest.
            try:
                sns = boto3.client("sns", region_name=REGION)
                digest_arn = os.environ.get(
                    "DIGEST_SNS_ARN",
                    f"arn:aws:sns:{REGION}:205930651321:life-platform-alerts-digest",
                )
                sns.publish(
                    TopicArn=digest_arn,
                    Subject=f"Compute pipeline incomplete {today_str}",
                    Message=msg,
                )
            except Exception as e:
                logger.warning(f"compute_outputs SNS publish failed: {e}")
        else:
            logger.info(f"compute_outputs all present for {today_str}")
        return {"statusCode": 200, "body": json.dumps(result)}

    # Default mode: probe Lambdas + check secrets
    results = []
    pass_count = 0
    fail_count = 0

    # Run probes in parallel (was sequential — caused 480s+ worst case)
    from concurrent.futures import ThreadPoolExecutor, as_completed

    paused_count = 0

    def _run_probe(pipeline):
        fn_name, display_name, source_id = pipeline
        # DI-1.1: a paused source has no live cron — a healthcheck "ok" would only prove
        # the Lambda boots, masking that ingestion is off-by-design. Skip the probe and
        # report it as `paused` (neither healthy-green nor failed-red).
        if is_paused(source_id):
            logger.info(f"{display_name} ({source_id}) is paused (off-by-design) — skipping boot probe")
            return {
                "function_name": fn_name,
                "display_name": display_name,
                "source_id": source_id,
                "healthy": True,
                "paused": True,
                "state": "paused",
                "note": "deliberately paused (no cron); boot-probe skipped — not 'healthy', not 'failed'",
            }
        logger.info(f"Probing {display_name} ({fn_name})...")
        result = _probe_lambda(fn_name)
        result["function_name"] = fn_name
        result["display_name"] = display_name
        result["source_id"] = source_id
        return result

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_run_probe, p): p for p in PIPELINES}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if result.get("paused"):
                paused_count += 1
            elif result["healthy"]:
                pass_count += 1
            else:
                fail_count += 1
                logger.warning(f"FAIL: {result['display_name']} — {result.get('error_type')}: {result.get('error_message')}")

    # Secret health check — detect deleted/missing secrets
    sm = boto3.client("secretsmanager", region_name=REGION)
    REQUIRED_SECRETS = [
        "life-platform/whoop",
        "life-platform/withings",
        "life-platform/strava",
        "life-platform/eightsleep",
        "life-platform/garmin",
        "life-platform/habitify",
        "life-platform/notion",
        "life-platform/dropbox",
        "life-platform/ai-keys",
        "life-platform/site-api-ai-key",
        "life-platform/ingestion-keys",
    ]
    for secret_name in REQUIRED_SECRETS:
        try:
            desc = sm.describe_secret(SecretId=secret_name)
            if desc.get("DeletedDate"):
                fail_count += 1
                results.append(
                    {
                        "function_name": f"secret:{secret_name}",
                        "display_name": f"Secret: {secret_name}",
                        "source_id": secret_name.replace("life-platform/", ""),
                        "healthy": False,
                        "error_type": "SecretDeleted",
                        "error_message": f"Secret {secret_name} is scheduled for deletion",
                    }
                )
                logger.warning(f"SECRET DELETED: {secret_name}")
        except Exception as e:
            if "ResourceNotFoundException" in str(e):
                fail_count += 1
                results.append(
                    {
                        "function_name": f"secret:{secret_name}",
                        "display_name": f"Secret: {secret_name}",
                        "source_id": secret_name.replace("life-platform/", ""),
                        "healthy": False,
                        "error_type": "SecretMissing",
                        "error_message": f"Secret {secret_name} does not exist",
                    }
                )
                logger.warning(f"SECRET MISSING: {secret_name}")

    # Write results to DynamoDB
    try:
        table.put_item(
            Item={
                "pk": f"USER#{USER_ID}#SOURCE#health_check",
                "sk": f"DATE#{now.strftime('%Y-%m-%d')}",
                "date": now.strftime("%Y-%m-%d"),
                "checked_at": now.isoformat(),
                "total": len(PIPELINES),
                "passed": pass_count,
                "failed": fail_count,
                "paused": paused_count,
                "results": json.dumps(results),
                "failures": json.dumps([r for r in results if not r.get("paused") and not r["healthy"]]),
            }
        )
        logger.info(f"Health check stored: {pass_count} pass, {fail_count} fail, {paused_count} paused")
    except Exception as e:
        logger.error(f"Failed to store health check: {e}")

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "passed": pass_count,
                "failed": fail_count,
                "paused": paused_count,
                "total": len(PIPELINES),
                "failures": [
                    {"name": r["display_name"], "error": r.get("error_message", "")}
                    for r in results
                    if not r.get("paused") and not r["healthy"]
                ],
            }
        ),
    }
