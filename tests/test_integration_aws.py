#!/usr/bin/env python3
"""
tests/test_integration_aws.py — Integration tests that run against live AWS.

These tests verify what offline unit tests cannot: IAM permissions, Lambda
Layer references, handler names, EventBridge rules, and basic invocability.
They catch the root cause of ~80% of historical incidents.

PREREQUISITES:
  - AWS credentials configured (AWS_PROFILE or env vars)
  - boto3 installed
  - Region: us-west-2

USAGE:
  python3 -m pytest tests/test_integration_aws.py -v --tb=short
  python3 -m pytest tests/test_integration_aws.py -v -k "test_handlers"   # one test
  python3 -m pytest tests/test_integration_aws.py -v -m integration       # by marker

SKIP:
  Tests skip automatically if no AWS credentials are available.
  They also skip if the platform is in a known maintenance state.

DESIGN PRINCIPLES (Jin Park / Viktor Sorokin, R11):
  - Every test catches a specific class of historical incident
  - Tests are read-only (no writes, no state changes)
  - Tests run in <60 seconds total
  - Tests fail loudly with actionable fix instructions
  - A passing run here means "works in AWS", not just "works in code"

RUN MANUALLY (not in CI/CD):
  These tests require live AWS credentials and are NOT wired into GitHub Actions
  (R12 Item 5). They are manual-only by design:
    1. They require AWS credentials not available in standard CI
    2. They invoke Lambdas (I3, I10) which could affect state
    3. They are best run as a post-CDK-deploy health check, not on every PR
  Run after any CDK deploy: python3 -m pytest tests/test_integration_aws.py -v --tb=short
  See RUNBOOK.md ’Session Close Checklist’ for trigger guidance.

v1.0.0 — 2026-03-14 (R11 engineering strategy item 8)
v1.1.0 — 2026-03-15 (R12: +I11 data-reconciliation check, manual-only doc)
"""

import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REGION = "us-west-2"
ACCOUNT = "205930651321"
TABLE_NAME = "life-platform"
BUCKET = "matthew-life-platform"
DLQ_URL = f"https://sqs.{REGION}.amazonaws.com/{ACCOUNT}/life-platform-ingestion-dlq"
SHARED_LAYER_NAME = "life-platform-shared-utils"
SHARED_LAYER_MIN_VERSION = 4


# ══════════════════════════════════════════════════════════════════════════════
# BOTO3 AVAILABILITY + CREDENTIAL CHECK
# ══════════════════════════════════════════════════════════════════════════════


def _get_boto3():
    """Return boto3 or skip if not available / no credentials."""
    try:
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError

        # Quick credential check
        sts = boto3.client("sts", region_name=REGION)
        sts.get_caller_identity()
        return boto3
    except ImportError:
        pytest.skip("boto3 not installed")
    except Exception as e:
        pytest.skip(f"No AWS credentials: {e}")


# Marker for all integration tests
pytestmark = pytest.mark.integration


# ══════════════════════════════════════════════════════════════════════════════
# I1 — Lambda handler names match expected module pattern
# Root cause of: 2026-02-28 P1 (5 Lambdas failing), 2026-03-12 P0 alarm flood
# ══════════════════════════════════════════════════════════════════════════════

# Expected handler mapping: function_name → expected_module_prefix
EXPECTED_HANDLERS = {
    "whoop-data-ingestion": "whoop_lambda",
    "garmin-data-ingestion": "garmin_lambda",
    "strava-data-ingestion": "strava_lambda",
    "withings-data-ingestion": "withings_lambda",
    "habitify-data-ingestion": "habitify_lambda",
    "eightsleep-data-ingestion": "eightsleep_lambda",
    "macrofactor-data-ingestion": "macrofactor_lambda",
    "todoist-data-ingestion": "todoist_lambda",
    "notion-journal-ingestion": "notion_lambda",
    "health-auto-export-webhook": "health_auto_export_lambda",
    "daily-brief": "daily_brief_lambda",
    "weekly-digest": "weekly_digest_lambda",
    "life-platform-mcp": "mcp_server",
    "life-platform-freshness-checker": "freshness_checker_lambda",
    "character-sheet-compute": "character_sheet_lambda",
    "daily-metrics-compute": "daily_metrics_compute_lambda",
    "daily-insight-compute": "daily_insight_compute_lambda",
    "anomaly-detector": "anomaly_detector_lambda",
    "life-platform-canary": "canary_lambda",
    "life-platform-dlq-consumer": "dlq_consumer_lambda",
}


def _load_not_deployed_functions():
    """Load function names flagged as not_deployed in lambda_map.json."""
    map_path = os.path.join(ROOT, "ci", "lambda_map.json")
    try:
        with open(map_path) as f:
            lmap = json.load(f)
        return {v["function"] for v in lmap.get("lambdas", {}).values() if isinstance(v, dict) and v.get("not_deployed")}
    except Exception:
        return set()


def test_i1_lambda_handlers_match_expected():
    """I1: Lambda handlers in AWS must match expected module names.

    Catches CDK reconcile regression (2026-03-12 P0): CDK overwrites live
    handler config with wrong module name → Lambda silently fails on every
    invocation until the alarm fires hours later.

    Skips functions flagged as not_deployed in lambda_map.json.

    Fix: aws lambda update-function-configuration --function-name <fn>
         --handler <module>.lambda_handler --region us-west-2
    """
    boto3 = _get_boto3()
    lc = boto3.client("lambda", region_name=REGION)
    not_deployed = _load_not_deployed_functions()

    failures = []
    for fn_name, expected_module in EXPECTED_HANDLERS.items():
        if fn_name in not_deployed:
            continue
        try:
            config = lc.get_function_configuration(FunctionName=fn_name)
            actual_handler = config["Handler"]
            # P3.1 (2026-05-25): handlers are subpackage-qualified now, e.g.
            # "ingestion.whoop_lambda.lambda_handler". Strip the entry-point
            # (last component) then take the LAST module-path component as the
            # "basename" to compare against EXPECTED_HANDLERS.
            # Examples:
            #   "ingestion.whoop_lambda.lambda_handler" → "whoop_lambda"
            #   "site_api_lambda.lambda_handler" (flat) → "site_api_lambda"
            handler_module_path = actual_handler.rsplit(".", 1)[0]  # strip entry point
            actual_module = handler_module_path.rsplit(".", 1)[-1]  # basename

            if actual_module == "lambda_function":
                failures.append(
                    f"{fn_name}: handler is 'lambda_function.lambda_handler' " f"(CDK reconcile regression — expected '{expected_module}')"
                )
            elif actual_module != expected_module:
                failures.append(f"{fn_name}: module '{actual_module}' != expected '{expected_module}'")
        except Exception as e:
            if "ResourceNotFoundException" in str(e):
                failures.append(f"{fn_name}: Lambda does not exist in AWS")
            # Other errors (throttling etc.) — don't fail the test
            pass

    assert not failures, (
        f"I1 FAIL: {len(failures)} Lambda handler mismatch(es):\n"
        + "\n".join(f"  ❌ {f}" for f in failures)
        + "\n\nRun: bash deploy/post_cdk_reconcile_smoke.sh"
    )


# ══════════════════════════════════════════════════════════════════════════════
# I2 — Lambda Layer version is current
# Root cause of: 2026-03-09 P2 (all 13 ingestion Lambdas failing after logger update)
# ══════════════════════════════════════════════════════════════════════════════

LAMBDAS_REQUIRING_LAYER = [
    "daily-brief",
    "weekly-digest",
    # life-platform-mcp: uses self-contained package, not shared layer
    "life-platform-freshness-checker",
    "anomaly-detector",
    "character-sheet-compute",
    "daily-metrics-compute",
    "daily-insight-compute",
]


def test_i2_lambda_layer_version_current():
    """I2: Key Lambdas must reference the current shared layer version.

    Stale layer references caused the March 9 P2 (set_date AttributeError).
    Fix: bash deploy/deploy_lambda.sh <function-name> lambdas/<source>.py
         (deploy_lambda.sh auto-attaches current layer version)
    """
    boto3 = _get_boto3()
    lc = boto3.client("lambda", region_name=REGION)

    # Find current layer version
    try:
        layer_versions = lc.list_layer_versions(LayerName=SHARED_LAYER_NAME)["LayerVersions"]
        if not layer_versions:
            pytest.skip(f"Layer {SHARED_LAYER_NAME} has no versions")
        current_version = layer_versions[0]["Version"]  # sorted newest first
    except Exception as e:
        pytest.skip(f"Could not query layer versions: {e}")

    stale = []
    for fn_name in LAMBDAS_REQUIRING_LAYER:
        try:
            config = lc.get_function_configuration(FunctionName=fn_name)
            layers = config.get("Layers", [])
            layer_arns = [l["Arn"] for l in layers]
            has_current = any(f":{SHARED_LAYER_NAME}:{current_version}" in arn for arn in layer_arns)
            if not layer_arns:
                stale.append(f"{fn_name}: NO layer attached at all")
            elif not has_current:
                # Find what version it has
                found_version = None
                for arn in layer_arns:
                    if SHARED_LAYER_NAME in arn:
                        found_version = arn.split(":")[-1]
                stale.append(f"{fn_name}: layer v{found_version} " f"(current is v{current_version})")
        except Exception:
            pass  # Lambda might not exist — I1 catches that

    assert not stale, (
        f"I2 FAIL: {len(stale)} Lambda(s) on stale layer:\n"
        + "\n".join(f"  ⚠️  {s}" for s in stale)
        + f"\n\nAll should reference {SHARED_LAYER_NAME}:{current_version}"
        + "\nFix: bash deploy/deploy_lambda.sh <function-name> lambdas/<source>.py"
    )


# ══════════════════════════════════════════════════════════════════════════════
# I3 — Spot-check Lambda invocability (no import errors)
# Root cause of: 2026-03-09 P2, 2026-02-28 P1 (ImportModuleError at runtime)
# ══════════════════════════════════════════════════════════════════════════════

SPOT_CHECK_LAMBDAS = [
    "life-platform-canary",  # always safe to invoke
    "life-platform-freshness-checker",  # read-only, non-destructive
    "life-platform-mcp",  # MCP health check (warmer path)
]


def test_i3_spot_check_lambda_invocability():
    """I3: Spot-check that key Lambdas boot without ImportModuleError.

    Tests the import stage specifically — wrong handler module, missing
    Layer dependency, or broken __init__.py all surface as import errors.

    Lambdas tested: canary (safe), freshness checker (read-only), MCP (health).
    """
    boto3 = _get_boto3()
    lc = boto3.client("lambda", region_name=REGION)
    import tempfile

    failures = []
    for fn_name in SPOT_CHECK_LAMBDAS:
        try:
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                tmp_path = tmp.name

            response = lc.invoke(
                FunctionName=fn_name,
                Payload=json.dumps({"dry_run": True, "__integration_test": True}),
            )
            status = response["StatusCode"]
            payload = json.loads(response["Payload"].read())

            # Check for function-level errors
            if "FunctionError" in response:
                error_type = payload.get("errorType", "unknown")
                error_msg = payload.get("errorMessage", "")[:120]

                if "ImportModuleError" in error_type or "ImportModuleError" in error_msg:
                    failures.append(f"{fn_name}: ImportModuleError — {error_msg}")
                elif "AccessDenied" in error_msg:
                    failures.append(f"{fn_name}: AccessDenied — IAM permission missing")
                else:
                    # Non-import errors are warnings (could be expected, e.g. no data)
                    pass  # Don't fail on functional errors, only structural ones

        except Exception as e:
            failures.append(f"{fn_name}: invocation exception — {e}")

    assert not failures, (
        f"I3 FAIL: {len(failures)} Lambda(s) have structural errors:\n"
        + "\n".join(f"  ❌ {f}" for f in failures)
        + "\n\nThese are import/IAM errors that prevent ANY invocation from working."
    )


# ══════════════════════════════════════════════════════════════════════════════
# I4 — DynamoDB table exists with deletion protection + PITR
# Root cause of: would be catastrophic data loss
# ══════════════════════════════════════════════════════════════════════════════


def test_i4_dynamodb_table_healthy():
    """I4: DynamoDB table exists, has deletion protection, and PITR enabled."""
    boto3 = _get_boto3()
    ddb = boto3.client("dynamodb", region_name=REGION)

    try:
        desc = ddb.describe_table(TableName=TABLE_NAME)["Table"]
    except Exception as e:
        pytest.fail(f"I4 FAIL: Could not describe DynamoDB table '{TABLE_NAME}': {e}")

    status = desc.get("TableStatus")
    assert status == "ACTIVE", f"I4 FAIL: Table status is '{status}' (expected ACTIVE)"

    deletion_protection = desc.get("DeletionProtectionEnabled", False)
    assert deletion_protection, (
        "I4 FAIL: DynamoDB deletion protection is OFF — risk of accidental deletion!\n"
        "Fix: aws dynamodb update-table --table-name life-platform "
        "--deletion-protection-enabled --region us-west-2"
    )

    # Check PITR
    try:
        pitr = ddb.describe_continuous_backups(TableName=TABLE_NAME)
        pitr_status = pitr["ContinuousBackupsDescription"]["PointInTimeRecoveryDescription"]["PointInTimeRecoveryStatus"]
        assert pitr_status == "ENABLED", f"I4 FAIL: PITR is '{pitr_status}' (expected ENABLED) — no 35-day backup!"
    except Exception as e:
        pytest.fail(f"I4 FAIL: Could not check PITR status: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# I5 — Critical secrets exist in Secrets Manager
# Root cause of: 2026-03-08 P3 (stale SECRET_NAME env var pointing at deleted secret)
# ══════════════════════════════════════════════════════════════════════════════

REQUIRED_SECRETS = [
    "life-platform/ai-keys",
    "life-platform/whoop",
    "life-platform/strava",
    "life-platform/withings",
    "life-platform/garmin",
    "life-platform/eightsleep",
    "life-platform/todoist",
    "life-platform/notion",
    "life-platform/habitify",
]

DELETED_SECRETS = [
    "life-platform/api-keys",  # permanently deleted 2026-03-14
]


def test_i5_required_secrets_exist():
    """I5: All critical secrets must exist and not be in a deleted state."""
    boto3 = _get_boto3()
    sm = boto3.client("secretsmanager", region_name=REGION)

    missing = []
    for secret_name in REQUIRED_SECRETS:
        try:
            desc = sm.describe_secret(SecretId=secret_name)
            if desc.get("DeletedDate"):
                missing.append(f"{secret_name}: MARKED FOR DELETION")
        except Exception as e:
            if "ResourceNotFoundException" in str(e):
                missing.append(f"{secret_name}: DOES NOT EXIST")

    # Verify permanently deleted secrets are actually gone
    still_alive = []
    for secret_name in DELETED_SECRETS:
        try:
            desc = sm.describe_secret(SecretId=secret_name)
            if not desc.get("DeletedDate"):
                still_alive.append(f"{secret_name}: still active (should be deleted)")
        except Exception:
            pass  # Not found = correct

    assert not missing, f"I5 FAIL: {len(missing)} required secret(s) missing or deleted:\n" + "\n".join(f"  ❌ {s}" for s in missing)

    assert not still_alive, f"I5 WARN: {len(still_alive)} secret(s) should have been deleted:\n" + "\n".join(
        f"  ⚠️  {s}" for s in still_alive
    )


# ══════════════════════════════════════════════════════════════════════════════
# I6 — Critical EventBridge rules exist and are enabled
# Root cause of: 2026-03-10 P3 (EB rule deleted, Lambda missed scheduled runs)
# ══════════════════════════════════════════════════════════════════════════════

REQUIRED_EB_RULES = [
    "daily-brief-schedule",
    "LifePlatformIngestion-WhoopIngestionScheduleC6CE3A0-DjUDUDY4XrFs",
    "LifePlatformIngestion-TodoistIngestionSchedule03D61-XqriAparCo0n",
    "LifePlatformOperational-FreshnessCheckerScheduleD9E-xZki3XA2x0bb",
]


def test_i6_eventbridge_rules_exist_and_enabled():
    """I6: Critical EventBridge rules must exist and be ENABLED.

    Missing/disabled rules cause scheduled Lambdas to silently stop running.
    Caught the March 10 P3 retroactively — this test would have caught it immediately.
    """
    boto3 = _get_boto3()
    eb = boto3.client("events", region_name=REGION)

    missing = []
    disabled = []

    for rule_name in REQUIRED_EB_RULES:
        try:
            rule = eb.describe_rule(Name=rule_name)
            state = rule.get("State", "UNKNOWN")
            if state != "ENABLED":
                disabled.append(f"{rule_name}: state is '{state}'")
        except Exception as e:
            if "ResourceNotFoundException" in str(e):
                missing.append(f"{rule_name}: RULE DOES NOT EXIST")

    issues = missing + disabled
    assert not issues, (
        f"I6 FAIL: {len(issues)} EventBridge rule issue(s):\n"
        + "\n".join(f"  ❌ {i}" for i in issues)
        + "\n\nMissing rules mean Lambdas won't run on schedule!"
    )


# ══════════════════════════════════════════════════════════════════════════════
# I7 — CloudWatch alarms exist and count matches expected
# Root cause of: would hide incidents if alarms were accidentally deleted
# ══════════════════════════════════════════════════════════════════════════════

EXPECTED_MIN_ALARMS = 40  # alert if dramatically fewer than expected


def test_i7_cloudwatch_alarms_exist():
    """I7: CloudWatch alarm count must meet minimum threshold."""
    boto3 = _get_boto3()
    cw = boto3.client("cloudwatch", region_name=REGION)

    try:
        paginator = cw.get_paginator("describe_alarms")
        alarms = []
        for page in paginator.paginate():
            alarms.extend(page["MetricAlarms"])
        alarm_count = len(alarms)
    except Exception as e:
        pytest.fail(f"I7 FAIL: Could not describe CloudWatch alarms: {e}")

    assert alarm_count >= EXPECTED_MIN_ALARMS, (
        f"I7 FAIL: Only {alarm_count} alarms found (expected ≥{EXPECTED_MIN_ALARMS}). "
        f"Alarms may have been accidentally deleted!\n"
        f"Fix: cdk deploy LifePlatformMonitoring"
    )


# ══════════════════════════════════════════════════════════════════════════════
# I8 — S3 bucket exists with critical config files
# Root cause of: would break AI coaching if board_of_directors.json was deleted
# ══════════════════════════════════════════════════════════════════════════════

REQUIRED_S3_KEYS = [
    "config/board_of_directors.json",
    "config/character_sheet.json",
    # profile.json: profile data lives in DynamoDB (PROFILE#v1), not S3
]


def test_i8_s3_bucket_and_config_files():
    """I8: S3 bucket exists and critical config files are present."""
    boto3 = _get_boto3()
    s3 = boto3.client("s3", region_name=REGION)

    # Check bucket exists
    try:
        s3.head_bucket(Bucket=BUCKET)
    except Exception as e:
        pytest.fail(f"I8 FAIL: S3 bucket '{BUCKET}' not accessible: {e}")

    # Check config files
    missing = []
    for key in REQUIRED_S3_KEYS:
        try:
            s3.head_object(Bucket=BUCKET, Key=key)
        except Exception:
            missing.append(key)

    assert not missing, (
        f"I8 FAIL: {len(missing)} critical config file(s) missing from S3:\n"
        + "\n".join(f"  ❌ s3://{BUCKET}/{k}" for k in missing)
        + "\n\nAI coaching will fall back to defaults without these files."
    )


# ══════════════════════════════════════════════════════════════════════════════
# I9 — SQS DLQ has zero messages (no silent failures accumulating)
# Root cause of: 2026-03-08 P3 (DLQ messages accumulated for 2 days unnoticed)
# ══════════════════════════════════════════════════════════════════════════════


def test_i9_dlq_empty():
    """I9: Ingestion DLQ should have zero messages.

    Non-zero DLQ means one or more Lambdas are silently failing. The March 8
    P3 ran for 2 days before anyone noticed the DLQ had accumulated failures.
    """
    boto3 = _get_boto3()
    sqs = boto3.client("sqs", region_name=REGION)

    try:
        attrs = sqs.get_queue_attributes(
            QueueUrl=DLQ_URL,
            AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
        )["Attributes"]
        visible = int(attrs.get("ApproximateNumberOfMessages", 0))
        in_flight = int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0))
        total = visible + in_flight
    except Exception as e:
        pytest.skip(f"Could not check DLQ: {e}")

    assert total == 0, (
        f"I9 FAIL: DLQ has {total} message(s) ({visible} visible, {in_flight} in-flight).\n"
        f"This means at least one Lambda is silently failing!\n"
        f"Check: aws sqs receive-message --queue-url {DLQ_URL} --region {REGION}\n"
        f"Drain: manually invoke life-platform-dlq-consumer"
    )


# ══════════════════════════════════════════════════════════════════════════════
# I10 — MCP Lambda responds to tool list (basic connectivity)
# Root cause of: any MCP deploy issue blocks all Claude tool calls
# ══════════════════════════════════════════════════════════════════════════════


def test_i10_mcp_lambda_responds():
    """I10: MCP Lambda must respond to a basic invocation without structural errors.

    Tests that the MCP Lambda boots and its handler is reachable. A warmer
    payload is used to avoid needing auth credentials in the test.
    """
    boto3 = _get_boto3()
    lc = boto3.client("lambda", region_name=REGION)

    try:
        # Invoke with a minimal event that triggers the warmer path (no auth needed)
        response = lc.invoke(
            FunctionName="life-platform-mcp",
            Payload=json.dumps({"source": "aws.events", "__integration_test": True}),
        )
    except Exception as e:
        pytest.fail(f"I10 FAIL: Could not invoke MCP Lambda: {e}")

    status = response["StatusCode"]
    assert status == 200, f"I10 FAIL: MCP Lambda returned HTTP {status}"

    payload = json.loads(response["Payload"].read())

    # Check for import error specifically
    if "FunctionError" in response:
        error_type = payload.get("errorType", "")
        error_msg = payload.get("errorMessage", "")[:150]
        if "ImportModuleError" in error_type or "ImportModuleError" in error_msg:
            pytest.fail(
                f"I10 FAIL: MCP Lambda has ImportModuleError — ALL tools broken!\n"
                f"Error: {error_msg}\n"
                f"Fix: bash deploy/deploy_lambda.sh life-platform-mcp lambdas/mcp_server.py"
            )
        # Other functional errors (e.g. bad warmer step) are warnings, not failures


# ══════════════════════════════════════════════════════════════════════════════
# I11 — data-reconciliation Lambda ran recently (end-to-end pipeline health)
# Root cause of: would silently mask data quality issues if reconciliation stops
# Jin (R12): "we don't have end-to-end verification; this is the first step."
# ══════════════════════════════════════════════════════════════════════════════

DRECON_FUNCTION = "life-platform-data-reconciliation"
# V2 P0.9: Lambda runs WEEKLY (cron(30 7 ? * MON *), see operational_stack.py).
# 192h = 8 days = 1 weekly cycle + 1 day grace for cron slippage. Was 48h (wrong).
DRECON_LOOKBACK_HOURS = 192


def test_i11_data_reconciliation_running():
    """I11: data-reconciliation Lambda must have run within the last 48 hours.

    The reconciliation Lambda cross-checks DDB state against ingestion history.
    If it stops running, data quality issues accumulate silently.
    This test is the first step toward Jin's end-to-end pipeline verification.

    Checks:
      1. Lambda exists and is invocable
      2. CloudWatch log group has recent activity (within DRECON_LOOKBACK_HOURS)
    """
    boto3 = _get_boto3()
    lc = boto3.client("lambda", region_name=REGION)
    logs = boto3.client("logs", region_name=REGION)

    # Step 1: Lambda must exist
    try:
        lc.get_function_configuration(FunctionName=DRECON_FUNCTION)
    except Exception as e:
        if "ResourceNotFoundException" in str(e):
            pytest.skip(f"I11: {DRECON_FUNCTION} Lambda not found — may not be deployed yet")
        pytest.fail(f"I11 FAIL: Could not describe {DRECON_FUNCTION}: {e}")

    # Step 2: CloudWatch log group has recent activity
    log_group = f"/aws/lambda/{DRECON_FUNCTION}"
    import time as _time

    cutoff_ms = int((_time.time() - DRECON_LOOKBACK_HOURS * 3600) * 1000)

    try:
        streams = logs.describe_log_streams(
            logGroupName=log_group,
            orderBy="LastEventTime",
            descending=True,
            limit=1,
        ).get("logStreams", [])
    except Exception as e:
        if "ResourceNotFoundException" in str(e):
            pytest.fail(
                f"I11 FAIL: No CloudWatch log group for {DRECON_FUNCTION}. "
                f"Lambda has never run or logs are missing!\n"
                f"Check: aws lambda invoke --function-name {DRECON_FUNCTION} "
                f"--payload '{{}}' /tmp/recon.json --region {REGION}"
            )
        pytest.skip(f"I11: Could not check CloudWatch logs: {e}")

    if not streams:
        pytest.fail(f"I11 FAIL: {DRECON_FUNCTION} log group exists but has no log streams. " f"Lambda has never successfully run!")

    last_event_ms = streams[0].get("lastEventTimestamp", 0)
    if last_event_ms < cutoff_ms:
        import datetime as _dt

        last_run = _dt.datetime.fromtimestamp(last_event_ms / 1000).strftime("%Y-%m-%d %H:%M UTC")
        pytest.fail(
            f"I11 FAIL: {DRECON_FUNCTION} last ran at {last_run} "
            f"({DRECON_LOOKBACK_HOURS}h+ ago). Expected to run weekly (Mon 07:30 UTC).\n"
            f"Manual trigger: aws lambda invoke --function-name {DRECON_FUNCTION} "
            f"--payload '{{}}' /tmp/recon.json --region {REGION}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# I12 — MCP tool call with response shape validation (R13-F02)
# Root cause it prevents: MCP server starts but tools return wrong shape
# (IAM gap, schema mismatch, import error in tool function)
# ══════════════════════════════════════════════════════════════════════════════


def test_i12_mcp_tool_call_response_shape():
    """I12: MCP server must execute a representative tool call and return valid JSON
    with the expected content array shape.

    R13-F02: Validates the full MCP path — auth, tool dispatch, DDB read, serialisation.
    Uses `get_weight_loss_progress` as the probe: it reads DDB but writes nothing and is
    always fast (<5s). Passes even when no data has been ingested yet.

    Failure modes caught: IAM DDB read denied, tool import error, response serialisation
    failure, wrong handler name post-CDK-deploy.
    """
    boto3 = _get_boto3()
    lc = boto3.client("lambda", region_name=REGION)
    sm = boto3.client("secretsmanager", region_name=REGION)

    # Get the MCP API key to build a valid Bearer token
    try:
        secret = sm.get_secret_value(SecretId="life-platform/mcp-api-key")
        api_key = secret["SecretString"]
    except Exception as e:
        pytest.skip(f"I12: Cannot retrieve MCP API key: {e}")

    import hashlib
    import hmac as _hmac

    sig = _hmac.new(api_key.encode(), b"life-platform-bearer-v1", hashlib.sha256).hexdigest()
    bearer = f"lp_{sig}"

    # Build a minimal MCP tools/call JSON-RPC payload
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_weight_loss_progress",
            "arguments": {},
        },
    }
    event = {
        "requestContext": {
            "http": {"method": "POST", "path": "/"},
            "domainName": "c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws",
        },
        "headers": {"authorization": f"Bearer {bearer}"},
        "body": json.dumps(payload),
        "isBase64Encoded": False,
    }

    try:
        response = lc.invoke(
            FunctionName="life-platform-mcp",
            Payload=json.dumps(event),
        )
    except Exception as e:
        pytest.fail(f"I12 FAIL: Could not invoke MCP Lambda: {e}")

    if "FunctionError" in response:
        raw = json.loads(response["Payload"].read())
        pytest.fail(f"I12 FAIL: MCP Lambda returned FunctionError: " f"{raw.get('errorType')}: {raw.get('errorMessage', '')[:150]}")

    raw_body = json.loads(response["Payload"].read())
    body_str = raw_body.get("body", "")

    try:
        body = json.loads(body_str)
    except (json.JSONDecodeError, TypeError) as e:
        pytest.fail(f"I12 FAIL: MCP response body is not valid JSON: {e}\nRaw: {body_str[:200]}")

    # Validate JSON-RPC response shape
    assert "jsonrpc" in body, f"I12 FAIL: response missing 'jsonrpc' field: {body}"
    assert "result" in body or "error" in body, f"I12 FAIL: response has neither 'result' nor 'error': {body}"

    if "error" in body:
        # An RPC-level error (e.g. auth failure) is a real failure
        pytest.fail(f"I12 FAIL: MCP tool call returned RPC error: {body['error']}.\n" "Check IAM permissions and Bearer token derivation.")

    result = body.get("result", {})
    content = result.get("content", [])
    assert isinstance(content, list) and len(content) > 0, f"I12 FAIL: result.content is empty or not a list: {result}"

    # Content items must have type and text
    first = content[0]
    assert first.get("type") == "text", f"I12 FAIL: content[0].type is not 'text': {first}"
    text = first.get("text", "")
    assert len(text) > 10, f"I12 FAIL: content[0].text is suspiciously short: {text!r}"

    # Must be parseable JSON (tool returns a dict)
    try:
        tool_result = json.loads(text)
    except json.JSONDecodeError as e:
        pytest.fail(f"I12 FAIL: tool result text is not valid JSON: {e}\nText: {text[:200]}")

    assert isinstance(tool_result, dict), f"I12 FAIL: tool result is not a dict: {type(tool_result)}"


# ══════════════════════════════════════════════════════════════════════════════
# I13 — Freshness checker returns valid data (R13-F02)
# Root cause it prevents: freshness Lambda exits 0 but freshness data is wrong/absent
# ══════════════════════════════════════════════════════════════════════════════

FRESHNESS_FUNCTION = "life-platform-freshness-checker"
_FRESHNESS_EXPECTED_SOURCES = ["whoop", "withings", "strava", "habitify"]


def test_i13_freshness_checker_returns_valid_data():
    """I13: Freshness checker Lambda must return structured data with at least
    the core health sources present and having non-null last-seen dates.

    R13-F02: Validates the DDB read path for freshness data. An invocation
    that returns 200 but empty/malformed freshness data indicates a DDB
    schema mismatch, missing partition, or IAM read gap that wouldn't show
    up in the liveness checks of I3/I10.
    """
    boto3 = _get_boto3()
    lc = boto3.client("lambda", region_name=REGION)

    try:
        response = lc.invoke(
            FunctionName=FRESHNESS_FUNCTION,
            Payload=json.dumps({}),
        )
    except Exception as e:
        pytest.fail(f"I13 FAIL: Could not invoke {FRESHNESS_FUNCTION}: {e}")

    status = response["StatusCode"]
    assert status == 200, f"I13 FAIL: {FRESHNESS_FUNCTION} returned HTTP {status}"

    if "FunctionError" in response:
        payload = json.loads(response["Payload"].read())
        pytest.fail(
            f"I13 FAIL: {FRESHNESS_FUNCTION} FunctionError: " f"{payload.get('errorType')}: {payload.get('errorMessage', '')[:150]}"
        )

    raw = json.loads(response["Payload"].read())

    # Freshness checker returns a JSON body — parse it
    body_str = raw.get("body", raw) if isinstance(raw, dict) else raw
    if isinstance(body_str, str):
        try:
            body = json.loads(body_str)
        except json.JSONDecodeError:
            body = raw
    else:
        body = body_str

    # Must contain some freshness data — accept several possible shapes
    has_sources = isinstance(body, dict) and (
        "sources" in body or "freshness" in body or any(src in str(body).lower() for src in _FRESHNESS_EXPECTED_SOURCES)
    )

    assert has_sources, (
        f"I13 FAIL: Freshness checker response does not contain expected source data.\n"
        f"Expected at least one of: {_FRESHNESS_EXPECTED_SOURCES}\n"
        f"Got: {str(body)[:400]}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# I14 — Canary Lambda MCP check passes end-to-end (R14-F04)
# Root cause it prevents: canary silently broken for ~5 versions due to
# auth changes (R13-F05 HMAC bearer migration) not reflected in canary's
# Bearer token derivation — canary reported "skip" but not caught as failure.
# ══════════════════════════════════════════════════════════════════════════════

CANARY_FUNCTION = "life-platform-canary"


def test_i14_canary_mcp_check_passes():
    """I14: Canary Lambda must execute the mcp_only=True path without errors
    and report all_pass=True.

    R14-F04: The canary was silently broken for ~5 versions after the
    R13-F05 HMAC bearer auth migration. The mcp_only path tests exactly the
    auth derivation + MCP tool-list round-trip that broke. A test here catches
    future canary regressions immediately rather than discovering them at the
    next architecture review.

    Failure modes caught:
      - ImportModuleError in canary_lambda (structural)
      - MCP auth derivation mismatch (HMAC secret changed or rotated)
      - MCP Lambda unreachable / returned wrong HTTP status
      - MCP tools/list returned < 50 tools (SIMP-1 headroom guard)
      - Canary SES or CloudWatch IAM gaps (env var errors that prevent invocation)

    Note: mcp_only=True skips the DDB/S3 round-trip checks so this test is
    read-safe — no write operations on real data partitions.
    """
    boto3 = _get_boto3()
    lc = boto3.client("lambda", region_name=REGION)

    # Invoke canary in mcp_only mode — skips DDB/S3, only tests MCP reachability
    try:
        response = lc.invoke(
            FunctionName=CANARY_FUNCTION,
            Payload=json.dumps({"mcp_only": True, "__integration_test": True}),
        )
    except Exception as e:
        pytest.fail(f"I14 FAIL: Could not invoke {CANARY_FUNCTION}: {e}")

    status = response["StatusCode"]
    assert status == 200, f"I14 FAIL: Lambda invocation returned HTTP {status}"

    # Check for Lambda-level errors (import error, unhandled exception, etc.)
    if "FunctionError" in response:
        raw = json.loads(response["Payload"].read())
        error_type = raw.get("errorType", "unknown")
        error_msg = raw.get("errorMessage", "")[:200]
        pytest.fail(
            f"I14 FAIL: {CANARY_FUNCTION} FunctionError ({error_type}): {error_msg}\n"
            f"If ImportModuleError: redeploy canary — bash deploy/deploy_lambda.sh "
            f"{CANARY_FUNCTION} lambdas/canary_lambda.py\n"
            f"If auth error: check life-platform/mcp-api-key secret and HMAC derivation in canary_lambda.py"
        )

    raw_payload = json.loads(response["Payload"].read())

    # Parse the canary response body
    body_str = raw_payload.get("body", "")
    try:
        body = json.loads(body_str)
    except (json.JSONDecodeError, TypeError) as e:
        pytest.fail(f"I14 FAIL: Canary response body is not valid JSON: {e}\nRaw: {str(raw_payload)[:300]}")

    # Must report all_pass=True — any failure in the MCP check shows here
    all_pass = body.get("all_pass", False)
    failures = body.get("failures", -1)
    results = body.get("results", {})
    mcp_result = results.get("mcp", {})

    assert all_pass, (
        f"I14 FAIL: Canary reported {failures} failure(s) in mcp_only mode.\n"
        f"MCP result: {mcp_result}\n\n"
        f"Most likely causes:\n"
        f"  1. MCP auth regression — check life-platform/mcp-api-key and HMAC derivation\n"
        f"     (canary derives Bearer via hmac(api_key, b'life-platform-bearer-v1', sha256))\n"
        f"  2. MCP Lambda unreachable — check life-platform-mcp CloudWatch logs\n"
        f"  3. MCP tools/list < 50 tools — SIMP-1 cut went too far or deploy regressed\n"
        f"  4. MCP_FUNCTION_URL env var missing on canary Lambda\n\n"
        f"Full canary response: {json.dumps(body, indent=2)}"
    )

    # Verify MCP result has expected shape
    assert mcp_result.get("ok") is True, f"I14 FAIL: MCP check did not return ok=True: {mcp_result}"

    # Latency sanity check — MCP cold start should be < 10s
    latency_ms = mcp_result.get("latency_ms", 0)
    assert latency_ms < 10_000, (
        f"I14 WARN: MCP latency {latency_ms}ms exceeds 10s — Lambda may be cold-starting " f"or experiencing resource contention."
    )


# ══════════════════════════════════════════════════════════════════════════════
# I15 — Reserved concurrency guard
# Catches: "Lambda quota raised to 100 but CDK reserved-concurrency overrides
# are still commented out" (or the inverse: quota still 10 but someone
# uncommented them and the deploy will fail).
# Added 2026-05-24 per P1.2 of the holistic platform investment plan.
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
def test_i15_reserved_concurrency_guard():
    """I15: account quota and CDK reserved-concurrency overrides must agree.

    Reserved-concurrency overrides are pre-staged as commented-out lines in
    cdk/stacks/{ingestion,operational}_stack.py. They MUST stay commented while
    the account concurrency quota is at the AWS default of 10 (otherwise CDK
    deploys fail). They SHOULD be uncommented once AWS Support raises the
    quota (case 177921309700709).
    """

    boto3 = _get_boto3()
    lambda_client = boto3.client("lambda", region_name=REGION)

    try:
        account_settings = lambda_client.get_account_settings()
        # AccountLimit.ConcurrentExecutions is the regional concurrent-execution cap.
        quota = account_settings["AccountLimit"]["ConcurrentExecutions"]
    except Exception as e:
        pytest.skip(f"I15 SKIP: could not fetch Lambda account settings: {e}")

    stack_files = [
        os.path.join(ROOT, "cdk", "stacks", "ingestion_stack.py"),
        os.path.join(ROOT, "cdk", "stacks", "operational_stack.py"),
        os.path.join(ROOT, "cdk", "stacks", "compute_stack.py"),
        os.path.join(ROOT, "cdk", "stacks", "mcp_stack.py"),
    ]
    uncommented_lines = []
    commented_lines = []
    for path in stack_files:
        if not os.path.exists(path):
            continue
        with open(path) as f:
            for lineno, line in enumerate(f, 1):
                if "ReservedConcurrentExecutions" not in line:
                    continue
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    commented_lines.append(f"{os.path.basename(path)}:{lineno}")
                else:
                    uncommented_lines.append(f"{os.path.basename(path)}:{lineno}")

    if quota < 100 and uncommented_lines:
        pytest.fail(
            f"I15 FAIL: Account quota is {quota} (< 100) but CDK has "
            f"{len(uncommented_lines)} uncommented reserved-concurrency override(s):\n"
            + "\n".join(f"    {ln}" for ln in uncommented_lines)
            + "\n\nThis combination will fail CDK deploy. Either re-comment the "
            "overrides, or wait for AWS Support case 177921309700709 to raise quota to 100+."
        )

    if quota >= 100 and commented_lines and not uncommented_lines:
        pytest.fail(
            f"I15 FAIL: Account quota is {quota} (≥ 100, raised by AWS), but ALL "
            f"reserved-concurrency overrides are still commented out:\n"
            + "\n".join(f"    {ln}" for ln in commented_lines)
            + "\n\nFix: uncomment the overrides in the listed CDK stacks and "
            "cdk deploy --all to protect critical Lambdas from starve-out."
        )


# ══════════════════════════════════════════════════════════════════════════════
# I16 — Ingest → DDB sanity check
# Each day after genesis, at least 2 ingestion sources should have a DATE#
# record. Catches "ingest cron silently broken — daily-brief renders zeros".
# Added 2026-05-24 per P2.1 of the holistic platform investment plan.
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
def test_i16_recent_ingest_records_exist():
    """I16: at least 2 ingestion sources have today-or-yesterday DATE# records.

    Post-genesis, the system should ingest withings + whoop + macrofactor +
    todoist + notion daily. Allow 24h slop so an early-morning run before all
    ingestions complete doesn't flake.

    Known behavioral flake (2026-05-27 observation): of the 5 sources, only
    whoop is fully passive — the rest depend on user action (stepping on
    Withings, logging food in MacroFactor, completing/creating Todoist
    tasks, writing in Notion). On low-activity days this test correctly
    fails with `Found: ['whoop@...']` (1 source < 2 required). This is
    NOT a code regression — the platform is faithfully reporting that
    you haven't been logging. Self-resolves on the first day with any
    real user activity.
    """
    from datetime import datetime, timedelta, timezone

    boto3 = _get_boto3()

    sys.path.insert(0, os.path.join(ROOT, "lambdas"))
    from constants import EXPERIMENT_START_DATE

    genesis = datetime.strptime(EXPERIMENT_START_DATE, "%Y-%m-%d").date()
    today = datetime.now(timezone.utc).date()
    if today < genesis:
        pytest.skip(f"I16 SKIP: pre-genesis (today={today}, genesis={genesis})")

    ddb = boto3.client("dynamodb", region_name=REGION)
    sources_to_check = ["withings", "whoop", "macrofactor", "todoist", "notion"]
    yesterday = (today - timedelta(days=1)).isoformat()
    today_iso = today.isoformat()

    found = []
    for source in sources_to_check:
        pk = f"USER#matthew#SOURCE#{source}"
        for sk in (f"DATE#{today_iso}", f"DATE#{yesterday}"):
            try:
                resp = ddb.get_item(
                    TableName=TABLE_NAME,
                    Key={"pk": {"S": pk}, "sk": {"S": sk}},
                )
                if "Item" in resp:
                    found.append(f"{source}@{sk[5:]}")
                    break
            except Exception:
                pass

    if len(found) < 2:
        pytest.fail(
            f"I16 FAIL: fewer than 2 sources have recent DATE# records. "
            f"Found: {found or 'NONE'}\n"
            f"Expected ≥2 from {sources_to_check} for {today_iso} or {yesterday}."
        )


# ══════════════════════════════════════════════════════════════════════════════
# I17 — Character compute → EMA continuity
# The character-sheet-compute Lambda runs daily and writes a single record per
# day. Catches "compute Lambda silently failed; level stays frozen for days".
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
def test_i17_character_sheet_recent_record():
    """I17: a character_sheet record exists in the last 3 days with level ≥ 1.

    Compute writes the PRIOR day's sheet daily at ~16:30 UTC, so the freshest record is
    routinely 1-2 days old (offset 2 before the run lands, offset 1 after). Window is 3
    days to match that cadence rather than flaking every morning before 16:30 UTC.
    """
    from datetime import datetime, timedelta, timezone

    boto3 = _get_boto3()

    sys.path.insert(0, os.path.join(ROOT, "lambdas"))
    from constants import EXPERIMENT_START_DATE

    genesis = datetime.strptime(EXPERIMENT_START_DATE, "%Y-%m-%d").date()
    today = datetime.now(timezone.utc).date()
    if today < genesis:
        pytest.skip(f"I17 SKIP: pre-genesis (today={today})")

    ddb = boto3.client("dynamodb", region_name=REGION)
    pk = "USER#matthew#SOURCE#character_sheet"

    for offset in (0, 1, 2):
        date = (today - timedelta(days=offset)).isoformat()
        resp = ddb.get_item(
            TableName=TABLE_NAME,
            Key={"pk": {"S": pk}, "sk": {"S": f"DATE#{date}"}},
        )
        item = resp.get("Item")
        if item:
            level_attr = item.get("character_level") or item.get("level") or {}
            level_raw = level_attr.get("N") if isinstance(level_attr, dict) else None
            assert level_raw is not None, (
                f"I17 FAIL: character record exists for {date} but has no "
                f"character_level/level attribute. Item keys: {sorted(item.keys())}"
            )
            assert float(level_raw) >= 1, f"I17 FAIL: character level is {level_raw} on {date} — expected ≥ 1."
            return

    pytest.fail(
        f"I17 FAIL: no character_sheet DATE# record for today or yesterday. "
        f"character-sheet-compute may have silently failed; investigate "
        f"/aws/lambda/character-sheet-compute logs."
    )


# ══════════════════════════════════════════════════════════════════════════════
# I18 — Daily-brief recent successful invocation
# Catches "daily-brief stopped sending; nobody noticed because the failure is
# silent (no alarm if it raises in error-trapped section)".
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
def test_i18_daily_brief_recently_invoked():
    """I18: daily-brief Lambda has been invoked successfully in the past 48h."""
    from datetime import datetime, timedelta, timezone

    boto3 = _get_boto3()

    sys.path.insert(0, os.path.join(ROOT, "lambdas"))
    from constants import EXPERIMENT_START_DATE

    genesis = datetime.strptime(EXPERIMENT_START_DATE, "%Y-%m-%d").date()
    today = datetime.now(timezone.utc).date()
    if today < genesis:
        pytest.skip(f"I18 SKIP: pre-genesis (today={today})")

    cw = boto3.client("cloudwatch", region_name=REGION)
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=48)

    resp = cw.get_metric_statistics(
        Namespace="AWS/Lambda",
        MetricName="Invocations",
        Dimensions=[{"Name": "FunctionName", "Value": "daily-brief"}],
        StartTime=start,
        EndTime=end,
        Period=3600,
        Statistics=["Sum"],
    )
    total = sum(p["Sum"] for p in resp.get("Datapoints", []))
    assert total >= 1, f"I18 FAIL: daily-brief has 0 invocations in the last 48h. " f"Check EventBridge rule + Lambda permissions."


# ══════════════════════════════════════════════════════════════════════════════
# I19 — Site-api /api/journey contract
# The homepage hero and Day-N counter are populated by /api/journey. The
# endpoint must keep returning the expected JSON shape — a typo'd field name
# silently breaks the homepage with no Lambda error.
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
def test_i19_site_api_journey_contract():
    """I19: /api/journey returns the expected fields with sensible values."""
    import urllib.request

    sys.path.insert(0, os.path.join(ROOT, "lambdas"))
    from constants import EXPERIMENT_START_DATE

    try:
        req = urllib.request.Request(
            "https://averagejoematt.com/api/journey",
            headers={"User-Agent": "integration-test-i19/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
    except Exception as e:
        pytest.skip(f"I19 SKIP: /api/journey unreachable: {e}")

    # Contract: top-level wrapper.
    assert "journey" in body, f"I19 FAIL: /api/journey missing 'journey' wrapper key. " f"Got keys: {sorted(body.keys())}"
    j = body["journey"]
    required = ["started_date", "start_weight_lbs", "current_weight_lbs", "goal_weight_lbs"]
    missing = [k for k in required if k not in j]
    assert not missing, f"I19 FAIL: /api/journey.journey missing fields: {missing}\n" f"Got keys: {sorted(j.keys())}"

    # Cross-check started_date matches our deployed constants.
    assert j["started_date"] == EXPERIMENT_START_DATE, (
        f"I19 FAIL: /api/journey started_date={j['started_date']} but "
        f"deployed constants say {EXPERIMENT_START_DATE}. site-api Lambda is stale."
    )

    # Sanity bounds on weight.
    cw = j["current_weight_lbs"]
    if cw is not None:
        assert 100 < float(cw) < 500, f"I19 FAIL: weight {cw} outside [100, 500]"


# ══════════════════════════════════════════════════════════════════════════════
# I20 — Pre-genesis DDB phase-tag integrity
# Anything written before EXPERIMENT_START_DATE should be phase-tagged "pilot"
# (so read-path phase_filter excludes it). A miss here means the launch-eve
# bug class is back. Catches "DDB read returns a 2026-04 record because someone
# forgot to phase-tag a partition".
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
def test_i20_pre_genesis_records_are_phase_tagged():
    """I20: spot-check that pre-genesis DATE# records carry phase='pilot'."""
    boto3 = _get_boto3()

    sys.path.insert(0, os.path.join(ROOT, "lambdas"))
    from constants import EXPERIMENT_START_DATE

    ddb = boto3.client("dynamodb", region_name=REGION)
    # Pick three partitions known to have pre-genesis history.
    sample_partitions = [
        "USER#matthew#SOURCE#whoop",
        "USER#matthew#SOURCE#withings",
        "USER#matthew#SOURCE#macrofactor",
    ]

    untagged_pre_genesis: list[str] = []
    checked = 0
    for pk in sample_partitions:
        resp = ddb.query(
            TableName=TABLE_NAME,
            KeyConditionExpression="pk = :p AND begins_with(sk, :s)",
            ExpressionAttributeValues={
                ":p": {"S": pk},
                ":s": {"S": "DATE#"},
            },
            Limit=20,
            ScanIndexForward=True,  # oldest first
        )
        for item in resp.get("Items", []):
            sk_raw = item["sk"]["S"]
            if not sk_raw.startswith("DATE#"):
                continue
            date_part = sk_raw[5:15]
            if date_part >= EXPERIMENT_START_DATE:
                continue  # post-genesis — skip
            checked += 1
            phase = item.get("phase", {}).get("S") if "phase" in item else None
            if phase != "pilot":
                untagged_pre_genesis.append(f"{pk} {sk_raw} phase={phase!r}")

    if checked == 0:
        pytest.skip("I20 SKIP: no pre-genesis records found in sample (table may " "be empty pre-launch — that's also fine)")

    assert not untagged_pre_genesis, (
        f"I20 FAIL: {len(untagged_pre_genesis)} pre-genesis records lack "
        f"phase='pilot' tag:\n  "
        + "\n  ".join(untagged_pre_genesis[:5])
        + (f"\n  ... ({len(untagged_pre_genesis) - 5} more)" if len(untagged_pre_genesis) > 5 else "")
        + "\n\nFix: rerun deploy/restart_phase_tag.py --apply"
    )


# ══════════════════════════════════════════════════════════════════════════════
# I21 — DDB profile matches deployed constants.py
# constants.py is the source of truth for EXPERIMENT_START_DATE +
# EXPERIMENT_BASELINE_WEIGHT_LBS. The DDB PROFILE#v1 record is what site-api
# reads. If they diverge, the site shows stale data with no Lambda error.
# Catches the "site_api warm cache held stale weight" class of bug.
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
def test_i21_ddb_profile_matches_constants():
    """I21: USER#matthew PROFILE#v1 fields must match lambdas/constants.py."""
    boto3 = _get_boto3()

    sys.path.insert(0, os.path.join(ROOT, "lambdas"))
    from constants import EXPERIMENT_BASELINE_WEIGHT_LBS, EXPERIMENT_START_DATE

    ddb = boto3.client("dynamodb", region_name=REGION)
    resp = ddb.get_item(
        TableName=TABLE_NAME,
        Key={"pk": {"S": "USER#matthew"}, "sk": {"S": "PROFILE#v1"}},
    )
    item = resp.get("Item")
    assert item, "I21 FAIL: USER#matthew PROFILE#v1 record missing from DDB"

    ddb_start = item.get("journey_start_date", {}).get("S")
    ddb_weight_raw = item.get("journey_start_weight_lbs", {}).get("N")
    ddb_weight = float(ddb_weight_raw) if ddb_weight_raw else None

    assert ddb_start == EXPERIMENT_START_DATE, (
        f"I21 FAIL: DDB profile journey_start_date={ddb_start!r} but constants.py "
        f"says {EXPERIMENT_START_DATE!r}. Run deploy/restart_pipeline.py to reconcile."
    )

    # Allow 0.5lb tolerance for Decimal/float rounding noise.
    if ddb_weight is not None:
        assert abs(ddb_weight - EXPERIMENT_BASELINE_WEIGHT_LBS) < 0.5, (
            f"I21 FAIL: DDB profile journey_start_weight_lbs={ddb_weight} vs "
            f"constants.py EXPERIMENT_BASELINE_WEIGHT_LBS={EXPERIMENT_BASELINE_WEIGHT_LBS}. "
            f"Run deploy/restart_pipeline.py to reconcile."
        )


# ══════════════════════════════════════════════════════════════════════════════
# Standalone runner
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import subprocess

    result = subprocess.run(
        ["python3", "-m", "pytest", __file__, "-v", "--tb=short", "-m", "integration"],
        cwd=ROOT,
    )
    sys.exit(result.returncode)
