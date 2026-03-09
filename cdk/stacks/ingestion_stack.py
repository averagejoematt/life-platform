"""
IngestionStack — All data ingestion Lambdas.

Covers 15 Lambdas:
  Scheduled (13):
    whoop-data-ingestion       cron(0 14 * * ? *)  + recovery refresh cron(30 17)
    garmin-data-ingestion      cron(0 14 * * ? *)
    notion-journal-ingestion   cron(0 14 * * ? *)
    withings-data-ingestion    cron(15 14 * * ? *)
    habitify-data-ingestion    cron(15 14 * * ? *)
    strava-data-ingestion      cron(30 14 * * ? *)
    journal-enrichment         cron(30 14 * * ? *)
    todoist-data-ingestion     cron(45 14 * * ? *)
    eightsleep-data-ingestion  cron(0 15 * * ? *)
    activity-enrichment        cron(30 15 * * ? *)
    macrofactor-data-ingestion cron(0 16 * * ? *)  + S3 trigger
    weather-data-ingestion     cron(45 13 * * ? *)
    dropbox-poll               rate(30 minutes)

  S3-triggered (1):
    apple-health-ingestion     S3 ObjectCreated on imports/apple_health/*.xml

  API Gateway-triggered (1):
    health-auto-export-webhook API Gateway POST /ingest (no DLQ — request/response)

Import procedure (run once, after reviewing cdk synth output):
  cdk import LifePlatformIngestion

  CDK will prompt for physical resource IDs for each Lambda and IAM role.
  Get them with:
    aws lambda list-functions --query 'Functions[].FunctionName' | grep ingestion
    aws iam list-roles --query 'Roles[?starts_with(RoleName, `lambda-`)].RoleName'

⚠️  Notes on resources NOT fully managed by this stack:
  - API Gateway (health-auto-export-webhook): modeled as a reference only.
    The existing API Gateway (a76xwxt2wa) is not imported here — it would
    require a separate RestStack or manual management.
  - S3 event notifications (macrofactor, apple-health): modeled via
    aws_s3_notifications but the existing bucket notifications must be
    removed and re-added as part of cdk import. Handle carefully.
  - Garmin Lambda Layer (garth): the garth OAuth library is pre-installed
    in an existing Lambda Layer. This stack references it by ARN.
    Update GARTH_LAYER_ARN below with the actual ARN before importing.
"""

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_lambda_event_sources as lambda_events,
    aws_iam as iam,
    aws_events as events,
    aws_events_targets as targets,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_dynamodb as dynamodb,
    aws_sqs as sqs,
    aws_sns as sns,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
)
from constructs import Construct

from stacks.lambda_helpers import create_platform_lambda

# ── Lambda Layer ARNs ────────────────────────────────────────────────────────
SHARED_LAYER_ARN = "arn:aws:lambda:us-west-2:205930651321:layer:life-platform-shared-utils:4"

# Garth OAuth library layer — required by garmin-data-ingestion only.
# Retrieve the current ARN before importing:
#   aws lambda list-layers --query 'Layers[?contains(LayerName, `garth`)].LatestMatchingVersion.LayerVersionArn' --output text
# Then update this constant and run `cdk synth LifePlatformIngestion` to verify.
GARTH_LAYER_ARN = "arn:aws:lambda:us-west-2:205930651321:layer:garth:1"  # UPDATE BEFORE IMPORT

# ── Existing IAM Role ARNs ────────────────────────────────────────────────
# Existing roles referenced by ARN (immutable) — CDK does not manage them.
# No DefaultPolicy generated, no DependsOn on Lambda, no import friction.
ACCT = "205930651321"
REGION = "us-west-2"
def _role(name): return f"arn:aws:iam::{ACCT}:role/{name}"

# All core resources referenced by ARN/name to avoid cross-stack CloudFormation
# export dependencies. CoreStack is not yet in CloudFormation, so its
# Fn::ImportValue exports don't exist. Using from_* produces plain ARN strings.
INGESTION_DLQ_ARN  = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
LIFE_PLATFORM_TABLE = "life-platform"
LIFE_PLATFORM_BUCKET = "matthew-life-platform"
# Fill in ALERTS_TOPIC_ARN before importing — run:
#   aws sns list-topics --query 'Topics[*].TopicArn' --output text | tr '\t' '\n' | grep life-platform
ALERTS_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"  # update if name differs

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

        # ── Shared utils layer reference (existing layer, not created here) ──
        shared_utils_layer = _lambda.LayerVersion.from_layer_version_arn(
            self, "SharedUtilsLayer", SHARED_LAYER_ARN
        )

        # Reference all core resources by ARN/name to avoid Fn::ImportValue.
        # CoreStack exports don't exist until CoreStack is imported into CFn.
        local_dlq = sqs.Queue.from_queue_arn(
            self, "IngestionDLQ", INGESTION_DLQ_ARN
        )
        local_table = dynamodb.Table.from_table_name(
            self, "LifePlatformTable", LIFE_PLATFORM_TABLE
        )
        local_bucket = s3.Bucket.from_bucket_name(
            self, "LifePlatformBucket", LIFE_PLATFORM_BUCKET
        )
        local_alerts_topic = sns.Topic.from_topic_arn(
            self, "AlertsTopic", ALERTS_TOPIC_ARN
        )

        # ── Shared kwargs passed to every ingestion Lambda ──
        shared = dict(
            table=local_table,
            bucket=local_bucket,
            dlq=local_dlq,
            alerts_topic=local_alerts_topic,
        )

        # ══════════════════════════════════════════════════════════════
        # 1. Whoop
        # Two EventBridge rules: daily ingestion + recovery refresh
        # ══════════════════════════════════════════════════════════════
        whoop = create_platform_lambda(
            self, "WhoopIngestion",
            function_name="whoop-data-ingestion",
            source_file="lambdas/whoop_lambda.py",
            handler="whoop_lambda.lambda_handler",
            secrets=["life-platform/whoop"],
            schedule="cron(0 14 * * ? *)",
            timeout_seconds=300,
            existing_role_arn=ROLE_ARNS["whoop"],
            **shared,
        )

        # Second EventBridge rule: Whoop recovery refresh at 10:30 AM PT
        recovery_rule = events.Rule(
            self, "WhoopRecoveryRefreshRule",
            # No rule_name — actual AWS name is whoop-recovery-refresh
            schedule=events.Schedule.expression("cron(30 17 * * ? *)"),
        )
        recovery_rule.add_target(targets.LambdaFunction(whoop))

        # ══════════════════════════════════════════════════════════════
        # 2. Garmin
        # Requires garth layer for OAuth token management
        # ══════════════════════════════════════════════════════════════
        garth_layer = _lambda.LayerVersion.from_layer_version_arn(
            self, "GarthLayer", GARTH_LAYER_ARN
        )

        create_platform_lambda(
            self, "GarminIngestion",
            function_name="garmin-data-ingestion",
            source_file="lambdas/garmin_lambda.py",
            handler="garmin_lambda.lambda_handler",
            secrets=["life-platform/garmin"],
            schedule="cron(0 14 * * ? *)",
            timeout_seconds=300,
            memory_mb=512,
            shared_layer=shared_utils_layer,
            additional_layers=[garth_layer],
            existing_role_arn=ROLE_ARNS["garmin"],
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # 3. Notion Journal
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "NotionIngestion",
            function_name="notion-journal-ingestion",
            source_file="lambdas/notion_lambda.py",
            handler="notion_lambda.lambda_handler",
            secrets=["life-platform/notion"],
            schedule="cron(0 14 * * ? *)",
            timeout_seconds=120,
            existing_role_arn=ROLE_ARNS["notion"],
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # 4. Withings
        # OAuth with token refresh (needs UpdateSecret)
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "WithingsIngestion",
            function_name="withings-data-ingestion",
            source_file="lambdas/withings_lambda.py",
            handler="withings_lambda.lambda_handler",
            secrets=["life-platform/withings"],
            schedule="cron(15 14 * * ? *)",
            timeout_seconds=120,
            existing_role_arn=ROLE_ARNS["withings"],
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # 5. Habitify
        # Static API key — stored in api-keys bundle (not dedicated secret)
        # Also writes to S3 uploads/macrofactor/ as part of supplement bridge
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "HabitifyIngestion",
            function_name="habitify-data-ingestion",
            source_file="lambdas/habitify_lambda.py",
            handler="habitify_lambda.lambda_handler",
            secrets=["life-platform/api-keys"],
            schedule="cron(15 14 * * ? *)",
            timeout_seconds=180,
            existing_role_arn=ROLE_ARNS["habitify"],
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # 6. Strava
        # OAuth with token refresh (needs UpdateSecret)
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "StravaIngestion",
            function_name="strava-data-ingestion",
            source_file="lambdas/strava_lambda.py",
            handler="strava_lambda.lambda_handler",
            secrets=["life-platform/strava"],
            schedule="cron(30 14 * * ? *)",
            timeout_seconds=300,
            existing_role_arn=ROLE_ARNS["strava"],
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # 7. Journal Enrichment
        # Haiku AI call — needs ai-keys secret
        # Runs after notion ingestion (07:30 AM PT)
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "JournalEnrichment",
            function_name="journal-enrichment",
            source_file="lambdas/journal_enrichment_lambda.py",
            handler="journal_enrichment_lambda.lambda_handler",
            secrets=["life-platform/ai-keys"],
            schedule="cron(30 14 * * ? *)",
            timeout_seconds=300,
            existing_role_arn=ROLE_ARNS["journal"],
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # 8. Todoist
        # Static API key in dedicated secret
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "TodoistIngestion",
            function_name="todoist-data-ingestion",
            source_file="lambdas/todoist_lambda.py",
            handler="todoist_lambda.lambda_handler",
            secrets=["life-platform/todoist"],
            schedule="cron(45 14 * * ? *)",
            timeout_seconds=120,
            existing_role_arn=ROLE_ARNS["todoist"],
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # 9. Eight Sleep
        # Username/password JWT (no OAuth, no UpdateSecret needed)
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "EightsleepIngestion",
            function_name="eightsleep-data-ingestion",
            source_file="lambdas/eightsleep_lambda.py",
            handler="eightsleep_lambda.lambda_handler",
            secrets=["life-platform/eightsleep"],
            schedule="cron(0 15 * * ? *)",
            timeout_seconds=120,
            existing_role_arn=ROLE_ARNS["eightsleep"],
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # 10. Activity Enrichment
        # Haiku AI call — needs ai-keys secret
        # Runs after strava ingestion (08:30 AM PT)
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "ActivityEnrichment",
            function_name="activity-enrichment",
            source_file="lambdas/enrichment_lambda.py",
            handler="enrichment_lambda.lambda_handler",
            secrets=["life-platform/ai-keys"],
            schedule="cron(30 15 * * ? *)",
            timeout_seconds=300,
            existing_role_arn=ROLE_ARNS["activity"],
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # 11. MacroFactor
        # Two triggers: EventBridge schedule + S3 ObjectCreated
        # S3 trigger: uploads/macrofactor/*.csv (dropped by dropbox-poll)
        # ══════════════════════════════════════════════════════════════
        macrofactor = create_platform_lambda(
            self, "MacrofactorIngestion",
            function_name="macrofactor-data-ingestion",
            source_file="lambdas/macrofactor_lambda.py",
            handler="macrofactor_lambda.lambda_handler",
            schedule="cron(0 16 * * ? *)",
            timeout_seconds=300,
            existing_role_arn=ROLE_ARNS["macrofactor"],
            **shared,
        )
        # S3 trigger (uploads/macrofactor/*.csv) is managed outside CDK.
        # Cross-stack S3 notifications create cyclic dependencies in CDK.
        # The notification already exists in AWS and is preserved as-is.
        # To grant API Gateway / S3 permission to invoke this Lambda:
        macrofactor.add_permission(
            "S3InvokeMacrofactor",
            principal=iam.ServicePrincipal("s3.amazonaws.com"),
            source_arn=f"arn:aws:s3:::matthew-life-platform",
        )

        # ══════════════════════════════════════════════════════════════
        # 12. Weather
        # Open-Meteo API — no auth required, no secrets
        # Uses weather_handler.py (SIMP-2 migration from weather_lambda.py)
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "WeatherIngestion",
            function_name="weather-data-ingestion",
            source_file="lambdas/weather_handler.py",
            handler="weather_handler.lambda_handler",
            schedule="cron(45 13 * * ? *)",
            timeout_seconds=60,
            s3_write=False,
            existing_role_arn=ROLE_ARNS["weather"],
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # 13. Dropbox Poll
        # Polls Dropbox every 30 min for new MacroFactor CSVs
        # Uploads to S3 → triggers macrofactor Lambda via S3 event
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "DropboxPoll",
            function_name="dropbox-poll",
            source_file="lambdas/dropbox_poll_lambda.py",
            handler="dropbox_poll_lambda.lambda_handler",
            secrets=["life-platform/dropbox"],
            schedule="rate(30 minutes)",
            timeout_seconds=120,
            existing_role_arn=ROLE_ARNS["dropbox"],
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # 14. Apple Health Ingestion
        # S3-triggered only — no EventBridge schedule
        # Trigger: imports/apple_health/*.xml (or .xml.gz)
        # Moves processed file to imports/apple_health/processed/
        # ══════════════════════════════════════════════════════════════
        apple_health = create_platform_lambda(
            self, "AppleHealthIngestion",
            function_name="apple-health-ingestion",
            source_file="lambdas/apple_health_lambda.py",
            handler="apple_health_lambda.lambda_handler",
            timeout_seconds=300,
            memory_mb=512,
            existing_role_arn=ROLE_ARNS["apple_health"],
            **shared,
        )
        # S3 trigger (imports/apple_health/) is managed outside CDK.
        # Same cyclic dependency reason as macrofactor above.
        apple_health.add_permission(
            "S3InvokeAppleHealth",
            principal=iam.ServicePrincipal("s3.amazonaws.com"),
            source_arn=f"arn:aws:s3:::matthew-life-platform",
        )

        # ══════════════════════════════════════════════════════════════
        # 15. Health Auto Export Webhook
        # API Gateway POST /ingest → Lambda
        # Request/response pattern — NO DLQ (synchronous invocation)
        # The API Gateway resource (a76xwxt2wa) is NOT managed by CDK here.
        # It would require a dedicated RestStack or importing the API GW.
        # For now: Lambda is managed by CDK; API GW trigger is external reference.
        # ══════════════════════════════════════════════════════════════
        # HAE role referenced by ARN — same pattern as other ingestion roles.
        hae_role = iam.Role.from_role_arn(
            self, "HaeWebhookRole", ROLE_ARNS["hae"]
        )

        _ASSET_EXCLUDES = [
            ".venv", ".venv/**", "cdk", "cdk/**", "cdk.out", "cdk.out/**",
            "docs", "docs/**", "deploy", "deploy/**", "handovers", "handovers/**",
            "backfill", "backfill/**", "patches", "patches/**", "seeds", "seeds/**",
            "setup", "setup/**", "datadrops", "datadrops/**",
            "__pycache__", "**/__pycache__/**", "*.pyc", "**/*.pyc",
            "*.md", ".git", ".git/**", "node_modules", "node_modules/**",
        ]
        hae = _lambda.Function(
            self, "HaeWebhook",
            function_name="health-auto-export-webhook",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="health_auto_export_lambda.lambda_handler",
            code=_lambda.Code.from_asset("..", exclude=_ASSET_EXCLUDES),
            role=hae_role,
            timeout=Duration.seconds(30),            # API GW max timeout is 29s
            memory_size=256,
            environment={
                "TABLE_NAME": local_table.table_name,
                "S3_BUCKET": local_bucket.bucket_name,
                "USER_ID": self.node.try_get_context("user_id") or "matthew",
            },
            # NO dead_letter_queue — request/response pattern
        )

        # Allow API Gateway to invoke this Lambda
        hae.add_permission(
            "ApiGatewayInvoke",
            principal=iam.ServicePrincipal("apigateway.amazonaws.com"),
            source_arn=f"arn:aws:execute-api:{self.region}:{self.account}:a76xwxt2wa/*/*/ingest",
        )

        # ══════════════════════════════════════════════════════════════
        # CloudWatch error alarm for HAE webhook (not via helper)
        # ══════════════════════════════════════════════════════════════
        hae_alarm = hae.metric_errors(
            period=Duration.hours(1),
            statistic="Sum",
        ).create_alarm(
            self, "HaeWebhookErrorAlarm",
            alarm_name="ingestion-error-health-auto-export-webhook",
            evaluation_periods=1,
            threshold=3,                             # tolerate 1-2 transient errors
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        hae_alarm.add_alarm_action(cw_actions.SnsAction(local_alerts_topic))
        hae_alarm.add_ok_action(cw_actions.SnsAction(local_alerts_topic))

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
