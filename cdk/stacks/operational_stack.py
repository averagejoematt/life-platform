"""
OperationalStack — Platform health, safety, and lifecycle Lambdas.

Lambdas (8):
  life-platform-freshness-checker   cron(45 16 * * ? *)  — 9:45 AM PT daily
  life-platform-dlq-consumer        rate(6 hours)
  life-platform-canary              rate(4 hours)
  life-platform-pip-audit           cron(0 17 ? * MON *) — Every Monday (first-Monday in AWS)
  life-platform-qa-smoke            cron(30 18 ? * * *)  — Daily 11:30 AM PT
  life-platform-key-rotator         (Secrets Manager rotation trigger — no EventBridge)
  life-platform-data-export         (on-demand only — no EventBridge schedule)
  life-platform-data-reconciliation cron(30 7 ? * MON *) — Monday 12:30 AM PT

IAM roles: All per-function dedicated roles (SEC-1 compliant).
DLQ: Only freshness-checker has ingestion-dlq attached in AWS.
     All others: dlq=None.

Alarm mapping (AWS actual names):
  freshness-checker-errors       → Lambda/Errors, 24h period
  key-rotator-errors             → Lambda/Errors, 24h period
  life-platform-data-export-errors → Lambda/Errors, 24h period
  life-platform-canary-ddb-failure → LifePlatform/Canary CanaryDDBFail, 5m
  life-platform-canary-mcp-failure → LifePlatform/Canary CanaryMCPFail, 5m
  life-platform-canary-s3-failure  → LifePlatform/Canary CanaryS3Fail, 5m
  life-platform-canary-any-failure → LifePlatform/Canary CanaryDDBFail, 5m (matches ddb, see note)
  life-platform-dlq-depth-warning  → AWS/SQS ApproximateNumberOfMessagesVisible, 5m

Handler naming: <module>.lambda_handler
  Exception: freshness-checker and key-rotator use lambda_function.lambda_handler (AWS actual)

Import procedure (run once, after cdk synth):
  cdk import LifePlatformOperational --force

  Resources to provide physical IDs for:
    Each Lambda: use FunctionName
    Each EventBridge rule: use rule Name
    Each CloudWatch alarm: use AlarmName

After import:
  cdk deploy LifePlatformOperational --require-approval never
"""

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_sqs as sqs,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_sns as sns,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_events as events,
    aws_events_targets as targets,
)
from constructs import Construct

from stacks.lambda_helpers import create_platform_lambda

REGION = "us-west-2"
ACCT = "205930651321"

INGESTION_DLQ_ARN    = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
LIFE_PLATFORM_TABLE  = "life-platform"
LIFE_PLATFORM_BUCKET = "matthew-life-platform"
ALERTS_TOPIC_ARN     = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"

def _role(name): return f"arn:aws:iam::{ACCT}:role/{name}"

# All roles verified 2026-03-09 via aws lambda get-function-configuration --query Role
ROLE_ARNS = {
    "freshness":       _role("lambda-freshness-checker-role"),
    "dlq_consumer":    _role("lambda-dlq-consumer-role"),
    "canary":          _role("lambda-canary-role"),
    "pip_audit":       _role("lambda-pip-audit-role"),
    "qa_smoke":        _role("lambda-qa-smoke-role"),
    "key_rotator":     _role("lambda-key-rotator-role"),
    "data_export":     _role("lambda-data-export-role"),
    "reconciliation":  _role("lambda-data-reconciliation-role"),
}


class OperationalStack(Stack):

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        table: dynamodb.ITable,
        bucket: s3.IBucket,
        dlq: sqs.IQueue,
        alerts_topic: sns.ITopic,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── Local resource references ──
        local_dlq          = sqs.Queue.from_queue_arn(self, "IngestionDLQ", INGESTION_DLQ_ARN)
        local_table        = dynamodb.Table.from_table_name(self, "LifePlatformTable", LIFE_PLATFORM_TABLE)
        local_bucket       = s3.Bucket.from_bucket_name(self, "LifePlatformBucket", LIFE_PLATFORM_BUCKET)
        local_alerts_topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)

        # ── Shared kwargs ──
        # freshness-checker is the only Operational Lambda with a DLQ in AWS.
        # All others: dlq=None (no SQS perm on their roles either).
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
            alerts_topic=None,  # override per Lambda where needed
        )

        # ══════════════════════════════════════════════════════════════
        # 1. Freshness Checker — 9:45 AM PT daily
        # Alerts if any ingestion source is stale (no new data in 24h).
        # Has DLQ + error alarm; extra SLO/invocation alarms created below.
        # handler: lambda_function.lambda_handler — AWS actual (old convention)
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "FreshnessChecker",
            function_name="life-platform-freshness-checker",
            source_file="lambdas/freshness_checker_lambda.py",
            handler="lambda_function.lambda_handler",  # AWS actual — zip has lambda_function.py
            schedule="cron(45 16 * * ? *)",
            timeout_seconds=30,
            memory_mb=128,
            alarm_name="freshness-checker-errors",  # AWS actual alarm name
            existing_role_arn=ROLE_ARNS["freshness"],
            **shared_with_dlq,
        )

        # ══════════════════════════════════════════════════════════════
        # 2. DLQ Consumer — every 6 hours
        # Classifies + retries / archives messages from ingestion-dlq.
        # No DLQ itself (it IS the DLQ processor). No Lambda error alarm.
        # DLQ depth alarm is SQS-based (created below separately).
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "DlqConsumer",
            function_name="life-platform-dlq-consumer",
            source_file="lambdas/dlq_consumer_lambda.py",
            handler="dlq_consumer_lambda.lambda_handler",
            schedule="rate(6 hours)",
            timeout_seconds=120,
            memory_mb=256,
            existing_role_arn=ROLE_ARNS["dlq_consumer"],
            **shared_no_dlq,
        )

        # ══════════════════════════════════════════════════════════════
        # 3. Canary — every 4 hours
        # End-to-end synthetic health check: DDB + S3 + MCP round-trip.
        # No DLQ. Lambda error alarm omitted — canary uses custom metric
        # alarms (LifePlatform/Canary namespace) created below.
        # MCP_SECRET_NAME env var hardcoded — uses api-keys bundle.
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "Canary",
            function_name="life-platform-canary",
            source_file="lambdas/canary_lambda.py",
            handler="canary_lambda.lambda_handler",
            schedule="rate(4 hours)",
            timeout_seconds=60,
            memory_mb=256,
            environment={
                "MCP_FUNCTION_URL": "https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws/",
                "MCP_SECRET_NAME": "life-platform/api-keys",
            },
            existing_role_arn=ROLE_ARNS["canary"],
            **shared_no_dlq,
        )

        # ══════════════════════════════════════════════════════════════
        # 4. Pip Audit — every Monday
        # Scans 18 requirements files for known CVEs. Emails report.
        # AWS schedule is every Monday (not first-Monday-only).
        # No DLQ. No error alarm in AWS.
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "PipAudit",
            function_name="life-platform-pip-audit",
            source_file="lambdas/pip_audit_lambda.py",
            handler="pip_audit_lambda.lambda_handler",
            schedule="cron(0 17 ? * MON *)",
            timeout_seconds=300,
            memory_mb=512,
            environment={
                "EMAIL_RECIPIENT": "awsdev@mattsusername.com",
                "EMAIL_SENDER": "awsdev@mattsusername.com",
            },
            existing_role_arn=ROLE_ARNS["pip_audit"],
            **shared_no_dlq,
        )

        # ══════════════════════════════════════════════════════════════
        # 5. QA Smoke — daily 11:30 AM PT
        # Smoke tests critical platform paths. Emails results.
        # No DLQ. No error alarm in AWS.
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "QaSmoke",
            function_name="life-platform-qa-smoke",
            source_file="lambdas/qa_smoke_lambda.py",
            handler="qa_smoke_lambda.lambda_handler",
            schedule="cron(30 18 ? * * *)",
            timeout_seconds=120,
            memory_mb=256,
            environment={
                "EMAIL_RECIPIENT": "awsdev@mattsusername.com",
                "EMAIL_SENDER": "awsdev@mattsusername.com",
            },
            existing_role_arn=ROLE_ARNS["qa_smoke"],
            **shared_no_dlq,
        )

        # ══════════════════════════════════════════════════════════════
        # 6. Key Rotator
        # Triggered by Secrets Manager automatic rotation (not EventBridge).
        # Rotates life-platform/mcp-api-key every 90 days.
        # No env vars in AWS. handler: lambda_function.lambda_handler (old convention)
        # Error alarm: key-rotator-errors
        # ══════════════════════════════════════════════════════════════
        key_rotator = create_platform_lambda(
            self, "KeyRotator",
            function_name="life-platform-key-rotator",
            source_file="lambdas/key_rotator_lambda.py",
            handler="lambda_function.lambda_handler",  # AWS actual — old convention
            # No schedule — triggered by Secrets Manager rotation only
            timeout_seconds=30,
            memory_mb=128,
            alarm_name="key-rotator-errors",  # AWS actual alarm name
            existing_role_arn=ROLE_ARNS["key_rotator"],
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=local_alerts_topic,  # needs alert for rotation failures
        )

        # Secrets Manager rotation permission — allows SM to invoke this Lambda
        key_rotator.add_permission(
            "SecretsManagerInvokeKeyRotator",
            principal=iam.ServicePrincipal("secretsmanager.amazonaws.com"),
            source_arn=f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:life-platform/mcp-api-key-*",
        )

        # ══════════════════════════════════════════════════════════════
        # 7. Data Export
        # On-demand only — invoked via MCP tool or manual event.
        # No EventBridge schedule. Error alarm: life-platform-data-export-errors
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "DataExport",
            function_name="life-platform-data-export",
            source_file="lambdas/data_export_lambda.py",
            handler="data_export_lambda.lambda_handler",
            # No schedule
            timeout_seconds=300,
            memory_mb=512,
            alarm_name="life-platform-data-export-errors",  # AWS actual alarm name
            existing_role_arn=ROLE_ARNS["data_export"],
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=local_alerts_topic,
        )

        # ══════════════════════════════════════════════════════════════
        # 8. Data Reconciliation — Monday 12:30 AM PT
        # Weekly reconciliation: checks DDB completeness vs expected sources.
        # Emails report + archives to S3. No error alarm in AWS.
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "DataReconciliation",
            function_name="life-platform-data-reconciliation",
            source_file="lambdas/data_reconciliation_lambda.py",
            handler="data_reconciliation_lambda.lambda_handler",
            schedule="cron(30 7 ? * MON *)",
            timeout_seconds=120,
            memory_mb=256,
            environment={
                "EMAIL_RECIPIENT": "awsdev@mattsusername.com",
                "EMAIL_SENDER": "awsdev@mattsusername.com",
            },
            existing_role_arn=ROLE_ARNS["reconciliation"],
            **shared_no_dlq,
        )

        # ══════════════════════════════════════════════════════════════
        # Canary custom metric alarms
        # Published to LifePlatform/Canary namespace by canary_lambda.py.
        # Four alarms: any-failure, ddb-failure, mcp-failure, s3-failure.
        # Period: 300s (5 min). Threshold: 1 (any failure = alarm).
        #
        # Note: any-failure and ddb-failure both watch CanaryDDBFail metric
        # (verified from AWS describe-alarms). This matches observed behavior
        # where DDB is the most critical check — two alarms = two notification
        # paths or early import artifact. Preserved as-is.
        # ══════════════════════════════════════════════════════════════
        _canary_alarm_topic = local_alerts_topic

        def _canary_alarm(alarm_id: str, alarm_name: str, metric_name: str):
            metric = cloudwatch.Metric(
                namespace="LifePlatform/Canary",
                metric_name=metric_name,
                period=Duration.seconds(300),
                statistic="Sum",
            )
            alarm = cloudwatch.Alarm(
                self, alarm_id,
                alarm_name=alarm_name,
                metric=metric,
                evaluation_periods=1,
                threshold=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            )
            alarm.add_alarm_action(cw_actions.SnsAction(_canary_alarm_topic))
            alarm.add_ok_action(cw_actions.SnsAction(_canary_alarm_topic))

        _canary_alarm("CanaryAnyFailureAlarm",  "life-platform-canary-any-failure",  "CanaryDDBFail")
        _canary_alarm("CanaryDdbFailureAlarm",  "life-platform-canary-ddb-failure",  "CanaryDDBFail")
        _canary_alarm("CanaryMcpFailureAlarm",  "life-platform-canary-mcp-failure",  "CanaryMCPFail")
        _canary_alarm("CanaryS3FailureAlarm",   "life-platform-canary-s3-failure",   "CanaryS3Fail")

        # ══════════════════════════════════════════════════════════════
        # DLQ depth alarm — SQS metric, not Lambda metric
        # Fires when ingestion DLQ has ≥1 visible message.
        # Period: 300s, statistic: Maximum (not Sum — catches transient spikes).
        # ══════════════════════════════════════════════════════════════
        dlq_depth_metric = cloudwatch.Metric(
            namespace="AWS/SQS",
            metric_name="ApproximateNumberOfMessagesVisible",
            dimensions_map={"QueueName": "life-platform-ingestion-dlq"},
            period=Duration.seconds(300),
            statistic="Maximum",
        )
        dlq_depth_alarm = cloudwatch.Alarm(
            self, "DlqDepthAlarm",
            alarm_name="life-platform-dlq-depth-warning",
            metric=dlq_depth_metric,
            evaluation_periods=1,
            threshold=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        dlq_depth_alarm.add_alarm_action(cw_actions.SnsAction(local_alerts_topic))
        dlq_depth_alarm.add_ok_action(cw_actions.SnsAction(local_alerts_topic))

        # ══════════════════════════════════════════════════════════════
        # Outputs
        # ══════════════════════════════════════════════════════════════
        cdk.CfnOutput(self, "FreshnessCheckerArn",
            value=f"arn:aws:lambda:{REGION}:{ACCT}:function:life-platform-freshness-checker",
            description="Freshness checker Lambda ARN",
        )
        cdk.CfnOutput(self, "CanaryArn",
            value=f"arn:aws:lambda:{REGION}:{ACCT}:function:life-platform-canary",
            description="Canary Lambda ARN",
        )
