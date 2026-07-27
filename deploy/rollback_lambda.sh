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

# DEFAULT_REGION is the fallback for the Lambda API calls (get/update/wait).
# S3_REGION is a SEPARATE, fixed constant: the matthew-life-platform bucket
# (where deploys/<fn>/previous.zip lives) is physically in us-west-2 no matter
# what region the function itself runs in — deploy_lambda.sh's S3 rollback
# artifacts and deploy_fleet.sh's seed_artifacts() both write there. Only the
# `aws lambda` calls should ever use a per-function region override.
DEFAULT_REGION="us-west-2"
S3_REGION="us-west-2"
BUCKET="matthew-life-platform"
LAMBDA_MAP="${LAMBDA_MAP:-ci/lambda_map.json}"

# ── Region resolution (#1859) ──
# ci/lambda_map.json's "region" field lives on the SOURCE-FILE entry, keyed by
# path, not by function name — so this reverses the lookup: find the .lambdas
# entry whose .function matches $1 and return its .region (falls back to
# DEFAULT_REGION if unmapped, jq is unavailable, or the map file is missing).
# 2026-07-27 incident (#1848 evidence thread): rollback_lambda.sh hardcoded
# us-west-2 for the Lambda API call too, so the one us-east-1 function
# (email-subscriber) failed every revert with "Lambda function not found" —
# it was the 1 failed rollback of the 98/99 fire.
resolve_region() {
    local FN="$1"
    local REGION="$DEFAULT_REGION"
    if [ -f "$LAMBDA_MAP" ] && command -v jq >/dev/null 2>&1; then
        local MAP_REGION
        MAP_REGION=$(jq -r --arg fn "$FN" \
            '[.lambdas[]? | select(.function == $fn) | .region] | .[0] // empty' \
            "$LAMBDA_MAP" 2>/dev/null || true)
        if [ -n "$MAP_REGION" ]; then
            REGION="$MAP_REGION"
        fi
    fi
    echo "$REGION"
}

rollback_one() {
    local FUNCTION_NAME="$1"
    local S3_PREVIOUS="deploys/${FUNCTION_NAME}/previous.zip"
    local WORK_DIR
    WORK_DIR=$(mktemp -d)
    local REGION
    REGION=$(resolve_region "$FUNCTION_NAME")

    echo ""
    echo "🔄 Rolling back: $FUNCTION_NAME"
    if [ "$REGION" != "$DEFAULT_REGION" ]; then
        echo "  🌎 Region override from $LAMBDA_MAP: $REGION (S3 artifact store stays $S3_REGION)"
    fi

    # ── Check previous artifact exists ──
    # Distinct exit class (#1848): "no artifact" means the function is LEFT ON ITS
    # CURRENT CODE — different from a rollback that was attempted and broke.
    if ! aws s3 ls "s3://$BUCKET/$S3_PREVIOUS" --region "$S3_REGION" > /dev/null 2>&1; then
        echo "  ⤳ No previous artifact at s3://$BUCKET/$S3_PREVIOUS — left on current code"
        rm -rf "$WORK_DIR"
        return 2
    fi

    # ── Verify function exists (in ITS region, not necessarily $DEFAULT_REGION) ──
    if ! aws lambda get-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION" \
        --no-cli-pager > /dev/null 2>&1; then
        echo "  ❌ Lambda function '$FUNCTION_NAME' not found in region '$REGION'"
        rm -rf "$WORK_DIR"
        return 1
    fi

    # ── Download previous artifact (always from the S3 bucket's home region) ──
    echo "  📥 Downloading s3://$BUCKET/$S3_PREVIOUS..."
    aws s3 cp "s3://$BUCKET/$S3_PREVIOUS" "$WORK_DIR/rollback.zip" \
        --region "$S3_REGION" --no-cli-pager > /dev/null

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

# ── Main (guarded so this script can be `source`d for unit-testing
# resolve_region()/rollback_one() without tripping the usage check — #1859) ──
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    if [ $# -lt 1 ]; then
        echo "Usage: $0 <function-name> [function-name-2 ...]"
        echo "Example: $0 daily-brief"
        echo "Example: $0 daily-brief weekly-digest anomaly-detector"
        exit 1
    fi

    FAILED=0
    ROLLED_BACK=0
    MISSING=0

    for func in "$@"; do
        RC=0
        rollback_one "$func" || RC=$?
        case "$RC" in
            0) ROLLED_BACK=$((ROLLED_BACK + 1)) ;;
            2) MISSING=$((MISSING + 1)) ;;
            *) FAILED=$((FAILED + 1)) ;;
        esac
    done

    echo ""
    echo "════════════════════════════════════"
    echo "Rollback complete: $ROLLED_BACK succeeded, $MISSING no-artifact (left as-is), $FAILED failed"
    echo "════════════════════════════════════"

    if [ "$FAILED" -gt 0 ]; then
        echo "❌ Some rollbacks failed — check output above"
        exit 1
    fi
    if [ "$MISSING" -gt 0 ] && [ "$ROLLED_BACK" -eq 0 ]; then
        # Nothing was actually reverted — signal the no-artifact class distinctly so
        # callers (the CI auto-rollback job) can report it truthfully.
        exit 2
    fi
    echo "✅ All rollbacks complete"
    echo ""
    echo "Next: run smoke test to verify"
    echo "  bash deploy/post_cdk_reconcile_smoke.sh"
fi
