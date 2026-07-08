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

# Pillow image processing layer (HP-13: OG image generator)
PILLOW_LAYER_VERSION = 1
PILLOW_LAYER_ARN = f"arn:aws:lambda:{REGION}:{ACCT}:layer:pillow-layer:{PILLOW_LAYER_VERSION}"

# Garth + garminconnect layer (Garmin OAuth — native deps, x86_64)
GARTH_LAYER_VERSION = 2
GARTH_LAYER_ARN = f"arn:aws:lambda:{REGION}:{ACCT}:layer:garth-layer:{GARTH_LAYER_VERSION}"

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
