#!/bin/bash
# Deploy v2.79.0 — Partner Weekly Email
#
# New Lambda: partner-weekly-email
# Schedule:   Sunday 9:30 AM PT (17:30 UTC) — after Matthew's 8:30 AM weekly digest
# Board:      Full panel consulted; Rodriguez, Conti, Murthy weighted for partner context
#
# Tool count: 124 (unchanged — no new MCP tools)

set -euo pipefail
cd ~/Documents/Claude/life-platform
chmod +x deploy/deploy_lambda.sh 2>/dev/null || true

REGION="us-west-2"
ACCOUNT="205930651321"
ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/lambda-weekly-digest-role"
FUNCTION_NAME="partner-weekly-email"

echo "=== v2.79.0 Deploy: Partner Weekly Email ==="
echo ""

# ── 1. Check if Lambda exists ─────────────────────────────────────────────────
echo "[1/4] Checking if Lambda exists..."
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" --no-cli-pager > /dev/null 2>&1; then
  LAMBDA_EXISTS=true
  echo "  Lambda already exists — updating code"
else
  LAMBDA_EXISTS=false
  echo "  Lambda does not exist — will create"
fi

# ── 2. Package + deploy ───────────────────────────────────────────────────────
echo "[2/4] Packaging and deploying Lambda..."
if [ "$LAMBDA_EXISTS" = true ]; then
  bash deploy/deploy_lambda.sh "$FUNCTION_NAME" lambdas/partner_email_lambda.py
else
  # New Lambda — package manually (handler must be lambda_function.py)
  cp lambdas/partner_email_lambda.py /tmp/lambda_function.py
  cd /tmp && zip -j partner_email.zip lambda_function.py && cd - > /dev/null
  aws lambda create-function \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.12 \
    --role "$ROLE_ARN" \
    --handler lambda_function.lambda_handler \
    --zip-file fileb:///tmp/partner_email.zip \
    --timeout 90 \
    --memory-size 256 \
    --region "$REGION" \
    --environment "Variables={
      TABLE_NAME=life-platform,
      EMAIL_SENDER=awsdev@mattsusername.com,
      PARTNER_EMAIL=REPLACE_WITH_PARTNER_EMAIL,
      ANTHROPIC_SECRET=life-platform/api-keys
    }" \
    --description "Weekly partner update email for Partner — full Board of Directors consultation" \
    --no-cli-pager \
    --query "FunctionArn" --output text
  echo "  ✅ Lambda created"
  aws lambda wait function-active --function-name "$FUNCTION_NAME" --region "$REGION"
fi
echo "  ✅ Partner email Lambda deployed"

sleep 10

# ── 3. EventBridge rule — Sunday 9:30 AM PT = 17:30 UTC ──────────────────────
echo "[3/4] Setting up EventBridge schedule..."

# Check if rule already exists
if aws events describe-rule --name "partner-weekly-email-schedule" --region "$REGION" --no-cli-pager > /dev/null 2>&1; then
  echo "  EventBridge rule already exists — skipping"
else
  aws events put-rule \
    --name "partner-weekly-email-schedule" \
    --schedule-expression "cron(30 17 ? * 1 *)" \
    --state ENABLED \
    --description "Partner weekly email — Sunday 9:30 AM PT" \
    --region "$REGION" \
    --no-cli-pager \
    --query "RuleArn" --output text

  LAMBDA_ARN=$(aws lambda get-function \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" --no-cli-pager \
    --query "Configuration.FunctionArn" --output text)

  aws events put-targets \
    --rule "partner-weekly-email-schedule" \
    --targets "Id=partner-email-target,Arn=$LAMBDA_ARN" \
    --region "$REGION" \
    --no-cli-pager > /dev/null

  aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "allow-eventbridge-partner-weekly" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "arn:aws:events:$REGION:$ACCOUNT:rule/partner-weekly-email-schedule" \
    --region "$REGION" \
    --no-cli-pager > /dev/null

  echo "  ✅ EventBridge rule created: Sunday 9:30 AM PT"
fi

# ── 4. Set his partner's email address ──────────────────────────────────────────
echo "[4/4] ⚠  MANUAL STEP REQUIRED"
echo ""
echo "  Set his partner's email address in the Lambda env vars:"
echo ""
echo "  aws lambda update-function-configuration \\"
echo "    --function-name $FUNCTION_NAME \\"
echo "    --environment 'Variables={TABLE_NAME=life-platform,EMAIL_SENDER=awsdev@mattsusername.com,PARTNER_EMAIL=YOUR_EMAIL_HERE,ANTHROPIC_SECRET=life-platform/api-keys}' \\"
echo "    --region $REGION \\"
echo "    --no-cli-pager"
echo ""

echo "=== v2.79.0 Deploy Complete ==="
echo ""
echo "  New Lambda:    partner-weekly-email"
echo "  Schedule:      Sunday 9:30 AM PT (after Matthew's 8:30 AM digest)"
echo "  Board panel:   Full (Rodriguez/Conti/Murthy elevated)"
echo "  Model:         Sonnet 4.6"
echo "  Recipient:     PARTNER_EMAIL env var (set manually above)"
echo ""
echo "  Test invoke:"
echo "    aws lambda invoke \\"
echo "      --function-name $FUNCTION_NAME \\"
echo "      --payload '{}' \\"
echo "      --cli-binary-format raw-in-base64-out \\"
echo "      --region $REGION \\"
echo "      /tmp/partner_out.json && cat /tmp/partner_out.json"
