#!/bin/bash
# deploy_monday_compass.sh — Deploy Monday Compass Lambda + EventBridge rule
# Run from project root: ./deploy/deploy_monday_compass.sh

set -euo pipefail

REGION="us-west-2"
ACCOUNT_ID="205930651321"
FUNCTION_NAME="monday-compass"
RULE_NAME="monday-compass"

echo "=== Monday Compass Deploy ==="
echo ""

# ── Step 1: Create Lambda if it doesn't exist ─────────────────────────────────
echo "🔍 Checking if Lambda exists..."
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" \
   --no-cli-pager > /dev/null 2>&1; then
    echo "   Lambda exists — updating code only"
else
    echo "   Lambda not found — creating..."

    ROLE_ARN=$(aws lambda get-function-configuration \
        --function-name "weekly-plate-schedule" \
        --region "$REGION" \
        --query "Role" --output text --no-cli-pager)
    echo "   Using role: $ROLE_ARN"

    echo "placeholder" > /tmp/placeholder.py
    zip -q /tmp/placeholder.zip /tmp/placeholder.py

    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.12 \
        --role "$ROLE_ARN" \
        --handler "monday_compass_lambda.lambda_handler" \
        --zip-file "fileb:///tmp/placeholder.zip" \
        --timeout 120 \
        --memory-size 512 \
        --environment "Variables={TABLE_NAME=life-platform,USER_ID=matthew,S3_BUCKET=matthew-life-platform,EMAIL_RECIPIENT=awsdev@mattsusername.com,EMAIL_SENDER=awsdev@mattsusername.com,SECRET_NAME=life-platform/api-keys}" \
        --region "$REGION" \
        --no-cli-pager > /dev/null
    echo "   ✅ Lambda created"
    sleep 10
fi

# ── Step 2: Deploy code ───────────────────────────────────────────────────────
echo ""
echo "📦 Deploying code..."
./deploy/deploy_lambda.sh "$FUNCTION_NAME" lambdas/monday_compass_lambda.py \
    --extra-files \
        lambdas/board_loader.py \
        lambdas/insight_writer.py

# ── Step 3: Upload S3 config ──────────────────────────────────────────────────
echo ""
echo "📤 Uploading project_pillar_map.json to S3..."
aws s3 cp config/project_pillar_map.json \
    s3://matthew-life-platform/config/project_pillar_map.json \
    --region "$REGION" \
    --no-cli-pager
echo "   ✅ config/project_pillar_map.json uploaded"

# ── Step 4: EventBridge rule — Monday 15:00 UTC = 7:00 AM PT ─────────────────
echo ""
echo "⏰ Configuring EventBridge rule (Monday 7:00 AM PT = 15:00 UTC)..."

RULE_ARN=$(aws events put-rule \
    --name "$RULE_NAME" \
    --schedule-expression "cron(0 15 ? * MON *)" \
    --state ENABLED \
    --description "Monday Compass weekly planning email — Monday 7:00 AM PT" \
    --region "$REGION" \
    --query "RuleArn" --output text --no-cli-pager)
echo "   Rule ARN: $RULE_ARN"

aws events put-targets \
    --rule "$RULE_NAME" \
    --targets "Id=monday-compass-target,Arn=arn:aws:lambda:$REGION:$ACCOUNT_ID:function:$FUNCTION_NAME" \
    --region "$REGION" \
    --no-cli-pager > /dev/null

aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "EventBridgeMondayCompass" \
    --action lambda:InvokeFunction \
    --principal events.amazonaws.com \
    --source-arn "$RULE_ARN" \
    --region "$REGION" \
    --no-cli-pager > /dev/null 2>&1 || echo "   (Permission already exists — skipping)"

echo "   ✅ EventBridge rule configured"

# ── Step 5: CloudWatch alarm ──────────────────────────────────────────────────
echo ""
echo "🔔 Creating CloudWatch alarm..."
aws cloudwatch put-metric-alarm \
    --alarm-name "monday-compass-errors" \
    --alarm-description "Monday Compass Lambda errors" \
    --metric-name Errors \
    --namespace AWS/Lambda \
    --dimensions Name=FunctionName,Value="$FUNCTION_NAME" \
    --statistic Sum \
    --period 3600 \
    --evaluation-periods 1 \
    --threshold 1 \
    --comparison-operator GreaterThanOrEqualToThreshold \
    --treat-missing-data notBreaching \
    --region "$REGION" \
    --no-cli-pager > /dev/null
echo "   ✅ Alarm: monday-compass-errors"

# ── Step 6: Smoke test ────────────────────────────────────────────────────────
echo ""
echo "🧪 Running smoke test (will send real email)..."
aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --payload '{}' \
    --region "$REGION" \
    --no-cli-pager \
    /tmp/compass_test_output.json > /dev/null

STATUS_CODE=$(python3 -c "import json; d=json.load(open('/tmp/compass_test_output.json')); print(d.get('statusCode', 'unknown'))" 2>/dev/null || echo "unknown")
echo "   Response statusCode: $STATUS_CODE"

if [ "$STATUS_CODE" = "200" ]; then
    BODY=$(python3 -c "import json; d=json.load(open('/tmp/compass_test_output.json')); print(d.get('body','{}'))" 2>/dev/null || echo "{}")
    echo "   $BODY"
    echo ""
    echo "✅ Monday Compass deployed successfully!"
else
    echo ""
    echo "⚠️  Non-200 response. Check CloudWatch:"
    echo "   aws logs describe-log-streams --log-group-name /aws/lambda/$FUNCTION_NAME \\"
    echo "     --order-by LastEventTime --descending --limit 1 --region $REGION"
fi

echo ""
echo "=== Summary ==="
echo "  Lambda:     $FUNCTION_NAME"
echo "  Schedule:   Monday 7:00 AM PT (cron(0 15 ? * MON *))"
echo "  S3 config:  s3://matthew-life-platform/config/project_pillar_map.json"
echo "  Alarm:      monday-compass-errors"
echo ""
echo "📝 After deploy:"
echo "  1. Check inbox for the test email"
echo "  2. Edit config/project_pillar_map.json to match your actual Todoist projects"
echo "  3. Re-upload: aws s3 cp config/project_pillar_map.json s3://matthew-life-platform/config/project_pillar_map.json"
