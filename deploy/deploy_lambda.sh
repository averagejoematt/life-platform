#!/bin/bash
# deploy_lambda.sh — Universal Lambda deploy helper
# Reads the handler config from AWS to determine the correct zip filename.
# Prevents the filename mismatch bug where code deploys but never loads.
#
# Usage (single-file Lambda):
#   ./deploy/deploy_lambda.sh <function-name> <source-file>
#
# Usage (multi-module Lambda — e.g. daily-brief):
#   ./deploy/deploy_lambda.sh <function-name> <source-file> --extra-files file1.py file2.py ...
#
# Examples:
#   ./deploy/deploy_lambda.sh health-auto-export-webhook lambdas/health_auto_export_lambda.py
#   ./deploy/deploy_lambda.sh daily-brief lambdas/daily_brief_lambda.py \
#       --extra-files lambdas/html_builder.py lambdas/ai_calls.py lambdas/output_writers.py lambdas/board_loader.py

set -euo pipefail

REGION="us-west-2"

if [ $# -lt 2 ]; then
    echo "Usage: $0 <function-name> <source-file> [--extra-files file1.py ...]"
    echo "Example: $0 health-auto-export-webhook lambdas/health_auto_export_lambda.py"
    exit 1
fi

FUNCTION_NAME="$1"
SOURCE_FILE="$2"
shift 2

# ── Parse --extra-files ──
EXTRA_FILES=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --extra-files)
            shift
            while [[ $# -gt 0 && "$1" != --* ]]; do
                EXTRA_FILES+=("$1")
                shift
            done
            ;;
        *) shift ;;
    esac
done

if [ ! -f "$SOURCE_FILE" ]; then
    echo "❌ Source file not found: $SOURCE_FILE"
    exit 1
fi

# Validate extra files exist before doing any work
for extra in "${EXTRA_FILES[@]}"; do
    if [ ! -f "$extra" ]; then
        echo "❌ Extra file not found: $extra"
        exit 1
    fi
done

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

cp "$SOURCE_FILE" "$WORK_DIR/$EXPECTED_FILENAME"

# Copy any extra files (retain original basename — handler imports them by name)
EXTRA_BASENAMES=()
for extra in "${EXTRA_FILES[@]}"; do
    basename_extra=$(basename "$extra")
    cp "$extra" "$WORK_DIR/$basename_extra"
    EXTRA_BASENAMES+=("$basename_extra")
    echo "   + $basename_extra"
done

# Build the zip
(cd "$WORK_DIR" && zip -q deploy.zip "$EXPECTED_FILENAME" "${EXTRA_BASENAMES[@]+"${EXTRA_BASENAMES[@]}"}")

if [ ${#EXTRA_FILES[@]} -gt 0 ]; then
    echo "📦 Packaged $(basename "$SOURCE_FILE") + ${#EXTRA_FILES[@]} extra file(s) → zip"
else
    echo "📦 Packaged $(basename "$SOURCE_FILE") → $EXPECTED_FILENAME in zip"
fi

# ── Step 3: Verify main handler is in the zip ──
ZIP_MAIN=$(unzip -l "$WORK_DIR/deploy.zip" | grep "\.py$" | awk '{print $4}' | grep "^${EXPECTED_FILENAME}$" || true)
if [ -z "$ZIP_MAIN" ]; then
    echo "❌ FATAL: Zip does not contain handler entry '$EXPECTED_FILENAME'"
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
