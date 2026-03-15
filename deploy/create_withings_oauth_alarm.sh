#!/usr/bin/env bash
# deploy/create_withings_oauth_alarm.sh
#
# R18 / R55: Withings OAuth consecutive-failure alarm
#
# Creates a CloudWatch alarm that fires if withings-data-ingestion errors
# for 2 consecutive days. Distinct from the generic freshness alert — this
# fires when the Lambda itself errors (typically OAuth token expiry), giving
# an early warning before data goes stale.
#
# Why 2 consecutive days?
#   - One failure is recoverable (transient API blip, network issue)
#   - Two consecutive errors = likely OAuth token expired (Withings rotates
#     every ~24h; if Lambda is down, refresh cycle breaks)
#   - TreatMissingData=notBreaching: days with no invocation won't trigger
#     (prevents false alarms during scheduled outages / maintenance mode)
#
# Run once:
#   bash deploy/create_withings_oauth_alarm.sh
#
# To delete:
#   aws cloudwatch delete-alarms --alarm-names withings-oauth-consecutive-errors --region us-west-2
#
set -euo pipefail

REGION="us-west-2"
FUNCTION_NAME="withings-data-ingestion"
ALARM_NAME="withings-oauth-consecutive-errors"
SNS_ARN="arn:aws:sns:us-west-2:205930651321:life-platform-alerts"

echo "Creating CloudWatch alarm: ${ALARM_NAME}"
echo "  Function : ${FUNCTION_NAME}"
echo "  Threshold: ≥1 error for 2 consecutive days"
echo "  Action   : SNS → awsdev@mattsusername.com"
echo ""

aws cloudwatch put-metric-alarm \
  --region "${REGION}" \
  --alarm-name "${ALARM_NAME}" \
  --alarm-description \
    "Withings Lambda errored for 2 consecutive days. Likely OAuth token expiry — re-auth with setup/fix_withings_oauth.py." \
  --namespace "AWS/Lambda" \
  --metric-name "Errors" \
  --dimensions "Name=FunctionName,Value=${FUNCTION_NAME}" \
  --statistic "Sum" \
  --period 86400 \
  --evaluation-periods 2 \
  --datapoints-to-alarm 2 \
  --threshold 1 \
  --comparison-operator "GreaterThanOrEqualToThreshold" \
  --treat-missing-data "notBreaching" \
  --alarm-actions "${SNS_ARN}"

echo ""
echo "✅  Alarm '${ALARM_NAME}' created successfully."
echo ""
echo "Verify in console:"
echo "  https://us-west-2.console.aws.amazon.com/cloudwatch/home?region=us-west-2#alarmsV2:alarm/${ALARM_NAME}"
echo ""
echo "Note: alarm requires 2 full evaluation periods (days) before it can fire."
echo "      It will enter INSUFFICIENT_DATA today — this is expected."
