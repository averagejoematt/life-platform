# cdk/stacks/constants.py — Single source of truth for shared infrastructure constants.
#
# CONF-01: All account/region/resource identifiers live here so a second environment
# (staging, DR) only requires environment variable overrides, not code edits.
#
# SHARED_LAYER_VERSION: Update this when a new shared utils layer is published.
# Consumers: ingestion_stack.py, email_stack.py (and any future stacks that attach the layer).
#
# After updating layer version:
#   1. Change the version number below
#   2. Run: npx cdk deploy LifePlatformIngestion LifePlatformEmail
#   3. Run: bash deploy/post_cdk_reconcile_smoke.sh
#   4. CI plan job verifies all consumers are on the new version

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

# Shared utils layer — update on every layer rebuild (bash deploy/build_layer.sh)
SHARED_LAYER_VERSION = 97  # v97: #392 source_registry (canonical behavioral-vs-infra source classification)

SHARED_LAYER_ARN = f"arn:aws:lambda:{REGION}:{ACCT}:layer:life-platform-shared-utils:{SHARED_LAYER_VERSION}"

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
