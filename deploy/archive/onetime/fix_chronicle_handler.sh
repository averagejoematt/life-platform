#!/bin/bash
# fix_chronicle_handler.sh — CHRON-3 fix
# The wednesday-chronicle Lambda has handler=lambda_function.lambda_handler
# but the actual file is wednesday_chronicle_lambda.py.
# This updates the handler config in AWS, then redeploys the code.
#
# Usage: bash deploy/fix_chronicle_handler.sh

set -euo pipefail

FUNCTION="wednesday-chronicle"
REGION="us-west-2"
SOURCE="lambdas/wednesday_chronicle_lambda.py"

echo "=== CHRON-3: Fix Chronicle Lambda Handler ==="

# Step 1: Check current handler config
echo ""
echo "[1/4] Checking current handler config..."
CURRENT=$(aws lambda get-function-configuration \
  --function-name "$FUNCTION" \
  --region "$REGION" \
  --query 'Handler' \
  --output text 2>/dev/null || echo "NOT_FOUND")

echo "  Current handler: $CURRENT"

if [ "$CURRENT" = "wednesday_chronicle_lambda.lambda_handler" ]; then
  echo "  ✅ Handler already correct!"
else
  echo "  ❌ Handler is wrong — updating..."
  aws lambda update-function-configuration \
    --function-name "$FUNCTION" \
    --handler "wednesday_chronicle_lambda.lambda_handler" \
    --region "$REGION" \
    --no-cli-pager
  echo "  ✅ Handler updated to wednesday_chronicle_lambda.lambda_handler"
  echo "  Waiting 10s for config to propagate..."
  sleep 10
fi

# Step 2: Redeploy the Lambda code
echo ""
echo "[2/4] Deploying Lambda code..."
bash deploy/deploy_lambda.sh "$FUNCTION" "$SOURCE"

# Step 3: Also fix chronicle-approve and chronicle-email-sender if needed
echo ""
echo "[3/4] Checking related Lambdas..."

for FN_PAIR in "chronicle-approve:chronicle_approve_lambda" "chronicle-email-sender:chronicle_email_sender_lambda"; do
  FN="${FN_PAIR%%:*}"
  HANDLER_BASE="${FN_PAIR##*:}"
  EXPECTED="${HANDLER_BASE}.lambda_handler"
  
  CUR=$(aws lambda get-function-configuration \
    --function-name "$FN" \
    --region "$REGION" \
    --query 'Handler' \
    --output text 2>/dev/null || echo "NOT_FOUND")
  
  echo "  $FN: handler=$CUR"
  if [ "$CUR" != "$EXPECTED" ] && [ "$CUR" != "NOT_FOUND" ]; then
    echo "    → Updating to $EXPECTED"
    aws lambda update-function-configuration \
      --function-name "$FN" \
      --handler "$EXPECTED" \
      --region "$REGION" \
      --no-cli-pager
    sleep 5
  else
    echo "    ✅ OK"
  fi
done

# Step 4: Check EventBridge rule
echo ""
echo "[4/4] Checking EventBridge schedule rule..."
aws events list-rules \
  --name-prefix "wednesday-chronicle" \
  --region "$REGION" \
  --query 'Rules[].{Name:Name,State:State,Schedule:ScheduleExpression}' \
  --output table 2>/dev/null || echo "  No EventBridge rule found with prefix 'wednesday-chronicle'"

# Also check for any life-platform rules
aws events list-rules \
  --region "$REGION" \
  --query 'Rules[?contains(Name, `chronicle`)].{Name:Name,State:State,Schedule:ScheduleExpression}' \
  --output table 2>/dev/null || echo "  No EventBridge rules with 'chronicle' in name"

echo ""
echo "=== CHRON-3 Fix Complete ==="
echo "Next steps:"
echo "  1. Verify EventBridge rule is ENABLED and targeting wednesday-chronicle"
echo "  2. Test manually: aws lambda invoke --function-name wednesday-chronicle --payload '{}' --region us-west-2 /tmp/chronicle-test.json --no-cli-pager"
echo "  3. Check CloudWatch: aws logs tail /aws/lambda/wednesday-chronicle --since 5m --region us-west-2"
echo "  4. If PREVIEW_MODE=true, you'll get a preview email — click Approve to publish"
