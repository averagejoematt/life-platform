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

# ── Shared utils Lambda Layer ARN ───────────────────────────────────────────
# life-platform-shared-utils:4 — contains shared dependencies used across
# multiple Lambdas. Garth (Garmin OAuth) is bundled in the Lambda zip directly
# rather than as a separate layer.
SHARED_LAYER_ARN = "arn:aws:lambda:us-west-2:205930651321:layer:life-platform-shared-utils:4"


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

        # ── Shared kwargs passed to every ingestion Lambda ──
        shared = dict(
            table=table,
            bucket=bucket,
            dlq=dlq,
            alerts_topic=alerts_topic,
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
            schedule="cron(0 14 * * ? *)",           # 07:00 AM PT
            timeout_seconds=300,
            **shared,
        )

        # Second EventBridge rule: Whoop recovery refresh at 10:30 AM PT
        recovery_rule = events.Rule(
            self, "WhoopRecoveryRefreshRule",
            rule_name="whoop-recovery-refresh",
            schedule=events.Schedule.expression("cron(30 17 * * ? *)"),
        )
        recovery_rule.add_target(targets.LambdaFunction(whoop))

        # ══════════════════════════════════════════════════════════════
        # 2. Garmin
        # Requires garth layer for OAuth token management
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "GarminIngestion",
            function_name="garmin-data-ingestion",
            source_file="lambdas/garmin_lambda.py",
            handler="garmin_lambda.lambda_handler",
            secrets=["life-platform/garmin"],
            schedule="cron(0 14 * * ? *)",           # 07:00 AM PT
            timeout_seconds=300,
            memory_mb=512,                           # garth auth + multi-day backfill
            shared_layer=shared_utils_layer,
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
            schedule="cron(0 14 * * ? *)",           # 07:00 AM PT
            timeout_seconds=120,
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
            schedule="cron(15 14 * * ? *)",          # 07:15 AM PT
            timeout_seconds=120,
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
            schedule="cron(15 14 * * ? *)",          # 07:15 AM PT
            timeout_seconds=180,
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
            schedule="cron(30 14 * * ? *)",          # 07:30 AM PT
            timeout_seconds=300,
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
            schedule="cron(30 14 * * ? *)",          # 07:30 AM PT
            timeout_seconds=300,
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
            schedule="cron(45 14 * * ? *)",          # 07:45 AM PT
            timeout_seconds=120,
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
            schedule="cron(0 15 * * ? *)",           # 08:00 AM PT
            timeout_seconds=120,
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
            schedule="cron(30 15 * * ? *)",          # 08:30 AM PT
            timeout_seconds=300,
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
            schedule="cron(0 16 * * ? *)",           # 09:00 AM PT
            timeout_seconds=300,
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
            schedule="cron(45 13 * * ? *)",          # 06:45 AM PT
            timeout_seconds=60,
            s3_write=False,                          # weather writes to DDB only
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
            memory_mb=512,                           # XML parsing for large exports
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
        hae_role = iam.Role(
            self, "HaeWebhookRole",
            role_name="lambda-health-auto-export-webhook-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
        )
        hae_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
                "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan",
                "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem",
            ],
            resources=[table.table_arn, f"{table.table_arn}/index/*"],
        ))
        hae_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
            resources=[bucket.bucket_arn, f"{bucket.bucket_arn}/*"],
        ))
        hae_role.add_to_policy(iam.PolicyStatement(
            actions=["secretsmanager:GetSecretValue"],
            resources=[
                f"arn:aws:secretsmanager:*:*:secret:life-platform/api-keys-*",
            ],
        ))

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
                "TABLE_NAME": table.table_name,
                "S3_BUCKET": bucket.bucket_name,
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
        hae_alarm.add_alarm_action(cw_actions.SnsAction(alerts_topic))
        hae_alarm.add_ok_action(cw_actions.SnsAction(alerts_topic))

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
