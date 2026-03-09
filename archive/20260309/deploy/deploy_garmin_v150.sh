#!/bin/bash
# deploy_garmin_v150.sh — Deploy Garmin Lambda v1.5.0 (Phase 1 API gap closure)
#
# Changes:
#   - extract_sleep: 2 → 18 fields (stages, timing, SpO2, restless, sub-scores)
#   - extract_activities: +5 fields (avg_hr, max_hr, calories, avg/max speed)
#
# Run from: ~/Documents/Claude/life-platform/

set -euo pipefail

FUNCTION_NAME="garmin-data-ingestion"
REGION="us-west-2"
ZIP_FILE="garmin_lambda.zip"
LAYER_ARN="arn:aws:lambda:us-west-2:205930651321:layer:garmin-deps:1"

echo "=== Deploying Garmin Lambda v1.5.0 ==="
echo "Phase 1: Sleep expansion (2→18 fields) + Activity HR/calories"

# Step 1: Package
echo ""
echo "Step 1: Packaging..."
rm -f "$ZIP_FILE"
zip "$ZIP_FILE" garmin_lambda.py
echo "  → $ZIP_FILE created ($(wc -c < "$ZIP_FILE") bytes)"

# Step 2: Deploy
echo ""
echo "Step 2: Deploying to Lambda..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP_FILE" \
    --region "$REGION" \
    --output json | head -20

echo ""
echo "Step 3: Waiting for update..."
aws lambda wait function-updated \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION"

echo ""
echo "Step 4: Verifying..."
aws lambda get-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --query '{LastModified: LastModified, Runtime: Runtime, MemorySize: MemorySize, Timeout: Timeout}' \
    --output table

echo ""
echo "=== ✅ Garmin Lambda v1.5.0 deployed ==="
echo ""
echo "Test with:"
echo "  aws lambda invoke --function-name $FUNCTION_NAME \\"
echo "    --payload '{\"date\": \"2026-02-23\"}' \\"
echo "    --cli-binary-format raw-in-base64-out \\"
echo "    --region $REGION /tmp/garmin-test.json && cat /tmp/garmin-test.json"
echo ""
echo "Then check DynamoDB for new sleep fields:"
echo "  aws dynamodb get-item --table-name life-platform \\"
echo "    --key '{\"pk\":{\"S\":\"USER#matthew#SOURCE#garmin\"},\"sk\":{\"S\":\"DATE#2026-02-23\"}}' \\"
echo "    --region $REGION \\"
echo "    --query 'Item.{deep_sleep: deep_sleep_seconds, rem_sleep: rem_sleep_seconds, sleep_spo2: sleep_spo2_avg, restless: restless_moments_count}'"
