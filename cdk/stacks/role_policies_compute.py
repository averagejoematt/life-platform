"""role_policies_compute.py — Compute- and intelligence-stack IAM policies (#2604 extraction).

Holds `_compute_base()`, every `compute_*()` and the three `intelligence_*()`
roles. Re-exported by `role_policies.py`.

Why a sibling and not another block in `role_policies.py`: that module sat AT its
recorded ceiling in `tests/test_module_size_guard.py` (3,291 of 3,291 lines), and that
registry is a shrink-only ratchet — the sanctioned way to add policy is a cohesive
module beside it, never a raised number (#1400 set the precedent with
`role_policies_permanence.py`; #2604 generalised it to the whole file).
"""

from aws_cdk import aws_iam as iam

from stacks.role_policies_base import (
    ACCT,
    DLQ_ARN,
    KMS_KEY_ARN,
    REGION,
    SES_CONFIG_SET_ARN,
    SES_IDENTITY,
    TABLE_ARN,
    _bedrock_statement,
    _s3,
    _secret_arn,
)

# ═══════════════════════════════════════════════════════════════════════════
# COMPUTE STACK — 7 Lambdas
# ═══════════════════════════════════════════════════════════════════════════


def _compute_base(
    needs_s3_config: bool = False,
    needs_s3_write: list[str] = None,
    needs_ai_keys: bool = False,
    needs_kms: bool = False,
    needs_ses: bool = False,
    extra_statements: list[iam.PolicyStatement] = None,
) -> list[iam.PolicyStatement]:
    """Build standard compute role policies."""
    stmts = [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:BatchGetItem"],
            resources=[TABLE_ARN, f"{TABLE_ARN}/index/*"],
        ),
    ]
    if needs_kms:
        # Phase 2.4: include S3 CMK too — most compute Lambdas read S3 config
        # and some write to S3, all of which now go through the CMK by default.
        stmts.append(
            iam.PolicyStatement(
                sid="KMS",
                actions=["kms:Decrypt", "kms:GenerateDataKey"],
                resources=[KMS_KEY_ARN],
            )
        )
    if needs_s3_config:
        stmts.append(
            iam.PolicyStatement(
                sid="S3ConfigRead",
                actions=["s3:GetObject"],
                resources=_s3("config/*"),
            )
        )
    if needs_s3_write:
        stmts.append(
            iam.PolicyStatement(
                sid="S3Write",
                actions=["s3:PutObject"],
                resources=_s3(*needs_s3_write),
            )
        )
    if needs_ai_keys:
        stmts.append(
            iam.PolicyStatement(
                sid="Secrets",
                actions=["secretsmanager:GetSecretValue"],
                resources=[_secret_arn("life-platform/ai-keys")],
            )
        )
        # ADR-062: needs_ai_keys marks AI-calling roles → also grant Bedrock.
        # (ai-keys secret kept for now; vestigial post-migration since Bedrock
        # uses IAM auth, but harmless and eases rollback.)
        stmts.append(_bedrock_statement())
        # G1 (PR #142): bedrock_client.invoke() now emits per-feature token +
        # EstimatedCostUSD metrics at the single chokepoint, so EVERY AI-calling
        # role needs PutMetricData. Without it the emit fails AccessDenied (fail-
        # open → log spam) and the cost telemetry is silently dropped for that
        # feature — observed on ai-expert-analyzer. PutMetricData only accepts "*".
        stmts.append(
            iam.PolicyStatement(
                sid="AICostMetrics",
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
            )
        )
    if needs_ses:
        stmts.append(
            iam.PolicyStatement(
                sid="SES",
                actions=["ses:SendEmail", "sesv2:SendEmail"],
                resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
            )
        )
    stmts.append(
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        )
    )
    if extra_statements:
        stmts.extend(extra_statements)
    return stmts


def compute_anomaly_detector() -> list[iam.PolicyStatement]:
    """Anomaly detector reads DDB + S3 config, sends SES alerts, uses ai-keys."""
    return _compute_base(
        needs_kms=True,  # reads CMK-encrypted DDB table
        needs_s3_config=True,
        needs_ai_keys=True,
        needs_ses=True,
    )


def compute_character_sheet() -> list[iam.PolicyStatement]:
    """Character sheet: DDB read+write, KMS, S3 config read, ai-keys, S3 site/ write.
    site/character_stats.json written via site_writer.py for averagejoematt.com.
    """
    return _compute_base(
        needs_kms=True,
        needs_s3_config=True,
        needs_ai_keys=True,
        needs_s3_write=["site/*", "generated/*"],
    )


def compute_daily_metrics() -> list[iam.PolicyStatement]:
    """Daily metrics: DDB read+write, KMS.

    #1858: + ssm:GetParameter on experiment-cycle — phase_taxonomy.experiment_stamp()
    (ADR-077 write-time provenance on this Lambda's EXPERIMENT_SCOPED writes) calls
    coach_checkin.read_cycle(), which was un-granted here and fail-softing to no
    cycle stamp (AccessDeniedException, caught and logged, never blocking the write).
    """
    return _compute_base(
        needs_kms=True,
        extra_statements=[
            iam.PolicyStatement(
                sid="ExperimentCycleRead",
                actions=["ssm:GetParameter"],
                resources=[f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/experiment-cycle"],
            ),
        ],
    )


def compute_scenario_explorer() -> list[iam.PolicyStatement]:
    """#550 scenario explorer: DDB read (9 source partitions via the hypothesis
    engine's gather) + write (SOURCE#scenarios), KMS. Pure Python — no AI."""
    return _compute_base(needs_kms=True)


def compute_forecast_engine() -> list[iam.PolicyStatement]:
    """#541 forecast engine: DDB read (whoop/withings history + own partition) + write
    (SOURCE#forecast rows + CROSS_PHASE calibration resolutions), KMS. Pure Python — no AI."""
    return _compute_base(needs_kms=True)


def compute_episode_detect() -> list[iam.PolicyStatement]:
    """BENCH-1: episode-detect — DDB read (withings/strava/hevy full history) + write
    (weight_episodes / training_reference computed sources), KMS. No AI, no S3."""
    return _compute_base(needs_kms=True)


def compute_coach_daily_reflection() -> list[iam.PolicyStatement]:
    """CC-08 daily reflection batch: reads COACH#/OUTPUT# + S3 voice specs, uses
    Bedrock (Haiku) for ≤120-word reflections, writes generated/coach_daily.json.
    Budget-tier SSM read is granted to every CDK role by create_platform_lambda."""
    return _compute_base(
        needs_kms=True,
        needs_ai_keys=True,
        needs_s3_config=True,
        needs_s3_write=["generated/coach_daily.json"],
    )


def compute_coach_memoir() -> list[iam.PolicyStatement]:
    """#553 quarterly coach memoir batch: reads COACH#/LEARNING#, PREDICTION#,
    STANCE# + S3 voice specs, writes MEMOIR# sentinel/records back to the same
    COACH# partition (needs PutItem, already granted by _compute_base's
    DynamoDB statement), uses Bedrock (Sonnet, narrative tier) for the
    first-person retrospective, writes generated/coach_memoirs.json.
    Budget-tier SSM read is granted to every CDK role by create_platform_lambda.
    #1441: + generated/qa_archive/text/* — the generation-time AI-surface archive (text leg only).

    #2824: + ssm:GetParameter on experiment-cycle. The MEMOIR# write-back runs
    phase_taxonomy.experiment_stamp() -> coach_checkin.read_cycle() (the same ADR-077
    write-time provenance #1858 granted compute_daily_metrics); the helper baseline covers
    budget-tier only, so the cycle read fail-softed to an unstamped quarterly memoir."""
    return _compute_base(
        needs_kms=True,
        needs_ai_keys=True,
        needs_s3_config=True,
        needs_s3_write=["generated/coach_memoirs.json", "generated/qa_archive/text/*"],
        extra_statements=[
            iam.PolicyStatement(
                sid="ExperimentCycleRead",
                actions=["ssm:GetParameter"],
                resources=[f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/experiment-cycle"],
            ),
        ],
    )


def compute_daily_insight() -> list[iam.PolicyStatement]:
    """Daily insight compute (IC-2): reads DDB metrics, writes insight records, uses ai-keys for Haiku."""
    return _compute_base(
        needs_kms=True,  # writes to platform_memory + insights DDB partitions
        needs_ai_keys=True,
        needs_s3_config=True,
    )


# ── Intelligence Lambdas (ADR-081) ──────────────────────────────────────
# ai-expert-analyzer / field-notes-generate / journal-analyzer were CLI-created
# orphans adopted into CDK on 2026-06-08. They previously shared the
# daily-insight role, so these grants are deliberately identical to
# compute_daily_insight() — a provably-safe role swap (the workload runs on
# this exact grant-set today) while giving each function its own dedicated,
# least-privilege role per the one-role-per-Lambda convention.


def intelligence_ai_expert() -> list[iam.PolicyStatement]:
    """Observatory AI expert analyzer (weekly): reads DDB, uses ai-keys for Bedrock narrative, writes analysis to DDB."""
    return _compute_base(
        needs_kms=True,  # writes observatory/insight records to DDB
        needs_ai_keys=True,
        needs_s3_config=True,
    )


def intelligence_field_notes() -> list[iam.PolicyStatement]:
    """Field-notes generator (weekly): reads DDB, uses ai-keys for Bedrock, writes field-note records to DDB.
    #1441: + generated/qa_archive/text/* — the generation-time AI-surface archive (text leg only)."""
    return _compute_base(
        needs_kms=True,
        needs_ai_keys=True,
        needs_s3_config=True,
        needs_s3_write=["generated/qa_archive/text/*"],
    )


def intelligence_journal_analyzer() -> list[iam.PolicyStatement]:
    """Journal analyzer (nightly): reads journal entries from DDB, uses ai-keys for Bedrock, writes sentiment/insights to DDB."""
    return _compute_base(
        needs_kms=True,
        needs_ai_keys=True,
        needs_s3_config=True,
    )


def compute_adaptive_mode() -> list[iam.PolicyStatement]:
    """Adaptive mode compute: reads DDB + S3 config, uses ai-keys for mode inference."""
    return _compute_base(
        needs_kms=True,  # writes adaptive_mode record to DDB
        needs_ai_keys=True,
        needs_s3_config=True,
    )


def compute_hypothesis_engine() -> list[iam.PolicyStatement]:
    """Hypothesis engine: reads DDB, uses ai-keys for Opus hypothesis generation, writes results to DDB."""
    return _compute_base(
        needs_kms=True,  # writes hypothesis records to DDB
        needs_ai_keys=True,
        needs_s3_config=True,
    )


def compute_state_of_matthew() -> list[iam.PolicyStatement]:
    """#552 State of Matthew weekly brief: reads forecast/hypotheses/coach/calibration
    DDB partitions, uses ai-keys for one weekly Haiku narration call, writes the
    combined brief back to DDB.
    #1441: + generated/qa_archive/text/* — the generation-time AI-surface archive (text leg only)."""
    return _compute_base(
        needs_kms=True,  # writes state_of_matthew records to DDB
        needs_ai_keys=True,
        needs_s3_config=True,
        needs_s3_write=["generated/qa_archive/text/*"],
    )


# ingestion_google_calendar() removed v3.7.46 — ADR-030 (integration retired)


def compute_challenge_generator() -> list[iam.PolicyStatement]:
    """Challenge generator: reads journal/character/habits from DDB, uses ai-keys for Sonnet, writes challenges to DDB."""
    return _compute_base(
        needs_kms=True,
        needs_ai_keys=True,
        needs_s3_config=True,
    )


def compute_weekly_correlations() -> list[iam.PolicyStatement]:
    """Weekly correlation compute (R8-LT9): reads 8 source partitions, writes SOURCE#weekly_correlations."""
    return _compute_base(needs_kms=True)


def compute_dashboard_refresh() -> list[iam.PolicyStatement]:
    """Dashboard refresh: reads DDB + its own dashboard/buddy JSON, writes them back."""
    policies = _compute_base(
        needs_kms=True,  # reads CMK-encrypted DDB table
        needs_s3_config=True,
        needs_s3_write=["dashboard/*", "buddy/*"],
    )
    # 2026-05-29: it reads back the existing dashboard/buddy data.json to PATCH them,
    # but the role only had PutObject on those prefixes (+ GetObject on config/*) — so
    # every read_existing_json() AccessDenied'd, swallowed as "No existing data.json —
    # skipping". The 4x/day live-stats refresh silently never ran, leaving data.json
    # stale between the daily primary write → recurring QA "stale dashboard" failures.
    policies.append(
        iam.PolicyStatement(
            sid="S3DashboardRead",
            actions=["s3:GetObject"],
            resources=_s3("dashboard/*", "buddy/*"),
        )
    )
    return policies


def compute_acwr() -> list[iam.PolicyStatement]:
    """ACWR compute (BS-09): reads Whoop strain from DDB, writes acwr fields to computed_metrics."""
    return _compute_base(needs_kms=True)


def compute_personal_baselines() -> list[iam.PolicyStatement]:
    """Personal baselines compute (#543): reads ~365d of computed_metrics from DDB, writes
    one SOURCE#personal_baselines snapshot. Deterministic, no LLM — DDB read/write only."""
    return _compute_base(needs_kms=True)


def compute_failure_pattern() -> list[iam.PolicyStatement]:
    """Failure pattern compute (IC-4): reads DDB metrics, uses ai-keys for pattern analysis, writes to DDB."""
    return _compute_base(
        needs_kms=True,  # writes failure_pattern records to platform_memory DDB partition
        needs_ai_keys=True,
        needs_s3_config=True,
    )


def compute_coach_computation() -> list[iam.PolicyStatement]:
    """Coach computation engine: reads all source partitions + COACH# predictions, writes COACH#computation results to DDB, reads S3 config.

    Shared with coach-observatory-renderer (read-only DDB + S3 — see compute_stack.py).

    #1858: + ssm:GetParameter on experiment-cycle — phase_taxonomy.experiment_stamp()
    (ADR-077 write-time provenance on this Lambda's COACH# writes) calls
    coach_checkin.read_cycle(), which was un-granted here and fail-softing to no
    cycle stamp (AccessDeniedException, caught and logged, never blocking the write).
    """
    return _compute_base(
        needs_kms=True,
        needs_s3_config=True,
        extra_statements=[
            iam.PolicyStatement(
                sid="ExperimentCycleRead",
                actions=["ssm:GetParameter"],
                resources=[f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/experiment-cycle"],
            ),
        ],
    )


def compute_voice_fidelity_harness() -> list[iam.PolicyStatement]:
    """Voice-fidelity harness (#545): reads COACH#{id} OUTPUT# samples + the persona
    registry (S3 config), runs a Haiku judge panel, writes VOICEFIDELITY# judgments
    + the scoreboard back to DDB. needs_ai_keys=True also covers Bedrock invoke +
    the AI cost-metrics PutMetricData grant."""
    return _compute_base(needs_kms=True, needs_ai_keys=True, needs_s3_config=True)


def compute_coach_prediction_evaluator() -> list[iam.PolicyStatement]:
    """Coach prediction evaluator: same DDB/S3 footprint as compute_coach_computation
    (deterministic, no LLM), PLUS #534's two narrow additions for the event-driven
    mid-week stance refresh this Lambda now also detects and fires:
      - ssm:GetParameter on budget-tier — so budget_guard.allow() actually reads the
        live tier instead of silently fail-opening (the tier=0 default) the way
        inter_coach_dialogue_lambda's un-granted budget_guard call does today.
      - lambda:InvokeFunction scoped to coach-history-summarizer ONLY — the async
        fire-and-forget invoke that starts the mid-week STANCE# refresh.
    Kept as its own dedicated function (not folded into compute_coach_computation,
    which coach-observatory-renderer and the computation engine also use) so those
    two Lambdas don't inherit permissions they don't need.

    #1196: added cloudwatch:PutMetricData. emit_grading_liveness() emits the #727
    scientific-liveness gauge (DaysSinceLastDecided / DecidedCount / GradableCount
    in the LifePlatform/Predictions namespace) EVERY run so the monitoring_stack
    GradingStalled alarm has daily data. Pre-fix every emit failed AccessDenied
    (non-fatal — caught as WARNING at coach_prediction_evaluator.py:1471), the
    gauge never landed a single datapoint, and grading-stalled sat in ALARM on
    missing-data-breaching and could never clear. Mirrors the identical grant
    compute_coach_state_updater already carries. PutMetricData only accepts "*".

    #1858: + ssm:GetParameter on experiment-cycle — phase_taxonomy.experiment_stamp()
    and dispute_docket.resolve_due() (the mid-week docket resolution this Lambda
    fires) both call coach_checkin.read_cycle(), which was un-granted here and
    fail-softing to no cycle stamp (AccessDeniedException, caught and logged,
    never blocking the write).
    """
    return _compute_base(
        needs_kms=True,
        needs_s3_config=True,
        extra_statements=[
            iam.PolicyStatement(
                sid="BudgetTierRead",
                actions=["ssm:GetParameter"],
                resources=[f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/budget-tier"],
            ),
            iam.PolicyStatement(
                sid="ExperimentCycleRead",
                actions=["ssm:GetParameter"],
                resources=[f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/experiment-cycle"],
            ),
            iam.PolicyStatement(
                sid="InvokeStanceRefresh",
                actions=["lambda:InvokeFunction"],
                resources=[f"arn:aws:lambda:{REGION}:{ACCT}:function:coach-history-summarizer"],
            ),
            iam.PolicyStatement(
                sid="CloudWatchMetrics",
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
            ),
        ],
    )


def compute_coach_orchestrator() -> list[iam.PolicyStatement]:
    """Coach narrative orchestrator: reads COACH#/ENSEMBLE#/NARRATIVE# partitions from DDB, reads S3 voice specs, uses ai-keys for Haiku LLM, writes briefs to DDB.

    Shared with coach-ensemble-digest and coach-history-summarizer (same permissions — see compute_stack.py).

    #1858: + ssm:GetParameter on experiment-cycle — phase_taxonomy.experiment_stamp()
    (coach-history-summarizer's writer, ADR-077) and dispute_docket.open_from_disagreements()
    (coach-ensemble-digest's docket-open path) both call coach_checkin.read_cycle(),
    which was un-granted here and fail-softing to no cycle stamp (AccessDeniedException,
    caught and logged, never blocking the write).
    """
    return _compute_base(
        needs_kms=True,
        needs_ai_keys=True,
        needs_s3_config=True,
        extra_statements=[
            iam.PolicyStatement(
                sid="ExperimentCycleRead",
                actions=["ssm:GetParameter"],
                resources=[f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/experiment-cycle"],
            ),
        ],
    )


def compute_coach_state_updater() -> list[iam.PolicyStatement]:
    """Coach state updater: reads S3 voice specs, uses ai-keys for Haiku extraction, writes COACH# state records to DDB.

    Reentry sweep (2026-05-03 v6.8.10): added cloudwatch:PutMetricData. Lambda emits
    AnthropicInputTokens / AnthropicOutputTokens per coach for cost tracking. Pre-fix
    every emit failed with AccessDenied (non-fatal — caught as WARNING) which made
    downstream alarms (ai-tokens-daily-brief-daily) inaccurate.

    Shared with coach-quality-gate (same permissions — see compute_stack.py).

    #1858: + ssm:GetParameter on experiment-cycle — phase_taxonomy.experiment_stamp()
    (ADR-077 write-time provenance on this Lambda's COACH# state writes) calls
    coach_checkin.read_cycle(), which was un-granted here and fail-softing to no
    cycle stamp (AccessDeniedException, caught and logged, never blocking the write).
    """
    return _compute_base(
        needs_kms=True,
        needs_ai_keys=True,
        needs_s3_config=True,
        extra_statements=[
            iam.PolicyStatement(
                sid="CloudWatchMetrics",
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
            ),
            iam.PolicyStatement(
                sid="ExperimentCycleRead",
                actions=["ssm:GetParameter"],
                resources=[f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/experiment-cycle"],
            ),
        ],
    )


# ═════════════════════════════════════════════════════════════════════════
# BS-SL2 — Circadian Compliance  (BS-08 Sleep Reconciler RETIRED #487/ADR-113)
# ═════════════════════════════════════════════════════════════════════════


def compute_circadian_compliance() -> list[iam.PolicyStatement]:
    """BS-SL2: Circadian Compliance Score — reads journal/MacroFactor/Whoop/Strava, writes circadian."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]
