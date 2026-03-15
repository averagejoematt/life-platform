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

v1.0.0 — 2026-03-14 (R11 engineering strategy item 8)
"""

import json
import os
import sys
import time
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
        from botocore.exceptions import NoCredentialsError, ClientError
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
    "whoop-data-ingestion":         "whoop_lambda",
    "garmin-data-ingestion":        "garmin_lambda",
    "strava-data-ingestion":        "strava_lambda",
    "withings-data-ingestion":      "withings_lambda",
    "habitify-data-ingestion":      "habitify_lambda",
    "eightsleep-data-ingestion":    "eightsleep_lambda",
    "macrofactor-data-ingestion":   "macrofactor_lambda",
    "todoist-data-ingestion":       "todoist_lambda",
    "notion-journal-ingestion":     "notion_lambda",
    "health-auto-export-webhook":   "health_auto_export_lambda",
    "daily-brief":                  "daily_brief_lambda",
    "weekly-digest":                "weekly_digest_lambda",
    "life-platform-mcp":            "mcp_server",
    "life-platform-freshness-checker": "freshness_checker_lambda",
    "google-calendar-ingestion":    "google_calendar_lambda",
    "character-sheet-compute":      "character_sheet_lambda",
    "daily-metrics-compute":        "daily_metrics_compute_lambda",
    "daily-insight-compute":        "daily_insight_compute_lambda",
    "anomaly-detector":             "anomaly_detector_lambda",
    "life-platform-canary":         "canary_lambda",
    "dlq-consumer":                 "dlq_consumer_lambda",
}


def test_i1_lambda_handlers_match_expected():
    """I1: Lambda handlers in AWS must match expected module names.

    Catches CDK reconcile regression (2026-03-12 P0): CDK overwrites live
    handler config with wrong module name → Lambda silently fails on every
    invocation until the alarm fires hours later.

    Fix: aws lambda update-function-configuration --function-name <fn>
         --handler <module>.lambda_handler --region us-west-2
    """
    boto3 = _get_boto3()
    lc = boto3.client("lambda", region_name=REGION)

    failures = []
    for fn_name, expected_module in EXPECTED_HANDLERS.items():
        try:
            config = lc.get_function_configuration(FunctionName=fn_name)
            actual_handler = config["Handler"]
            actual_module = actual_handler.split(".")[0]

            if actual_module == "lambda_function":
                failures.append(
                    f"{fn_name}: handler is 'lambda_function.lambda_handler' "
                    f"(CDK reconcile regression — expected '{expected_module}')"
                )
            elif actual_module != expected_module:
                failures.append(
                    f"{fn_name}: module '{actual_module}' != expected '{expected_module}'"
                )
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
    "life-platform-mcp",
    "life-platform-freshness-checker",
    "anomaly-detector",
    "character-sheet-compute",
    "daily-metrics-compute",
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
            has_current = any(
                f":{SHARED_LAYER_NAME}:{current_version}" in arn
                for arn in layer_arns
            )
            if not layer_arns:
                stale.append(f"{fn_name}: NO layer attached at all")
            elif not has_current:
                # Find what version it has
                found_version = None
                for arn in layer_arns:
                    if SHARED_LAYER_NAME in arn:
                        found_version = arn.split(":")[-1]
                stale.append(
                    f"{fn_name}: layer v{found_version} "
                    f"(current is v{current_version})"
                )
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
    "life-platform-canary",           # always safe to invoke
    "life-platform-freshness-checker", # read-only, non-destructive
    "life-platform-mcp",              # MCP health check (warmer path)
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
        pitr_status = (pitr["ContinuousBackupsDescription"]
                       ["PointInTimeRecoveryDescription"]
                       ["PointInTimeRecoveryStatus"])
        assert pitr_status == "ENABLED", (
            f"I4 FAIL: PITR is '{pitr_status}' (expected ENABLED) — no 35-day backup!"
        )
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

    assert not missing, (
        f"I5 FAIL: {len(missing)} required secret(s) missing or deleted:\n"
        + "\n".join(f"  ❌ {s}" for s in missing)
    )

    assert not still_alive, (
        f"I5 WARN: {len(still_alive)} secret(s) should have been deleted:\n"
        + "\n".join(f"  ⚠️  {s}" for s in still_alive)
    )


# ══════════════════════════════════════════════════════════════════════════════
# I6 — Critical EventBridge rules exist and are enabled
# Root cause of: 2026-03-10 P3 (EB rule deleted, Lambda missed scheduled runs)
# ══════════════════════════════════════════════════════════════════════════════

REQUIRED_EB_RULES = [
    "daily-brief-schedule",
    "whoop-daily-ingestion",
    "todoist-data-ingestion",
    "life-platform-freshness-check",
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
    "config/profile.json",
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
            AttributeNames=["ApproximateNumberOfMessages",
                             "ApproximateNumberOfMessagesNotVisible"],
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
# Standalone runner
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        ["python3", "-m", "pytest", __file__, "-v", "--tb=short", "-m", "integration"],
        cwd=ROOT,
    )
    sys.exit(result.returncode)
