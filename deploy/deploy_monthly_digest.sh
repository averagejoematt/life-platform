#!/bin/bash
# Deploy Monthly Coach's Letter Lambda
# Usage: ./deploy_monthly_digest.sh

set -e

FUNCTION_NAME="monthly-digest"
ROLE_ARN="arn:aws:iam::205930651321:role/lambda-weekly-digest-role"
REGION="us-west-2"
LAMBDA_FILE="monthly_digest_lambda.py"
ZIP_FILE="/tmp/monthly_digest.zip"

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

  aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"

  echo "[3/4] Updating configuration..."
  aws lambda update-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --timeout 120 \
    --memory-size 256 \
    --region "$REGION" > /dev/null
  echo "  ✓ Config updated (120s timeout for Haiku 2500 tokens)"
else
  echo "[2/4] Creating new function..."
  aws lambda create-function \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.11 \
    --role "$ROLE_ARN" \
    --handler lambda_function.lambda_handler \
    --zip-file "fileb://$ZIP_FILE" \
    --timeout 120 \
    --memory-size 256 \
    --region "$REGION" > /dev/null
  echo "  ✓ Function created (120s timeout)"

  aws lambda wait function-active --function-name "$FUNCTION_NAME" --region "$REGION"
  echo "  ✓ Function active"

  echo "[3/4] Creating EventBridge rule (first Sunday of month, 8am PT = 16:00 UTC)..."
  # cron(0 16 ? * 1#1 *) = first Sunday of month at 16:00 UTC
  aws events put-rule \
    --name "monthly-digest-schedule" \
    --schedule-expression "cron(0 16 ? * 1#1 *)" \
    --state ENABLED \
    --region "$REGION" > /dev/null

  LAMBDA_ARN=$(aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" \
    --query "Configuration.FunctionArn" --output text)

  aws events put-targets \
    --rule "monthly-digest-schedule" \
    --targets "Id=monthly-digest-target,Arn=$LAMBDA_ARN" \
    --region "$REGION" > /dev/null

  aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "allow-eventbridge-monthly-digest" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "arn:aws:events:$REGION:205930651321:rule/monthly-digest-schedule" \
    --region "$REGION" > /dev/null

  echo "  ✓ EventBridge rule created: first Sunday of month at 8am PT"
fi

echo "[4/4] Done."
echo ""
echo "=== Test with ==="
echo "aws lambda invoke \\"
echo "  --function-name $FUNCTION_NAME \\"
echo "  --payload '{}' \\"
echo "  --cli-binary-format raw-in-base64-out \\"
echo "  --region $REGION \\"
echo "  /tmp/monthly_digest_out.json && cat /tmp/monthly_digest_out.json"
