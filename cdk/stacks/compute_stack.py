"""
ComputeStack — pre-computation Lambdas + EventBridge schedules.

Lambdas (7):
  anomaly-detector          cron(5 15 * * ? *)    — 8:05 AM PT daily
  character-sheet-compute   cron(35 17 * * ? *)   — 9:35 AM PT daily
  daily-metrics-compute     cron(40 17 * * ? *)   — 9:40 AM PT daily
  daily-insight-compute     cron(45 17 * * ? *)   — 9:45 AM PT daily
  adaptive-mode-compute     cron(50 17 * * ? *)   — 9:50 AM PT daily
  hypothesis-engine         cron(0 19 ? * SUN *)  — Sunday 11:00 AM PT
  dashboard-refresh         cron(0 21 * * ? *)    — 2:00 PM PDT (primary rule)
                            cron(0 1  * * ? *)    — 6:00 PM PDT (second rule)

All use from_role_arn() to reference existing IAM roles — no DefaultPolicy generated.
All DLQs set via L1 escape hatch — avoids grant_send_messages DependsOn.
Cross-stack resources resolved locally — no Fn::ImportValue (CoreStack not yet in CFn).

Handler naming convention: <source_module>.lambda_handler
  All handlers verified against actual source file function signatures.
  DO NOT change handlers to lambda_function.lambda_handler — that would break existing Lambdas.

Import procedure (first time only):
  cdk import LifePlatformCompute --resource-mapping compute-import-map.json

After import: run drift detection to confirm role + env var alignment.
  aws cloudformation detect-stack-drift --stack-name LifePlatformCompute
"""

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_iam as iam,
    aws_sqs as sqs,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_sns as sns,
    aws_events as events,
    aws_events_targets as targets,
)
from constructs import Construct

from stacks.lambda_helpers import create_platform_lambda

REGION = "us-west-2"
ACCT = "205930651321"

# ── Core resource ARNs (resolved locally — CoreStack not yet in CloudFormation) ──
INGESTION_DLQ_ARN    = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
LIFE_PLATFORM_TABLE  = "life-platform"
LIFE_PLATFORM_BUCKET = "matthew-life-platform"
ALERTS_TOPIC_ARN     = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"

def _role(name): return f"arn:aws:iam::{ACCT}:role/{name}"

# ── IAM role ARNs ──
# Verify actual roles before import with:
#   for fn in anomaly-detector character-sheet-compute daily-metrics-compute \
#       daily-insight-compute adaptive-mode-compute hypothesis-engine dashboard-refresh; do
#     echo "$fn: $(aws lambda get-function-configuration --function-name $fn --query Role --output text)"
#   done
#
# anomaly-detector, character-sheet-compute, dashboard-refresh were deployed pre-SEC-1
# and may use a shared role. The weekly-digest-role entries below are best guesses —
# update after running the verification query above.
ROLE_ARNS = {
    "anomaly_detector":   _role("life-platform-email-role"),      # verified 2026-03-09
    "character_sheet":    _role("life-platform-compute-role"),    # verified 2026-03-09
    "daily_metrics":      _role("lambda-daily-metrics-role"),     # verified 2026-03-09
    "daily_insight":      _role("lambda-daily-insight-role"),     # verified 2026-03-09
    "adaptive_mode":      _role("lambda-adaptive-mode-role"),     # verified 2026-03-09
    "hypothesis":         _role("lambda-hypothesis-engine-role"), # verified 2026-03-09
    "dashboard_refresh":  _role("lambda-mcp-server-role"),        # verified 2026-03-09
}


class ComputeStack(Stack):

    def __init__(self, scope: Construct, construct_id: str,
                 table, bucket, dlq, alerts_topic, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── Local resource references (bypass cross-stack Fn::ImportValue) ──
        local_dlq          = sqs.Queue.from_queue_arn(self, "IngestionDLQ", INGESTION_DLQ_ARN)
        local_table        = dynamodb.Table.from_table_name(self, "LifePlatformTable", LIFE_PLATFORM_TABLE)
        local_bucket       = s3.Bucket.from_bucket_name(self, "LifePlatformBucket", LIFE_PLATFORM_BUCKET)
        local_alerts_topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)

        # ── Two shared dicts: with DLQ (dedicated-role Lambdas) and without (shared-role Lambdas)
        # Shared-role Lambdas (anomaly, character-sheet, dashboard-refresh) use pre-SEC-1 roles
        # that lack SQS SendMessage — CDK's DLQ escape hatch triggers a permission check and fails.
        # Solution: skip DLQ management for those 3 Lambdas in CDK; their DLQ state is unmanaged drift.
        # The 4 dedicated-role Lambdas (daily-metrics, daily-insight, adaptive-mode, hypothesis)
        # have SQS perms from SEC-1 and get DLQ managed normally.
        shared_with_dlq = dict(
            table=local_table,
            bucket=local_bucket,
            dlq=local_dlq,
            alerts_topic=local_alerts_topic,
        )
        shared_no_dlq = dict(
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=local_alerts_topic,
        )

        # ══════════════════════════════════════════════════════════════
        # 1. anomaly-detector — 8:05 AM PT daily
        # Role: life-platform-email-role (shared, no SQS perm) → dlq=None
        # DLQ exists in AWS but is unmanaged drift — acceptable for now.
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "AnomalyDetector",
            function_name="anomaly-detector",
            handler="anomaly_detector_lambda.lambda_handler",
            source_file="lambdas/anomaly_detector_lambda.py",
            schedule="cron(5 15 * * ? *)",
            timeout_seconds=90,
            memory_mb=256,
            existing_role_arn=ROLE_ARNS["anomaly_detector"],
            **shared_no_dlq,
        )

        # ══════════════════════════════════════════════════════════════
        # 2. character-sheet-compute — 9:35 AM PT daily
        # Role: life-platform-compute-role (shared, no SQS perm) → dlq=None
        # No DLQ in AWS either — consistent.
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "CharacterSheetCompute",
            function_name="character-sheet-compute",
            handler="character_sheet_lambda.lambda_handler",
            source_file="lambdas/character_sheet_lambda.py",
            schedule="cron(35 17 * * ? *)",
            timeout_seconds=60,
            memory_mb=512,
            existing_role_arn=ROLE_ARNS["character_sheet"],
            **shared_no_dlq,
        )

        # ══════════════════════════════════════════════════════════════
        # 3. daily-metrics-compute — 9:40 AM PT daily
        # Role: lambda-daily-metrics-role (dedicated, has SQS perm) → dlq managed
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "DailyMetricsCompute",
            function_name="daily-metrics-compute",
            handler="daily_metrics_compute_lambda.lambda_handler",
            source_file="lambdas/daily_metrics_compute_lambda.py",
            schedule="cron(40 17 * * ? *)",
            timeout_seconds=120,
            memory_mb=512,
            existing_role_arn=ROLE_ARNS["daily_metrics"],
            **shared_with_dlq,
        )

        # ══════════════════════════════════════════════════════════════
        # 4. daily-insight-compute — 9:45 AM PT daily
        # Role: lambda-daily-insight-role (dedicated, has SQS perm) → dlq managed
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "DailyInsightCompute",
            function_name="daily-insight-compute",
            handler="daily_insight_compute_lambda.lambda_handler",
            source_file="lambdas/daily_insight_compute_lambda.py",
            schedule="cron(45 17 * * ? *)",
            timeout_seconds=120,
            memory_mb=512,
            existing_role_arn=ROLE_ARNS["daily_insight"],
            **shared_with_dlq,
        )

        # ══════════════════════════════════════════════════════════════
        # 5. adaptive-mode-compute — 9:50 AM PT daily
        # Role: lambda-adaptive-mode-role (dedicated, has SQS perm) → dlq managed
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "AdaptiveModeCompute",
            function_name="adaptive-mode-compute",
            handler="adaptive_mode_lambda.lambda_handler",
            source_file="lambdas/adaptive_mode_lambda.py",
            schedule="cron(50 17 * * ? *)",
            timeout_seconds=120,
            memory_mb=256,
            existing_role_arn=ROLE_ARNS["adaptive_mode"],
            **shared_with_dlq,
        )

        # ══════════════════════════════════════════════════════════════
        # 6. hypothesis-engine — Sunday 11:00 AM PT
        # Role: lambda-hypothesis-engine-role (dedicated, has SQS perm) → dlq managed
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "HypothesisEngine",
            function_name="hypothesis-engine",
            handler="hypothesis_engine_lambda.lambda_handler",
            source_file="lambdas/hypothesis_engine_lambda.py",
            schedule="cron(0 19 ? * SUN *)",
            timeout_seconds=120,
            memory_mb=256,
            existing_role_arn=ROLE_ARNS["hypothesis"],
            **shared_with_dlq,
        )

        # ══════════════════════════════════════════════════════════════
        # 7. dashboard-refresh — two EventBridge rules, one Lambda
        # Afternoon: 2:00 PM PDT = 21:00 UTC  cron(0 21 * * ? *)
        # Evening:   6:00 PM PDT = 01:00 UTC  cron(0 1  * * ? *)
        # DST note: updated from PST (22:00/02:00) to PDT (21:00/01:00) on 2026-03-08
        # Role: lambda-mcp-server-role (shared, no SQS perm) → dlq=None
        # No DLQ in AWS either — consistent.
        # ══════════════════════════════════════════════════════════════
        dashboard = create_platform_lambda(
            self, "DashboardRefresh",
            function_name="dashboard-refresh",
            handler="dashboard_refresh_lambda.lambda_handler",
            source_file="lambdas/dashboard_refresh_lambda.py",
            schedule="cron(0 21 * * ? *)",    # afternoon rule — dashboard-refresh-afternoon
            timeout_seconds=60,
            memory_mb=256,
            existing_role_arn=ROLE_ARNS["dashboard_refresh"],
            **shared_no_dlq,
        )

        # Second EventBridge rule: evening refresh at 6 PM PDT
        # The actual AWS rule name is "dashboard-refresh-evening" — tracked in import map.
        evening_rule = events.Rule(
            self, "DashboardRefreshEveningRule",
            schedule=events.Schedule.expression("cron(0 1 * * ? *)"),
            description="Dashboard refresh — 6:00 PM PDT",
        )
        evening_rule.add_target(targets.LambdaFunction(dashboard))
