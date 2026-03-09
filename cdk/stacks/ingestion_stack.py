"""
IngestionStack — All data ingestion Lambdas.

Covers 15 Lambdas:
  Scheduled (13):
    whoop-data-ingestion       whoop-daily-ingestion + whoop-recovery-refresh
    garmin-data-ingestion      garmin-daily-ingestion
    notion-journal-ingestion   notion-daily-ingest
    withings-data-ingestion    withings-daily-ingestion
    habitify-data-ingestion    habitify-daily-ingest
    strava-data-ingestion      strava-daily-ingestion
    journal-enrichment         journal-enrichment-daily
    todoist-data-ingestion     todoist-daily-ingestion
    eightsleep-data-ingestion  eightsleep-daily-ingestion
    activity-enrichment        activity-enrichment-nightly
    macrofactor-data-ingestion macrofactor-daily-ingestion + S3 trigger
    weather-data-ingestion     weather-daily-ingestion
    dropbox-poll               dropbox-poll-schedule (rate 30 min)

  S3-triggered (1):
    apple-health-ingestion     S3 ObjectCreated on imports/apple_health/*.xml

  API Gateway-triggered (1):
    health-auto-export-webhook API Gateway POST /ingest

EventBridge rules are NOT managed by CDK — they already exist in AWS and
updating them via CloudFormation fails with "Internal Failure" (known CFN/EB
bug on imported rules). Rules are managed as unmanaged drift.

CDK manages ONLY:
  - Lambda functions (code, config, env vars)
  - CloudWatch error alarms
  - Lambda::Permission resources (allow EB/S3/APIGW to invoke)

Lambda::Permissions are added via fn.add_permission() with hardcoded rule ARNs,
not via events.Rule.add_target() — this avoids creating/updating EventBridge rules.
"""

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_sqs as sqs,
    aws_sns as sns,
)
from constructs import Construct

from stacks.lambda_helpers import create_platform_lambda

# ── Lambda Layer ARNs ────────────────────────────────────────────────────────
SHARED_LAYER_ARN = "arn:aws:lambda:us-west-2:205930651321:layer:life-platform-shared-utils:4"

ACCT = "205930651321"
REGION = "us-west-2"
def _role(name): return f"arn:aws:iam::{ACCT}:role/{name}"
def _rule_arn(name): return f"arn:aws:events:{REGION}:{ACCT}:rule/{name}"

INGESTION_DLQ_ARN  = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
LIFE_PLATFORM_TABLE = "life-platform"
LIFE_PLATFORM_BUCKET = "matthew-life-platform"
ALERTS_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"

ROLE_ARNS = {
    "whoop":        _role("lambda-whoop-role"),
    "garmin":       _role("lambda-garmin-ingestion-role"),
    "notion":       _role("lambda-notion-ingestion-role"),
    "withings":     _role("lambda-withings-role"),
    "habitify":     _role("lambda-habitify-ingestion-role"),
    "strava":       _role("lambda-strava-role"),
    "journal":      _role("lambda-journal-enrichment-role"),
    "todoist":      _role("lambda-todoist-role"),
    "eightsleep":   _role("lambda-eightsleep-role"),
    "activity":     _role("lambda-enrichment-role"),
    "macrofactor":  _role("lambda-macrofactor-role"),
    "weather":      _role("lambda-weather-role"),
    "dropbox":      _role("lambda-dropbox-poll-role"),
    "apple_health": _role("lambda-apple-health-role"),
    "hae":          _role("lambda-health-auto-export-role"),
}

# EventBridge rule names (verified 2026-03-09 via aws events list-rules)
RULE_NAMES = {
    "whoop_daily":        "whoop-daily-ingestion",
    "whoop_recovery":     "whoop-recovery-refresh",
    "garmin":             "garmin-daily-ingestion",
    "notion":             "notion-daily-ingest",
    "withings":           "withings-daily-ingestion",
    "habitify":           "habitify-daily-ingest",
    "strava":             "strava-daily-ingestion",
    "journal":            "journal-enrichment-daily",
    "todoist":            "todoist-daily-ingestion",
    "eightsleep":         "eightsleep-daily-ingestion",
    "activity":           "activity-enrichment-nightly",
    "macrofactor_daily":  "macrofactor-daily-ingestion",
    "weather":            "weather-daily-ingestion",
    "dropbox":            "dropbox-poll-schedule",
}


class IngestionStack(Stack):

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        table: dynamodb.ITable,
        bucket: s3.IBucket,
        dlq: sqs.IQueue,
        alerts_topic: sns.ITopic,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        shared_utils_layer = _lambda.LayerVersion.from_layer_version_arn(
            self, "SharedUtilsLayer", SHARED_LAYER_ARN
        )

        local_dlq          = sqs.Queue.from_queue_arn(self, "IngestionDLQ", INGESTION_DLQ_ARN)
        local_table        = dynamodb.Table.from_table_name(self, "LifePlatformTable", LIFE_PLATFORM_TABLE)
        local_bucket       = s3.Bucket.from_bucket_name(self, "LifePlatformBucket", LIFE_PLATFORM_BUCKET)
        local_alerts_topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)

        eb_principal = iam.ServicePrincipal("events.amazonaws.com")

        shared = dict(
            table=local_table,
            bucket=local_bucket,
            dlq=local_dlq,
            alerts_topic=local_alerts_topic,
        )

        # ══════════════════════════════════════════════════════════════
        # 1. Whoop — two EventBridge rules
        # ══════════════════════════════════════════════════════════════
        whoop = create_platform_lambda(
            self, "WhoopIngestion",
            function_name="whoop-data-ingestion",
            source_file="lambdas/whoop_lambda.py",
            handler="lambda_function.lambda_handler",  # AWS actual
            secrets=["life-platform/whoop"],
            timeout_seconds=300,
            alarm_name="ingestion-error-whoop",
            existing_role_arn=ROLE_ARNS["whoop"],
            **shared,
        )
        whoop.add_permission("EBWhoopDaily",
            principal=eb_principal,
            source_arn=_rule_arn(RULE_NAMES["whoop_daily"]),
        )
        whoop.add_permission("EBWhoopRecovery",
            principal=eb_principal,
            source_arn=_rule_arn(RULE_NAMES["whoop_recovery"]),
        )

        # ══════════════════════════════════════════════════════════════
        # 2. Garmin
        # ══════════════════════════════════════════════════════════════
        garmin = create_platform_lambda(
            self, "GarminIngestion",
            function_name="garmin-data-ingestion",
            source_file="lambdas/garmin_lambda.py",
            handler="garmin_lambda.lambda_handler",
            secrets=["life-platform/garmin"],
            timeout_seconds=300,
            memory_mb=512,
            shared_layer=shared_utils_layer,
            existing_role_arn=ROLE_ARNS["garmin"],
            alerts_topic=None,
            **{k: v for k, v in shared.items() if k != "alerts_topic"},
        )
        garmin.add_permission("EBGarmin",
            principal=eb_principal,
            source_arn=_rule_arn(RULE_NAMES["garmin"]),
        )

        # ══════════════════════════════════════════════════════════════
        # 3. Notion Journal
        # ══════════════════════════════════════════════════════════════
        notion = create_platform_lambda(
            self, "NotionIngestion",
            function_name="notion-journal-ingestion",
            source_file="lambdas/notion_lambda.py",
            handler="notion_lambda.lambda_handler",
            secrets=["life-platform/notion"],
            timeout_seconds=120,
            existing_role_arn=ROLE_ARNS["notion"],
            alerts_topic=None,
            **{k: v for k, v in shared.items() if k != "alerts_topic"},
        )
        notion.add_permission("EBNotion",
            principal=eb_principal,
            source_arn=_rule_arn(RULE_NAMES["notion"]),
        )

        # ══════════════════════════════════════════════════════════════
        # 4. Withings
        # ══════════════════════════════════════════════════════════════
        withings = create_platform_lambda(
            self, "WithingsIngestion",
            function_name="withings-data-ingestion",
            source_file="lambdas/withings_lambda.py",
            handler="lambda_function.lambda_handler",  # AWS actual
            secrets=["life-platform/withings"],
            timeout_seconds=120,
            alarm_name="ingestion-error-withings",
            existing_role_arn=ROLE_ARNS["withings"],
            **shared,
        )
        withings.add_permission("EBWithings",
            principal=eb_principal,
            source_arn=_rule_arn(RULE_NAMES["withings"]),
        )

        # ══════════════════════════════════════════════════════════════
        # 5. Habitify
        # ══════════════════════════════════════════════════════════════
        habitify = create_platform_lambda(
            self, "HabitifyIngestion",
            function_name="habitify-data-ingestion",
            source_file="lambdas/habitify_lambda.py",
            handler="lambda_function.lambda_handler",  # AWS actual
            secrets=["life-platform/api-keys"],
            timeout_seconds=180,
            existing_role_arn=ROLE_ARNS["habitify"],
            alerts_topic=None,
            **{k: v for k, v in shared.items() if k != "alerts_topic"},
        )
        habitify.add_permission("EBHabitify",
            principal=eb_principal,
            source_arn=_rule_arn(RULE_NAMES["habitify"]),
        )

        # ══════════════════════════════════════════════════════════════
        # 6. Strava
        # ══════════════════════════════════════════════════════════════
        strava = create_platform_lambda(
            self, "StravaIngestion",
            function_name="strava-data-ingestion",
            source_file="lambdas/strava_lambda.py",
            handler="lambda_function.lambda_handler",  # AWS actual
            secrets=["life-platform/strava"],
            timeout_seconds=300,
            alarm_name="ingestion-error-strava",
            existing_role_arn=ROLE_ARNS["strava"],
            **shared,
        )
        strava.add_permission("EBStrava",
            principal=eb_principal,
            source_arn=_rule_arn(RULE_NAMES["strava"]),
        )

        # ══════════════════════════════════════════════════════════════
        # 7. Journal Enrichment
        # ══════════════════════════════════════════════════════════════
        journal = create_platform_lambda(
            self, "JournalEnrichment",
            function_name="journal-enrichment",
            source_file="lambdas/journal_enrichment_lambda.py",
            handler="journal_enrichment_lambda.lambda_handler",
            secrets=["life-platform/ai-keys"],
            timeout_seconds=300,
            existing_role_arn=ROLE_ARNS["journal"],
            alerts_topic=None,
            **{k: v for k, v in shared.items() if k != "alerts_topic"},
        )
        journal.add_permission("EBJournal",
            principal=eb_principal,
            source_arn=_rule_arn(RULE_NAMES["journal"]),
        )

        # ══════════════════════════════════════════════════════════════
        # 8. Todoist
        # ══════════════════════════════════════════════════════════════
        todoist = create_platform_lambda(
            self, "TodoistIngestion",
            function_name="todoist-data-ingestion",
            source_file="lambdas/todoist_lambda.py",
            handler="lambda_function.lambda_handler",  # AWS actual
            secrets=["life-platform/todoist"],
            timeout_seconds=120,
            alarm_name="ingestion-error-todoist",
            existing_role_arn=ROLE_ARNS["todoist"],
            **shared,
        )
        todoist.add_permission("EBTodoist",
            principal=eb_principal,
            source_arn=_rule_arn(RULE_NAMES["todoist"]),
        )

        # ══════════════════════════════════════════════════════════════
        # 9. Eight Sleep
        # ══════════════════════════════════════════════════════════════
        eightsleep = create_platform_lambda(
            self, "EightsleepIngestion",
            function_name="eightsleep-data-ingestion",
            source_file="lambdas/eightsleep_lambda.py",
            handler="lambda_function.lambda_handler",  # AWS actual
            secrets=["life-platform/eightsleep"],
            timeout_seconds=120,
            alarm_name="ingestion-error-eightsleep",
            existing_role_arn=ROLE_ARNS["eightsleep"],
            **shared,
        )
        eightsleep.add_permission("EBEightsleep",
            principal=eb_principal,
            source_arn=_rule_arn(RULE_NAMES["eightsleep"]),
        )

        # ══════════════════════════════════════════════════════════════
        # 10. Activity Enrichment
        # ══════════════════════════════════════════════════════════════
        activity = create_platform_lambda(
            self, "ActivityEnrichment",
            function_name="activity-enrichment",
            source_file="lambdas/enrichment_lambda.py",
            handler="enrichment_lambda.lambda_handler",
            secrets=["life-platform/ai-keys"],
            timeout_seconds=300,
            alarm_name="ingestion-error-enrichment",
            existing_role_arn=ROLE_ARNS["activity"],
            **shared,
        )
        activity.add_permission("EBActivity",
            principal=eb_principal,
            source_arn=_rule_arn(RULE_NAMES["activity"]),
        )

        # ══════════════════════════════════════════════════════════════
        # 11. MacroFactor — EventBridge + S3 trigger
        # ══════════════════════════════════════════════════════════════
        macrofactor = create_platform_lambda(
            self, "MacrofactorIngestion",
            function_name="macrofactor-data-ingestion",
            source_file="lambdas/macrofactor_lambda.py",
            handler="macrofactor_lambda.lambda_handler",
            timeout_seconds=300,
            alarm_name="ingestion-error-macrofactor",
            existing_role_arn=ROLE_ARNS["macrofactor"],
            **shared,
        )
        macrofactor.add_permission("EBMacrofactor",
            principal=eb_principal,
            source_arn=_rule_arn(RULE_NAMES["macrofactor_daily"]),
        )
        macrofactor.add_permission("S3InvokeMacrofactor",
            principal=iam.ServicePrincipal("s3.amazonaws.com"),
            source_arn=f"arn:aws:s3:::matthew-life-platform",
        )

        # ══════════════════════════════════════════════════════════════
        # 12. Weather
        # ══════════════════════════════════════════════════════════════
        weather = create_platform_lambda(
            self, "WeatherIngestion",
            function_name="weather-data-ingestion",
            source_file="lambdas/weather_handler.py",
            handler="weather_handler.lambda_handler",
            timeout_seconds=60,
            s3_write=False,
            existing_role_arn=ROLE_ARNS["weather"],
            alerts_topic=None,
            **{k: v for k, v in shared.items() if k != "alerts_topic"},
        )
        weather.add_permission("EBWeather",
            principal=eb_principal,
            source_arn=_rule_arn(RULE_NAMES["weather"]),
        )

        # ══════════════════════════════════════════════════════════════
        # 13. Dropbox Poll
        # ══════════════════════════════════════════════════════════════
        dropbox = create_platform_lambda(
            self, "DropboxPoll",
            function_name="dropbox-poll",
            source_file="lambdas/dropbox_poll_lambda.py",
            handler="dropbox_poll_lambda.lambda_handler",
            secrets=["life-platform/dropbox"],
            timeout_seconds=120,
            existing_role_arn=ROLE_ARNS["dropbox"],
            alerts_topic=None,
            **{k: v for k, v in shared.items() if k != "alerts_topic"},
        )
        dropbox.add_permission("EBDropbox",
            principal=eb_principal,
            source_arn=_rule_arn(RULE_NAMES["dropbox"]),
        )

        # ══════════════════════════════════════════════════════════════
        # 14. Apple Health Ingestion — S3 trigger only
        # ══════════════════════════════════════════════════════════════
        apple_health = create_platform_lambda(
            self, "AppleHealthIngestion",
            function_name="apple-health-ingestion",
            source_file="lambdas/apple_health_lambda.py",
            handler="lambda_function.lambda_handler",  # AWS actual
            timeout_seconds=300,
            memory_mb=512,
            alarm_name="ingestion-error-apple-health",
            existing_role_arn=ROLE_ARNS["apple_health"],
            **shared,
        )
        apple_health.add_permission("S3InvokeAppleHealth",
            principal=iam.ServicePrincipal("s3.amazonaws.com"),
            source_arn=f"arn:aws:s3:::matthew-life-platform",
        )

        # ══════════════════════════════════════════════════════════════
        # 15. Health Auto Export Webhook — API Gateway trigger
        # ══════════════════════════════════════════════════════════════
        hae_role = iam.Role.from_role_arn(self, "HaeWebhookRole", ROLE_ARNS["hae"])

        _ASSET_EXCLUDES = [
            "__pycache__", "**/__pycache__/**", "*.pyc", "**/*.pyc",
            "*.md", ".DS_Store",
            "dashboard", "dashboard/**", "buddy", "buddy/**",
            "cf-auth", "cf-auth/**", "requirements", "requirements/**",
        ]
        hae = _lambda.Function(
            self, "HaeWebhook",
            function_name="health-auto-export-webhook",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="health_auto_export_lambda.lambda_handler",
            code=_lambda.Code.from_asset("../lambdas", exclude=_ASSET_EXCLUDES),
            role=hae_role,
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                "TABLE_NAME": local_table.table_name,
                "S3_BUCKET": local_bucket.bucket_name,
                "USER_ID": self.node.try_get_context("user_id") or "matthew",
            },
        )
        hae.add_permission("ApiGatewayInvoke",
            principal=iam.ServicePrincipal("apigateway.amazonaws.com"),
            source_arn=f"arn:aws:execute-api:{self.region}:{self.account}:a76xwxt2wa/*/*/ingest",
        )

        # ══════════════════════════════════════════════════════════════
        # Outputs
        # ══════════════════════════════════════════════════════════════
        cdk.CfnOutput(self, "WhoopFnArn",
            value=whoop.function_arn,
            description="Whoop ingestion Lambda ARN",
        )
        cdk.CfnOutput(self, "HaeWebhookFnArn",
            value=hae.function_arn,
            description="Health Auto Export webhook Lambda ARN",
        )
