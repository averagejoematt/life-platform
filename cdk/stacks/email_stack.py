"""
EmailStack — email/digest Lambdas + EventBridge schedules.

Lambdas (8):
  daily-brief             cron(0 17 * * ? *)      — 10:00 AM PDT daily (8:15 AM -> 10 AM after DST)
  weekly-digest           cron(0 16 ? * SUN *)    — Sunday 8:00 AM PT
  monthly-digest          cron(0 16 ? * 1#1 *)    — First Sunday of month 8:00 AM PT
  nutrition-review        cron(0 17 ? * SAT *)    — Saturday 9:00 AM PT
  wednesday-chronicle     cron(0 15 ? * WED *)    — Wednesday 7:00 AM PT
  weekly-plate            cron(0 2  ? * SAT *)    — Friday 6:00 PM PT (Sat 02:00 UTC)
  monday-compass          cron(0 15 ? * MON *)    — Monday 7:00 AM PT
  brittany-weekly-email   cron(30 17 ? * 1 *)     — Sunday 9:30 AM PT

Special handler notes:
  weekly-digest: handler = digest_handler.lambda_handler (not <module>.lambda_handler)
  All others: <source_module>.lambda_handler convention.

Handler naming convention: <source_module>.lambda_handler
  All handlers verified against actual source file function signatures.
  DO NOT change handlers to lambda_function.lambda_handler — that would break existing Lambdas.

All use from_role_arn() to reference existing IAM roles — no DefaultPolicy generated.
Cross-stack resources resolved locally — no Fn::ImportValue (CoreStack not yet in CFn).

Import procedure (first time only):
  cdk import LifePlatformEmail --resource-mapping email-import-map.json

After import: run drift detection to confirm role + env var alignment.
  aws cloudformation detect-stack-drift --stack-name LifePlatformEmail
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

REGION = "us-west-2"
ACCT = "205930651321"

# ── Core resource ARNs (resolved locally — CoreStack not yet in CloudFormation) ──
INGESTION_DLQ_ARN    = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
LIFE_PLATFORM_TABLE  = "life-platform"
LIFE_PLATFORM_BUCKET = "matthew-life-platform"
ALERTS_TOPIC_ARN     = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"

def _role(name): return f"arn:aws:iam::{ACCT}:role/{name}"

# ── IAM role ARNs ──
# SEC-1 (setup_sec1_iam_roles.sh) created per-function roles for all email Lambdas.
# Verify actual roles with:
#   for fn in daily-brief weekly-digest monthly-digest nutrition-review \
#       wednesday-chronicle weekly-plate monday-compass brittany-weekly-email; do
#     echo "$fn: $(aws lambda get-function-configuration --function-name $fn --query Role --output text)"
#   done
ROLE_ARNS = {
    "daily_brief":     _role("lambda-daily-brief-role"),
    "weekly_digest":   _role("lambda-weekly-digest-role-v2"),
    "monthly_digest":  _role("lambda-monthly-digest-role"),
    "nutrition":       _role("lambda-nutrition-review-role"),
    "chronicle":       _role("lambda-wednesday-chronicle-role"),
    "weekly_plate":    _role("lambda-weekly-plate-role"),
    "monday_compass":  _role("lambda-monday-compass-role"),
    "brittany":        _role("lambda-weekly-digest-role"),    # original deploy used shared role
}


class EmailStack(Stack):

    def __init__(self, scope: Construct, construct_id: str,
                 table, bucket, dlq, alerts_topic, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── Local resource references (bypass cross-stack Fn::ImportValue) ──
        local_dlq          = sqs.Queue.from_queue_arn(self, "IngestionDLQ", INGESTION_DLQ_ARN)
        local_table        = dynamodb.Table.from_table_name(self, "LifePlatformTable", LIFE_PLATFORM_TABLE)
        local_bucket       = s3.Bucket.from_bucket_name(self, "LifePlatformBucket", LIFE_PLATFORM_BUCKET)
        local_alerts_topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)

        shared = dict(
            table=local_table,
            bucket=local_bucket,
            dlq=local_dlq,
            alerts_topic=local_alerts_topic,
        )

        # ══════════════════════════════════════════════════════════════
        # 1. daily-brief — 10:00 AM PDT daily
        # Heaviest Lambda: BoD + TL;DR + training/nutrition coach AI calls
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "DailyBrief",
            function_name="daily-brief",
            handler="daily_brief_lambda.lambda_handler",
            source_file="lambdas/daily_brief_lambda.py",
            schedule="cron(0 17 * * ? *)",
            timeout_seconds=300,
            memory_mb=512,
            existing_role_arn=ROLE_ARNS["daily_brief"],
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # 2. weekly-digest — Sunday 8:00 AM PT
        # SPECIAL: handler is digest_handler.lambda_handler (not <module>.lambda_handler)
        # This is an intentional deviation from the naming convention — the weekly-digest
        # Lambda was deployed with digest_handler.py as the entry point.
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "WeeklyDigest",
            function_name="weekly-digest",
            handler="digest_handler.lambda_handler",
            source_file="lambdas/weekly_digest_lambda.py",
            schedule="cron(0 16 ? * SUN *)",
            timeout_seconds=120,
            memory_mb=256,
            existing_role_arn=ROLE_ARNS["weekly_digest"],
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # 3. monthly-digest — First Sunday of month 8:00 AM PT
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "MonthlyDigest",
            function_name="monthly-digest",
            handler="monthly_digest_lambda.lambda_handler",
            source_file="lambdas/monthly_digest_lambda.py",
            schedule="cron(0 16 ? * 1#1 *)",
            timeout_seconds=120,
            memory_mb=256,
            existing_role_arn=ROLE_ARNS["monthly_digest"],
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # 4. nutrition-review — Saturday 9:00 AM PT
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "NutritionReview",
            function_name="nutrition-review",
            handler="nutrition_review_lambda.lambda_handler",
            source_file="lambdas/nutrition_review_lambda.py",
            schedule="cron(0 17 ? * SAT *)",
            timeout_seconds=120,
            memory_mb=256,
            existing_role_arn=ROLE_ARNS["nutrition"],
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # 5. wednesday-chronicle — Wednesday 7:00 AM PT
        # Elena Voss "The Measured Life" blog + email narrative
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "WednesdayChronicle",
            function_name="wednesday-chronicle",
            handler="wednesday_chronicle_lambda.lambda_handler",
            source_file="lambdas/wednesday_chronicle_lambda.py",
            schedule="cron(0 15 ? * WED *)",
            timeout_seconds=120,
            memory_mb=256,
            existing_role_arn=ROLE_ARNS["chronicle"],
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # 6. weekly-plate — Friday 6:00 PM PT (Saturday 02:00 UTC)
        # Food magazine column with Met Market grocery list
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "WeeklyPlate",
            function_name="weekly-plate",
            handler="weekly_plate_lambda.lambda_handler",
            source_file="lambdas/weekly_plate_lambda.py",
            schedule="cron(0 2 ? * SAT *)",
            timeout_seconds=120,
            memory_mb=512,
            existing_role_arn=ROLE_ARNS["weekly_plate"],
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # 7. monday-compass — Monday 7:00 AM PT
        # Weekly planning email with Todoist project context
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "MondayCompass",
            function_name="monday-compass",
            handler="monday_compass_lambda.lambda_handler",
            source_file="lambdas/monday_compass_lambda.py",
            schedule="cron(0 15 ? * MON *)",
            timeout_seconds=120,
            memory_mb=512,
            existing_role_arn=ROLE_ARNS["monday_compass"],
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # 8. brittany-weekly-email — Sunday 9:30 AM PT
        # Partner accountability email — sent after Matthew's weekly digest
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "BrittanyWeeklyEmail",
            function_name="brittany-weekly-email",
            handler="brittany_email_lambda.lambda_handler",
            source_file="lambdas/brittany_email_lambda.py",
            schedule="cron(30 17 ? * 1 *)",
            timeout_seconds=90,
            memory_mb=256,
            existing_role_arn=ROLE_ARNS["brittany"],
            **shared,
        )
