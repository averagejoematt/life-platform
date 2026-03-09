#!/bin/bash
# fix_habitify_packaging.sh — Redeploy Habitify Lambda with correct packaging
set -euo pipefail

FUNCTION_NAME="habitify-data-ingestion"
LAMBDA_DIR="$HOME/Documents/Claude/life-platform/lambdas"

echo "=== Fix Habitify Lambda Packaging ==="
echo ""
echo "[1/2] Packaging (habitify_lambda.py → lambda_function.py)..."
cd "$LAMBDA_DIR"
cp habitify_lambda.py lambda_function.py
rm -f habitify_lambda.zip
zip -j habitify_lambda.zip lambda_function.py
rm lambda_function.py
echo "  ✓ Zip created: $(du -h habitify_lambda.zip | cut -f1)"

echo ""
echo "[2/2] Deploying..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://habitify_lambda.zip" \
    --region us-west-2 \
    --output json | jq '{FunctionName, CodeSize, LastModified}'

aws lambda wait function-updated \
    --function-name "$FUNCTION_NAME" \
    --region us-west-2
echo "  ✓ Lambda updated"

echo ""
echo "[3/3] Test invoke for today..."
aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --region us-west-2 \
    --cli-read-timeout 60 \
    --payload '{}' \
    /tmp/habitify_test.json \
    --no-cli-pager

echo ""
echo "Response:"
cat /tmp/habitify_test.json
echo ""
echo ""
echo "=== Done ==="
