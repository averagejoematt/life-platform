"""
EmailStack — email/digest Lambdas + EventBridge schedules.

v2.0 (v3.4.0): CDK-managed IAM roles replace existing_role_arn references.
  All 8 Lambdas get dedicated CDK-owned roles with least-privilege policies.

v2.1 (v3.7.62): BS-03 Chronicle Email Sender added.
v2.2 (FEAT-12): chronicle-approve Lambda + preview-before-publish workflow.

Lambdas (11):
  daily-brief, weekly-digest, monthly-digest, nutrition-review,
  wednesday-chronicle, weekly-plate, monday-compass, partner-weekly-email,
  evening-nudge, chronicle-email-sender (BS-03), chronicle-approve (FEAT-12),
  weekly-signal (PB-06)

"""

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_dynamodb as dynamodb,
    aws_events as events,
    aws_events_targets as targets,
    aws_lambda as _lambda,
    aws_s3 as s3,
    aws_sns as sns,
    aws_sqs as sqs,
)
from constructs import Construct

from stacks import role_policies as rp
from stacks.constants import ACCT, CF_DIST_ID, REGION, SHARED_LAYER_ARN  # single source of truth for layer version
from stacks.lambda_helpers import create_platform_lambda

INGESTION_DLQ_ARN = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
LIFE_PLATFORM_TABLE = "life-platform"
LIFE_PLATFORM_BUCKET = "matthew-life-platform"
ALERTS_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"
DIGEST_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts-digest"


class EmailStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, table, bucket, dlq, alerts_topic, digest_topic=None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        local_dlq = sqs.Queue.from_queue_arn(self, "IngestionDLQ", INGESTION_DLQ_ARN)
        local_table = dynamodb.Table.from_table_name(self, "LifePlatformTable", LIFE_PLATFORM_TABLE)
        local_bucket = s3.Bucket.from_bucket_name(self, "LifePlatformBucket", LIFE_PLATFORM_BUCKET)
        local_alerts_topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)
        local_digest_topic = sns.Topic.from_topic_arn(self, "DigestTopic", DIGEST_TOPIC_ARN)

        shared_utils_layer = _lambda.LayerVersion.from_layer_version_arn(self, "SharedUtilsLayer", SHARED_LAYER_ARN)
        # ADR-050: email Lambda error alarms route to digest. They're recoverable
        # (next day's run picks up where this one failed) and rarely user-facing.
        # daily-brief still has its urgent alarm via MonitoringStack.
        shared = dict(
            table=local_table,
            bucket=local_bucket,
            dlq=local_dlq,
            alerts_topic=local_alerts_topic,
            digest_topic=local_digest_topic,
            digest=True,
            shared_layer=shared_utils_layer,
        )

        # daily-brief: alerts_topic=None — MonitoringStack owns its alarms
        # (slo-daily-brief-delivery, life-platform-daily-brief-errors,
        #  daily-brief-no-invocations-24h, daily-brief-duration-high).
        # Suppressed here to avoid ingestion-error-daily-brief duplicate. COST-A 2026-03-10.
        _email_env = {
            "ANTHROPIC_SECRET": "life-platform/ai-keys",
            # Editorial cover imagery (visual uplevel P3, 2026-07-03): the durable ON
            # switch for editorial_image.py — chronicle + podcast covers. Must live here
            # (a CLI env-set is wiped by the next stack deploy). Fail-soft by design;
            # flip to "off" + redeploy to roll back.
            "EDITORIAL_IMAGES": "on",
        }

        # daily-brief timeout bumped 300s → 900s (Lambda max) on 2026-05-03 v6.8.10.
        # Pre-existing chronic timeout: 6 coach V2 narratives + IC-3 + ensemble work
        # was sometimes exceeding 5 min, especially when Anthropic was slow. Today's
        # alarm cascade was triggered when Anthropic recovered after the morning
        # disable — calls actually completed but blew past the 300s budget. 900s
        # gives ample headroom; daily-brief typically completes in 4-5 min when
        # Anthropic is healthy. Memory bumped 512→768 MB for some headroom too.
        create_platform_lambda(
            self,
            "DailyBrief",
            function_name="daily-brief",
            handler="emails.daily_brief_lambda.lambda_handler",
            source_file="lambdas/emails/daily_brief_lambda.py",
            schedule="cron(0 17 * * ? *)",
            timeout_seconds=900,
            memory_mb=768,
            environment=_email_env,
            custom_policies=rp.email_daily_brief(),
            **{**shared, "alerts_topic": None},
        )

        create_platform_lambda(
            self,
            "WeeklyDigest",
            function_name="weekly-digest",
            handler="emails.weekly_digest_lambda.lambda_handler",
            source_file="lambdas/emails/weekly_digest_lambda.py",
            schedule="cron(0 16 ? * SUN *)",
            timeout_seconds=120,
            memory_mb=256,
            environment=_email_env,
            custom_policies=rp.email_weekly_digest(),
            **shared,
        )

        create_platform_lambda(
            self,
            "MonthlyDigest",
            function_name="monthly-digest",
            handler="emails.monthly_digest_lambda.lambda_handler",
            source_file="lambdas/emails/monthly_digest_lambda.py",
            schedule="cron(0 16 ? * 1#1 *)",
            timeout_seconds=120,
            memory_mb=256,
            environment=_email_env,
            custom_policies=rp.email_monthly_digest(),
            **shared,
        )

        create_platform_lambda(
            self,
            "NutritionReview",
            function_name="nutrition-review",
            handler="emails.nutrition_review_lambda.lambda_handler",
            source_file="lambdas/emails/nutrition_review_lambda.py",
            schedule="cron(0 17 ? * SAT *)",
            # Verified at 63% of ceiling (max 75.5s / 120s over 30d) — the AI review's
            # only at-risk scheduled generator; 300s gives a slow-Bedrock-day cushion so
            # it can't follow coach-history-summarizer into the DLQ. (Audit 2026-06-28.)
            timeout_seconds=300,
            memory_mb=256,
            environment=_email_env,
            custom_policies=rp.email_nutrition_review(),
            **shared,
        )

        # SEASON-1 ZOMBIE RETIRED (2026-07-02, flagged by #310): the weekly Wed 15:40 UTC
        # cron kept re-indexing the stale /podcast/episodes.json from season 1's dead
        # posts.json (and _episode_exists keys mp3s by bare wk{N}, colliding across
        # cycles). The lambda STAYS for manual/one-off invokes (back-catalogue re-render,
        # feed repair) — only the schedule is removed. The live weekly show is
        # coach-panel-podcast ("The Panel"), below.
        create_platform_lambda(
            self,
            "ChroniclePodcast",
            function_name="chronicle-podcast",
            handler="emails.chronicle_podcast_lambda.lambda_handler",
            source_file="lambdas/emails/chronicle_podcast_lambda.py",
            # 900s: a force re-render voices the whole back-catalogue (5+ episodes,
            # multi-chunk Google TTS each) in one pass — 300s timed out mid-catalogue.
            timeout_seconds=900,
            memory_mb=512,
            environment=_email_env,
            custom_policies=rp.email_chronicle_podcast(),
            **shared,
        )

        # "The Panel" — weekly two-host show (Elena + a rotating coach). Runs at
        # 16:20 UTC, ~40 min after the chronicle podcast, so posts.json + the
        # week's COACH#/OUTPUT# are settled. Bedrock script-gen + Google Chirp 3: HD.
        coach_panel_podcast = create_platform_lambda(
            self,
            "CoachPanelPodcast",
            function_name="coach-panel-podcast",
            handler="emails.coach_panel_podcast_lambda.lambda_handler",
            source_file="lambdas/emails/coach_panel_podcast_lambda.py",
            # Fri 17:00 UTC (10am PT) — chronicle drops Wed; the Panel reviews the
            # settled week on Friday. 900s: Sonnet writer + Haiku judge + Gemini synth.
            schedule="cron(0 17 ? * FRI *)",
            timeout_seconds=900,
            memory_mb=512,
            environment=_email_env,
            custom_policies=rp.email_coach_panel_podcast(),
            **shared,
        )

        # SS-02 hold-aging sweep: a soft (quality) HOLD used to strand an episode in
        # panelcast-holds/ forever (the Friday cron moves on to the next week). This
        # Mon+Wed 18:00 UTC rule passes {"sweep_holds": true} to auto-RETRY a quality
        # hold on the current week (a fresh generation through every gate) once a review
        # window has lapsed — so a fixable flag can't permanently silence the show.
        # Safety/sensitivity holds are NEVER auto-retried (fail-closed in the handler).
        # Twice-weekly (not daily) keeps the regeneration spend low; the retry cap bounds it.
        panel_hold_sweep = events.Rule(
            self,
            "PanelHoldSweep",
            schedule=events.Schedule.cron(minute="0", hour="18", week_day="MON,WED"),
            description="SS-02: retry a soft (quality) Panel HOLD on the current week after the review window",
        )
        panel_hold_sweep.add_target(
            targets.LambdaFunction(
                coach_panel_podcast,
                event=events.RuleTargetInput.from_object({"sweep_holds": True}),
            )
        )

        wednesday_chronicle = create_platform_lambda(
            self,
            "WednesdayChronicle",
            function_name="wednesday-chronicle",
            handler="emails.wednesday_chronicle_lambda.lambda_handler",
            source_file="lambdas/emails/wednesday_chronicle_lambda.py",
            schedule="cron(0 15 ? * WED *)",
            timeout_seconds=120,
            memory_mb=256,
            environment=_email_env,
            custom_policies=rp.email_wednesday_chronicle(),
            **shared,
        )

        create_platform_lambda(
            self,
            "WeeklyPlate",
            function_name="weekly-plate",
            handler="emails.weekly_plate_lambda.lambda_handler",
            source_file="lambdas/emails/weekly_plate_lambda.py",
            schedule="cron(0 2 ? * SAT *)",
            timeout_seconds=120,
            memory_mb=512,
            environment=_email_env,
            custom_policies=rp.email_weekly_plate(),
            **shared,
        )

        create_platform_lambda(
            self,
            "MondayCompass",
            function_name="monday-compass",
            handler="emails.monday_compass_lambda.lambda_handler",
            source_file="lambdas/emails/monday_compass_lambda.py",
            schedule="cron(0 15 ? * MON *)",
            timeout_seconds=120,
            memory_mb=512,
            environment=_email_env,
            custom_policies=rp.email_monday_compass(),
            **shared,
        )

        # EXTERNAL_EMAILS_ENABLED kill switch — flip to "true" to resume sending to
        # non-Matthew recipients (Partner, confirmed subscribers). Used by
        # partner-weekly-email, chronicle-email-sender, weekly-signal.
        # The recipient address is PII and lives OUT of the repo: SSM parameter
        # /life-platform/partner-email (created via CLI; on the managed-where
        # ledger). The lambda reads it at runtime with a cached client and falls
        # back to Matthew's own address if the parameter is absent.
        _partner_env = {
            **_email_env,
            "PARTNER_EMAIL_PARAM": "/life-platform/partner-email",
            "EMAIL_SENDER": "awsdev@mattsusername.com",
            "EXTERNAL_EMAILS_ENABLED": "false",
        }
        create_platform_lambda(
            self,
            "PartnerWeeklyEmail",
            function_name="partner-weekly-email",
            handler="emails.partner_email_lambda.lambda_handler",
            source_file="lambdas/emails/partner_email_lambda.py",
            schedule="cron(30 17 ? * 1 *)",
            timeout_seconds=90,
            memory_mb=256,
            environment=_partner_env,
            custom_policies=rp.email_partner(),
            **shared,
        )

        # R54: Evening nudge — checks supplements/journal/How We Feel completeness at 8 PM PT
        # cron(0 3 * * ? *) = 3:00 AM UTC = 8:00 PM PDT (UTC-7). Adjust after DST ends.
        create_platform_lambda(
            self,
            "EveningNudge",
            function_name="evening-nudge",
            handler="emails.evening_nudge_lambda.lambda_handler",
            source_file="lambdas/emails/evening_nudge_lambda.py",
            schedule="cron(0 3 * * ? *)",
            timeout_seconds=60,
            memory_mb=256,
            environment=_email_env,
            custom_policies=rp.email_evening_nudge(),
            **shared,
        )

        # PB-06: Weekly Signal — curated 5-section subscriber email every Sunday 9:30 AM PT.
        # Reads pre-computed data from S3 + DynamoDB — no AI calls.
        # Independent DLQ + alarm. timeout_seconds=300: headroom for rate-limited sends.
        create_platform_lambda(
            self,
            "WeeklySignal",
            function_name="weekly-signal",
            handler="compute.weekly_signal_lambda.lambda_handler",
            source_file="lambdas/compute/weekly_signal_lambda.py",
            schedule="cron(30 16 ? * SUN *)",  # Sunday 9:30 AM PT
            timeout_seconds=300,
            memory_mb=256,
            environment={
                "SITE_URL": "https://averagejoematt.com",
                "SEND_RATE_PER_SEC": "14.0",
                "EXTERNAL_EMAILS_ENABLED": "false",  # privacy mode kill switch
            },
            custom_policies=rp.email_weekly_signal(),
            **shared,
        )

        # BS-03: Chronicle Email Sender — delivers Chronicle installment to confirmed subscribers.
        # Fires 10 min after wednesday-chronicle (cron(0 15 ? * WED *) = 8:00 AM PT).
        # Viktor guard: clean no-op if no installment found this week.
        # Independent DLQ + alarm from wednesday-chronicle.
        # timeout_seconds=300: headroom for ~300 subs at 1/sec rate limit.
        # Bump SEND_RATE_PER_SEC env var after SES production access is granted.
        chronicle_sender = create_platform_lambda(
            self,
            "ChronicleEmailSender",
            function_name="chronicle-email-sender",
            handler="emails.chronicle_email_sender_lambda.lambda_handler",
            source_file="lambdas/emails/chronicle_email_sender_lambda.py",
            schedule="cron(10 15 ? * WED *)",
            timeout_seconds=300,
            memory_mb=256,
            environment={
                "SITE_URL": "https://averagejoematt.com",
                "SEND_RATE_PER_SEC": "14.0",
                "EXTERNAL_EMAILS_ENABLED": "false",  # privacy mode kill switch
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
            self,
            "ChronicleApprove",
            function_name="chronicle-approve",
            handler="emails.chronicle_approve_lambda.lambda_handler",
            source_file="lambdas/emails/chronicle_approve_lambda.py",
            timeout_seconds=60,
            memory_mb=256,
            # SS-01: a daily sweep auto-publishes any draft older than the review window
            # (CHRONICLE_AUTOPUBLISH_HOURS) so the weekly story never goes dark unattended.
            # The scheduled invoke arrives as source=aws.events → handled as a sweep.
            schedule="cron(0 18 * * ? *)",  # daily 10:00 AM PT
            environment={
                "CF_DIST_ID": CF_DIST_ID,
                "CHRONICLE_EMAIL_SENDER_ARN": chronicle_sender.function_arn,
                "CHRONICLE_AUTOPUBLISH_HOURS": "48",  # publish a draft unapproved for this long…
                "CHRONICLE_AUTOPUBLISH_MAX_DAYS": "10",  # …but never resurrect one abandoned past this
            },
            custom_policies=rp.email_chronicle_approve(),
            **shared,
        )
        approve_url_obj = chronicle_approve.add_function_url(
            auth_type=_lambda.FunctionUrlAuthType.NONE,
        )
        cdk.CfnOutput(
            self,
            "ChronicleApproveFunctionUrl",
            value=approve_url_obj.url,
            description="Lambda Function URL for chronicle-approve (FEAT-12 preview workflow)",
        )

        # Update wednesday-chronicle to know the approve Lambda URL.
        # PREVIEW_MODE defaults to 'true'; set to 'false' in CDK context to disable preview.
        _preview_mode = self.node.try_get_context("chronicle_preview_mode") or "true"
        wednesday_chronicle.add_environment("PREVIEW_MODE", _preview_mode)
        wednesday_chronicle.add_environment("APPROVE_LAMBDA_URL", approve_url_obj.url)

        # ── Subscriber Onboarding — daily (Day 2 bridge email for new subscribers)
        create_platform_lambda(
            self,
            "SubscriberOnboarding",
            function_name="subscriber-onboarding",
            source_file="lambdas/web/subscriber_onboarding_lambda.py",
            handler="web.subscriber_onboarding_lambda.lambda_handler",
            schedule="cron(5 17 * * ? *)",  # 10:05 AM PT daily (staggered from daily-brief)
            timeout_seconds=120,
            memory_mb=256,
            environment=_email_env,
            custom_policies=rp.subscriber_onboarding(),
            **shared,
        )
