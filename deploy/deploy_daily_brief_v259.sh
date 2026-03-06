#!/bin/bash
# Deploy Daily Brief v2.59.0 (Character Sheet Integration)
# Reads pre-computed character sheet from DDB (written by character-sheet-compute Lambda).
# Adds: Character Sheet HTML section, BoD character context, dashboard+buddy JSON.
# Bundles: lambda_function.py + board_loader.py (no character_engine.py needed)
set -euo pipefail

REGION="us-west-2"
LAMBDA_NAME="daily-brief"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LAMBDAS_DIR="$PROJECT_DIR/lambdas"

echo "═══════════════════════════════════════════════════"
echo "  Daily Brief Deploy — v2.59.0"
echo "  Character Sheet Integration"
echo "═══════════════════════════════════════════════════"
echo ""

# Verify source files exist
SOURCE_FILE="$LAMBDAS_DIR/daily_brief_lambda.py"
BOARD_LOADER="$LAMBDAS_DIR/board_loader.py"

if [ ! -f "$SOURCE_FILE" ]; then
    echo "ERROR: $SOURCE_FILE not found"
    exit 1
fi
if [ ! -f "$BOARD_LOADER" ]; then
    echo "ERROR: $BOARD_LOADER not found"
    exit 1
fi

# Verify version string
VERSION=$(head -1 "$SOURCE_FILE" | grep -o 'v2\.59\.0' || echo "")
if [ -z "$VERSION" ]; then
    echo "WARNING: Version string v2.59.0 not found in first line"
    head -3 "$SOURCE_FILE"
    echo ""
    read -p "Continue anyway? [y/N] " -n 1 -r
    echo ""
    [[ $REPLY =~ ^[Yy]$ ]] || exit 1
fi

# Build zip
echo "[1/3] Building deployment package..."
DEPLOY_DIR="/tmp/daily-brief-v259-deploy"
rm -rf "$DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR"

cp "$SOURCE_FILE" "$DEPLOY_DIR/lambda_function.py"
cp "$BOARD_LOADER" "$DEPLOY_DIR/board_loader.py"

cd "$DEPLOY_DIR"
zip -q daily_brief_lambda.zip lambda_function.py board_loader.py
ZIP_SIZE=$(du -h daily_brief_lambda.zip | cut -f1)
echo "  Package: $ZIP_SIZE (lambda_function.py + board_loader.py)"
echo "  Contents:"
unzip -l daily_brief_lambda.zip

# Deploy
echo ""
echo "[2/3] Deploying to Lambda: $LAMBDA_NAME..."
aws lambda update-function-code \
    --function-name "$LAMBDA_NAME" \
    --zip-file "fileb://daily_brief_lambda.zip" \
    --region "$REGION" \
    --output text --query 'FunctionArn'

echo "  ✅ Lambda code updated"

# Also copy zip to project for reference
cp daily_brief_lambda.zip "$LAMBDAS_DIR/daily_brief_lambda.zip"
echo "  Zip saved: lambdas/daily_brief_lambda.zip"

# Verify
echo ""
echo "[3/3] Verification..."
sleep 3
RESULT=$(aws lambda invoke \
    --function-name "$LAMBDA_NAME" \
    --payload '{"demo_mode": true}' \
    --cli-binary-format raw-in-base64-out \
    --region "$REGION" \
    /tmp/daily-brief-test.json 2>&1)
echo "  $RESULT"
echo "  Response:"
cat /tmp/daily-brief-test.json | python3 -m json.tool 2>/dev/null || cat /tmp/daily-brief-test.json
echo ""

# Cleanup
rm -rf "$DEPLOY_DIR"

echo ""
echo "═══════════════════════════════════════════════════"
echo "✅ Daily Brief v2.59.0 deployed"
echo "   Character Sheet section reads from character_sheet DDB partition"
echo "   Dependency: character-sheet-compute Lambda must run before 10:00 AM PT"
echo ""
echo "   Check tomorrow's brief for the new section, or test now:"
echo "   aws lambda invoke --function-name $LAMBDA_NAME --payload '{\"demo_mode\":true}' --cli-binary-format raw-in-base64-out --region $REGION /tmp/test.json"
echo "═══════════════════════════════════════════════════"
