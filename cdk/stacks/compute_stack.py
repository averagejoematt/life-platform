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
  weekly-correlation-compute cron(30 18 ? * SUN *) — Sunday 11:30 AM PT
  dashboard-refresh         cron(0 21 * * ? *)    — 2:00 PM PDT + 6:00 PM PDT
  challenge-generator       cron(0 22 ? * SUN *)  — Sunday 3:00 PM PT

V2 P2.9 (2026-05-17): docstring corrected to match actual ADR-052 reordering
(was 17:35-17:50, now 16:30-16:45 to run BEFORE daily-brief at 17:00).
"""

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_sqs as sqs,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_sns as sns,
    aws_events as events,
    aws_events_targets as targets,
)
from constructs import Construct

from stacks.lambda_helpers import create_platform_lambda
from stacks import role_policies as rp
from stacks.constants import ACCT, REGION, TABLE_NAME, S3_BUCKET, AI_MODEL_HAIKU, SHARED_LAYER_ARN  # CONF-01, CONF-04

INGESTION_DLQ_ARN    = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
LIFE_PLATFORM_TABLE  = TABLE_NAME
LIFE_PLATFORM_BUCKET = S3_BUCKET
ALERTS_TOPIC_ARN     = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"
DIGEST_TOPIC_ARN     = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts-digest"


class ComputeStack(Stack):

    def __init__(self, scope: Construct, construct_id: str,
                 table, bucket, dlq, alerts_topic, digest_topic=None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        local_dlq          = sqs.Queue.from_queue_arn(self, "IngestionDLQ", INGESTION_DLQ_ARN)
        local_table        = dynamodb.Table.from_table_name(self, "LifePlatformTable", LIFE_PLATFORM_TABLE)
        local_bucket       = s3.Bucket.from_bucket_name(self, "LifePlatformBucket", LIFE_PLATFORM_BUCKET)
        local_alerts_topic = sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)
        local_digest_topic = sns.Topic.from_topic_arn(self, "DigestTopic", DIGEST_TOPIC_ARN)
        # Phase B re-entry sweep (2026-05-03): attach the shared utils layer to all
        # Compute Lambdas. Previously these Lambdas were created without a layer
        # argument, so they pinned to whatever layer version they had at first
        # one-time deploy (v22 / v25 / v40 — way behind v42). Result: hypothesis-
        # engine + ai-expert-analyzer + others were missing the COST-OPT-2 prompt
        # caching benefit, the TD-20 platform_logger fix, etc.
        shared_utils_layer = _lambda.LayerVersion.from_layer_version_arn(
            self, "SharedUtilsLayer", SHARED_LAYER_ARN,
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

        # Observatory Intelligence (ai-expert-analyzer) — manually deployed Lambda
        # Cannot import to CDK (already exists). Layer updates via deploy script:
        #   LATEST=$(aws lambda list-layer-versions --layer-name life-platform-shared-utils --query 'LayerVersions[0].Version' --output text)
        #   aws lambda update-function-configuration --function-name ai-expert-analyzer --layers "arn:aws:lambda:us-west-2:205930651321:layer:life-platform-shared-utils:${LATEST}"

        create_platform_lambda(
            self, "AnomalyDetector",
            function_name="anomaly-detector",
            handler="email.anomaly_detector_lambda.lambda_handler",
            source_file="lambdas/email/anomaly_detector_lambda.py",
            schedule="cron(5 15 * * ? *)",
            timeout_seconds=90, memory_mb=256,
            custom_policies=rp.compute_anomaly_detector(),
            **shared,
        )

        create_platform_lambda(
            self, "CharacterSheetCompute",
            function_name="character-sheet-compute",
            handler="compute.character_sheet_lambda.lambda_handler",
            source_file="lambdas/compute/character_sheet_lambda.py",
            schedule="cron(30 16 * * ? *)",  # Phase 3.1 (2026-05-16): 17:35→16:30 (9:30 AM PT) so character_sheet completes BEFORE daily-brief at 17:00 UTC. Was reading yesterday's sheet.
            timeout_seconds=60, memory_mb=512,
            custom_policies=rp.compute_character_sheet(),
            **shared,
        )

        create_platform_lambda(
            self, "DailyMetricsCompute",
            function_name="daily-metrics-compute",
            handler="compute.daily_metrics_compute_lambda.lambda_handler",
            source_file="lambdas/compute/daily_metrics_compute_lambda.py",
            schedule="cron(40 16 * * ? *)",  # Phase 3.1 (2026-05-16): 17:40→16:40 (9:40 AM PT) so daily-metrics completes BEFORE daily-brief.
            timeout_seconds=120, memory_mb=512,
            custom_policies=rp.compute_daily_metrics(),
            **shared,
        )

        create_platform_lambda(
            self, "DailyInsightCompute",
            function_name="daily-insight-compute",
            handler="compute.daily_insight_compute_lambda.lambda_handler",
            source_file="lambdas/compute/daily_insight_compute_lambda.py",
            schedule="cron(45 16 * * ? *)",  # Phase 3.1 (2026-05-16): 17:45→16:45 (9:45 AM PT) so daily-insight completes BEFORE daily-brief.
            timeout_seconds=120, memory_mb=512,
            custom_policies=rp.compute_daily_insight(),
            **shared,
        )

        create_platform_lambda(
            self, "AdaptiveModeCompute",
            function_name="adaptive-mode-compute",
            handler="compute.adaptive_mode_lambda.lambda_handler",
            source_file="lambdas/compute/adaptive_mode_lambda.py",
            schedule="cron(35 16 * * ? *)",  # Phase 3.1 (2026-05-16): 17:50→16:35 (9:35 AM PT) so adaptive-mode completes BEFORE daily-brief.
            timeout_seconds=120, memory_mb=256,
            custom_policies=rp.compute_adaptive_mode(),
            **shared,
        )

        create_platform_lambda(
            self, "HypothesisEngine",
            function_name="hypothesis-engine",
            handler="compute.hypothesis_engine_lambda.lambda_handler",
            source_file="lambdas/compute/hypothesis_engine_lambda.py",
            schedule="cron(0 19 ? * SUN *)",
            timeout_seconds=120, memory_mb=256,
            custom_policies=rp.compute_hypothesis_engine(),
            **shared,
        )

        create_platform_lambda(
            self, "WeeklyCorrelationCompute",
            function_name="weekly-correlation-compute",
            handler="compute.weekly_correlation_compute_lambda.lambda_handler",
            source_file="lambdas/compute/weekly_correlation_compute_lambda.py",
            schedule="cron(30 18 ? * SUN *)",  # Sunday 11:30 AM PT (30 min before hypothesis engine)
            timeout_seconds=120, memory_mb=256,
            custom_policies=rp.compute_weekly_correlations(),
            **shared,
        )

        dashboard = create_platform_lambda(
            self, "DashboardRefresh",
            function_name="dashboard-refresh",
            handler="compute.dashboard_refresh_lambda.lambda_handler",
            source_file="lambdas/compute/dashboard_refresh_lambda.py",
            schedule="cron(0 21 * * ? *)",
            timeout_seconds=60, memory_mb=256,
            custom_policies=rp.compute_dashboard_refresh(),
            **shared,
        )

        evening_rule = events.Rule(
            self, "DashboardRefreshEveningRule",
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
            self, "ACWRCompute",
            function_name="acwr-compute",
            handler="compute.acwr_compute_lambda.lambda_handler",
            source_file="lambdas/compute/acwr_compute_lambda.py",
            schedule="cron(55 16 * * ? *)",
            timeout_seconds=60, memory_mb=256,
            custom_policies=rp.compute_acwr(),
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # 10. sleep-reconciler — BS-08 (7:00 AM PT — after ingestion, before daily brief)
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "SleepReconciler",
            function_name="sleep-reconciler",
            handler="compute.sleep_reconciler_lambda.lambda_handler",
            source_file="lambdas/compute/sleep_reconciler_lambda.py",
            schedule="cron(0 14 * * ? *)",  # 7:00 AM PT daily
            timeout_seconds=60, memory_mb=256,
            custom_policies=rp.compute_sleep_reconciler(),
            **shared,
        )

        # ══════════════════════════════════════════════════════════════
        # 11. circadian-compliance — BS-SL2 (7:00 PM PT — evening nudge window)
        # ══════════════════════════════════════════════════════════════
        create_platform_lambda(
            self, "CircadianCompliance",
            function_name="circadian-compliance",
            handler="compute.circadian_compliance_lambda.lambda_handler",
            source_file="lambdas/compute/circadian_compliance_lambda.py",
            schedule="cron(0 2 * * ? *)",  # 7:00 PM PT daily (02:00 UTC)
            timeout_seconds=60, memory_mb=256,
            custom_policies=rp.compute_circadian_compliance(),
            **shared,
        )

        create_platform_lambda(
            self, "FailurePatternCompute",
            function_name="failure-pattern-compute",
            handler="compute.failure_pattern_compute_lambda.lambda_handler",
            source_file="lambdas/compute/failure_pattern_compute_lambda.py",
            schedule="cron(50 17 ? * SUN *)",
            timeout_seconds=300, memory_mb=256,
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
            self, "ChallengeGenerator",
            function_name="challenge-generator",
            handler="intelligence.challenge_generator_lambda.lambda_handler",
            source_file="lambdas/intelligence/challenge_generator_lambda.py",
            schedule="cron(0 22 ? * SUN *)",  # Sunday 3:00 PM PT (22:00 UTC)
            timeout_seconds=120, memory_mb=512,
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
            self, "CoachComputationEngine",
            function_name="coach-computation-engine",
            handler="coach.coach_computation_engine.lambda_handler",
            source_file="lambdas/coach/coach_computation_engine.py",
            timeout_seconds=60, memory_mb=256,
            custom_policies=rp.compute_coach_computation(),
            **shared,
        )

        create_platform_lambda(
            self, "CoachNarrativeOrchestrator",
            function_name="coach-narrative-orchestrator",
            handler="coach.coach_narrative_orchestrator.lambda_handler",
            source_file="lambdas/coach/coach_narrative_orchestrator.py",
            timeout_seconds=90, memory_mb=256,
            environment={
                "ANTHROPIC_SECRET": "life-platform/ai-keys",
                "AI_MODEL_HAIKU": AI_MODEL_HAIKU,
            },
            custom_policies=rp.compute_coach_orchestrator(),
            **shared,
        )

        create_platform_lambda(
            self, "CoachStateUpdater",
            function_name="coach-state-updater",
            handler="coach.coach_state_updater.lambda_handler",
            source_file="lambdas/coach/coach_state_updater.py",
            timeout_seconds=60, memory_mb=256,
            environment={
                "ANTHROPIC_SECRET": "life-platform/ai-keys",
                "AI_MODEL_HAIKU": AI_MODEL_HAIKU,
            },
            custom_policies=rp.compute_coach_state_updater(),
            **shared,
        )

        create_platform_lambda(
            self, "CoachEnsembleDigest",
            function_name="coach-ensemble-digest",
            handler="coach.coach_ensemble_digest.lambda_handler",
            source_file="lambdas/coach/coach_ensemble_digest.py",
            timeout_seconds=90, memory_mb=256,
            environment={
                "ANTHROPIC_SECRET": "life-platform/ai-keys",
                "AI_MODEL_HAIKU": AI_MODEL_HAIKU,
            },
            custom_policies=rp.compute_coach_orchestrator(),  # same permissions as orchestrator
            **shared,
        )

        create_platform_lambda(
            self, "CoachHistorySummarizer",
            function_name="coach-history-summarizer",
            handler="coach.coach_history_summarizer.lambda_handler",
            source_file="lambdas/coach/coach_history_summarizer.py",
            schedule="cron(0 17 ? * SUN *)",  # Sunday 10:00 AM PT (before weekly digest)
            timeout_seconds=120, memory_mb=256,
            environment={
                "ANTHROPIC_SECRET": "life-platform/ai-keys",
                "AI_MODEL_HAIKU": AI_MODEL_HAIKU,
            },
            custom_policies=rp.compute_coach_orchestrator(),
            **shared,
        )

        create_platform_lambda(
            self, "CoachQualityGate",
            function_name="coach-quality-gate",
            handler="coach.coach_quality_gate.lambda_handler",
            source_file="lambdas/coach/coach_quality_gate.py",
            timeout_seconds=30, memory_mb=256,
            environment={
                "ANTHROPIC_SECRET": "life-platform/ai-keys",
                "AI_MODEL_HAIKU": AI_MODEL_HAIKU,
            },
            custom_policies=rp.compute_coach_state_updater(),
            **shared,
        )

        create_platform_lambda(
            self, "CoachObservatoryRenderer",
            function_name="coach-observatory-renderer",
            handler="coach.coach_observatory_renderer.lambda_handler",
            source_file="lambdas/coach/coach_observatory_renderer.py",
            timeout_seconds=30, memory_mb=256,
            custom_policies=rp.compute_coach_computation(),  # read-only DDB + S3
            **shared,
        )

        create_platform_lambda(
            self, "CoachPredictionEvaluator",
            function_name="coach-prediction-evaluator",
            handler="coach.coach_prediction_evaluator.lambda_handler",
            source_file="lambdas/coach/coach_prediction_evaluator.py",
            schedule="cron(0 16 * * ? *)",  # 9:00 AM PT daily (before daily brief at 11 AM)
            timeout_seconds=60, memory_mb=256,
            custom_policies=rp.compute_coach_computation(),  # same permissions as computation engine
            **shared,
        )
