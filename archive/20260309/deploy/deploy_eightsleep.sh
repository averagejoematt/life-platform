#!/bin/bash
# deploy_eightsleep.sh — Deploy Eight Sleep ingestion Lambda + EventBridge schedule
#
# Reuses the existing IAM role (lambda-whoop-ingestion-role) which already has
# the permissions needed: DynamoDB, S3, Secrets Manager, CloudWatch Logs.
#
# Schedule: 10:00 AM PT daily (18:00 UTC) — after sleep data is available.
# Eight Sleep finalises sleep scores a few hours after wake, so 10am is safe.

set -e
REGION="us-west-2"
ACCOUNT="205930651321"
ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/lambda-whoop-ingestion-role"
FUNCTION_NAME="eightsleep-data-ingestion"

echo "=== Packaging Lambda ==="
cd "$(dirname "$0")"
zip eightsleep_lambda.zip eightsleep_lambda.py
echo "Package created: eightsleep_lambda.zip"

echo ""
echo "=== Deploying Lambda ==="
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" &>/dev/null; then
    echo "Updating existing function..."
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file fileb://eightsleep_lambda.zip \
        --region "$REGION"
else
    echo "Creating new function..."
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.12 \
        --role "$ROLE_ARN" \
        --handler eightsleep_lambda.lambda_handler \
        --zip-file fileb://eightsleep_lambda.zip \
        --timeout 60 \
        --memory-size 256 \
        --region "$REGION"
fi

echo ""
echo "=== Setting EventBridge Schedule (10:00 AM PT daily) ==="
# 18:00 UTC = 10:00 AM PT
RULE_NAME="eightsleep-daily-ingestion"

aws events put-rule \
    --name "$RULE_NAME" \
    --schedule-expression "cron(0 18 * * ? *)" \
    --state ENABLED \
    --region "$REGION"

FUNCTION_ARN="arn:aws:lambda:${REGION}:${ACCOUNT}:function:${FUNCTION_NAME}"

aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "EventBridgeInvoke-eightsleep" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "arn:aws:events:${REGION}:${ACCOUNT}:rule/${RULE_NAME}" \
    --region "$REGION" 2>/dev/null || echo "Permission already exists, skipping."

aws events put-targets \
    --rule "$RULE_NAME" \
    --targets "Id=EightSleepLambda,Arn=${FUNCTION_ARN}" \
    --region "$REGION"

echo ""
echo "=== Done ==="
echo "Function : $FUNCTION_NAME"
echo "Schedule : 10:00 AM PT daily (cron 0 18 * * ? *)"
echo ""
echo "Next steps:"
echo "  1. Create the secret first (see setup instructions below)"
echo "  2. Test with:"
echo "     aws lambda invoke \\"
echo "       --function-name $FUNCTION_NAME \\"
echo "       --payload '{\"date\": \"$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d yesterday +%Y-%m-%d)\"}' \\"
echo "       --region $REGION /tmp/eightsleep_test.json"
echo "     cat /tmp/eightsleep_test.json"
echo ""
echo "=== Secret setup (run once before deploying) ==="
echo "aws secretsmanager create-secret \\"
echo "  --name life-platform/eightsleep \\"
echo "  --region $REGION \\"
echo "  --secret-string '{"
echo "    \"email\": \"YOUR_EIGHTSLEEP_EMAIL\","
echo "    \"password\": \"YOUR_EIGHTSLEEP_PASSWORD\","
echo "    \"user_id\": \"\","
echo "    \"access_token\": \"\","
echo "    \"refresh_token\": \"\","
echo "    \"bed_side\": \"left\","
echo "    \"timezone\": \"America/Los_Angeles\""
echo "  }'"
