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
from stacks.constants import ACCT, CF_DIST_ID, LAMEENC_LAYER_ARN, REGION, TABLE_NAME
from stacks.lambda_helpers import create_platform_lambda

INGESTION_DLQ_ARN = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
LIFE_PLATFORM_TABLE = TABLE_NAME
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

        # COST-01 (#790, ADR-116 executed 2026-07-07): the ~16 per-Lambda
        # `ingestion-error-*` first-error alarms on email Lambdas are RETIRED
        # (error_alarm=False). Every email Lambda already routes terminal async
        # failures to the shared `life-platform-ingestion-dlq` (dlq=local_dlq below,
        # verified in synth: 17/17 have a DeadLetterConfig + per-role sqs:SendMessage),
        # which is alarmed by `life-platform-ingestion-dlq-messages` (monitoring) +
        # `life-platform-dlq-depth-warning` (operational) and covered by the DLQ
        # digest. daily-brief is unaffected — it already opted out here
        # (alerts_topic=None) and keeps its dedicated MonitoringStack alarms
        # (life-platform-daily-brief-errors, slo-daily-brief-delivery, etc.).
        # ~$1.60/mo (16 × $0.10). See ADR-116 §5.
        shared = dict(
            table=local_table,
            bucket=local_bucket,
            dlq=local_dlq,
            alerts_topic=local_alerts_topic,
            digest_topic=local_digest_topic,
            digest=True,
            error_alarm=False,
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

        # DAILY DEBRIEF (#734, epic #721) — the ~2-minute "state of Matthew" audio
        # briefing. Reads the already-computed daily-brief facts, ONE grounded Haiku
        # call (ADR-104, template fallback), Google Chirp 3: HD → MP3 under
        # generated/podcast/debrief/ + a podcast RSS feed. Daily 19:00 UTC (noon PT /
        # 11 AM PST) — after the morning compute + daily-brief window, so it narrates
        # the freshest complete day. Fixed UTC (no DST drift). 300s: one Haiku call +
        # a short single-voice TTS synth; 512 MB is ample. Narration is budget-gated
        # (budget_guard "daily_debrief", tier ≥ 2 → template), so the show never goes
        # dark for cost — it degrades to the deterministic narrative at $0 AI spend.
        create_platform_lambda(
            self,
            "DailyDebrief",
            function_name="daily-debrief",
            handler="emails.daily_debrief_lambda.lambda_handler",
            source_file="lambdas/emails/daily_debrief_lambda.py",
            schedule="cron(0 19 * * ? *)",
            timeout_seconds=300,
            memory_mb=512,
            environment=_email_env,
            custom_policies=rp.email_daily_debrief(),
            **shared,
        )

        # "The Panel" — two-host show (Elena + a rotating coach). EVENT-DRIVEN since
        # #734: the standing Friday cron was RETIRED (it fired every week regardless of
        # engagement and tripped the panelcast-no-episode alarm the moment Matthew
        # disengaged). It now ships only when a week EARNS an episode — chronicle-approve
        # async-invokes it on publish (mirrors its chronicle-email-sender / elena-state-
        # updater triggers). The Panel's own reset-proof week-selection + idempotency +
        # publish-or-HOLD are unchanged. Still manually invokable ({} / {"force": true} /
        # {"dry_run": true}) and driven by the hold-sweep rule below. Bedrock script-gen +
        # Google Chirp 3: HD. 900s: Sonnet writer + Haiku judge + Gemini synth.
        # lameenc dependency layer (#1018): audio_encode compresses the episode WAV
        # to spoken-word MP3 at publish. Fail-open — a missing layer publishes WAV.
        lameenc_layer = _lambda.LayerVersion.from_layer_version_arn(self, "LameencLayer", LAMEENC_LAYER_ARN)
        coach_panel_podcast = create_platform_lambda(
            self,
            "CoachPanelPodcast",
            function_name="coach-panel-podcast",
            handler="emails.coach_panel_podcast_lambda.lambda_handler",
            source_file="lambdas/emails/coach_panel_podcast_lambda.py",
            timeout_seconds=900,
            memory_mb=512,
            environment=_email_env,
            custom_policies=rp.email_coach_panel_podcast(),
            additional_layers=[lameenc_layer],
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

        # #398: Between-chronicle note — the machine's mid-gap findings for
        # subscribers, assembled purely from already-computed records (monthly
        # what-changed, graded predictions, stance shifts). Zero AI inference.
        # Sends ONLY when there is real, previously-unsent content (content-hash
        # dedup marker); honors the same EXTERNAL_EMAILS_ENABLED kill switch.
        # Sunday 17:00 UTC — mid-gap between Wednesday chronicles.
        create_platform_lambda(
            self,
            "BetweenChronicle",
            function_name="between-chronicle",
            handler="emails.between_chronicle_lambda.lambda_handler",
            source_file="lambdas/emails/between_chronicle_lambda.py",
            schedule="cron(0 17 ? * SUN *)",
            timeout_seconds=300,
            memory_mb=256,
            environment={
                "SITE_URL": "https://averagejoematt.com",
                "SEND_RATE_PER_SEC": "14.0",
                "EXTERNAL_EMAILS_ENABLED": "false",  # same privacy-mode kill switch as the chronicle
            },
            custom_policies=rp.email_between_chronicle(),
            **shared,
        )

        # #537: Elena Voss persona state updater — post-PUBLISH Haiku extraction
        # into PERSONA#elena (threads, callbacks ledger, motifs, receipts-gated
        # stance). No schedule — async-invoked from the chronicle publish paths
        # (chronicle-approve's approve click + stale-draft sweep, and
        # wednesday-chronicle's direct-publish branch when PREVIEW_MODE=false).
        create_platform_lambda(
            self,
            "ElenaStateUpdater",
            function_name="elena-state-updater",
            handler="emails.elena_state_updater.lambda_handler",
            source_file="lambdas/emails/elena_state_updater.py",
            timeout_seconds=120,
            memory_mb=256,
            custom_policies=rp.email_elena_state_updater(),
            **shared,
        )

        # FEAT-12: Chronicle Approve Lambda — one-click approve/reject for Chronicle drafts.
        # Invoked via Lambda Function URL embedded in the preview email.
        # No EventBridge schedule — triggered only by Matthew clicking the preview email link.
        # approve → writes pre-built S3 artifacts, invalidates CF, invokes chronicle-email-sender
        # + elena-state-updater (#537). request_changes → marks DDB status, no publish.
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
