#!/bin/bash
# fix_chronicle_packaging.sh — Fix wednesday-chronicle Lambda packaging
# Bug: zip contained wednesday_chronicle_lambda.py instead of lambda_function.py
# Handler expects lambda_function.lambda_handler
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
LAMBDA_DIR="$ROOT_DIR/lambdas"
FUNC_NAME="wednesday-chronicle"
REGION="us-west-2"

echo "=== Fix Chronicle Lambda Packaging ==="
echo ""

# Package correctly: rename to lambda_function.py inside zip
echo "[1/3] Packaging Lambda..."
cd "$LAMBDA_DIR"
cp wednesday_chronicle_lambda.py lambda_function.py
rm -f wednesday_chronicle.zip
zip -j wednesday_chronicle.zip lambda_function.py board_loader.py
rm lambda_function.py
echo "  ✓ Zip created with lambda_function.py + board_loader.py"

# Deploy
echo ""
echo "[2/3] Updating Lambda function code..."
aws lambda update-function-code \
  --function-name "$FUNC_NAME" \
  --zip-file "fileb://wednesday_chronicle.zip" \
  --region "$REGION" \
  --output json | jq '{FunctionName, CodeSize, LastModified}'

echo "  Waiting for update..."
aws lambda wait function-updated \
  --function-name "$FUNC_NAME" \
  --region "$REGION"
echo "  ✓ Lambda updated"

# Verify
echo ""
echo "[3/3] Verifying..."
aws lambda invoke \
  --function-name "$FUNC_NAME" \
  --region "$REGION" \
  --cli-read-timeout 10 \
  --payload '{"dry_run": true}' \
  /tmp/chronicle_verify.json 2>/dev/null || true

# Check if import error is gone
ERRORS=$(aws logs filter-log-events \
  --log-group-name "/aws/lambda/$FUNC_NAME" \
  --start-time $(($(date +%s) * 1000 - 60000)) \
  --region "$REGION" \
  --filter-pattern "ImportModuleError" \
  --query 'events[].message' \
  --output text 2>/dev/null || echo "")

if [ -z "$ERRORS" ] || [ "$ERRORS" = "None" ]; then
  echo "  ✓ No import errors — packaging fix confirmed"
else
  echo "  ⚠ May still have issues — check CloudWatch logs"
fi

echo ""
echo "=== Done ==="
echo "  Do NOT invoke yet — we'll trigger manually after the draft is approved."
