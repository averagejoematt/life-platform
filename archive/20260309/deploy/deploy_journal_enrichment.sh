#!/bin/bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════════════════
# Notion Journal Phase 2 — Haiku Enrichment Deploy
#
# 1. Patch Notion DB with 4 new expert panel fields
# 2. Update notion ingestion Lambda (new field extraction)
# 3. Deploy journal enrichment Lambda (Haiku-powered)
# 4. EventBridge schedule: 6:30 AM PT (after Notion ingestion at 6:00 AM)
# 5. CloudWatch alarm
#
# Prerequisites:
#   - Phase 1 deployed (setup_notion.sh completed)
#   - Anthropic API key in Secrets Manager (life-platform/anthropic)
#
# Usage: bash deploy_journal_enrichment.sh
# ══════════════════════════════════════════════════════════════════════════════

cd ~/Documents/Claude/life-platform

echo "═══════════════════════════════════════════════════"
echo "  Journal Enrichment (Phase 2) — Deploy"
echo "═══════════════════════════════════════════════════"
echo ""

REGION="us-west-2"
ACCOUNT_ID="205930651321"
TABLE_NAME="life-platform"
SNS_TOPIC_ARN="arn:aws:sns:${REGION}:${ACCOUNT_ID}:life-platform-alerts"

# ── Step 1: Patch Notion DB ──────────────────────────────────────────────────
echo "Step 1: Patching Notion DB with Phase 2 fields..."
echo "──────────────────────────────────────────────────"

# Get Notion creds from Secrets Manager
NOTION_SECRET=$(aws secretsmanager get-secret-value \
    --secret-id "life-platform/notion" \
    --region "$REGION" \
    --query 'SecretString' --output text)

NOTION_KEY=$(echo "$NOTION_SECRET" | python3 -c "import sys,json; print(json.load(sys.stdin)['api_key'])")
NOTION_DB=$(echo "$NOTION_SECRET" | python3 -c "import sys,json; print(json.load(sys.stdin)['database_id'])")

python3 patch_notion_db_phase2.py "$NOTION_KEY" "$NOTION_DB"
echo ""

# ── Step 2: Update Notion ingestion Lambda ───────────────────────────────────
echo "Step 2: Updating Notion ingestion Lambda..."
echo "────────────────────────────────────────────"

NOTION_ZIP="notion_lambda.zip"
rm -f "$NOTION_ZIP"
zip -q "$NOTION_ZIP" notion_lambda.py

aws lambda update-function-code \
    --function-name "notion-journal-ingestion" \
    --zip-file "fileb://$NOTION_ZIP" \
    --region "$REGION" > /dev/null
aws lambda wait function-updated \
    --function-name "notion-journal-ingestion" \
    --region "$REGION"
echo "  ✓ notion-journal-ingestion updated"
echo ""

# ── Step 3: Check Anthropic API key ──────────────────────────────────────────
echo "Step 3: Verifying Anthropic API key..."
echo "──────────────────────────────────────"

if aws secretsmanager describe-secret --secret-id "life-platform/anthropic" --region "$REGION" 2>/dev/null; then
    echo "  ✓ Secret exists: life-platform/anthropic"
else
    echo "  ⚠ Secret not found: life-platform/anthropic"
    read -sp "  Enter your Anthropic API key: " ANTHROPIC_KEY
    echo ""
    aws secretsmanager create-secret \
        --name "life-platform/anthropic" \
        --description "Anthropic API key for journal enrichment (Haiku)" \
        --secret-string "{\"api_key\": \"$ANTHROPIC_KEY\"}" \
        --region "$REGION" > /dev/null
    echo "  ✓ Secret created"
fi
echo ""

# ── Step 4: IAM Role ─────────────────────────────────────────────────────────
echo "Step 4: Creating IAM role..."
echo "────────────────────────────"

ENRICH_FUNCTION="journal-enrichment"
ENRICH_ROLE="lambda-journal-enrichment-role"

TRUST_POLICY='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

if aws iam get-role --role-name "$ENRICH_ROLE" 2>/dev/null; then
    echo "  ✓ Role already exists"
else
    aws iam create-role \
        --role-name "$ENRICH_ROLE" \
        --assume-role-policy-document "$TRUST_POLICY" > /dev/null

    POLICY='{
      "Version": "2012-10-17",
      "Statement": [
        {
          "Effect": "Allow",
          "Action": ["dynamodb:Query", "dynamodb:UpdateItem", "dynamodb:GetItem"],
          "Resource": "arn:aws:dynamodb:'$REGION':'$ACCOUNT_ID':table/'$TABLE_NAME'"
        },
        {
          "Effect": "Allow",
          "Action": ["secretsmanager:GetSecretValue"],
          "Resource": [
            "arn:aws:secretsmanager:'$REGION':'$ACCOUNT_ID':secret:life-platform/anthropic-*"
          ]
        },
        {
          "Effect": "Allow",
          "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
          "Resource": "arn:aws:logs:'$REGION':'$ACCOUNT_ID':log-group:/aws/lambda/'$ENRICH_FUNCTION':*"
        }
      ]
    }'
    aws iam put-role-policy \
        --role-name "$ENRICH_ROLE" \
        --policy-name "journal-enrichment-policy" \
        --policy-document "$POLICY" > /dev/null
    echo "  ✓ Role + policy created"
    echo "  Waiting 10s for IAM propagation..."
    sleep 10
fi
echo ""

# ── Step 5: Deploy Enrichment Lambda ─────────────────────────────────────────
echo "Step 5: Deploying enrichment Lambda..."
echo "──────────────────────────────────────"

ENRICH_ZIP="journal_enrichment_lambda.zip"
rm -f "$ENRICH_ZIP"
zip -q "$ENRICH_ZIP" journal_enrichment_lambda.py

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ENRICH_ROLE}"

if aws lambda get-function --function-name "$ENRICH_FUNCTION" --region "$REGION" 2>/dev/null; then
    aws lambda update-function-code \
        --function-name "$ENRICH_FUNCTION" \
        --zip-file "fileb://$ENRICH_ZIP" \
        --region "$REGION" > /dev/null
    aws lambda wait function-updated --function-name "$ENRICH_FUNCTION" --region "$REGION"
    echo "  ✓ Lambda updated"
else
    aws lambda create-function \
        --function-name "$ENRICH_FUNCTION" \
        --runtime python3.12 \
        --handler journal_enrichment_lambda.lambda_handler \
        --role "$ROLE_ARN" \
        --zip-file "fileb://$ENRICH_ZIP" \
        --timeout 300 \
        --memory-size 128 \
        --environment "Variables={TABLE_NAME=$TABLE_NAME,ANTHROPIC_SECRET=life-platform/anthropic}" \
        --region "$REGION" > /dev/null
    aws lambda wait function-active --function-name "$ENRICH_FUNCTION" --region "$REGION"
    echo "  ✓ Lambda created"
fi
echo ""

# ── Step 6: EventBridge schedule ──────────────────────────────────────────────
echo "Step 6: Setting up schedule..."
echo "──────────────────────────────"

RULE_NAME="journal-enrichment-daily"

# 6:30 AM PT = 14:30 UTC
aws events put-rule \
    --name "$RULE_NAME" \
    --schedule-expression "cron(30 14 * * ? *)" \
    --state ENABLED \
    --description "Journal enrichment via Haiku (6:30 AM PT, after Notion ingestion)" \
    --region "$REGION" > /dev/null

LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${ENRICH_FUNCTION}"

aws lambda add-permission \
    --function-name "$ENRICH_FUNCTION" \
    --statement-id "journal-enrichment-eventbridge" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "arn:aws:events:${REGION}:${ACCOUNT_ID}:rule/${RULE_NAME}" \
    --region "$REGION" 2>/dev/null || true

aws events put-targets \
    --rule "$RULE_NAME" \
    --targets "Id=journal-enrichment-lambda,Arn=$LAMBDA_ARN" \
    --region "$REGION" > /dev/null
echo "  ✓ Schedule: 6:30 AM PT daily"
echo ""

# ── Step 7: CloudWatch alarm ─────────────────────────────────────────────────
echo "Step 7: Creating alarm..."
echo "─────────────────────────"

aws cloudwatch put-metric-alarm \
    --alarm-name "journal-enrichment-errors" \
    --alarm-description "Journal enrichment Lambda errors > 0 in 24h" \
    --metric-name Errors \
    --namespace AWS/Lambda \
    --statistic Sum \
    --period 86400 \
    --threshold 1 \
    --comparison-operator GreaterThanOrEqualToThreshold \
    --evaluation-periods 1 \
    --dimensions "Name=FunctionName,Value=$ENRICH_FUNCTION" \
    --alarm-actions "$SNS_TOPIC_ARN" \
    --treat-missing-data notBreaching \
    --region "$REGION"
echo "  ✓ Alarm: journal-enrichment-errors → SNS"
echo ""

# ── Step 8: Test ──────────────────────────────────────────────────────────────
echo "Step 8: Test invocation..."
echo "──────────────────────────"
echo "  Note: This will only enrich entries that exist in DynamoDB."
echo "  If no journal entries yet, create one in Notion and run:"
echo "    aws lambda invoke --function-name notion-journal-ingestion \\"
echo "      --payload '{\"full_sync\": true}' --cli-binary-format raw-in-base64-out \\"
echo "      --region $REGION /tmp/notion_sync.json"
echo ""

read -p "  Run test enrichment now? (y/N): " TEST
if [[ "$TEST" == "y" || "$TEST" == "Y" ]]; then
    aws lambda invoke \
        --function-name "$ENRICH_FUNCTION" \
        --payload '{"full_sync": true, "force": true}' \
        --cli-binary-format raw-in-base64-out \
        --region "$REGION" \
        /tmp/enrichment_test.json > /dev/null

    echo "  Response:"
    python3 -m json.tool /tmp/enrichment_test.json
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✓ Journal Enrichment (Phase 2) deployed!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Notion DB:    4 new fields added (Gratitude, Social Connection, Deep Work Hours, One Thing I'm Avoiding)"
echo "  Ingestion:    notion-journal-ingestion updated (extracts new fields)"
echo "  Enrichment:   $ENRICH_FUNCTION (Haiku-powered)"
echo "  Schedule:     6:30 AM PT daily (30 min after Notion ingestion)"
echo "  Model:        claude-haiku-4-5-20251001"
echo ""
echo "  Pipeline: Notion DB → notion-journal-ingestion (6:00 AM) → journal-enrichment (6:30 AM) → daily-brief (8:15 AM)"
echo ""
echo "  Enriched fields: mood, energy, stress, sentiment, emotions, themes,"
echo "    cognitive_patterns, growth_signals, avoidance_flags, ownership,"
echo "    social_quality, flow, values_lived, gratitude, alcohol_mention,"
echo "    sleep_context, pain_mentions, exercise_context, notable_quote"
echo ""
echo "  Next: Phase 3 (MCP tools) → Phase 4 (daily brief integration)"
echo ""
