"""
ComputeStack — pre-computation Lambdas + EventBridge schedules.

v2.0 (v3.4.0): CDK-managed IAM roles replace existing_role_arn references.
  All 7 Lambdas now have dedicated CDK-owned roles with least-privilege policies.
  DLQ managed normally for all Lambdas (no more shared-role SQS workaround).

Lambdas (7):
  anomaly-detector          cron(5 15 * * ? *)    — 8:05 AM PT daily
  character-sheet-compute   cron(35 17 * * ? *)   — 9:35 AM PT daily
  daily-metrics-compute     cron(40 17 * * ? *)   — 9:40 AM PT daily
  daily-insight-compute     cron(45 17 * * ? *)   — 9:45 AM PT daily
  adaptive-mode-compute     cron(50 17 * * ? *)   — 9:50 AM PT daily
  hypothesis-engine         cron(0 19 ? * SUN *)  — Sunday 11:00 AM PT
  dashboard-refresh         cron(0 21 * * ? *)    — 2:00 PM PDT + 6:00 PM PDT
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
from stacks import role_policies as rp

REGION = "us-west-2"
ACCT = "205930651321"

INGESTION_DLQ_ARN    = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
LIFE_PLATFORM_TABLE  = "life-platform"
LIFE_PLATFORM_BUCKET = "matthew-life-platform"
ALERTS_TOPIC_ARN     = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"


class ComputeStack(Stack):

    def __init__(self, scope: Construct, construct_id: str,
                 table, bucket, dlq, alerts_topic, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        local_dlq          = sqs.Queue.from_queue_arn(self, "IngestionDLQ", INGESTION_DLQ_ARN)
        local_table        = dynamodb.Table.from_table_name(self, "LifePlatformTable", LIFE_PLATFORM_TABLE)
        local_bucket       = s3.Bucket.from_bucket_name(self, "LifePlatformBucket", LIFE_PLATFORM_BUCKET)
        local_alerts_topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)

        shared = dict(
            table=local_table,
            bucket=local_bucket,
            dlq=local_dlq,
            alerts_topic=local_alerts_topic,
        )

        create_platform_lambda(
            self, "AnomalyDetector",
            function_name="anomaly-detector",
            handler="anomaly_detector_lambda.lambda_handler",
            source_file="lambdas/anomaly_detector_lambda.py",
            schedule="cron(5 15 * * ? *)",
            timeout_seconds=90, memory_mb=256,
            custom_policies=rp.compute_anomaly_detector(),
            **shared,
        )

        create_platform_lambda(
            self, "CharacterSheetCompute",
            function_name="character-sheet-compute",
            handler="character_sheet_lambda.lambda_handler",
            source_file="lambdas/character_sheet_lambda.py",
            schedule="cron(35 17 * * ? *)",
            timeout_seconds=60, memory_mb=512,
            custom_policies=rp.compute_character_sheet(),
            **shared,
        )

        create_platform_lambda(
            self, "DailyMetricsCompute",
            function_name="daily-metrics-compute",
            handler="daily_metrics_compute_lambda.lambda_handler",
            source_file="lambdas/daily_metrics_compute_lambda.py",
            schedule="cron(40 17 * * ? *)",
            timeout_seconds=120, memory_mb=512,
            custom_policies=rp.compute_daily_metrics(),
            **shared,
        )

        create_platform_lambda(
            self, "DailyInsightCompute",
            function_name="daily-insight-compute",
            handler="daily_insight_compute_lambda.lambda_handler",
            source_file="lambdas/daily_insight_compute_lambda.py",
            schedule="cron(45 17 * * ? *)",
            timeout_seconds=120, memory_mb=512,
            custom_policies=rp.compute_daily_insight(),
            **shared,
        )

        create_platform_lambda(
            self, "AdaptiveModeCompute",
            function_name="adaptive-mode-compute",
            handler="adaptive_mode_lambda.lambda_handler",
            source_file="lambdas/adaptive_mode_lambda.py",
            schedule="cron(50 17 * * ? *)",
            timeout_seconds=120, memory_mb=256,
            custom_policies=rp.compute_adaptive_mode(),
            **shared,
        )

        create_platform_lambda(
            self, "HypothesisEngine",
            function_name="hypothesis-engine",
            handler="hypothesis_engine_lambda.lambda_handler",
            source_file="lambdas/hypothesis_engine_lambda.py",
            schedule="cron(0 19 ? * SUN *)",
            timeout_seconds=120, memory_mb=256,
            custom_policies=rp.compute_hypothesis_engine(),
            **shared,
        )

        dashboard = create_platform_lambda(
            self, "DashboardRefresh",
            function_name="dashboard-refresh",
            handler="dashboard_refresh_lambda.lambda_handler",
            source_file="lambdas/dashboard_refresh_lambda.py",
            schedule="cron(0 21 * * ? *)",
            timeout_seconds=60, memory_mb=256,
            custom_policies=rp.compute_dashboard_refresh(),
            **shared,
        )

        evening_rule = events.Rule(
            self, "DashboardRefreshEveningRule",
            schedule=events.Schedule.expression("cron(0 1 * * ? *)"),
            description="Dashboard refresh — 6:00 PM PDT",
        )
        evening_rule.add_target(targets.LambdaFunction(dashboard))

        # ══════════════════════════════════════════════════════════════
        # 8. failure-pattern-compute — Sunday 9:50 AM PT (previously unmanaged)
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "FailurePatternCompute",
            function_name="failure-pattern-compute",
            handler="failure_pattern_compute_lambda.lambda_handler",
            source_file="lambdas/failure_pattern_compute_lambda.py",
            schedule="cron(50 17 ? * SUN *)",
            timeout_seconds=300, memory_mb=256,
            environment={
                "ANTHROPIC_SECRET": "life-platform/ai-keys",
                "AI_MODEL_HAIKU": "claude-haiku-4-5-20251001",
            },
            custom_policies=rp.compute_failure_pattern(),
            **shared,
        )
