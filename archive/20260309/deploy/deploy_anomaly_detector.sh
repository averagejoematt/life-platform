#!/bin/bash
# Deploy anomaly_detector Lambda
# Run from: ~/Documents/Claude/life-platform/

set -e

FUNCTION_NAME="anomaly-detector"
REGION="us-west-2"
ROLE_ARN="arn:aws:iam::205930651321:role/lambda-weekly-digest-role"
ZIP_FILE="anomaly_detector_lambda.zip"

echo "📦 Packaging..."
zip -j "$ZIP_FILE" anomaly_detector_lambda.py

# Check if function exists
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" &>/dev/null; then
  echo "🔄 Updating existing function..."
  aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP_FILE" \
    --region "$REGION"
  aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
  aws lambda update-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --timeout 90 \
    --memory-size 256 \
    --region "$REGION"
else
  echo "🆕 Creating new function..."
  aws lambda create-function \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.11 \
    --role "$ROLE_ARN" \
    --handler anomaly_detector_lambda.lambda_handler \
    --zip-file "fileb://$ZIP_FILE" \
    --timeout 90 \
    --memory-size 256 \
    --region "$REGION"
  aws lambda wait function-active --function-name "$FUNCTION_NAME" --region "$REGION"
fi

echo "⏰ Setting EventBridge schedule (8:05am PT = 15:05 UTC)..."

# Create or update the EventBridge rule
aws events put-rule \
  --name "anomaly-detector-daily" \
  --schedule-expression "cron(5 15 * * ? *)" \
  --state ENABLED \
  --region "$REGION"

# Get Lambda ARN
LAMBDA_ARN=$(aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" \
  --query 'Configuration.FunctionArn' --output text)

# Add permission for EventBridge to invoke Lambda (ignore error if already exists)
aws lambda add-permission \
  --function-name "$FUNCTION_NAME" \
  --statement-id "anomaly-detector-eventbridge" \
  --action "lambda:InvokeFunction" \
  --principal "events.amazonaws.com" \
  --source-arn "arn:aws:events:$REGION:205930651321:rule/anomaly-detector-daily" \
  --region "$REGION" 2>/dev/null || echo "  (permission already exists — skipping)"

# Wire EventBridge rule to Lambda
aws events put-targets \
  --rule "anomaly-detector-daily" \
  --targets "Id=anomaly-detector-target,Arn=$LAMBDA_ARN" \
  --region "$REGION"

echo ""
echo "✅ Deployed: $FUNCTION_NAME"
echo "   Schedule: 8:05am PT daily (cron(5 15 * * ? *))"
echo "   Runs BEFORE daily-brief (8:15am PT)"
echo ""
echo "🧪 Test invoke:"
echo "   aws lambda invoke --function-name $FUNCTION_NAME --region $REGION --payload '{}' /tmp/anomaly-test.json && cat /tmp/anomaly-test.json"
