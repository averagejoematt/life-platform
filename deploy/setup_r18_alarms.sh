#!/bin/bash
set -euo pipefail

# R18-F04: Add CloudWatch alarms for Lambdas created during the v3.7.82→v4.3.0 sprint
# that don't have alarms yet.

REGION="us-west-2"
SNS_ARN="arn:aws:sns:us-west-2:205930651321:life-platform-alerts"

NEW_LAMBDAS=(
  "og-image-generator"
  "food-delivery-ingestion"
  "challenge-generator"
  "email-subscriber"
)

for LAMBDA in "${NEW_LAMBDAS[@]}"; do
  if ! aws lambda get-function --function-name "$LAMBDA" --region "$REGION" --no-cli-pager > /dev/null 2>&1; then
    echo "⚠️  Lambda $LAMBDA not found in $REGION — skipping"
    continue
  fi

  ALARM_NAME="${LAMBDA}-errors"

  if aws cloudwatch describe-alarms --alarm-names "$ALARM_NAME" --region "$REGION" --query 'MetricAlarms[0].AlarmName' --output text 2>/dev/null | grep -q "$ALARM_NAME"; then
    echo "✓ Alarm $ALARM_NAME already exists — skipping"
    continue
  fi

  echo "Creating alarm: $ALARM_NAME"
  aws cloudwatch put-metric-alarm \
    --alarm-name "$ALARM_NAME" \
    --alarm-description "R18-F04: Error alarm for $LAMBDA" \
    --metric-name Errors \
    --namespace AWS/Lambda \
    --dimensions Name=FunctionName,Value="$LAMBDA" \
    --statistic Sum \
    --period 86400 \
    --evaluation-periods 1 \
    --threshold 1 \
    --comparison-operator GreaterThanOrEqualToThreshold \
    --alarm-actions "$SNS_ARN" \
    --treat-missing-data notBreaching \
    --region "$REGION" \
    --no-cli-pager

  echo "  ✓ Created $ALARM_NAME"
done

echo ""
echo "Done."
