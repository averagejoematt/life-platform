#!/bin/bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════════════════
# Deploy Habitify ingestion Lambda + infrastructure
#
# Creates:
#   - Secrets Manager secret (life-platform/habitify)
#   - IAM role (lambda-habitify-ingestion-role)
#   - Lambda function (habitify-data-ingestion)
#   - EventBridge rule (habitify-daily-ingest) at 6:15 AM PT
#   - CloudWatch alarm → life-platform-alerts SNS
#   - Updates DynamoDB profile source_of_truth: habits → habitify
#
# Prerequisites:
#   - AWS CLI configured
#   - Habitify API key (prompted below)
#
# Run from: ~/Documents/Claude/life-platform/
# ══════════════════════════════════════════════════════════════════════════════

REGION="us-west-2"
ACCOUNT_ID="205930651321"
FUNCTION_NAME="habitify-data-ingestion"
ROLE_NAME="lambda-habitify-ingestion-role"
SECRET_NAME="life-platform/habitify"
SNS_TOPIC_ARN="arn:aws:sns:${REGION}:${ACCOUNT_ID}:life-platform-alerts"
RULE_NAME="habitify-daily-ingest"
TABLE_NAME="life-platform"

cd ~/Documents/Claude/life-platform

echo "═══════════════════════════════════════════════════"
echo "  Habitify Integration Deployment"
echo "═══════════════════════════════════════════════════"

# ── Step 1: Secrets Manager ──────────────────────────────────────────────────
echo ""
echo "Step 1: Secrets Manager"
echo "───────────────────────"

# Check if secret already exists
if aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$REGION" 2>/dev/null; then
    echo "  Secret '$SECRET_NAME' already exists."
    read -p "  Update the API key? (y/N): " UPDATE_KEY
    if [[ "$UPDATE_KEY" == "y" || "$UPDATE_KEY" == "Y" ]]; then
        read -sp "  Enter your Habitify API key: " API_KEY
        echo ""
        aws secretsmanager update-secret \
            --secret-id "$SECRET_NAME" \
            --secret-string "{\"api_key\": \"$API_KEY\"}" \
            --region "$REGION"
        echo "  ✓ Secret updated"
    fi
else
    read -sp "  Enter your Habitify API key: " API_KEY
    echo ""
    aws secretsmanager create-secret \
        --name "$SECRET_NAME" \
        --description "Habitify API key for P40 habit tracking" \
        --secret-string "{\"api_key\": \"$API_KEY\"}" \
        --region "$REGION"
    echo "  ✓ Secret created: $SECRET_NAME"
fi

# ── Step 2: IAM Role ────────────────────────────────────────────────────────
echo ""
echo "Step 2: IAM Role"
echo "────────────────"

TRUST_POLICY='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}'

if aws iam get-role --role-name "$ROLE_NAME" --region "$REGION" 2>/dev/null; then
    echo "  Role '$ROLE_NAME' already exists — skipping creation"
else
    aws iam create-role \
        --role-name "$ROLE_NAME" \
        --assume-role-policy-document "$TRUST_POLICY" \
        --region "$REGION"
    echo "  ✓ Role created: $ROLE_NAME"

    # Inline policy: DynamoDB + Secrets Manager + CloudWatch Logs
    POLICY='{
      "Version": "2012-10-17",
      "Statement": [
        {
          "Effect": "Allow",
          "Action": ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query", "dynamodb:UpdateItem"],
          "Resource": "arn:aws:dynamodb:'$REGION':'$ACCOUNT_ID':table/'$TABLE_NAME'"
        },
        {
          "Effect": "Allow",
          "Action": ["secretsmanager:GetSecretValue"],
          "Resource": "arn:aws:secretsmanager:'$REGION':'$ACCOUNT_ID':secret:life-platform/habitify-*"
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
        --policy-name "habitify-ingestion-policy" \
        --policy-document "$POLICY" \
        --region "$REGION"
    echo "  ✓ Policy attached"

    echo "  Waiting 10s for IAM propagation..."
    sleep 10
fi

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

# ── Step 3: Package Lambda ───────────────────────────────────────────────────
echo ""
echo "Step 3: Package Lambda"
echo "──────────────────────"

# No external dependencies — just boto3 (included in Lambda runtime)
ZIP_FILE="habitify_lambda.zip"
rm -f "$ZIP_FILE"
zip "$ZIP_FILE" habitify_lambda.py
echo "  ✓ Packaged: $ZIP_FILE ($(du -h $ZIP_FILE | cut -f1))"

# ── Step 4: Create/Update Lambda ─────────────────────────────────────────────
echo ""
echo "Step 4: Lambda Function"
echo "───────────────────────"

if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" 2>/dev/null; then
    echo "  Updating existing function..."
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file "fileb://$ZIP_FILE" \
        --region "$REGION" > /dev/null
    aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
    echo "  ✓ Lambda code updated"
else
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.12 \
        --handler habitify_lambda.lambda_handler \
        --role "$ROLE_ARN" \
        --zip-file "fileb://$ZIP_FILE" \
        --timeout 60 \
        --memory-size 128 \
        --environment "Variables={TABLE_NAME=$TABLE_NAME,HABITIFY_SECRET_NAME=$SECRET_NAME}" \
        --region "$REGION" > /dev/null
    aws lambda wait function-active --function-name "$FUNCTION_NAME" --region "$REGION"
    echo "  ✓ Lambda created: $FUNCTION_NAME"
fi

# ── Step 5: EventBridge Schedule ─────────────────────────────────────────────
echo ""
echo "Step 5: EventBridge Schedule"
echo "────────────────────────────"

# 6:15 AM PT = 14:15 UTC (standard time) / 13:15 UTC (daylight)
# Using 14:15 UTC — runs before daily brief at 8:15am PT
aws events put-rule \
    --name "$RULE_NAME" \
    --schedule-expression "cron(15 14 * * ? *)" \
    --state ENABLED \
    --description "Habitify daily habit ingestion (6:15 AM PT)" \
    --region "$REGION" > /dev/null

LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"

# Add permission for EventBridge to invoke Lambda
aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "habitify-eventbridge" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "arn:aws:events:${REGION}:${ACCOUNT_ID}:rule/${RULE_NAME}" \
    --region "$REGION" 2>/dev/null || true  # ignore if already exists

aws events put-targets \
    --rule "$RULE_NAME" \
    --targets "Id=habitify-lambda,Arn=$LAMBDA_ARN" \
    --region "$REGION" > /dev/null

echo "  ✓ Schedule: 6:15 AM PT daily (cron 15 14 * * ? *)"

# ── Step 6: CloudWatch Alarm ─────────────────────────────────────────────────
echo ""
echo "Step 6: CloudWatch Alarm"
echo "────────────────────────"

aws cloudwatch put-metric-alarm \
    --alarm-name "habitify-ingestion-errors" \
    --alarm-description "Habitify Lambda errors > 0 in 24h" \
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

echo "  ✓ Alarm: habitify-ingestion-errors → SNS"

# ── Step 7: Update source-of-truth ───────────────────────────────────────────
echo ""
echo "Step 7: Update source-of-truth"
echo "──────────────────────────────"

aws dynamodb update-item \
    --table-name "$TABLE_NAME" \
    --key '{"pk": {"S": "USER#matthew"}, "sk": {"S": "PROFILE#v1"}}' \
    --update-expression "SET source_of_truth.habits = :h" \
    --expression-attribute-values '{":h": {"S": "habitify"}}' \
    --region "$REGION"

echo "  ✓ source_of_truth.habits = 'habitify'"

# ── Step 8: Test invocation ──────────────────────────────────────────────────
echo ""
echo "Step 8: Test invocation"
echo "───────────────────────"

TODAY=$(date +%Y-%m-%d)
echo "  Invoking for today ($TODAY)..."

aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --payload "{\"date\": \"$TODAY\"}" \
    --cli-binary-format raw-in-base64-out \
    --region "$REGION" \
    /tmp/habitify_test.json > /dev/null

echo "  Response:"
cat /tmp/habitify_test.json | python3 -m json.tool
echo ""

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✓ Habitify integration deployed!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Lambda:     $FUNCTION_NAME"
echo "  Schedule:   6:15 AM PT daily"
echo "  Secret:     $SECRET_NAME"
echo "  IAM Role:   $ROLE_NAME"
echo "  Alarm:      habitify-ingestion-errors"
echo "  SOT:        habits → habitify"
echo ""
echo "  Next steps:"
echo "    1. Verify test output above shows your habits"
echo "    2. Check DynamoDB: pk=USER#matthew#SOURCE#habitify, sk=DATE#$TODAY"
echo "    3. Update MCP server if habit tools are hardcoded to 'chronicling'"
echo "    4. Update SCHEMA.md, ARCHITECTURE.md, CHANGELOG.md"
echo ""
echo "  Manual test:"
echo "    aws lambda invoke --function-name $FUNCTION_NAME \\"
echo "      --payload '{\"date\": \"2026-02-23\"}' \\"
echo "      --cli-binary-format raw-in-base64-out \\"
echo "      --region $REGION /tmp/test.json && cat /tmp/test.json"
echo ""
