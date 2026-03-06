#!/bin/bash
# deploy_whoop_phase3.sh — Deploy Whoop Lambda (Phase 3 API gap closure)
#
# Changes:
#   - Sleep start/end timestamps (sleep_start, sleep_end)
#   - Nap data extraction (nap_count, nap_duration_hours)
#
# Prerequisites:
#   - python3 patch_whoop_phase3.py  (must be run first to patch whoop_lambda.py)
#
# Run from: ~/Documents/Claude/life-platform/

set -euo pipefail

FUNCTION_NAME="whoop-data-ingestion"
REGION="us-west-2"
ZIP_FILE="whoop_lambda.zip"

echo "=== Deploying Whoop Lambda (Phase 3: Sleep Timestamps + Naps) ==="
echo "Adds sleep_start/end ISO timestamps and nap_count/nap_duration_hours"

# Step 1: Verify patch was applied
echo ""
echo "Step 1: Verifying patch..."
if [ ! -f "whoop_lambda.py" ]; then
    echo "ERROR: whoop_lambda.py not found."
    echo "Run: python3 patch_whoop_phase3.py"
    exit 1
fi
if ! grep -q "Phase 3" whoop_lambda.py; then
    echo "ERROR: whoop_lambda.py does not contain Phase 3 changes."
    echo "Run: python3 patch_whoop_phase3.py"
    exit 1
fi
echo "  ✅ whoop_lambda.py patched (Phase 3 markers found)"

# Step 2: Package (Whoop handler expects lambda_function.py)
echo ""
echo "Step 2: Packaging..."
BUILD_DIR=$(mktemp -d)
cp whoop_lambda.py "$BUILD_DIR/lambda_function.py"

rm -f "$ZIP_FILE"
cd "$BUILD_DIR"
zip "${OLDPWD}/${ZIP_FILE}" lambda_function.py
cd "$OLDPWD"
rm -rf "$BUILD_DIR"

echo "  → $ZIP_FILE created ($(wc -c < "$ZIP_FILE") bytes)"

# Step 3: Deploy
echo ""
echo "Step 3: Deploying to Lambda..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP_FILE" \
    --region "$REGION" \
    --output json | head -20

echo ""
echo "Step 4: Waiting for update..."
aws lambda wait function-updated \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION"

echo ""
echo "Step 5: Verifying..."
aws lambda get-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --query '{LastModified: LastModified, Runtime: Runtime, MemorySize: MemorySize, Timeout: Timeout}' \
    --output table

echo ""
echo "=== ✅ Whoop Lambda (Phase 3) deployed ==="
echo ""
echo "Test with:"
echo "  aws lambda invoke --function-name $FUNCTION_NAME \\"
echo "    --payload '{\"date\": \"2026-02-23\"}' \\"
echo "    --cli-binary-format raw-in-base64-out \\"
echo "    --region $REGION /tmp/whoop-test.json && cat /tmp/whoop-test.json"
echo ""
echo "Check new fields:"
echo "  aws dynamodb get-item --table-name life-platform \\"
echo "    --key '{\"pk\":{\"S\":\"USER#matthew#SOURCE#whoop\"},\"sk\":{\"S\":\"DATE#2026-02-23\"}}' \\"
echo "    --region $REGION \\"
echo "    --query 'Item.{sleep_start:sleep_start,sleep_end:sleep_end,nap_count:nap_count,nap_hours:nap_duration_hours}'"
