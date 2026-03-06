#!/bin/bash
# Deploy Daily Brief v2.62.0 — QA fixes: subject line, dynamic weight, 7-day training context
# Run from: ~/Documents/Claude/life-platform/
set -euo pipefail

echo "=== Daily Brief v2.62.0 — QA Fixes ==="
echo ""
echo "Changes:"
echo "  1. Subject line: date shows TODAY not yesterday"
echo "  2. Subject line: readiness emoji 🟢/🟡/🔴/⚪ replaces cryptic G/M/E/-"
echo "  3. Dynamic weight context in all 4 AI prompts (was hardcoded '302->185' / 'losing 117 lbs')"
echo "  4. 7-day training context added to training coach (prevents 'zero strength' panic on rest days)"
echo ""

# --- Build zip ---
LAMBDA_NAME="daily-brief"
ZIP_FILE="lambdas/daily_brief_lambda.zip"
SOURCE="lambdas/daily_brief_lambda.py"

echo "[1/3] Building deployment package..."
cd "$(dirname "$0")/.."

# Must be named lambda_function.py in the zip (handler = lambda_function.lambda_handler)
TMP_DIR=$(mktemp -d)
cp "$SOURCE" "$TMP_DIR/lambda_function.py"
if [ -f "lambdas/board_loader.py" ]; then
    cp "lambdas/board_loader.py" "$TMP_DIR/"
    echo "  Included: lambda_function.py + board_loader.py"
else
    echo "  Included: lambda_function.py"
fi
(cd "$TMP_DIR" && zip -j "$(cd - > /dev/null && pwd)/$ZIP_FILE" ./*)
rm -rf "$TMP_DIR"

echo "[2/3] Deploying to Lambda..."
aws lambda update-function-code \
    --function-name "$LAMBDA_NAME" \
    --zip-file "fileb://$ZIP_FILE" \
    --region us-west-2 \
    --no-cli-pager

echo ""
echo "[3/3] Verifying deployment..."
sleep 3
aws lambda get-function-configuration \
    --function-name "$LAMBDA_NAME" \
    --region us-west-2 \
    --query '{LastModified: LastModified, CodeSize: CodeSize, Handler: Handler}' \
    --no-cli-pager

echo ""
echo "=== Deploy complete ==="
echo ""
echo "Verification:"
echo "  - Tomorrow's email subject should show TODAY's date with emoji: 🟢/🟡/🔴/⚪"
echo "  - Training coach should reference last 7 days, not panic about rest days"
echo "  - BoD/TL;DR/Journal prompts should show actual current weight"
echo "  - Check CloudWatch for: '[INFO] Using config-driven daily BoD prompt'"
