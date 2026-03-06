#!/bin/bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════════════════
# Notion Journal Integration — Full Setup
#
# Runs everything in order:
#   1. Store Notion API key + database ID in Secrets Manager
#   2. Create IAM role
#   3. Deploy Lambda
#   4. Set up EventBridge schedule (6:00 AM PT daily)
#   5. Create CloudWatch alarm
#   6. Update SOT profile
#   7. Test invocation
#   8. (Optional) Deploy updated MCP server
#
# Prerequisites:
#   - Notion internal integration created (Settings → Integrations → New)
#   - Integration connected to the journal database (Share → Invite)
#   - Database ID copied from the Notion URL
#     (https://notion.so/<workspace>/<DATABASE_ID>?v=...)
#
# Usage: bash setup_notion.sh
# ══════════════════════════════════════════════════════════════════════════════

cd ~/Documents/Claude/life-platform

echo "═══════════════════════════════════════════════════"
echo "  Notion Journal Integration — Full Setup"
echo "═══════════════════════════════════════════════════"
echo ""

# ── Collect credentials ──────────────────────────────────────────────────────
read -sp "Enter your Notion Internal Integration API key: " API_KEY
echo ""
API_KEY=$(echo "$API_KEY" | tr -d '\n\r ')

read -p "Enter the Notion Database ID: " DATABASE_ID
# Strip whitespace, hyphens, and any URL components
DATABASE_ID=$(echo "$DATABASE_ID" | tr -d '\n\r ' | sed 's/.*\///' | sed 's/?.*//' | tr -d '-')
# Re-format as UUID
if [[ ${#DATABASE_ID} -eq 32 ]]; then
    DATABASE_ID="${DATABASE_ID:0:8}-${DATABASE_ID:8:4}-${DATABASE_ID:12:4}-${DATABASE_ID:16:4}-${DATABASE_ID:20:12}"
fi
echo ""

# ── Validate inputs ──────────────────────────────────────────────────────────
if [[ -z "$API_KEY" || -z "$DATABASE_ID" ]]; then
    echo "❌ API key and Database ID are both required."
    exit 1
fi

# ── Config ────────────────────────────────────────────────────────────────────
REGION="us-west-2"
ACCOUNT_ID="205930651321"
FUNCTION_NAME="notion-journal-ingestion"
ROLE_NAME="lambda-notion-ingestion-role"
SECRET_NAME="life-platform/notion"
SNS_TOPIC_ARN="arn:aws:sns:${REGION}:${ACCOUNT_ID}:life-platform-alerts"
RULE_NAME="notion-daily-ingest"
TABLE_NAME="life-platform"

# ── Step 1: Test API connection ──────────────────────────────────────────────
echo "Step 1: Testing Notion API..."
echo "─────────────────────────────"

HTTP_CODE=$(curl -s -o /tmp/notion_test.json -w "%{http_code}" \
    -X POST "https://api.notion.com/v1/databases/${DATABASE_ID}/query" \
    -H "Authorization: Bearer ${API_KEY}" \
    -H "Notion-Version: 2022-06-28" \
    -H "Content-Type: application/json" \
    -d '{"page_size": 1}')

if [[ "$HTTP_CODE" == "200" ]]; then
    echo "  ✓ API connection successful (HTTP $HTTP_CODE)"
    RESULT_COUNT=$(python3 -c "import json; d=json.load(open('/tmp/notion_test.json')); print(len(d.get('results',[])))")
    echo "  ✓ Database accessible (${RESULT_COUNT} entries in sample)"
else
    echo "  ❌ API returned HTTP $HTTP_CODE"
    echo "  Response:"
    cat /tmp/notion_test.json
    echo ""
    echo "  Common fixes:"
    echo "    - Verify the integration is connected to the database (Share → Invite)"
    echo "    - Verify the database ID is correct"
    echo "    - Verify the API key is correct"
    exit 1
fi

echo ""
read -p "Proceed with deployment? (y/N): " CONFIRM
if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
    echo "Aborting."
    exit 1
fi

# ── Step 2: Store secret ─────────────────────────────────────────────────────
echo ""
echo "Step 2: Storing credentials..."
echo "──────────────────────────────"

SECRET_VALUE="{\"api_key\": \"${API_KEY}\", \"database_id\": \"${DATABASE_ID}\"}"

if aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$REGION" 2>/dev/null; then
    aws secretsmanager update-secret \
        --secret-id "$SECRET_NAME" \
        --secret-string "$SECRET_VALUE" \
        --region "$REGION" > /dev/null
    echo "  ✓ Secret updated"
else
    aws secretsmanager create-secret \
        --name "$SECRET_NAME" \
        --description "Notion API key + database ID for P40 journal" \
        --secret-string "$SECRET_VALUE" \
        --region "$REGION" > /dev/null
    echo "  ✓ Secret created"
fi

# ── Step 3: IAM Role ─────────────────────────────────────────────────────────
echo ""
echo "Step 3: Creating IAM role..."
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
          "Action": ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query", "dynamodb:UpdateItem"],
          "Resource": "arn:aws:dynamodb:'$REGION':'$ACCOUNT_ID':table/'$TABLE_NAME'"
        },
        {
          "Effect": "Allow",
          "Action": ["secretsmanager:GetSecretValue"],
          "Resource": "arn:aws:secretsmanager:'$REGION':'$ACCOUNT_ID':secret:life-platform/notion-*"
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
        --policy-name "notion-ingestion-policy" \
        --policy-document "$POLICY" > /dev/null
    echo "  ✓ Role + policy created"
    echo "  Waiting 10s for IAM propagation..."
    sleep 10
fi

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

# ── Step 4: Deploy Lambda ────────────────────────────────────────────────────
echo ""
echo "Step 4: Deploying Lambda..."
echo "───────────────────────────"

ZIP_FILE="notion_lambda.zip"
rm -f "$ZIP_FILE"
zip -q "$ZIP_FILE" notion_lambda.py
echo "  ✓ Packaged: $ZIP_FILE"

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
        --handler notion_lambda.lambda_handler \
        --role "$ROLE_ARN" \
        --zip-file "fileb://$ZIP_FILE" \
        --timeout 120 \
        --memory-size 128 \
        --environment "Variables={TABLE_NAME=$TABLE_NAME,NOTION_SECRET_NAME=$SECRET_NAME}" \
        --region "$REGION" > /dev/null
    aws lambda wait function-active --function-name "$FUNCTION_NAME" --region "$REGION"
    echo "  ✓ Lambda created"
fi

# ── Step 5: EventBridge schedule ──────────────────────────────────────────────
echo ""
echo "Step 5: Setting up schedule..."
echo "──────────────────────────────"

# 6:00 AM PT = 14:00 UTC (PST) / 13:00 UTC (PDT)
# Using 14:00 UTC (conservative — runs in the ingestion window)
aws events put-rule \
    --name "$RULE_NAME" \
    --schedule-expression "cron(0 14 * * ? *)" \
    --state ENABLED \
    --description "Notion journal daily ingestion (6:00 AM PT)" \
    --region "$REGION" > /dev/null

LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"

aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "notion-eventbridge" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "arn:aws:events:${REGION}:${ACCOUNT_ID}:rule/${RULE_NAME}" \
    --region "$REGION" 2>/dev/null || true

aws events put-targets \
    --rule "$RULE_NAME" \
    --targets "Id=notion-lambda,Arn=$LAMBDA_ARN" \
    --region "$REGION" > /dev/null
echo "  ✓ Schedule: 6:00 AM PT daily"

# ── Step 6: CloudWatch alarm ─────────────────────────────────────────────────
echo ""
echo "Step 6: Creating alarm..."
echo "─────────────────────────"

aws cloudwatch put-metric-alarm \
    --alarm-name "notion-ingestion-errors" \
    --alarm-description "Notion Lambda errors > 0 in 24h" \
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
echo "  ✓ Alarm: notion-ingestion-errors → SNS"

# ── Step 7: Update SOT ───────────────────────────────────────────────────────
echo ""
echo "Step 7: Updating source-of-truth..."
echo "────────────────────────────────────"

aws dynamodb update-item \
    --table-name "$TABLE_NAME" \
    --key '{"pk": {"S": "USER#matthew"}, "sk": {"S": "PROFILE#v1"}}' \
    --update-expression "SET source_of_truth.journal = :j" \
    --expression-attribute-values '{":j": {"S": "notion"}}' \
    --region "$REGION"
echo "  ✓ source_of_truth.journal = 'notion'"

# ── Step 8: Test invocation ──────────────────────────────────────────────────
echo ""
echo "Step 8: Test invocation (full sync)"
echo "────────────────────────────────────"

echo "  Invoking with full_sync to load any existing entries..."
aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --payload '{"full_sync": true}' \
    --cli-binary-format raw-in-base64-out \
    --region "$REGION" \
    /tmp/notion_test_result.json > /dev/null

echo "  Response:"
python3 -m json.tool /tmp/notion_test_result.json
echo ""

# ── Step 9: Deploy MCP? ──────────────────────────────────────────────────────
echo ""
read -p "Deploy updated MCP server now? (y/N): " DEPLOY_MCP
if [[ "$DEPLOY_MCP" == "y" || "$DEPLOY_MCP" == "Y" ]]; then
    echo ""
    echo "Step 9: Deploying MCP server..."
    echo "───────────────────────────────"
    bash deploy_mcp.sh
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✓ Notion Journal integration complete!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Lambda:     $FUNCTION_NAME"
echo "  Schedule:   6:00 AM PT daily (fetches last 2 days)"
echo "  Secret:     $SECRET_NAME"
echo "  SOT:        journal → notion"
echo ""
echo "  Next steps:"
echo "    1. Start journaling! Open Notion and create your first Morning entry."
echo "    2. The Lambda will pick it up at 6:00 AM tomorrow."
echo "    3. Or invoke manually:"
echo "       aws lambda invoke --function-name $FUNCTION_NAME \\"
echo "         --payload '{\"full_sync\": true}' \\"
echo "         --cli-binary-format raw-in-base64-out \\"
echo "         --region $REGION /tmp/notion_result.json"
echo ""
echo "  Phase 2: Haiku enrichment (mood/energy/stress/themes extraction)"
echo "  Phase 3: MCP tools (get_journal_entries, search_journal, get_mood_trend)"
echo "  Phase 4: Daily brief + weekly digest integration"
echo ""
