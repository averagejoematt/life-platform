#!/bin/bash
# ============================================================
#  CloudWatch Alarms — email/digest Lambda error monitoring
#  Creates Errors alarms for: daily-brief, weekly-digest,
#  monthly-digest, anomaly-detector
# ============================================================

set -e

SNS_ARN="arn:aws:sns:us-west-2:205930651321:life-platform-alerts"
REGION="us-west-2"

FUNCTIONS=(
  "daily-brief"
  "weekly-digest"
  "monthly-digest"
  "anomaly-detector"
)

echo ""
echo "Creating CloudWatch Errors alarms..."
echo "SNS topic: $SNS_ARN"
echo ""

for FN in "${FUNCTIONS[@]}"; do
  ALARM_NAME="life-platform-${FN}-errors"

  aws cloudwatch put-metric-alarm \
    --alarm-name        "$ALARM_NAME" \
    --alarm-description "Errors in ${FN} Lambda — investigate immediately" \
    --namespace         "AWS/Lambda" \
    --metric-name       "Errors" \
    --dimensions        Name=FunctionName,Value="$FN" \
    --statistic         "Sum" \
    --period            300 \
    --evaluation-periods 1 \
    --threshold         1 \
    --comparison-operator "GreaterThanOrEqualToThreshold" \
    --treat-missing-data "notBreaching" \
    --alarm-actions     "$SNS_ARN" \
    --ok-actions        "$SNS_ARN" \
    --region            "$REGION"

  echo "  ✓ $ALARM_NAME"
done

echo ""
echo "Done. Verifying alarms..."
echo ""

aws cloudwatch describe-alarms \
  --alarm-name-prefix "life-platform-" \
  --query "MetricAlarms[].{Name:AlarmName,State:StateValue,Threshold:Threshold}" \
  --output table \
  --region "$REGION"
