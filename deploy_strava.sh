#!/bin/bash
set -e

FUNCTION_NAME="strava-data-ingestion"
ROLE_ARN="arn:aws:iam::205930651321:role/lambda-whoop-ingestion-role"
REGION="us-west-2"

echo "=== Deploying Strava Lambda ==="

# Package
cp strava_lambda.py lambda_function.py
zip -r strava_lambda.zip lambda_function.py
rm lambda_function.py

# Create or update
if aws lambda get-function --function-name $FUNCTION_NAME --region $REGION 2>/dev/null; then
  echo "Updating existing function..."
  aws lambda update-function-code \
    --function-name $FUNCTION_NAME \
    --zip-file fileb://strava_lambda.zip \
    --region $REGION
else
  echo "Creating new function..."
  aws lambda create-function \
    --function-name $FUNCTION_NAME \
    --runtime python3.12 \
    --role $ROLE_ARN \
    --handler lambda_function.lambda_handler \
    --zip-file fileb://strava_lambda.zip \
    --timeout 300 \
    --memory-size 256 \
    --region $REGION
fi

echo "Waiting for function to be active..."
aws lambda wait function-active --function-name $FUNCTION_NAME --region $REGION

# EventBridge schedule: 7 AM PT daily (15:00 UTC)
aws events put-rule \
  --name "strava-daily-ingestion" \
  --schedule-expression "cron(0 15 * * ? *)" \
  --state ENABLED \
  --region $REGION

FUNCTION_ARN=$(aws lambda get-function --function-name $FUNCTION_NAME --region $REGION --query 'Configuration.FunctionArn' --output text)

aws lambda add-permission \
  --function-name $FUNCTION_NAME \
  --statement-id strava-eventbridge \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn "arn:aws:events:$REGION:205930651321:rule/strava-daily-ingestion" \
  --region $REGION 2>/dev/null || echo "Permission already exists"

aws events put-targets \
  --rule "strava-daily-ingestion" \
  --targets "Id=strava-lambda,Arn=$FUNCTION_ARN" \
  --region $REGION

echo "=== Strava Lambda deployed successfully ==="
echo "Schedule: 7:00 AM PT daily"
