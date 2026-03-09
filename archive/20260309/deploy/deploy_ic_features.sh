#!/bin/bash
# deploy_ic_features.sh — Deploy IC-2, IC-3, IC-6 intelligence features
#
# IC-2: daily-insight-compute Lambda (new) + EventBridge at 9:42 AM PT
# IC-3: chain-of-thought analysis pass (ai_calls.py changes in daily-brief)
# IC-6: milestone architecture (ai_calls.py changes in daily-brief)
#
# Order:
#   1. Create daily-insight-compute Lambda (if new) and deploy code
#   2. Create EventBridge rule at 9:42 AM PT (17:42 UTC)
#   3. Deploy daily-brief (ai_calls.py + daily_brief_lambda.py changes)

set -euo pipefail

REGION="us-west-2"
ACCOUNT="205930651321"
ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/lambda-mcp-server-role"

echo "🧠 Deploying IC-2 / IC-3 / IC-6 Intelligence Features"
echo "======================================================="

# ── Step 1: Create or update daily-insight-compute Lambda ──
echo ""
echo "📦 Step 1: daily-insight-compute Lambda"

INSIGHT_FUNCTION="daily-insight-compute"
INSIGHT_SOURCE="lambdas/daily_insight_compute_lambda.py"

if [ ! -f "$INSIGHT_SOURCE" ]; then
    echo "❌ Source not found: $INSIGHT_SOURCE"
    exit 1
fi

# Check if Lambda exists
LAMBDA_EXISTS=$(aws lambda get-function --function-name "$INSIGHT_FUNCTION" --region "$REGION" \
    --query 'Configuration.FunctionName' --output text --no-cli-pager 2>/dev/null || echo "NOT_FOUND")

WORK_DIR=$(mktemp -d)
cp "$INSIGHT_SOURCE" "$WORK_DIR/lambda_function.py"
(cd "$WORK_DIR" && zip -q deploy.zip lambda_function.py)

if [ "$LAMBDA_EXISTS" == "NOT_FOUND" ]; then
    echo "   Creating new Lambda: $INSIGHT_FUNCTION"
    aws lambda create-function \
        --function-name "$INSIGHT_FUNCTION" \
        --runtime python3.12 \
        --role "$ROLE_ARN" \
        --handler lambda_function.lambda_handler \
        --zip-file "fileb://$WORK_DIR/deploy.zip" \
        --timeout 120 \
        --memory-size 512 \
        --environment "Variables={TABLE_NAME=life-platform,USER_ID=matthew,S3_BUCKET=matthew-life-platform}" \
        --description "IC-2: Pre-compute curated coaching intelligence for Daily Brief AI calls" \
        --region "$REGION" \
        --no-cli-pager > /dev/null
    echo "   ✅ Created $INSIGHT_FUNCTION"
    sleep 5  # Wait for Lambda to be active
else
    echo "   Updating existing Lambda: $INSIGHT_FUNCTION"
    aws lambda update-function-code \
        --function-name "$INSIGHT_FUNCTION" \
        --zip-file "fileb://$WORK_DIR/deploy.zip" \
        --region "$REGION" \
        --no-cli-pager > /dev/null
    echo "   ✅ Updated $INSIGHT_FUNCTION"
fi
rm -rf "$WORK_DIR"

# ── Step 2: EventBridge rule at 9:42 AM PT (17:42 UTC) ──
echo ""
echo "⏰ Step 2: EventBridge rule — 9:42 AM PT daily"

RULE_NAME="daily-insight-compute"
SCHEDULE="cron(42 17 * * ? *)"

RULE_EXISTS=$(aws events list-rules --name-prefix "$RULE_NAME" --region "$REGION" \
    --query 'Rules[0].Name' --output text --no-cli-pager 2>/dev/null || echo "None")

if [ "$RULE_EXISTS" == "$RULE_NAME" ]; then
    echo "   EventBridge rule already exists — updating schedule"
    aws events put-rule \
        --name "$RULE_NAME" \
        --schedule-expression "$SCHEDULE" \
        --state ENABLED \
        --description "Daily insight pre-computation at 9:42 AM PT (between metrics-compute and daily-brief)" \
        --region "$REGION" \
        --no-cli-pager > /dev/null
else
    echo "   Creating EventBridge rule"
    aws events put-rule \
        --name "$RULE_NAME" \
        --schedule-expression "$SCHEDULE" \
        --state ENABLED \
        --description "Daily insight pre-computation at 9:42 AM PT (between metrics-compute and daily-brief)" \
        --region "$REGION" \
        --no-cli-pager > /dev/null
fi

# Add Lambda as target
LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT}:function:${INSIGHT_FUNCTION}"
aws events put-targets \
    --rule "$RULE_NAME" \
    --targets "Id=1,Arn=$LAMBDA_ARN" \
    --region "$REGION" \
    --no-cli-pager > /dev/null

# Grant EventBridge permission to invoke the Lambda
aws lambda add-permission \
    --function-name "$INSIGHT_FUNCTION" \
    --statement-id "EventBridgeInvoke-$RULE_NAME" \
    --action lambda:InvokeFunction \
    --principal events.amazonaws.com \
    --source-arn "arn:aws:events:${REGION}:${ACCOUNT}:rule/${RULE_NAME}" \
    --region "$REGION" \
    --no-cli-pager > /dev/null 2>&1 || echo "   (permission already exists — ok)"

echo "   ✅ EventBridge rule: $SCHEDULE → $INSIGHT_FUNCTION"

# ── Step 3: Deploy daily-brief (IC-3 + IC-6 in ai_calls.py) ──
echo ""
echo "📧 Step 3: daily-brief (IC-3 chain-of-thought + IC-6 milestones in ai_calls.py)"
sleep 10  # Wait between Lambda deploys

bash deploy/deploy_lambda.sh daily-brief lambdas/daily_brief_lambda.py \
    --extra-files lambdas/ai_calls.py lambdas/html_builder.py \
    lambdas/output_writers.py lambdas/board_loader.py lambdas/scoring_engine.py

echo ""
echo "======================================================="
echo "✅ All done. Verify:"
echo ""
echo "1. Smoke test IC-2 (run insight Lambda for today's data):"
echo "   aws lambda invoke --function-name daily-insight-compute \\"
echo "     --payload '{\"date\":\"$(date -u -v-1d '+%Y-%m-%d' 2>/dev/null || date -u -d 'yesterday' '+%Y-%m-%d')\",\"force\":true}' \\"
echo "     /tmp/insight_out.json --region us-west-2 && cat /tmp/insight_out.json"
echo ""
echo "2. Check CloudWatch for daily-brief ImportError (none expected):"
echo "   aws logs describe-log-streams --log-group-name /aws/lambda/daily-brief \\"
echo "     --order-by LastEventTime --descending --limit 1 --region us-west-2"
echo ""
echo "3. EventBridge schedule: 9:42 AM PT daily (17:42 UTC) = 2 min after daily-metrics-compute"
echo ""
echo "4. Tomorrow's brief will include IC-2 context, IC-3 analysis pass, and IC-6 milestones."
