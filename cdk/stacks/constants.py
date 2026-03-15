# cdk/stacks/constants.py — Single source of truth for shared infrastructure versions.
#
# SHARED_LAYER_VERSION: Update this when a new shared utils layer is published.
# Consumers: ingestion_stack.py, email_stack.py (and any future stacks that attach the layer).
#
# After updating:
#   1. Change the version number below
#   2. Run: npx cdk deploy LifePlatformIngestion LifePlatformEmail
#   3. Run: bash deploy/post_cdk_reconcile_smoke.sh
#   4. CI plan job verifies all consumers are on the new version

REGION = "us-west-2"
ACCT   = "205930651321"

# Shared utils layer — update on every layer rebuild (bash deploy/build_layer.sh)
SHARED_LAYER_VERSION = 10  # ADR-027: v10 adds stable mcp/ core modules

SHARED_LAYER_ARN = (
    f"arn:aws:lambda:{REGION}:{ACCT}:layer:life-platform-shared-utils:{SHARED_LAYER_VERSION}"
)
