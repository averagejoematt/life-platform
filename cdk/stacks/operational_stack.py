"""
OperationalStack — Platform health, safety, and lifecycle Lambdas.

Lambdas (8):
  life-platform-freshness-checker   cron(45 16 * * ? *)  — 9:45 AM PT daily
  life-platform-dlq-consumer        rate(6 hours)
  life-platform-canary              rate(4 hours)
  life-platform-pip-audit           cron(0 17 ? * MON *) — Every Monday
  life-platform-qa-smoke            cron(30 18 ? * * *)  — Daily 11:30 AM PT
  life-platform-key-rotator         (Secrets Manager rotation trigger only)
  life-platform-data-export         (on-demand only)
  life-platform-data-reconciliation cron(30 7 ? * MON *) — Monday 12:30 AM PT

EventBridge rules are NOT managed by CDK — they already exist in AWS.
Updating imported rules via CloudFormation fails with "Internal Failure"
(same issue as IngestionStack). Rules are managed as unmanaged drift.

CDK manages ONLY:
  - Lambda functions (code, config, env vars)
  - CloudWatch error alarms
  - Lambda::Permission resources (allow EB/SM to invoke)

Lambda::Permissions added via fn.add_permission() with hardcoded rule ARNs.
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
def _rule_arn(name): return f"arn:aws:events:{REGION}:{ACCT}:rule/{name}"

# All roles verified 2026-03-09 via aws lambda get-function-configuration --query Role
ROLE_ARNS = {
    "freshness":      _role("lambda-freshness-checker-role"),
    "dlq_consumer":   _role("lambda-dlq-consumer-role"),
    "canary":         _role("lambda-canary-role"),
    "pip_audit":      _role("lambda-pip-audit-role"),
    "qa_smoke":       _role("lambda-qa-smoke-role"),
    "key_rotator":    _role("lambda-key-rotator-role"),
    "data_export":    _role("lambda-data-export-role"),
    "reconciliation": _role("lambda-data-reconciliation-role"),
}

# EventBridge rule names (verified 2026-03-09 via aws events list-rules)
RULE_NAMES = {
    "freshness":      "life-platform-freshness-check",
    "dlq_consumer":   "dlq-consumer-schedule",
    "canary":         "canary-schedule",
    "pip_audit":      "life-platform-pip-audit-monthly",
    "qa_smoke":       "life-platform-qa-smoke",
    "reconciliation": "life-platform-data-reconciliation-weekly",
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

        local_dlq          = sqs.Queue.from_queue_arn(self, "IngestionDLQ", INGESTION_DLQ_ARN)
        local_table        = dynamodb.Table.from_table_name(self, "LifePlatformTable", LIFE_PLATFORM_TABLE)
        local_bucket       = s3.Bucket.from_bucket_name(self, "LifePlatformBucket", LIFE_PLATFORM_BUCKET)
        local_alerts_topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)

        eb_principal = iam.ServicePrincipal("events.amazonaws.com")

        # ══════════════════════════════════════════════════════════════
        # 1. Freshness Checker — EXCLUDED from this stack
        # life-platform-freshness-checker is managed in its own individual
        # CloudFormation stack (life-platform-freshness-checker), which
        # pre-dates CDK. Cannot import into LifePlatformOperational while
        # it exists in another stack. Options for later:
        #   A. Delete the individual stack + redeploy Lambda via deploy_lambda.sh
        #      then import here on next session.
        #   B. Leave as-is (Lambda runs fine, alarm managed in that stack).
        # The freshness-checker-errors alarm IS imported here (see below)
        # since the alarm lives outside the individual stack.
        # ══════════════════════════════════════════════════════════════
        # freshness-checker-errors alarm exists in AWS outside the individual
        # Lambda stack — import it here so CDK tracks it.
        # (The Lambda itself is excluded above.)
        cloudwatch.Alarm(
            self, "FreshnessCheckerErrorAlarm",
            alarm_name="freshness-checker-errors",
            metric=cloudwatch.Metric(
                namespace="AWS/Lambda",
                metric_name="Errors",
                dimensions_map={"FunctionName": "life-platform-freshness-checker"},
                period=Duration.hours(24),
                statistic="Sum",
            ),
            evaluation_periods=1,
            threshold=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        # ══════════════════════════════════════════════════════════════
        # 2. DLQ Consumer — every 6 hours, no DLQ, no alarm
        # ══════════════════════════════════════════════════════════════
        dlq_consumer = create_platform_lambda(
            self, "DlqConsumer",
            function_name="life-platform-dlq-consumer",
            source_file="lambdas/dlq_consumer_lambda.py",
            handler="dlq_consumer_lambda.lambda_handler",
            timeout_seconds=120,
            memory_mb=256,
            existing_role_arn=ROLE_ARNS["dlq_consumer"],
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=None,
        )
        dlq_consumer.add_permission("EBDlqConsumer",
            principal=eb_principal,
            source_arn=_rule_arn(RULE_NAMES["dlq_consumer"]),
        )

        # ══════════════════════════════════════════════════════════════
        # 3. Canary — every 4 hours, no DLQ
        # Uses custom CloudWatch metric alarms (created below)
        # ══════════════════════════════════════════════════════════════
        canary = create_platform_lambda(
            self, "Canary",
            function_name="life-platform-canary",
            source_file="lambdas/canary_lambda.py",
            handler="canary_lambda.lambda_handler",
            timeout_seconds=60,
            memory_mb=256,
            environment={
                "MCP_FUNCTION_URL": "https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws/",
                "MCP_SECRET_NAME": "life-platform/api-keys",
            },
            existing_role_arn=ROLE_ARNS["canary"],
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=None,
        )
        canary.add_permission("EBCanary",
            principal=eb_principal,
            source_arn=_rule_arn(RULE_NAMES["canary"]),
        )

        # ══════════════════════════════════════════════════════════════
        # 4. Pip Audit — every Monday, no DLQ, no alarm
        # ══════════════════════════════════════════════════════════════
        pip_audit = create_platform_lambda(
            self, "PipAudit",
            function_name="life-platform-pip-audit",
            source_file="lambdas/pip_audit_lambda.py",
            handler="pip_audit_lambda.lambda_handler",
            timeout_seconds=300,
            memory_mb=512,
            environment={
                "EMAIL_RECIPIENT": "awsdev@mattsusername.com",
                "EMAIL_SENDER": "awsdev@mattsusername.com",
            },
            existing_role_arn=ROLE_ARNS["pip_audit"],
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=None,
        )
        pip_audit.add_permission("EBPipAudit",
            principal=eb_principal,
            source_arn=_rule_arn(RULE_NAMES["pip_audit"]),
        )

        # ══════════════════════════════════════════════════════════════
        # 5. QA Smoke — daily 11:30 AM PT, no DLQ, no alarm
        # ══════════════════════════════════════════════════════════════
        qa_smoke = create_platform_lambda(
            self, "QaSmoke",
            function_name="life-platform-qa-smoke",
            source_file="lambdas/qa_smoke_lambda.py",
            handler="qa_smoke_lambda.lambda_handler",
            timeout_seconds=120,
            memory_mb=256,
            environment={
                "EMAIL_RECIPIENT": "awsdev@mattsusername.com",
                "EMAIL_SENDER": "awsdev@mattsusername.com",
            },
            existing_role_arn=ROLE_ARNS["qa_smoke"],
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=None,
        )
        qa_smoke.add_permission("EBQaSmoke",
            principal=eb_principal,
            source_arn=_rule_arn(RULE_NAMES["qa_smoke"]),
        )

        # ══════════════════════════════════════════════════════════════
        # 6. Key Rotator — Secrets Manager rotation trigger only, error alarm
        # handler: lambda_function.lambda_handler (AWS actual, old convention)
        # No env vars in AWS.
        # ══════════════════════════════════════════════════════════════
        key_rotator = create_platform_lambda(
            self, "KeyRotator",
            function_name="life-platform-key-rotator",
            source_file="lambdas/key_rotator_lambda.py",
            handler="lambda_function.lambda_handler",  # AWS actual
            timeout_seconds=30,
            memory_mb=128,
            alarm_name="key-rotator-errors",
            existing_role_arn=ROLE_ARNS["key_rotator"],
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=local_alerts_topic,
        )
        key_rotator.add_permission("SecretsManagerInvokeKeyRotator",
            principal=iam.ServicePrincipal("secretsmanager.amazonaws.com"),
            source_arn=f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:life-platform/mcp-api-key-*",
        )

        # ══════════════════════════════════════════════════════════════
        # 7. Data Export — on-demand only, error alarm
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "DataExport",
            function_name="life-platform-data-export",
            source_file="lambdas/data_export_lambda.py",
            handler="data_export_lambda.lambda_handler",
            timeout_seconds=300,
            memory_mb=512,
            alarm_name="life-platform-data-export-errors",
            existing_role_arn=ROLE_ARNS["data_export"],
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=local_alerts_topic,
        )

        # ══════════════════════════════════════════════════════════════
        # 8. Data Reconciliation — Monday 12:30 AM PT, no alarm
        # ══════════════════════════════════════════════════════════════
        reconciliation = create_platform_lambda(
            self, "DataReconciliation",
            function_name="life-platform-data-reconciliation",
            source_file="lambdas/data_reconciliation_lambda.py",
            handler="data_reconciliation_lambda.lambda_handler",
            timeout_seconds=120,
            memory_mb=256,
            environment={
                "EMAIL_RECIPIENT": "awsdev@mattsusername.com",
                "EMAIL_SENDER": "awsdev@mattsusername.com",
            },
            existing_role_arn=ROLE_ARNS["reconciliation"],
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=None,
        )
        reconciliation.add_permission("EBReconciliation",
            principal=eb_principal,
            source_arn=_rule_arn(RULE_NAMES["reconciliation"]),
        )

        # ══════════════════════════════════════════════════════════════
        # Canary custom metric alarms (LifePlatform/Canary namespace)
        # any-failure and ddb-failure both watch CanaryDDBFail — AWS actual
        # ══════════════════════════════════════════════════════════════
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
            alarm.add_alarm_action(cw_actions.SnsAction(local_alerts_topic))
            alarm.add_ok_action(cw_actions.SnsAction(local_alerts_topic))

        _canary_alarm("CanaryAnyFailureAlarm", "life-platform-canary-any-failure", "CanaryDDBFail")
        _canary_alarm("CanaryDdbFailureAlarm", "life-platform-canary-ddb-failure", "CanaryDDBFail")
        _canary_alarm("CanaryMcpFailureAlarm", "life-platform-canary-mcp-failure", "CanaryMCPFail")
        _canary_alarm("CanaryS3FailureAlarm",  "life-platform-canary-s3-failure",  "CanaryS3Fail")

        # ══════════════════════════════════════════════════════════════
        # DLQ depth alarm — SQS metric, Maximum statistic
        # ══════════════════════════════════════════════════════════════
        dlq_depth_alarm = cloudwatch.Alarm(
            self, "DlqDepthAlarm",
            alarm_name="life-platform-dlq-depth-warning",
            metric=cloudwatch.Metric(
                namespace="AWS/SQS",
                metric_name="ApproximateNumberOfMessagesVisible",
                dimensions_map={"QueueName": "life-platform-ingestion-dlq"},
                period=Duration.seconds(300),
                statistic="Maximum",
            ),
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
            description="Freshness checker Lambda ARN (managed in separate stack)",
        )
        cdk.CfnOutput(self, "CanaryArn",
            value=canary.function_arn,
            description="Canary Lambda ARN",
        )
