#!/bin/bash
# deploy_strava_phase2.sh — Deploy Strava Lambda (Phase 2 API gap closure)
#
# Changes:
#   - Per-activity HR zone distribution via GET /activities/{id}/zones
#   - hr_zone_seconds, zone2_seconds, zone_boundaries per activity
#   - Day-level total_zone2_seconds aggregation
#
# NOTE: The /activities/{id}/zones endpoint requires Strava Summit subscription.
# Without it, zone fields will be null but activity data still saves correctly.
# Schema retains zone fields for future subscription enablement.
#
# Run from: ~/Documents/Claude/life-platform/

set -euo pipefail

FUNCTION_NAME="strava-data-ingestion"
REGION="us-west-2"
ZIP_FILE="strava_lambda.zip"

echo "=== Deploying Strava Lambda (Phase 2: HR Zones) ==="
echo "Adds per-activity zone distribution for accurate Zone 2 tracking"

# Step 1: Package
echo ""
echo "Step 1: Packaging..."
rm -f "$ZIP_FILE"
zip "$ZIP_FILE" strava_lambda.py
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
echo "Step 2b: Ensuring handler matches filename..."
aws lambda wait function-updated \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION"
aws lambda update-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --handler strava_lambda.lambda_handler \
    --region "$REGION" \
    --output json | head -5

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
echo "=== ✅ Strava Lambda (Phase 2) deployed ==="
echo ""
echo "Test with:"
echo "  aws lambda invoke --function-name $FUNCTION_NAME \\"
echo "    --payload '{\"date\": \"2026-02-23\"}' \\"
echo "    --cli-binary-format raw-in-base64-out \\"
echo "    --region $REGION /tmp/strava-test.json && cat /tmp/strava-test.json"
echo ""
echo "Then check DynamoDB for zone data on activities:"
echo "  aws dynamodb get-item --table-name life-platform \\"
echo "    --key '{\"pk\":{\"S\":\"USER#matthew#SOURCE#strava\"},\"sk\":{\"S\":\"DATE#2026-02-23\"}}' \\"
echo "    --region $REGION \\"
echo "    --query 'Item.total_zone2_seconds'"
