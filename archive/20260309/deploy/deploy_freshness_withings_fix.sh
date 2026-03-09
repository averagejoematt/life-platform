#!/bin/bash
# Deploy: Freshness Checker + Withings Token Fix
# Freshness: Fix date parsing for sub-record SKs (workout records)
# Withings: Re-read secret each gap-fill iteration to prevent stale refresh tokens
set -euo pipefail

LAMBDA_DIR="$HOME/Documents/Claude/life-platform/lambdas"
DEPLOY_DIR="$HOME/Documents/Claude/life-platform/deploy"
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

echo "=== Freshness Checker + Withings Token Fix ==="

# --- 1. Deploy Freshness Checker ---
echo ""
echo "[1/4] Deploying Freshness Checker..."
cp "$LAMBDA_DIR/freshness_checker_lambda.py" "$TMPDIR/lambda_function.py"
cd "$TMPDIR"
zip -j "$DEPLOY_DIR/freshness_checker.zip" lambda_function.py
aws lambda update-function-code \
  --function-name life-platform-freshness-checker \
  --zip-file "fileb://$DEPLOY_DIR/freshness_checker.zip" \
  --query '{FunctionName: FunctionName, LastModified: LastModified}' \
  --output table
echo "  ✅ Freshness checker deployed"

echo ""
echo "[2/4] Deploying Withings Lambda (waiting 10s)..."
sleep 10
rm -f "$TMPDIR/lambda_function.py"
cp "$LAMBDA_DIR/withings_lambda.py" "$TMPDIR/lambda_function.py"
cd "$TMPDIR"
zip -j "$DEPLOY_DIR/withings_lambda.zip" lambda_function.py
aws lambda update-function-code \
  --function-name withings-data-ingestion \
  --zip-file "fileb://$DEPLOY_DIR/withings_lambda.zip" \
  --query '{FunctionName: FunctionName, LastModified: LastModified}' \
  --output table
echo "  ✅ Withings Lambda deployed"

echo ""
echo "[3/4] Invoking Withings to pick up today's weight (waiting 10s)..."
sleep 10
aws lambda invoke \
  --function-name withings-data-ingestion \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/withings_invoke_result.json
echo "  Response:"
cat /tmp/withings_invoke_result.json | python3 -m json.tool
echo ""

echo "[4/4] Invoking Freshness Checker to verify..."
sleep 5
aws lambda invoke \
  --function-name life-platform-freshness-checker \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/freshness_result.json
echo "  Response:"
cat /tmp/freshness_result.json | python3 -m json.tool

echo ""
echo "=== Deploy complete ==="
echo ""
echo "Changes:"
echo "  1. Freshness Checker: date_str now truncated to YYYY-MM-DD ([:10])"
echo "     Fixes false ❌ when sub-records (workouts) sort above daily records"
echo "  2. Withings Lambda: get_secret() called per iteration in gap-fill loop"
echo "     Prevents stale refresh_token after Withings invalidates old token"
echo "  3. Withings invoked to pick up today's weigh-in"
