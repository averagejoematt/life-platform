#!/bin/bash
# deploy_v2.55.1_habitify_supplement_bridge.sh
# Adds supplement bridge to Habitify Lambda — automatically writes to
# USER#matthew#SOURCE#supplements after each Habitify ingestion.
#
# What changed in habitify_lambda.py:
#   - Added SUPPLEMENT_MAP config (21 supplements, 3 timing batches)
#   - Added bridge_supplements() function
#   - write_to_dynamo() now calls bridge_supplements() after each write
#   - Supplement bridge failures are caught and logged (non-fatal)

set -euo pipefail

FUNCTION_NAME="habitify-data-ingestion"
LAMBDA_DIR="$HOME/Documents/Claude/life-platform/lambdas"
ZIP_FILE="$LAMBDA_DIR/habitify_lambda.zip"

echo "=== Deploy v2.55.1: Habitify Supplement Bridge ==="
echo ""

# Package (must be lambda_function.py inside the zip)
echo "[1/2] Packaging Lambda..."
cd "$LAMBDA_DIR"
cp habitify_lambda.py /tmp/lambda_function.py
zip -j "$ZIP_FILE" /tmp/lambda_function.py
rm /tmp/lambda_function.py
echo "  → $(ls -lh "$ZIP_FILE" | awk '{print $5}') package"

# Deploy
echo "[2/2] Deploying to $FUNCTION_NAME..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP_FILE" \
    --region us-west-2 \
    --no-cli-pager

echo ""
echo "✅ Deployed! Supplement bridge is now active."
echo "   Every Habitify ingestion will auto-write to supplements partition."
echo ""
echo "Verify with: aws lambda invoke --function-name $FUNCTION_NAME --payload '{\"date\":\"2026-03-03\"}' --region us-west-2 --no-cli-pager /dev/stdout"
