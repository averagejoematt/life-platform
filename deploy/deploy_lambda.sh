#!/bin/bash
# deploy_lambda.sh — Universal Lambda deploy helper (#781: full-bundle, always)
#
# Ships the SAME staged full-tree bundle CDK deploys (deploy/build_bundle.py):
# the whole lambdas/ tree + food_vocabulary.json, so a hot deploy can never
# strip sibling modules or shared modules again (the "single-file deploy strips
# siblings" incident class is structurally dead, and there is no shared layer
# to drift from — #781 retired it).
#
# The <source-file> argument is kept for interface compatibility and sanity
# checking (the file must exist and the live handler must resolve inside the
# bundle). --extra-files is accepted but ignored — everything ships already.
#
# Usage:
#   ./deploy/deploy_lambda.sh <function-name> <source-file>
#
# life-platform-mcp / life-platform-mcp-warmer get the mcp-shaped bundle
# (tree + mcp_server.py + mcp/).
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
    echo "Usage: $0 <function-name> <source-file>"
    echo "Example: $0 whoop-data-ingestion lambdas/ingestion/whoop_lambda.py"
    exit 1
fi

FUNCTION_NAME="$1"
SOURCE_FILE="$2"
shift 2

# --extra-files kept for interface compat; the full bundle already ships everything.
while [ $# -gt 0 ]; do
    case "$1" in
        --extra-files)
            echo "ℹ️  --extra-files ignored — the full-tree bundle already contains every module (#781)"
            ;;
    esac
    shift
done

# ── Resolve region (per-Lambda override) ──
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

HANDLER_MODULE_PATH="${HANDLER%.*}"                      # "ingestion.whoop_lambda" or "whoop_lambda"
EXPECTED_FILENAME="${HANDLER_MODULE_PATH//.//}.py"       # "ingestion/whoop_lambda.py" or "whoop_lambda.py"

echo "   Handler: $HANDLER"
echo "   Expected bundle entry: $EXPECTED_FILENAME"

# ── Step 2: Stage + zip the full bundle ──
WORK_DIR=$(mktemp -d)
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BUNDLE_FLAG=""
case "$FUNCTION_NAME" in
    life-platform-mcp|life-platform-mcp-warmer) BUNDLE_FLAG="--mcp" ;;
esac

python3 "$ROOT/deploy/build_bundle.py" $BUNDLE_FLAG --out "$WORK_DIR/stage" --zip "$WORK_DIR/deploy.zip"

# ── Step 3: Verify the live handler resolves inside the bundle ──
if [ ! -f "$WORK_DIR/stage/$EXPECTED_FILENAME" ]; then
    echo "❌ FATAL: bundle does not contain handler entry '$EXPECTED_FILENAME'"
    echo "   The live handler ($HANDLER) doesn't match the repo tree layout."
    rm -rf "$WORK_DIR"
    exit 1
fi

# ── Step 3.5: S3 rollback artifact management ──
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
