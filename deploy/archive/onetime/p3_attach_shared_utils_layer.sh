#!/bin/bash
# p3_attach_shared_utils_layer.sh — Attach life-platform-shared-utils layer to all consumer Lambdas
#
# Run AFTER p3_build_shared_utils_layer.sh.
# Usage: bash deploy/p3_attach_shared_utils_layer.sh <LAYER_VERSION_ARN>
#
# Consumer list must match ci/lambda_map.json shared_layer.consumers.

set -euo pipefail
REGION="us-west-2"

[ $# -ge 1 ] || { echo "Usage: $0 <LAYER_VERSION_ARN>"; exit 1; }
LAYER_ARN="$1"

# Validate it looks like a layer ARN
[[ "$LAYER_ARN" == arn:aws:lambda:*:layer:* ]] || { echo "❌ Does not look like a layer ARN: $LAYER_ARN"; exit 1; }

echo "Attaching layer: $LAYER_ARN"
echo ""

# Must match ci/lambda_map.json shared_layer.consumers
LAMBDAS=(
    "daily-brief"
    "weekly-digest"
    "monthly-digest"
    "nutrition-review"
    "wednesday-chronicle"
    "weekly-plate"
    "monday-compass"
    "anomaly-detector"
    "character-sheet-compute"
    "daily-metrics-compute"
    "daily-insight-compute"
    "adaptive-mode-compute"
    "hypothesis-engine"
    "dashboard-refresh"
    "weekly-correlation-compute"
)

ATTACHED=0
FAILED=0

for fn in "${LAMBDAS[@]}"; do
    echo "  Attaching to $fn..."
    EXISTING=$(aws lambda get-function-configuration \
        --function-name "$fn" \
        --region "$REGION" \
        --query "Layers[*].Arn" \
        --output json \
        --no-cli-pager 2>/dev/null || echo "[]")

    # Merge: strip old version of this layer, add new
    NEW_LAYERS=$(EXISTING_JSON="$EXISTING" NEW_ARN="$LAYER_ARN" python3 -c "
import json, os
existing = json.loads(os.environ.get('EXISTING_JSON', '[]'))
if not isinstance(existing, list): existing = []
new_arn = os.environ.get('NEW_ARN', '')
layer_base = ':'.join(new_arn.split(':')[:-1])
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
