#!/bin/bash
# Deploy Daily Brief v2.47.0 (Habit Intelligence v1 + habit_scores storage)
# Now includes: tier-weighted scoring, vice streaks, registry-enriched BoD,
#               AND daily habit_scores persistence to DynamoDB for trending.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
LAMBDA_NAME="daily-brief"

echo "=== Deploying Daily Brief v2.47.0 (Habit Intelligence v1 + Storage) ==="

# Verify the source file exists
SOURCE_FILE="${ROOT_DIR}/lambdas/daily_brief_lambda.py"
if [ ! -f "$SOURCE_FILE" ]; then
    echo "ERROR: Source file not found: $SOURCE_FILE"
    echo "Download from Claude outputs and save to lambdas/daily_brief_lambda.py first."
    exit 1
fi

# Create zip with Lambda handler name
cd "${ROOT_DIR}/lambdas"
cp daily_brief_lambda.py lambda_function.py
zip -j daily_brief_lambda.zip lambda_function.py
rm lambda_function.py
echo "Created: ${ROOT_DIR}/lambdas/daily_brief_lambda.zip ($(wc -c < daily_brief_lambda.zip) bytes)"

# Deploy
echo "Deploying to Lambda: ${LAMBDA_NAME}..."
aws lambda update-function-code \
    --function-name "${LAMBDA_NAME}" \
    --zip-file "fileb://daily_brief_lambda.zip" \
    --region us-west-2

echo ""
echo "=== Deploy Complete ==="
echo "  Function: ${LAMBDA_NAME}"
echo "  Version: v2.47.0"
echo "  New: store_habit_scores() writes to habit_scores partition daily"
echo "  MCP: 3 new tools (get_habit_registry, get_habit_tier_report, get_vice_streak_history)"
echo ""
echo "=== Verify ==="
echo "  aws lambda get-function-configuration --function-name ${LAMBDA_NAME} --region us-west-2 --query 'LastModified'"
echo ""
echo "=== First registry-powered brief: tomorrow 10am PT ==="
echo ""
echo "=== Rollback ==="
echo "  aws lambda update-function-code --function-name ${LAMBDA_NAME} --zip-file fileb://lambdas/daily_brief_lambda_BACKUP.zip --region us-west-2"
