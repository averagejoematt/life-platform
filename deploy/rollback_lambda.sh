#!/bin/bash
# rollback_lambda.sh — Roll back a Lambda to its previous deployed artifact
#
# Uses the S3 artifact store maintained by deploy_lambda.sh.
# Each deploy shifts: latest.zip → previous.zip. This script redeploys previous.zip.
#
# Usage:
#   bash deploy/rollback_lambda.sh <function-name>
#   bash deploy/rollback_lambda.sh daily-brief
#
# Multiple rollbacks:
#   bash deploy/rollback_lambda.sh daily-brief
#   bash deploy/rollback_lambda.sh weekly-digest
#
# Note: Consecutive rollbacks of the same function will re-deploy the same artifact
# (previous.zip is not rotated further). For older versions, use S3 versioning or
# re-deploy from source.

set -euo pipefail

REGION="us-west-2"
BUCKET="matthew-life-platform"

if [ $# -lt 1 ]; then
    echo "Usage: $0 <function-name> [function-name-2 ...]"
    echo "Example: $0 daily-brief"
    echo "Example: $0 daily-brief weekly-digest anomaly-detector"
    exit 1
fi

rollback_one() {
    local FUNCTION_NAME="$1"
    local S3_PREVIOUS="deploys/${FUNCTION_NAME}/previous.zip"
    local WORK_DIR
    WORK_DIR=$(mktemp -d)

    echo ""
    echo "🔄 Rolling back: $FUNCTION_NAME"

    # ── Check previous artifact exists ──
    if ! aws s3 ls "s3://$BUCKET/$S3_PREVIOUS" --region "$REGION" > /dev/null 2>&1; then
        echo "  ❌ No previous artifact found at s3://$BUCKET/$S3_PREVIOUS"
        echo "     (Was this function ever deployed via deploy_lambda.sh?)"
        rm -rf "$WORK_DIR"
        return 1
    fi

    # ── Verify function exists ──
    if ! aws lambda get-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION" \
        --no-cli-pager > /dev/null 2>&1; then
        echo "  ❌ Lambda function '$FUNCTION_NAME' not found in AWS"
        rm -rf "$WORK_DIR"
        return 1
    fi

    # ── Download previous artifact ──
    echo "  📥 Downloading s3://$BUCKET/$S3_PREVIOUS..."
    aws s3 cp "s3://$BUCKET/$S3_PREVIOUS" "$WORK_DIR/rollback.zip" \
        --region "$REGION" --no-cli-pager > /dev/null

    # ── Verify zip is non-empty ──
    ZIP_SIZE=$(wc -c < "$WORK_DIR/rollback.zip")
    if [ "$ZIP_SIZE" -lt 100 ]; then
        echo "  ❌ Downloaded artifact is suspiciously small ($ZIP_SIZE bytes) — aborting"
        rm -rf "$WORK_DIR"
        return 1
    fi

    # ── Confirm ──
    echo "  Artifact size: $ZIP_SIZE bytes"
    echo "  Zip contents:"
    unzip -l "$WORK_DIR/rollback.zip" | awk 'NR>3 && NF==4 {print "    " $NF}'

    # ── Deploy ──
    echo "  🚀 Deploying rollback artifact to $FUNCTION_NAME..."
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file "fileb://$WORK_DIR/rollback.zip" \
        --region "$REGION" \
        --no-cli-pager > /dev/null

    # ── Wait for active ──
    echo "  ⏳ Waiting for function to become active..."
    aws lambda wait function-updated \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION"

    LAST_MODIFIED=$(aws lambda get-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION" \
        --query "LastModified" --output text --no-cli-pager)

    echo "  ✅ $FUNCTION_NAME rolled back (modified: $LAST_MODIFIED)"
    rm -rf "$WORK_DIR"
}

FAILED=0
ROLLED_BACK=0

for func in "$@"; do
    if rollback_one "$func"; then
        ROLLED_BACK=$((ROLLED_BACK + 1))
    else
        FAILED=$((FAILED + 1))
    fi
done

echo ""
echo "════════════════════════════════════"
echo "Rollback complete: $ROLLED_BACK succeeded, $FAILED failed"
echo "════════════════════════════════════"

if [ "$FAILED" -gt 0 ]; then
    echo "❌ Some rollbacks failed — check output above"
    exit 1
fi
echo "✅ All rollbacks complete"
echo ""
echo "Next: run smoke test to verify"
echo "  bash deploy/post_cdk_reconcile_smoke.sh"
