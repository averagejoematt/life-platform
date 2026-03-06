#!/bin/bash
# deploy_lambda.sh — Universal Lambda deploy helper
# Reads the handler config from AWS to determine the correct zip filename.
# Prevents the filename mismatch bug where code deploys but never loads.
#
# Usage:
#   ./deploy/deploy_lambda.sh <function-name> <source-file>
#
# Examples:
#   ./deploy/deploy_lambda.sh health-auto-export-webhook lambdas/health_auto_export_lambda.py
#   ./deploy/deploy_lambda.sh life-platform-daily-brief lambdas/daily_brief_lambda.py
#   ./deploy/deploy_lambda.sh habitify-webhook lambdas/habitify_lambda.py

set -euo pipefail

REGION="us-west-2"

if [ $# -lt 2 ]; then
    echo "Usage: $0 <function-name> <source-file>"
    echo "Example: $0 health-auto-export-webhook lambdas/health_auto_export_lambda.py"
    exit 1
fi

FUNCTION_NAME="$1"
SOURCE_FILE="$2"

if [ ! -f "$SOURCE_FILE" ]; then
    echo "❌ Source file not found: $SOURCE_FILE"
    exit 1
fi

# ── Step 1: Query AWS for the handler config ──
echo "🔍 Checking handler config for $FUNCTION_NAME..."
HANDLER=$(aws lambda get-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --query "Handler" --output text --no-cli-pager)

# Handler format: <module_name>.lambda_handler → we need <module_name>.py
MODULE_NAME=$(echo "$HANDLER" | cut -d'.' -f1)
EXPECTED_FILENAME="${MODULE_NAME}.py"

echo "   Handler: $HANDLER"
echo "   Expected zip entry: $EXPECTED_FILENAME"

# ── Step 2: Package with the correct filename ──
WORK_DIR=$(mktemp -d)
ZIP_FILE="${SOURCE_FILE%.py}.zip"

cp "$SOURCE_FILE" "$WORK_DIR/$EXPECTED_FILENAME"
(cd "$WORK_DIR" && zip -q deploy.zip "$EXPECTED_FILENAME")

echo "📦 Packaged $(basename "$SOURCE_FILE") → $EXPECTED_FILENAME in zip"

# ── Step 3: Verify zip contents match handler ──
ZIP_ENTRY=$(unzip -l "$WORK_DIR/deploy.zip" | grep "\.py$" | awk '{print $4}')
if [ "$ZIP_ENTRY" != "$EXPECTED_FILENAME" ]; then
    echo "❌ FATAL: Zip contains '$ZIP_ENTRY' but handler expects '$EXPECTED_FILENAME'"
    rm -rf "$WORK_DIR"
    exit 1
fi

# ── Step 4: Deploy ──
echo "🚀 Deploying $FUNCTION_NAME..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$WORK_DIR/deploy.zip" \
    --region "$REGION" \
    --no-cli-pager > /dev/null

# ── Step 5: Verify ──
LAST_MODIFIED=$(aws lambda get-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --query "LastModified" --output text --no-cli-pager)

echo "✅ Deployed $FUNCTION_NAME (modified: $LAST_MODIFIED)"

# Cleanup
rm -rf "$WORK_DIR"
