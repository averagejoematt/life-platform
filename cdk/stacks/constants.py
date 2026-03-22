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

# Anthropic model versions (CONF-04: env-overridable to avoid code changes on model upgrades)
AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

# SEC-08: SES sender domain — parameterized so staging can use a different verified identity.
SES_DOMAIN = os.environ.get("SES_DOMAIN", "mattsusername.com")

# Shared utils layer — update on every layer rebuild (bash deploy/build_layer.sh)
SHARED_LAYER_VERSION = 10  # ADR-027: v10 adds stable mcp/ core modules

SHARED_LAYER_ARN = (
    f"arn:aws:lambda:{REGION}:{ACCT}:layer:life-platform-shared-utils:{SHARED_LAYER_VERSION}"
)
