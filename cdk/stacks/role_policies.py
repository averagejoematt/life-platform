"""
role_policies.py — Centralized IAM policy definitions for all Life Platform Lambdas.

Each function returns a list of iam.PolicyStatement objects that exactly
replicate the existing console-created per-function IAM roles from SEC-1.

Audit source: aws iam get-role-policy on all 37 lambda-* roles (2026-03-09).
Organized by CDK stack: ingestion, compute, email, operational, mcp.

Policy principle: least-privilege per Lambda. No shared roles.
"""

from aws_cdk import aws_iam as iam
from stacks.constants import ACCT, REGION, TABLE_NAME, S3_BUCKET, KMS_KEY_ID, CF_DIST_ID, SES_DOMAIN  # CONF-01, SEC-06, SEC-08

# ── Constants ──────────────────────────────────────────────────────────────
TABLE_ARN = f"arn:aws:dynamodb:{REGION}:{ACCT}:table/{TABLE_NAME}"
BUCKET = S3_BUCKET
CF_DIST_ARN = f"arn:aws:cloudfront::{ACCT}:distribution/{CF_DIST_ID}"
BUCKET_ARN = f"arn:aws:s3:::{BUCKET}"
DLQ_ARN = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
KMS_KEY_ARN = f"arn:aws:kms:{REGION}:{ACCT}:key/{KMS_KEY_ID}"
SES_IDENTITY = f"arn:aws:ses:{REGION}:{ACCT}:identity/{SES_DOMAIN}"  # SEC-08: domain from constants


def _secret_arn(name: str) -> str:
    """Secrets Manager ARN with wildcard suffix for version IDs."""
    return f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:{name}*"


def _s3(*prefixes: str) -> list[str]:
    """S3 object ARNs for the given key prefixes."""
    return [f"{BUCKET_ARN}/{p}" for p in prefixes]


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

    # DynamoDB
    actions = ddb_actions or ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Query"]
    stmts.append(iam.PolicyStatement(
        sid="DynamoDB",
        actions=actions,
        resources=[TABLE_ARN],
    ))

    # KMS — required for all DDB operations (table is CMK-encrypted)
    stmts.append(iam.PolicyStatement(
        sid="KMS",
        actions=["kms:Decrypt", "kms:GenerateDataKey"],
        resources=[KMS_KEY_ARN],
    ))

    # S3 write (raw data)
    if not no_s3:
        prefix = s3_prefix or f"raw/matthew/{source}/*"
        write_resources = _s3(prefix) + (_s3(*extra_s3_write) if extra_s3_write else [])
        stmts.append(iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            resources=write_resources,
        ))

    # S3 read (if needed)
    if extra_s3_read:
        stmts.append(iam.PolicyStatement(
            sid="S3Read",
            actions=["s3:GetObject"],
            resources=_s3(*extra_s3_read),
        ))

    # Secrets
    if not no_secret and secret_name:
        secret_actions = ["secretsmanager:GetSecretValue", "secretsmanager:UpdateSecret"]
        if extra_secret_actions:
            secret_actions = list(set(secret_actions + extra_secret_actions))
        stmts.append(iam.PolicyStatement(
            sid="Secrets",
            actions=secret_actions,
            resources=[_secret_arn(secret_name)],
        ))

    # DLQ
    stmts.append(iam.PolicyStatement(
        sid="DLQ",
        actions=["sqs:SendMessage"],
        resources=[DLQ_ARN],
    ))

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
        ddb_actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"],
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
    """MacroFactor: DDB write + S3 raw/macrofactor, no API secret."""
    return _ingestion_base(
        "macrofactor",
        no_secret=True,
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
    Dedicated life-platform/webhook-key also exists — migration deferred.
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
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem",
                     "dynamodb:UpdateItem", "dynamodb:BatchGetItem"],
            resources=[TABLE_ARN, f"{TABLE_ARN}/index/*"],
        ),
    ]
    if needs_kms:
        stmts.append(iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ))
    if needs_s3_config:
        stmts.append(iam.PolicyStatement(
            sid="S3ConfigRead",
            actions=["s3:GetObject"],
            resources=_s3("config/*"),
        ))
    if needs_s3_write:
        stmts.append(iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            resources=_s3(*needs_s3_write),
        ))
    if needs_ai_keys:
        stmts.append(iam.PolicyStatement(
            sid="Secrets",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/ai-keys")],
        ))
    if needs_ses:
        stmts.append(iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY],
        ))
    stmts.append(iam.PolicyStatement(
        sid="DLQ",
        actions=["sqs:SendMessage"],
        resources=[DLQ_ARN],
    ))
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
        needs_s3_write=["site/*"],
    )


def compute_daily_metrics() -> list[iam.PolicyStatement]:
    """Daily metrics: DDB read+write, KMS."""
    return _compute_base(needs_kms=True)


def compute_daily_insight() -> list[iam.PolicyStatement]:
    """Daily insight compute (IC-2): reads DDB metrics, writes insight records, uses ai-keys for Haiku."""
    return _compute_base(
        needs_kms=True,  # writes to platform_memory + insights DDB partitions
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
    """Dashboard refresh: reads DDB, writes dashboard/data.json + buddy/data.json to S3."""
    return _compute_base(
        needs_kms=True,  # reads CMK-encrypted DDB table
        needs_s3_config=True,
        needs_s3_write=["dashboard/*", "buddy/*"],
    )


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
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem",
                     "dynamodb:UpdateItem", "dynamodb:BatchGetItem"],
            resources=[TABLE_ARN, f"{TABLE_ARN}/index/*"],
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
            sid="Secrets",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn(s) for s in ["life-platform/ai-keys"] + (extra_secrets or [])],
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]
    if needs_s3_write:
        stmts.append(iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            resources=_s3(*needs_s3_write),
        ))
    if extra_statements:
        stmts.extend(extra_statements)
    return stmts


def email_daily_brief() -> list[iam.PolicyStatement]:
    """Daily brief: DDB read, S3 config, ai-keys, SES, writes dashboard/ + buddy/ + site/ to S3.
    Risk-7: also emits ComputePipelineStaleness metric to CloudWatch.
    site/public_stats.json written via site_writer.py for averagejoematt.com.
    """
    return _email_base(
        needs_s3_write=["dashboard/*", "buddy/*", "site/*"],
        extra_statements=[
            iam.PolicyStatement(
                sid="CloudWatchMetrics",
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
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


def email_wednesday_chronicle() -> list[iam.PolicyStatement]:
    """Wednesday chronicle: DDB read, S3 config, ai-keys, SES, writes blog/* + site/journal/* to S3.
    site/journal/posts/week-{nn}/index.html + site/journal/posts.json written via publish_to_journal.
    """
    return _email_base(needs_s3_write=["blog/*", "site/journal/*"])


def email_weekly_plate() -> list[iam.PolicyStatement]:
    """Weekly Plate: DDB read, S3 config, ai-keys, SES."""
    return _email_base()


def email_monday_compass() -> list[iam.PolicyStatement]:
    """Monday Compass: DDB read, S3 config, ai-keys, SES."""
    return _email_base()


def email_brittany() -> list[iam.PolicyStatement]:
    """Brittany weekly email: DDB read, S3 config, ai-keys, SES."""
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
            resources=[SES_IDENTITY],
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
            resources=[SES_IDENTITY],
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
            resources=_s3("blog/*", "site/journal/*"),
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
            resources=[SES_IDENTITY],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
        iam.PolicyStatement(
            sid="OAuthSecretDescribe",
            # R8-ST4: DescribeSecret to read LastChangedDate for OAuth token health monitoring
            actions=["secretsmanager:DescribeSecret"],
            resources=[
                _secret_arn("life-platform/whoop"),
                _secret_arn("life-platform/withings"),
                _secret_arn("life-platform/strava"),
                _secret_arn("life-platform/garmin"),
            ],
        ),
    ]


def operational_dlq_consumer() -> list[iam.PolicyStatement]:
    """DLQ consumer: reads from DLQ, logs dead messages, sends SES summary."""
    return [
        iam.PolicyStatement(
            sid="SQS",
            actions=["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"],
            resources=[DLQ_ARN],
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
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
            # MCP check tries to fetch Bearer token — ai-keys is closest match
            # Note: canary skips MCP gracefully if key unavailable (non-fatal)
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/ai-keys")],
        ),
        iam.PolicyStatement(
            sid="SESAlert",
            # Canary sends an SES alert email when checks fail
            actions=["ses:SendEmail"],
            resources=["*"],
        ),
    ]


def operational_pip_audit() -> list[iam.PolicyStatement]:
    """Pip audit: no AWS resource access needed — just runs pip-audit and reports."""
    return [
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY],
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
            sid="S3ListBlog",
            actions=["s3:ListBucket"],
            resources=[BUCKET_ARN],
            conditions={"StringLike": {"s3:prefix": "blog/*"}},
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
            resources=[SES_IDENTITY],
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
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan"],
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
            resources=_s3("exports/*"),
        ),
    ]


def operational_data_reconciliation() -> list[iam.PolicyStatement]:
    """Data reconciliation: reads DDB, sends SES report."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan"],
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
            resources=_s3("reports/*"),
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY],
        ),
    ]


def operational_og_image_generator() -> list[iam.PolicyStatement]:
    """OG image generator: reads public_stats.json, writes PNG images to S3, invalidates CloudFront."""
    return [
        iam.PolicyStatement(
            sid="S3Read",
            actions=["s3:GetObject"],
            resources=_s3("site/data/*"),
        ),
        iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            resources=_s3("site/assets/images/*"),
        ),
        iam.PolicyStatement(
            sid="CloudFrontInvalidation",
            actions=["cloudfront:CreateInvalidation"],
            resources=["*"],
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
            resources=_s3("site/*"),
        ),
        iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            resources=_s3("site/*"),
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
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem"],
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
            resources=_s3("inbound-email/*"),
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]


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
            resources=[SES_IDENTITY],
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
    NO S3 write.
    Yael directive: never expose MCP endpoint publicly — this is a
    separate, minimal-permission Lambda.
    WEB-WCT: Added S3 site/config/* read for /api/current_challenge endpoint.
    R17-04: Added dedicated Secrets read for life-platform/site-api-ai-key (isolated from main ai-keys).
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
            ],
        ),
        iam.PolicyStatement(
            sid="AiKeySecret",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/site-api-ai-key")],
        ),
    ]


def site_api_ai() -> list[iam.PolicyStatement]:
    """Site API AI Lambda: read-only DDB + S3 config + Secrets Manager for AI endpoints.

    Handles /api/ask and /api/board_ask only. Separated from site_api() to isolate
    AI endpoint concurrency from data endpoints (ADR-036 fix).
    NO DDB writes — AI Lambda is strictly read-only.
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDBRead",
            actions=["dynamodb:GetItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt"],
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
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem",
                     "dynamodb:UpdateItem", "dynamodb:BatchGetItem"],
            resources=[TABLE_ARN, f"{TABLE_ARN}/index/*"],
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
            ],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]


# ═════════════════════════════════════════════════════════════════════════
# WEB STACK — OG Image Lambda (WR-17)
# ═════════════════════════════════════════════════════════════════════════

def og_image() -> list[iam.PolicyStatement]:
    """OG Image Lambda: S3 read-only for public_stats.json."""
    return [
        iam.PolicyStatement(
            sid="S3ReadPublicStats",
            actions=["s3:GetObject"],
            resources=[f"{BUCKET_ARN}/site/data/public_stats.json"],
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
    """Pipeline health check: invoke Lambdas, read secrets, write DDB health_check."""
    return [
        iam.PolicyStatement(sid="DynamoDB", actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"], resources=[TABLE_ARN]),
        iam.PolicyStatement(sid="KMS", actions=["kms:Decrypt", "kms:GenerateDataKey"], resources=[KMS_KEY_ARN]),
        iam.PolicyStatement(sid="LambdaInvoke", actions=["lambda:InvokeFunction"], resources=[f"arn:aws:lambda:{REGION}:{ACCT}:function:*"]),
        iam.PolicyStatement(sid="SecretsRead", actions=["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"], resources=[f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:life-platform/*"]),
    ]


def subscriber_onboarding() -> list[iam.PolicyStatement]:
    """Subscriber onboarding: DDB read, SES send, Secrets Manager read."""
    return [
        iam.PolicyStatement(sid="DynamoDB", actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem"], resources=[TABLE_ARN]),
        iam.PolicyStatement(sid="KMS", actions=["kms:Decrypt", "kms:GenerateDataKey"], resources=[KMS_KEY_ARN]),
        iam.PolicyStatement(sid="SES", actions=["ses:SendEmail", "ses:SendRawEmail"], resources=["*"]),
        iam.PolicyStatement(sid="SecretsRead", actions=["secretsmanager:GetSecretValue"], resources=[f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:life-platform/ai-keys*"]),
    ]

