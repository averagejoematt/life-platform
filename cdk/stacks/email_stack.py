"""
EmailStack — email/digest Lambdas + EventBridge schedules.

v2.0 (v3.4.0): CDK-managed IAM roles replace existing_role_arn references.
  All 8 Lambdas get dedicated CDK-owned roles with least-privilege policies.

v2.1 (v3.7.62): BS-03 Chronicle Email Sender added.
v2.2 (FEAT-12): chronicle-approve Lambda + preview-before-publish workflow.

Lambdas (10):
  daily-brief, weekly-digest, monthly-digest, nutrition-review,
  wednesday-chronicle, weekly-plate, monday-compass, brittany-weekly-email,
  evening-nudge, chronicle-email-sender (BS-03), chronicle-approve (FEAT-12)

"""

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_sqs as sqs,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_sns as sns,
)
from constructs import Construct

from stacks.lambda_helpers import create_platform_lambda
from stacks import role_policies as rp
from stacks.constants import SHARED_LAYER_ARN, ACCT, REGION, CF_DIST_ID  # single source of truth for layer version

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

        shared_utils_layer = _lambda.LayerVersion.from_layer_version_arn(self, "SharedUtilsLayer", SHARED_LAYER_ARN)
        shared = dict(table=local_table, bucket=local_bucket, dlq=local_dlq, alerts_topic=local_alerts_topic,
                      shared_layer=shared_utils_layer)

        # daily-brief: alerts_topic=None — MonitoringStack owns its alarms
        # (slo-daily-brief-delivery, life-platform-daily-brief-errors,
        #  daily-brief-no-invocations-24h, daily-brief-duration-high).
        # Suppressed here to avoid ingestion-error-daily-brief duplicate. COST-A 2026-03-10.
        _email_env = {"ANTHROPIC_SECRET": "life-platform/ai-keys"}

        create_platform_lambda(self, "DailyBrief", function_name="daily-brief", handler="daily_brief_lambda.lambda_handler", source_file="lambdas/daily_brief_lambda.py", schedule="cron(0 17 * * ? *)", timeout_seconds=300, memory_mb=512, environment=_email_env, custom_policies=rp.email_daily_brief(), **{**shared, "alerts_topic": None})

        create_platform_lambda(self, "WeeklyDigest", function_name="weekly-digest", handler="weekly_digest_lambda.lambda_handler", source_file="lambdas/weekly_digest_lambda.py", schedule="cron(0 16 ? * SUN *)", timeout_seconds=120, memory_mb=256, environment=_email_env, custom_policies=rp.email_weekly_digest(), **shared)

        create_platform_lambda(self, "MonthlyDigest", function_name="monthly-digest", handler="monthly_digest_lambda.lambda_handler", source_file="lambdas/monthly_digest_lambda.py", schedule="cron(0 16 ? * 1#1 *)", timeout_seconds=120, memory_mb=256, environment=_email_env, custom_policies=rp.email_monthly_digest(), **shared)

        create_platform_lambda(self, "NutritionReview", function_name="nutrition-review", handler="nutrition_review_lambda.lambda_handler", source_file="lambdas/nutrition_review_lambda.py", schedule="cron(0 17 ? * SAT *)", timeout_seconds=120, memory_mb=256, environment=_email_env, custom_policies=rp.email_nutrition_review(), **shared)

        wednesday_chronicle = create_platform_lambda(self, "WednesdayChronicle", function_name="wednesday-chronicle", handler="wednesday_chronicle_lambda.lambda_handler", source_file="lambdas/wednesday_chronicle_lambda.py", schedule="cron(0 15 ? * WED *)", timeout_seconds=120, memory_mb=256, environment=_email_env, custom_policies=rp.email_wednesday_chronicle(), **shared)

        create_platform_lambda(self, "WeeklyPlate", function_name="weekly-plate", handler="weekly_plate_lambda.lambda_handler", source_file="lambdas/weekly_plate_lambda.py", schedule="cron(0 2 ? * SAT *)", timeout_seconds=120, memory_mb=512, environment=_email_env, custom_policies=rp.email_weekly_plate(), **shared)

        create_platform_lambda(self, "MondayCompass", function_name="monday-compass", handler="monday_compass_lambda.lambda_handler", source_file="lambdas/monday_compass_lambda.py", schedule="cron(0 15 ? * MON *)", timeout_seconds=120, memory_mb=512, environment=_email_env, custom_policies=rp.email_monday_compass(), **shared)

        _brittany_env = {**_email_env, "BRITTANY_EMAIL": "brittany@mattsusername.com", "EMAIL_SENDER": "awsdev@mattsusername.com"}
        create_platform_lambda(self, "BrittanyWeeklyEmail", function_name="brittany-weekly-email", handler="brittany_email_lambda.lambda_handler", source_file="lambdas/brittany_email_lambda.py", schedule="cron(30 17 ? * 1 *)", timeout_seconds=90, memory_mb=256, environment=_brittany_env, custom_policies=rp.email_brittany(), **shared)

        # R54: Evening nudge — checks supplements/journal/How We Feel completeness at 8 PM PT
        # cron(0 3 * * ? *) = 3:00 AM UTC = 8:00 PM PDT (UTC-7). Adjust after DST ends.
        create_platform_lambda(self, "EveningNudge", function_name="evening-nudge", handler="evening_nudge_lambda.lambda_handler", source_file="lambdas/evening_nudge_lambda.py", schedule="cron(0 3 * * ? *)", timeout_seconds=60, memory_mb=256, environment=_email_env, custom_policies=rp.email_evening_nudge(), **shared)

        # BS-03: Chronicle Email Sender — delivers Chronicle installment to confirmed subscribers.
        # Fires 10 min after wednesday-chronicle (cron(0 15 ? * WED *) = 8:00 AM PT).
        # Viktor guard: clean no-op if no installment found this week.
        # Independent DLQ + alarm from wednesday-chronicle.
        # timeout_seconds=300: headroom for ~300 subs at 1/sec rate limit.
        # Bump SEND_RATE_PER_SEC env var after SES production access is granted.
        chronicle_sender = create_platform_lambda(
            self, "ChronicleEmailSender",
            function_name="chronicle-email-sender",
            handler="chronicle_email_sender_lambda.lambda_handler",
            source_file="lambdas/chronicle_email_sender_lambda.py",
            schedule="cron(10 15 ? * WED *)",
            timeout_seconds=300,
            memory_mb=256,
            environment={
                "SITE_URL":          "https://averagejoematt.com",
                "SEND_RATE_PER_SEC": "14.0",
            },
            custom_policies=rp.email_chronicle_sender(),
            **shared,
        )

        # FEAT-12: Chronicle Approve Lambda — one-click approve/reject for Chronicle drafts.
        # Invoked via Lambda Function URL embedded in the preview email.
        # No EventBridge schedule — triggered only by Matthew clicking the preview email link.
        # approve → writes pre-built S3 artifacts, invalidates CF, invokes chronicle-email-sender.
        # request_changes → marks DDB status, no publish.
        chronicle_approve = create_platform_lambda(
            self, "ChronicleApprove",
            function_name="chronicle-approve",
            handler="chronicle_approve_lambda.lambda_handler",
            source_file="lambdas/chronicle_approve_lambda.py",
            timeout_seconds=30,
            memory_mb=256,
            environment={
                "CF_DIST_ID":                   CF_DIST_ID,
                "CHRONICLE_EMAIL_SENDER_ARN":    chronicle_sender.function_arn,
            },
            custom_policies=rp.email_chronicle_approve(),
            **shared,
        )
        approve_url_obj = chronicle_approve.add_function_url(
            auth_type=_lambda.FunctionUrlAuthType.NONE,
        )
        cdk.CfnOutput(self, "ChronicleApproveFunctionUrl",
            value=approve_url_obj.url,
            description="Lambda Function URL for chronicle-approve (FEAT-12 preview workflow)",
        )

        # Update wednesday-chronicle to know the approve Lambda URL.
        # PREVIEW_MODE defaults to 'true'; set to 'false' in CDK context to disable preview.
        _preview_mode = self.node.try_get_context("chronicle_preview_mode") or "true"
        wednesday_chronicle.add_environment("PREVIEW_MODE",       _preview_mode)
        wednesday_chronicle.add_environment("APPROVE_LAMBDA_URL", approve_url_obj.url)

        # ── Subscriber Onboarding — EXISTS as CLI-created Lambda. CDK import pending.
        # See docs/audits/AUDIT_2026-03-30_cdk_adoption.md for full plan.
