#!/bin/bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════════════════
# Habitify Integration — Full Setup
#
# Runs everything in order:
#   1. Test API key
#   2. Patch MCP server
#   3. Deploy Lambda + infrastructure
#   4. (Optional) Deploy updated MCP server
#
# Usage: bash setup_habitify.sh
# ══════════════════════════════════════════════════════════════════════════════

cd ~/Documents/Claude/life-platform

echo "═══════════════════════════════════════════════════"
echo "  Habitify Integration — Full Setup"
echo "═══════════════════════════════════════════════════"
echo ""

# ── Get API key ──────────────────────────────────────────────────────────────
read -sp "Enter your Habitify API key: " API_KEY
echo ""
API_KEY=$(echo "$API_KEY" | tr -d '\n\r ')
echo ""

# ── Step 1: Test API ─────────────────────────────────────────────────────────
echo "Step 1: Testing Habitify API..."
echo "───────────────────────────────"
python3 test_habitify_api.py "$API_KEY"

echo ""
read -p "Does the output above look correct? (y/N): " CONFIRM
if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
    echo "Aborting. Fix any issues and re-run."
    exit 1
fi

# ── Step 2: Patch MCP server ─────────────────────────────────────────────────
echo ""
echo "Step 2: Patching MCP server..."
echo "──────────────────────────────"
bash patch_mcp_habitify.sh

# ── Step 3: Deploy Habitify Lambda ───────────────────────────────────────────
echo ""
echo "Step 3: Deploying Habitify Lambda..."
echo "────────────────────────────────────"

# Export API_KEY so deploy_habitify.sh can use it non-interactively
export HABITIFY_API_KEY="$API_KEY"

# Run deploy but feed the API key automatically
# We'll inline the deployment steps here to avoid the interactive prompt

REGION="us-west-2"
ACCOUNT_ID="205930651321"
FUNCTION_NAME="habitify-data-ingestion"
ROLE_NAME="lambda-habitify-ingestion-role"
SECRET_NAME="life-platform/habitify"
SNS_TOPIC_ARN="arn:aws:sns:${REGION}:${ACCOUNT_ID}:life-platform-alerts"
RULE_NAME="habitify-daily-ingest"
TABLE_NAME="life-platform"

# Secret
echo "  Creating secret..."
if aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$REGION" 2>/dev/null; then
    aws secretsmanager update-secret \
        --secret-id "$SECRET_NAME" \
        --secret-string "{\"api_key\": \"$API_KEY\"}" \
        --region "$REGION" > /dev/null
    echo "  ✓ Secret updated"
else
    aws secretsmanager create-secret \
        --name "$SECRET_NAME" \
        --description "Habitify API key for P40 habit tracking" \
        --secret-string "{\"api_key\": \"$API_KEY\"}" \
        --region "$REGION" > /dev/null
    echo "  ✓ Secret created"
fi

# IAM Role
echo "  Creating IAM role..."
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
        --policy-document "$POLICY" > /dev/null
    echo "  ✓ Role + policy created"
    echo "  Waiting 10s for IAM propagation..."
    sleep 10
fi

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

# Package Lambda
echo "  Packaging Lambda..."
ZIP_FILE="habitify_lambda.zip"
rm -f "$ZIP_FILE"
zip -q "$ZIP_FILE" habitify_lambda.py
echo "  ✓ Packaged: $ZIP_FILE"

# Create/Update Lambda
echo "  Deploying Lambda..."
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
        --handler habitify_lambda.lambda_handler \
        --role "$ROLE_ARN" \
        --zip-file "fileb://$ZIP_FILE" \
        --timeout 60 \
        --memory-size 128 \
        --environment "Variables={TABLE_NAME=$TABLE_NAME,HABITIFY_SECRET_NAME=$SECRET_NAME}" \
        --region "$REGION" > /dev/null
    aws lambda wait function-active --function-name "$FUNCTION_NAME" --region "$REGION"
    echo "  ✓ Lambda created"
fi

# EventBridge
echo "  Setting up schedule..."
aws events put-rule \
    --name "$RULE_NAME" \
    --schedule-expression "cron(15 14 * * ? *)" \
    --state ENABLED \
    --description "Habitify daily habit ingestion (6:15 AM PT)" \
    --region "$REGION" > /dev/null

LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"

aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "habitify-eventbridge" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "arn:aws:events:${REGION}:${ACCOUNT_ID}:rule/${RULE_NAME}" \
    --region "$REGION" 2>/dev/null || true

aws events put-targets \
    --rule "$RULE_NAME" \
    --targets "Id=habitify-lambda,Arn=$LAMBDA_ARN" \
    --region "$REGION" > /dev/null
echo "  ✓ Schedule: 6:15 AM PT daily"

# CloudWatch Alarm
echo "  Creating alarm..."
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

# Update SOT
echo "  Updating source-of-truth..."
aws dynamodb update-item \
    --table-name "$TABLE_NAME" \
    --key '{"pk": {"S": "USER#matthew"}, "sk": {"S": "PROFILE#v1"}}' \
    --update-expression "SET source_of_truth.habits = :h" \
    --expression-attribute-values '{":h": {"S": "habitify"}}' \
    --region "$REGION"
echo "  ✓ source_of_truth.habits = 'habitify'"

# ── Step 4: Test invocation ──────────────────────────────────────────────────
echo ""
echo "Step 4: Test invocation"
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
python3 -m json.tool /tmp/habitify_test.json
echo ""

# ── Step 5: Deploy MCP? ─────────────────────────────────────────────────────
echo ""
read -p "Deploy updated MCP server now? (y/N): " DEPLOY_MCP
if [[ "$DEPLOY_MCP" == "y" || "$DEPLOY_MCP" == "Y" ]]; then
    echo ""
    echo "Step 5: Deploying MCP server..."
    echo "───────────────────────────────"
    bash deploy_mcp.sh
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✓ Habitify integration complete!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Lambda:     habitify-data-ingestion"
echo "  Schedule:   6:15 AM PT daily (fetches yesterday)"
echo "  Secret:     life-platform/habitify"
echo "  SOT:        habits → habitify"
echo ""
echo "  Verify in DynamoDB:"
echo "    pk = USER#matthew#SOURCE#habitify"
echo "    sk = DATE#$TODAY"
echo ""
echo "  Remaining docs to update:"
echo "    - SCHEMA.md"
echo "    - ARCHITECTURE.md"
echo "    - CHANGELOG.md"
echo ""
