"""
CoreStack — DynamoDB, S3, SQS DLQ, SNS alerts.

These resources already exist in AWS. First deployment uses `cdk import` to
bring them under CDK management without recreating them.

Import procedure (run once):
  1. Deploy this stack with the import-friendly constructs
  2. Run: cdk import LifePlatformCore
  3. CDK will prompt for the physical resource IDs:
     - DynamoDB table: life-platform
     - S3 bucket: matthew-life-platform
     - SQS queue: https://sqs.us-west-2.amazonaws.com/205930651321/life-platform-ingestion-dlq
     - SNS topic: arn:aws:sns:us-west-2:205930651321:life-platform-alerts
"""

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    RemovalPolicy,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_sqs as sqs,
    aws_sns as sns,
    Duration,
)
from constructs import Construct


class CoreStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        ctx = self.node.try_get_context

        # ══════════════════════════════════════════════════════════════
        # DynamoDB — single-table design
        # ══════════════════════════════════════════════════════════════
        self.table = dynamodb.Table(
            self, "LifePlatformTable",
            table_name=ctx("ddb_table_name") or "life-platform",
            partition_key=dynamodb.Attribute(
                name="pk", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
            deletion_protection=True,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            time_to_live_attribute="ttl",
        )

        # ══════════════════════════════════════════════════════════════
        # S3 — raw data + static website hosting
        # ══════════════════════════════════════════════════════════════
        self.bucket = s3.Bucket(
            self, "LifePlatformBucket",
            bucket_name=ctx("s3_bucket_name") or "matthew-life-platform",
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
            versioned=False,
            block_public_access=s3.BlockPublicAccess(
                block_public_acls=True,
                block_public_policy=True,
                ignore_public_acls=True,
                restrict_public_buckets=True,
            ),
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="archive-raw-to-glacier",
                    prefix="raw/",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.GLACIER,
                            transition_after=Duration.days(90),
                        )
                    ],
                ),
            ],
        )

        # ══════════════════════════════════════════════════════════════
        # SQS — Dead Letter Queue for failed Lambda invocations
        # ══════════════════════════════════════════════════════════════
        self.dlq = sqs.Queue(
            self, "IngestionDLQ",
            queue_name=ctx("sqs_dlq_name") or "life-platform-ingestion-dlq",
            retention_period=Duration.days(14),
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ══════════════════════════════════════════════════════════════
        # SNS — Alert routing
        # ══════════════════════════════════════════════════════════════
        self.alerts_topic = sns.Topic(
            self, "AlertsTopic",
            topic_name=ctx("sns_topic_name") or "life-platform-alerts",
        )

        # ══════════════════════════════════════════════════════════════
        # Outputs (for cross-stack references)
        # ══════════════════════════════════════════════════════════════
        cdk.CfnOutput(self, "TableName", value=self.table.table_name)
        cdk.CfnOutput(self, "TableArn", value=self.table.table_arn)
        cdk.CfnOutput(self, "BucketName", value=self.bucket.bucket_name)
        cdk.CfnOutput(self, "BucketArn", value=self.bucket.bucket_arn)
        cdk.CfnOutput(self, "DlqUrl", value=self.dlq.queue_url)
        cdk.CfnOutput(self, "DlqArn", value=self.dlq.queue_arn)
        cdk.CfnOutput(self, "AlertsTopicArn", value=self.alerts_topic.topic_arn)
