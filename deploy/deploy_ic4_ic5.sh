#!/usr/bin/env bash
# deploy_ic4_ic5.sh — Deploy IC-4 (failure-pattern-compute) + IC-5 (daily-insight-compute v1.2.0)
# Run from project root: bash deploy/deploy_ic4_ic5.sh
set -euo pipefail

REGION="us-west-2"
ACCOUNT="205930651321"
LAMBDAS_DIR="lambdas"

echo "=== Deploying IC-4: failure-pattern-compute (new Lambda) ==="

# --- IC-4: Create zip ---
TMP=$(mktemp -d)
cp "$LAMBDAS_DIR/failure_pattern_compute_lambda.py" "$TMP/"
cp "$LAMBDAS_DIR/platform_logger.py" "$TMP/"
cd "$TMP"
zip -q failure_pattern_compute.zip failure_pattern_compute_lambda.py platform_logger.py
cd -

# Check if Lambda exists
if aws lambda get-function --function-name failure-pattern-compute --region "$REGION" &>/dev/null; then
  echo "Updating existing failure-pattern-compute..."
  aws lambda update-function-code \
    --function-name failure-pattern-compute \
    --zip-file "fileb://$TMP/failure_pattern_compute.zip" \
    --region "$REGION"
else
  echo "Creating failure-pattern-compute Lambda..."
  ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/life-platform-lambda-role"
  aws lambda create-function \
    --function-name failure-pattern-compute \
    --runtime python3.12 \
    --role "$ROLE_ARN" \
    --handler failure_pattern_compute_lambda.lambda_handler \
    --zip-file "fileb://$TMP/failure_pattern_compute.zip" \
    --timeout 300 \
    --memory-size 256 \
    --environment "Variables={USER_ID=matthew,TABLE_NAME=life-platform,ANTHROPIC_SECRET=life-platform/ai-keys,AI_MODEL_HAIKU=claude-haiku-4-5-20251001}" \
    --region "$REGION"

  echo "Waiting for function to be active..."
  aws lambda wait function-active \
    --function-name failure-pattern-compute \
    --region "$REGION"

  # EventBridge rule: Sunday 9:50 AM PT = 17:50 UTC
  echo "Creating EventBridge rule for Sunday 9:50 AM PT..."
  aws events put-rule \
    --name "failure-pattern-compute-weekly" \
    --schedule-expression "cron(50 17 ? * SUN *)" \
    --state ENABLED \
    --region "$REGION"

  LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT}:function:failure-pattern-compute"
  aws events put-targets \
    --rule "failure-pattern-compute-weekly" \
    --targets "Id=failure-pattern-compute,Arn=$LAMBDA_ARN" \
    --region "$REGION"

  aws lambda add-permission \
    --function-name failure-pattern-compute \
    --statement-id "AllowEventBridgeWeekly" \
    --action lambda:InvokeFunction \
    --principal events.amazonaws.com \
    --source-arn "arn:aws:events:${REGION}:${ACCOUNT}:rule/failure-pattern-compute-weekly" \
    --region "$REGION"

  echo "EventBridge rule created: failure-pattern-compute-weekly (cron 50 17 ? * SUN *)"
fi

rm -rf "$TMP"
echo "✅ IC-4 failure-pattern-compute deployed"

echo ""
echo "=== Deploying IC-5: daily-insight-compute v1.2.0 ==="
sleep 10  # avoid ResourceConflictException if both are being updated

bash deploy/deploy_lambda.sh daily-insight-compute

echo ""
echo "=== All done ==="
echo "Verify IC-4 with a test invoke:"
echo "  aws lambda invoke --function-name failure-pattern-compute --payload '{\"force\":true}' /tmp/ic4_out.json --region us-west-2 && cat /tmp/ic4_out.json"
echo ""
echo "Verify IC-5 with a test invoke:"
echo "  aws lambda invoke --function-name daily-insight-compute --payload '{}' /tmp/ic5_out.json --region us-west-2 && cat /tmp/ic5_out.json"
