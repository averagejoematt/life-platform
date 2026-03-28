#!/bin/bash
# deploy/fix_stale_layers.sh
# I2: Update anomaly-detector, character-sheet-compute, daily-metrics-compute
# from life-platform-shared-utils:9 → :10
# Run: bash deploy/fix_stale_layers.sh

set -e
REGION="us-west-2"
ACCOUNT="205930651321"
LAYER_ARN="arn:aws:lambda:$REGION:$ACCOUNT:layer:life-platform-shared-utils:10"

LAMBDAS=(
  "anomaly-detector"
  "character-sheet-compute"
  "daily-metrics-compute"
)

echo "=== I2: Fix Stale Layer Versions (v9 → v10) ==="
echo "Target layer: $LAYER_ARN"
echo ""

for FN in "${LAMBDAS[@]}"; do
  echo "--- $FN ---"

  # Get current layer ARNs
  CURRENT_LAYERS=$(aws lambda get-function-configuration \
    --function-name "$FN" \
    --region "$REGION" \
    --query 'Layers[].Arn' \
    --output text 2>/dev/null || echo "")

  if echo "$CURRENT_LAYERS" | grep -q "shared-utils:10"; then
    echo "  ✅ Already on v10 — skipping."
    continue
  fi

  echo "  Current layers: $CURRENT_LAYERS"
  echo "  Updating to v10..."

  # Build new layer list: replace any shared-utils:N with :10, keep others
  NEW_LAYERS=$(echo "$CURRENT_LAYERS" | tr '\t' '\n' | \
    sed "s|:layer:life-platform-shared-utils:[0-9]*|:layer:life-platform-shared-utils:10|g" | \
    tr '\n' ' ' | xargs)

  # If no layers at all, just add the new one
  if [ -z "$NEW_LAYERS" ]; then
    NEW_LAYERS="$LAYER_ARN"
  fi

  aws lambda update-function-configuration \
    --function-name "$FN" \
    --layers $NEW_LAYERS \
    --region "$REGION" \
    --query 'LastUpdateStatus' \
    --output text

  echo "  Waiting for update to complete..."
  aws lambda wait function-updated \
    --function-name "$FN" \
    --region "$REGION"

  echo "  ✅ Updated."
  sleep 3
done

echo ""
echo "=== Verification ==="
for FN in "${LAMBDAS[@]}"; do
  LAYER_VER=$(aws lambda get-function-configuration \
    --function-name "$FN" \
    --region "$REGION" \
    --query 'Layers[?contains(Arn, `shared-utils`)].Arn' \
    --output text 2>/dev/null || echo "none")
  echo "  $FN → $LAYER_VER"
done

echo ""
echo "Done. I2 stale layer finding resolved."
