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
        self.alerts_topic = sns.Topic(
            self, "AlertsTopic",
            topic_name="life-platform-alerts",
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
        cdk.CfnOutput(self, "SharedLayerArn", value=self.shared_layer.layer_version_arn)
