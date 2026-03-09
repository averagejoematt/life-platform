#!/bin/bash
# Deploy Daily Brief Lambda
# Usage: ./deploy_daily_brief.sh

set -e

FUNCTION_NAME="daily-brief"
ROLE_ARN="arn:aws:iam::205930651321:role/lambda-weekly-digest-role"
REGION="us-west-2"
LAMBDA_FILE="daily_brief_lambda.py"
ZIP_FILE="/tmp/daily_brief.zip"

echo "=== Deploying $FUNCTION_NAME ==="

# Package
echo "[1/4] Packaging..."
cp "$LAMBDA_FILE" /tmp/lambda_function.py
cd /tmp && zip -j "$ZIP_FILE" lambda_function.py
cd - > /dev/null
echo "  ✓ Packaged: $ZIP_FILE"

# Check if function exists
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" > /dev/null 2>&1; then
  echo "[2/4] Updating existing function..."
  aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP_FILE" \
    --region "$REGION" > /dev/null
  echo "  ✓ Code updated"

  # Wait for update to complete
  aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"

  echo "[3/4] Updating configuration..."
  aws lambda update-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --timeout 60 \
    --memory-size 256 \
    --region "$REGION" > /dev/null
  echo "  ✓ Config updated"
else
  echo "[2/4] Creating new function..."
  aws lambda create-function \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.11 \
    --role "$ROLE_ARN" \
    --handler lambda_function.lambda_handler \
    --zip-file "fileb://$ZIP_FILE" \
    --timeout 60 \
    --memory-size 256 \
    --region "$REGION" > /dev/null
  echo "  ✓ Function created"

  # Wait for function to be active
  echo "  Waiting for function to be active..."
  aws lambda wait function-active --function-name "$FUNCTION_NAME" --region "$REGION"
  echo "  ✓ Function active"

  echo "[3/4] Creating EventBridge rule (daily 8:15am PT = 15:15 UTC)..."
  # Create the rule
  aws events put-rule \
    --name "daily-brief-schedule" \
    --schedule-expression "cron(15 15 * * ? *)" \
    --state ENABLED \
    --region "$REGION" > /dev/null

  # Get Lambda ARN
  LAMBDA_ARN=$(aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" \
    --query "Configuration.FunctionArn" --output text)

  # Add EventBridge target
  aws events put-targets \
    --rule "daily-brief-schedule" \
    --targets "Id=daily-brief-target,Arn=$LAMBDA_ARN" \
    --region "$REGION" > /dev/null

  # Allow EventBridge to invoke Lambda
  aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "allow-eventbridge-daily-brief" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "arn:aws:events:$REGION:205930651321:rule/daily-brief-schedule" \
    --region "$REGION" > /dev/null

  echo "  ✓ EventBridge rule created: daily at 8:15am PT"
fi

echo "[4/4] Done."
echo ""
echo "=== Test with ==="
echo "aws lambda invoke \\"
echo "  --function-name $FUNCTION_NAME \\"
echo "  --payload '{}' \\"
echo "  --cli-binary-format raw-in-base64-out \\"
echo "  --region $REGION \\"
echo "  /tmp/daily_brief_out.json && cat /tmp/daily_brief_out.json"
