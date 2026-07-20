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
  reading-cover-pipeline            (on-demand only)        — Mind pillar covers (ADR-097)
"""

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_dynamodb as dynamodb,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_s3 as s3,
    aws_sns as sns,
    aws_sns_subscriptions as sns_subs,
    aws_sqs as sqs,
)

from stacks import role_policies as rp
from stacks.constants import TABLE_NAME  # CONF-01 / #936: one source for the table name (DR cutover)
from stacks.lambda_helpers import create_platform_lambda

# ── #793 (2026-07-08): the public serving path moved OUT of this stack ───────
# site-api + site-api-ai (functions, Function URLs, roles, alarms, outputs) now
# live in serve_stack.py (LifePlatformServe), moved via `cdk refactor` so the
# physical functions and Function URLs were preserved. Ops-motivated deploy
# holds on this stack no longer freeze the reader-facing API path. The R17-09
# cross-region note and the #794 ownership rules travel with the code — see
# serve_stack.py's module docstring.
# ──────────────────────────────────────────────────────────────────────────────

REGION = "us-west-2"
ACCT = "205930651321"
INGESTION_DLQ_ARN = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
LIFE_PLATFORM_TABLE = TABLE_NAME
LIFE_PLATFORM_BUCKET = "matthew-life-platform"
ALERTS_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"
DIGEST_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts-digest"


class OperationalStack(Stack):
    def __init__(self, scope, construct_id, table, bucket, dlq, alerts_topic, digest_topic=None, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        local_dlq = sqs.Queue.from_queue_arn(self, "IngestionDLQ", INGESTION_DLQ_ARN)
        local_table = dynamodb.Table.from_table_name(self, "LifePlatformTable", LIFE_PLATFORM_TABLE)
        local_bucket = s3.Bucket.from_bucket_name(self, "LifePlatformBucket", LIFE_PLATFORM_BUCKET)
        local_alerts_topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)
        local_digest_topic = sns.Topic.from_topic_arn(self, "DigestTopic", DIGEST_TOPIC_ARN)
        # #781 (2026-07-06): the shared utils layer is retired — every function's
        # code asset is the staged full-tree bundle (deploy/build_bundle.py), so
        # shared modules ship inside the bundle itself.

        # ── 1. Freshness Checker — 9:45 AM PT daily (previously in separate CFn stack)
        # ADR-052: SNS_ARN points to the digest topic. The freshness checker's
        # direct publishes (stale-source / partial-completeness / OAuth-token-stale)
        # are exactly the "4 stale source(s)" daily emails we want to batch.
        freshness = create_platform_lambda(
            self,
            "FreshnessChecker",
            function_name="life-platform-freshness-checker",
            source_file="lambdas/emails/freshness_checker_lambda.py",
            handler="emails.freshness_checker_lambda.lambda_handler",
            schedule="cron(45 16 * * ? *)",
            timeout_seconds=30,
            memory_mb=128,
            environment={
                "EMAIL_RECIPIENT": "awsdev@mattsusername.com",
                "EMAIL_SENDER": "awsdev@mattsusername.com",
                "SNS_ARN": DIGEST_TOPIC_ARN,
            },
            custom_policies=rp.operational_freshness_checker(),
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=local_alerts_topic,
            digest_topic=local_digest_topic,
            digest=True,
            alarm_name="freshness-checker-errors",
        )

        # ── 2. DLQ Consumer — every 6 hours
        create_platform_lambda(
            self,
            "DlqConsumer",
            function_name="life-platform-dlq-consumer",
            source_file="lambdas/operational/dlq_consumer_lambda.py",
            handler="operational.dlq_consumer_lambda.lambda_handler",
            schedule="rate(6 hours)",
            timeout_seconds=120,
            memory_mb=256,
            environment={
                # 2026-05-26: DLQ_URL was never wired in CDK; the Lambda
                # required it (see lambda body) but only ever got default
                # env from create_platform_lambda. Result: every scheduled
                # fire logged "DLQ_URL not set" and returned 500 silently.
                # The Lambda comment says "set from deploy script" but no
                # such script exists. Wired here now.
                "DLQ_URL": f"https://sqs.{REGION}.amazonaws.com/{ACCT}/life-platform-ingestion-dlq",
                # ADR-115/#402: escalation pages the operator on the existing
                # urgent SNS topic when a message crosses the failure threshold.
                "ALERTS_TOPIC_ARN": f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts",
            },
            custom_policies=rp.operational_dlq_consumer(),
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=None,
        )

        # ── 2b. Alert Digest (ADR-050) — drains digest queue daily at 8 AM PT
        # SQS retention is 25h so the daily run never misses a fire that happened
        # during the previous 24h window. SNS raw message delivery puts the
        # CloudWatch alarm JSON directly into the SQS body (no envelope).
        digest_queue = sqs.Queue(
            self,
            "AlertDigestQueue",
            queue_name="life-platform-alerts-digest-queue",
            retention_period=Duration.hours(25),
            visibility_timeout=Duration.seconds(120),
        )
        # Subscribe the queue to the digest SNS topic (raw delivery for simpler parsing).
        local_digest_topic.add_subscription(
            sns_subs.SqsSubscription(digest_queue, raw_message_delivery=True),
        )

        digest_lambda = create_platform_lambda(
            self,
            "AlertDigest",
            function_name="life-platform-alert-digest",
            source_file="lambdas/operational/alert_digest_lambda.py",
            handler="operational.alert_digest_lambda.lambda_handler",
            # cron(0 15 * * ? *) = 15:00 UTC = 8 AM PT (UTC-fixed, no DST drift).
            schedule="cron(0 15 * * ? *)",
            timeout_seconds=60,
            memory_mb=128,
            environment={
                "DIGEST_QUEUE_URL": digest_queue.queue_url,
                "EMAIL_RECIPIENT": "awsdev@mattsusername.com",
                "EMAIL_SENDER": "awsdev@mattsusername.com",
            },
            custom_policies=rp.operational_alert_digest(),
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=None,
        )
        cdk.CfnOutput(self, "AlertDigestQueueUrl", value=digest_queue.queue_url)
        cdk.CfnOutput(self, "AlertDigestLambdaArn", value=digest_lambda.function_arn)

        # ── 2c. Weekly traffic digest (privacy-clean returnability measurement) ──
        # CloudFront standard access logs (first-party server logs — no cookies, no
        # client JS, no third party) land in this bucket; the Lambda aggregates the
        # past 7 days (IPs hashed-then-discarded) and emails a digest. ObjectOwnership
        # = BUCKET_OWNER_PREFERRED so CloudFront standard logging can grant itself the
        # awslogsdelivery ACL. Enabling logging on the (non-CDK) site distribution is
        # a one-time manual step — see docs/SITE_UPLEVEL_PLAYBOOK.md.
        cf_log_bucket = s3.Bucket(
            self,
            "CfLogBucket",
            bucket_name="matthew-life-platform-cf-logs",
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_PREFERRED,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(90))],  # logs are transient
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        traffic_digest = create_platform_lambda(
            self,
            "TrafficDigest",
            function_name="life-platform-traffic-digest",
            source_file="lambdas/operational/traffic_digest_lambda.py",
            handler="operational.traffic_digest_lambda.lambda_handler",
            # cron(0 16 ? * MON *) = 16:00 UTC Mondays = 9 AM PT (UTC-fixed, no DST drift).
            schedule="cron(0 16 ? * MON *)",
            timeout_seconds=120,
            memory_mb=256,
            environment={
                "LOG_BUCKET": cf_log_bucket.bucket_name,
                "LOG_PREFIX": "cf/",
                "SITE_HOST": "averagejoematt.com",
                "EMAIL_RECIPIENT": "awsdev@mattsusername.com",
                "EMAIL_SENDER": "awsdev@mattsusername.com",
            },
            custom_policies=rp.operational_traffic_digest(),
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            # No error alarm by design — a weekly digest failing is low-stakes (you miss
            # one traffic email; the CF logs are retained, so the next run still sees the
            # window). Consistent with the other alerts_topic=None operational Lambdas
            # (canary, qa_smoke, cost_governor). To add a failure signal later, pass
            # alerts_topic=local_alerts_topic + digest_topic=local_digest_topic + digest=True.
            alerts_topic=None,
        )
        cdk.CfnOutput(self, "CfLogBucketName", value=cf_log_bucket.bucket_name)
        cdk.CfnOutput(self, "TrafficDigestLambdaArn", value=traffic_digest.function_arn)

        # ── 3. Canary — every 4 hours
        canary = create_platform_lambda(
            self,
            "Canary",
            function_name="life-platform-canary",
            source_file="lambdas/operational/canary_lambda.py",
            handler="operational.canary_lambda.lambda_handler",
            schedule="rate(4 hours)",
            timeout_seconds=60,
            memory_mb=256,
            environment={
                # SEC-02 (#780): MCP_FUNCTION_URL is discovered at runtime (mcp_url.resolve_mcp_url)
                # via lambda:GetFunctionUrlConfig — not committed here (repo is public, URL is the boundary).
                "MCP_SECRET_NAME": "life-platform/mcp-api-key",
            },
            custom_policies=rp.operational_canary(),
            table=local_table,
            bucket=local_bucket,
            dlq=local_dlq,  # #809/ADR-116: terminal async failures -> DLQ digest (replaces the 2026-05-25 orphan error alarm)
            alerts_topic=None,
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
        create_platform_lambda(
            self,
            "CostGovernor",
            function_name="life-platform-cost-governor",
            source_file="lambdas/operational/cost_governor_lambda.py",
            handler="operational.cost_governor_lambda.lambda_handler",
            schedule="cron(0 0/8 * * ? *)",  # every 8h (3x/day) — CE self-cost: each run = 1 Cost Explorer call ($0.01). Non-AI spend is slow-moving + Bedrock is tracked via free CloudWatch token metrics, so 3x/day is ample; the actual-mtd cap in _decide_tier still catches a real runaway within a day.
            timeout_seconds=60,
            memory_mb=256,
            # 2026-05-29: enforcement ENABLED — the projection fix makes the
            # estimate reliable (projected ~$45, Tier 0). Writes the SSM tier +
            # alerts on change; budget_guard then gates AI. Set OBSERVE_MODE=true
            # to revert to observe-only.
            environment={"OBSERVE_MODE": "false"},
            custom_policies=rp.operational_cost_governor(),
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=None,
        )

        # ── 3c. Remediation Dispatcher — SNS-subscribed urgent-alarm → GH dispatch
        # Closes the urgent-alarm latency the daily 07:45 PT sweep can't cover.
        # Subscribes to life-platform-alerts (urgent topic), filters to a narrow
        # urgent-pattern list, dedupes per 30-min window, calls GH repository_dispatch.
        # Operator step: populate life-platform/github-dispatch-token with a
        # fine-grained PAT (Contents: read+write on this repo only).
        dispatcher_lambda = create_platform_lambda(
            self,
            "RemediationDispatcher",
            function_name="life-platform-remediation-dispatcher",
            source_file="lambdas/operational/remediation_dispatcher_lambda.py",
            handler="operational.remediation_dispatcher_lambda.lambda_handler",
            timeout_seconds=30,
            memory_mb=128,
            environment={
                "REPO_OWNER": "averagejoematt",
                "REPO_NAME": "life-platform",
                "TOKEN_SECRET": "life-platform/github-dispatch-token",
            },
            custom_policies=rp.operational_remediation_dispatcher(),
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=None,
        )
        local_alerts_topic.add_subscription(sns_subs.LambdaSubscription(dispatcher_lambda))

        # #1444: the alerts topic's ONLY IaC-declared subscriber was this Lambda —
        # the human email leg existed only as a manual (console) subscription,
        # invisible to IaC and at risk of silently vanishing on any topic
        # recreation. Codify it so an urgent alarm always has a human fast path
        # even when the dispatcher itself is the thing that's broken.
        # Live check (2026-07-18, `aws sns list-subscriptions-by-topic
        # --topic-arn arn:aws:sns:us-west-2:205930651321:life-platform-alerts`):
        # a CONFIRMED manual email subscription to this same address already
        # exists. On first deploy of this construct, `cdk import` it (the same
        # CDK-managed-via-import pattern core_stack.py already uses for the
        # alerts/digest topics themselves) rather than letting `cdk deploy`
        # create a second, separately-pending subscription to the same inbox.
        alerts_email = self.node.try_get_context("alerts_email") or "awsdev@mattsusername.com"
        local_alerts_topic.add_subscription(sns_subs.EmailSubscription(alerts_email))

        # ── 4. Pip Audit — every Monday
        create_platform_lambda(
            self,
            "PipAudit",
            function_name="life-platform-pip-audit",
            source_file="lambdas/operational/pip_audit_lambda.py",
            handler="operational.pip_audit_lambda.lambda_handler",
            schedule="cron(0 17 ? * MON *)",
            timeout_seconds=300,
            memory_mb=512,
            environment={"EMAIL_RECIPIENT": "awsdev@mattsusername.com", "EMAIL_SENDER": "awsdev@mattsusername.com"},
            custom_policies=rp.operational_pip_audit(),
            table=local_table,
            bucket=local_bucket,
            dlq=local_dlq,  # #809/ADR-116: terminal async failures -> DLQ digest (replaces the 2026-05-25 orphan error alarm)
            alerts_topic=None,
        )

        # ── 5. QA Smoke — daily 11:30 AM PT
        create_platform_lambda(
            self,
            "QaSmoke",
            function_name="life-platform-qa-smoke",
            source_file="lambdas/operational/qa_smoke_lambda.py",
            handler="operational.qa_smoke_lambda.lambda_handler",
            schedule="cron(30 18 ? * * *)",
            # 120 → 240 (#1096): the Reader Truth pass adds 6 HTTPS fetches + one
            # or two Haiku batches (~20-60s) on top of the existing checks.
            timeout_seconds=240,
            memory_mb=256,
            environment={
                "EMAIL_RECIPIENT": "awsdev@mattsusername.com",
                "EMAIL_SENDER": "awsdev@mattsusername.com",
                # SEC-02 (#780): MCP_FUNCTION_URL discovered at runtime (mcp_url.resolve_mcp_url) — not committed.
                "MCP_SECRET_NAME": "life-platform/mcp-api-key",
            },
            custom_policies=rp.operational_qa_smoke(),
            # #498: qa tiers derive from source_registry (shared layer). Without the
            # layer, CI's single-file hot deploy strips the bundled copy and the
            # import dies (broke the 2026-07-04 smoke run).
            table=local_table,
            bucket=local_bucket,
            dlq=local_dlq,  # #809/ADR-116: terminal async failures -> DLQ digest (replaces the 2026-05-25 orphan error alarm)
            alerts_topic=None,
        )

        # ── 6. Key Rotator — Secrets Manager rotation trigger only
        key_rotator = create_platform_lambda(
            self,
            "KeyRotator",
            function_name="life-platform-key-rotator",
            source_file="lambdas/operational/key_rotator_lambda.py",
            handler="operational.key_rotator_lambda.lambda_handler",
            timeout_seconds=30,
            memory_mb=128,
            alarm_name="key-rotator-errors",
            custom_policies=rp.operational_key_rotator(),
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=local_alerts_topic,
            digest_topic=local_digest_topic,
            digest=True,
        )
        key_rotator.add_permission(
            "SecretsManagerInvokeKeyRotator",
            principal=iam.ServicePrincipal("secretsmanager.amazonaws.com"),
            source_arn=f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:life-platform/mcp-api-key-*",
        )

        # ── 7. Data Export — on-demand only
        create_platform_lambda(
            self,
            "DataExport",
            function_name="life-platform-data-export",
            source_file="lambdas/operational/data_export_lambda.py",
            handler="operational.data_export_lambda.lambda_handler",
            timeout_seconds=300,
            memory_mb=512,
            alarm_name="life-platform-data-export-errors",
            custom_policies=rp.operational_data_export(),
            # #498: export census derives from phase_taxonomy (shared layer as of v109).
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=local_alerts_topic,
            digest_topic=local_digest_topic,
            digest=True,
        )

        # ── 7b. Delete User Data (P7.3) — on-demand only ──
        # Phase 7.3 (2026-05-16): right-to-be-forgotten flow. Invoked manually
        # via `aws lambda invoke --payload '{"user_id":"X","dry_run":true}'`.
        # Refuses protected users (matthew/admin/system) in code. Writes audit
        # record to USER#admin#SOURCE#deletion_log on every real run.
        create_platform_lambda(
            self,
            "DeleteUserData",
            function_name="life-platform-delete-user-data",
            source_file="lambdas/operational/delete_user_data_lambda.py",
            handler="operational.delete_user_data_lambda.lambda_handler",
            timeout_seconds=300,
            memory_mb=256,
            alarm_name="life-platform-delete-user-data-errors",
            custom_policies=rp.operational_delete_user_data(),
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=local_alerts_topic,
            digest_topic=local_digest_topic,
            digest=True,
        )

        # ── 8. Data Reconciliation — Monday 12:30 AM PT
        create_platform_lambda(
            self,
            "DataReconciliation",
            function_name="life-platform-data-reconciliation",
            source_file="lambdas/operational/data_reconciliation_lambda.py",
            handler="operational.data_reconciliation_lambda.lambda_handler",
            schedule="cron(30 7 ? * MON *)",
            timeout_seconds=120,
            memory_mb=256,
            environment={"EMAIL_RECIPIENT": "awsdev@mattsusername.com", "EMAIL_SENDER": "awsdev@mattsusername.com"},
            custom_policies=rp.operational_data_reconciliation(),
            # #498: expected-days derive from source_registry (shared layer).
            table=local_table,
            bucket=local_bucket,
            dlq=local_dlq,  # #809/ADR-116: terminal async failures -> DLQ digest (replaces the 2026-05-25 orphan error alarm)
            alerts_topic=None,
        )

        # ── 8b. Coherence Sentinel — does the intelligence layer still make sense?
        # Daily 10:45 AM PT (after compute 9:40 + prediction-evaluator 10:00). Runs the
        # pure invariants (coherence_invariants.py, bundled with the lambdas/ asset)
        # against live state and emits LifePlatform/Coherence metrics → DIGEST alarms in
        # monitoring_stack. Read-only; budget-gated Haiku semantic pass on top. (ADR: the
        # Self-Management & Coherence Program — detect incoherent-but-green output.)
        create_platform_lambda(
            self,
            "CoherenceSentinel",
            function_name="life-platform-coherence-sentinel",
            source_file="lambdas/operational/coherence_sentinel_lambda.py",
            handler="operational.coherence_sentinel_lambda.lambda_handler",
            schedule="cron(45 18 ? * * *)",
            timeout_seconds=120,
            memory_mb=256,
            custom_policies=rp.operational_coherence_sentinel(),
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=None,
        )

        # ── AI Quality Canary (#385) — standing eyes on the two public AI
        # endpoints. Invokes site-api-ai directly (no reader rate-limit spend),
        # runs pre-registered probes with deterministic quality checks +
        # regression cases for the 2026-07 review defects, emits LifePlatform/
        # AICanary (→ digest alarm + heartbeat), persists findings to
        # ai-canary-log/. 3×/week + read-only + idempotent (#1443 — the public-AI
        # blind window was 7d at weekly; Mon/Wed/Fri caps it at ~2-3d).
        create_platform_lambda(
            self,
            "AiQualityCanary",
            function_name="life-platform-ai-quality-canary",
            source_file="lambdas/operational/ai_quality_canary_lambda.py",
            handler="operational.ai_quality_canary_lambda.lambda_handler",
            schedule="cron(20 16 ? * MON,WED,FRI *)",  # 3×/week, 16:20 UTC (09:20 AM PDT), UTC-fixed
            timeout_seconds=120,
            memory_mb=256,
            custom_policies=rp.operational_ai_quality_canary(),
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=None,
        )

        # ── 9. Insight Email Parser — SES inbound trigger (previously unmanaged)
        insight_parser = create_platform_lambda(
            self,
            "InsightEmailParser",
            function_name="insight-email-parser",
            source_file="lambdas/emails/insight_email_parser_lambda.py",
            handler="emails.insight_email_parser_lambda.lambda_handler",
            timeout_seconds=30,
            memory_mb=128,
            environment={
                "ALLOWED_SENDERS": "awsdev@mattsusername.com,mattsthrowaway@protonmail.com",
            },
            custom_policies=rp.operational_insight_email_parser(),
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=None,
        )
        insight_parser.add_permission(
            "SESInvokeInsightParser",
            principal=iam.ServicePrincipal("ses.amazonaws.com"),
            source_arn=f"arn:aws:ses:{REGION}:{ACCT}:receipt-rule-set/*",
        )

        # ── Canary custom metric alarms ──
        def _canary_alarm(aid, aname, mname):
            a = cloudwatch.Alarm(
                self,
                aid,
                alarm_name=aname,
                metric=cloudwatch.Metric(namespace="LifePlatform/Canary", metric_name=mname, period=Duration.seconds(300), statistic="Sum"),
                evaluation_periods=1,
                threshold=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            )
            a.add_alarm_action(cw_actions.SnsAction(local_digest_topic))
            a.add_ok_action(cw_actions.SnsAction(local_digest_topic))

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
        dlq_depth = cloudwatch.Alarm(
            self,
            "DlqDepthAlarm",
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
        dlq_depth.add_alarm_action(cw_actions.SnsAction(local_digest_topic))
        dlq_depth.add_ok_action(cw_actions.SnsAction(local_digest_topic))

        # ── WR-48 Enhancement 5: backstop alarm for the freshness checker itself ──
        # PR-reentry-4 (2026-05-03): the freshness-checker is the platform's gap-detection
        # alarm. Without a backstop, if it silently stops emitting (Lambda crashes / schedule
        # disabled / IAM regression), the platform loses its self-monitoring without anyone
        # noticing. This alarm fires if no `StaleSourceCount` metric has been emitted in the
        # last 26 hours (freshness checker runs daily at 9:45 AM PT = ~16:45 UTC).
        # treat_missing_data=BREACHING is intentional — missing data IS the alarm condition.
        freshness_backstop = cloudwatch.Alarm(
            self,
            "FreshnessCheckerBackstopAlarm",
            alarm_name="life-platform-freshness-checker-not-emitting",
            alarm_description="WR-48 backstop: freshness checker has not emitted StaleSourceCount in >26h. Check the Lambda + EventBridge schedule.",
            metric=cloudwatch.Metric(
                namespace="LifePlatform/Freshness",
                metric_name="StaleSourceCount",
                period=Duration.seconds(26 * 3600),
                statistic="SampleCount",
            ),
            evaluation_periods=1,
            threshold=1,
            comparison_operator=cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.BREACHING,
        )
        freshness_backstop.add_alarm_action(cw_actions.SnsAction(local_digest_topic))
        freshness_backstop.add_ok_action(cw_actions.SnsAction(local_digest_topic))

        # ── 10. (site-api / site-api-ai moved to serve_stack.py — #793, cdk refactor 2026-07-08)

        # ── 11. Site Stats Refresh — 4x/day: 8am, 12pm, 4pm, 8pm PT (15:00, 19:00, 23:00, 03:00 UTC)
        # Invokes ingestion Lambdas synchronously, reads fresh DynamoDB, updates vitals in
        # public_stats.json in-place without any AI calls. Zero incremental cost.
        site_stats_fn = create_platform_lambda(
            self,
            "SiteStatsRefresh",
            function_name="site-stats-refresh",
            source_file="lambdas/web/site_stats_refresh_lambda.py",
            handler="web.site_stats_refresh_lambda.lambda_handler",
            timeout_seconds=300,
            memory_mb=256,
            environment={
                "TABLE_NAME": TABLE_NAME,
                "S3_BUCKET": "matthew-life-platform",
                "USER_ID": "matthew",
            },
            custom_policies=rp.operational_site_stats_refresh(),
            table=local_table,
            bucket=local_bucket,
            dlq=local_dlq,  # #809/ADR-116: terminal async failures -> DLQ digest (replaces the 2026-05-25 orphan error alarm)
            alerts_topic=None,
            # #794: same staged full-tree bundle as site-api above — no layer (ADR-131).
        )
        # Four EventBridge cron rules — UTC equivalents of 8am/12pm/4pm/8pm Pacific (no DST drift)
        for utc_hour, label in [(15, "8amPT"), (19, "12pmPT"), (23, "4pmPT"), (3, "8pmPT")]:
            rule = events.Rule(
                self,
                f"SiteStatsRefresh{label}",
                schedule=events.Schedule.cron(hour=str(utc_hour), minute="0"),
            )
            rule.add_target(targets.LambdaFunction(site_stats_fn))

        # ── 12. OG Image Generator — daily at 19:30 UTC (11:30 AM PT, after daily brief)
        # Adopted into CDK 2026-06-08 (ADR-081): the last CLI orphan. Its source was
        # already in the monorepo at lambdas/web/og_image_lambda.py (the deployed CLI
        # package was byte-identical) — no relocation needed, just CDK wiring. Pillow-
        # renders 12 PNG + WebP share cards from generated/public_stats.json into
        # generated/assets/images/, then self-invalidates CloudFront. Needs the standalone
        # pillow-layer; imports no shared platform modules so the shared utils layer is
        # intentionally omitted. (NB: web_stack's us-east-1 life-platform-og-image points
        # at the SAME file via a stale `.handler` ref — a separate pre-existing bug; that
        # function has errored since 2026-03-20. Out of scope here; tracked in ADR-081.)
        pillow_layer = _lambda.LayerVersion.from_layer_version_arn(
            self,
            "PillowLayer",
            # Externally managed runtime layer (Pillow) — not the platform shared-utils layer.
            "arn:aws:lambda:us-west-2:205930651321:layer:pillow-layer:1",
        )
        create_platform_lambda(
            self,
            "OGImageGenerator",
            function_name="og-image-generator",
            source_file="lambdas/web/og_image_lambda.py",
            handler="web.og_image_lambda.lambda_handler",
            schedule="cron(30 19 * * ? *)",  # 11:30 AM PT daily, after the daily brief refreshes public_stats
            timeout_seconds=60,
            memory_mb=512,
            additional_layers=[pillow_layer],
            custom_policies=rp.operational_og_image_generator(),
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=local_alerts_topic,
            digest_topic=local_digest_topic,
            digest=True,
        )

        # ── 12b. Reading Cover Pipeline (ADR-097, Mind pillar Phase A) — on-demand only.
        # Invoked with a book dict; fetches a cover (Open Library → Google Books →
        # designed placeholder), caches it to generated/covers/<bookId>.jpg, and
        # updates BOOK#.coverS3Key. No schedule (the add_book path / MCP triggers it in
        # Phase B). Pillow via the standalone pillow-layer (same as OG); imports no
        # shared-layer modules. Never hot-links — always stores bytes (spec §8).
        create_platform_lambda(
            self,
            "ReadingCoverPipeline",
            function_name="reading-cover-pipeline",
            source_file="lambdas/reading/cover_pipeline_lambda.py",
            handler="reading.cover_pipeline_lambda.lambda_handler",
            timeout_seconds=60,
            memory_mb=512,
            additional_layers=[pillow_layer],
            custom_policies=rp.operational_reading_cover_pipeline(),
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=local_alerts_topic,
            digest_topic=local_digest_topic,
            digest=True,
        )

        # ── 12c. Reading Recall Sweep (ADR-097, Mind pillar Phase D) — daily 16:00 UTC
        # (8 AM PT). Queries the sparse GSI1 for due spaced-retrieval prompts, writes
        # the owner-PRIVATE nudge snapshot, emits LifePlatform/Reading::RecallsDue.
        # Fixed-UTC schedule (DST-safe). No AI (gist scoring runs in the MCP answer path).
        create_platform_lambda(
            self,
            "ReadingRecallSweep",
            function_name="reading-recall-sweep",
            source_file="lambdas/reading/reading_recall_sweep_lambda.py",
            handler="reading.reading_recall_sweep_lambda.lambda_handler",
            schedule="cron(0 16 * * ? *)",
            timeout_seconds=60,
            memory_mb=256,
            custom_policies=rp.operational_reading_recall_sweep(),
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=local_alerts_topic,
            digest_topic=local_digest_topic,
            digest=True,
        )

        # ── 13. Pipeline Health Check — daily at 13:00 UTC (6 AM PT)
        # SNS_ARN env added 2026-05-25: Lambda hardcodes life-platform-alerts as
        # fallback (the immediate-email topic). Set explicitly to digest so
        # direct publishes batch into the daily alerts-digest email.
        pipeline_health = create_platform_lambda(
            self,
            "PipelineHealthCheck",
            function_name="pipeline-health-check",
            source_file="lambdas/operational/pipeline_health_check_lambda.py",
            handler="operational.pipeline_health_check_lambda.lambda_handler",
            schedule="cron(30 2,6,14,18,22 * * ? *)",  # 5x daily, 30 min after ingestion
            timeout_seconds=300,
            memory_mb=256,
            environment={"SNS_ARN": DIGEST_TOPIC_ARN},
            # DI-1.1 (2026-06-20): needs the shared layer for ingest_health + source_state
            # (is_paused). Was previously running on an out-of-band v85 that CDK didn't
            # manage, so source_state silently fell back to the no-op stub.
            custom_policies=rp.pipeline_health_check(),
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=local_alerts_topic,
            digest_topic=local_digest_topic,
            digest=True,
        )

        # Phase 3.2 (2026-05-16): second EventBridge schedule for compute-output
        # verification. Fires at 16:58 UTC = 9:58 AM PT — between the compute
        # cascade ending at 9:55 and the daily-brief at 10:00. Invokes with
        # {check_compute_outputs: true} so the Lambda runs the DDB freshness
        # check instead of the default Lambda-probe path.
        compute_check_rule = events.Rule(
            self,
            "PipelineHealthComputeCheck",
            schedule=events.Schedule.cron(hour="16", minute="58"),
            description="Phase 3.2: verify today's compute records exist before daily-brief",
        )
        compute_check_rule.add_target(
            targets.LambdaFunction(
                pipeline_health,
                event=events.RuleTargetInput.from_object({"check_compute_outputs": True}),
            )
        )

        # ER-01 (2026-06-09): infra-liveness heartbeat. Fires once daily at 17:10
        # UTC = 10:10 AM PT — after the morning ingestion crons (4–10 AM PT hourly)
        # have all run, so the INGEST_HEALTH sentinels reflect the day's attempts.
        # Invokes with {check_ingest_liveness: true} so the Lambda asserts each
        # active source ran + 200'd (vs. behavioral freshness), emitting
        # UnhealthySourceCount for the ingest-liveness-unhealthy alarm.
        liveness_check_rule = events.Rule(
            self,
            "PipelineHealthIngestLiveness",
            schedule=events.Schedule.cron(hour="17", minute="10"),
            description="ER-01: assert each active source's ingestion Lambda ran + 200'd (infra-liveness)",
        )
        liveness_check_rule.add_target(
            targets.LambdaFunction(
                pipeline_health,
                event=events.RuleTargetInput.from_object({"check_ingest_liveness": True}),
            )
        )

        # ── 14. Hevy Routine Cron (ADR-066) — Phase 3 scheduled generator ──
        # SHIPS DISABLED at the EventBridge level AND SSM /life-platform/hevy/cron_enabled
        # defaults to "false" (belt-and-suspenders gate). Operator flips both ON
        # after ~3 weeks of Phase 1 chat-path usage justifies it (SPEC §2).
        # Schedule expression below is for the eventual cadence — Sunday 06:30 PT
        # (13:30 UTC, UTC-fixed, no DST). Until enabled, the cron does not fire.
        hevy_routine_cron = create_platform_lambda(
            self,
            "HevyRoutineCron",
            function_name="hevy-routine-cron",
            source_file="lambdas/operational/hevy_routine_cron_lambda.py",
            handler="operational.hevy_routine_cron_lambda.lambda_handler",
            timeout_seconds=120,
            memory_mb=256,
            environment={
                "TABLE_NAME": TABLE_NAME,
                "USER_ID": "matthew",
                "S3_BUCKET": "matthew-life-platform",
                "PAUSE_MODE_PARAM": "/life-platform/pause-mode",
                "BUDGET_TIER_PARAM": "/life-platform/budget-tier",
                "HEVY_CRON_ENABLED_PARAM": "/life-platform/hevy/cron_enabled",
                "HEVY_ADD_LOAD_PARAM": "/life-platform/hevy/autoreg_add_load_enabled",
                "HEVY_WRITE_SECRET": "life-platform/hevy-write",
            },
            custom_policies=rp.hevy_routine_cron(),
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=local_alerts_topic,
            digest_topic=local_digest_topic,
            digest=True,
            alarm_name="hevy-routine-cron-errors",
        )
        # Manual events.Rule escape hatch — create_platform_lambda's schedule= shortcut
        # auto-enables the rule. ADR-066 ships disabled. Do NOT collapse this back.
        hevy_routine_cron_rule = events.Rule(
            self,
            "HevyRoutineCronRule",
            rule_name="hevy-routine-cron-weekly",
            description="ADR-066 ships disabled; operator enables after Phase 1 use justifies it.",
            schedule=events.Schedule.expression("cron(30 13 ? * SUN *)"),
            enabled=False,
        )
        hevy_routine_cron_rule.add_target(targets.LambdaFunction(hevy_routine_cron))

        # ── 14b. Hevy Overnight Branch Re-stamp (#417 / TR-05) ──
        # Runs AFTER the overnight wearable sync and RE-ORDERS / re-highlights
        # which branch of the already-pushed routine is recommended, so the
        # morning's plan reflects the night's recovery. FAILS OPEN: a missed or
        # failed run leaves the last pushed routine fully usable. Never adds or
        # removes a branch.
        #
        # Schedule (UTC-fixed, no DST): 18:00 UTC = 10:00 PST / 11:00 PDT — moved
        # here (from the originally proposed 12:45 UTC) per Matthew's call on
        # PR #711's deferred decision 2a: Whoop recovery refreshes ~17:30 UTC, so
        # 12:45 UTC would have re-stamped on STALE recovery. 18:00 UTC runs after
        # the recovery pull lands. ENABLED here; the SSM belt-and-suspenders gate
        # (/life-platform/hevy/restamp_enabled, default "false") is flipped true
        # as a separate post-merge step so the enabled rule and the new push
        # format (#417 2b) arrive together.
        hevy_restamp = create_platform_lambda(
            self,
            "HevyRestamp",
            function_name="hevy-restamp",
            source_file="lambdas/operational/hevy_restamp_lambda.py",
            handler="operational.hevy_restamp_lambda.lambda_handler",
            timeout_seconds=120,
            memory_mb=256,
            environment={
                "TABLE_NAME": TABLE_NAME,
                "USER_ID": "matthew",
                "S3_BUCKET": "matthew-life-platform",
                "PAUSE_MODE_PARAM": "/life-platform/pause-mode",
                "BUDGET_TIER_PARAM": "/life-platform/budget-tier",
                "HEVY_RESTAMP_ENABLED_PARAM": "/life-platform/hevy/restamp_enabled",
                "HEVY_WRITE_SECRET": "life-platform/hevy-write",
            },
            custom_policies=rp.hevy_restamp(),
            table=local_table,
            bucket=local_bucket,
            dlq=None,
            alerts_topic=local_alerts_topic,
            digest_topic=local_digest_topic,
            digest=True,
            alarm_name="hevy-restamp-errors",
        )
        hevy_restamp_rule = events.Rule(
            self,
            "HevyRestampRule",
            rule_name="hevy-restamp-daily",
            description="#417 TR-05: re-stamps on fresh Whoop recovery (~17:30 UTC refresh); enabled post PR #711 decision 2a.",
            schedule=events.Schedule.expression("cron(0 18 * * ? *)"),
            enabled=True,
        )
        hevy_restamp_rule.add_target(targets.LambdaFunction(hevy_restamp))

        cdk.CfnOutput(self, "FreshnessCheckerArn", value=freshness.function_arn, description="Freshness checker Lambda ARN")
        cdk.CfnOutput(self, "CanaryArn", value=canary.function_arn, description="Canary Lambda ARN")
