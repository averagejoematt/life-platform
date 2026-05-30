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
#   ./deploy/deploy_lambda.sh health-auto-export-webhook lambdas/ingestion/health_auto_export_lambda.py
#   ./deploy/deploy_lambda.sh daily-brief lambdas/emails/daily_brief_lambda.py \
#       --extra-files lambdas/ai_calls.py lambdas/html_builder.py lambdas/output_writers.py lambdas/board_loader.py
#
# Rollback:
#   Each deploy shifts the previous zip to s3://.../deploys/<func>/previous.zip.
#   Run: bash deploy/rollback_lambda.sh <function-name>

set -euo pipefail

# Default region. Per-Lambda overrides come from ci/lambda_map.json's "region"
# field — see the resolution block below. 2026-05-29 incident: email-subscriber
# lives in us-east-1 (CloudFront origin) but a vestigial twin exists in us-west-2.
# Without per-Lambda regions, this script silently updated the dead twin while
# production stayed stale — CI reported "success" but the change wasn't live.
DEFAULT_REGION="us-west-2"
LAMBDA_MAP="${LAMBDA_MAP:-ci/lambda_map.json}"
BUCKET="matthew-life-platform"

if [ $# -lt 2 ]; then
    echo "Usage: $0 <function-name> <source-file> [--extra-files file1.py ...]"
    echo "Example: $0 health-auto-export-webhook lambdas/ingestion/health_auto_export_lambda.py"
    exit 1
fi

FUNCTION_NAME="$1"
SOURCE_FILE="$2"
shift 2

# ── Resolve region (per-Lambda override) ──
# 1. Read region from lambda_map.json if present.
# 2. Else default to us-west-2.
# 3. Verify the function actually exists in the chosen region — fail loudly
#    if it doesn't. Crossing regions silently is exactly what broke 2026-05-29.
REGION="$DEFAULT_REGION"
if [ -f "$LAMBDA_MAP" ] && command -v jq >/dev/null 2>&1; then
    MAP_REGION=$(jq -r --arg f "$SOURCE_FILE" '.lambdas[$f].region // empty' "$LAMBDA_MAP")
    if [ -n "$MAP_REGION" ]; then
        REGION="$MAP_REGION"
        echo "🌎 Region override from $LAMBDA_MAP: $REGION"
    fi
fi
if ! aws lambda get-function-configuration --function-name "$FUNCTION_NAME" --region "$REGION" \
        --query 'FunctionName' --output text --no-cli-pager > /dev/null 2>&1; then
    echo "❌ Function '$FUNCTION_NAME' not found in region '$REGION'."
    echo "   If it lives in another region, add"
    echo "     \"region\": \"us-east-1\""
    echo "   to its entry in $LAMBDA_MAP and re-run."
    exit 1
fi

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

# Handler format examples:
#   Flat:       whoop_lambda.lambda_handler           → zip entry: whoop_lambda.py
#   Subpkg:     ingestion.whoop_lambda.lambda_handler → zip entry: ingestion/whoop_lambda.py
# We strip the final `.lambda_handler` (or other entry-point) and convert the
# remaining dots to slashes for the zip layout. Then the Lambda runtime can
# import the handler module by its full qualified name (P3.1).
HANDLER_FN="${HANDLER##*.}"                              # "lambda_handler"
HANDLER_MODULE_PATH="${HANDLER%.*}"                      # "ingestion.whoop_lambda" or "whoop_lambda"
EXPECTED_FILENAME="${HANDLER_MODULE_PATH//.//}.py"       # "ingestion/whoop_lambda.py" or "whoop_lambda.py"

echo "   Handler: $HANDLER"
echo "   Expected zip entry: $EXPECTED_FILENAME"

# ── Step 2: Package with the correct filename ──
WORK_DIR=$(mktemp -d)

# Create any parent directories the handler needs (e.g., ingestion/)
EXPECTED_DIR=$(dirname "$EXPECTED_FILENAME")
if [ "$EXPECTED_DIR" != "." ]; then
    mkdir -p "$WORK_DIR/$EXPECTED_DIR"
    # Lambda needs __init__.py to recognize the subpackage at runtime
    touch "$WORK_DIR/$EXPECTED_DIR/__init__.py"
fi

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
# P3.1: zip -r handles subdirectories (ingestion/whoop_lambda.py) + __init__.py
if [ ${#EXTRA_BASENAMES[@]} -gt 0 ]; then
    (cd "$WORK_DIR" && zip -qr deploy.zip "$EXPECTED_FILENAME" "${EXTRA_BASENAMES[@]}")
    # Include __init__.py if the handler is in a subpackage
    if [ "$EXPECTED_DIR" != "." ]; then
        (cd "$WORK_DIR" && zip -qr deploy.zip "${EXPECTED_DIR}/__init__.py")
    fi
    echo "📦 Packaged $(basename "$SOURCE_FILE") + ${#EXTRA_BASENAMES[@]} extra file(s) → zip"
else
    (cd "$WORK_DIR" && zip -qr deploy.zip "$EXPECTED_FILENAME")
    if [ "$EXPECTED_DIR" != "." ]; then
        (cd "$WORK_DIR" && zip -qr deploy.zip "${EXPECTED_DIR}/__init__.py")
    fi
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
