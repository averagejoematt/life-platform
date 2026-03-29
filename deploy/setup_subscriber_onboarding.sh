#!/bin/bash
set -euo pipefail

# First deploy of subscriber-onboarding Lambda
# Creates IAM role, Lambda function, and EventBridge daily cron

REGION="us-west-2"
FUNCTION_NAME="subscriber-onboarding"
ROLE_NAME="subscriber-onboarding-role"
SOURCE_FILE="lambdas/subscriber_onboarding_lambda.py"

echo "=== Setting up $FUNCTION_NAME ==="

# Create IAM role if it doesn't exist
if ! aws iam get-role --role-name "$ROLE_NAME" > /dev/null 2>&1; then
  echo "[1/4] Creating IAM role..."
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document '{
      "Version": "2012-10-17",
      "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "lambda.amazonaws.com"},
        "Action": "sts:AssumeRole"
      }]
    }' --no-cli-pager > /dev/null

  aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole \
    --no-cli-pager

  aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name subscriber-onboarding-access \
    --policy-document '{
      "Version": "2012-10-17",
      "Statement": [
        {
          "Effect": "Allow",
          "Action": ["dynamodb:Query", "dynamodb:UpdateItem"],
          "Resource": "arn:aws:dynamodb:us-west-2:205930651321:table/life-platform"
        },
        {
          "Effect": "Allow",
          "Action": ["ses:SendEmail"],
          "Resource": "*"
        },
        {
          "Effect": "Allow",
          "Action": ["kms:Decrypt"],
          "Resource": "arn:aws:kms:us-west-2:205930651321:key/444438d1-a5e0-43b8-9391-3cd2d70dde4d"
        }
      ]
    }' --no-cli-pager
  echo "  Waiting for role propagation..."
  sleep 10
else
  echo "[1/4] IAM role exists"
fi

ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text --no-cli-pager)

# Create or update Lambda
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" > /dev/null 2>&1; then
  echo "[2/4] Lambda exists — updating code..."
  bash deploy/deploy_lambda.sh "$FUNCTION_NAME" "$SOURCE_FILE"
else
  echo "[2/4] Creating Lambda..."
  zip -j /tmp/onboarding_deploy.zip "$SOURCE_FILE"
  aws lambda create-function \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.12 \
    --handler subscriber_onboarding_lambda.lambda_handler \
    --zip-file fileb:///tmp/onboarding_deploy.zip \
    --role "$ROLE_ARN" \
    --timeout 120 \
    --memory-size 256 \
    --environment "Variables={TABLE_NAME=life-platform,USER_ID=matthew,EMAIL_SENDER=lifeplatform@mattsusername.com,SITE_URL=https://averagejoematt.com}" \
    --region "$REGION" \
    --no-cli-pager > /dev/null
  echo "  Created $FUNCTION_NAME"
fi

# EventBridge daily cron (9 AM PT = 16:00 UTC)
RULE_NAME="subscriber-onboarding-daily"
if ! aws events describe-rule --name "$RULE_NAME" --region "$REGION" > /dev/null 2>&1; then
  echo "[3/4] Creating EventBridge rule..."
  aws events put-rule \
    --name "$RULE_NAME" \
    --schedule-expression "cron(0 16 * * ? *)" \
    --state ENABLED \
    --region "$REGION" \
    --no-cli-pager > /dev/null

  aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id eventbridge-daily \
    --action lambda:InvokeFunction \
    --principal events.amazonaws.com \
    --source-arn "arn:aws:events:$REGION:205930651321:rule/$RULE_NAME" \
    --region "$REGION" \
    --no-cli-pager > /dev/null

  aws events put-targets \
    --rule "$RULE_NAME" \
    --targets "Id=$FUNCTION_NAME,Arn=arn:aws:lambda:$REGION:205930651321:function:$FUNCTION_NAME" \
    --region "$REGION" \
    --no-cli-pager > /dev/null
  echo "  Created daily cron"
else
  echo "[3/4] EventBridge rule exists"
fi

echo "[4/4] Done."
echo "  Lambda: $FUNCTION_NAME"
echo "  Schedule: Daily 9 AM PT (16:00 UTC)"
echo "  Test: aws lambda invoke --function-name $FUNCTION_NAME --region $REGION /tmp/onboarding_test.json"
