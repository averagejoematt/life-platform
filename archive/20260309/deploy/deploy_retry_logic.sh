#!/bin/bash
# ============================================================
#  Deploy Haiku retry logic to daily-brief, weekly-digest,
#  anomaly-detector
# ============================================================

set -e

REGION="us-west-2"

deploy_lambda() {
  local FUNCTION_NAME="$1"
  local SOURCE_FILE="$2"
  local ZIP_FILE="/tmp/${FUNCTION_NAME}_retry.zip"

  echo ""
  echo "--- Deploying $FUNCTION_NAME ---"

  # Verify retry logic is present before deploying
  if ! grep -q "call_anthropic_with_retry" "$SOURCE_FILE"; then
    echo "  ✗ ERROR: call_anthropic_with_retry not found in $SOURCE_FILE — skipping"
    return 1
  fi

  cp "$SOURCE_FILE" /tmp/lambda_function.py
  cd /tmp && zip -j "$ZIP_FILE" lambda_function.py > /dev/null
  cd - > /dev/null

  aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP_FILE" \
    --region "$REGION" > /dev/null

  aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
  echo "  ✓ $FUNCTION_NAME deployed with retry logic"
}

BASE="$(cd "$(dirname "$0")" && pwd)"

deploy_lambda "daily-brief"      "$BASE/daily_brief_lambda.py"
deploy_lambda "weekly-digest"    "$BASE/weekly_digest_lambda.py"
deploy_lambda "anomaly-detector" "$BASE/anomaly_detector_lambda.py"

echo ""
echo "=== Done. Now run: ==="
echo "  bash patch_monthly_digest_retry.sh"
echo ""
echo "That will download, patch, and redeploy monthly-digest."
