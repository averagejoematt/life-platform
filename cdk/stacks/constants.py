# cdk/stacks/constants.py — Single source of truth for shared infrastructure constants.
#
# CONF-01: All account/region/resource identifiers live here so a second environment
# (staging, DR) only requires environment variable overrides, not code edits.
#
import os

REGION = os.environ.get("CDK_REGION", "us-west-2")
ACCT = os.environ.get("CDK_ACCOUNT", "205930651321")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
CF_DIST_ID = os.environ.get("CF_DIST_ID", "E3S424OXQZ8NBE")

# ── DynamoDB TTL attribute (table-config-noop-ttl, #2799 residual — #951 recurrence) ──
# `life-platform` is imported into CDK (`Table.from_table_name`), so its
# TimeToLiveSpecification is not a CFN resource — it was enabled once out-of-band via
# the AWS API, with no declared source anywhere for which attribute name carries the
# expiry epoch. That gap is exactly how #951 shipped: email_subscriber_lambda wrote its
# expiry to `expires_at` while the table's live TTL was actually enabled on `ttl`
# (rate_limiter.py's attribute) — 550 rows accumulated forever behind a code comment
# claiming DDB would reap them, and nothing compared the two. This constant is now the
# ONE declared name; every writer of a TTL-bearing item should key its expiry field to
# it, and `deploy/drift_sentinel.py::check_dynamodb_ttl` asserts the live
# `describe_time_to_live` response actually matches (same declared-vs-live idiom as
# `check_s3_lifecycle`, deploy/drift_sentinel.py:525).
TABLE_TTL_ATTRIBUTE = os.environ.get("TABLE_TTL_ATTRIBUTE", "ttl")

# ── #3278: CloudWatch Logs retention tiers — the declared side of docs/DATA_GOVERNANCE.md ──
# The governance table's "Logs" section promised a 90-day security tier since 2026-05-17
# while `lambda_helpers.py` set ONE_MONTH uniformly (the only RetentionDays reference in
# cdk/) and the two Lambda@Edge auth gates — never CDK-created — sat at 30 in their two
# home regions and NEVER_EXPIRE in the five replica regions nobody had hand-set. Two
# defects, one cause: the tier existed only as prose. This registry is now the ONE
# declared source; three consumers derive from it and are parity-tested
# (`tests/test_security_log_retention_3278.py`):
#   1. cdk/stacks/lambda_helpers.py      — `log_retention` derived per function_name, by
#                                          construction (no per-call-site kwarg to forget)
#   2. deploy/sentinel_log_retention.py  — weekly declared-vs-live assertion across EVERY
#                                          enabled region (Lambda@Edge replicates a log
#                                          group into each region that ever served a request)
#   3. deploy/apply_log_retention.py     — the idempotent writer for the groups CDK cannot
#                                          own (edge replicas), dry-run by default
# The governance doc's row is asserted against these values, so "the table moves" and
# "the config moves" are the same edit here — never a silent doc-down reconcile.
LOG_RETENTION_DEFAULT_DAYS = 30  # "Lambda CloudWatch Logs (most)"
LOG_RETENTION_SECURITY_DAYS = 90  # "Lambda CloudWatch Logs (security tier)" — matches CloudTrail's 90d
# Lambda@Edge functions are published in us-east-1 and their replica log groups are named
# `/aws/lambda/us-east-1.<function>` in every region that executed them (including us-east-1).
EDGE_HOME_REGION = "us-east-1"
# function_name -> "regional" (CDK-owned, LifePlatformOperational) | "edge" (Lambda@Edge, out of CDK)
SECURITY_TIER_LOG_FUNCTIONS = {
    "life-platform-canary": "regional",
    "life-platform-key-rotator": "regional",
    "life-platform-dlq-consumer": "regional",
    "life-platform-cf-auth": "edge",
    "life-platform-buddy-auth": "edge",
}


def log_retention_days_for(function_name: str) -> int:
    """The retention tier a Lambda's log group must carry (pure — no CDK import)."""
    return LOG_RETENTION_SECURITY_DAYS if function_name in SECURITY_TIER_LOG_FUNCTIONS else LOG_RETENTION_DEFAULT_DAYS


def security_tier_log_group_names() -> dict[str, str]:
    """Every log-group name a security-tier function can appear under, -> its function.

    Regional functions log to `/aws/lambda/<fn>`; edge functions log to the replica name
    `/aws/lambda/<home-region>.<fn>` in every served region, plus the plain name in the
    home region if ever invoked directly. All candidates are listed so the sweep guards
    the SET rather than the two regions someone once hand-configured."""
    out: dict[str, str] = {}
    for fn, kind in SECURITY_TIER_LOG_FUNCTIONS.items():
        out[f"/aws/lambda/{fn}"] = fn
        if kind == "edge":
            out[f"/aws/lambda/{EDGE_HOME_REGION}.{fn}"] = fn
    return out


# ── DIL-027: the isolated backup of the irreplaceable zone ────────────────────
# `raw/` is the ONLY unrecomputable data on the platform (original wearable/API
# captures; every DDB metric, every derived artifact and the whole site can be
# rebuilt from it). It lived single-region, in one account, with versioning as its
# only protection — which survives an accidental overwrite but NOT a bucket
# deletion or a us-west-2 outage (`docs/DISASTER_RECOVERY.md` scored both
# "NOT RECOVERABLE").
#
# These four constants are the SINGLE source of truth for the replication build.
# Three consumers derive from them and are parity-tested against this file
# (`tests/test_raw_replication_dil027.py`), so a rename cannot half-land:
#   1. cdk/stacks/backup_stack.py    — the destination bucket + the replication role
#   2. deploy/s3_replication.json    — the source-side replication configuration
#   3. deploy/sentinel_replication.py — the weekly live assertion
#
# The destination region is deliberately NOT us-east-1: the site's control plane
# (ACM certs + CloudFront config, LifePlatformWeb) already lives there, so a
# us-east-1 event would hit the platform AND its backup at once. us-east-2 is
# independent of both us-west-2 and that dependency.
RAW_BACKUP_BUCKET = os.environ.get("RAW_BACKUP_BUCKET", "matthew-life-platform-raw-backup")
RAW_BACKUP_REGION = os.environ.get("RAW_BACKUP_REGION", "us-east-2")
RAW_REPLICATION_ROLE_NAME = os.environ.get("RAW_REPLICATION_ROLE_NAME", "life-platform-raw-replication")
RAW_BATCH_REPLICATION_ROLE_NAME = os.environ.get("RAW_BATCH_REPLICATION_ROLE_NAME", "life-platform-raw-batch-replication")
# The ONLY prefix replicated. Widening this is a deliberate cost + privacy decision,
# not a convenience edit — everything outside raw/ is recomputable by definition.
RAW_REPLICATION_PREFIX = "raw/"

# KMS key for DynamoDB encryption (SEC-06: env-overridable so staging can use a different key)
KMS_KEY_ID = os.environ.get("KMS_KEY_ID", "444438d1-a5e0-43b8-9391-3cd2d70dde4d")
# Phase 2.4 (2026-05-16): KMS CMK for S3 default encryption. Created in
# CoreStack as `s3_kms_key`. IAM does not resolve KMS alias ARNs — must use
# key ID ARN. Update this constant if the key is ever rotated/replaced.
S3_KMS_KEY_ID = os.environ.get("S3_KMS_KEY_ID", "5c50ca02-c187-4338-8704-5b27f1efafca")

# Anthropic model versions (CONF-04: env-overridable to avoid code changes on model upgrades)
AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

# SEC-08: SES sender domain — parameterized so staging can use a different verified identity.
SES_DOMAIN = os.environ.get("SES_DOMAIN", "mattsusername.com")

# SHARED LAYER RETIRED (#781, 2026-07-06). life-platform-shared-utils ended at
# v118; the full version history lives in git (this file, pre-#781). Shared code
# now ships inside every function's code bundle (deploy/build_bundle.py) — one
# distribution channel, no version pin to drift.

# ── Binary dependency layers ──────────────────────────────────────────────────
# These three ARNs are the platform's ENTIRE third-party runtime surface (the Lambda
# source tree is stdlib-only). Each is built by `deploy/build_lambda_layer.py`, whose
# LAYERS registry holds the pinned inputs; `lambdas/requirements/*.txt` is generated
# from the measured contents of the live version and is what pip-audit scans.
# Bumping a *_LAYER_VERSION below is step 3 of 4 — publish, bump, `cdk deploy` the
# owning stack, then `--promote` to re-derive the manifest (#2099).

# Pillow image processing layer (HP-13: OG image generator)
# Build: `python3 deploy/build_lambda_layer.py build pillow`. Consumers: og-image-generator,
# reading-cover-pipeline (both in LifePlatformOperational, which reads PILLOW_LAYER_ARN —
# it used to hardcode `pillow-layer:1`, so this constant was inert until #2099).
PILLOW_LAYER_VERSION = 2
PILLOW_LAYER_ARN = f"arn:aws:lambda:{REGION}:{ACCT}:layer:pillow-layer:{PILLOW_LAYER_VERSION}"

# Garth + garminconnect layer (Garmin OAuth — native deps, x86_64)
# Build: `python3 deploy/build_lambda_layer.py build garth`. Consumer: garmin-data-ingestion.
# Pinned at the 0.2.x ceiling on purpose — garminconnect 0.3.x drops garth and breaks this
# lambda's auth path (#1780); see the LAYERS['garth'] note before proposing a bump.
GARTH_LAYER_VERSION = 3
GARTH_LAYER_ARN = f"arn:aws:lambda:{REGION}:{ACCT}:layer:garth-layer:{GARTH_LAYER_VERSION}"

# lameenc (LAME MP3 encoder) layer (#1018: the Panel compresses its Gemini-TTS WAV
# to ~80 kbps spoken-word MP3 before publish — 16.6 MB → ~3.5 MB per episode).
# Build: `python3 deploy/build_lambda_layer.py build lameenc` (#2099). Attached only to
# coach-panel-podcast; lambdas/audio_encode.py fails open to WAV without it.
LAMEENC_LAYER_VERSION = 1
LAMEENC_LAYER_ARN = f"arn:aws:lambda:{REGION}:{ACCT}:layer:lameenc-layer:{LAMEENC_LAYER_VERSION}"

# ── Privacy mode (averagejoematt.com password gate) ──
# True  → attach cf-auth Lambda@Edge to AmjDistribution default behavior (HTML pages gated).
# False → public site, no auth required.
# Secret: life-platform/cf-auth (us-east-1).
# Bump CF_AUTH_LAMBDA_VERSION when republishing the cf-auth function code.
PRIVACY_MODE = os.environ.get("PRIVACY_MODE", "false").lower() == "true"
CF_AUTH_LAMBDA_VERSION = int(os.environ.get("CF_AUTH_LAMBDA_VERSION", "2"))
CF_AUTH_VERSION_ARN = f"arn:aws:lambda:us-east-1:{ACCT}:function:life-platform-cf-auth:{CF_AUTH_LAMBDA_VERSION}"

# ── #815 (R22-SEC-03): site-api origin-header guard secret ──
# Wires the previously-inert SEC-04 control (lambdas/web/site_api_common.py /
# site_api_lambda.py): when non-empty, site-api and site-api-ai 403 any request
# missing/mismatching the "X-AMJ-Origin" header. CloudFront (web_stack.py,
# us-east-1) must inject the header on the LambdaApiOrigin/AiLambdaOrigin origins
# and serve_stack.py (us-west-2) must set the identical value as the Lambdas'
# SITE_API_ORIGIN_SECRET env var — see stacks/secrets_helpers.py, which both
# stacks call so the value can never drift between the two channels.
#
# Not security-critical (defense-in-depth on an intentionally-public read-only
# API — CLAUDE.md "Site API is primarily read-only") — its value is expected to
# be visible in the synthesized CloudFormation template / CloudFront console,
# same posture as any other origin-verification header secret.
#
# Lives at this NAME as a PLAIN STRING secret (not JSON) in Secrets Manager,
# MULTI-REGION: primary in us-west-2 (co-located with every other
# life-platform/ secret), replica in us-east-1 for WebStack/CloudFront.
# CloudFormation's {{resolve:secretsmanager:...}} dynamic reference resolves
# only within the stack's own region (a cross-region ARN fails at deploy with
# ResourceNotFoundException — observed 2026-07-08), so secrets_helpers.py
# builds the region-local ARN per stack. The partial ARN (no random
# Secrets-Manager suffix) is intentional — Secret.from_secret_partial_arn
# resolves it without needing the suffix known at synth time.
SITE_API_ORIGIN_SECRET_NAME = "life-platform/site-api-origin-secret"  # noqa: S105 — secret name, not a secret value
