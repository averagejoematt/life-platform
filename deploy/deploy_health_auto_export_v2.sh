#!/bin/bash
# deploy_health_auto_export_v2.sh — Update Health Auto Export Lambda code only
# Does NOT regenerate API key or recreate API Gateway
set -euo pipefail

REGION="us-west-2"
FUNCTION_NAME="health-auto-export-webhook"
LAMBDA_FILE="health_auto_export_lambda.py"
ZIP_FILE="health_auto_export_lambda.zip"

echo "=== Update Health Auto Export Lambda (code only) ==="

cd "$(dirname "$0")"

echo "Packaging..."
zip -j "$ZIP_FILE" "$LAMBDA_FILE"

echo "Deploying..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP_FILE" \
    --region "$REGION" > /dev/null

aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
rm -f "$ZIP_FILE"

echo "✓ Lambda updated. Trigger a sync from Health Auto Export to test."
