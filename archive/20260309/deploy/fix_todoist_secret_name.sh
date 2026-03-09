#!/usr/bin/env bash
# fix_todoist_secret_name.sh — Fix stale SECRET_NAME env var on todoist Lambda
#
# The DLQ archive (2026-03-08) showed todoist-data-ingestion failing with:
#   "You can't perform this operation on the secret because it was marked for deletion"
# This means an explicit SECRET_NAME env var is overriding the code default
# and pointing to a secret that was deleted during P1 secrets consolidation.
#
# Fix: remove the stale SECRET_NAME override so the code default
# (life-platform/api-keys) takes effect.
#
# Usage: bash deploy/fix_todoist_secret_name.sh

set -euo pipefail
REGION="us-west-2"
FUNCTION="todoist-data-ingestion"

echo "=== Investigating todoist SECRET_NAME issue ==="
echo ""

# 1. Show current env vars
echo "Current environment variables:"
aws lambda get-function-configuration \
    --function-name "$FUNCTION" \
    --region "$REGION" \
    --query 'Environment.Variables' \
    --output json

echo ""

# 2. Check if SECRET_NAME is set and what it points to
SECRET_VAL=$(aws lambda get-function-configuration \
    --function-name "$FUNCTION" \
    --region "$REGION" \
    --query 'Environment.Variables.SECRET_NAME' \
    --output text 2>/dev/null || echo "None")

echo "SECRET_NAME env var: $SECRET_VAL"

if [ "$SECRET_VAL" = "None" ] || [ "$SECRET_VAL" = "null" ] || [ -z "$SECRET_VAL" ]; then
    echo ""
    echo "No SECRET_NAME env var set — issue may be transient or secret itself is deleted."
    echo "Checking if life-platform/api-keys exists..."
    aws secretsmanager describe-secret \
        --secret-id "life-platform/api-keys" \
        --region "$REGION" \
        --query '{Name:Name,DeletedDate:DeletedDate}' \
        --output json
else
    echo ""
    echo "Found stale SECRET_NAME=$SECRET_VAL — checking if this secret is pending deletion..."
    aws secretsmanager describe-secret \
        --secret-id "$SECRET_VAL" \
        --region "$REGION" \
        --query '{Name:Name,DeletedDate:DeletedDate}' \
        --output json 2>/dev/null || echo "Secret not found (already deleted)"

    echo ""
    echo "Removing stale SECRET_NAME env var from $FUNCTION..."

    # Get all current env vars, remove SECRET_NAME
    CURRENT_VARS=$(aws lambda get-function-configuration \
        --function-name "$FUNCTION" \
        --region "$REGION" \
        --query 'Environment.Variables' \
        --output json)

    # Use Python to remove the key
    NEW_VARS=$(python3 -c "
import json, sys
vars = json.loads('''$CURRENT_VARS''')
vars.pop('SECRET_NAME', None)
print(json.dumps({'Variables': vars}))
")

    aws lambda update-function-configuration \
        --function-name "$FUNCTION" \
        --environment "$NEW_VARS" \
        --region "$REGION" \
        --no-cli-pager > /dev/null

    echo "✅ Removed SECRET_NAME — Lambda will now use code default: life-platform/api-keys"
fi

echo ""
echo "=== Testing invocation ==="
aws lambda invoke \
    --function-name "$FUNCTION" \
    --region "$REGION" \
    --log-type Tail \
    /tmp/todoist_fix_test.json \
    --query 'LogResult' \
    --output text 2>/dev/null | base64 -d | grep -E "(ERROR|Secret|secret|Fetching|Saved|DynamoDB|gap)" | head -20 || true

echo ""
echo "Response: $(cat /tmp/todoist_fix_test.json)"

# Also check other ingestion Lambdas for the same stale SECRET_NAME pattern
echo ""
echo "=== Checking other ingestion Lambdas for stale SECRET_NAME ==="
for FN in habitify-data-ingestion notion-journal-ingestion dropbox-poll \
           weather-data-ingestion macrofactor-data-ingestion \
           strava-data-ingestion whoop-data-ingestion; do
    VAL=$(aws lambda get-function-configuration \
        --function-name "$FN" \
        --region "$REGION" \
        --query 'Environment.Variables.SECRET_NAME' \
        --output text 2>/dev/null || echo "error")
    if [ "$VAL" != "None" ] && [ "$VAL" != "null" ] && [ -n "$VAL" ] && [ "$VAL" != "error" ]; then
        echo "  ⚠️  $FN has SECRET_NAME=$VAL — may need audit"
    else
        echo "  ✅ $FN — no stale SECRET_NAME"
    fi
done

echo ""
echo "=== Done ==="
