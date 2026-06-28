"""
role_policies.py — Centralized IAM policy definitions for all Life Platform Lambdas.

Each function returns a list of iam.PolicyStatement objects that exactly
replicate the existing console-created per-function IAM roles from SEC-1.

Audit source: aws iam get-role-policy on all 37 lambda-* roles (2026-03-09).
Organized by CDK stack: ingestion, compute, email, operational, mcp.

Policy principle: least-privilege per Lambda. No shared roles.
"""

from aws_cdk import aws_iam as iam

from stacks.constants import ACCT, CF_DIST_ID, KMS_KEY_ID, REGION, S3_BUCKET, SES_DOMAIN, TABLE_NAME  # CONF-01, SEC-06, SEC-08

# ── Constants ──────────────────────────────────────────────────────────────
TABLE_ARN = f"arn:aws:dynamodb:{REGION}:{ACCT}:table/{TABLE_NAME}"
BUCKET = S3_BUCKET
CF_DIST_ARN = f"arn:aws:cloudfront::{ACCT}:distribution/{CF_DIST_ID}"
BUCKET_ARN = f"arn:aws:s3:::{BUCKET}"
DLQ_ARN = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
KMS_KEY_ARN = f"arn:aws:kms:{REGION}:{ACCT}:key/{KMS_KEY_ID}"
# Phase 2.4 (2026-05-16): dedicated CMK for S3 default encryption.
# IMPORTANT: must reference by key ID ARN (not alias) — IAM does not resolve
# alias ARNs in resource policies. Key is created in CoreStack (`s3_kms_key`).
# Roles need encrypt/decrypt on it to write/read KMS-encrypted objects.
# S3_KMS_KEY_ARN removed 2026-05-24 — orphan reference; bucket uses AES256, key
# scheduled for deletion 2026-06-16. See BACKLOG.md follow-up.
SES_IDENTITY = f"arn:aws:ses:{REGION}:{ACCT}:identity/{SES_DOMAIN}"  # SEC-08: domain from constants
# V2 P1.6 follow-up (2026-05-19): SES requires send permission on BOTH the
# identity AND the configuration-set when SendEmail includes ConfigurationSetName.
# Missing this caused daily-brief AccessDeniedException for 2 days post-P1.6.
SES_CONFIG_SET_ARN = f"arn:aws:ses:{REGION}:{ACCT}:configuration-set/life-platform-emails"


def _secret_arn(name: str) -> str:
    """Secrets Manager ARN with wildcard suffix for version IDs."""
    return f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:{name}*"


def _s3(*prefixes: str) -> list[str]:
    """S3 object ARNs for the given key prefixes."""
    return [f"{BUCKET_ARN}/{p}" for p in prefixes]


def _bedrock_statement() -> iam.PolicyStatement:
    """ADR-062 (2026-05-27): bedrock:InvokeModel for Claude inference.

    Migration from direct Anthropic API → Bedrock. Granted to every AI-calling
    role (anywhere ai-keys was previously granted). Scoped to Anthropic Claude
    only — both the cross-region inference profiles (`us.anthropic.claude-*`,
    which on-demand 4.x models require) AND the underlying foundation-model
    ARNs the profiles fan out to (InvokeModel is authorized against both).
    Region wildcard because the us. profile routes across us-east-1/us-east-2/
    us-west-2.
    """
    return iam.PolicyStatement(
        sid="BedrockInvoke",
        actions=["bedrock:InvokeModel"],
        resources=[
            f"arn:aws:bedrock:*:{ACCT}:inference-profile/us.anthropic.claude-*",
            "arn:aws:bedrock:*::foundation-model/anthropic.claude-*",
        ],
    )


# ═══════════════════════════════════════════════════════════════════════════
# INGESTION STACK — 15 Lambdas
# Pattern: DDB write, S3 raw/<source>/*, source-specific secret, DLQ
# ═══════════════════════════════════════════════════════════════════════════


def _ingestion_base(
    source: str,
    secret_name: str = None,
    s3_prefix: str = None,
    ddb_actions: list[str] = None,
    extra_secret_actions: list[str] = None,
    extra_s3_read: list[str] = None,
    extra_s3_write: list[str] = None,
    extra_statements: list[iam.PolicyStatement] = None,
    no_s3: bool = False,
    no_secret: bool = False,
) -> list[iam.PolicyStatement]:
    """Build standard ingestion role policies."""
    stmts = []

    # DynamoDB — DeleteItem needed for SIMP-2 framework's auth-breaker
    # clear_failure() path (deletes the AUTH#failures marker on a clean run).
    actions = ddb_actions or ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:DeleteItem"]
    stmts.append(
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=actions,
            resources=[TABLE_ARN],
        )
    )

    # KMS — DDB CMK only. Phase 2.4 had also granted on the S3 CMK, but the
    # S3 bucket switched to AES256 default encryption (no per-object KMS), so
    # the S3 key is now orphaned and scheduled for deletion 2026-06-16.
    stmts.append(
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        )
    )

    # S3 write (raw data)
    if not no_s3:
        prefix = s3_prefix or f"raw/matthew/{source}/*"
        write_resources = _s3(prefix) + (_s3(*extra_s3_write) if extra_s3_write else [])
        stmts.append(
            iam.PolicyStatement(
                sid="S3Write",
                actions=["s3:PutObject"],
                resources=write_resources,
            )
        )

    # S3 read (if needed)
    if extra_s3_read:
        stmts.append(
            iam.PolicyStatement(
                sid="S3Read",
                actions=["s3:GetObject"],
                resources=_s3(*extra_s3_read),
            )
        )

    # Secrets
    if not no_secret and secret_name:
        secret_actions = ["secretsmanager:GetSecretValue", "secretsmanager:UpdateSecret"]
        if extra_secret_actions:
            secret_actions = list(set(secret_actions + extra_secret_actions))
        stmts.append(
            iam.PolicyStatement(
                sid="Secrets",
                actions=secret_actions,
                resources=[_secret_arn(secret_name)],
            )
        )

    # DLQ
    stmts.append(
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        )
    )

    # CloudWatch metrics (ADR-052): OAuth refresh writeback failures and other
    # custom ingestion metrics. PutMetricData only accepts "*" as a resource.
    stmts.append(
        iam.PolicyStatement(
            sid="CloudWatchMetrics",
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
        )
    )

    # Extra statements
    if extra_statements:
        stmts.extend(extra_statements)

    return stmts


def ingestion_whoop() -> list[iam.PolicyStatement]:
    return _ingestion_base(
        "whoop",
        secret_name="life-platform/whoop",
        extra_secret_actions=["secretsmanager:PutSecretValue"],
    )


def ingestion_garmin() -> list[iam.PolicyStatement]:
    return _ingestion_base(
        "garmin",
        secret_name="life-platform/garmin",
        # DeleteItem added for SIMP-2 framework auth-breaker clear_failure path
        ddb_actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query", "dynamodb:DeleteItem"],
    )


def ingestion_notion() -> list[iam.PolicyStatement]:
    return _ingestion_base(
        "notion",
        secret_name="life-platform/ingestion-keys",  # COST-B: bundled 2026-03-10
        s3_prefix="raw/matthew/notion/*",
    )


def ingestion_withings() -> list[iam.PolicyStatement]:
    return _ingestion_base(
        "withings",
        secret_name="life-platform/withings",
        extra_secret_actions=["secretsmanager:PutSecretValue"],  # OAuth token refresh writes back to secret
    )


def ingestion_habitify() -> list[iam.PolicyStatement]:
    # ADR-014: life-platform/habitify has its own dedicated secret (restored 2026-03-10
    # after accidental deletion). NOT bundled in ingestion-keys — keep separate.
    return _ingestion_base(
        "habitify",
        secret_name="life-platform/habitify",
        s3_prefix="raw/matthew/habitify/*",
    )


def ingestion_strava() -> list[iam.PolicyStatement]:
    return _ingestion_base(
        "strava",
        secret_name="life-platform/strava",
        extra_secret_actions=["secretsmanager:PutSecretValue"],  # OAuth token refresh writes back to secret
    )


def ingestion_hevy_webhook() -> list[iam.PolicyStatement]:
    """Hevy webhook FunctionURL Lambda — receives webhook POST + fetches workout.

    Per SPEC_HEVY_AND_NUTRITION_BRIDGE_2026_05_25 + ADR-014 (dedicated secret).
    Reads: life-platform/hevy secret (api_key + webhook_secret).
    Writes: DDB workouts under USER#matthew#SOURCE#hevy + S3 raw/hevy/.
    """
    return _ingestion_base(
        "hevy",
        secret_name="life-platform/hevy",
        s3_prefix="raw/hevy/*",
    )


def ingestion_hevy_backfill() -> list[iam.PolicyStatement]:
    """Hevy scheduled events-cursor backfill Lambda.

    Same secret + storage as webhook, plus cursor read/write under
    USER#system / INGESTION_CURSOR#hevy.
    """
    return _ingestion_base(
        "hevy",
        secret_name="life-platform/hevy",
        s3_prefix="raw/hevy/*",
    )


# ingestion_macrofactor_puller() removed 2026-05-25 — see ADR-061. MF Tier 1
# (unofficial Firebase API) was blocked by App Check, code path torn down. MF
# data continues to flow via Tier 2 Dropbox export (dropbox-poll →
# macrofactor-data-ingestion).


def ingestion_journal_enrichment() -> list[iam.PolicyStatement]:
    """Journal enrichment uses ai-keys for Haiku enrichment, no raw S3 write."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="Secrets",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/ai-keys")],
        ),
        _bedrock_statement(),  # ADR-062: AI-calling enrichment role → Bedrock invoke
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
        iam.PolicyStatement(
            sid="XRay",  # R13-XR: X-Ray active tracing
            actions=[
                "xray:PutTraceSegments",
                "xray:PutTelemetryRecords",
                "xray:GetSamplingRules",
                "xray:GetSamplingTargets",
            ],
            resources=["*"],  # X-Ray does not support resource-level restrictions
        ),
    ]


def ingestion_todoist() -> list[iam.PolicyStatement]:
    return _ingestion_base(
        "todoist",
        secret_name="life-platform/ingestion-keys",  # COST-B: bundled 2026-03-10
        s3_prefix="raw/todoist/*",  # NOTE: no matthew/ prefix — Lambda writes to raw/todoist/ directly
    )


def ingestion_eightsleep() -> list[iam.PolicyStatement]:
    return _ingestion_base(
        "eightsleep",
        secret_name="life-platform/eightsleep",
    )


def ingestion_activity_enrichment() -> list[iam.PolicyStatement]:
    """Activity enrichment uses ai-keys for Haiku enrichment, no raw S3 write."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="Secrets",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/ai-keys")],
        ),
        _bedrock_statement(),  # ADR-062: AI-calling enrichment role → Bedrock invoke
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
        iam.PolicyStatement(
            sid="XRay",  # R13-XR: X-Ray active tracing
            actions=[
                "xray:PutTraceSegments",
                "xray:PutTelemetryRecords",
                "xray:GetSamplingRules",
                "xray:GetSamplingTargets",
            ],
            resources=["*"],  # X-Ray does not support resource-level restrictions
        ),
    ]


def ingestion_macrofactor() -> list[iam.PolicyStatement]:
    """MacroFactor: DDB write + S3 raw/macrofactor, reads CSV from uploads/macrofactor/."""
    return _ingestion_base(
        "macrofactor",
        no_secret=True,
        extra_s3_read=["uploads/macrofactor/*"],
    )


def ingestion_weather() -> list[iam.PolicyStatement]:
    """Weather: DDB write only, no S3, no secrets."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"],
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


def ingestion_dropbox() -> list[iam.PolicyStatement]:
    return _ingestion_base(
        "dropbox",
        secret_name="life-platform/ingestion-keys",  # COST-B: bundled 2026-03-10
        s3_prefix="uploads/macrofactor/*",  # dropbox writes MacroFactor CSVs here
        extra_s3_read=["uploads/macrofactor/*"],
    )


def ingestion_apple_health() -> list[iam.PolicyStatement]:
    """Apple Health: S3-triggered, reads XML from imports/, writes to DDB."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3Read",
            actions=["s3:GetObject"],
            resources=_s3("imports/apple_health/*"),
        ),
        iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            resources=_s3("raw/matthew/apple_health/*"),
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]


def ingestion_hae() -> list[iam.PolicyStatement]:
    """Health Auto Export webhook: API Gateway trigger, DDB + S3 write.

    R8 Finding-2 fix: Added Secrets Manager access for Bearer token auth.
    Code default reads life-platform/ingestion-keys (health_auto_export_api_key).
    (Note: a dedicated life-platform/webhook-key existed in early 2026 but was
    deleted 2026-03-14 per HANDOVER_v3.7.84; ingestion-keys is now the only path.)
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            # R8-ST7: tightened from raw/matthew/* to explicit HAE sub-paths (2026-03-14)
            resources=_s3(
                "raw/matthew/cgm_readings/*",
                "raw/matthew/blood_pressure/*",
                "raw/matthew/state_of_mind/*",
                "raw/matthew/workouts/*",
                "raw/matthew/health_auto_export/*",
            ),
        ),
        iam.PolicyStatement(
            sid="Secrets",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/ingestion-keys")],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]


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
    """Daily metrics: DDB read+write, KMS."""
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
    """Field-notes generator (weekly): reads DDB, uses ai-keys for Bedrock, writes field-note records to DDB."""
    return _compute_base(
        needs_kms=True,
        needs_ai_keys=True,
        needs_s3_config=True,
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


def compute_failure_pattern() -> list[iam.PolicyStatement]:
    """Failure pattern compute (IC-4): reads DDB metrics, uses ai-keys for pattern analysis, writes to DDB."""
    return _compute_base(
        needs_kms=True,  # writes failure_pattern records to platform_memory DDB partition
        needs_ai_keys=True,
        needs_s3_config=True,
    )


def compute_coach_computation() -> list[iam.PolicyStatement]:
    """Coach computation engine: reads all source partitions + COACH# predictions, writes COACH#computation results to DDB, reads S3 config."""
    return _compute_base(needs_kms=True, needs_s3_config=True)


def compute_coach_orchestrator() -> list[iam.PolicyStatement]:
    """Coach narrative orchestrator: reads COACH#/ENSEMBLE#/NARRATIVE# partitions from DDB, reads S3 voice specs, uses ai-keys for Haiku LLM, writes briefs to DDB."""
    return _compute_base(needs_kms=True, needs_ai_keys=True, needs_s3_config=True)


def compute_coach_state_updater() -> list[iam.PolicyStatement]:
    """Coach state updater: reads S3 voice specs, uses ai-keys for Haiku extraction, writes COACH# state records to DDB.

    Reentry sweep (2026-05-03 v6.8.10): added cloudwatch:PutMetricData. Lambda emits
    AnthropicInputTokens / AnthropicOutputTokens per coach for cost tracking. Pre-fix
    every emit failed with AccessDenied (non-fatal — caught as WARNING) which made
    downstream alarms (ai-tokens-daily-brief-daily) inaccurate.
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
            )
        ],
    )


# ═════════════════════════════════════════════════════════════════════════
# EMAIL STACK — 8 Lambdas
# Pattern: DDB read, S3 config (board_of_directors.json), ai-keys, SES send, DLQ
# ═════════════════════════════════════════════════════════════════════════


def _email_base(
    needs_s3_write: list[str] = None,
    extra_secrets: list[str] = None,
    extra_statements: list[iam.PolicyStatement] = None,
) -> list[iam.PolicyStatement]:
    """Build standard email Lambda policies: DDB read, S3 config, ai-keys, SES, DLQ."""
    stmts = [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:BatchGetItem"],
            resources=[TABLE_ARN, f"{TABLE_ARN}/index/*"],
        ),
        iam.PolicyStatement(
            sid="KMS",
            # Phase 2.4: include S3 CMK — email Lambdas read S3 (config, generated
            # content from S3) and some write back (chronicle, og images).
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3ConfigRead",
            actions=["s3:GetObject"],
            resources=_s3("config/*"),
        ),
        iam.PolicyStatement(
            sid="Secrets",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn(s) for s in ["life-platform/ai-keys"] + (extra_secrets or [])],
        ),
        # ADR-062: all email Lambdas call AI → grant Bedrock invoke.
        _bedrock_statement(),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]
    if needs_s3_write:
        stmts.append(
            iam.PolicyStatement(
                sid="S3Write",
                actions=["s3:PutObject"],
                resources=_s3(*needs_s3_write),
            )
        )
    if extra_statements:
        stmts.extend(extra_statements)
    return stmts


def email_daily_brief() -> list[iam.PolicyStatement]:
    """Daily brief: DDB read, S3 config, ai-keys, SES, writes dashboard/ + buddy/ + site/ to S3.
    Risk-7: also emits ComputePipelineStaleness metric to CloudWatch.
    site/public_stats.json written via site_writer.py for averagejoematt.com.
    Coach Intelligence: invokes coach-computation-engine, coach-narrative-orchestrator, coach-state-updater.
    """
    return _email_base(
        needs_s3_write=["dashboard/*", "buddy/*", "site/*", "generated/*"],
        extra_statements=[
            iam.PolicyStatement(
                sid="CloudWatchMetrics",
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
            ),
            iam.PolicyStatement(
                sid="CoachIntelligenceInvoke",
                actions=["lambda:InvokeFunction"],
                resources=[
                    f"arn:aws:lambda:{REGION}:{ACCT}:function:coach-computation-engine",
                    f"arn:aws:lambda:{REGION}:{ACCT}:function:coach-narrative-orchestrator",
                    f"arn:aws:lambda:{REGION}:{ACCT}:function:coach-state-updater",
                    f"arn:aws:lambda:{REGION}:{ACCT}:function:coach-ensemble-digest",
                    # Added 2026-05-24: daily-brief invokes coach-quality-gate
                    # per-coach during the V2 pipeline; without this grant every
                    # coach call logs an AccessDeniedException (non-blocking,
                    # but flooding CloudWatch with errors).
                    f"arn:aws:lambda:{REGION}:{ACCT}:function:coach-quality-gate",
                ],
            ),
        ],
    )


def email_weekly_digest() -> list[iam.PolicyStatement]:
    """Weekly digest: DDB read, S3 config, ai-keys, SES, writes clinical.json to S3."""
    return _email_base(needs_s3_write=["dashboard/clinical.json"])


def email_monthly_digest() -> list[iam.PolicyStatement]:
    """Monthly digest: DDB read, S3 config, ai-keys, SES."""
    return _email_base()


def email_nutrition_review() -> list[iam.PolicyStatement]:
    """Nutrition review: DDB read, S3 config, ai-keys, SES."""
    return _email_base()


def email_chronicle_podcast() -> list[iam.PolicyStatement]:
    """Chronicle podcast: DDB read (content_markdown), S3 read posts.json +
    write generated/podcast/*. Voice via Google Chirp 3: HD (API key in
    life-platform/google-tts) — Polly dropped 2026-06-14."""
    return _email_base(
        needs_s3_write=["generated/podcast/*"],
        extra_secrets=["life-platform/google-tts"],
        extra_statements=[
            iam.PolicyStatement(sid="ChroniclePostsRead", actions=["s3:GetObject"], resources=[f"{BUCKET_ARN}/site/chronicle/posts.json"]),
        ],
    )


def email_coach_panel_podcast() -> list[iam.PolicyStatement]:
    """The Panel (two-host show): DDB read (chronicle + COACH#/OUTPUT#), S3 read
    posts.json, Bedrock (Haiku) script-gen, Google Chirp 3: HD voices
    (life-platform/google-tts), write generated/panelcast/*. Bedrock + budget-tier
    SSM granted by _email_base / create_platform_lambda."""
    return _email_base(
        # generated/panelcast/* = published episodes; panelcast-holds/* = NON-public
        # human-review drafts when the QA/compassion gate holds an episode.
        needs_s3_write=["generated/panelcast/*", "panelcast-holds/*"],
        extra_secrets=["life-platform/google-tts"],
        extra_statements=[
            iam.PolicyStatement(sid="ChroniclePostsRead", actions=["s3:GetObject"], resources=[f"{BUCKET_ARN}/site/chronicle/posts.json"]),
            # Loud HOLD + new-episode notify: SNS to life-platform-alerts.
            iam.PolicyStatement(
                sid="HoldAlertSNS", actions=["sns:Publish"], resources=[f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"]
            ),
            # Publish heartbeat metric — the "show went silent" alarm watches for its absence.
            iam.PolicyStatement(sid="PublishedMetric", actions=["cloudwatch:PutMetricData"], resources=["*"]),
            # Auto-invalidate /panelcast/* after publishing so a new episode is live
            # immediately — wk*.wav carries a 24h cache header, so without this the CDN
            # serves the prior cut for up to a day (observed 2026-06-17: a stale Ep0).
            iam.PolicyStatement(sid="PanelcastCdnInvalidate", actions=["cloudfront:CreateInvalidation"], resources=[CF_DIST_ARN]),
        ],
    )


def email_wednesday_chronicle() -> list[iam.PolicyStatement]:
    """Wednesday chronicle: DDB read, S3 config, ai-keys, SES, writes blog/* + site/journal/* to S3.
    site/journal/posts/week-{nn}/index.html + site/journal/posts.json written via publish_to_journal.
    """
    return _email_base(needs_s3_write=["blog/*", "site/journal/*", "generated/journal/*"])


def email_weekly_plate() -> list[iam.PolicyStatement]:
    """Weekly Plate: DDB read, S3 config, ai-keys, SES."""
    return _email_base()


def email_monday_compass() -> list[iam.PolicyStatement]:
    """Monday Compass: DDB read, S3 config, ai-keys, SES."""
    return _email_base()


def email_partner() -> list[iam.PolicyStatement]:
    """Partner weekly email: DDB read, S3 config, ai-keys, SES."""
    return _email_base()


def email_evening_nudge() -> list[iam.PolicyStatement]:
    """Evening nudge: DDB read (supplements, notion, apple_health, state_of_mind), SES. No ai-keys needed."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]


# ═════════════════════════════════════════════════════════════════════════
# OPERATIONAL STACK — 8 Lambdas
# ═════════════════════════════════════════════════════════════════════════


def email_chronicle_sender() -> list[iam.PolicyStatement]:
    """Chronicle email sender (BS-03): reads DDB (chronicle + subscribers), KMS, SES send, DLQ.
    No ai-keys — content is pre-generated by wednesday-chronicle and stored in DDB.
    No S3 read — no config or file reads needed.
    Separate from wednesday-chronicle IAM by design (Board: independent failure domains).
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]


def email_weekly_signal() -> list[iam.PolicyStatement]:
    """Weekly Signal subscriber email (PB-06): reads DDB (insights + subscribers),
    S3 (generated/public_stats.json, generated/journal/posts.json), KMS, SES send, DLQ.
    No ai-keys — reads pre-computed data only.
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="S3Read",
            actions=["s3:GetObject"],
            resources=[
                f"{BUCKET_ARN}/generated/public_stats.json",
                f"{BUCKET_ARN}/generated/journal/*",
            ],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]


def email_chronicle_approve() -> list[iam.PolicyStatement]:
    """Chronicle approve Lambda (FEAT-12): reads + updates DDB draft, writes pre-built
    artifacts to S3, creates CloudFront invalidation, invokes chronicle-email-sender.
    No ai-keys — content was pre-generated by wednesday-chronicle.
    No SES — subscriber emails are delegated to chronicle-email-sender.
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:UpdateItem"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            resources=_s3("blog/*", "site/journal/*", "generated/journal/*"),
        ),
        iam.PolicyStatement(
            sid="CloudFrontInvalidate",
            actions=["cloudfront:CreateInvalidation"],
            resources=[CF_DIST_ARN],
        ),
        iam.PolicyStatement(
            sid="InvokeEmailSender",
            actions=["lambda:InvokeFunction"],
            # chronicle-email-sender ARN pattern
            resources=[f"arn:aws:lambda:{REGION}:{ACCT}:function:chronicle-email-sender"],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]


def _operational_base(
    ddb_actions: list[str] = None,
    needs_ses: bool = False,
    needs_dlq: bool = False,
    needs_s3_read: list[str] = None,
    needs_s3_write: list[str] = None,
    extra_statements: list[iam.PolicyStatement] = None,
) -> list[iam.PolicyStatement]:
    """Build standard operational role policies.

    Operational Lambdas tend to share: DDB read+optional-write, KMS, optional
    SES, optional S3 read/write, optional DLQ. Use this for the simpler ones;
    keep bespoke patterns (canary, qa_smoke, delete_user_data) explicit.
    """
    stmts = [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=ddb_actions or ["dynamodb:GetItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
    ]
    if needs_s3_read:
        stmts.append(
            iam.PolicyStatement(
                sid="S3Read",
                actions=["s3:GetObject"],
                resources=_s3(*needs_s3_read),
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
    if needs_ses:
        stmts.append(
            iam.PolicyStatement(
                sid="SES",
                actions=["ses:SendEmail", "sesv2:SendEmail"],
                resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
            )
        )
    if needs_dlq:
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


def operational_freshness_checker() -> list[iam.PolicyStatement]:
    """Freshness checker: reads DDB + publishes CloudWatch custom metrics, sends SES alert.
    R8-ST4: also calls DescribeSecret on OAuth secrets to check token freshness.
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="CloudWatchMetrics",
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
        ),
        iam.PolicyStatement(
            # WR-48 root-cause fix (PR-reentry-4, 2026-05-03): the freshness checker
            # was running daily and detecting 4-5 stale sources during the Apr 2 →
            # May 2 silence, but EVERY SNS publish failed with AuthorizationError
            # because this statement was missing.
            # ADR-052: now publishes to BOTH topics — env var SNS_ARN selects the
            # active target (currently digest). Keeping urgent in the grant means
            # an operational override (e.g., for a future "page me now" mode)
            # doesn't require a redeploy.
            sid="SnsPublishAlerts",
            actions=["sns:Publish"],
            resources=[
                f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts",
                f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts-digest",
            ],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
        iam.PolicyStatement(
            sid="OAuthSecretDescribe",
            # R8-ST4: DescribeSecret to read LastChangedDate for token health monitoring.
            # 2026-05-28: the freshness checker also monitors MANUAL_ROTATION_SECRETS
            # (Phase 2.6) but the role only granted the 4 OAuth secrets → every run
            # AccessDenied'd on the manual ones (swallowed), so the "catch the next
            # dead OAuth integration" safeguard could never fire. Added the manual set.
            # Dropped strava (paused 2026-05-28) and dropbox (secret soft-deleted).
            actions=["secretsmanager:DescribeSecret"],
            resources=[
                _secret_arn("life-platform/whoop"),
                _secret_arn("life-platform/withings"),
                _secret_arn("life-platform/garmin"),
                _secret_arn("life-platform/ai-keys"),
                _secret_arn("life-platform/site-api-ai-key"),
                _secret_arn("life-platform/eightsleep-client"),
                _secret_arn("life-platform/notion"),
                _secret_arn("life-platform/todoist"),
                _secret_arn("life-platform/ingestion-keys"),
            ],
        ),
    ]


def operational_alert_digest() -> list[iam.PolicyStatement]:
    """Alert digest Lambda (ADR-050): drains digest queue, sends one SES summary daily."""
    digest_queue_arn = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-alerts-digest-queue"
    return [
        iam.PolicyStatement(
            sid="SQSDrain",
            actions=["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:DeleteMessageBatch", "sqs:GetQueueAttributes"],
            resources=[digest_queue_arn],
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
        ),
    ]


def operational_traffic_digest() -> list[iam.PolicyStatement]:
    """Weekly traffic digest: reads CloudFront access logs from the log bucket
    (aggregate-only, IPs hashed-then-discarded, no PII retained) + one SES email."""
    log_bucket_arn = "arn:aws:s3:::matthew-life-platform-cf-logs"
    return [
        iam.PolicyStatement(
            sid="ReadCFLogs",
            actions=["s3:GetObject", "s3:ListBucket"],
            resources=[log_bucket_arn, f"{log_bucket_arn}/*"],
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
        ),
    ]


def operational_dlq_consumer() -> list[iam.PolicyStatement]:
    """DLQ consumer: reads the DLQ, re-drives transient failures to the source
    Lambda, archives permanent failures to S3, sends an SES summary."""
    return [
        iam.PolicyStatement(
            sid="SQS",
            actions=["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"],
            resources=[DLQ_ARN],
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
        # Archive permanent failures for post-mortem (was AccessDenied — 2026-05-28).
        iam.PolicyStatement(
            sid="S3Archive",
            actions=["s3:PutObject"],
            resources=_s3("dead-letter-archive/*"),
        ),
        # Re-drive transient failures: resolve the source function from the
        # triggering EventBridge rule, then re-invoke it (2026-05-28).
        iam.PolicyStatement(
            sid="ResolveRuleTarget",
            actions=["events:ListTargetsByRule"],
            resources=[f"arn:aws:events:{REGION}:{ACCT}:rule/LifePlatform*"],
        ),
        iam.PolicyStatement(
            sid="RedriveInvoke",
            actions=["lambda:InvokeFunction"],
            resources=[f"arn:aws:lambda:{REGION}:{ACCT}:function:*"],
        ),
    ]


def operational_remediation_dispatcher() -> list[iam.PolicyStatement]:
    """Remediation dispatcher (ADR-064 urgent fast path): subscribed to the
    life-platform-alerts SNS topic; reads the GH dispatch PAT from Secrets
    Manager; writes a 30-min dedupe marker to S3."""
    return [
        iam.PolicyStatement(
            sid="GHToken",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/github-dispatch-token")],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt"],
            resources=[f"arn:aws:kms:{REGION}:{ACCT}:key/{KMS_KEY_ID}"],
        ),
        iam.PolicyStatement(
            sid="Dedupe",
            actions=["s3:GetObject", "s3:PutObject"],
            resources=_s3("remediation-log/dispatch-dedupe/*"),
        ),
        # HeadObject on a non-existent key returns 403 instead of 404 without
        # ListBucket — the Lambda's existence check (_seen) needs the 404 to
        # signal "first time, go ahead and dispatch."
        iam.PolicyStatement(
            sid="DedupeList",
            actions=["s3:ListBucket"],
            resources=[f"arn:aws:s3:::{S3_BUCKET}"],
            conditions={"StringLike": {"s3:prefix": ["remediation-log/dispatch-dedupe/*"]}},
        ),
    ]


def operational_cost_governor() -> list[iam.PolicyStatement]:
    """Cost governor (budget guardrails): estimate spend (Cost Explorer non-AI +
    Bedrock per-model token metrics), write the budget tier to SSM, emit metrics,
    alert on tier change. ce:* and cloudwatch:* have no resource-level scoping."""
    return [
        iam.PolicyStatement(
            sid="CostExplorer",
            actions=["ce:GetCostAndUsage"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="CloudWatch",
            actions=[
                "cloudwatch:GetMetricData",
                "cloudwatch:GetMetricStatistics",
                "cloudwatch:ListMetrics",
                "cloudwatch:PutMetricData",
            ],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="BudgetTierParam",
            actions=["ssm:GetParameter", "ssm:PutParameter"],
            resources=[f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/budget-tier"],
        ),
        iam.PolicyStatement(
            sid="Alert",
            actions=["sns:Publish"],
            resources=[f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"],
        ),
    ]


def operational_canary() -> list[iam.PolicyStatement]:
    """Canary: write-read-delete round-trip test on DDB + S3, optional MCP check, SES alert."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            # Canary writes a synthetic record, reads it back, then deletes it
            actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:DeleteItem"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            # DDB table uses CMK — canary needs decrypt + generate for PutItem/GetItem
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3Canary",
            # Canary writes to canary/ prefix, reads back, then deletes
            actions=["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
            resources=_s3("canary/*"),
        ),
        iam.PolicyStatement(
            sid="CloudWatchMetrics",
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="Secrets",
            # MCP check needs the Bearer token from life-platform/mcp-api-key.
            # Anthropic check (post-reentry, 2026-05-03) needs the Anthropic API key
            # from life-platform/ai-keys. Catches the "API access turned off" failure
            # mode that hit on the morning of 2026-05-03 — Anthropic disabled the
            # platform's key for billing reasons; daily-brief failed silently for
            # ~2 hours before Matthew noticed via the Grade-F email. The canary now
            # makes a tiny ($0.0001) call every 4h and emits CanaryAnthropicFail on
            # any 4xx/5xx, with a CloudWatch alarm wired to SNS.
            actions=["secretsmanager:GetSecretValue"],
            resources=[
                _secret_arn("life-platform/mcp-api-key"),
                _secret_arn("life-platform/ai-keys"),
            ],
        ),
        # ADR-062: canary's AI health-check now invokes Bedrock (was direct
        # Anthropic API). Catches the Bedrock access/throttle failure modes.
        _bedrock_statement(),
        iam.PolicyStatement(
            sid="SESAlert",
            # Canary sends an SES alert email when checks fail
            actions=["ses:SendEmail"],
            resources=[SES_IDENTITY],
        ),
    ]


def operational_pip_audit() -> list[iam.PolicyStatement]:
    """Pip audit: no AWS resource access needed — just runs pip-audit and reports."""
    return [
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
        ),
    ]


def operational_qa_smoke() -> list[iam.PolicyStatement]:
    """QA smoke: reads DDB + cache, S3, MCP API key, Lambda/Secrets inventory, sends SES report."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            # DDB table uses CMK — required for all GetItem/Query calls
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3Read",
            actions=["s3:GetObject"],
            # dashboard/* + config/* + blog/* (check_blog_links reads blog/index.html)
            resources=_s3("dashboard/*", "config/*", "blog/*"),
        ),
        iam.PolicyStatement(
            sid="S3List",
            actions=["s3:ListBucket"],
            resources=[BUCKET_ARN],
            # check_avatar_assets lists the character avatar sprites (was AccessDenied —
            # 2026-06-03). blog/* kept scoped for if/when that surface is revived.
            conditions={"StringLike": {"s3:prefix": ["dashboard/avatar/*", "blog/*"]}},
        ),
        iam.PolicyStatement(
            sid="SecretsGetMCP",
            # check_mcp_tool_calls: fetch MCP API key
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/mcp-api-key")],
        ),
        iam.PolicyStatement(
            sid="SecretsInventory",
            # check_lambda_secrets: list all secrets to validate Lambda SECRET_NAME refs
            actions=["secretsmanager:ListSecrets"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="LambdaList",
            # check_lambda_secrets: enumerate Lambda env vars to find stale SECRET_NAME values
            actions=["lambda:ListFunctions"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
        ),
    ]


def operational_key_rotator() -> list[iam.PolicyStatement]:
    """Key rotator: rotates MCP API key in Secrets Manager."""
    return [
        iam.PolicyStatement(
            sid="Secrets",
            actions=[
                "secretsmanager:GetSecretValue",
                "secretsmanager:PutSecretValue",
                "secretsmanager:UpdateSecret",
                "secretsmanager:DescribeSecret",
            ],
            resources=[_secret_arn("life-platform/mcp-api-key")],
        ),
    ]


def operational_data_export() -> list[iam.PolicyStatement]:
    """Data export: reads all DDB items, writes JSON/CSV to S3 exports/."""
    return _operational_base(
        ddb_actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan"],
        needs_s3_write=["exports/*"],
    )


def operational_delete_user_data() -> list[iam.PolicyStatement]:
    """Delete-user-data (P7.3): wipes a user's data from DDB + S3 + Secrets.
    Audit record written to DDB USER#admin#SOURCE#deletion_log.
    Refuses to operate on protected users (matthew/admin/system) — enforced in code.
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:Scan", "dynamodb:BatchWriteItem", "dynamodb:DeleteItem", "dynamodb:PutItem"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3DeleteUserData",
            actions=["s3:ListBucket"],
            resources=[BUCKET_ARN],
        ),
        iam.PolicyStatement(
            sid="S3DeleteUserObjects",
            # Restricted to user-prefixed paths (not matthew's data — Lambda
            # also refuses 'matthew' in code).
            actions=["s3:DeleteObject"],
            resources=_s3("raw/*", "uploads/*", "dashboard/*", "generated/*", "exports/*"),
        ),
        iam.PolicyStatement(
            sid="SecretsList",
            actions=["secretsmanager:ListSecrets"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="SecretsDelete",
            actions=["secretsmanager:DeleteSecret"],
            # Scoped to life-platform/<user_id>/* — owner secrets like
            # life-platform/ai-keys are NOT included.
            resources=[f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:life-platform/*/*"],
        ),
    ]


def operational_data_reconciliation() -> list[iam.PolicyStatement]:
    """Data reconciliation: reads DDB, sends SES report."""
    return _operational_base(
        ddb_actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan"],
        needs_s3_write=["reconciliation/*"],
        needs_ses=True,
    )


def operational_og_image_generator() -> list[iam.PolicyStatement]:
    """OG image generator: reads public_stats.json, writes PNG images to S3, invalidates CloudFront."""
    return [
        iam.PolicyStatement(
            sid="S3Read",
            actions=["s3:GetObject"],
            resources=_s3("generated/public_stats.json"),
        ),
        iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            resources=_s3("generated/assets/images/*"),
        ),
        iam.PolicyStatement(
            sid="CloudFrontInvalidation",
            actions=["cloudfront:CreateInvalidation"],
            resources=[CF_DIST_ARN],
        ),
    ]


def operational_site_stats_refresh() -> list[iam.PolicyStatement]:
    """Site stats refresh: invokes ingestion Lambdas, reads DDB, reads+writes public_stats.json."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3Read",
            actions=["s3:GetObject"],
            resources=_s3("site/*", "generated/public_stats.json"),
        ),
        iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            resources=_s3("site/*", "generated/public_stats.json"),
        ),
        iam.PolicyStatement(
            sid="InvokeIngestionLambdas",
            actions=["lambda:InvokeFunction"],
            resources=[
                f"arn:aws:lambda:{REGION}:{ACCT}:function:whoop-data-ingestion",
                f"arn:aws:lambda:{REGION}:{ACCT}:function:withings-data-ingestion",
                f"arn:aws:lambda:{REGION}:{ACCT}:function:habitify-data-ingestion",
            ],
        ),
    ]


def operational_insight_email_parser() -> list[iam.PolicyStatement]:
    """Insight email parser: reads from SES S3 drop, writes insight records to DDB."""
    return _operational_base(
        ddb_actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem"],
        needs_s3_read=["inbound-email/*"],
        needs_dlq=True,
    )


# ═════════════════════════════════════════════════════════════════════════
# WEB API STACK — 1 Lambda (read-only public site API)
# ═════════════════════════════════════════════════════════════════════════


def operational_email_subscriber() -> list[iam.PolicyStatement]:
    """Email subscriber Lambda (BS-03): DDB read+write (subscribers partition), KMS, SES send."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]


def site_api() -> list[iam.PolicyStatement]:
    """Site API Lambda: read access + limited writes for public interaction endpoints.

    Serves averagejoematt.com real-time data endpoints.
    GET endpoints are read-only. POST endpoints (vote, follow, checkin, nudge,
    submit_finding) perform targeted DDB writes to specific partitions.
    Yael directive: never expose MCP endpoint publicly — this is a
    separate, minimal-permission Lambda.
    WEB-WCT: Added S3 site/config/* read for /api/current_challenge endpoint.
    R17-04: Added dedicated Secrets read for life-platform/site-api-ai-key (isolated from main ai-keys).
    BL-02: Added S3 dashboard/* and generated/* read for /api/labs (clinical.json) and health check (public_stats.json).
    BL-02: Added S3 generated/findings/* write for /api/submit_finding.
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDBRead",
            actions=["dynamodb:GetItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="DynamoDBWrite",
            actions=["dynamodb:PutItem", "dynamodb:UpdateItem"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3SiteConfigRead",
            actions=["s3:GetObject"],
            resources=[
                f"{BUCKET_ARN}/site/config/*",
                f"{BUCKET_ARN}/config/*",
                f"{BUCKET_ARN}/dashboard/*",
                f"{BUCKET_ARN}/generated/*",
            ],
        ),
        iam.PolicyStatement(
            sid="S3FindingsWrite",
            actions=["s3:PutObject"],
            resources=[f"{BUCKET_ARN}/generated/findings/*"],
        ),
        iam.PolicyStatement(
            sid="AiKeySecret",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/site-api-ai-key")],
        ),
        iam.PolicyStatement(
            sid="SubscriberTokenSecret",  # #106 (2026-05-30): HMAC signing key for subscriber tokens.
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/subscriber-token-secret")],
        ),
        # Inference receipt (2026-06-13): read-only token metrics + budget tier.
        # CloudWatch read APIs don't support resource-level scoping.
        iam.PolicyStatement(
            sid="InferenceReceiptMetrics",
            actions=["cloudwatch:GetMetricStatistics", "cloudwatch:ListMetrics"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="BudgetTierRead",
            actions=["ssm:GetParameter"],
            resources=[f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/budget-tier"],
        ),
    ]


def site_api_ai() -> list[iam.PolicyStatement]:
    """Site API AI Lambda: read-only DDB + S3 config + Secrets Manager for AI endpoints.

    Handles /api/ask and /api/board_ask only. Separated from site_api() to isolate
    AI endpoint concurrency from data endpoints (ADR-036 fix).
    Phase 2.1 (2026-05-16): added scoped DDB write to RATE#* partition for
    DynamoDB-backed rate limiting (replaces in-memory dict that didn't survive
    warm-container distribution). Write scope enforced via dynamodb:LeadingKeys.
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDBRead",
            actions=["dynamodb:GetItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="DynamoDBRateLimit",
            actions=["dynamodb:UpdateItem"],
            resources=[TABLE_ARN],
            conditions={
                "ForAllValues:StringLike": {
                    "dynamodb:LeadingKeys": ["RATE#*"],
                },
            },
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3ConfigRead",
            actions=["s3:GetObject"],
            resources=[f"{BUCKET_ARN}/config/*", f"{BUCKET_ARN}/site/config/*"],
        ),
        iam.PolicyStatement(
            sid="AiKeySecret",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/site-api-ai-key")],
        ),
        iam.PolicyStatement(
            sid="SubscriberTokenSecret",  # #106 (2026-05-30): HMAC signing key for subscriber tokens.
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/subscriber-token-secret")],
        ),
        _bedrock_statement(),  # ADR-062: /api/ask + /api/board_ask now use Bedrock
    ]


# ═════════════════════════════════════════════════════════════════════════
# BS-08 / BS-SL2 — Sleep Reconciler + Circadian Compliance
# ═════════════════════════════════════════════════════════════════════════


def compute_sleep_reconciler() -> list[iam.PolicyStatement]:
    """BS-08: Unified Sleep Record — reads Whoop/Eight Sleep/Apple Health, writes sleep_unified."""
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


# ═════════════════════════════════════════════════════════════════════════
# MCP STACK — 1 Lambda
# ═════════════════════════════════════════════════════════════════════════


def mcp_server() -> list[iam.PolicyStatement]:
    """MCP server: DDB read/write (cache), S3 read (config + CGM only), secrets, no full-bucket access.

    S3 tightened from BUCKET_ARN/* → explicit prefixes only (Yael, item 5, v3.7.27):
      - config/*                      board personas, character config, profile
      - raw/matthew/cgm_readings/*    5-min glucose readings for CGM tools
    ListBucket scoped to cgm_readings prefix only.

    ADR-066 (2026-05-31): Hevy routine write-loop adds the hevy-write secret +
    the hevy/* SSM params for the `manage_hevy_routine` fat tool's commit and
    dry-run actions.
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:BatchGetItem"],
            resources=[TABLE_ARN, f"{TABLE_ARN}/index/*"],
        ),
        iam.PolicyStatement(
            # Scoped delete (2026-06-19, Yael): manage_meals.regroup_day prunes stale
            # MEAL#NN ordinals from the derived meal projection. DeleteItem is restricted
            # to the macrofactor_meals partition via dynamodb:LeadingKeys, so this
            # LLM-facing role can NEVER delete raw health data — even though it's a
            # single-table store (the no-write-to-raw test is code, not an IAM boundary;
            # this is the boundary). Mirrors the site_api_ai RATE#* LeadingKeys scoping.
            sid="DynamoDBMealPrune",
            actions=["dynamodb:DeleteItem"],
            resources=[TABLE_ARN],
            conditions={
                "ForAllValues:StringEquals": {
                    "dynamodb:LeadingKeys": ["USER#matthew#SOURCE#macrofactor_meals"],
                },
            },
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3Read",
            actions=["s3:GetObject"],
            resources=_s3("config/*", "raw/matthew/cgm_readings/*"),
        ),
        iam.PolicyStatement(
            sid="S3ListCGM",
            # Scoped list for fasting_glucose_validation tool (paginates raw/matthew/cgm_readings/)
            actions=["s3:ListBucket"],
            resources=[BUCKET_ARN],
            conditions={"StringLike": {"s3:prefix": ["raw/matthew/cgm_readings/*"]}},
        ),
        iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            resources=_s3("config/*"),
        ),
        iam.PolicyStatement(
            sid="Secrets",
            actions=["secretsmanager:GetSecretValue"],
            resources=[
                _secret_arn("life-platform/mcp-api-key"),
                _secret_arn("life-platform/ai-keys"),
                # TD-23 (2026-05-02): MCP write tools for Todoist read this secret
                # via mcp/tools_todoist.py:22. Without it, all create/update/close
                # Todoist tools fail with AccessDeniedException.
                _secret_arn("life-platform/todoist"),
                # ADR-066: manage_hevy_routine commits/dry-runs through the write secret.
                # Distinct from life-platform/hevy (read) per Yael bundling rule.
                _secret_arn("life-platform/hevy-write"),
            ],
        ),
        iam.PolicyStatement(
            sid="HevySsmParams",
            # ADR-066: cron + add-load gates read from SSM.
            actions=["ssm:GetParameter"],
            resources=[
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/hevy/cron_enabled",
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/hevy/autoreg_add_load_enabled",
            ],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]


def hevy_routine_cron() -> list[iam.PolicyStatement]:
    """Hevy routine cron (ADR-066): generates RoutineSpec IRs, persists to
    ROUTINE# partition, compiles via hevy_compiler, pushes to Hevy via the
    write secret. Reads SSM gates so it no-ops under Pause-Mode or while
    cron_enabled=false (default).
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3ConfigRead",
            actions=["s3:GetObject"],
            resources=_s3("config/*"),
        ),
        iam.PolicyStatement(
            sid="S3TemplateCacheWrite",
            actions=["s3:PutObject"],
            resources=_s3("config/hevy_template_cache.json"),
        ),
        iam.PolicyStatement(
            sid="HevyWriteSecret",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/hevy-write")],
        ),
        iam.PolicyStatement(
            sid="SsmGates",
            actions=["ssm:GetParameter"],
            resources=[
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/pause-mode",
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/budget-tier",
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/hevy/cron_enabled",
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/hevy/autoreg_add_load_enabled",
            ],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
        iam.PolicyStatement(
            sid="CloudWatchMetrics",
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
        ),
    ]


# ═════════════════════════════════════════════════════════════════════════
# WEB STACK — OG Image Lambda (WR-17)
# ═════════════════════════════════════════════════════════════════════════


def og_image() -> list[iam.PolicyStatement]:
    """OG Image Lambda: S3 read public_stats + write OG images to generated/."""
    return [
        iam.PolicyStatement(
            sid="S3ReadPublicStats",
            actions=["s3:GetObject"],
            resources=[f"{BUCKET_ARN}/generated/public_stats.json"],
        ),
        iam.PolicyStatement(
            sid="S3WriteOgImages",
            actions=["s3:PutObject"],
            resources=[f"{BUCKET_ARN}/generated/assets/images/*"],
        ),
    ]


# ── R19 Phase 6 CDK adoption: 4 unmanaged Lambdas ──


def food_delivery_ingestion() -> list[iam.PolicyStatement]:
    """Food delivery: DDB write, S3 read from uploads/food_delivery/."""
    return [
        iam.PolicyStatement(sid="DynamoDB", actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"], resources=[TABLE_ARN]),
        iam.PolicyStatement(sid="KMS", actions=["kms:Decrypt", "kms:GenerateDataKey"], resources=[KMS_KEY_ARN]),
        iam.PolicyStatement(sid="S3Read", actions=["s3:GetObject"], resources=[f"{BUCKET_ARN}/uploads/food_delivery/*"]),
        iam.PolicyStatement(sid="DLQ", actions=["sqs:SendMessage"], resources=[DLQ_ARN]),
    ]


def measurements_ingestion() -> list[iam.PolicyStatement]:
    """Measurements: DDB write, S3 read from imports/measurements/."""
    return [
        iam.PolicyStatement(sid="DynamoDB", actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"], resources=[TABLE_ARN]),
        iam.PolicyStatement(sid="KMS", actions=["kms:Decrypt", "kms:GenerateDataKey"], resources=[KMS_KEY_ARN]),
        iam.PolicyStatement(sid="S3Read", actions=["s3:GetObject"], resources=[f"{BUCKET_ARN}/imports/measurements/*"]),
    ]


def pipeline_health_check() -> list[iam.PolicyStatement]:
    """Pipeline health check: invoke Lambdas, read secrets, write DDB health_check.
    Phase 3.2 (2026-05-16): added cloudwatch:PutMetricData (compute-output metric)
    and sns:Publish on alerts-digest topic (compute-incomplete warning).
    """
    return [
        iam.PolicyStatement(sid="DynamoDB", actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"], resources=[TABLE_ARN]),
        iam.PolicyStatement(sid="KMS", actions=["kms:Decrypt", "kms:GenerateDataKey"], resources=[KMS_KEY_ARN]),
        iam.PolicyStatement(
            sid="LambdaInvoke", actions=["lambda:InvokeFunction"], resources=[f"arn:aws:lambda:{REGION}:{ACCT}:function:*"]
        ),
        iam.PolicyStatement(
            # ER/elite-review 2026-06-15: the health check only calls describe_secret
            # (existence/metadata) on a fixed source list — it NEVER reads secret
            # values. Dropped GetSecretValue so a compromised health-check can't
            # exfiltrate OAuth tokens / API keys it has no reason to read.
            sid="SecretsDescribe",
            actions=["secretsmanager:DescribeSecret"],
            resources=[f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:life-platform/*"],
        ),
        iam.PolicyStatement(sid="CloudWatchMetrics", actions=["cloudwatch:PutMetricData"], resources=["*"]),
        iam.PolicyStatement(
            sid="SnsPublishDigest",
            actions=["sns:Publish"],
            resources=[
                f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts",
                f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts-digest",
            ],
        ),
    ]


def subscriber_onboarding() -> list[iam.PolicyStatement]:
    """Subscriber onboarding: DDB read, SES send, Secrets Manager read."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB", actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem"], resources=[TABLE_ARN]
        ),
        iam.PolicyStatement(sid="KMS", actions=["kms:Decrypt", "kms:GenerateDataKey"], resources=[KMS_KEY_ARN]),
        iam.PolicyStatement(sid="SES", actions=["ses:SendEmail", "ses:SendRawEmail"], resources=[SES_IDENTITY]),
        iam.PolicyStatement(
            sid="SecretsRead",
            actions=["secretsmanager:GetSecretValue"],
            resources=[f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:life-platform/ai-keys*"],
        ),
    ]
