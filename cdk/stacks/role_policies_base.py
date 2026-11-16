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


def _charter_twin_list() -> "iam.PolicyStatement":
    """#5220: s3:ListBucket scoped to config/coaching/ so an ABSENT optional object (the private
    charter twin) answers 404 instead of 403 AccessDenied -- the loader then logs `absent`, and the
    swallowed-permission-denial filter fires only on a real denial. Lists key NAMES under one prefix."""
    return iam.PolicyStatement(
        sid="CharterTwinList",
        actions=["s3:ListBucket"],
        resources=[BUCKET_ARN],
        conditions={"StringLike": {"s3:prefix": ["config/coaching/*"]}},
    )


def _charter_twin_read() -> "iam.PolicyStatement":
    """#5220: GetObject on the ONE private charter twin object, for a role whose function reads the charter
    (training_charter.load_charter) but holds no `config/*` read. Pairs with `_charter_twin_list()`: a role needs
    BOTH to see 404 `absent` instead of 403 for the optional twin. Object-scoped, never `config/coaching/*`."""
    return iam.PolicyStatement(
        sid="CharterTwinRead",
        actions=["s3:GetObject"],
        resources=[f"{BUCKET_ARN}/config/coaching/training_charter.private.json"],
    )


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

    #4776 (open-weight trial, a SPIKE): the five ARNs under the marker below are EXACTLY the
    four Converse-family candidates `bedrock_client._MODEL_MAP` names — gpt-oss-120b, gpt-oss-20b
    and Qwen3-32B are in-region foundation models (no inference profile; region pinned to
    REGION), Nova Micro is INFERENCE_PROFILE-only (the `us.` profile plus the foundation model
    it fans out to, region wildcard like the Claude pair). The Converse API authorizes against
    the same `bedrock:InvokeModel` action. No feature is routed to any of them; the grant exists
    so the swap eval (#4771) and an adopted model can run under the Lambda roles. If the spike
    closes not-realized, DELETE the block — `tests/test_converse_adapter_4776.py` holds this list
    equal to the chokepoint's map in both directions, so a stale row reds. Additive IAM: CI's
    Plan gate (#2834) reads every bedrock ARN as out-of-namespace → OWNER-REQUIRED, so the
    deploy of this change is an attended `bash deploy/cdk_deploy.sh <Stack>` by the owner.
    """
    return iam.PolicyStatement(
        sid="BedrockInvoke",
        actions=["bedrock:InvokeModel"],
        resources=[
            f"arn:aws:bedrock:*:{ACCT}:inference-profile/us.anthropic.claude-*",
            "arn:aws:bedrock:*::foundation-model/anthropic.claude-*",
            # #1384: Titan-v2 embeddings for semantic recall (bedrock_client.embed_text).
            "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v2:0",
            # ── #4776 open-weight trial (see the docstring; delete the block if the spike closes not-realized)
            f"arn:aws:bedrock:{REGION}::foundation-model/openai.gpt-oss-120b-1:0",
            f"arn:aws:bedrock:{REGION}::foundation-model/openai.gpt-oss-20b-1:0",
            f"arn:aws:bedrock:{REGION}::foundation-model/qwen.qwen3-32b-v1:0",
            f"arn:aws:bedrock:*:{ACCT}:inference-profile/us.amazon.nova-micro-v1:0",
            "arn:aws:bedrock:*::foundation-model/amazon.nova-micro-v1:0",
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

    #5545: conditioned to `LifePlatform/AI` — the only namespace `bedrock_client` writes.
    A role whose code ALSO reaches another namespace carries that grant in its own
    statement (`_put_metric_data_statement`), so this one stays exactly what its sid says.
    """
    return _put_metric_data_statement("BedrockTelemetryMetric", NS_AI)


# ── #5545: every cloudwatch:PutMetricData grant names its namespaces ─────────────────────────
# PutMetricData takes no resource ARN, so before #5545 every grant was `"*"` with no condition:
# any of ~70 roles could write ANY namespace — including `LifePlatform/AI` and
# `LifePlatform/Budget`, the series `cost_governor_lambda` projects spend from. The one lever
# IAM offers is the `cloudwatch:namespace` condition key (single-valued; a StringEquals list is
# an OR). Each role's set is the namespaces its handler's import closure passes to
# `put_metric_data(Namespace=...)`; EMF lines printed to logs need no IAM and are NOT counted.
# `tests/test_putmetricdata_namespace_condition_5545.py` re-derives every set from the code and
# reds on a missing namespace (the metric would go dark) or an unconditioned grant.
NS_ROOT = "LifePlatform"  # bare root — daily_brief's ComputePipelineStaleness; `LifePlatform/*` would NOT match it
NS_AI = "LifePlatform/AI"
NS_AI_CANARY = "LifePlatform/AICanary"
NS_BUDGET = "LifePlatform/Budget"
NS_CANARY = "LifePlatform/Canary"
NS_COHERENCE = "LifePlatform/Coherence"
NS_COMPUTE = "LifePlatform/Compute"
NS_DYNAMODB = "LifePlatform/DynamoDB"
NS_EMAIL = "LifePlatform/Email"
NS_FRESHNESS = "LifePlatform/Freshness"
NS_HEVY_ROUTINE = "LifePlatform/HevyRoutine"
NS_INGEST_LIVENESS = "LifePlatform/IngestLiveness"
NS_INGEST_RECONCILIATION = "LifePlatform/IngestReconciliation"
NS_OAUTH = "LifePlatform/OAuth"
NS_PIPELINE = "LifePlatform/Pipeline"
NS_PODCAST = "LifePlatform/Podcast"
NS_PREDICTIONS = "LifePlatform/Predictions"
NS_QA = "LifePlatform/QA"
NS_READING = "LifePlatform/Reading"
NS_TELEGRAM = "LifePlatform/Telegram"
NS_TRAFFIC = "LifePlatform/Traffic"

#: What every ingestion Lambda reaches through the shared ingestion framework:
#: `common.item_size_guard` (DynamoDB) and `common.auth_breaker` (OAuth).
NS_INGEST_SHARED = (NS_DYNAMODB, NS_OAUTH)


def _metric_namespace_condition(*namespaces: str) -> dict:
    """The IAM condition block limiting PutMetricData to `namespaces` (exact match, OR'd)."""
    names = sorted(set(namespaces))
    if not names:
        raise ValueError("a PutMetricData grant must name at least one namespace (#5545)")
    return {"StringEquals": {"cloudwatch:namespace": names}}


def _put_metric_data_statement(sid: str, *namespaces: str) -> iam.PolicyStatement:
    """`cloudwatch:PutMetricData` on `"*"` (it takes no resource ARN) limited to `namespaces`.

    PutMetricData ONLY. `cloudwatch:namespace` is present in the request context of
    PutMetricData alone, so a read action (GetMetricData, GetMetricStatistics, ListMetrics)
    in the same statement would meet a condition whose key is absent — StringEquals on an
    absent key does not match, and the read would be denied. Reads stay in their own statement.
    """
    return iam.PolicyStatement(
        sid=sid,
        actions=["cloudwatch:PutMetricData"],
        resources=["*"],
        conditions=_metric_namespace_condition(*namespaces),
    )
