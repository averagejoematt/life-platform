#!/usr/bin/env bash
# REL-1: Compute failure signals
#
# Creates CloudWatch alarm on daily-metrics-compute errors.
# When the compute Lambda errors, SNS fires → you get an email alert
# *before* the Daily Brief runs on stale data.
#
# Also checks that html_builder.py stale-compute banner is wired (it is —
# daily_brief_lambda.py passes compute_stale=True when data is >4h old).
# This script adds the *proactive* signal: alarm fires at 9:45 AM if
# daily-metrics-compute failed at 9:40 AM, giving 15 min warning.
#
# Run from: ~/Documents/Claude/life-platform/
# Usage:    bash deploy/rel1_compute_alarm.sh

set -euo pipefail

REGION="us-west-2"
ACCOUNT="205930651321"
SNS_TOPIC_ARN="arn:aws:sns:${REGION}:${ACCOUNT}:life-platform-alerts"
ALERT_EMAIL="awsdev@mattsusername.com"

echo "=== REL-1: Compute failure signals ==="
echo ""

# ──────────────────────────────────────────────────────────────────────────────
# 1. Ensure SNS topic exists (may already exist from prior hardening)
# ──────────────────────────────────────────────────────────────────────────────
echo "Step 1: Verifying SNS topic life-platform-alerts..."
EXISTING_TOPIC=$(aws sns list-topics \
  --region "${REGION}" \
  --query "Topics[?ends_with(TopicArn, ':life-platform-alerts')].TopicArn" \
  --output text \
  --no-cli-pager 2>/dev/null || echo "")

if [ -z "${EXISTING_TOPIC}" ]; then
  echo "  Creating SNS topic..."
  aws sns create-topic \
    --name "life-platform-alerts" \
    --region "${REGION}" \
    --no-cli-pager
  echo "  ✓ Created life-platform-alerts"

  echo "  Subscribing ${ALERT_EMAIL}..."
  aws sns subscribe \
    --topic-arn "${SNS_TOPIC_ARN}" \
    --protocol email \
    --notification-endpoint "${ALERT_EMAIL}" \
    --region "${REGION}" \
    --no-cli-pager
  echo "  ✓ Subscription created — check email to confirm"
else
  echo "  ✓ SNS topic exists: ${EXISTING_TOPIC}"
fi

# ──────────────────────────────────────────────────────────────────────────────
# 2. Create CloudWatch alarm: daily-metrics-compute errors
#    Fires if any error occurs in the 5-min window around execution (9:40 AM PT)
# ──────────────────────────────────────────────────────────────────────────────
echo ""
echo "Step 2: Creating CloudWatch alarm for daily-metrics-compute errors..."

aws cloudwatch put-metric-alarm \
  --alarm-name "life-platform-daily-metrics-compute-errors" \
  --alarm-description "REL-1: daily-metrics-compute Lambda errored. Daily Brief will use stale data at 10 AM. Check CloudWatch logs immediately." \
  --metric-name "Errors" \
  --namespace "AWS/Lambda" \
  --dimensions Name=FunctionName,Value=daily-metrics-compute \
  --statistic Sum \
  --period 300 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --evaluation-periods 1 \
  --treat-missing-data notBreaching \
  --alarm-actions "${SNS_TOPIC_ARN}" \
  --ok-actions "${SNS_TOPIC_ARN}" \
  --region "${REGION}" \
  --no-cli-pager

echo "  ✓ Alarm: life-platform-daily-metrics-compute-errors"

# ──────────────────────────────────────────────────────────────────────────────
# 3. Create alarm: daily-metrics-compute not-invoked (missed execution)
#    Fires if the Lambda wasn't invoked in 26 hours (covers midnight to 10 AM)
# ──────────────────────────────────────────────────────────────────────────────
echo ""
echo "Step 3: Creating alarm for daily-metrics-compute missed execution..."

aws cloudwatch put-metric-alarm \
  --alarm-name "life-platform-daily-metrics-compute-missed" \
  --alarm-description "REL-1: daily-metrics-compute not invoked in 26 hours. EventBridge schedule may have failed. Daily Brief data is stale." \
  --metric-name "Invocations" \
  --namespace "AWS/Lambda" \
  --dimensions Name=FunctionName,Value=daily-metrics-compute \
  --statistic Sum \
  --period 93600 \
  --threshold 1 \
  --comparison-operator LessThanThreshold \
  --evaluation-periods 1 \
  --treat-missing-data breaching \
  --alarm-actions "${SNS_TOPIC_ARN}" \
  --region "${REGION}" \
  --no-cli-pager

echo "  ✓ Alarm: life-platform-daily-metrics-compute-missed"

# ──────────────────────────────────────────────────────────────────────────────
# 4. Create alarm: daily-insight-compute errors (IC-2/IC-8)
# ──────────────────────────────────────────────────────────────────────────────
echo ""
echo "Step 4: Creating alarm for daily-insight-compute errors..."

aws cloudwatch put-metric-alarm \
  --alarm-name "life-platform-daily-insight-compute-errors" \
  --alarm-description "REL-1: daily-insight-compute Lambda errored. AI context block will be degraded in Daily Brief." \
  --metric-name "Errors" \
  --namespace "AWS/Lambda" \
  --dimensions Name=FunctionName,Value=daily-insight-compute \
  --statistic Sum \
  --period 300 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --evaluation-periods 1 \
  --treat-missing-data notBreaching \
  --alarm-actions "${SNS_TOPIC_ARN}" \
  --region "${REGION}" \
  --no-cli-pager

echo "  ✓ Alarm: life-platform-daily-insight-compute-errors"

# ──────────────────────────════════════════════════════════════════════════════
# 5. Create alarm: character-sheet-compute errors
#    Character sheet is read by Daily Brief at 10 AM — if it failed at 9:35 AM,
#    brief falls back to cached data without a visible signal today
# ──────────────────────────────────────────────────────────────────────────────
echo ""
echo "Step 5: Creating alarm for character-sheet-compute errors..."

aws cloudwatch put-metric-alarm \
  --alarm-name "life-platform-character-sheet-compute-errors" \
  --alarm-description "REL-1: character-sheet-compute Lambda errored. Character Sheet section in Daily Brief will use stale/missing data." \
  --metric-name "Errors" \
  --namespace "AWS/Lambda" \
  --dimensions Name=FunctionName,Value=character-sheet-compute \
  --statistic Sum \
  --period 300 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --evaluation-periods 1 \
  --treat-missing-data notBreaching \
  --alarm-actions "${SNS_TOPIC_ARN}" \
  --region "${REGION}" \
  --no-cli-pager

echo "  ✓ Alarm: life-platform-character-sheet-compute-errors"

# ──────────────────────────────────────────────────────────────────────────────
# 6. Verify all alarms exist
# ──────────────────────────────────────────────────────────────────────────────
echo ""
echo "Step 6: Verifying alarms..."

for ALARM_NAME in \
  "life-platform-daily-metrics-compute-errors" \
  "life-platform-daily-metrics-compute-missed" \
  "life-platform-daily-insight-compute-errors" \
  "life-platform-character-sheet-compute-errors"; do
  STATE=$(aws cloudwatch describe-alarms \
    --alarm-names "${ALARM_NAME}" \
    --query "MetricAlarms[0].StateValue" \
    --output text \
    --region "${REGION}" \
    --no-cli-pager 2>/dev/null || echo "NOT FOUND")
  echo "  ${ALARM_NAME}: ${STATE}"
done

# ──────────────────────────────────────────────────────────────────────────────
# 7. Summary: REL-1 status
# ──────────────────────────────────────────────────────────────────────────────
echo ""
echo "=== REL-1 complete ==="
echo ""
echo "Compute failure signal chain:"
echo "  9:35 AM  character-sheet-compute errors → SNS alarm within 5 min"
echo "  9:40 AM  daily-metrics-compute errors   → SNS alarm within 5 min"
echo "  9:42 AM  daily-insight-compute errors   → SNS alarm within 5 min"
echo "  10:00 AM daily-brief: if compute_stale=True, email includes:"
echo "           ⚠️ 'Compute data <age> — some metrics may be estimated'"
echo "           (html_builder.py line 1106 — already wired)"
echo ""
echo "Both signals active:"
echo "  1. Email banner in Daily Brief (html_builder stale check — existing)"
echo "  2. SNS alert within 5 min of compute failure (new — this script)"
echo ""
echo "CloudWatch alarm total is now ~39 (was 35 before this script)"
echo ""
echo "If SNS subscription email wasn't confirmed yet:"
echo "  aws sns list-subscriptions-by-topic --topic-arn ${SNS_TOPIC_ARN} --region ${REGION}"
