#!/bin/bash
# deploy_tb7_19_23.sh — Deploy TB7-19 through TB7-23 changes
#
# TB7-19: ai_output_validator.py v1.1.0 — hallucinated data reference detection
# TB7-20: ai_calls.py — _load_insights_context() 1500-char hard cap
# TB7-21: anomaly_detector_lambda.py v2.5.0 — Z-floor raised to 2.0
# TB7-22: daily_insight_compute_lambda.py v1.4.0 — equalized drift windows (14d/14d)
# TB7-23: INTELLIGENCE_LAYER.md doc-only (no deploy needed)
#
# Usage: bash deploy/deploy_tb7_19_23.sh

set -euo pipefail
cd "$(dirname "$0")/.."

REGION="us-west-2"
LAYER_NAME="life-platform-shared-utils"
ACCOUNT="205930651321"
LAYER_ARN_PREFIX="arn:aws:lambda:us-west-2:${ACCOUNT}:layer:${LAYER_NAME}"

echo "=== TB7-19/20/21/22/23 Deploy ==="
echo ""

# ── Step 1: Rebuild shared Lambda Layer ──────────────────────────────────────
echo "[1/4] Rebuilding shared Lambda Layer..."
LAYER_ZIP="/tmp/shared_utils_layer.zip"
rm -f "$LAYER_ZIP"
cd lambdas
zip -q "$LAYER_ZIP" \
    ai_output_validator.py \
    ai_calls.py \
    insight_writer.py \
    platform_logger.py \
    digest_utils.py \
    board_loader.py \
    item_size_guard.py \
    ingestion_validator.py \
    ingestion_framework.py \
    retry_utils.py \
    scoring_engine.py \
    character_engine.py \
    html_builder.py \
    output_writers.py
cd ..

NEW_LAYER_VERSION=$(aws lambda publish-layer-version \
    --layer-name "$LAYER_NAME" \
    --zip-file "fileb://$LAYER_ZIP" \
    --compatible-runtimes python3.12 \
    --region "$REGION" \
    --query 'Version' \
    --output text)
echo "    -> Layer v${NEW_LAYER_VERSION} published"
NEW_LAYER_ARN="${LAYER_ARN_PREFIX}:${NEW_LAYER_VERSION}"

# ── Step 2: Deploy anomaly-detector (TB7-21) ─────────────────────────────────
echo "[2/4] Deploying anomaly-detector (v2.5.0)..."
bash deploy/deploy_lambda.sh anomaly-detector lambdas/anomaly_detector_lambda.py
sleep 10

# ── Step 3: Deploy daily-insight-compute (TB7-22) ────────────────────────────
echo "[3/4] Deploying daily-insight-compute (v1.4.0)..."
bash deploy/deploy_lambda.sh daily-insight-compute lambdas/daily_insight_compute_lambda.py
sleep 10

# ── Step 4: Update all Layer consumers to new layer version ──────────────────
echo "[4/4] Updating Layer consumers to v${NEW_LAYER_VERSION}..."

# From ci/lambda_map.json shared_layer.consumers
LAYER_CONSUMERS=(
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
)

for fn in "${LAYER_CONSUMERS[@]}"; do
    echo "    Updating layer: $fn"
    aws lambda update-function-configuration \
        --function-name "$fn" \
        --layers "$NEW_LAYER_ARN" \
        --region "$REGION" \
        --output text --query 'FunctionName' > /dev/null
    sleep 5
done

echo ""
echo "=== Deploy complete ==="
echo "  anomaly-detector:       v2.5.0 (TB7-21: Z-floor=2.0)"
echo "  daily-insight-compute:  v1.4.0 (TB7-22: 14d/14d drift windows)"
echo "  shared layer:           v${NEW_LAYER_VERSION} (TB7-19: hallucination check, TB7-20: insights cap)"
echo "  INTELLIGENCE_LAYER.md:  updated (TB7-21/22/23 -- doc only)"
echo ""
echo "Run smoke test: bash deploy/post_cdk_reconcile_smoke.sh"
