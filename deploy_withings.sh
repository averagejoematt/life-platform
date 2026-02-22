#!/bin/bash
# Deploy Withings Lambda function
# Reuses the same IAM role as Whoop (lambda-whoop-ingestion-role)
# since permissions are identical (S3, DynamoDB, Secrets Manager, CloudWatch)

set -e
REGION="us-west-2"
ACCOUNT="205930651321"
ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/lambda-whoop-ingestion-role"
FUNCTION_NAME="withings-data-ingestion"

echo "=== Packaging Lambda ==="
cd "$(dirname "$0")"
zip withings_lambda.zip withings_lambda.py
echo "Package created: withings_lambda.zip"

echo ""
echo "=== Deploying Lambda ==="
# Check if function already exists
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" &>/dev/null; then
    echo "Updating existing function..."
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file fileb://withings_lambda.zip \
        --region "$REGION"
else
    echo "Creating new function..."
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.12 \
        --role "$ROLE_ARN" \
        --handler withings_lambda.lambda_handler \
        --zip-file fileb://withings_lambda.zip \
        --timeout 60 \
        --memory-size 256 \
        --region "$REGION"
fi

echo ""
echo "=== Setting EventBridge Schedule (6:30 AM PT daily) ==="
# 14:30 UTC = 6:30 AM PT (offset from Whoop at 14:00 so they don't overlap)
RULE_NAME="withings-daily-ingestion"

aws events put-rule \
    --name "$RULE_NAME" \
    --schedule-expression "cron(30 14 * * ? *)" \
    --state ENABLED \
    --region "$REGION"

FUNCTION_ARN="arn:aws:lambda:${REGION}:${ACCOUNT}:function:${FUNCTION_NAME}"

aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "EventBridgeInvoke-withings" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "arn:aws:events:${REGION}:${ACCOUNT}:rule/${RULE_NAME}" \
    --region "$REGION" 2>/dev/null || echo "Permission already exists, skipping."

aws events put-targets \
    --rule "$RULE_NAME" \
    --targets "Id=WithingsLambda,Arn=${FUNCTION_ARN}" \
    --region "$REGION"

echo ""
echo "=== Done ==="
echo "Function: $FUNCTION_NAME"
echo "Schedule: 6:30 AM PT daily (cron 30 14 * * ? *)"
echo ""
echo "Test with:"
echo "  aws lambda invoke --function-name $FUNCTION_NAME --region $REGION /tmp/withings_output.json && cat /tmp/withings_output.json"
