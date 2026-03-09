#!/bin/bash
# Deploy Dashboard Refresh Lambda — intraday data updater
# Runs at 2 PM and 6 PM PT (currently PST = UTC-8)
# NOTE: After DST (March 8), crons need updating to PDT (UTC-7)
set -euo pipefail

LAMBDA_NAME="dashboard-refresh"
REGION="us-west-2"
ZIP_FILE="/tmp/dashboard_refresh.zip"
SRC_DIR="$HOME/Documents/Claude/life-platform/lambdas"

# Auto-detect role from existing Lambda
ROLE_ARN=$(aws lambda get-function-configuration \
    --function-name life-platform-mcp \
    --region "$REGION" \
    --output text --query 'Role' 2>/dev/null || echo "")
if [[ -z "$ROLE_ARN" ]]; then
    echo "ERROR: Could not detect IAM role. Set ROLE_ARN manually."
    exit 1
fi
echo "Using role: $ROLE_ARN"

echo "=== Deploying Dashboard Refresh Lambda ==="

# 1. Package
echo "[1/5] Packaging Lambda..."
cd "$SRC_DIR"
cp dashboard_refresh_lambda.py lambda_function.py
zip -j "$ZIP_FILE" lambda_function.py
rm lambda_function.py

# 2. Check if Lambda exists
echo "[2/5] Creating/updating Lambda..."
if aws lambda get-function --function-name "$LAMBDA_NAME" &>/dev/null; then
    echo "  Lambda exists — updating code..."
    aws lambda update-function-code \
        --function-name "$LAMBDA_NAME" \
        --zip-file "fileb://$ZIP_FILE" \
        --query 'LastModified' --output text
else
    echo "  Creating new Lambda..."
    aws lambda create-function \
        --function-name "$LAMBDA_NAME" \
        --runtime python3.12 \
        --handler lambda_function.lambda_handler \
        --role "$ROLE_ARN" \
        --zip-file "fileb://$ZIP_FILE" \
        --timeout 60 \
        --memory-size 256 \
        --environment "Variables={TABLE_NAME=life-platform,S3_BUCKET=matthew-life-platform,USER_ID=matthew}" \
        --query 'FunctionArn' --output text
fi

# Wait for Lambda to be active
echo "  Waiting for Lambda to be active..."
aws lambda wait function-active --function-name "$LAMBDA_NAME" 2>/dev/null || sleep 5

# 3. EventBridge: 2 PM PT (22:00 UTC during PST)
echo "[3/5] Creating EventBridge rule: 2 PM PT..."
aws events put-rule \
    --name "dashboard-refresh-afternoon" \
    --schedule-expression "cron(0 22 * * ? *)" \
    --state ENABLED \
    --description "Dashboard refresh — 2 PM PT (22:00 UTC / PST)" \
    --region "$REGION" \
    --query 'RuleArn' --output text

LAMBDA_ARN=$(aws lambda get-function --function-name "$LAMBDA_NAME" --query 'Configuration.FunctionArn' --output text)

aws events put-targets \
    --rule "dashboard-refresh-afternoon" \
    --targets "Id=dashboard-refresh-afternoon,Arn=$LAMBDA_ARN"

# Add permission for EventBridge to invoke Lambda (ignore if exists)
aws lambda add-permission \
    --function-name "$LAMBDA_NAME" \
    --statement-id "allow-eventbridge-afternoon" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "$(aws events describe-rule --name dashboard-refresh-afternoon --query 'Arn' --output text)" \
    2>/dev/null || true

# 4. EventBridge: 6 PM PT (02:00 UTC+1 during PST)
echo "[4/5] Creating EventBridge rule: 6 PM PT..."
aws events put-rule \
    --name "dashboard-refresh-evening" \
    --schedule-expression "cron(0 2 * * ? *)" \
    --state ENABLED \
    --description "Dashboard refresh — 6 PM PT (02:00 UTC / PST)" \
    --region "$REGION" \
    --query 'RuleArn' --output text

aws events put-targets \
    --rule "dashboard-refresh-evening" \
    --targets "Id=dashboard-refresh-evening,Arn=$LAMBDA_ARN"

aws lambda add-permission \
    --function-name "$LAMBDA_NAME" \
    --statement-id "allow-eventbridge-evening" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "$(aws events describe-rule --name dashboard-refresh-evening --query 'Arn' --output text)" \
    2>/dev/null || true

# 5. Summary
echo ""
echo "[5/5] Done!"
echo ""
echo "=== Dashboard Refresh Lambda deployed ==="
echo ""
echo "Schedule (PST — update for PDT after March 8):"
echo "  10:00 AM — Daily Brief writes data.json (existing)"
echo "   2:00 PM — Dashboard refresh (lightweight, no AI)"
echo "   6:00 PM — Dashboard refresh (lightweight, no AI)"
echo ""
echo "What it refreshes:"
echo "  Dashboard: weight, glucose, zone2, TSB, source count"
echo "  Buddy: all 4 signals (food, exercise, routine, weight)"
echo ""
echo "What it preserves from morning:"
echo "  Day grade, TL;DR, BoD insight, character sheet, readiness"
echo ""
echo "Cost impact: ~\$0.01/month (2 extra Lambda runs/day)"
echo ""
echo "Lambda:  $LAMBDA_NAME"
echo "Rules:   dashboard-refresh-afternoon (22:00 UTC)"
echo "         dashboard-refresh-evening (02:00 UTC)"
echo ""
echo "⚠️  DST NOTE: After March 8, update these crons to:"
echo "    afternoon: cron(0 21 * * ? *)  (2 PM PDT = 21:00 UTC)"
echo "    evening:   cron(0 1 * * ? *)   (6 PM PDT = 01:00 UTC)"
