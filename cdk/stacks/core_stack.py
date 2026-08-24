"""
CoreStack — Shared infrastructure: SQS DLQ, SNS alerts, budget.

DynamoDB and S3 are deliberately NOT CDK-managed (stateful resources).
SQS DLQ and SNS topic are CDK-managed via `cdk import` (first time).
The shared Lambda layer was RETIRED here (#781, 2026-07-06) — shared code
ships inside every function's staged full-tree bundle (deploy/build_bundle.py).
"""

import importlib.util
from pathlib import Path

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

from stacks.constants import TABLE_NAME  # #936: DR cutover — no hardcoded table names

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _governor_budget_amount_usd() -> float | int:
    """The monthly base ceiling, read from the cost governor at SYNTH time (#2898).

    The AWS Budgets backstop must equal the number the real-time governor enforces: a
    backstop left behind a raised base pages every month by construction (#2836). Before
    this it was a second hand-maintained copy, and the two had in fact sat out of step
    for six weeks on purpose, then silently by accident.

    Loaded BY PATH, not via `sys.path` (the idiom `scripts/check_doc_facts.py` already
    uses for its siblings): `cdk synth` runs this file inside a Node-launched Python
    process, and prepending a repo directory to that process's import path is how a
    module name collision becomes an unreproducible synth failure. `budget_ceilings`
    AST-parses the governor and imports nothing beyond the stdlib, so this adds no
    boto3/AWS dependency to synth.

    It RAISES if the number can't be derived — a synth that cannot read the ceiling
    must fail loudly, never fall back to a guessed dollar amount.

    The int-vs-float coercion lives in `budget_ceilings.budget_amount_usd`, not here, so
    the derivation guard can assert it without importing `aws_cdk` (which the offline
    test job does not have — see that function's docstring).
    """
    src = _REPO_ROOT / "scripts" / "budget_ceilings.py"
    spec = importlib.util.spec_from_file_location("_cdk_budget_ceilings", src)
    if spec is None or spec.loader is None:  # pragma: no cover - a missing file is a broken checkout
        raise RuntimeError(f"cannot load the budget-ceiling derivation from {src} (#2898)")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.budget_amount_usd()


BUDGET_AMOUNT_USD: float | int = _governor_budget_amount_usd()


class CoreStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        ctx = self.node.try_get_context

        # ── DynamoDB — lookup only (NOT CDK-managed) ──
        self.table = dynamodb.Table.from_table_name(
            self,
            "LifePlatformTable",
            table_name=ctx("ddb_table_name") or TABLE_NAME,
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
        # ADR-143 (#1333): the paging channel — SMS for the named ≤5-alarm P1 set
        # ONLY (never the alerts topic; that would page on every alarm). The phone
        # subscription is wired out-of-band from SSM /life-platform/paging-phone by
        # deploy/wire_paging_phone.sh — a SecureString can't be a CFN SNS endpoint,
        # and the number stays out of git and the template.
        self.paging_topic = sns.Topic(
            self,
            "PagingTopic",
            topic_name="life-platform-paging",
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

        # ── AWS Budget — single all-in monthly ceiling (replaces 2 stale $20 manual budgets) ──
        # The amount is `BUDGET_AMOUNT_USD`, DERIVED from the cost governor's
        # MONTHLY_CEILING at synth time (#2898) — never restated here, so the two can no
        # longer drift apart the way they did when the base moved and the backstop did not.
        # The logical ID "MonthlyBudget75" and budget_name "life-platform-monthly-75"
        # are HISTORICAL — deliberately NOT renamed, because budget_name is the
        # CfnBudget replacement key (a rename would delete + recreate the budget
        # and its notification history).
        # Lagged secondary backstop + notice; the real-time enforcer is the
        # cost_governor Lambda (token-metric estimate → SSM tier → bedrock_client gate).
        # Budgets data trails Bedrock spend 24-48h, so it's notice, not the hard stop.
        # NB: this backstop tracks the PERMANENT base only — it does not follow ADR-133
        # surge mode or a dated raise window. In either, the percentage alert emails just
        # arrive a little earlier than the governor's tiers, which is acceptable for a
        # notice-only channel.
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
                budget_limit=budgets.CfnBudget.SpendProperty(amount=BUDGET_AMOUNT_USD, unit="USD"),
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
