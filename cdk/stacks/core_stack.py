"""
CoreStack — Shared infrastructure: SQS DLQ, SNS alerts, Lambda Layer.

DynamoDB and S3 are deliberately NOT CDK-managed (stateful resources).
SQS DLQ and SNS topic are CDK-managed via `cdk import` (first time).
Lambda Layer is CDK-managed — new versions published on each deploy.

IMPORTANT: Run `bash deploy/build_layer.sh` before `cdk deploy` to
build the layer directory at cdk/layer-build/python/*.
"""

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    RemovalPolicy,
    Duration,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_sqs as sqs,
    aws_sns as sns,
    aws_lambda as _lambda,
    aws_kms as kms,
    aws_iam as iam,
)
from constructs import Construct


class CoreStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        ctx = self.node.try_get_context

        # ── DynamoDB — lookup only (NOT CDK-managed) ──
        self.table = dynamodb.Table.from_table_name(
            self, "LifePlatformTable",
            table_name=ctx("ddb_table_name") or "life-platform",
        )

        # ── S3 — lookup only (NOT CDK-managed) ──
        self.bucket = s3.Bucket.from_bucket_name(
            self, "LifePlatformBucket",
            bucket_name=ctx("s3_bucket_name") or "matthew-life-platform",
        )

        # ── SQS DLQ (CDK-managed, imported first time) ──
        self.dlq = sqs.Queue(
            self, "IngestionDLQ",
            queue_name="life-platform-ingestion-dlq",
            retention_period=Duration.days(14),
            visibility_timeout=Duration.seconds(30),
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ── SNS alerts (CDK-managed, imported first time) ──
        # Two-tier alerting (ADR-050): urgent goes straight to inbox; digest
        # accumulates in SQS and is drained once daily by alert_digest_lambda.
        self.alerts_topic = sns.Topic(
            self, "AlertsTopic",
            topic_name="life-platform-alerts",
        )
        self.digest_topic = sns.Topic(
            self, "DigestTopic",
            topic_name="life-platform-alerts-digest",
        )

        # ── KMS CMK for S3 (Phase 2.4, ADR-052+) ───────────────────────
        # Created so the bucket can switch from AES256 (AWS-managed shared key)
        # to KMS CMK encryption. Only NEW objects use this key by default;
        # existing 27k AES256 objects remain as-is (user opted "new only").
        # Annual rotation enabled by default in CDK.
        # Policy: account-wide use (mirrors the DDB CMK pattern at
        # 444438d1-a5e0-43b8-9391-3cd2d70dde4d) — IAM controls who can use it.
        self.s3_kms_key = kms.Key(
            self, "S3DataKey",
            alias="alias/life-platform-s3",
            description="Life Platform S3 bucket data encryption (Phase 2.4)",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.RETAIN,
        )
        # Allow account to use the key — same pattern as DDB CMK.
        self.s3_kms_key.grant_encrypt_decrypt(iam.AccountRootPrincipal())

        # P2.4-followup (v7.21.0, 2026-05-17): CloudFront must be able to
        # decrypt KMS-encrypted objects in the site bucket. Without this grant,
        # any KMS-encrypted object under site/ returns HTTP 400 to CloudFront
        # readers ("InvalidRequest: stored using a form of Server Side
        # Encryption"). Surfaced on 2026-05-17 when a default `aws s3 cp`
        # broke averagejoematt.com for ~90 seconds.
        #
        # Scope: cloudfront.amazonaws.com service principal, restricted via
        # aws:SourceAccount to this account only. CloudFront only triggers a
        # KMS decrypt when serving an object from a configured S3 origin —
        # the principal can't decrypt arbitrary objects elsewhere.
        self.s3_kms_key.grant_decrypt(
            iam.ServicePrincipal(
                "cloudfront.amazonaws.com",
                conditions={"StringEquals": {"aws:SourceAccount": cdk.Aws.ACCOUNT_ID}},
            )
        )

        # ── Lambda Layer (CDK-managed) ──
        # Pre-built by deploy/build_layer.sh → cdk/layer-build/python/
        # No Docker needed. CDK zips the directory and publishes.
        self.shared_layer = _lambda.LayerVersion(
            self, "SharedUtilsLayer",
            layer_version_name="life-platform-shared-utils",
            code=_lambda.Code.from_asset("layer-build"),
            compatible_runtimes=[_lambda.Runtime.PYTHON_3_12],
            description="Shared utils for Life Platform Lambdas",
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ── Outputs ──
        cdk.CfnOutput(self, "TableName", value=self.table.table_name)
        cdk.CfnOutput(self, "BucketName", value=self.bucket.bucket_name)
        cdk.CfnOutput(self, "DlqUrl", value=self.dlq.queue_url)
        cdk.CfnOutput(self, "DlqArn", value=self.dlq.queue_arn)
        cdk.CfnOutput(self, "AlertsTopicArn", value=self.alerts_topic.topic_arn)
        cdk.CfnOutput(self, "DigestTopicArn", value=self.digest_topic.topic_arn)
        cdk.CfnOutput(self, "SharedLayerArn", value=self.shared_layer.layer_version_arn)
        cdk.CfnOutput(self, "S3KmsKeyArn", value=self.s3_kms_key.key_arn)
        cdk.CfnOutput(self, "S3KmsKeyId", value=self.s3_kms_key.key_id)
