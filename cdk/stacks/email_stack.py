"""
EmailStack — email/digest Lambdas + EventBridge schedules.

v2.0 (v3.4.0): CDK-managed IAM roles replace existing_role_arn references.
  All 8 Lambdas get dedicated CDK-owned roles with least-privilege policies.

Lambdas (8):
  daily-brief, weekly-digest, monthly-digest, nutrition-review,
  wednesday-chronicle, weekly-plate, monday-compass, brittany-weekly-email

Special handler: weekly-digest uses digest_handler.lambda_handler
"""

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_iam as iam,
    aws_sqs as sqs,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_sns as sns,
)
from constructs import Construct

from stacks.lambda_helpers import create_platform_lambda
from stacks import role_policies as rp

REGION = "us-west-2"
ACCT = "205930651321"

INGESTION_DLQ_ARN    = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
LIFE_PLATFORM_TABLE  = "life-platform"
LIFE_PLATFORM_BUCKET = "matthew-life-platform"
ALERTS_TOPIC_ARN     = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"


class EmailStack(Stack):

    def __init__(self, scope: Construct, construct_id: str,
                 table, bucket, dlq, alerts_topic, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        local_dlq          = sqs.Queue.from_queue_arn(self, "IngestionDLQ", INGESTION_DLQ_ARN)
        local_table        = dynamodb.Table.from_table_name(self, "LifePlatformTable", LIFE_PLATFORM_TABLE)
        local_bucket       = s3.Bucket.from_bucket_name(self, "LifePlatformBucket", LIFE_PLATFORM_BUCKET)
        local_alerts_topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)

        shared = dict(table=local_table, bucket=local_bucket, dlq=local_dlq, alerts_topic=local_alerts_topic)

        # daily-brief: alerts_topic=None — MonitoringStack owns its alarms
        # (slo-daily-brief-delivery, life-platform-daily-brief-errors,
        #  daily-brief-no-invocations-24h, daily-brief-duration-high).
        # Suppressed here to avoid ingestion-error-daily-brief duplicate. COST-A 2026-03-10.
        _email_env = {"ANTHROPIC_SECRET": "life-platform/ai-keys"}

        create_platform_lambda(self, "DailyBrief", function_name="daily-brief", handler="daily_brief_lambda.lambda_handler", source_file="lambdas/daily_brief_lambda.py", schedule="cron(0 17 * * ? *)", timeout_seconds=300, memory_mb=512, environment=_email_env, custom_policies=rp.email_daily_brief(), **{**shared, "alerts_topic": None})

        create_platform_lambda(self, "WeeklyDigest", function_name="weekly-digest", handler="digest_handler.lambda_handler", source_file="lambdas/weekly_digest_lambda.py", schedule="cron(0 16 ? * SUN *)", timeout_seconds=120, memory_mb=256, environment=_email_env, custom_policies=rp.email_weekly_digest(), **shared)

        create_platform_lambda(self, "MonthlyDigest", function_name="monthly-digest", handler="monthly_digest_lambda.lambda_handler", source_file="lambdas/monthly_digest_lambda.py", schedule="cron(0 16 ? * 1#1 *)", timeout_seconds=120, memory_mb=256, environment=_email_env, custom_policies=rp.email_monthly_digest(), **shared)

        create_platform_lambda(self, "NutritionReview", function_name="nutrition-review", handler="nutrition_review_lambda.lambda_handler", source_file="lambdas/nutrition_review_lambda.py", schedule="cron(0 17 ? * SAT *)", timeout_seconds=120, memory_mb=256, environment=_email_env, custom_policies=rp.email_nutrition_review(), **shared)

        create_platform_lambda(self, "WednesdayChronicle", function_name="wednesday-chronicle", handler="wednesday_chronicle_lambda.lambda_handler", source_file="lambdas/wednesday_chronicle_lambda.py", schedule="cron(0 15 ? * WED *)", timeout_seconds=120, memory_mb=256, environment=_email_env, custom_policies=rp.email_wednesday_chronicle(), **shared)

        create_platform_lambda(self, "WeeklyPlate", function_name="weekly-plate", handler="weekly_plate_lambda.lambda_handler", source_file="lambdas/weekly_plate_lambda.py", schedule="cron(0 2 ? * SAT *)", timeout_seconds=120, memory_mb=512, environment=_email_env, custom_policies=rp.email_weekly_plate(), **shared)

        create_platform_lambda(self, "MondayCompass", function_name="monday-compass", handler="monday_compass_lambda.lambda_handler", source_file="lambdas/monday_compass_lambda.py", schedule="cron(0 15 ? * MON *)", timeout_seconds=120, memory_mb=512, environment=_email_env, custom_policies=rp.email_monday_compass(), **shared)

        _brittany_env = {**_email_env, "BRITTANY_EMAIL": "awsdev@mattsusername.com"}
        create_platform_lambda(self, "BrittanyWeeklyEmail", function_name="brittany-weekly-email", handler="brittany_email_lambda.lambda_handler", source_file="lambdas/brittany_email_lambda.py", schedule="cron(30 17 ? * 1 *)", timeout_seconds=90, memory_mb=256, environment=_brittany_env, custom_policies=rp.email_brittany(), **shared)
