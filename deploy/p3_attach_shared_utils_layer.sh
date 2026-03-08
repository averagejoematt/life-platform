#!/bin/bash
# p3_attach_shared_utils_layer.sh — Attach life-platform-shared-utils layer to all consumer Lambdas
#
# Run AFTER p3_build_shared_utils_layer.sh.
# Usage: ./deploy/p3_attach_shared_utils_layer.sh <LAYER_VERSION_ARN>
#
# Example:
#   ./deploy/p3_attach_shared_utils_layer.sh \
#     arn:aws:lambda:us-west-2:205930651321:layer:life-platform-shared-utils:1
#
# Lambdas that consume shared utils (retry_utils / board_loader / insight_writer / scoring_engine):
#   AI email/digest Lambdas (7): daily-brief, weekly-digest, monthly-digest,
#     nutrition-review, wednesday-chronicle, weekly-plate, monday-compass
#   Anomaly detector (uses board_loader)
#   Compute Lambdas (2): character-sheet-compute, daily-insight-compute, hypothesis-engine
#
# NOTE: After attaching, redeploy each Lambda WITHOUT extra-files for shared modules.
# deploy_unified.sh will handle this automatically once this layer is registered.

set -euo pipefail
chmod +x "$0"
REGION="us-west-2"

[ $# -ge 1 ] || { echo "Usage: $0 <LAYER_VERSION_ARN>"; exit 1; }
LAYER_ARN="$1"

# Validate it looks like a layer ARN
[[ "$LAYER_ARN" == arn:aws:lambda:*:layer:* ]] || { echo "❌ Does not look like a layer ARN: $LAYER_ARN"; exit 1; }

echo "Attaching layer: $LAYER_ARN"
echo ""

LAMBDAS=(
    # Email / digest Lambdas (use board_loader, retry_utils, insight_writer, html_builder, ai_calls)
    "daily-brief"
    "weekly-digest"
    "monthly-digest"
    "nutrition-review"
    "wednesday-chronicle"
    "weekly-plate"
    "monday-compass"
    "anomaly-detector"
    "brittany-weekly-email"
    # Compute Lambdas (use scoring_engine, character_engine, output_writers)
    "character-sheet-compute"
    "daily-metrics-compute"
    "daily-insight-compute"
    "adaptive-mode-compute"
    "hypothesis-engine"
    # Dashboard refresh (uses output_writers)
    "dashboard-refresh"
)

ATTACHED=0
FAILED=0

for fn in "${LAMBDAS[@]}"; do
    echo "  Attaching to $fn..."
    # Get existing layers so we don't clobber them (e.g. garmin has its own)
    EXISTING=$(aws lambda get-function-configuration \
        --function-name "$fn" \
        --region "$REGION" \
        --query "Layers[*].Arn" \
        --output json \
        --no-cli-pager 2>/dev/null || echo "[]")

    # Build merged layer list: existing + new (deduplicated by layer name prefix)
    # Strip any previous version of this same layer, then add new version
    NEW_LAYERS=$(python3 -c "
import json, sys

existing = json.loads('$EXISTING') if '$EXISTING' != '[]' else []
new_arn = '$LAYER_ARN'
layer_base = ':'.join(new_arn.split(':')[:-1])  # strip version number

# Remove old version of same layer
filtered = [a for a in existing if not a.startswith(layer_base)]
filtered.append(new_arn)
print(' '.join(filtered))
")

    if aws lambda update-function-configuration \
        --function-name "$fn" \
        --region "$REGION" \
        --layers $NEW_LAYERS \
        --no-cli-pager > /dev/null 2>&1; then
        echo "  ✅ $fn"
        ATTACHED=$((ATTACHED + 1))
    else
        echo "  ❌ FAILED: $fn"
        FAILED=$((FAILED + 1))
    fi
    sleep 2  # avoid ResourceConflictException
done

echo ""
echo "═══ Complete: $ATTACHED attached, $FAILED failed ═══"
echo ""
echo "Now redeploy affected Lambdas WITHOUT extra-files (layer serves those modules):"
echo "  ./deploy/deploy_unified.sh daily-brief"
echo "  ./deploy/deploy_unified.sh weekly-digest"
echo "  ... etc"
echo ""
echo "Or deploy all: ./deploy/deploy_unified.sh all"
