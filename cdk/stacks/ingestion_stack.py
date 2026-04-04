"""
IngestionStack — All data ingestion Lambdas.

v2.1 (v3.4.0): CDK-managed IAM roles + CDK-managed EventBridge rules.
  - Each Lambda has dedicated CDK-owned role with least-privilege policies.
  - EventBridge rules created via schedule= (no more add_permission workaround).
  - Old console-created EB rules should be deleted after deploy.

Covers 16 Lambdas (13 scheduled + 1 S3-triggered + 1 API Gateway-triggered).
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
from stacks.constants import SHARED_LAYER_ARN, ACCT, REGION, TABLE_NAME, S3_BUCKET  # CONF-01

# ── Hourly ingestion with 10pm-4am PST maintenance window ──
# Active hours: 4am-10pm PST = UTC 12-6 (next day) = 0,1,2,3,4,5,12,13,14,15,16,17,18,19,20,21,22,23
# Skipped: UTC 6,7,8,9,10,11 = 10pm-4am PST (maintenance window — no user activity expected)
# Cost: ~$0/month — gap-aware Lambdas short-circuit in <50ms when no new data exists
INGEST_HOURLY = "0,1,2,3,4,5,12,13,14,15,16,17,18,19,20,21,22,23"

INGESTION_DLQ_ARN    = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
LIFE_PLATFORM_TABLE  = TABLE_NAME
LIFE_PLATFORM_BUCKET = S3_BUCKET
ALERTS_TOPIC_ARN     = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"


class IngestionStack(Stack):
    def __init__(self, scope, construct_id, table, bucket, dlq, alerts_topic, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        shared_utils_layer = _lambda.LayerVersion.from_layer_version_arn(self, "SharedUtilsLayer", SHARED_LAYER_ARN)
        local_dlq          = sqs.Queue.from_queue_arn(self, "IngestionDLQ", INGESTION_DLQ_ARN)
        local_table        = dynamodb.Table.from_table_name(self, "LifePlatformTable", LIFE_PLATFORM_TABLE)
        local_bucket       = s3.Bucket.from_bucket_name(self, "LifePlatformBucket", LIFE_PLATFORM_BUCKET)
        local_alerts_topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)
        shared = dict(table=local_table, bucket=local_bucket, dlq=local_dlq, alerts_topic=local_alerts_topic)

        # ── 1. Whoop — 5x daily ingestion + recovery refresh
        whoop = create_platform_lambda(self, "WhoopIngestion",
            function_name="whoop-data-ingestion",
            source_file="lambdas/whoop_lambda.py",
            handler="whoop_lambda.lambda_handler",
            schedule=f"cron(0 {INGEST_HOURLY} * * ? *)",
            timeout_seconds=300, alarm_name="ingestion-error-whoop",
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_whoop(), **shared)
        # Second schedule: recovery refresh at 9:30 AM PT
        # OAuth race prevention: max 1 concurrent invocation per OAuth Lambda (ADR-036 fix)
        # NOTE: Requires account concurrency limit increase from 10 → 50+ before enabling.
        # Request via AWS Support Console → Service Quotas → Lambda concurrent executions.
        # whoop.node.default_child.add_property_override("ReservedConcurrentExecutions", 1)

        whoop_recovery = events.Rule(self, "WhoopRecoverySchedule",
            schedule=events.Schedule.expression("cron(30 17 * * ? *)"),
            description="Whoop recovery refresh — 9:30 AM PT")
        whoop_recovery.add_target(targets.LambdaFunction(whoop))

        # ── 2. Garmin — 4x daily (Garmin API rate-limits OAuth token exchange at hourly frequency)
        garmin = create_platform_lambda(self, "GarminIngestion",
            function_name="garmin-data-ingestion",
            source_file="lambdas/garmin_lambda.py",
            handler="garmin_lambda.lambda_handler",
            schedule="cron(0 0,6,14,22 * * ? *)",
            timeout_seconds=300, memory_mb=512, shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_garmin(),
            alerts_topic=None, **{k: v for k, v in shared.items() if k != "alerts_topic"})
        # garmin.node.default_child.add_property_override("ReservedConcurrentExecutions", 1)

        # ── 3. Notion — 5x daily
        create_platform_lambda(self, "NotionIngestion",
            function_name="notion-journal-ingestion",
            source_file="lambdas/notion_lambda.py",
            handler="notion_lambda.lambda_handler",
            schedule=f"cron(0 {INGEST_HOURLY} * * ? *)",
            timeout_seconds=120,
            environment={"NOTION_SECRET_NAME": "life-platform/ingestion-keys"},
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_notion(),
            alerts_topic=None, **{k: v for k, v in shared.items() if k != "alerts_topic"})

        # ── 4. Withings — 5x daily (:05 stagger)
        withings = create_platform_lambda(self, "WithingsIngestion",
            function_name="withings-data-ingestion",
            source_file="lambdas/withings_lambda.py",
            handler="withings_lambda.lambda_handler",
            schedule=f"cron(5 {INGEST_HOURLY} * * ? *)",
            timeout_seconds=120, alarm_name="ingestion-error-withings",
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_withings(), **shared)
        # withings.node.default_child.add_property_override("ReservedConcurrentExecutions", 1)

        # ── 5. Habitify — 5x daily (:05 stagger)
        create_platform_lambda(self, "HabitifyIngestion",
            function_name="habitify-data-ingestion",
            source_file="lambdas/habitify_lambda.py",
            handler="habitify_lambda.lambda_handler",
            schedule=f"cron(5 {INGEST_HOURLY} * * ? *)",
            timeout_seconds=180,
            environment={"HABITIFY_SECRET_NAME": "life-platform/habitify"},
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_habitify(),
            alerts_topic=None, **{k: v for k, v in shared.items() if k != "alerts_topic"})

        # ── 6. Strava — 5x daily (:10 stagger)
        strava = create_platform_lambda(self, "StravaIngestion",
            function_name="strava-data-ingestion",
            source_file="lambdas/strava_lambda.py",
            handler="strava_lambda.lambda_handler",
            schedule=f"cron(10 {INGEST_HOURLY} * * ? *)",
            timeout_seconds=300, alarm_name="ingestion-error-strava",
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_strava(), **shared)
        # strava.node.default_child.add_property_override("ReservedConcurrentExecutions", 1)

        # ── 7. Journal Enrichment — 6:30 AM PT daily
        create_platform_lambda(self, "JournalEnrichment",
            function_name="journal-enrichment",
            source_file="lambdas/journal_enrichment_lambda.py",
            handler="journal_enrichment_lambda.lambda_handler",
            schedule="cron(30 14 * * ? *)",
            timeout_seconds=300,
            environment={"ANTHROPIC_SECRET": "life-platform/ai-keys"},
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_journal_enrichment(),
            alerts_topic=None, **{k: v for k, v in shared.items() if k != "alerts_topic"})

        # ── 8. Todoist — 2x daily (COST-OPT-2: low-frequency source, tasks logged in batches)
        create_platform_lambda(self, "TodoistIngestion",
            function_name="todoist-data-ingestion",
            source_file="lambdas/todoist_lambda.py",
            handler="todoist_lambda.lambda_handler",
            schedule="cron(15 14,2 * * ? *)",
            timeout_seconds=120, alarm_name="ingestion-error-todoist",
            environment={"SECRET_NAME": "life-platform/ingestion-keys"},
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_todoist(), **shared)

        # ── 9. Eight Sleep — 5x daily (:15 stagger)
        eightsleep = create_platform_lambda(self, "EightsleepIngestion",
            function_name="eightsleep-data-ingestion",
            source_file="lambdas/eightsleep_lambda.py",
            handler="eightsleep_lambda.lambda_handler",
            schedule=f"cron(15 {INGEST_HOURLY} * * ? *)",
            timeout_seconds=120, alarm_name="ingestion-error-eightsleep",
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_eightsleep(), **shared)
        # eightsleep.node.default_child.add_property_override("ReservedConcurrentExecutions", 1)

        # ── 10. Activity Enrichment — 7:30 AM PT daily
        create_platform_lambda(self, "ActivityEnrichment",
            function_name="activity-enrichment",
            source_file="lambdas/enrichment_lambda.py",
            handler="enrichment_lambda.lambda_handler",
            schedule="cron(30 15 * * ? *)",
            timeout_seconds=300, alarm_name="ingestion-error-enrichment",
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_activity_enrichment(), **shared)

        # ── 11. MacroFactor — 8:00 AM PT daily + S3 trigger
        macrofactor = create_platform_lambda(self, "MacrofactorIngestion",
            function_name="macrofactor-data-ingestion",
            source_file="lambdas/macrofactor_lambda.py",
            handler="macrofactor_lambda.lambda_handler",
            schedule="cron(0 16 * * ? *)",
            timeout_seconds=300, alarm_name="ingestion-error-macrofactor",
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_macrofactor(), **shared)
        macrofactor.add_permission("S3InvokeMacrofactor",
            principal=iam.ServicePrincipal("s3.amazonaws.com"),
            source_arn=f"arn:aws:s3:::{S3_BUCKET}",  # SEC-01: IAM level is bucket-scoped; prefix filtering enforced via S3 event notification filter on uploads/macrofactor/ prefix
            source_account=self.account)

        # ── 12. Weather — 2x daily (COST-OPT-2: weather doesn't change meaningfully hourly)
        create_platform_lambda(self, "WeatherIngestion",
            function_name="weather-data-ingestion",
            source_file="lambdas/weather_handler.py",
            handler="weather_handler.lambda_handler",
            schedule="cron(0 14,2 * * ? *)",
            timeout_seconds=60,
            shared_layer=shared_utils_layer,
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
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_dropbox(),
            alerts_topic=None, **{k: v for k, v in shared.items() if k != "alerts_topic"})

        # ── 14. Apple Health — S3 trigger only (no EventBridge)
        apple_health = create_platform_lambda(self, "AppleHealthIngestion",
            function_name="apple-health-ingestion",
            source_file="lambdas/apple_health_lambda.py",
            handler="apple_health_lambda.lambda_handler",
            timeout_seconds=300, memory_mb=512, alarm_name="ingestion-error-apple-health",
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_apple_health(), **shared)
        apple_health.add_permission("S3InvokeAppleHealth",
            principal=iam.ServicePrincipal("s3.amazonaws.com"),
            source_arn=f"arn:aws:s3:::{S3_BUCKET}",  # SEC-01: IAM level is bucket-scoped; prefix filtering enforced via S3 event notification filter on uploads/apple-health/ prefix
            source_account=self.account)

        # ── 15. Health Auto Export Webhook — API Gateway trigger
        _ASSET_EXCLUDES = ["__pycache__", "**/__pycache__/**", "*.pyc", "**/*.pyc", "*.md", ".DS_Store", "dashboard", "dashboard/**", "buddy", "buddy/**", "cf-auth", "cf-auth/**", "requirements", "requirements/**"]
        hae_role = iam.Role(self, "HaeWebhookRole", assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"), managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")])
        for stmt in rp.ingestion_hae():
            hae_role.add_to_policy(stmt)
        # NOTE: HAE uses code=from_asset (entire lambdas/ dir), not source_file=.
        # Handler health_auto_export_lambda.lambda_handler → lambdas/health_auto_export_lambda.py  # noqa: CDK_HANDLER_ORPHAN
        hae = _lambda.Function(self, "HaeWebhook", function_name="health-auto-export-webhook", runtime=_lambda.Runtime.PYTHON_3_12, handler="health_auto_export_lambda.lambda_handler", code=_lambda.Code.from_asset("../lambdas", exclude=_ASSET_EXCLUDES), role=hae_role, timeout=Duration.seconds(60), memory_size=256, environment={"TABLE_NAME": local_table.table_name, "S3_BUCKET": local_bucket.bucket_name, "USER_ID": self.node.try_get_context("user_id") or "matthew"})  # BUG-07: large Apple Health exports need >30s
        hae.add_permission("ApiGatewayInvoke", principal=iam.ServicePrincipal("apigateway.amazonaws.com"), source_arn=f"arn:aws:execute-api:{self.region}:{self.account}:a76xwxt2wa/*/*/ingest")

        # ── 16. Google Calendar — RETIRED (ADR-030, v3.7.46)
        # All integration paths blocked by Smartsheet IT policy or macOS restrictions.
        # Lambda + EventBridge rule removed. See docs/DECISIONS.md ADR-030.

        # ── 17. Food Delivery — S3 trigger on uploads/food_delivery/
        food_delivery = create_platform_lambda(self, "FoodDeliveryIngestion",
            function_name="food-delivery-ingestion",
            source_file="lambdas/food_delivery_lambda.py",
            handler="food_delivery_lambda.lambda_handler",
            timeout_seconds=60,
            shared_layer=shared_utils_layer,
            custom_policies=rp.food_delivery_ingestion(), **shared)
        food_delivery.add_permission("S3InvokeFoodDelivery",
            principal=iam.ServicePrincipal("s3.amazonaws.com"),
            source_arn=f"arn:aws:s3:::{S3_BUCKET}",
            source_account=self.account)

        # ── 18. Measurements — manual/MCP-triggered (no schedule)
        create_platform_lambda(self, "MeasurementsIngestion",
            function_name="measurements-ingestion",
            source_file="lambdas/measurements_ingestion_lambda.py",
            handler="measurements_ingestion_lambda.lambda_handler",
            timeout_seconds=60,
            shared_layer=shared_utils_layer,
            custom_policies=rp.measurements_ingestion(), **shared)

        cdk.CfnOutput(self, "WhoopFnArn", value=whoop.function_arn, description="Whoop ingestion Lambda ARN")
        cdk.CfnOutput(self, "HaeWebhookFnArn", value=hae.function_arn, description="Health Auto Export webhook Lambda ARN")
