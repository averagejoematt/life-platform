"""role_policies_base.py — the shared ARN constants and statement helpers every
`role_policies_*` module builds on (#2604 extraction).

This is the one definition of the table, bucket, DLQ, KMS key and SES identity
ARNs. It is imported by the per-domain policy modules and re-exported by
`role_policies.py`, so `rp.TABLE_ARN` and `rp._s3(...)` keep resolving for the
stacks, the sibling modules and the IAM linters that read them.
"""

import sys
from pathlib import Path

from aws_cdk import aws_iam as iam

from stacks.constants import ACCT, CF_DIST_ID, KMS_KEY_ID, REGION, S3_BUCKET, SES_DOMAIN, TABLE_NAME  # CONF-01, SEC-06, SEC-08

# #3568: the site sending domain comes from the ONE registry, not a second
# hand-typed constant — same sys.path pattern ingestion_stack.py uses.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "lambdas"))
from common.email_identity import SITE_DOMAIN  # noqa: E402

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
# #3568: reader mail is From the SITE domain, which is a SECOND SES identity.
# The grant is resource-scoped per identity, so moving the From address without
# this ARN is an AccessDeniedException at send time, not a config warning — the
# same failure mode as the config-set omission noted above (2 days of dark
# daily-briefs). Added ONLY to the five reader-facing senders below; owner and
# operational mail keeps the single-identity grant.
SES_SITE_IDENTITY = f"arn:aws:ses:{REGION}:{ACCT}:identity/{SITE_DOMAIN}"


def _ses_reader_resources() -> list[str]:
    """A FRESH resource list for a reader-facing sender.

    A function, not a module-level list: three policy functions use it, and a
    shared mutable default that any one of them (or CDK) appended to would
    silently widen the other two.

    Underscore-prefixed on purpose. `tests/test_iam_secrets_consistency.py`
    discovers policy factories as "every public function in a role_policies_*
    module" and calls each expecting `list[PolicyStatement]`; a public helper
    returning `list[str]` aborts collection for the whole suite. `_s3`,
    `_secret_arn` and `_bedrock_statement` carry the prefix for the same reason.
    """
    return [SES_IDENTITY, SES_SITE_IDENTITY, SES_CONFIG_SET_ARN]


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

    #3563: THIS GRANT HAS A COMPANION — see `_bedrock_telemetry_statement()`.
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


def _bedrock_telemetry_statement() -> iam.PolicyStatement:
    """#3563: the companion to `_bedrock_statement()` — the right to RECORD the call.

    `lambdas/ai/bedrock_client.invoke()` emits three telemetry families to
    CloudWatch on every single call — cost (`AnthropicInputTokens`,
    `AnthropicOutputTokens`, `EstimatedCostUSD`), truncation (`TruncatedResponses`,
    `TruncatedCostUSD`) and prompt-cache (`PromptCacheNoOp`) — and every emit is
    wrapped in `except Exception: print("[ERROR] ... datapoints DROPPED")` so that
    telemetry can never break an AI call. That fail-soft is correct (ADR-104) and it
    is also, by construction, silent: a role that can `bedrock:InvokeModel` and
    cannot `cloudwatch:PutMetricData` bills Bedrock in full and records nothing,
    forever, with green tests.

    That is not hypothetical. #2974 found it once on the visual-qa CI role. On
    2026-09-14 a 30-day log sweep for #3563 found it again on TWELVE production
    roles (8 with live dropped datapoints in the window, ongoing that morning:
    ai-review-pack, chronicle-approve, coach-nudge, monday-compass, monthly-digest,
    nutrition-review, weekly-digest, weekly-plate). Those are the same series
    `cost_governor_lambda` reads to project Bedrock spend against the ADR-133
    ceiling, so the undercount lands on the budget, not just a dashboard.

    `resources=["*"]`: PutMetricData accepts no resource ARN (the account-level
    registry in `tests/test_iam_twin_free_3336.py` records the probe).
    Deliberately a SEPARATE sid from the ad-hoc `CloudWatchMetrics` /
    `PublishedMetric` / `DeliveryHeartbeatMetric` grants some roles already carry:
    those are a role's own feature metric and may be narrowed or dropped with that
    feature, while this one is owed to every Bedrock caller as such. A role holding
    both simply holds two Allows for the same call — valid, and honest about which
    reason is which. `tests/test_bedrock_telemetry_iam_parity_3563.py` derives the
    pairing from the role family and reds on the next role that skips it.
    """
    return iam.PolicyStatement(
        sid="BedrockTelemetryMetric",
        actions=["cloudwatch:PutMetricData"],
        resources=["*"],
    )
