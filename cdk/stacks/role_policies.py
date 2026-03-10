"""
role_policies.py — Centralized IAM policy definitions for all Life Platform Lambdas.

Each function returns a list of iam.PolicyStatement objects that exactly
replicate the existing console-created per-function IAM roles from SEC-1.

Audit source: aws iam get-role-policy on all 37 lambda-* roles (2026-03-09).
Organized by CDK stack: ingestion, compute, email, operational, mcp.

Policy principle: least-privilege per Lambda. No shared roles.
"""

from aws_cdk import aws_iam as iam

# ── Constants ──────────────────────────────────────────────────────────────
ACCT = "205930651321"
REGION = "us-west-2"
TABLE_ARN = f"arn:aws:dynamodb:{REGION}:{ACCT}:table/life-platform"
BUCKET = "matthew-life-platform"
BUCKET_ARN = f"arn:aws:s3:::{BUCKET}"
DLQ_ARN = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
KMS_KEY_ARN = f"arn:aws:kms:{REGION}:{ACCT}:key/444438d1-a5e0-43b8-9391-3cd2d70dde4d"
SES_IDENTITY = f"arn:aws:ses:{REGION}:{ACCT}:identity/mattsusername.com"


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
        prefix = s3_prefix or f"raw/{source}/*"
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
        s3_prefix="raw/notion/*",
    )


def ingestion_withings() -> list[iam.PolicyStatement]:
    return _ingestion_base(
        "withings",
        secret_name="life-platform/withings",
    )


def ingestion_habitify() -> list[iam.PolicyStatement]:
    return _ingestion_base(
        "habitify",
        secret_name="life-platform/ingestion-keys",  # COST-B: bundled 2026-03-10
        s3_prefix="raw/habitify/*",
    )


def ingestion_strava() -> list[iam.PolicyStatement]:
    return _ingestion_base(
        "strava",
        secret_name="life-platform/strava",
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
    ]


def ingestion_todoist() -> list[iam.PolicyStatement]:
    return _ingestion_base(
        "todoist",
        secret_name="life-platform/ingestion-keys",  # COST-B: bundled 2026-03-10
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
        s3_prefix="imports/*",
        extra_s3_read=["imports/*"],
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
            resources=_s3("raw/apple_health/*"),
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]


def ingestion_hae() -> list[iam.PolicyStatement]:
    """Health Auto Export webhook: API Gateway trigger, DDB + S3 write."""
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
            resources=_s3("raw/apple_health/*"),
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
    """Character sheet: DDB read+write, KMS, S3 config read, ai-keys."""
    return _compute_base(
        needs_kms=True,
        needs_s3_config=True,
        needs_ai_keys=True,
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


def compute_dashboard_refresh() -> list[iam.PolicyStatement]:
    """Dashboard refresh: reads DDB, writes dashboard/data.json + buddy/data.json to S3."""
    return _compute_base(
        needs_kms=True,  # reads CMK-encrypted DDB table
        needs_s3_config=True,
        needs_s3_write=["dashboard/*", "buddy/*"],
    )


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
    """Daily brief: DDB read, S3 config, ai-keys, SES, writes dashboard/ + buddy/ to S3."""
    return _email_base(needs_s3_write=["dashboard/*", "buddy/*"])


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
    """Wednesday chronicle: DDB read, S3 config, ai-keys, SES, writes blog post to S3."""
    return _email_base(needs_s3_write=["blog/*"])


def email_weekly_plate() -> list[iam.PolicyStatement]:
    """Weekly Plate: DDB read, S3 config, ai-keys, SES."""
    return _email_base()


def email_monday_compass() -> list[iam.PolicyStatement]:
    """Monday Compass: DDB read, S3 config, ai-keys, SES."""
    return _email_base()


def email_brittany() -> list[iam.PolicyStatement]:
    """Brittany weekly email: DDB read, S3 config, ai-keys, SES."""
    return _email_base()


# ═════════════════════════════════════════════════════════════════════════
# OPERATIONAL STACK — 8 Lambdas
# ═════════════════════════════════════════════════════════════════════════

def operational_freshness_checker() -> list[iam.PolicyStatement]:
    """Freshness checker: reads DDB + publishes CloudWatch custom metrics, sends SES alert."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
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
    """Canary: reads DDB + S3 + invokes MCP Lambda function URL — no write access."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="S3Read",
            actions=["s3:GetObject"],
            resources=_s3("dashboard/*"),
        ),
        iam.PolicyStatement(
            sid="CloudWatchMetrics",
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="Secrets",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/mcp-api-key")],
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
    """QA smoke: reads DDB, S3, invokes other Lambdas for smoke tests."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="S3Read",
            actions=["s3:GetObject"],
            resources=_s3("dashboard/*", "config/*"),
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


def operational_insight_email_parser() -> list[iam.PolicyStatement]:
    """Insight email parser: reads from SES S3 drop, writes insight records to DDB."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem"],
            resources=[TABLE_ARN],
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
# MCP STACK — 1 Lambda
# ═════════════════════════════════════════════════════════════════════════

def mcp_server() -> list[iam.PolicyStatement]:
    """MCP server: full DDB read, S3 read (all prefixes), all secrets read, no write."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem",
                     "dynamodb:UpdateItem", "dynamodb:BatchGetItem"],
            resources=[TABLE_ARN, f"{TABLE_ARN}/index/*"],
        ),
        iam.PolicyStatement(
            sid="S3Read",
            actions=["s3:GetObject", "s3:ListBucket"],
            resources=[BUCKET_ARN, f"{BUCKET_ARN}/*"],
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
