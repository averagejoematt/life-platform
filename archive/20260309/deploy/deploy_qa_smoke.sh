#!/bin/bash
# deploy_qa_smoke.sh — Deploy QA smoke test Lambda + EventBridge trigger
# Run from project root: bash deploy/deploy_qa_smoke.sh

set -euo pipefail

REGION="us-west-2"
ACCOUNT="205930651321"
FUNCTION="life-platform-qa-smoke"
ROLE="arn:aws:iam::${ACCOUNT}:role/lambda-weekly-digest-role"
SCHEDULE="cron(30 18 ? * * *)"   # 10:30 AM PT daily

echo "=== Deploying QA Smoke Test Lambda ==="

# Package
cd lambdas
zip -j /tmp/qa_smoke.zip qa_smoke_lambda.py
cd ..

# Create or update function
if aws lambda get-function --function-name "$FUNCTION" --region "$REGION" &>/dev/null; then
  echo "Updating existing Lambda..."
  aws lambda update-function-code \
    --function-name "$FUNCTION" \
    --zip-file fileb:///tmp/qa_smoke.zip \
    --region "$REGION" --no-cli-pager

  sleep 5

  aws lambda update-function-configuration \
    --function-name "$FUNCTION" \
    --environment 'Variables={
      TABLE_NAME=life-platform,
      S3_BUCKET=matthew-life-platform,
      EMAIL_RECIPIENT=awsdev@mattsusername.com,
      EMAIL_SENDER=awsdev@mattsusername.com
    }' \
    --timeout 120 \
    --memory-size 256 \
    --region "$REGION" --no-cli-pager
else
  echo "Creating new Lambda..."
  aws lambda create-function \
    --function-name "$FUNCTION" \
    --runtime python3.12 \
    --role "$ROLE" \
    --handler qa_smoke_lambda.lambda_handler \
    --zip-file fileb:///tmp/qa_smoke.zip \
    --timeout 120 \
    --memory-size 256 \
    --environment 'Variables={
      TABLE_NAME=life-platform,
      S3_BUCKET=matthew-life-platform,
      EMAIL_RECIPIENT=awsdev@mattsusername.com,
      EMAIL_SENDER=awsdev@mattsusername.com
    }' \
    --region "$REGION" --no-cli-pager

  # EventBridge rule
  RULE_ARN=$(aws events put-rule \
    --name "life-platform-qa-smoke" \
    --schedule-expression "$SCHEDULE" \
    --state ENABLED \
    --region "$REGION" \
    --query "RuleArn" --output text --no-cli-pager)
  echo "EventBridge rule: $RULE_ARN"

  LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT}:function:${FUNCTION}"

  aws lambda add-permission \
    --function-name "$FUNCTION" \
    --statement-id "AllowEventBridgeQASmoke" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "$RULE_ARN" \
    --region "$REGION" --no-cli-pager

  aws events put-targets \
    --rule "life-platform-qa-smoke" \
    --targets "Id=qa-smoke-target,Arn=$LAMBDA_ARN" \
    --region "$REGION" --no-cli-pager
fi

echo ""
echo "=== Done. Lambda updated with 4h dashboard freshness threshold. ==="
