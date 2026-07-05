"""
ComputeStack — pre-computation Lambdas + EventBridge schedules.

v2.0 (v3.4.0): CDK-managed IAM roles replace existing_role_arn references.
  All 7 Lambdas now have dedicated CDK-owned roles with least-privilege policies.
  DLQ managed normally for all Lambdas (no more shared-role SQS workaround).

Lambdas (8+):
  anomaly-detector          cron(5 15 * * ? *)    — 8:05 AM PT daily
  character-sheet-compute   cron(30 16 * * ? *)   — 9:30 AM PT daily (ADR-052)
  adaptive-mode-compute     cron(35 16 * * ? *)   — 9:35 AM PT daily (ADR-052)
  daily-metrics-compute     cron(40 16 * * ? *)   — 9:40 AM PT daily (ADR-052)
  daily-insight-compute     cron(45 16 * * ? *)   — 9:45 AM PT daily (ADR-052)
  hypothesis-engine         cron(0 19 ? * SUN *)  — Sunday 12:00 PM PT
  state-of-matthew          cron(30 19 ? * SUN *) — Sunday 12:30 PM PT (#552)
  weekly-correlation-compute cron(30 18 ? * SUN *) — Sunday 11:30 AM PT
  dashboard-refresh         cron(0 21 * * ? *)    — 2:00 PM PDT + 6:00 PM PDT
  challenge-generator       cron(0 22 ? * SUN *)  — Sunday 3:00 PM PT
  personal-baselines-compute cron(0 8 1 * ? *)    — 1st of month 08:00 UTC (#543, ADR-105 r4)

V2 P2.9 (2026-05-17): docstring corrected to match actual ADR-052 reordering
(was 17:35-17:50, now 16:30-16:45 to run BEFORE daily-brief at 17:00).
"""

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
from stacks.constants import ACCT, AI_MODEL_HAIKU, REGION, S3_BUCKET, SHARED_LAYER_ARN, TABLE_NAME  # CONF-01, CONF-04
from stacks.lambda_helpers import create_platform_lambda

INGESTION_DLQ_ARN = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
LIFE_PLATFORM_TABLE = TABLE_NAME
LIFE_PLATFORM_BUCKET = S3_BUCKET
ALERTS_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"
DIGEST_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts-digest"


class ComputeStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, table, bucket, dlq, alerts_topic, digest_topic=None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        local_dlq = sqs.Queue.from_queue_arn(self, "IngestionDLQ", INGESTION_DLQ_ARN)
        local_table = dynamodb.Table.from_table_name(self, "LifePlatformTable", LIFE_PLATFORM_TABLE)
        local_bucket = s3.Bucket.from_bucket_name(self, "LifePlatformBucket", LIFE_PLATFORM_BUCKET)
        local_alerts_topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)
        local_digest_topic = sns.Topic.from_topic_arn(self, "DigestTopic", DIGEST_TOPIC_ARN)
        # Phase B re-entry sweep (2026-05-03): attach the shared utils layer to all
        # Compute Lambdas. Previously these Lambdas were created without a layer
        # argument, so they pinned to whatever layer version they had at first
        # one-time deploy (v22 / v25 / v40 — way behind v42). Result: hypothesis-
        # engine + ai-expert-analyzer + others were missing the COST-OPT-2 prompt
        # caching benefit, the TD-20 platform_logger fix, etc.
        shared_utils_layer = _lambda.LayerVersion.from_layer_version_arn(
            self,
            "SharedUtilsLayer",
            SHARED_LAYER_ARN,
        )

        # ADR-050: every compute Lambda's error alarm routes to the digest topic.
        # Compute Lambdas are background pre-computation; transient errors recover
        # on the next scheduled run.
        shared = dict(
            table=local_table,
            bucket=local_bucket,
            dlq=local_dlq,
            alerts_topic=local_alerts_topic,
            digest_topic=local_digest_topic,
            digest=True,
            shared_layer=shared_utils_layer,
        )

        # ══════════════════════════════════════════════════════════════
        # Intelligence Lambdas (ADR-081) — adopted into CDK 2026-06-08.
        # ai-expert-analyzer, field-notes-generate + journal-analyzer were
        # CLI-created orphans (no IaC, no shared layer, no DLQ, no error alarm,
        # shared the daily-insight role). `cdk import` adopts the physical
        # functions; the first deploy converges them to the platform standard:
        # dedicated least-priv role, shared layer, DLQ, X-Ray, 30-day logs +
        # a digest error alarm — identical to their compute siblings.
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self,
            "AIExpertAnalyzer",
            function_name="ai-expert-analyzer",
            handler="intelligence.ai_expert_analyzer_lambda.lambda_handler",
            source_file="lambdas/intelligence/ai_expert_analyzer_lambda.py",
            schedule="cron(0 14 * * ? *)",  # 6:00 AM PT daily (Observatory weekly cadence is enforced in-handler)
            # 2026-06-17: 120s → 600s. The handler analyzes ~8 experts sequentially,
            # each a multi-second Bedrock call; 120s timed out mid-run (~15 errors/day),
            # so the async EventBridge events exhausted retries into the ingestion DLQ
            # (drove the dlq-messages + ingestion-error + dlq-depth alarms). Peers
            # (daily-brief, coaches) run at 900s; 600s gives ample headroom (mem fine
            # at 115/256MB — it needed TIME, not memory).
            timeout_seconds=600,
            memory_mb=256,
            environment={"AI_SECRET_NAME": "life-platform/ai-keys"},
            custom_policies=rp.intelligence_ai_expert(),
            **shared,
        )

        create_platform_lambda(
            self,
            "FieldNotesGenerate",
            function_name="field-notes-generate",
            handler="intelligence.field_notes_lambda.lambda_handler",
            source_file="lambdas/intelligence/field_notes_lambda.py",
            schedule="cron(0 18 ? * SUN *)",  # 11:00 AM PT Sundays
            timeout_seconds=120,
            memory_mb=256,
            custom_policies=rp.intelligence_field_notes(),
            **shared,
        )

        create_platform_lambda(
            self,
            "JournalAnalyzer",
            function_name="journal-analyzer",
            handler="intelligence.journal_analyzer_lambda.lambda_handler",
            source_file="lambdas/intelligence/journal_analyzer_lambda.py",
            schedule="cron(0 10 * * ? *)",  # 3:00 AM PT daily (nightly journal sweep)
            timeout_seconds=180,
            memory_mb=256,
            custom_policies=rp.intelligence_journal_analyzer(),
            **shared,
        )

        # CC-08: per-coach daily reflection batch. Runs at noon PT — AFTER the
        # daily brief (17:00 UTC) has written today's COACH#/OUTPUT# records.
        # Haiku, budget-tier>=2 self-skip, ER-03-gated, writes generated/coach_daily.json.
        create_platform_lambda(
            self,
            "CoachDailyReflection",
            function_name="coach-daily-reflection",
            handler="compute.coach_daily_reflection_lambda.lambda_handler",
            source_file="lambdas/compute/coach_daily_reflection_lambda.py",
            schedule="cron(0 19 * * ? *)",  # 19:00 UTC = 12:00 PM PT, after the daily brief
            timeout_seconds=180,
            memory_mb=256,
            custom_policies=rp.compute_coach_daily_reflection(),
            **shared,
        )

        # #553: quarterly in-voice coach memoirs. Runs on the 1st of each
        # calendar quarter (Jan/Apr/Jul/Oct) at 15:00 UTC — well after the
        # daily brief and the prior day's coach-prediction-evaluator have
        # written the quarter's final LEARNING#/STANCE# records.
        # Sonnet (narrative tier), budget-tier-1 self-pause via
        # budget_guard.allow("coach_narrative"), regen-once-per-quarter via a
        # MEMOIR#{quarter} DDB sentinel, writes generated/coach_memoirs.json.
        create_platform_lambda(
            self,
            "CoachMemoir",
            function_name="coach-memoir",
            handler="compute.coach_memoir_lambda.lambda_handler",
            source_file="lambdas/compute/coach_memoir_lambda.py",
            schedule="cron(0 15 1 1,4,7,10 ? *)",
            timeout_seconds=300,
            memory_mb=256,
            custom_policies=rp.compute_coach_memoir(),
            **shared,
        )

        create_platform_lambda(
            self,
            "AnomalyDetector",
            function_name="anomaly-detector",
            handler="emails.anomaly_detector_lambda.lambda_handler",
            source_file="lambdas/emails/anomaly_detector_lambda.py",
            schedule="cron(5 15 * * ? *)",
            timeout_seconds=90,
            memory_mb=256,
            custom_policies=rp.compute_anomaly_detector(),
            **shared,
        )

        create_platform_lambda(
            self,
            "CharacterSheetCompute",
            function_name="character-sheet-compute",
            handler="compute.character_sheet_lambda.lambda_handler",
            source_file="lambdas/compute/character_sheet_lambda.py",
            schedule="cron(30 16 * * ? *)",  # Phase 3.1 (2026-05-16): 17:35→16:30 (9:30 AM PT) so character_sheet completes BEFORE daily-brief at 17:00 UTC. Was reading yesterday's sheet.
            timeout_seconds=60,
            memory_mb=512,
            custom_policies=rp.compute_character_sheet(),
            **shared,
        )

        daily_metrics_fn = create_platform_lambda(
            self,
            "DailyMetricsCompute",
            function_name="daily-metrics-compute",
            handler="compute.daily_metrics_compute_lambda.lambda_handler",
            source_file="lambdas/compute/daily_metrics_compute_lambda.py",
            schedule="cron(40 16 * * ? *)",  # Phase 3.1 (2026-05-16): 17:40→16:40 (9:40 AM PT) so daily-metrics completes BEFORE daily-brief.
            timeout_seconds=120,
            memory_mb=512,
            custom_policies=rp.compute_daily_metrics(),
            **shared,
        )

        # #541: forecast engine — deterministic EWMA next-day/next-7-day expectations
        # with 80% intervals (stats_core, no AI). Runs at 16:50 UTC: after daily-metrics
        # (16:40) so the same morning's actuals are in, before the 17:00 daily-brief lane
        # so coaches narrate TODAY's expectation. Resolutions grade into the CROSS_PHASE
        # calibration ledger.
        create_platform_lambda(
            self,
            "ForecastEngine",
            function_name="forecast-engine",
            handler="compute.forecast_engine_lambda.lambda_handler",
            source_file="lambdas/compute/forecast_engine_lambda.py",
            schedule="cron(50 16 * * ? *)",  # 9:50 AM PT daily (fixed UTC, no DST drift)
            timeout_seconds=120,
            memory_mb=512,
            custom_policies=rp.compute_forecast_engine(),
            **shared,
        )

        # #550: scenario explorer — nightly what-followed conditional distributions
        # (stats_core matching + block-bootstrap CIs, effective-n gate). Pure Python,
        # no AI. 12:10 UTC (~5:10 AM PT): after the overnight ingest, hours before
        # anyone reads /method/scenarios/.
        create_platform_lambda(
            self,
            "ScenarioExplorer",
            function_name="scenario-explorer",
            handler="compute.scenario_explorer_lambda.lambda_handler",
            source_file="lambdas/compute/scenario_explorer_lambda.py",
            schedule="cron(10 12 * * ? *)",  # fixed UTC, no DST drift
            timeout_seconds=120,
            memory_mb=512,
            custom_policies=rp.compute_scenario_explorer(),
            **shared,
        )

        # #109 (2026-05-30): second daily run at 5 PM PT (00:00 UTC) so
        # workouts logged after the 9:40 AM PT compute (e.g. Hevy sessions
        # logged mid-morning) surface on averagejoematt.com + coach insights
        # the same day instead of waiting for tomorrow's run. Event-driven
        # recompute is the proper fix (Option A), but this twice-daily
        # schedule covers ~90% of late-arrival cases at a single CDK line.
        events.Rule(
            self,
            "DailyMetricsComputeEvening",
            schedule=events.Schedule.expression("cron(0 0 * * ? *)"),
        ).add_target(targets.LambdaFunction(daily_metrics_fn))

        # BENCH-1.2: episode-detect — weekly cut/regain benchmarking (Viktor's
        # weekly-not-nightly cadence). Reads full withings/strava/hevy history, writes
        # weight_episodes + training_reference. Sun 17:00 UTC (~10 AM PT). Manual-invoke
        # supported for the one-time backfill. Pure-Python algorithm, no Bedrock.
        create_platform_lambda(
            self,
            "EpisodeDetect",
            function_name="episode-detect",
            handler="compute.episode_detect_lambda.lambda_handler",
            source_file="lambdas/compute/episode_detect_lambda.py",
            schedule="cron(0 17 ? * SUN *)",  # weekly, Sunday ~10:00 AM PT (fixed UTC, no DST drift)
            timeout_seconds=120,
            memory_mb=512,
            custom_policies=rp.compute_episode_detect(),
            **shared,
        )

        create_platform_lambda(
            self,
            "DailyInsightCompute",
            function_name="daily-insight-compute",
            handler="compute.daily_insight_compute_lambda.lambda_handler",
            source_file="lambdas/compute/daily_insight_compute_lambda.py",
            schedule="cron(45 16 * * ? *)",  # Phase 3.1 (2026-05-16): 17:45→16:45 (9:45 AM PT) so daily-insight completes BEFORE daily-brief.
            timeout_seconds=120,
            memory_mb=512,
            custom_policies=rp.compute_daily_insight(),
            **shared,
        )

        create_platform_lambda(
            self,
            "AdaptiveModeCompute",
            function_name="adaptive-mode-compute",
            handler="compute.adaptive_mode_lambda.lambda_handler",
            source_file="lambdas/compute/adaptive_mode_lambda.py",
            schedule="cron(35 16 * * ? *)",  # Phase 3.1 (2026-05-16): 17:50→16:35 (9:35 AM PT) so adaptive-mode completes BEFORE daily-brief.
            timeout_seconds=120,
            memory_mb=256,
            custom_policies=rp.compute_adaptive_mode(),
            **shared,
        )

        create_platform_lambda(
            self,
            "HypothesisEngine",
            function_name="hypothesis-engine",
            handler="compute.hypothesis_engine_lambda.lambda_handler",
            source_file="lambdas/compute/hypothesis_engine_lambda.py",
            schedule="cron(0 19 ? * SUN *)",
            timeout_seconds=120,
            memory_mb=256,
            custom_policies=rp.compute_hypothesis_engine(),
            **shared,
        )

        # #552: "State of Matthew" weekly model brief — deterministic assembly of
        # the forecast engine + hypothesis engine + coach consensus + calibration
        # scoreboard into one narrated brief (ONE Haiku call/week, ADR-104 gated).
        # Sunday 19:30 UTC (12:30 PM PT): 30 min after hypothesis-engine (19:00 UTC)
        # so this week's fresh checks/resolutions are in before the brief reads them.
        create_platform_lambda(
            self,
            "StateOfMatthew",
            function_name="state-of-matthew",
            handler="compute.state_of_matthew_lambda.lambda_handler",
            source_file="lambdas/compute/state_of_matthew_lambda.py",
            schedule="cron(30 19 ? * SUN *)",
            timeout_seconds=60,
            memory_mb=256,
            custom_policies=rp.compute_state_of_matthew(),
            **shared,
        )

        create_platform_lambda(
            self,
            "WeeklyCorrelationCompute",
            function_name="weekly-correlation-compute",
            handler="compute.weekly_correlation_compute_lambda.lambda_handler",
            source_file="lambdas/compute/weekly_correlation_compute_lambda.py",
            schedule="cron(30 18 ? * SUN *)",  # Sunday 11:30 AM PT (30 min before hypothesis engine)
            timeout_seconds=120,
            memory_mb=256,
            custom_policies=rp.compute_weekly_correlations(),
            **shared,
        )

        dashboard = create_platform_lambda(
            self,
            "DashboardRefresh",
            function_name="dashboard-refresh",
            handler="compute.dashboard_refresh_lambda.lambda_handler",
            source_file="lambdas/compute/dashboard_refresh_lambda.py",
            schedule="cron(0 21 * * ? *)",
            timeout_seconds=60,
            memory_mb=256,
            custom_policies=rp.compute_dashboard_refresh(),
            **shared,
        )

        evening_rule = events.Rule(
            self,
            "DashboardRefreshEveningRule",
            schedule=events.Schedule.expression("cron(0 1 * * ? *)"),
            description="Dashboard refresh — 6:00 PM PDT",
        )
        evening_rule.add_target(targets.LambdaFunction(dashboard))

        # ══════════════════════════════════════════════════════════════
        # 8. failure-pattern-compute — Sunday 9:50 AM PT (previously unmanaged)
        # ══════════════════════════════════════════════════════════════
        # ══════════════════════════════════════════════════════════════
        # 9. acwr-compute — BS-09 (9:55 AM PT — after adaptive-mode, before brief)
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self,
            "ACWRCompute",
            function_name="acwr-compute",
            handler="compute.acwr_compute_lambda.lambda_handler",
            source_file="lambdas/compute/acwr_compute_lambda.py",
            schedule="cron(55 16 * * ? *)",
            timeout_seconds=60,
            memory_mb=256,
            custom_policies=rp.compute_acwr(),
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # 9b. personal-baselines — #543 (ADR-105 rule 4): monthly percentile
        #     bands from Matthew's OWN distribution replace hand-set cutoffs.
        #     Monthly cadence (slow-moving distribution); fixed UTC, no DST drift.
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self,
            "PersonalBaselinesCompute",
            function_name="personal-baselines-compute",
            handler="compute.personal_baselines_lambda.lambda_handler",
            source_file="lambdas/compute/personal_baselines_lambda.py",
            schedule="cron(0 8 1 * ? *)",  # 1st of every month, 08:00 UTC (fixed UTC, no DST drift)
            timeout_seconds=120,
            memory_mb=256,
            custom_policies=rp.compute_personal_baselines(),
            **shared,
        )

        # 10. sleep-reconciler — RETIRED 2026-07-05 (#487 / ADR-113). The unified-sleep
        #     per-field merge read record fields that never existed (it stored the Whoop record
        #     plus one Eight Sleep score, not the promised best-source-per-field merge) and ran
        #     1–2 nights stale, mislabelling the public /data/sleep "night of" header. Zero
        #     compute consumers; /api/sleep_detail already carries the same figures, fresher.

        # ══════════════════════════════════════════════════════════════
        # 11. circadian-compliance — BS-SL2 (7:00 PM PT — evening nudge window)
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self,
            "CircadianCompliance",
            function_name="circadian-compliance",
            handler="compute.circadian_compliance_lambda.lambda_handler",
            source_file="lambdas/compute/circadian_compliance_lambda.py",
            schedule="cron(0 2 * * ? *)",  # 7:00 PM PT daily (02:00 UTC)
            timeout_seconds=60,
            memory_mb=256,
            custom_policies=rp.compute_circadian_compliance(),
            **shared,
        )

        create_platform_lambda(
            self,
            "FailurePatternCompute",
            function_name="failure-pattern-compute",
            handler="compute.failure_pattern_compute_lambda.lambda_handler",
            source_file="lambdas/compute/failure_pattern_compute_lambda.py",
            schedule="cron(50 17 ? * SUN *)",
            timeout_seconds=300,
            memory_mb=256,
            environment={
                "ANTHROPIC_SECRET": "life-platform/ai-keys",
                "AI_MODEL_HAIKU": AI_MODEL_HAIKU,
            },
            custom_policies=rp.compute_failure_pattern(),
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # Challenge Generator — AI-powered weekly challenge pipeline
        # Runs Sunday 3 PM PT (after hypothesis engine + weekly correlations)
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self,
            "ChallengeGenerator",
            function_name="challenge-generator",
            handler="intelligence.challenge_generator_lambda.lambda_handler",
            source_file="lambdas/intelligence/challenge_generator_lambda.py",
            schedule="cron(0 22 ? * SUN *)",  # Sunday 3:00 PM PT (22:00 UTC)
            timeout_seconds=120,
            memory_mb=512,
            environment={
                "ANTHROPIC_SECRET": "life-platform/ai-keys",
            },
            custom_policies=rp.compute_challenge_generator(),
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # Coach Intelligence Architecture — Phase 1+2
        # No schedule — invoked by daily-brief pipeline
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self,
            "CoachComputationEngine",
            function_name="coach-computation-engine",
            handler="coach.coach_computation_engine.lambda_handler",
            source_file="lambdas/coach/coach_computation_engine.py",
            timeout_seconds=60,
            memory_mb=256,
            custom_policies=rp.compute_coach_computation(),
            **shared,
        )

        create_platform_lambda(
            self,
            "CoachNarrativeOrchestrator",
            function_name="coach-narrative-orchestrator",
            handler="coach.coach_narrative_orchestrator.lambda_handler",
            source_file="lambdas/coach/coach_narrative_orchestrator.py",
            timeout_seconds=90,
            memory_mb=256,
            environment={
                "ANTHROPIC_SECRET": "life-platform/ai-keys",
                "AI_MODEL_HAIKU": AI_MODEL_HAIKU,
            },
            custom_policies=rp.compute_coach_orchestrator(),
            **shared,
        )

        create_platform_lambda(
            self,
            "CoachStateUpdater",
            function_name="coach-state-updater",
            handler="coach.coach_state_updater.lambda_handler",
            source_file="lambdas/coach/coach_state_updater.py",
            timeout_seconds=60,
            memory_mb=256,
            environment={
                "ANTHROPIC_SECRET": "life-platform/ai-keys",
                "AI_MODEL_HAIKU": AI_MODEL_HAIKU,
            },
            custom_policies=rp.compute_coach_state_updater(),
            **shared,
        )

        create_platform_lambda(
            self,
            "CoachEnsembleDigest",
            function_name="coach-ensemble-digest",
            handler="coach.coach_ensemble_digest.lambda_handler",
            source_file="lambdas/coach/coach_ensemble_digest.py",
            timeout_seconds=90,
            memory_mb=256,
            environment={
                "ANTHROPIC_SECRET": "life-platform/ai-keys",
                "AI_MODEL_HAIKU": AI_MODEL_HAIKU,
            },
            custom_policies=rp.compute_coach_orchestrator(),  # same permissions as orchestrator
            **shared,
        )

        # #540: real inter-coach dialogue — the week's most persistent ensemble
        # disagreement gets two gated in-voice Haiku turns, persisted as an
        # ENSEMBLE#dispute thread. Sunday 18:00 UTC — after the history summarizer
        # (17:00) so the week's disagreement ledger is settled. Tier>=1 self-pauses.
        create_platform_lambda(
            self,
            "InterCoachDialogue",
            function_name="inter-coach-dialogue",
            handler="coach.inter_coach_dialogue_lambda.lambda_handler",
            source_file="lambdas/coach/inter_coach_dialogue_lambda.py",
            schedule="cron(0 18 ? * SUN *)",  # Sunday 11:00 AM PT (fixed UTC)
            timeout_seconds=300,
            memory_mb=256,
            environment={"AI_MODEL_HAIKU": AI_MODEL_HAIKU},
            custom_policies=rp.compute_coach_orchestrator(),
            **shared,
        )

        # #545: the blind voice-fidelity harness — monthly, samples each coach's own
        # real recent OUTPUT# text, blinds it, and runs a 3-judge Haiku panel that
        # guesses authorship. Confusion matrix + per-coach distinguishability persist
        # cumulatively at VOICEFIDELITY#scoreboard/latest (public via /api/voice_fidelity
        # -> /method/voice-fidelity/). At most 8 coaches x 2 samples x 3-judge panel =
        # 48 Haiku calls/month. 1st of the month, 15:00 UTC (8 AM PT, fixed UTC).
        # Tier>=1 self-pauses (a monthly luxury metric, same cutoff as the dispute above).
        create_platform_lambda(
            self,
            "VoiceFidelityHarness",
            function_name="voice-fidelity-harness",
            handler="coach.voice_fidelity_harness.lambda_handler",
            source_file="lambdas/coach/voice_fidelity_harness.py",
            schedule="cron(0 15 1 * ? *)",
            timeout_seconds=600,
            memory_mb=256,
            environment={
                "ANTHROPIC_SECRET": "life-platform/ai-keys",
                "AI_MODEL_HAIKU": AI_MODEL_HAIKU,
            },
            custom_policies=rp.compute_voice_fidelity_harness(),
            **shared,
        )

        create_platform_lambda(
            self,
            "CoachHistorySummarizer",
            function_name="coach-history-summarizer",
            handler="coach.coach_history_summarizer.lambda_handler",
            source_file="lambdas/coach/coach_history_summarizer.py",
            schedule="cron(0 17 ? * SUN *)",  # Sunday 10:00 AM PT (before weekly digest)
            # 120s was too tight for the Haiku history-summarization call — the Sunday
            # run timed out and dumped its scheduled event into the ingestion DLQ
            # (reddening the I9 post-deploy check). 600s matches the ai-expert-analyzer
            # precedent for AI-calling scheduled Lambdas; Lambda hard max is 900s.
            timeout_seconds=600,
            memory_mb=256,
            environment={
                "ANTHROPIC_SECRET": "life-platform/ai-keys",
                "AI_MODEL_HAIKU": AI_MODEL_HAIKU,
            },
            custom_policies=rp.compute_coach_orchestrator(),
            **shared,
        )

        create_platform_lambda(
            self,
            "CoachQualityGate",
            function_name="coach-quality-gate",
            handler="coach.coach_quality_gate.lambda_handler",
            source_file="lambdas/coach/coach_quality_gate.py",
            timeout_seconds=30,
            memory_mb=256,
            environment={
                "ANTHROPIC_SECRET": "life-platform/ai-keys",
                "AI_MODEL_HAIKU": AI_MODEL_HAIKU,
            },
            custom_policies=rp.compute_coach_state_updater(),
            **shared,
        )

        create_platform_lambda(
            self,
            "CoachObservatoryRenderer",
            function_name="coach-observatory-renderer",
            handler="coach.coach_observatory_renderer.lambda_handler",
            source_file="lambdas/coach/coach_observatory_renderer.py",
            timeout_seconds=30,
            memory_mb=256,
            custom_policies=rp.compute_coach_computation(),  # read-only DDB + S3
            **shared,
        )

        create_platform_lambda(
            self,
            "CoachPredictionEvaluator",
            function_name="coach-prediction-evaluator",
            handler="coach.coach_prediction_evaluator.lambda_handler",
            source_file="lambdas/coach/coach_prediction_evaluator.py",
            schedule="cron(0 16 * * ? *)",  # 9:00 AM PT daily (before daily brief at 11 AM)
            # 60s -> 90s (#534): the event-driven stance-refresh detection tacked onto
            # the end of this run adds a handful of extra GetItem/Query reads (sick
            # day, habit_scores, weight) plus up to 2 fire-and-forget async Lambda
            # invokes — cheap, but not free inside the old 60s budget on a slow day.
            timeout_seconds=90,
            memory_mb=256,
            # #534: dedicated policy (was compute_coach_computation()) — adds
            # budget-tier read + a scoped InvokeFunction on coach-history-summarizer
            # for the mid-week stance-refresh trigger; see role_policies.py.
            custom_policies=rp.compute_coach_prediction_evaluator(),
            **shared,
        )
