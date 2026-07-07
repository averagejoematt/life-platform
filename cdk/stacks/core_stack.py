"""
CoreStack — Shared infrastructure: SQS DLQ, SNS alerts, budget.

DynamoDB and S3 are deliberately NOT CDK-managed (stateful resources).
SQS DLQ and SNS topic are CDK-managed via `cdk import` (first time).
The shared Lambda layer was RETIRED here (#781, 2026-07-06) — shared code
ships inside every function's staged full-tree bundle (deploy/build_bundle.py).
"""

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_budgets as budgets,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_sns as sns,
    aws_sqs as sqs,
)
from constructs import Construct


class CoreStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        ctx = self.node.try_get_context

        # ── DynamoDB — lookup only (NOT CDK-managed) ──
        self.table = dynamodb.Table.from_table_name(
            self,
            "LifePlatformTable",
            table_name=ctx("ddb_table_name") or "life-platform",
        )

        # ── S3 — lookup only (NOT CDK-managed) ──
        self.bucket = s3.Bucket.from_bucket_name(
            self,
            "LifePlatformBucket",
            bucket_name=ctx("s3_bucket_name") or "matthew-life-platform",
        )

        # ── SQS DLQ (CDK-managed, imported first time) ──
        self.dlq = sqs.Queue(
            self,
            "IngestionDLQ",
            queue_name="life-platform-ingestion-dlq",
            retention_period=Duration.days(14),
            visibility_timeout=Duration.seconds(30),
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ── SNS alerts (CDK-managed, imported first time) ──
        # Two-tier alerting (ADR-050): urgent goes straight to inbox; digest
        # accumulates in SQS and is drained once daily by alert_digest_lambda.
        self.alerts_topic = sns.Topic(
            self,
            "AlertsTopic",
            topic_name="life-platform-alerts",
        )
        self.digest_topic = sns.Topic(
            self,
            "DigestTopic",
            topic_name="life-platform-alerts-digest",
        )

        # ── S3 CMK retired (ADR-058, 2026-05-24) ───────────────────────
        # The Phase 2.4 customer-managed S3 KMS key (5c50ca02-...) was
        # scheduled for deletion when the bucket moved to AES256 (SSE-S3).
        # CDK resource definition removed here; the key completes its
        # scheduled deletion independently. IAM policies in role_policies.py
        # still reference the (soon-orphan) ARN — harmless, cleaned up later.

        # ── Lambda Layer RETIRED (#781, 2026-07-06) ──
        # life-platform-shared-utils is no longer published or attached. Every
        # function's code asset is the staged full-tree bundle
        # (deploy/build_bundle.py), so shared modules ship inside the bundle and
        # layer-version drift is structurally impossible. The old published
        # versions remain in AWS (the resource had RemovalPolicy.RETAIN) but
        # nothing references them.

        # ── AWS Budget — single $75/mo all-in ceiling (replaces 2 stale $20 manual budgets) ──
        # Lagged secondary backstop + notice; the real-time enforcer is the
        # cost_governor Lambda (token-metric estimate → SSM tier → bedrock_client gate).
        # Budgets data trails Bedrock spend 24-48h, so it's notice, not the hard stop.
        budget_email = ctx("budget_email") or "awsdev@mattsusername.com"
        _budget_notifications = []
        for _thr, _type in [(50, "ACTUAL"), (70, "ACTUAL"), (85, "ACTUAL"), (100, "ACTUAL"), (100, "FORECASTED")]:
            _budget_notifications.append(
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        notification_type=_type,
                        comparison_operator="GREATER_THAN",
                        threshold=_thr,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[
                        budgets.CfnBudget.SubscriberProperty(
                            subscription_type="EMAIL",
                            address=budget_email,
                        )
                    ],
                )
            )
        budgets.CfnBudget(
            self,
            "MonthlyBudget75",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name="life-platform-monthly-75",
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=75, unit="USD"),
            ),
            notifications_with_subscribers=_budget_notifications,
        )

        # ── Outputs ──
        cdk.CfnOutput(self, "TableName", value=self.table.table_name)
        cdk.CfnOutput(self, "BucketName", value=self.bucket.bucket_name)
        cdk.CfnOutput(self, "DlqUrl", value=self.dlq.queue_url)
        cdk.CfnOutput(self, "DlqArn", value=self.dlq.queue_arn)
        cdk.CfnOutput(self, "AlertsTopicArn", value=self.alerts_topic.topic_arn)
        cdk.CfnOutput(self, "DigestTopicArn", value=self.digest_topic.topic_arn)
