"""role_policies_base.py — the shared ARN constants and statement helpers every
`role_policies_*` module builds on (#2604 extraction).

This is the one definition of the table, bucket, DLQ, KMS key and SES identity
ARNs. It is imported by the per-domain policy modules and re-exported by
`role_policies.py`, so `rp.TABLE_ARN` and `rp._s3(...)` keep resolving for the
stacks, the sibling modules and the IAM linters that read them.
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
    inference — both the cross-region inference profiles (`us.anthropic.claude-*`,
    which on-demand 4.x models require) AND the underlying foundation-model
    ARNs the profiles fan out to (InvokeModel is authorized against both) — plus
    Amazon Titan-v2 text embeddings (#1384, semantic recall): a bare
    foundation-model id (no inference profile), routed through the same
    bedrock_client chokepoint (ADR-062). Region wildcard because the us. profile
    routes across us-east-1/us-east-2/us-west-2.
    """
    return iam.PolicyStatement(
        sid="BedrockInvoke",
        actions=["bedrock:InvokeModel"],
        resources=[
            f"arn:aws:bedrock:*:{ACCT}:inference-profile/us.anthropic.claude-*",
            "arn:aws:bedrock:*::foundation-model/anthropic.claude-*",
            # #1384: Titan-v2 embeddings for semantic recall (bedrock_client.embed_text).
            "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v2:0",
        ],
    )
