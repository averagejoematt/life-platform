#!/bin/bash
# deploy_lambda.sh — Universal Lambda deploy helper
# Reads the handler config from AWS to determine the correct zip filename.
# Prevents the filename mismatch bug where code deploys but never loads.
#
# Usage (single-file Lambda):
#   ./deploy/deploy_lambda.sh <function-name> <source-file>
#
# Usage (multi-module Lambda):
#   ./deploy/deploy_lambda.sh <function-name> <source-file> --extra-files file1.py file2.py ...
#
# Examples:
#   ./deploy/deploy_lambda.sh health-auto-export-webhook lambdas/health_auto_export_lambda.py
#   ./deploy/deploy_lambda.sh daily-brief lambdas/daily_brief_lambda.py \
#       --extra-files lambdas/ai_calls.py lambdas/html_builder.py lambdas/output_writers.py lambdas/board_loader.py
#
# Rollback:
#   Each deploy shifts the previous zip to s3://.../deploys/<func>/previous.zip.
#   Run: bash deploy/rollback_lambda.sh <function-name>

set -euo pipefail

REGION="us-west-2"
BUCKET="matthew-life-platform"

if [ $# -lt 2 ]; then
    echo "Usage: $0 <function-name> <source-file> [--extra-files file1.py ...]"
    echo "Example: $0 health-auto-export-webhook lambdas/health_auto_export_lambda.py"
    exit 1
fi

FUNCTION_NAME="$1"
SOURCE_FILE="$2"
shift 2

# ── Parse --extra-files (safe with empty set) ──
declare -a EXTRA_FILES=()
while [ $# -gt 0 ]; do
    case "$1" in
        --extra-files)
            shift
            while [ $# -gt 0 ] && [[ "$1" != --* ]]; do
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

# ── MCP guard: life-platform-mcp requires the full mcp/ package in the zip ──
# deploy_lambda.sh only packages the single handler file. For MCP, this strips
# the mcp/ directory and breaks the Lambda. Use the correct build pattern:
#   zip -j $ZIP mcp_server.py mcp_bridge.py && zip -r $ZIP mcp/ -x "mcp/__pycache__/*"
# See deploy/archive/20260314/deploy_mcp_consolidation.sh for reference.
if [ "$FUNCTION_NAME" = "life-platform-mcp" ]; then
    echo "❌ FATAL: Use the full MCP build — deploy_lambda.sh cannot package life-platform-mcp."
    echo "   Run this instead:"
    echo "     ZIP=/tmp/mcp_deploy.zip"
    echo "     rm -f \$ZIP"
    echo "     zip -j \$ZIP mcp_server.py mcp_bridge.py"
    echo "     zip -r \$ZIP mcp/ -x 'mcp/__pycache__/*' 'mcp/*.pyc'"
    echo "     aws lambda update-function-code --function-name life-platform-mcp --zip-file fileb://\$ZIP --region us-west-2"
    exit 1
fi

# Validate extra files exist before doing any work
for extra in "${EXTRA_FILES[@]+"${EXTRA_FILES[@]}"}"; do
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
declare -a EXTRA_BASENAMES=()
for extra in "${EXTRA_FILES[@]+"${EXTRA_FILES[@]}"}"; do
    bn=$(basename "$extra")
    cp "$extra" "$WORK_DIR/$bn"
    EXTRA_BASENAMES+=("$bn")
    echo "   + $bn"
done

# Build the zip — handle empty extras safely
if [ ${#EXTRA_BASENAMES[@]} -gt 0 ]; then
    (cd "$WORK_DIR" && zip -q deploy.zip "$EXPECTED_FILENAME" "${EXTRA_BASENAMES[@]}")
    echo "📦 Packaged $(basename "$SOURCE_FILE") + ${#EXTRA_BASENAMES[@]} extra file(s) → zip"
else
    (cd "$WORK_DIR" && zip -q deploy.zip "$EXPECTED_FILENAME")
    echo "📦 Packaged $(basename "$SOURCE_FILE") → $EXPECTED_FILENAME in zip"
fi

# ── Step 2.5: S3 rollback artifact management ──
# Shift latest → previous before overwriting. Enables rollback_lambda.sh.
S3_LATEST="deploys/${FUNCTION_NAME}/latest.zip"
S3_PREVIOUS="deploys/${FUNCTION_NAME}/previous.zip"

if aws s3 ls "s3://$BUCKET/$S3_LATEST" --region "$REGION" > /dev/null 2>&1; then
    aws s3 cp "s3://$BUCKET/$S3_LATEST" "s3://$BUCKET/$S3_PREVIOUS" \
        --region "$REGION" --no-cli-pager > /dev/null
    echo "💾 Rollback artifact saved → s3://$BUCKET/$S3_PREVIOUS"
fi

aws s3 cp "$WORK_DIR/deploy.zip" "s3://$BUCKET/$S3_LATEST" \
    --region "$REGION" --no-cli-pager > /dev/null
echo "💾 Deploy artifact stored  → s3://$BUCKET/$S3_LATEST"

# ── Step 3: Verify main handler is in the zip ──
# unzip -l columns: Length Date Time Name — use $NF (last field) for filename
ZIP_FILES=$(unzip -l "$WORK_DIR/deploy.zip" | awk 'NR>3 && NF==4 {print $NF}')
if ! echo "$ZIP_FILES" | grep -qx "$EXPECTED_FILENAME"; then
    echo "❌ FATAL: Zip does not contain handler entry '$EXPECTED_FILENAME'"
    echo "   Zip contains: $(echo "$ZIP_FILES" | tr '\n' ' ')"
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
