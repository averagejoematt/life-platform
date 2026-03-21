"""
OperationalStack — Platform health, safety, and lifecycle Lambdas.

v2.1 (v3.4.0): CDK-managed IAM roles + CDK-managed EventBridge rules.
  All Lambdas have dedicated CDK-owned roles with least-privilege policies.
  EventBridge rules created via schedule= (no more add_permission workaround).
  Freshness-checker and insight-email-parser added (previously unmanaged).

Lambdas (9):
  life-platform-freshness-checker   cron(45 16 * * ? *)     — 9:45 AM PT daily
  life-platform-dlq-consumer        rate(6 hours)
  life-platform-canary              rate(4 hours)
  life-platform-pip-audit           cron(0 17 ? * MON *)    — Every Monday
  life-platform-qa-smoke            cron(30 18 ? * * *)     — Daily 11:30 AM PT
  life-platform-key-rotator         (Secrets Manager rotation trigger only)
  life-platform-data-export         (on-demand only)
  life-platform-data-reconciliation cron(30 7 ? * MON *)    — Monday 12:30 AM PT
  insight-email-parser              (SES inbound trigger only)
"""

import aws_cdk as cdk
from aws_cdk import (
    Stack, Duration,
    aws_lambda as _lambda, aws_iam as iam, aws_sqs as sqs,
    aws_dynamodb as dynamodb, aws_s3 as s3, aws_sns as sns,
    aws_cloudwatch as cloudwatch, aws_cloudwatch_actions as cw_actions,
)
from constructs import Construct
from stacks.lambda_helpers import create_platform_lambda
from stacks import role_policies as rp

# ── R17-09 cross-region note ──────────────────────────────────────────────────
# site-api Lambda lives here (us-west-2) so it shares a region with DynamoDB.
# CloudFront (web_stack, us-east-1) references the Function URL as a custom
# origin — cross-region Function URL origins are fully supported by CloudFront.
# Migration from web_stack:
#   1. Deploy LifePlatformOperational → capture SiteApiFunctionUrlDomain output
#   2. Set context: cdk.json "site_api_fn_url_domain": "<captured-domain>"
#   3. Run cdk deploy LifePlatformWeb (web_stack will import via context var)
# ──────────────────────────────────────────────────────────────────────────────

REGION = "us-west-2"
ACCT = "205930651321"
INGESTION_DLQ_ARN    = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
LIFE_PLATFORM_TABLE  = "life-platform"
LIFE_PLATFORM_BUCKET = "matthew-life-platform"
ALERTS_TOPIC_ARN     = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"


class OperationalStack(Stack):
    def __init__(self, scope, construct_id, table, bucket, dlq, alerts_topic, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        local_dlq          = sqs.Queue.from_queue_arn(self, "IngestionDLQ", INGESTION_DLQ_ARN)
        local_table        = dynamodb.Table.from_table_name(self, "LifePlatformTable", LIFE_PLATFORM_TABLE)
        local_bucket       = s3.Bucket.from_bucket_name(self, "LifePlatformBucket", LIFE_PLATFORM_BUCKET)
        local_alerts_topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)

        # ── 1. Freshness Checker — 9:45 AM PT daily (previously in separate CFn stack)
        freshness = create_platform_lambda(self, "FreshnessChecker",
            function_name="life-platform-freshness-checker",
            source_file="lambdas/freshness_checker_lambda.py",
            handler="freshness_checker_lambda.lambda_handler",
            schedule="cron(45 16 * * ? *)",
            timeout_seconds=30, memory_mb=128,
            environment={
                "EMAIL_RECIPIENT": "awsdev@mattsusername.com",
                "EMAIL_SENDER": "awsdev@mattsusername.com",
                "SNS_ARN": f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts",
            },
            custom_policies=rp.operational_freshness_checker(),
            table=local_table, bucket=local_bucket, dlq=None, alerts_topic=local_alerts_topic,
            alarm_name="freshness-checker-errors",
        )

        # ── 2. DLQ Consumer — every 6 hours
        create_platform_lambda(self, "DlqConsumer",
            function_name="life-platform-dlq-consumer",
            source_file="lambdas/dlq_consumer_lambda.py",
            handler="dlq_consumer_lambda.lambda_handler",
            schedule="rate(6 hours)",
            timeout_seconds=120, memory_mb=256,
            custom_policies=rp.operational_dlq_consumer(),
            table=local_table, bucket=local_bucket, dlq=None, alerts_topic=None,
        )

        # ── 3. Canary — every 4 hours
        canary = create_platform_lambda(self, "Canary",
            function_name="life-platform-canary",
            source_file="lambdas/canary_lambda.py",
            handler="canary_lambda.lambda_handler",
            schedule="rate(4 hours)",
            timeout_seconds=60, memory_mb=256,
            environment={
                "MCP_FUNCTION_URL": "https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws/",
                "MCP_SECRET_NAME": "life-platform/ai-keys",
            },
            custom_policies=rp.operational_canary(),
            table=local_table, bucket=local_bucket, dlq=None, alerts_topic=None,
        )

        # ── 4. Pip Audit — every Monday
        create_platform_lambda(self, "PipAudit",
            function_name="life-platform-pip-audit",
            source_file="lambdas/pip_audit_lambda.py",
            handler="pip_audit_lambda.lambda_handler",
            schedule="cron(0 17 ? * MON *)",
            timeout_seconds=300, memory_mb=512,
            environment={"EMAIL_RECIPIENT": "awsdev@mattsusername.com", "EMAIL_SENDER": "awsdev@mattsusername.com"},
            custom_policies=rp.operational_pip_audit(),
            table=local_table, bucket=local_bucket, dlq=None, alerts_topic=None,
        )

        # ── 5. QA Smoke — daily 11:30 AM PT
        create_platform_lambda(self, "QaSmoke",
            function_name="life-platform-qa-smoke",
            source_file="lambdas/qa_smoke_lambda.py",
            handler="qa_smoke_lambda.lambda_handler",
            schedule="cron(30 18 ? * * *)",
            timeout_seconds=120, memory_mb=256,
            environment={
                "EMAIL_RECIPIENT": "awsdev@mattsusername.com",
                "EMAIL_SENDER": "awsdev@mattsusername.com",
                "MCP_FUNCTION_URL": "https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws/",
                "MCP_SECRET_NAME": "life-platform/mcp-api-key",
            },
            custom_policies=rp.operational_qa_smoke(),
            table=local_table, bucket=local_bucket, dlq=None, alerts_topic=None,
        )

        # ── 6. Key Rotator — Secrets Manager rotation trigger only
        key_rotator = create_platform_lambda(self, "KeyRotator",
            function_name="life-platform-key-rotator",
            source_file="lambdas/key_rotator_lambda.py",
            handler="key_rotator_lambda.lambda_handler",
            timeout_seconds=30, memory_mb=128,
            alarm_name="key-rotator-errors",
            custom_policies=rp.operational_key_rotator(),
            table=local_table, bucket=local_bucket, dlq=None, alerts_topic=local_alerts_topic,
        )
        key_rotator.add_permission("SecretsManagerInvokeKeyRotator",
            principal=iam.ServicePrincipal("secretsmanager.amazonaws.com"),
            source_arn=f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:life-platform/mcp-api-key-*",
        )

        # ── 7. Data Export — on-demand only
        create_platform_lambda(self, "DataExport",
            function_name="life-platform-data-export",
            source_file="lambdas/data_export_lambda.py",
            handler="data_export_lambda.lambda_handler",
            timeout_seconds=300, memory_mb=512,
            alarm_name="life-platform-data-export-errors",
            custom_policies=rp.operational_data_export(),
            table=local_table, bucket=local_bucket, dlq=None, alerts_topic=local_alerts_topic,
        )

        # ── 8. Data Reconciliation — Monday 12:30 AM PT
        create_platform_lambda(self, "DataReconciliation",
            function_name="life-platform-data-reconciliation",
            source_file="lambdas/data_reconciliation_lambda.py",
            handler="data_reconciliation_lambda.lambda_handler",
            schedule="cron(30 7 ? * MON *)",
            timeout_seconds=120, memory_mb=256,
            environment={"EMAIL_RECIPIENT": "awsdev@mattsusername.com", "EMAIL_SENDER": "awsdev@mattsusername.com"},
            custom_policies=rp.operational_data_reconciliation(),
            table=local_table, bucket=local_bucket, dlq=None, alerts_topic=None,
        )

        # ── 9. Insight Email Parser — SES inbound trigger (previously unmanaged)
        insight_parser = create_platform_lambda(self, "InsightEmailParser",
            function_name="insight-email-parser",
            source_file="lambdas/insight_email_parser_lambda.py",
            handler="insight_email_parser_lambda.lambda_handler",
            timeout_seconds=30, memory_mb=128,
            environment={
                "ALLOWED_SENDERS": "awsdev@mattsusername.com,mattsthrowaway@protonmail.com",
            },
            custom_policies=rp.operational_insight_email_parser(),
            table=local_table, bucket=local_bucket, dlq=None, alerts_topic=None,
        )
        insight_parser.add_permission("SESInvokeInsightParser",
            principal=iam.ServicePrincipal("ses.amazonaws.com"),
            source_arn=f"arn:aws:ses:{REGION}:{ACCT}:receipt-rule-set/*",
        )

        # ── Canary custom metric alarms ──
        def _canary_alarm(aid, aname, mname):
            a = cloudwatch.Alarm(self, aid, alarm_name=aname, metric=cloudwatch.Metric(namespace="LifePlatform/Canary", metric_name=mname, period=Duration.seconds(300), statistic="Sum"), evaluation_periods=1, threshold=1, comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD, treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING)
            a.add_alarm_action(cw_actions.SnsAction(local_alerts_topic)); a.add_ok_action(cw_actions.SnsAction(local_alerts_topic))
        # NOTE: CanaryAnyFailureAlarm removed 2026-03-10 — bug: watched CanaryDDBFail
        # (identical to canary-ddb-failure). The 3 individual alarms below provide full coverage.
        _canary_alarm("CanaryDdbFailureAlarm", "life-platform-canary-ddb-failure", "CanaryDDBFail")
        _canary_alarm("CanaryMcpFailureAlarm", "life-platform-canary-mcp-failure", "CanaryMCPFail")
        _canary_alarm("CanaryS3FailureAlarm", "life-platform-canary-s3-failure", "CanaryS3Fail")

        # ── DLQ depth alarm ──
        dlq_depth = cloudwatch.Alarm(self, "DlqDepthAlarm", alarm_name="life-platform-dlq-depth-warning", metric=cloudwatch.Metric(namespace="AWS/SQS", metric_name="ApproximateNumberOfMessagesVisible", dimensions_map={"QueueName": "life-platform-ingestion-dlq"}, period=Duration.seconds(300), statistic="Maximum"), evaluation_periods=1, threshold=1, comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD, treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING)
        dlq_depth.add_alarm_action(cw_actions.SnsAction(local_alerts_topic)); dlq_depth.add_ok_action(cw_actions.SnsAction(local_alerts_topic))

        # ── 10. Site API Lambda — life-platform-site-api (R17-09: moved from web_stack us-east-1)
        # Read-only. DynamoDB same-region (eliminates cross-region latency).
        # Function URL is a global HTTPS endpoint — CloudFront in us-east-1 can origin to it.
        site_api_fn = create_platform_lambda(self, "SiteApiLambda",
            function_name="life-platform-site-api",
            source_file="lambdas/site_api_lambda.py",
            handler="site_api_lambda.lambda_handler",
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=None,
            custom_policies=rp.site_api(),
            timeout_seconds=15,
            memory_mb=256,
            environment={
                "USER_ID":        "matthew",
                "TABLE_NAME":     "life-platform",
                "AI_SECRET_NAME": "life-platform/site-api-ai-key",
            },
        )

        site_api_url = site_api_fn.add_function_url(
            auth_type=_lambda.FunctionUrlAuthType.NONE,
            cors=_lambda.FunctionUrlCorsOptions(
                allowed_origins=["https://averagejoematt.com", "https://www.averagejoematt.com"],
                allowed_methods=[_lambda.HttpMethod.GET, _lambda.HttpMethod.POST],
                allowed_headers=["Content-Type"],
            ),
        )

        site_api_fn_url_domain = cdk.Fn.select(2, cdk.Fn.split("/", site_api_url.url))

        # ── Site API CloudWatch alarms + dashboard (moved from web_stack — alarms must be same region as Lambda)
        GTE = cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD

        site_api_errors = cloudwatch.Metric(
            namespace="AWS/Lambda", metric_name="Errors",
            dimensions_map={"FunctionName": "life-platform-site-api"},
            period=Duration.minutes(5), statistic="Sum",
        )
        site_api_invocations = cloudwatch.Metric(
            namespace="AWS/Lambda", metric_name="Invocations",
            dimensions_map={"FunctionName": "life-platform-site-api"},
            period=Duration.minutes(5), statistic="Sum",
        )
        site_api_duration_p95 = cloudwatch.Metric(
            namespace="AWS/Lambda", metric_name="Duration",
            dimensions_map={"FunctionName": "life-platform-site-api"},
            period=Duration.minutes(5), statistic="p95",
        )
        site_api_duration_p50 = cloudwatch.Metric(
            namespace="AWS/Lambda", metric_name="Duration",
            dimensions_map={"FunctionName": "life-platform-site-api"},
            period=Duration.minutes(5), statistic="p50",
        )

        cloudwatch.Alarm(self, "SiteApiErrors", alarm_name="site-api-errors",
            metric=site_api_errors, threshold=1, evaluation_periods=1,
            comparison_operator=GTE, treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING)

        cloudwatch.Alarm(self, "SiteApiLatencyHigh", alarm_name="site-api-p95-latency-high",
            metric=site_api_duration_p95, threshold=5000, evaluation_periods=1,
            comparison_operator=GTE, treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING)

        cloudwatch.Alarm(self, "SiteApiInvocationSpike", alarm_name="site-api-invocation-spike",
            metric=site_api_invocations, threshold=200, evaluation_periods=1,
            comparison_operator=GTE, treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING)

        cloudwatch.Dashboard(self, "SiteApiDashboard", dashboard_name="life-platform-site-api",
            widgets=[[
                cloudwatch.GraphWidget(title="Invocations", left=[site_api_invocations], width=8),
                cloudwatch.GraphWidget(title="Errors", left=[site_api_errors], width=8),
                cloudwatch.GraphWidget(title="Duration (p50 / p95)", left=[site_api_duration_p50, site_api_duration_p95], width=8),
            ]])

        cdk.CfnOutput(self, "FreshnessCheckerArn", value=freshness.function_arn, description="Freshness checker Lambda ARN")
        cdk.CfnOutput(self, "CanaryArn", value=canary.function_arn, description="Canary Lambda ARN")
        cdk.CfnOutput(self, "SiteApiFunctionUrl",
            value=site_api_url.url,
            description="Lambda Function URL for life-platform-site-api (us-west-2) — R17-09",
        )
        cdk.CfnOutput(self, "SiteApiFunctionUrlDomain",
            value=site_api_fn_url_domain,
            description="Function URL domain (without https://) — use in web_stack CloudFront origin after R17-09 migration",
        )
