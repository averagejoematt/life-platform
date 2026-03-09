#!/bin/bash
# deploy_health_auto_export_webhook.sh — Deploy updated health-auto-export-webhook Lambda
# Adds: structured logging, auth failure tracking, request timing
# RCA corrective action items #7 and #9

set -euo pipefail

LAMBDA_NAME="health-auto-export-webhook"
REGION="us-west-2"
ZIP_FILE="/tmp/health_auto_export_webhook.zip"
SOURCE_FILE="$HOME/Documents/Claude/life-platform/health_auto_export_lambda.py"

echo "=== Deploying $LAMBDA_NAME ==="

# Package
echo "Packaging..."
cd /tmp
cp "$SOURCE_FILE" health_auto_export_lambda.py
zip -j "$ZIP_FILE" health_auto_export_lambda.py
rm health_auto_export_lambda.py

# Deploy
echo "Deploying to $LAMBDA_NAME..."
aws lambda update-function-code \
    --function-name "$LAMBDA_NAME" \
    --zip-file "fileb://$ZIP_FILE" \
    --region "$REGION" \
    --output text \
    --query 'LastModified'

# Wait for update to complete
echo "Waiting for update..."
aws lambda wait function-updated \
    --function-name "$LAMBDA_NAME" \
    --region "$REGION"

# Verify
echo ""
echo "=== Verification ==="
aws lambda get-function \
    --function-name "$LAMBDA_NAME" \
    --region "$REGION" \
    --query 'Configuration.[FunctionName,Runtime,LastModified,CodeSize,MemorySize]' \
    --output table

# Cleanup
rm -f "$ZIP_FILE"

echo ""
echo "✅ Deploy complete. Structured logging now active."
echo "   CloudWatch Insights query:"
echo '   fields @timestamp, event, metrics_count, other_metric_days, duration_ms'
echo '   | filter event = "webhook_complete"'
echo '   | sort @timestamp desc'
echo '   | limit 20'
