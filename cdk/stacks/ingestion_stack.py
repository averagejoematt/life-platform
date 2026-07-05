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
    Duration,
    Stack,
    aws_apigatewayv2 as apigwv2,
    aws_dynamodb as dynamodb,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_logs as logs,
    aws_s3 as s3,
    aws_sns as sns,
    aws_sqs as sqs,
)
from aws_cdk.aws_apigatewayv2_integrations import HttpLambdaIntegration

from stacks import role_policies as rp
from stacks.constants import ACCT, GARTH_LAYER_ARN, REGION, S3_BUCKET, SHARED_LAYER_ARN, TABLE_NAME  # CONF-01
from stacks.lambda_helpers import create_platform_lambda

# ── Hourly ingestion with 10pm-4am PST maintenance window ──
# Active hours: 4am-10pm PST = UTC 12-6 (next day) = 0,1,2,3,4,5,12,13,14,15,16,17,18,19,20,21,22,23
# Skipped: UTC 6,7,8,9,10,11 = 10pm-4am PST (maintenance window — no user activity expected)
# Cost: ~$0/month — gap-aware Lambdas short-circuit in <50ms when no new data exists
INGEST_HOURLY = "0,1,2,3,4,5,12,13,14,15,16,17,18,19,20,21,22,23"

INGESTION_DLQ_ARN = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
LIFE_PLATFORM_TABLE = TABLE_NAME
LIFE_PLATFORM_BUCKET = S3_BUCKET
ALERTS_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"
DIGEST_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts-digest"


class IngestionStack(Stack):
    def __init__(self, scope, construct_id, table, bucket, dlq, alerts_topic, digest_topic=None, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        shared_utils_layer = _lambda.LayerVersion.from_layer_version_arn(self, "SharedUtilsLayer", SHARED_LAYER_ARN)
        garth_layer = _lambda.LayerVersion.from_layer_version_arn(self, "GarthLayer", GARTH_LAYER_ARN)
        local_dlq = sqs.Queue.from_queue_arn(self, "IngestionDLQ", INGESTION_DLQ_ARN)
        local_table = dynamodb.Table.from_table_name(self, "LifePlatformTable", LIFE_PLATFORM_TABLE)
        local_bucket = s3.Bucket.from_bucket_name(self, "LifePlatformBucket", LIFE_PLATFORM_BUCKET)
        local_alerts_topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)
        local_digest_topic = sns.Topic.from_topic_arn(self, "DigestTopic", DIGEST_TOPIC_ARN)
        # ADR-050: every ingestion-error-* alarm is routed to the digest topic.
        # Transient API hiccups and gap-aware backfill recover automatically; one
        # daily digest is the right pace for these.
        shared = dict(
            table=local_table,
            bucket=local_bucket,
            dlq=local_dlq,
            alerts_topic=local_alerts_topic,
            digest_topic=local_digest_topic,
            digest=True,
            # 2026-05-29: per-Lambda ingestion-error-* alarms consolidated into one
            # metric-math aggregate (LifePlatformMonitoring). Saves ~$4.60/mo.
            error_alarm=False,
        )

        # ── 1. Whoop — 5x daily ingestion + recovery refresh
        whoop = create_platform_lambda(
            self,
            "WhoopIngestion",
            function_name="whoop-data-ingestion",
            source_file="lambdas/ingestion/whoop_lambda.py",
            handler="ingestion.whoop_lambda.lambda_handler",
            schedule=f"cron(0 {INGEST_HOURLY} * * ? *)",
            timeout_seconds=300,
            alarm_name="ingestion-error-whoop",
            shared_layer=shared_utils_layer,
            # No async retry: Whoop rotates its refresh token on every refresh, so
            # a failed run is almost always a token-rotation race (HTTP 400). The
            # default 2 EventBridge retries just re-hit it with the same stale
            # token (the 19:00/19:01/19:03 clusters in the alarm digest); the next
            # hourly run recovers via gap-fill. Same fix as Garmin.
            retry_attempts=0,
            custom_policies=rp.ingestion_whoop(),
            **shared,
        )
        # Second schedule: recovery refresh at 9:30 AM PT
        # OAuth race prevention: max 1 concurrent invocation per OAuth Lambda (ADR-036 fix)
        # 2026-06-17: account concurrency quota raised to 100 by AWS Support
        # (case 177921309700709) — reserving 1 here is now safe (unreserved stays ≥ minimum).
        whoop.node.default_child.add_property_override("ReservedConcurrentExecutions", 1)

        whoop_recovery = events.Rule(
            self,
            "WhoopRecoverySchedule",
            schedule=events.Schedule.expression("cron(30 17 * * ? *)"),
            description="Whoop recovery refresh — 9:30 AM PT",
        )
        whoop_recovery.add_target(targets.LambdaFunction(whoop))

        # ── 2. Garmin — PAUSED, no schedule (#497/C-2, 2026-07-04). ADR-074
        # declares the pause (vendor anti-automation 429-blocks server-side
        # OAuth refresh), yet the cron kept firing 4×/day into the throttle —
        # ~73 consecutive failures, and per the code's own note each hit only
        # prolongs the lockout. Revive = manual re-auth (setup_garmin_browser_auth.py)
        # + restore `schedule="cron(0 0,6,14,22 * * ? *)"` here. The function
        # stays deployed for manual invokes; the INGEST_HEALTH sentinel keeps
        # tracking whatever runs.
        garmin = create_platform_lambda(
            self,
            "GarminIngestion",
            function_name="garmin-data-ingestion",
            source_file="lambdas/ingestion/garmin_lambda.py",
            handler="ingestion.garmin_lambda.lambda_handler",
            timeout_seconds=300,
            memory_mb=512,
            shared_layer=shared_utils_layer,
            additional_layers=[garth_layer],
            custom_policies=rp.ingestion_garmin(),
            # No async retry: a failed run is almost always an OAuth-refresh 429.
            # Retrying re-hammers Garmin's throttled endpoint and prolongs the
            # lockout; the gap-fill loop recovers missed days on the next run.
            retry_attempts=0,
            alerts_topic=None,
            **{k: v for k, v in shared.items() if k != "alerts_topic"},
        )
        garmin.node.default_child.add_property_override("ReservedConcurrentExecutions", 1)

        # ── 3. Notion — 5x daily
        create_platform_lambda(
            self,
            "NotionIngestion",
            function_name="notion-journal-ingestion",
            source_file="lambdas/ingestion/notion_lambda.py",
            handler="ingestion.notion_lambda.lambda_handler",
            schedule=f"cron(0 {INGEST_HOURLY} * * ? *)",
            timeout_seconds=120,
            environment={"NOTION_SECRET_NAME": "life-platform/ingestion-keys"},
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_notion(),
            alerts_topic=None,
            **{k: v for k, v in shared.items() if k != "alerts_topic"},
        )

        # ── 4. Withings — 5x daily (:05 stagger)
        withings = create_platform_lambda(
            self,
            "WithingsIngestion",
            function_name="withings-data-ingestion",
            source_file="lambdas/ingestion/withings_lambda.py",
            handler="ingestion.withings_lambda.lambda_handler",
            schedule=f"cron(5 {INGEST_HOURLY} * * ? *)",
            timeout_seconds=120,
            alarm_name="ingestion-error-withings",
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_withings(),
            **shared,
        )
        withings.node.default_child.add_property_override("ReservedConcurrentExecutions", 1)

        # ── 5. Habitify — 5x daily (:05 stagger)
        create_platform_lambda(
            self,
            "HabitifyIngestion",
            function_name="habitify-data-ingestion",
            source_file="lambdas/ingestion/habitify_lambda.py",
            handler="ingestion.habitify_lambda.lambda_handler",
            schedule=f"cron(5 {INGEST_HOURLY} * * ? *)",
            timeout_seconds=180,
            environment={"HABITIFY_SECRET_NAME": "life-platform/habitify"},
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_habitify(),
            alerts_topic=None,
            **{k: v for k, v in shared.items() if k != "alerts_topic"},
        )

        # ── 6. Strava — RE-ENABLED 2026-06-20. Paused 2026-05-28 on a persistent HTTP 402
        # (API paywall) since ~05-18; the Garmin→Strava auto-upload backstop now feeds
        # activities and a live test returned 200 (gap-filled 6/16–6/20, 0 errors). Schedule
        # restored. NB: `strava` is still listed in source_state.DECLARED_PAUSED_SOURCES, but
        # that is now behaviorally inert — resolve_source_state() returns `live` whenever the
        # data is fresh (freshness-wins). Drop it from that set on the next layer rebuild for
        # tidiness (pipeline_health_check.is_paused() still reads it directly — cosmetic only).
        strava = create_platform_lambda(
            self,
            "StravaIngestion",
            function_name="strava-data-ingestion",
            source_file="lambdas/ingestion/strava_lambda.py",
            handler="ingestion.strava_lambda.lambda_handler",
            schedule=f"cron(10 {INGEST_HOURLY} * * ? *)",  # RE-ENABLED 2026-06-20
            timeout_seconds=300,
            alarm_name="ingestion-error-strava",
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_strava(),
            **shared,
        )
        strava.node.default_child.add_property_override("ReservedConcurrentExecutions", 1)

        # ── 6a. Strava reconciliation (DI-2) — daily source-of-truth diff.
        # Every other freshness check reads only DDB and so is blind to a silent
        # drop (an activity the API has that never landed in the store — the Jun
        # 2026 evening-walk bug). This rule invokes the SAME lambda with
        # {"reconcile": true}: it pulls a trailing 14-day activity set from the
        # Strava API and diffs it against the store, emitting
        # LifePlatform/IngestReconciliation::MissingActivityCount{Source=strava}
        # (alarmed in monitoring_stack). 17:20 UTC = 10:20 AM PT — after the
        # morning ingestion crons have run, so the comparison is against a settled
        # store. UTC-fixed, no DST drift.
        strava_reconcile_rule = events.Rule(
            self,
            "StravaReconciliation",
            schedule=events.Schedule.cron(hour="17", minute="20"),
            description="DI-2: diff stored Strava activities vs the Strava API (trailing 14d) — emits MissingActivityCount",
        )
        strava_reconcile_rule.add_target(
            targets.LambdaFunction(
                strava,
                event=events.RuleTargetInput.from_object({"reconcile": True}),
            )
        )

        # ── 6b. Hevy webhook (real-time) — FunctionURL, no schedule.
        #        Per SPEC_HEVY_AND_NUTRITION_BRIDGE_2026_05_25 §2.2-A. The URL is
        #        registered with Hevy's webhook subscription endpoint after deploy.
        hevy_webhook = create_platform_lambda(
            self,
            "HevyWebhook",
            function_name="hevy-webhook",
            source_file="lambdas/ingestion/hevy_webhook_lambda.py",
            handler="ingestion.hevy_webhook_lambda.lambda_handler",
            timeout_seconds=30,
            memory_mb=256,
            environment={
                "SECRET_NAME": "life-platform/hevy",
                "S3_BUCKET": "matthew-life-platform",
                "TABLE_NAME": "life-platform",
            },
            alarm_name="ingestion-error-hevy-webhook",
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_hevy_webhook(),
            **shared,
        )
        # Expose a public FunctionURL for Hevy to POST to. Auth=NONE because
        # Hevy can't sign with a CDK-managed IAM principal; we validate via
        # the webhook_secret stored in life-platform/hevy.
        hevy_webhook_url = hevy_webhook.add_function_url(
            auth_type=_lambda.FunctionUrlAuthType.NONE,
        )

        # ── 6c. Hevy events-feed poller (PRIMARY ingestion path — hourly).
        # Discovered 2026-05-25: Hevy doesn't currently offer public webhook
        # subscriptions (OpenAPI spec at api.hevyapp.com/docs/ has no
        # /v1/webhook* endpoints). The webhook Lambda above stays deployed
        # for future Hevy webhook support but currently doesn't receive
        # traffic. This poller is the actual ingestion mechanism: every
        # waking hour, walk /v1/workouts/events?since=<last_success>.
        # 12-23 UTC = 5 AM – 4 PM PT.  Adjust if Matthew lifts later.
        create_platform_lambda(
            self,
            "HevyBackfill",
            function_name="hevy-backfill",
            source_file="lambdas/ingestion/hevy_backfill_lambda.py",
            handler="ingestion.hevy_backfill_lambda.lambda_handler",
            schedule="cron(0 12-23 * * ? *)",  # hourly :00, 5 AM – 4 PM PT
            timeout_seconds=300,
            memory_mb=256,
            environment={
                "SECRET_NAME": "life-platform/hevy",
                "S3_BUCKET": "matthew-life-platform",
                "TABLE_NAME": "life-platform",
            },
            alarm_name="ingestion-error-hevy-backfill",
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_hevy_backfill(),
            **shared,
        )

        # Export the FunctionURL so the post-deploy `setup_hevy_webhook_subscription.sh`
        # script can register it with Hevy.
        cdk.CfnOutput(
            self,
            "HevyWebhookFunctionUrl",
            value=hevy_webhook_url.url,
            description="POST this URL to Hevy's webhook subscription endpoint",
        )

        # ── (6d) MacroFactor unofficial-API puller removed 2026-05-25.
        # Was attempted as WS-2 Tier 1 under SPEC_HEVY_AND_NUTRITION_BRIDGE §3
        # and ADR-061: pull nutrition + workouts via reverse-engineered Firebase
        # auth + Firestore. Blocked by Firebase App Check enforcement (5
        # workarounds tried — Android client headers, v3/verifyPassword,
        # Referer/Origin spoofing, no-bundle, debug App Check token). MF
        # nutrition + workouts continue to flow through Tier 2 (manual Dropbox
        # CSV export → dropbox-poll → macrofactor-data-ingestion). See ADR-061
        # for the full attempt + tear-down rationale.

        # ── 7. Journal Enrichment — 6:30 AM PT daily
        create_platform_lambda(
            self,
            "JournalEnrichment",
            function_name="journal-enrichment",
            source_file="lambdas/ingestion/journal_enrichment_lambda.py",
            handler="ingestion.journal_enrichment_lambda.lambda_handler",
            schedule="cron(30 14 * * ? *)",
            timeout_seconds=300,
            environment={"ANTHROPIC_SECRET": "life-platform/ai-keys"},
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_journal_enrichment(),
            alerts_topic=None,
            **{k: v for k, v in shared.items() if k != "alerts_topic"},
        )

        # ── 8. Todoist — 1x daily (TD-12, 2026-05-03): dropped from 2x to 1x.
        # Lambda has a no-op gate that returns early if no changes since last run; in
        # practice most invocations did nothing. Daily cadence is fine for a personal
        # accountability platform — Matthew isn't refreshing a dashboard hoping for
        # real-time task additions. Future work: webhook migration alongside other
        # sources (Notion, Whoop, Habitify).
        # cron(0 14 * * ? *) = 14:00 UTC = 6 AM PST / 7 AM PDT (UTC-fixed per CLAUDE.md).
        create_platform_lambda(
            self,
            "TodoistIngestion",
            function_name="todoist-data-ingestion",
            source_file="lambdas/ingestion/todoist_lambda.py",
            handler="ingestion.todoist_lambda.lambda_handler",
            schedule="cron(0 14 * * ? *)",
            timeout_seconds=120,
            alarm_name="ingestion-error-todoist",
            environment={"SECRET_NAME": "life-platform/ingestion-keys"},
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_todoist(),
            **shared,
        )

        # ── 9. Eight Sleep — 5x daily (:15 stagger)
        eightsleep = create_platform_lambda(
            self,
            "EightsleepIngestion",
            function_name="eightsleep-data-ingestion",
            source_file="lambdas/ingestion/eightsleep_lambda.py",
            handler="ingestion.eightsleep_lambda.lambda_handler",
            schedule=f"cron(15 {INGEST_HOURLY} * * ? *)",
            timeout_seconds=120,
            alarm_name="ingestion-error-eightsleep",
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_eightsleep(),
            **shared,
        )
        eightsleep.node.default_child.add_property_override("ReservedConcurrentExecutions", 1)

        # ── 10. Activity Enrichment — 7:30 AM PT daily
        create_platform_lambda(
            self,
            "ActivityEnrichment",
            function_name="activity-enrichment",
            source_file="lambdas/ingestion/enrichment_lambda.py",
            handler="ingestion.enrichment_lambda.lambda_handler",
            schedule="cron(30 15 * * ? *)",
            timeout_seconds=300,
            alarm_name="ingestion-error-enrichment",
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_activity_enrichment(),
            **shared,
        )

        # ── 11. MacroFactor — S3-trigger only (upload via dropbox_poll or manual).
        # #469 (B-7): the old daily cron(0 16) was a guaranteed no-op — the handler
        # requires an S3 record and 400'd every scheduled invoke (365 dead runs/year
        # masquerading as coverage). The real paths are the S3 event notification
        # below + dropbox_poll's upload; liveness is dropbox's ER-01 sentinel.
        macrofactor = create_platform_lambda(
            self,
            "MacrofactorIngestion",
            function_name="macrofactor-data-ingestion",
            source_file="lambdas/ingestion/macrofactor_lambda.py",
            handler="ingestion.macrofactor_lambda.lambda_handler",
            timeout_seconds=300,
            alarm_name="ingestion-error-macrofactor",
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_macrofactor(),
            **shared,
        )
        macrofactor.add_permission(
            "S3InvokeMacrofactor",
            principal=iam.ServicePrincipal("s3.amazonaws.com"),
            source_arn=f"arn:aws:s3:::{S3_BUCKET}",  # SEC-01: IAM level is bucket-scoped; prefix filtering enforced via S3 event notification filter on uploads/macrofactor/ prefix
            source_account=self.account,
        )

        # ── 12. Weather — 2x daily (COST-OPT-2: weather doesn't change meaningfully hourly)
        create_platform_lambda(
            self,
            "WeatherIngestion",
            function_name="weather-data-ingestion",
            source_file="lambdas/ingestion/weather_lambda.py",
            handler="ingestion.weather_lambda.lambda_handler",
            schedule="cron(0 14,2 * * ? *)",
            timeout_seconds=60,
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_weather(),
            alerts_topic=None,
            **{k: v for k, v in shared.items() if k != "alerts_topic"},
        )

        # ── 13. Dropbox Poll — every 30 minutes
        create_platform_lambda(
            self,
            "DropboxPoll",
            function_name="dropbox-poll",
            source_file="lambdas/ingestion/dropbox_poll_lambda.py",
            handler="ingestion.dropbox_poll_lambda.lambda_handler",
            schedule="rate(30 minutes)",
            timeout_seconds=120,
            environment={"SECRET_NAME": "life-platform/ingestion-keys"},
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_dropbox(),
            alerts_topic=None,
            **{k: v for k, v in shared.items() if k != "alerts_topic"},
        )

        # ── 14. (RETIRED 2026-07-04, #474/D-5, ADR-103) apple-health-ingestion —
        # the export.xml import path. It was a latent full-replace clobber of the
        # records the HAE webhook merge-enriches (_rd_* dedup maps, SoM/TIR,
        # monotonic guards) and its S3 trigger never existed. Deleted; the HAE
        # webhook is the sole apple_health writer. Historical XML backfill:
        # backfill/archive/backfill_apple_health.py (hard-guarded).

        # ── 15. Health Auto Export Webhook — API Gateway trigger
        _ASSET_EXCLUDES = [
            "__pycache__",
            "**/__pycache__/**",
            "*.pyc",
            "**/*.pyc",
            "*.md",
            ".DS_Store",
            "dashboard",
            "dashboard/**",
            "cf-auth",
            "cf-auth/**",
            "requirements",
            "requirements/**",
        ]
        hae_role = iam.Role(
            self,
            "HaeWebhookRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")],
        )
        for stmt in rp.ingestion_hae():
            hae_role.add_to_policy(stmt)
        # NOTE: HAE uses code=from_asset (entire lambdas/ dir), not source_file=.
        # Handler health_auto_export_lambda.lambda_handler → lambdas/health_auto_export_lambda.py  # noqa: CDK_HANDLER_ORPHAN
        hae = _lambda.Function(
            self,
            "HaeWebhook",
            function_name="health-auto-export-webhook",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="ingestion.health_auto_export_lambda.lambda_handler",
            code=_lambda.Code.from_asset("../lambdas", exclude=_ASSET_EXCLUDES),
            role=hae_role,
            timeout=Duration.seconds(300),
            memory_size=256,
            environment={
                "TABLE_NAME": local_table.table_name,
                "S3_BUCKET": local_bucket.bucket_name,
                "USER_ID": self.node.try_get_context("user_id") or "matthew",
            },
        )  # Phase 1.6 (2026-05-16): 60s→300s. Large Apple Health exports (10-50MB) silently 504'd. BUG-07.

        # ── HTTP API front door (#500/D-7) ──
        # Imported into CDK: this was console-created 2026-02-24 (api id
        # a76xwxt2wa, name "health-auto-export-api") and only referenced by a
        # hardcoded ARN string in a Lambda permission — the route, stage,
        # throttle, and access-log config lived entirely outside IaC. Values
        # below mirror the live config so `cdk deploy` can rebuild the edge
        # from scratch. Auth is the Lambda's own bearer-token check (see
        # health_auto_export_lambda.py) — WAFv2 cannot attach to HTTP APIs
        # (only REST APIs / ALB / CloudFront), so it is NOT a defense here.
        # See ADR-057's correction: WAF was removed 2026-06 platform-wide;
        # rate limiting is in-Lambda/DynamoDB (rate_limiter.py), and this
        # stage's throttle settings are the only edge-level guard.
        hae_api = apigwv2.HttpApi(
            self,
            "HaeWebhookApi",
            api_name="health-auto-export-api",
            create_default_stage=False,
            disable_execute_api_endpoint=False,
        )
        hae_routes = hae_api.add_routes(
            path="/ingest",
            methods=[apigwv2.HttpMethod.POST],
            integration=HttpLambdaIntegration("HaeWebhookIntegration", hae),
        )
        # Pre-existing log group (console-created alongside the API); imported
        # rather than owned so CDK doesn't try to manage its retention/removal.
        hae_access_log_group = logs.LogGroup.from_log_group_name(
            self, "HaeWebhookApiAccessLogGroup", "/aws/apigateway/health-auto-export-api"
        )
        hae_stage = apigwv2.CfnStage(
            self,
            "HaeWebhookApiDefaultStage",
            api_id=hae_api.http_api_id,
            stage_name="$default",
            auto_deploy=True,
            access_log_settings=apigwv2.CfnStage.AccessLogSettingsProperty(
                destination_arn=hae_access_log_group.log_group_arn,
                format="$context.requestId $context.requestTime $context.httpMethod $context.path "
                "$context.status $context.error.message $context.identity.sourceIp",
            ),
            default_route_settings=apigwv2.CfnStage.RouteSettingsProperty(
                throttling_burst_limit=10,
                throttling_rate_limit=1.67,
            ),
            # NB: the per-route `route_settings` map is a CDK serialization
            # trap — unlike default_route_settings (a typed property CDK runs
            # through its converter → PascalCase), map VALUES are passed
            # through untransformed, so a CfnStage.RouteSettingsProperty here
            # emits camelCase keys (throttlingBurstLimit) that the CFN
            # ApiGatewayV2::Stage handler rejects ("Unrecognized field ...").
            # Pass a raw dict with CloudFormation-native PascalCase keys.
            route_settings={
                "POST /ingest": {
                    "ThrottlingBurstLimit": 20,
                    "ThrottlingRateLimit": 10.0,
                },
            },
        )
        # The stage's per-route RouteSettings ("POST /ingest") is validated by
        # the ApiGatewayV2 service against routes that already exist — without
        # an explicit ordering, CFN creates the stage before the route and
        # fails with "Unable to find Route by key POST /ingest". Force the
        # route(s) to materialize first.
        for _route in hae_routes:
            hae_stage.node.add_dependency(_route)
        # NOTE: add_routes()'s HttpLambdaIntegration auto-grants the API
        # Gateway invoke permission on `hae` scoped to this route — no manual
        # hae.add_permission() needed (that hardcoded-ARN call is what this
        # story removes).

        # ── 16. Google Calendar — RETIRED (ADR-030, v3.7.46)
        # All integration paths blocked by Smartsheet IT policy or macOS restrictions.
        # Lambda + EventBridge rule removed. See docs/DECISIONS.md ADR-030.

        # ── 17. Food Delivery — S3 trigger on uploads/food_delivery/
        food_delivery = create_platform_lambda(
            self,
            "FoodDeliveryIngestion",
            function_name="food-delivery-ingestion",
            source_file="lambdas/ingestion/food_delivery_lambda.py",
            handler="ingestion.food_delivery_lambda.lambda_handler",
            timeout_seconds=60,
            shared_layer=shared_utils_layer,
            custom_policies=rp.food_delivery_ingestion(),
            **shared,
        )
        food_delivery.add_permission(
            "S3InvokeFoodDelivery",
            principal=iam.ServicePrincipal("s3.amazonaws.com"),
            source_arn=f"arn:aws:s3:::{S3_BUCKET}",
            source_account=self.account,
        )

        # ── 18. Measurements — S3 trigger on imports/measurements/ (#473/B-4:
        # re-armed 2026-07-04 per ADR-044; the notification itself lives in the
        # bucket config OUTSIDE CDK — see the runbook. This grants S3 invoke.)
        measurements = create_platform_lambda(
            self,
            "MeasurementsIngestion",
            function_name="measurements-ingestion",
            source_file="lambdas/ingestion/measurements_ingestion_lambda.py",
            handler="ingestion.measurements_ingestion_lambda.lambda_handler",
            timeout_seconds=60,
            shared_layer=shared_utils_layer,
            custom_policies=rp.measurements_ingestion(),
            **shared,
        )
        measurements.add_permission(
            "S3InvokeMeasurements",
            principal=iam.ServicePrincipal("s3.amazonaws.com"),
            source_arn=f"arn:aws:s3:::{S3_BUCKET}",
            source_account=self.account,
        )

        cdk.CfnOutput(self, "WhoopFnArn", value=whoop.function_arn, description="Whoop ingestion Lambda ARN")
        cdk.CfnOutput(self, "HaeWebhookFnArn", value=hae.function_arn, description="Health Auto Export webhook Lambda ARN")
        cdk.CfnOutput(
            self, "HaeWebhookApiEndpoint", value=hae_api.api_endpoint, description="Health Auto Export webhook API Gateway endpoint"
        )
