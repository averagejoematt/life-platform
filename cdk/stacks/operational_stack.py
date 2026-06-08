"""
OperationalStack — Platform health, safety, and lifecycle Lambdas.

v2.1 (v3.4.0): CDK-managed IAM roles + CDK-managed EventBridge rules.
  All Lambdas have dedicated CDK-owned roles with least-privilege policies.
  EventBridge rules created via schedule= (no more add_permission workaround).
  Freshness-checker and insight-email-parser added (previously unmanaged).

Lambdas (11):
  life-platform-freshness-checker   cron(45 16 * * ? *)     — 9:45 AM PT daily
  life-platform-dlq-consumer        rate(6 hours)
  life-platform-canary              rate(4 hours)
  life-platform-pip-audit           cron(0 17 ? * MON *)    — Every Monday
  life-platform-qa-smoke            cron(30 18 ? * * *)     — Daily 11:30 AM PT
  life-platform-key-rotator         (Secrets Manager rotation trigger only)
  life-platform-data-export         (on-demand only)
  life-platform-data-reconciliation cron(30 7 ? * MON *)    — Monday 12:30 AM PT
  insight-email-parser              (SES inbound trigger only)
  site-stats-refresh                4x/day (15:00, 19:00, 23:00, 03:00 UTC) — no AI calls
  og-image-generator                cron(30 19 * * ? *)     — 11:30 AM PT daily (HP-13)
"""

import aws_cdk as cdk
from aws_cdk import (
    Stack, Duration,
    aws_lambda as _lambda, aws_iam as iam, aws_sqs as sqs,
    aws_dynamodb as dynamodb, aws_s3 as s3, aws_sns as sns,
    aws_sns_subscriptions as sns_subs,
    aws_cloudwatch as cloudwatch, aws_cloudwatch_actions as cw_actions,
    aws_events as events, aws_events_targets as targets,
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
DIGEST_TOPIC_ARN     = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts-digest"


class OperationalStack(Stack):
    def __init__(self, scope, construct_id, table, bucket, dlq, alerts_topic, digest_topic=None, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        local_dlq          = sqs.Queue.from_queue_arn(self, "IngestionDLQ", INGESTION_DLQ_ARN)
        local_table        = dynamodb.Table.from_table_name(self, "LifePlatformTable", LIFE_PLATFORM_TABLE)
        local_bucket       = s3.Bucket.from_bucket_name(self, "LifePlatformBucket", LIFE_PLATFORM_BUCKET)
        local_alerts_topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)
        local_digest_topic = sns.Topic.from_topic_arn(self, "DigestTopic", DIGEST_TOPIC_ARN)
        # Phase B re-entry sweep (2026-05-03): shared layer for Lambdas that import
        # platform_logger (currently freshness-checker + canary). They have a
        # try/except ImportError fallback to stdlib logging, so the missing layer
        # was hidden — but TD-20 platform_logger fix never reached freshness-checker
        # (still pinned at v19). Other operational Lambdas (site-api, key-rotator,
        # pip-audit, etc.) don't import shared modules so don't need the layer.
        from stacks.constants import SHARED_LAYER_ARN
        shared_utils_layer = _lambda.LayerVersion.from_layer_version_arn(
            self, "SharedUtilsLayer", SHARED_LAYER_ARN,
        )

        # ── 1. Freshness Checker — 9:45 AM PT daily (previously in separate CFn stack)
        # ADR-052: SNS_ARN points to the digest topic. The freshness checker's
        # direct publishes (stale-source / partial-completeness / OAuth-token-stale)
        # are exactly the "4 stale source(s)" daily emails we want to batch.
        freshness = create_platform_lambda(self, "FreshnessChecker",
            function_name="life-platform-freshness-checker",
            source_file="lambdas/emails/freshness_checker_lambda.py",
            handler="emails.freshness_checker_lambda.lambda_handler",
            schedule="cron(45 16 * * ? *)",
            timeout_seconds=30, memory_mb=128,
            environment={
                "EMAIL_RECIPIENT": "awsdev@mattsusername.com",
                "EMAIL_SENDER": "awsdev@mattsusername.com",
                "SNS_ARN": DIGEST_TOPIC_ARN,
            },
            custom_policies=rp.operational_freshness_checker(),
            table=local_table, bucket=local_bucket, dlq=None,
            alerts_topic=local_alerts_topic, digest_topic=local_digest_topic, digest=True,
            alarm_name="freshness-checker-errors",
            shared_layer=shared_utils_layer,
        )

        # ── 2. DLQ Consumer — every 6 hours
        create_platform_lambda(self, "DlqConsumer",
            function_name="life-platform-dlq-consumer",
            source_file="lambdas/operational/dlq_consumer_lambda.py",
            handler="operational.dlq_consumer_lambda.lambda_handler",
            schedule="rate(6 hours)",
            timeout_seconds=120, memory_mb=256,
            environment={
                # 2026-05-26: DLQ_URL was never wired in CDK; the Lambda
                # required it (see lambda body) but only ever got default
                # env from create_platform_lambda. Result: every scheduled
                # fire logged "DLQ_URL not set" and returned 500 silently.
                # The Lambda comment says "set from deploy script" but no
                # such script exists. Wired here now.
                "DLQ_URL": f"https://sqs.{REGION}.amazonaws.com/{ACCT}/life-platform-ingestion-dlq",
            },
            custom_policies=rp.operational_dlq_consumer(),
            table=local_table, bucket=local_bucket, dlq=None, alerts_topic=None,
        )

        # ── 2b. Alert Digest (ADR-050) — drains digest queue daily at 8 AM PT
        # SQS retention is 25h so the daily run never misses a fire that happened
        # during the previous 24h window. SNS raw message delivery puts the
        # CloudWatch alarm JSON directly into the SQS body (no envelope).
        digest_queue = sqs.Queue(self, "AlertDigestQueue",
            queue_name="life-platform-alerts-digest-queue",
            retention_period=Duration.hours(25),
            visibility_timeout=Duration.seconds(120),
        )
        # Subscribe the queue to the digest SNS topic (raw delivery for simpler parsing).
        local_digest_topic.add_subscription(
            sns_subs.SqsSubscription(digest_queue, raw_message_delivery=True),
        )

        digest_lambda = create_platform_lambda(self, "AlertDigest",
            function_name="life-platform-alert-digest",
            source_file="lambdas/operational/alert_digest_lambda.py",
            handler="operational.alert_digest_lambda.lambda_handler",
            # cron(0 15 * * ? *) = 15:00 UTC = 8 AM PT (UTC-fixed, no DST drift).
            schedule="cron(0 15 * * ? *)",
            timeout_seconds=60, memory_mb=128,
            environment={
                "DIGEST_QUEUE_URL": digest_queue.queue_url,
                "EMAIL_RECIPIENT":  "awsdev@mattsusername.com",
                "EMAIL_SENDER":     "awsdev@mattsusername.com",
            },
            custom_policies=rp.operational_alert_digest(),
            table=local_table, bucket=local_bucket, dlq=None, alerts_topic=None,
            shared_layer=shared_utils_layer,
        )
        cdk.CfnOutput(self, "AlertDigestQueueUrl", value=digest_queue.queue_url)
        cdk.CfnOutput(self, "AlertDigestLambdaArn", value=digest_lambda.function_arn)

        # ── 3. Canary — every 4 hours
        canary = create_platform_lambda(self, "Canary",
            function_name="life-platform-canary",
            source_file="lambdas/operational/canary_lambda.py",
            handler="operational.canary_lambda.lambda_handler",
            schedule="rate(4 hours)",
            timeout_seconds=60, memory_mb=256,
            environment={
                "MCP_FUNCTION_URL": "https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws/",
                "MCP_SECRET_NAME": "life-platform/mcp-api-key",
            },
            custom_policies=rp.operational_canary(),
            table=local_table, bucket=local_bucket, dlq=None, alerts_topic=None,
            shared_layer=shared_utils_layer,
        )

        # ── 3b. Cost Governor — budget-tier estimator (budget guardrails)
        # Estimates near-real-time spend (Cost Explorer non-AI + Bedrock token
        # metrics) and writes /life-platform/budget-tier to SSM. The AI features
        # read it (budget_guard) to degrade gracefully; bedrock_client enforces
        # the Tier-3 hard stop. AWS Budgets is the lagged backstop.
        # Cadence: every 4h (was hourly). Each run makes one Cost Explorer
        # GetCostAndUsage call ($0.01 each) — hourly was ~$2-4/mo of self-cost to
        # poll a slow-moving non-AI bill. 6×/day keeps the tier fresh enough (the
        # fast-moving AI half is priced from cheap CloudWatch token metrics, and
        # public AI is rate-limited + the AWS Budget alerts independently) while
        # cutting the CE-API line ~80%.
        create_platform_lambda(self, "CostGovernor",
            function_name="life-platform-cost-governor",
            source_file="lambdas/operational/cost_governor_lambda.py",
            handler="operational.cost_governor_lambda.lambda_handler",
            schedule="cron(0 0/4 * * ? *)",  # every 4 hours (CE self-cost reduction)
            timeout_seconds=60, memory_mb=256,
            # 2026-05-29: enforcement ENABLED — the projection fix makes the
            # estimate reliable (projected ~$45, Tier 0). Writes the SSM tier +
            # alerts on change; budget_guard then gates AI. Set OBSERVE_MODE=true
            # to revert to observe-only.
            environment={"OBSERVE_MODE": "false"},
            custom_policies=rp.operational_cost_governor(),
            table=local_table, bucket=local_bucket, dlq=None, alerts_topic=None,
            shared_layer=shared_utils_layer,
        )

        # ── 3c. Remediation Dispatcher — SNS-subscribed urgent-alarm → GH dispatch
        # Closes the urgent-alarm latency the daily 07:45 PT sweep can't cover.
        # Subscribes to life-platform-alerts (urgent topic), filters to a narrow
        # urgent-pattern list, dedupes per 30-min window, calls GH repository_dispatch.
        # Operator step: populate life-platform/github-dispatch-token with a
        # fine-grained PAT (Contents: read+write on this repo only).
        dispatcher_lambda = create_platform_lambda(self, "RemediationDispatcher",
            function_name="life-platform-remediation-dispatcher",
            source_file="lambdas/operational/remediation_dispatcher_lambda.py",
            handler="operational.remediation_dispatcher_lambda.lambda_handler",
            timeout_seconds=30, memory_mb=128,
            environment={
                "REPO_OWNER": "averagejoematt",
                "REPO_NAME":  "life-platform",
                "TOKEN_SECRET": "life-platform/github-dispatch-token",
            },
            custom_policies=rp.operational_remediation_dispatcher(),
            table=local_table, bucket=local_bucket, dlq=None, alerts_topic=None,
            shared_layer=shared_utils_layer,
        )
        local_alerts_topic.add_subscription(sns_subs.LambdaSubscription(dispatcher_lambda))

        # ── 4. Pip Audit — every Monday
        create_platform_lambda(self, "PipAudit",
            function_name="life-platform-pip-audit",
            source_file="lambdas/operational/pip_audit_lambda.py",
            handler="operational.pip_audit_lambda.lambda_handler",
            schedule="cron(0 17 ? * MON *)",
            timeout_seconds=300, memory_mb=512,
            environment={"EMAIL_RECIPIENT": "awsdev@mattsusername.com", "EMAIL_SENDER": "awsdev@mattsusername.com"},
            custom_policies=rp.operational_pip_audit(),
            table=local_table, bucket=local_bucket, dlq=None, alerts_topic=None,
        )

        # ── 5. QA Smoke — daily 11:30 AM PT
        create_platform_lambda(self, "QaSmoke",
            function_name="life-platform-qa-smoke",
            source_file="lambdas/operational/qa_smoke_lambda.py",
            handler="operational.qa_smoke_lambda.lambda_handler",
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
            source_file="lambdas/operational/key_rotator_lambda.py",
            handler="operational.key_rotator_lambda.lambda_handler",
            timeout_seconds=30, memory_mb=128,
            alarm_name="key-rotator-errors",
            custom_policies=rp.operational_key_rotator(),
            table=local_table, bucket=local_bucket, dlq=None,
            alerts_topic=local_alerts_topic, digest_topic=local_digest_topic, digest=True,
        )
        key_rotator.add_permission("SecretsManagerInvokeKeyRotator",
            principal=iam.ServicePrincipal("secretsmanager.amazonaws.com"),
            source_arn=f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:life-platform/mcp-api-key-*",
        )

        # ── 7. Data Export — on-demand only
        create_platform_lambda(self, "DataExport",
            function_name="life-platform-data-export",
            source_file="lambdas/operational/data_export_lambda.py",
            handler="operational.data_export_lambda.lambda_handler",
            timeout_seconds=300, memory_mb=512,
            alarm_name="life-platform-data-export-errors",
            custom_policies=rp.operational_data_export(),
            table=local_table, bucket=local_bucket, dlq=None,
            alerts_topic=local_alerts_topic, digest_topic=local_digest_topic, digest=True,
        )

        # ── 7b. Delete User Data (P7.3) — on-demand only ──
        # Phase 7.3 (2026-05-16): right-to-be-forgotten flow. Invoked manually
        # via `aws lambda invoke --payload '{"user_id":"X","dry_run":true}'`.
        # Refuses protected users (matthew/admin/system) in code. Writes audit
        # record to USER#admin#SOURCE#deletion_log on every real run.
        create_platform_lambda(self, "DeleteUserData",
            function_name="life-platform-delete-user-data",
            source_file="lambdas/operational/delete_user_data_lambda.py",
            handler="operational.delete_user_data_lambda.lambda_handler",
            timeout_seconds=300, memory_mb=256,
            alarm_name="life-platform-delete-user-data-errors",
            custom_policies=rp.operational_delete_user_data(),
            table=local_table, bucket=local_bucket, dlq=None,
            alerts_topic=local_alerts_topic, digest_topic=local_digest_topic, digest=True,
        )

        # ── 8. Data Reconciliation — Monday 12:30 AM PT
        create_platform_lambda(self, "DataReconciliation",
            function_name="life-platform-data-reconciliation",
            source_file="lambdas/operational/data_reconciliation_lambda.py",
            handler="operational.data_reconciliation_lambda.lambda_handler",
            schedule="cron(30 7 ? * MON *)",
            timeout_seconds=120, memory_mb=256,
            environment={"EMAIL_RECIPIENT": "awsdev@mattsusername.com", "EMAIL_SENDER": "awsdev@mattsusername.com"},
            custom_policies=rp.operational_data_reconciliation(),
            table=local_table, bucket=local_bucket, dlq=None, alerts_topic=None,
        )

        # ── 9. Insight Email Parser — SES inbound trigger (previously unmanaged)
        insight_parser = create_platform_lambda(self, "InsightEmailParser",
            function_name="insight-email-parser",
            source_file="lambdas/emails/insight_email_parser_lambda.py",
            handler="emails.insight_email_parser_lambda.lambda_handler",
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
            a.add_alarm_action(cw_actions.SnsAction(local_digest_topic)); a.add_ok_action(cw_actions.SnsAction(local_digest_topic))
        # NOTE: CanaryAnyFailureAlarm removed 2026-03-10 — bug: watched CanaryDDBFail
        # (identical to canary-ddb-failure). The 3 individual alarms below provide full coverage.
        _canary_alarm("CanaryDdbFailureAlarm", "life-platform-canary-ddb-failure", "CanaryDDBFail")
        _canary_alarm("CanaryMcpFailureAlarm", "life-platform-canary-mcp-failure", "CanaryMCPFail")
        _canary_alarm("CanaryS3FailureAlarm", "life-platform-canary-s3-failure", "CanaryS3Fail")
        # Reentry sweep (2026-05-03): catches the "Anthropic API access turned off"
        # failure mode (key disabled by Anthropic for billing). Canary runs every 4h,
        # makes a $0.0001 Anthropic call per run, alarm fires within ≤4h of any 4xx.
        _canary_alarm("CanaryAnthropicFailureAlarm", "life-platform-canary-anthropic-failure", "CanaryAnthropicFail")

        # ── DLQ depth alarm ──
        dlq_depth = cloudwatch.Alarm(self, "DlqDepthAlarm", alarm_name="life-platform-dlq-depth-warning", metric=cloudwatch.Metric(namespace="AWS/SQS", metric_name="ApproximateNumberOfMessagesVisible", dimensions_map={"QueueName": "life-platform-ingestion-dlq"}, period=Duration.seconds(300), statistic="Maximum"), evaluation_periods=1, threshold=1, comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD, treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING)
        dlq_depth.add_alarm_action(cw_actions.SnsAction(local_digest_topic)); dlq_depth.add_ok_action(cw_actions.SnsAction(local_digest_topic))

        # ── WR-48 Enhancement 5: backstop alarm for the freshness checker itself ──
        # PR-reentry-4 (2026-05-03): the freshness-checker is the platform's gap-detection
        # alarm. Without a backstop, if it silently stops emitting (Lambda crashes / schedule
        # disabled / IAM regression), the platform loses its self-monitoring without anyone
        # noticing. This alarm fires if no `StaleSourceCount` metric has been emitted in the
        # last 26 hours (freshness checker runs daily at 9:45 AM PT = ~16:45 UTC).
        # treat_missing_data=BREACHING is intentional — missing data IS the alarm condition.
        freshness_backstop = cloudwatch.Alarm(self, "FreshnessCheckerBackstopAlarm",
            alarm_name="life-platform-freshness-checker-not-emitting",
            alarm_description="WR-48 backstop: freshness checker has not emitted StaleSourceCount in >26h. Check the Lambda + EventBridge schedule.",
            metric=cloudwatch.Metric(
                namespace="LifePlatform/Freshness", metric_name="StaleSourceCount",
                period=Duration.seconds(26 * 3600), statistic="SampleCount",
            ),
            evaluation_periods=1, threshold=1,
            comparison_operator=cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.BREACHING,
        )
        freshness_backstop.add_alarm_action(cw_actions.SnsAction(local_digest_topic))
        freshness_backstop.add_ok_action(cw_actions.SnsAction(local_digest_topic))

        # ── 10. Site API Lambda — life-platform-site-api (R17-09: moved from web_stack us-east-1)
        # Read-only. DynamoDB same-region (eliminates cross-region latency).
        # Function URL is a global HTTPS endpoint — CloudFront in us-east-1 can origin to it.
        site_api_fn = create_platform_lambda(self, "SiteApiLambda",
            function_name="life-platform-site-api",
            source_file="lambdas/web/site_api_lambda.py",
            handler="web.site_api_lambda.lambda_handler",
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=None,
            custom_policies=rp.site_api(),
            timeout_seconds=30,  # Phase 1.6 (2026-05-16): 15s→30s. Matches CloudFront default; complex /api/changes-since queries hit 15s ceiling.
            memory_mb=256,
            environment={
                "USER_ID":        "matthew",
                "TABLE_NAME":     "life-platform",
                "AI_SECRET_NAME": "life-platform/site-api-ai-key",
                "S3_BUCKET":      "matthew-life-platform",
                "S3_REGION":      "us-west-2",
                "CORS_ORIGIN":    "https://averagejoematt.com",
            },
            # 2026-05-24: shared layer re-attached after drift. Lambda was running
            # `Layers: null` and importing constants/phase_filter from the deploy
            # zip directly (worked but fragile). Layer provides the canonical copy.
            shared_layer=shared_utils_layer,
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

        # ADR-036 fix: cap data Lambda concurrency to isolate from AI traffic spikes
        # NOTE: Account concurrency limit is 10 — too low for reserved concurrency.
        # Request increase to 50+ via AWS Support, then uncomment:
        # site_api_fn.node.default_child.add_property_override("ReservedConcurrentExecutions", 5)

        # ── 10b. Site API AI Lambda — /api/ask + /api/board_ask (split from site-api for blast radius isolation)
        # Separate Lambda for AI endpoints: sequential Haiku calls can take 3-20s.
        # Reserved concurrency=2 prevents AI traffic from starving data endpoints.
        site_api_ai_fn = create_platform_lambda(self, "SiteApiAiLambda",
            function_name="life-platform-site-api-ai",
            source_file="lambdas/web/site_api_ai_lambda.py",
            handler="web.site_api_ai_lambda.lambda_handler",
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=None,
            custom_policies=rp.site_api_ai(),
            timeout_seconds=30,  # AI calls take 3-5s each; board_ask chains up to 6
            memory_mb=256,
            environment={
                "USER_ID":        "matthew",
                "TABLE_NAME":     "life-platform",
                "AI_SECRET_NAME": "life-platform/site-api-ai-key",
                "S3_BUCKET":      "matthew-life-platform",
                "S3_REGION":      "us-west-2",
                "CORS_ORIGIN":    "https://averagejoematt.com",
            },
            # 2026-05-24: shared layer attached. Was running `Layers: null` — same drift as site-api.
            shared_layer=shared_utils_layer,
        )

        # Cap AI Lambda concurrency — 2 concurrent is enough for personal site traffic
        # NOTE: Account concurrency limit is 10 — too low for reserved concurrency.
        # Request increase to 50+ via AWS Support, then uncomment:
        # site_api_ai_fn.node.default_child.add_property_override("ReservedConcurrentExecutions", 2)

        site_api_ai_url = site_api_ai_fn.add_function_url(
            auth_type=_lambda.FunctionUrlAuthType.NONE,
            cors=_lambda.FunctionUrlCorsOptions(
                allowed_origins=["https://averagejoematt.com", "https://www.averagejoematt.com"],
                allowed_methods=[_lambda.HttpMethod.POST],
                allowed_headers=["Content-Type", "X-Subscriber-Token"],
            ),
        )

        site_api_ai_fn_url_domain = cdk.Fn.select(2, cdk.Fn.split("/", site_api_ai_url.url))

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

        # ADR-050: site-api alarms route to digest. The canary covers true outages
        # (CanaryS3Fail / CanaryDDBFail fire urgently); these are degradation signals.
        _site_api_errors_alarm = cloudwatch.Alarm(self, "SiteApiErrors", alarm_name="site-api-errors",
            metric=site_api_errors, threshold=1, evaluation_periods=1,
            comparison_operator=GTE, treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING)
        _site_api_errors_alarm.add_alarm_action(cw_actions.SnsAction(local_digest_topic))

        _site_api_latency_alarm = cloudwatch.Alarm(self, "SiteApiLatencyHigh", alarm_name="site-api-p95-latency-high",
            metric=site_api_duration_p95, threshold=5000, evaluation_periods=1,
            comparison_operator=GTE, treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING)
        _site_api_latency_alarm.add_alarm_action(cw_actions.SnsAction(local_digest_topic))

        _site_api_spike_alarm = cloudwatch.Alarm(self, "SiteApiInvocationSpike", alarm_name="site-api-invocation-spike",
            metric=site_api_invocations, threshold=200, evaluation_periods=1,
            comparison_operator=GTE, treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING)
        _site_api_spike_alarm.add_alarm_action(cw_actions.SnsAction(local_digest_topic))

        cloudwatch.Dashboard(self, "SiteApiDashboard", dashboard_name="life-platform-site-api",
            widgets=[[
                cloudwatch.GraphWidget(title="Invocations", left=[site_api_invocations], width=8),
                cloudwatch.GraphWidget(title="Errors", left=[site_api_errors], width=8),
                cloudwatch.GraphWidget(title="Duration (p50 / p95)", left=[site_api_duration_p50, site_api_duration_p95], width=8),
            ]])

        # ── 11. Site Stats Refresh — 4x/day: 8am, 12pm, 4pm, 8pm PT (15:00, 19:00, 23:00, 03:00 UTC)
        # Invokes ingestion Lambdas synchronously, reads fresh DynamoDB, updates vitals in
        # public_stats.json in-place without any AI calls. Zero incremental cost.
        site_stats_fn = create_platform_lambda(self, "SiteStatsRefresh",
            function_name="site-stats-refresh",
            source_file="lambdas/web/site_stats_refresh_lambda.py",
            handler="web.site_stats_refresh_lambda.lambda_handler",
            timeout_seconds=300, memory_mb=256,
            environment={
                "TABLE_NAME":  "life-platform",
                "S3_BUCKET":   "matthew-life-platform",
                "USER_ID":     "matthew",
            },
            custom_policies=rp.operational_site_stats_refresh(),
            table=local_table, bucket=local_bucket, dlq=None, alerts_topic=None,
            # 2026-05-24: shared layer attached. Was running `Layers: null` — same drift as site-api.
            shared_layer=shared_utils_layer,
        )
        # Four EventBridge cron rules — UTC equivalents of 8am/12pm/4pm/8pm Pacific (no DST drift)
        for utc_hour, label in [(15, "8amPT"), (19, "12pmPT"), (23, "4pmPT"), (3, "8pmPT")]:
            rule = events.Rule(self, f"SiteStatsRefresh{label}",
                schedule=events.Schedule.cron(hour=str(utc_hour), minute="0"),
            )
            rule.add_target(targets.LambdaFunction(site_stats_fn))

        # ── 12. OG Image Generator — daily at 19:30 UTC (11:30 AM PT, after daily brief)
        # DEFERRED: og-image-generator already exists (CLI-created). Needs CDK import before
        # CDK can manage it. Tracked as R18-F02. Lambda runs fine outside CDK.

        # ── 13. Pipeline Health Check — daily at 13:00 UTC (6 AM PT)
        # SNS_ARN env added 2026-05-25: Lambda hardcodes life-platform-alerts as
        # fallback (the immediate-email topic). Set explicitly to digest so
        # direct publishes batch into the daily alerts-digest email.
        pipeline_health = create_platform_lambda(self, "PipelineHealthCheck",
            function_name="pipeline-health-check",
            source_file="lambdas/operational/pipeline_health_check_lambda.py",
            handler="operational.pipeline_health_check_lambda.lambda_handler",
            schedule="cron(30 2,6,14,18,22 * * ? *)",  # 5x daily, 30 min after ingestion
            timeout_seconds=300, memory_mb=256,
            environment={"SNS_ARN": DIGEST_TOPIC_ARN},
            custom_policies=rp.pipeline_health_check(),
            table=local_table, bucket=local_bucket, dlq=None,
            alerts_topic=local_alerts_topic, digest_topic=local_digest_topic, digest=True)

        # Phase 3.2 (2026-05-16): second EventBridge schedule for compute-output
        # verification. Fires at 16:58 UTC = 9:58 AM PT — between the compute
        # cascade ending at 9:55 and the daily-brief at 10:00. Invokes with
        # {check_compute_outputs: true} so the Lambda runs the DDB freshness
        # check instead of the default Lambda-probe path.
        compute_check_rule = events.Rule(self, "PipelineHealthComputeCheck",
            schedule=events.Schedule.cron(hour="16", minute="58"),
            description="Phase 3.2: verify today's compute records exist before daily-brief",
        )
        compute_check_rule.add_target(targets.LambdaFunction(
            pipeline_health,
            event=events.RuleTargetInput.from_object({"check_compute_outputs": True}),
        ))

        # ── 14. Hevy Routine Cron (ADR-066) — Phase 3 scheduled generator ──
        # SHIPS DISABLED at the EventBridge level AND SSM /life-platform/hevy/cron_enabled
        # defaults to "false" (belt-and-suspenders gate). Operator flips both ON
        # after ~3 weeks of Phase 1 chat-path usage justifies it (SPEC §2).
        # Schedule expression below is for the eventual cadence — Sunday 06:30 PT
        # (13:30 UTC, UTC-fixed, no DST). Until enabled, the cron does not fire.
        hevy_routine_cron = create_platform_lambda(self, "HevyRoutineCron",
            function_name="hevy-routine-cron",
            source_file="lambdas/operational/hevy_routine_cron_lambda.py",
            handler="operational.hevy_routine_cron_lambda.lambda_handler",
            timeout_seconds=120, memory_mb=256,
            environment={
                "TABLE_NAME": "life-platform",
                "USER_ID": "matthew",
                "S3_BUCKET": "matthew-life-platform",
                "PAUSE_MODE_PARAM": "/life-platform/pause-mode",
                "BUDGET_TIER_PARAM": "/life-platform/budget-tier",
                "HEVY_CRON_ENABLED_PARAM": "/life-platform/hevy/cron_enabled",
                "HEVY_ADD_LOAD_PARAM": "/life-platform/hevy/autoreg_add_load_enabled",
                "HEVY_WRITE_SECRET": "life-platform/hevy-write",
            },
            custom_policies=rp.hevy_routine_cron(),
            table=local_table, bucket=local_bucket, dlq=None,
            alerts_topic=local_alerts_topic, digest_topic=local_digest_topic, digest=True,
            alarm_name="hevy-routine-cron-errors",
            shared_layer=shared_utils_layer,
        )
        # Manual events.Rule escape hatch — create_platform_lambda's schedule= shortcut
        # auto-enables the rule. ADR-066 ships disabled. Do NOT collapse this back.
        hevy_routine_cron_rule = events.Rule(self, "HevyRoutineCronRule",
            rule_name="hevy-routine-cron-weekly",
            description="ADR-066 ships disabled; operator enables after Phase 1 use justifies it.",
            schedule=events.Schedule.expression("cron(30 13 ? * SUN *)"),
            enabled=False,
        )
        hevy_routine_cron_rule.add_target(targets.LambdaFunction(hevy_routine_cron))

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
        cdk.CfnOutput(self, "SiteApiAiFunctionUrl",
            value=site_api_ai_url.url,
            description="Lambda Function URL for life-platform-site-api-ai (us-west-2)",
        )
        cdk.CfnOutput(self, "SiteApiAiFunctionUrlDomain",
            value=site_api_ai_fn_url_domain,
            description="AI Lambda Function URL domain — use in web_stack CloudFront AiLambdaOrigin",
        )
