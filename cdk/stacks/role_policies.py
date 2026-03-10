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
        secret_name="life-platform/notion",
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
        secret_name="life-platform/api-keys",
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
        secret_name="life-platform/todoist",
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
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]


def ingestion_dropbox() -> list[iam.PolicyStatement]:
    return _ingestion_base(
        "dropbox",
        secret_name="life-platform/dropbox",
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
        needs_s3_config=True,
        needs_ai_keys=True,
        needs_ses=True,
    )


def compute_character_sheet() -> list[iam.PolicyStatement]:
    """Character sheet: DDB read+write, S3 config read, ai-keys."""
    return _compute_base(
        needs_s3_config=True,
        needs_ai_keys=True,
    )


def compute_daily_metrics() -> list[iam.PolicyStatement]:
    """Daily metrics: DDB read+write, KMS."""
    return _compute_base(needs_kms=True)


def compute_daily_insight() -> list[iam.PolicyStatement]:
    """Daily insight: DDB read+write, KMS, ai-keys."""
    return _compute_base(needs_kms=True, needs_ai_keys=True)


def compute_adaptive_mode() -> list[iam.PolicyStatement]:
    """Adaptive mode: DDB read+write."""
    return _compute_base()


def compute_hypothesis_engine() -> list[iam.PolicyStatement]:
    """Hypothesis engine: DDB read+write, ai-keys."""
    return _compute_base(needs_ai_keys=True)


def compute_dashboard_refresh() -> list[iam.PolicyStatement]:
    """Dashboard refresh: DDB read, S3 config read + dashboard/buddy write."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan",
                     "dynamodb:PutItem", "dynamodb:BatchGetItem"],
            resources=[TABLE_ARN, f"{TABLE_ARN}/index/*"],
        ),
        iam.PolicyStatement(
            sid="S3Read",
            actions=["s3:GetObject", "s3:ListBucket"],
            resources=[BUCKET_ARN, *_s3("config/*", "dashboard/*", "buddy/*")],
        ),
        iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            resources=_s3("dashboard/*", "buddy/*"),
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]


# ═══════════════════════════════════════════════════════════════════════════
# EMAIL STACK — 8 Lambdas
# Pattern: DDB read+write, KMS, S3 config read + dashboard write, ai-keys, SES
# ═══════════════════════════════════════════════════════════════════════════

def _email_base(
    extra_s3_read: list[str] = None,
    extra_s3_write: list[str] = None,
    needs_kms: bool = True,
    needs_todoist: bool = False,
) -> list[iam.PolicyStatement]:
    """Build standard email/digest role policies."""
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

    # S3 read
    read_prefixes = ["config/*"] + (extra_s3_read or [])
    stmts.append(iam.PolicyStatement(
        sid="S3Read",
        actions=["s3:GetObject", "s3:HeadObject"],
        resources=_s3(*read_prefixes),
    ))

    # S3 write
    write_prefixes = ["dashboard/*"] + (extra_s3_write or [])
    stmts.append(iam.PolicyStatement(
        sid="S3Write",
        actions=["s3:PutObject"],
        resources=_s3(*write_prefixes),
    ))

    # Secrets — ai-keys for all email Lambdas
    secret_resources = [_secret_arn("life-platform/ai-keys")]
    if needs_todoist:
        secret_resources.append(_secret_arn("life-platform/todoist"))
    stmts.append(iam.PolicyStatement(
        sid="Secrets",
        actions=["secretsmanager:GetSecretValue"],
        resources=secret_resources,
    ))

    # SES
    stmts.append(iam.PolicyStatement(
        sid="SES",
        actions=["ses:SendEmail", "sesv2:SendEmail"],
        resources=[SES_IDENTITY],
    ))

    # DLQ
    stmts.append(iam.PolicyStatement(
        sid="DLQ",
        actions=["sqs:SendMessage"],
        resources=[DLQ_ARN],
    ))

    return stmts


def email_daily_brief() -> list[iam.PolicyStatement]:
    """Daily Brief: full read + dashboard/buddy write + CGM read."""
    return _email_base(
        extra_s3_read=["raw/cgm_readings/*"],
        extra_s3_write=["buddy/*"],
    )


def email_weekly_digest() -> list[iam.PolicyStatement]:
    return _email_base()


def email_monthly_digest() -> list[iam.PolicyStatement]:
    return _email_base()


def email_nutrition_review() -> list[iam.PolicyStatement]:
    return _email_base()


def email_wednesday_chronicle() -> list[iam.PolicyStatement]:
    """Chronicle: also writes to blog/ prefix."""
    return _email_base(extra_s3_write=["blog/*"])


def email_weekly_plate() -> list[iam.PolicyStatement]:
    return _email_base()


def email_monday_compass() -> list[iam.PolicyStatement]:
    """Monday Compass: needs todoist secret for task context."""
    return _email_base(needs_todoist=True)


def email_brittany() -> list[iam.PolicyStatement]:
    """Brittany email: DDB read + S3 config/dashboard/buddy read, SES, ai-keys."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:BatchGetItem"],
            resources=[TABLE_ARN, f"{TABLE_ARN}/index/*"],
        ),
        iam.PolicyStatement(
            sid="S3Read",
            actions=["s3:GetObject", "s3:HeadObject"],
            resources=_s3("config/*", "dashboard/*", "buddy/*", "avatar/*"),
        ),
        iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            resources=_s3("dashboard/*", "buddy/*"),
        ),
        iam.PolicyStatement(
            sid="Secrets",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/ai-keys")],
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


# ═══════════════════════════════════════════════════════════════════════════
# OPERATIONAL STACK — 7 Lambdas (freshness-checker excluded)
# ═══════════════════════════════════════════════════════════════════════════

def operational_dlq_consumer() -> list[iam.PolicyStatement]:
    """DLQ consumer: read DLQ, invoke ingestion Lambdas, archive to S3, SES alert."""
    return [
        iam.PolicyStatement(
            sid="DLQAccess",
            actions=["sqs:ReceiveMessage", "sqs:DeleteMessage",
                     "sqs:GetQueueAttributes", "sqs:GetQueueUrl"],
            resources=[DLQ_ARN],
        ),
        iam.PolicyStatement(
            sid="LambdaRetryInvoke",
            actions=["lambda:InvokeFunction"],
            resources=[f"arn:aws:lambda:{REGION}:{ACCT}:function:*-data-ingestion"],
        ),
        iam.PolicyStatement(
            sid="S3Archive",
            actions=["s3:PutObject"],
            resources=_s3("dead-letter-archive/*"),
        ),
        iam.PolicyStatement(
            sid="SESAlert",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY],
        ),
    ]


def operational_canary() -> list[iam.PolicyStatement]:
    """Canary: DDB CANARY#* only (condition), S3 canary/*, CW metrics, SES, Secrets."""
    return [
        iam.PolicyStatement(
            sid="DDBCanaryOnly",
            actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:DeleteItem"],
            resources=[TABLE_ARN],
            conditions={
                "ForAllValues:StringLike": {
                    "dynamodb:LeadingKeys": ["CANARY#*"],
                },
            },
        ),
        iam.PolicyStatement(
            sid="S3CanaryPrefix",
            actions=["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
            resources=_s3("canary/*"),
        ),
        iam.PolicyStatement(
            sid="CloudWatchMetrics",
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
            conditions={
                "StringEquals": {
                    "cloudwatch:namespace": "LifePlatform/Canary",
                },
            },
        ),
        iam.PolicyStatement(
            sid="SESAlert",
            actions=["sesv2:SendEmail"],
            resources=[SES_IDENTITY],
        ),
        iam.PolicyStatement(
            sid="SecretsAPIKey",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/api-keys")],
        ),
    ]


def operational_pip_audit() -> list[iam.PolicyStatement]:
    """Pip audit: S3 read requirements, SES report."""
    return [
        iam.PolicyStatement(
            sid="S3Read",
            actions=["s3:GetObject", "s3:ListBucket"],
            resources=[BUCKET_ARN, *_s3("requirements/*", "lambdas/requirements/*")],
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY],
        ),
    ]


def operational_qa_smoke() -> list[iam.PolicyStatement]:
    """QA smoke: DDB read, S3 read, SES report."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="S3Read",
            actions=["s3:GetObject"],
            resources=_s3("config/*", "dashboard/*"),
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY],
        ),
    ]


def operational_key_rotator() -> list[iam.PolicyStatement]:
    """Key rotator: Secrets Manager full rotation lifecycle on MCP API key."""
    return [
        iam.PolicyStatement(
            sid="SecretsManagerRotation",
            actions=["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue",
                     "secretsmanager:DescribeSecret", "secretsmanager:UpdateSecretVersionStage"],
            resources=[_secret_arn("life-platform/mcp-api-key-")],
        ),
    ]


def operational_data_export() -> list[iam.PolicyStatement]:
    """Data export: DDB Scan + S3 exports write."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:Scan", "dynamodb:Query", "dynamodb:GetItem"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            resources=_s3("exports/*"),
        ),
    ]


def operational_data_reconciliation() -> list[iam.PolicyStatement]:
    """Data reconciliation: DDB read, S3 archive, SES report."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            resources=_s3("reconciliation/*"),
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY],
        ),
    ]


# ═══════════════════════════════════════════════════════════════════════════
# MCP STACK — 1 Lambda
# ═══════════════════════════════════════════════════════════════════════════

def mcp_server() -> list[iam.PolicyStatement]:
    """MCP server: broad DDB access, S3 dashboard/buddy/exports, MCP API key."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan",
                     "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem",
                     "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem"],
            resources=[TABLE_ARN, f"{TABLE_ARN}/index/*"],
        ),
        iam.PolicyStatement(
            sid="S3ReadWrite",
            actions=["s3:GetObject", "s3:PutObject"],
            resources=_s3("dashboard/*", "buddy/*", "profile.json", "config/*"),
        ),
        iam.PolicyStatement(
            sid="S3ExportWrite",
            actions=["s3:PutObject"],
            resources=_s3("exports/*"),
        ),
        iam.PolicyStatement(
            sid="S3ListBucket",
            actions=["s3:ListBucket"],
            resources=[BUCKET_ARN],
        ),
        iam.PolicyStatement(
            sid="SecretsMcpKey",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/mcp-api-key")],
        ),
    ]


# ═══════════════════════════════════════════════════════════════════════════
# PREVIOUSLY UNMANAGED LAMBDAS — added v3.4.0
# ═══════════════════════════════════════════════════════════════════════════

def compute_failure_pattern() -> list[iam.PolicyStatement]:
    """Failure pattern compute: DDB read+write, S3 config read, ai-keys."""
    return _compute_base(
        needs_s3_config=True,
        needs_ai_keys=True,
    )


def operational_freshness_checker() -> list[iam.PolicyStatement]:
    """Freshness checker: DDB read, SNS publish, SES email."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="SNSPublish",
            actions=["sns:Publish"],
            resources=[f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"],
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY],
        ),
        iam.PolicyStatement(
            sid="CloudWatchMetrics",
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
            conditions={
                "StringEquals": {
                    "cloudwatch:namespace": "LifePlatform/Freshness",
                },
            },
        ),
    ]


def operational_insight_email_parser() -> list[iam.PolicyStatement]:
    """Insight email parser: SES-triggered, DDB write, S3 read inbound, SES reply."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:PutItem"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="S3Read",
            actions=["s3:GetObject"],
            resources=_s3("raw/inbound_email/*"),
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail"],
            resources=[SES_IDENTITY],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]
