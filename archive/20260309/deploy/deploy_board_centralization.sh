#!/bin/bash
# deploy_board_centralization.sh — v2.57.0
# Deploys all 5 Lambdas refactored to use centralized Board of Directors config.
# Each Lambda zip now includes board_loader.py alongside the handler.
#
# Safety: Falls back to hardcoded prompts if board_loader or S3 config unavailable.
# Zero-risk: existing behaviour preserved if config read fails.
#
# Usage:
#   cd ~/Documents/Claude/life-platform
#   bash deploy/deploy_board_centralization.sh           # deploy all 5
#   bash deploy/deploy_board_centralization.sh monthly   # deploy one
#   bash deploy/deploy_board_centralization.sh --dry-run # show what would happen
set -euo pipefail

REGION="us-west-2"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LAMBDAS_DIR="$PROJECT_DIR/lambdas"
BOARD_LOADER="$LAMBDAS_DIR/board_loader.py"
TMP_DIR="/tmp/board_central_deploy"
DELAY=10

# Verify board_loader.py exists
if [ ! -f "$BOARD_LOADER" ]; then
    echo "ERROR: $BOARD_LOADER not found"
    exit 1
fi

echo "═══════════════════════════════════════════════════"
echo "  Board Centralization Deploy — v2.57.0"
echo "  5 Lambdas × board_loader.py"
echo "═══════════════════════════════════════════════════"
echo ""

DRY_RUN=false
TARGET="${1:-all}"
if [ "$TARGET" = "--dry-run" ]; then
    DRY_RUN=true
    TARGET="all"
    echo "  *** DRY RUN — no changes will be made ***"
    echo ""
fi

deploy_lambda() {
    local FUNC_NAME="$1"
    local SOURCE_FILE="$2"
    local HANDLER_FILE="$3"  # filename inside zip (lambda_function.py or digest_handler.py)
    local STEP="$4"

    echo "▸ [$STEP/5] $FUNC_NAME"
    echo "  Source: $SOURCE_FILE"
    echo "  Handler: $HANDLER_FILE + board_loader.py"

    if [ ! -f "$LAMBDAS_DIR/$SOURCE_FILE" ]; then
        echo "  ❌ ERROR: $LAMBDAS_DIR/$SOURCE_FILE not found — skipping"
        return 1
    fi

    # Package
    rm -rf "$TMP_DIR" && mkdir -p "$TMP_DIR"
    cp "$LAMBDAS_DIR/$SOURCE_FILE" "$TMP_DIR/$HANDLER_FILE"
    cp "$BOARD_LOADER" "$TMP_DIR/board_loader.py"

    local ZIP_FILE="$TMP_DIR/${FUNC_NAME}.zip"
    cd "$TMP_DIR"
    zip -q "$ZIP_FILE" "$HANDLER_FILE" board_loader.py
    cd "$PROJECT_DIR"

    local ZIP_SIZE
    ZIP_SIZE=$(du -h "$ZIP_FILE" | cut -f1)
    echo "  Zip: $ZIP_SIZE ($(unzip -l "$ZIP_FILE" | tail -1 | awk '{print $2}') bytes)"

    if [ "$DRY_RUN" = true ]; then
        echo "  [DRY RUN] Would deploy $FUNC_NAME"
        echo ""
        return 0
    fi

    # Deploy
    aws lambda update-function-code \
        --function-name "$FUNC_NAME" \
        --zip-file "fileb://$ZIP_FILE" \
        --region "$REGION" \
        --output text \
        --query 'FunctionName' \
        --no-cli-pager
    echo "  ✓ Deployed"

    # Wait for propagation
    aws lambda wait function-updated \
        --function-name "$FUNC_NAME" \
        --region "$REGION" 2>/dev/null || true

    echo ""
}

DEPLOYED=0

# ── 1. Monthly Digest ──
if [ "$TARGET" = "all" ] || [ "$TARGET" = "monthly" ]; then
    deploy_lambda "monthly-digest" \
        "monthly_digest_lambda.py" \
        "lambda_function.py" \
        "1"
    DEPLOYED=$((DEPLOYED + 1))
    [ "$TARGET" = "all" ] && [ "$DRY_RUN" = false ] && sleep $DELAY
fi

# ── 2. Weekly Digest ──
if [ "$TARGET" = "all" ] || [ "$TARGET" = "weekly" ]; then
    deploy_lambda "weekly-digest" \
        "weekly_digest_v2_lambda.py" \
        "digest_handler.py" \
        "2"
    DEPLOYED=$((DEPLOYED + 1))
    [ "$TARGET" = "all" ] && [ "$DRY_RUN" = false ] && sleep $DELAY
fi

# ── 3. Nutrition Review ──
if [ "$TARGET" = "all" ] || [ "$TARGET" = "nutrition" ]; then
    deploy_lambda "nutrition-review" \
        "nutrition_review_lambda.py" \
        "lambda_function.py" \
        "3"
    DEPLOYED=$((DEPLOYED + 1))
    [ "$TARGET" = "all" ] && [ "$DRY_RUN" = false ] && sleep $DELAY
fi

# ── 4. Daily Brief ──
if [ "$TARGET" = "all" ] || [ "$TARGET" = "daily" ]; then
    deploy_lambda "daily-brief" \
        "daily_brief_lambda.py" \
        "lambda_function.py" \
        "4"
    DEPLOYED=$((DEPLOYED + 1))
    [ "$TARGET" = "all" ] && [ "$DRY_RUN" = false ] && sleep $DELAY
fi

# ── 5. Wednesday Chronicle ──
if [ "$TARGET" = "all" ] || [ "$TARGET" = "chronicle" ]; then
    deploy_lambda "wednesday-chronicle" \
        "wednesday_chronicle_lambda.py" \
        "lambda_function.py" \
        "5"
    DEPLOYED=$((DEPLOYED + 1))
fi

# Cleanup
rm -rf "$TMP_DIR"

echo "═══════════════════════════════════════════════════"
if [ "$DRY_RUN" = true ]; then
    echo "  DRY RUN complete — $DEPLOYED Lambdas would be deployed"
else
    echo "  ✅ $DEPLOYED Lambda(s) deployed with board_loader.py"
fi
echo ""
echo "  Config source: s3://matthew-life-platform/config/board_of_directors.json"
echo "  Shared module: lambdas/board_loader.py (bundled in each zip)"
echo "═══════════════════════════════════════════════════"
echo ""
echo "Verify with:"
echo "  aws lambda invoke --function-name monthly-digest --payload '{}' \\"
echo "    --cli-binary-format raw-in-base64-out --region $REGION /tmp/test.json"
echo "  cat /tmp/test.json"
echo ""
echo "Check logs for 'config-driven' or 'fallback':"
echo "  aws logs tail /aws/lambda/daily-brief --since 5m --region $REGION"
