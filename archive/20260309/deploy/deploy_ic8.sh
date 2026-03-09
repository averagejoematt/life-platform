#!/bin/bash
# deploy_ic8.sh — Deploy IC-8: Intent vs Execution Gap
# Adds intention tracking to daily-insight-compute Lambda.
# Only one Lambda needs updating — everything else is additive within it.
#
# Usage: bash deploy/deploy_ic8.sh

set -e
LAMBDA="daily-insight-compute"
REGION="us-west-2"

echo "=== IC-8: Intent vs Execution Gap Deploy ==="
echo "Lambda: $LAMBDA"
echo ""

echo "Step 1: Deploying $LAMBDA..."
bash deploy/deploy_lambda.sh $LAMBDA lambdas/daily_insight_compute_lambda.py
echo "Waiting 10s..."
sleep 10

echo ""
echo "Step 2: Smoke test (force=true for yesterday)..."
YESTERDAY=$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d yesterday +%Y-%m-%d)
aws lambda invoke \
  --function-name $LAMBDA \
  --payload '{"force": true}' \
  --cli-binary-format raw-in-base64-out \
  --region $REGION \
  /tmp/ic8_response.json
echo "Response:"
cat /tmp/ic8_response.json | python3 -m json.tool 2>/dev/null || cat /tmp/ic8_response.json
echo ""

echo "Step 3: Check CloudWatch logs for IC-8 lines..."
sleep 5
LOG_STREAM=$(aws logs describe-log-streams \
  --log-group-name /aws/lambda/$LAMBDA \
  --order-by LastEventTime --descending --limit 1 \
  --region $REGION \
  --query 'logStreams[0].logStreamName' --output text)
echo "Log stream: $LOG_STREAM"
aws logs get-log-events \
  --log-group-name /aws/lambda/$LAMBDA \
  --log-stream-name "$LOG_STREAM" \
  --region $REGION \
  --query 'events[*].message' --output text | grep -E "IC-8|ic8|intention|Insight" | head -20

echo ""
echo "=== Deploy complete ==="
echo ""
echo "What to verify:"
echo "  - 'IC-8: Intention gap context: NNN chars' in logs (means journal data found)"
echo "  - OR 'IC-8: No intention data for YYYY-MM-DD -- skipping' (fine — means no journal)"
echo "  - 'ic8_active: true/false' in response"
echo "  - DynamoDB: pk=USER#matthew#SOURCE#platform_memory, sk=MEMORY#intention_tracking#<date>"
echo ""
echo "IC-8 compounds value over time — first 2 weeks: daily evaluation only."
echo "Recurring gap patterns emerge at ~14 days of journal data."
