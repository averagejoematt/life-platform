"""
IngestionStack — All data ingestion Lambdas.

v2.1 (v3.4.0): CDK-managed IAM roles + CDK-managed EventBridge rules.
  - Each Lambda has dedicated CDK-owned role with least-privilege policies.
  - EventBridge rules created via schedule= (no more add_permission workaround).
  - Old console-created EB rules should be deleted after deploy.

Covers 15 Lambdas (13 scheduled + 1 S3-triggered + 1 API Gateway-triggered).
"""

import aws_cdk as cdk
from aws_cdk import (
    Stack, Duration,
    aws_lambda as _lambda, aws_iam as iam,
    aws_dynamodb as dynamodb, aws_s3 as s3, aws_sqs as sqs, aws_sns as sns,
    aws_events as events, aws_events_targets as targets,
)
from constructs import Construct
from stacks.lambda_helpers import create_platform_lambda
from stacks import role_policies as rp

SHARED_LAYER_ARN = "arn:aws:lambda:us-west-2:205930651321:layer:life-platform-shared-utils:4"
ACCT = "205930651321"
REGION = "us-west-2"
INGESTION_DLQ_ARN  = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
LIFE_PLATFORM_TABLE = "life-platform"
LIFE_PLATFORM_BUCKET = "matthew-life-platform"
ALERTS_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"


class IngestionStack(Stack):
    def __init__(self, scope, construct_id, table, bucket, dlq, alerts_topic, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        shared_utils_layer = _lambda.LayerVersion.from_layer_version_arn(self, "SharedUtilsLayer", SHARED_LAYER_ARN)
        local_dlq          = sqs.Queue.from_queue_arn(self, "IngestionDLQ", INGESTION_DLQ_ARN)
        local_table        = dynamodb.Table.from_table_name(self, "LifePlatformTable", LIFE_PLATFORM_TABLE)
        local_bucket       = s3.Bucket.from_bucket_name(self, "LifePlatformBucket", LIFE_PLATFORM_BUCKET)
        local_alerts_topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)
        shared = dict(table=local_table, bucket=local_bucket, dlq=local_dlq, alerts_topic=local_alerts_topic)

        # ── 1. Whoop — daily ingestion + recovery refresh (two schedules)
        whoop = create_platform_lambda(self, "WhoopIngestion",
            function_name="whoop-data-ingestion",
            source_file="lambdas/whoop_lambda.py",
            handler="whoop_lambda.lambda_handler",
            schedule="cron(0 14 * * ? *)",  # 6:00 AM PT daily
            timeout_seconds=300, alarm_name="ingestion-error-whoop",
            custom_policies=rp.ingestion_whoop(), **shared)
        # Second schedule: recovery refresh at 9:30 AM PT
        whoop_recovery = events.Rule(self, "WhoopRecoverySchedule",
            schedule=events.Schedule.expression("cron(30 17 * * ? *)"),
            description="Whoop recovery refresh — 9:30 AM PT")
        whoop_recovery.add_target(targets.LambdaFunction(whoop))

        # ── 2. Garmin — 6:00 AM PT daily
        create_platform_lambda(self, "GarminIngestion",
            function_name="garmin-data-ingestion",
            source_file="lambdas/garmin_lambda.py",
            handler="garmin_lambda.lambda_handler",
            schedule="cron(0 14 * * ? *)",
            timeout_seconds=300, memory_mb=512, shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_garmin(),
            alerts_topic=None, **{k: v for k, v in shared.items() if k != "alerts_topic"})

        # ── 3. Notion — 6:00 AM PT daily
        create_platform_lambda(self, "NotionIngestion",
            function_name="notion-journal-ingestion",
            source_file="lambdas/notion_lambda.py",
            handler="notion_lambda.lambda_handler",
            schedule="cron(0 14 * * ? *)",
            timeout_seconds=120,
            environment={"NOTION_SECRET_NAME": "life-platform/ingestion-keys"},
            custom_policies=rp.ingestion_notion(),
            alerts_topic=None, **{k: v for k, v in shared.items() if k != "alerts_topic"})

        # ── 4. Withings — 6:15 AM PT daily
        create_platform_lambda(self, "WithingsIngestion",
            function_name="withings-data-ingestion",
            source_file="lambdas/withings_lambda.py",
            handler="withings_lambda.lambda_handler",
            schedule="cron(15 14 * * ? *)",
            timeout_seconds=120, alarm_name="ingestion-error-withings",
            custom_policies=rp.ingestion_withings(), **shared)

        # ── 5. Habitify — 6:15 AM PT daily
        create_platform_lambda(self, "HabitifyIngestion",
            function_name="habitify-data-ingestion",
            source_file="lambdas/habitify_lambda.py",
            handler="habitify_lambda.lambda_handler",
            schedule="cron(15 14 * * ? *)",
            timeout_seconds=180,
            environment={"HABITIFY_SECRET_NAME": "life-platform/habitify"},
            custom_policies=rp.ingestion_habitify(),
            alerts_topic=None, **{k: v for k, v in shared.items() if k != "alerts_topic"})

        # ── 6. Strava — 6:30 AM PT daily
        create_platform_lambda(self, "StravaIngestion",
            function_name="strava-data-ingestion",
            source_file="lambdas/strava_lambda.py",
            handler="strava_lambda.lambda_handler",
            schedule="cron(30 14 * * ? *)",
            timeout_seconds=300, alarm_name="ingestion-error-strava",
            custom_policies=rp.ingestion_strava(), **shared)

        # ── 7. Journal Enrichment — 6:30 AM PT daily
        create_platform_lambda(self, "JournalEnrichment",
            function_name="journal-enrichment",
            source_file="lambdas/journal_enrichment_lambda.py",
            handler="journal_enrichment_lambda.lambda_handler",
            schedule="cron(30 14 * * ? *)",
            timeout_seconds=300,
            environment={"ANTHROPIC_SECRET": "life-platform/ai-keys"},
            custom_policies=rp.ingestion_journal_enrichment(),
            alerts_topic=None, **{k: v for k, v in shared.items() if k != "alerts_topic"})

        # ── 8. Todoist — 6:45 AM PT daily
        create_platform_lambda(self, "TodoistIngestion",
            function_name="todoist-data-ingestion",
            source_file="lambdas/todoist_lambda.py",
            handler="todoist_lambda.lambda_handler",
            schedule="cron(45 14 * * ? *)",
            timeout_seconds=120, alarm_name="ingestion-error-todoist",
            environment={"SECRET_NAME": "life-platform/ingestion-keys"},
            custom_policies=rp.ingestion_todoist(), **shared)

        # ── 9. Eight Sleep — 7:00 AM PT daily
        create_platform_lambda(self, "EightsleepIngestion",
            function_name="eightsleep-data-ingestion",
            source_file="lambdas/eightsleep_lambda.py",
            handler="eightsleep_lambda.lambda_handler",
            schedule="cron(0 15 * * ? *)",
            timeout_seconds=120, alarm_name="ingestion-error-eightsleep",
            custom_policies=rp.ingestion_eightsleep(), **shared)

        # ── 10. Activity Enrichment — 7:30 AM PT daily
        create_platform_lambda(self, "ActivityEnrichment",
            function_name="activity-enrichment",
            source_file="lambdas/enrichment_lambda.py",
            handler="enrichment_lambda.lambda_handler",
            schedule="cron(30 15 * * ? *)",
            timeout_seconds=300, alarm_name="ingestion-error-enrichment",
            custom_policies=rp.ingestion_activity_enrichment(), **shared)

        # ── 11. MacroFactor — 8:00 AM PT daily + S3 trigger
        macrofactor = create_platform_lambda(self, "MacrofactorIngestion",
            function_name="macrofactor-data-ingestion",
            source_file="lambdas/macrofactor_lambda.py",
            handler="macrofactor_lambda.lambda_handler",
            schedule="cron(0 16 * * ? *)",
            timeout_seconds=300, alarm_name="ingestion-error-macrofactor",
            custom_policies=rp.ingestion_macrofactor(), **shared)
        macrofactor.add_permission("S3InvokeMacrofactor",
            principal=iam.ServicePrincipal("s3.amazonaws.com"),
            source_arn=f"arn:aws:s3:::matthew-life-platform")

        # ── 12. Weather — 5:45 AM PT daily
        create_platform_lambda(self, "WeatherIngestion",
            function_name="weather-data-ingestion",
            source_file="lambdas/weather_handler.py",
            handler="weather_handler.lambda_handler",
            schedule="cron(45 13 * * ? *)",
            timeout_seconds=60,
            custom_policies=rp.ingestion_weather(),
            alerts_topic=None, **{k: v for k, v in shared.items() if k != "alerts_topic"})

        # ── 13. Dropbox Poll — every 30 minutes
        create_platform_lambda(self, "DropboxPoll",
            function_name="dropbox-poll",
            source_file="lambdas/dropbox_poll_lambda.py",
            handler="dropbox_poll_lambda.lambda_handler",
            schedule="rate(30 minutes)",
            timeout_seconds=120,
            environment={"SECRET_NAME": "life-platform/ingestion-keys"},
            custom_policies=rp.ingestion_dropbox(),
            alerts_topic=None, **{k: v for k, v in shared.items() if k != "alerts_topic"})

        # ── 14. Apple Health — S3 trigger only (no EventBridge)
        apple_health = create_platform_lambda(self, "AppleHealthIngestion",
            function_name="apple-health-ingestion",
            source_file="lambdas/apple_health_lambda.py",
            handler="apple_health_lambda.lambda_handler",
            timeout_seconds=300, memory_mb=512, alarm_name="ingestion-error-apple-health",
            custom_policies=rp.ingestion_apple_health(), **shared)
        apple_health.add_permission("S3InvokeAppleHealth",
            principal=iam.ServicePrincipal("s3.amazonaws.com"),
            source_arn=f"arn:aws:s3:::matthew-life-platform")

        # ── 15. Health Auto Export Webhook — API Gateway trigger
        _ASSET_EXCLUDES = ["__pycache__", "**/__pycache__/**", "*.pyc", "**/*.pyc", "*.md", ".DS_Store", "dashboard", "dashboard/**", "buddy", "buddy/**", "cf-auth", "cf-auth/**", "requirements", "requirements/**"]
        hae_role = iam.Role(self, "HaeWebhookRole", assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"), managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")])
        for stmt in rp.ingestion_hae():
            hae_role.add_to_policy(stmt)
        hae = _lambda.Function(self, "HaeWebhook", function_name="health-auto-export-webhook", runtime=_lambda.Runtime.PYTHON_3_12, handler="health_auto_export_lambda.lambda_handler", code=_lambda.Code.from_asset("../lambdas", exclude=_ASSET_EXCLUDES), role=hae_role, timeout=Duration.seconds(30), memory_size=256, environment={"TABLE_NAME": local_table.table_name, "S3_BUCKET": local_bucket.bucket_name, "USER_ID": self.node.try_get_context("user_id") or "matthew"})
        hae.add_permission("ApiGatewayInvoke", principal=iam.ServicePrincipal("apigateway.amazonaws.com"), source_arn=f"arn:aws:execute-api:{self.region}:{self.account}:a76xwxt2wa/*/*/ingest")

        cdk.CfnOutput(self, "WhoopFnArn", value=whoop.function_arn, description="Whoop ingestion Lambda ARN")
        cdk.CfnOutput(self, "HaeWebhookFnArn", value=hae.function_arn, description="Health Auto Export webhook Lambda ARN")
