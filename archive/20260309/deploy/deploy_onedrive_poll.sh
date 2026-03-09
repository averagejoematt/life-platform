#!/bin/bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════════════════
# OneDrive Poll Lambda — Deploy
#
# Polls OneDrive:/life-platform/ for MacroFactor CSVs → S3 → existing pipeline.
# Removes the laptop hop from the MacroFactor ingestion flow.
#
# Prerequisites:
#   - Run setup_onedrive_auth.py first (stores refresh token in Secrets Manager)
#   - Existing macrofactor-data-ingestion Lambda with S3 trigger
#
# Usage: bash deploy_onedrive_poll.sh
# ══════════════════════════════════════════════════════════════════════════════

cd ~/Documents/Claude/life-platform

echo "═══════════════════════════════════════════════════"
echo "  OneDrive Poll Lambda — Deploy"
echo "═══════════════════════════════════════════════════"
echo ""

REGION="us-west-2"
ACCOUNT_ID="205930651321"
TABLE_NAME="life-platform"
S3_BUCKET="matthew-life-platform"
SNS_TOPIC_ARN="arn:aws:sns:${REGION}:${ACCOUNT_ID}:life-platform-alerts"
FUNCTION_NAME="onedrive-poll"
ROLE_NAME="lambda-onedrive-poll-role"

# ── Step 1: Verify OneDrive secret exists ─────────────────────────────────────
echo "Step 1: Verifying OneDrive credentials..."
echo "──────────────────────────────────────────"

if aws secretsmanager describe-secret --secret-id "life-platform/onedrive" --region "$REGION" 2>/dev/null; then
    echo "  ✓ Secret exists: life-platform/onedrive"
else
    echo "  ❌ Secret not found. Run setup_onedrive_auth.py first."
    exit 1
fi
echo ""

# ── Step 2: IAM Role ─────────────────────────────────────────────────────────
echo "Step 2: Creating IAM role..."
echo "────────────────────────────"

TRUST_POLICY='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

if aws iam get-role --role-name "$ROLE_NAME" 2>/dev/null; then
    echo "  ✓ Role already exists"
else
    aws iam create-role \
        --role-name "$ROLE_NAME" \
        --assume-role-policy-document "$TRUST_POLICY" > /dev/null

    POLICY='{
      "Version": "2012-10-17",
      "Statement": [
        {
          "Effect": "Allow",
          "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"],
          "Resource": "arn:aws:dynamodb:'$REGION':'$ACCOUNT_ID':table/'$TABLE_NAME'"
        },
        {
          "Effect": "Allow",
          "Action": ["s3:PutObject"],
          "Resource": "arn:aws:s3:::'$S3_BUCKET'/uploads/macrofactor/*"
        },
        {
          "Effect": "Allow",
          "Action": ["secretsmanager:GetSecretValue", "secretsmanager:UpdateSecret"],
          "Resource": [
            "arn:aws:secretsmanager:'$REGION':'$ACCOUNT_ID':secret:life-platform/onedrive-*"
          ]
        },
        {
          "Effect": "Allow",
          "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
          "Resource": "arn:aws:logs:'$REGION':'$ACCOUNT_ID':log-group:/aws/lambda/'$FUNCTION_NAME':*"
        }
      ]
    }'
    aws iam put-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-name "onedrive-poll-policy" \
        --policy-document "$POLICY" > /dev/null
    echo "  ✓ Role + policy created"
    echo "  Waiting 10s for IAM propagation..."
    sleep 10
fi
echo ""

# ── Step 3: Deploy Lambda ────────────────────────────────────────────────────
echo "Step 3: Deploying Lambda..."
echo "───────────────────────────"

ZIP_FILE="onedrive_poll_lambda.zip"
rm -f "$ZIP_FILE"
zip -q "$ZIP_FILE" onedrive_poll_lambda.py

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" 2>/dev/null; then
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file "fileb://$ZIP_FILE" \
        --region "$REGION" > /dev/null
    aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
    echo "  ✓ Lambda updated"
else
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.12 \
        --handler onedrive_poll_lambda.lambda_handler \
        --role "$ROLE_ARN" \
        --zip-file "fileb://$ZIP_FILE" \
        --timeout 120 \
        --memory-size 128 \
        --environment "Variables={TABLE_NAME=$TABLE_NAME,S3_BUCKET=$S3_BUCKET,SECRET_NAME=life-platform/onedrive,ONEDRIVE_FOLDER=life-platform}" \
        --region "$REGION" > /dev/null
    aws lambda wait function-active --function-name "$FUNCTION_NAME" --region "$REGION"
    echo "  ✓ Lambda created"
fi
echo ""

# ── Step 4: EventBridge schedule (every 30 min) ──────────────────────────────
echo "Step 4: Setting up schedule..."
echo "──────────────────────────────"

RULE_NAME="onedrive-poll-schedule"

aws events put-rule \
    --name "$RULE_NAME" \
    --schedule-expression "rate(30 minutes)" \
    --state ENABLED \
    --description "Poll OneDrive for MacroFactor CSV exports every 30 min" \
    --region "$REGION" > /dev/null

LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"

aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "onedrive-poll-eventbridge" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "arn:aws:events:${REGION}:${ACCOUNT_ID}:rule/${RULE_NAME}" \
    --region "$REGION" 2>/dev/null || true

aws events put-targets \
    --rule "$RULE_NAME" \
    --targets "Id=onedrive-poll-lambda,Arn=$LAMBDA_ARN" \
    --region "$REGION" > /dev/null
echo "  ✓ Schedule: every 30 minutes"
echo ""

# ── Step 5: CloudWatch alarm ─────────────────────────────────────────────────
echo "Step 5: Creating alarm..."
echo "─────────────────────────"

aws cloudwatch put-metric-alarm \
    --alarm-name "onedrive-poll-errors" \
    --alarm-description "OneDrive poll Lambda errors > 0 in 24h" \
    --metric-name Errors \
    --namespace AWS/Lambda \
    --statistic Sum \
    --period 86400 \
    --threshold 1 \
    --comparison-operator GreaterThanOrEqualToThreshold \
    --evaluation-periods 1 \
    --dimensions "Name=FunctionName,Value=$FUNCTION_NAME" \
    --alarm-actions "$SNS_TOPIC_ARN" \
    --treat-missing-data notBreaching \
    --region "$REGION"
echo "  ✓ Alarm: onedrive-poll-errors → SNS"
echo ""

# ── Step 6: Test ──────────────────────────────────────────────────────────────
echo "Step 6: Test invocation..."
echo "──────────────────────────"

read -p "  Run a test poll now? (y/N): " TEST
if [[ "$TEST" == "y" || "$TEST" == "Y" ]]; then
    aws lambda invoke \
        --function-name "$FUNCTION_NAME" \
        --payload '{}' \
        --region "$REGION" \
        /tmp/onedrive_poll_test.json > /dev/null
    echo "  Response:"
    python3 -m json.tool /tmp/onedrive_poll_test.json
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✓ OneDrive Poll Lambda deployed!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Lambda:    $FUNCTION_NAME"
echo "  Schedule:  Every 30 minutes"
echo "  Folder:    OneDrive:/life-platform/"
echo "  Pipeline:  OneDrive → Lambda → S3 → macrofactor-data-ingestion → DynamoDB"
echo ""
echo "  New flow (phone only):"
echo "    MacroFactor → Export → Share to OneDrive → Save to /life-platform/"
echo "    That's it. Lambda picks it up within 30 minutes."
echo ""
echo "  You can safely disable the launchd agent:"
echo "    launchctl unload ~/Library/LaunchAgents/com.matthewwalker.macrofactor-drop.plist"
echo ""
