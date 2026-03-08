#!/bin/bash
# deploy_daily_brief_v2.76.0.sh
# Deploys daily_brief_lambda.py + scoring_engine.py (Phase 1 monolith extraction)
#
# scoring_engine.py must be bundled alongside daily_brief_lambda.py in the same zip
# because Lambda resolves imports from the deployment package root.
#
# Usage: ./deploy/deploy_daily_brief_v2.76.0.sh

set -euo pipefail

REGION="us-west-2"
FUNCTION_NAME="daily-brief"
LAMBDAS_DIR="$(dirname "$0")/../lambdas"

echo "=== Daily Brief v2.76.0 Deploy (scoring_engine extraction) ==="

# ── Step 1: Verify source files exist ────────────────────────────────────────
if [ ! -f "$LAMBDAS_DIR/daily_brief_lambda.py" ]; then
    echo "❌ daily_brief_lambda.py not found in lambdas/"
    exit 1
fi
if [ ! -f "$LAMBDAS_DIR/scoring_engine.py" ]; then
    echo "❌ scoring_engine.py not found in lambdas/"
    exit 1
fi

# ── Step 2: Verify handler config from AWS ───────────────────────────────────
echo "🔍 Checking handler config for $FUNCTION_NAME..."
HANDLER=$(aws lambda get-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --query "Handler" --output text --no-cli-pager)

MODULE_NAME=$(echo "$HANDLER" | cut -d'.' -f1)
EXPECTED_FILENAME="${MODULE_NAME}.py"
echo "   Handler: $HANDLER → expects $EXPECTED_FILENAME"

# ── Step 3: Build zip with both files ────────────────────────────────────────
WORK_DIR=$(mktemp -d)

cp "$LAMBDAS_DIR/daily_brief_lambda.py" "$WORK_DIR/$EXPECTED_FILENAME"
cp "$LAMBDAS_DIR/scoring_engine.py"     "$WORK_DIR/scoring_engine.py"

(cd "$WORK_DIR" && zip -q deploy.zip "$EXPECTED_FILENAME" "scoring_engine.py")

echo "📦 Zip contents:"
unzip -l "$WORK_DIR/deploy.zip" | grep "\.py$"

# ── Step 4: Verify zip integrity ─────────────────────────────────────────────
ZIP_ENTRY=$(unzip -l "$WORK_DIR/deploy.zip" | grep "\.py$" | awk '{print $4}' | head -1)
if [ "$ZIP_ENTRY" != "$EXPECTED_FILENAME" ]; then
    echo "❌ FATAL: zip entry '$ZIP_ENTRY' != expected '$EXPECTED_FILENAME'"
    rm -rf "$WORK_DIR"
    exit 1
fi

# ── Step 5: Deploy ────────────────────────────────────────────────────────────
echo "🚀 Deploying $FUNCTION_NAME..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$WORK_DIR/deploy.zip" \
    --region "$REGION" \
    --no-cli-pager > /dev/null

# ── Step 6: Verify ───────────────────────────────────────────────────────────
LAST_MODIFIED=$(aws lambda get-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --query "LastModified" --output text --no-cli-pager)

echo "✅ Deployed $FUNCTION_NAME (modified: $LAST_MODIFIED)"
echo ""
echo "Next: invoke with a test date to verify scoring works:"
echo "  aws lambda invoke --function-name daily-brief \\"
echo "    --payload '{\"date\": \"$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d yesterday +%Y-%m-%d)\"}' \\"
echo "    --cli-binary-format raw-in-base64-out --region $REGION /tmp/brief_test.json"
echo "  cat /tmp/brief_test.json | python3 -c \"import sys,json; r=json.load(sys.stdin); print(r.get('statusCode', r))\""

rm -rf "$WORK_DIR"
