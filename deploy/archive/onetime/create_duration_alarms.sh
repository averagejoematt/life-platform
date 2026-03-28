#!/bin/bash
# deploy/create_duration_alarms.sh
# R13-F08-dur: p95 duration alarms on Daily Brief and MCP Lambda.
#
# Timeout-without-error is currently undetected: if a Lambda runs for 290s
# of its 300s limit and succeeds, no alarm fires. These alarms catch silent
# degradation before it becomes a timeout.
#
# Alarm logic:
#   - Fires when p95 duration exceeds threshold for 3 consecutive 5-min periods
#   - 3 datapoints to reduce noise from one-off slow cold starts
#   - All alarms notify life-platform-alerts SNS topic
#
# Thresholds (informed by observed p50 durations):
#   daily-brief:       p95 > 240,000 ms (4 min, hard limit 300s)
#   life-platform-mcp: p95 > 25,000 ms  (25s, hard limit 300s, soft timeout 30s)
#
# Usage: bash deploy/create_duration_alarms.sh
# Requires: AWS CLI, credentials for account 205930651321

set -euo pipefail

REGION="us-west-2"
ACCOUNT="205930651321"
SNS_ARN="arn:aws:sns:${REGION}:${ACCOUNT}:life-platform-alerts"

echo "=== R13-F08-dur: Creating duration alarms ==="
echo ""

# ── daily-brief duration alarm ───────────────────────────────────────────────
echo "Creating p95 duration alarm for daily-brief..."
aws cloudwatch put-metric-alarm \
  --alarm-name "life-platform-daily-brief-duration-p95" \
  --alarm-description "R13-F08-dur: daily-brief p95 duration >240s. Silent degradation risk — hard limit is 300s." \
  --namespace "AWS/Lambda" \
  --metric-name "Duration" \
  --dimensions Name=FunctionName,Value=daily-brief \
  --statistic p95 \
  --extended-statistic p95 \
  --period 300 \
  --evaluation-periods 3 \
  --datapoints-to-alarm 3 \
  --threshold 240000 \
  --comparison-operator GreaterThanThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "${SNS_ARN}" \
  --region "${REGION}" 2>/dev/null || \
aws cloudwatch put-metric-alarm \
  --alarm-name "life-platform-daily-brief-duration-p95" \
  --alarm-description "R13-F08-dur: daily-brief p95 duration >240s. Silent degradation risk — hard limit is 300s." \
  --namespace "AWS/Lambda" \
  --metric-name "Duration" \
  --dimensions Name=FunctionName,Value=daily-brief \
  --extended-statistic p95 \
  --period 300 \
  --evaluation-periods 3 \
  --datapoints-to-alarm 3 \
  --threshold 240000 \
  --comparison-operator GreaterThanThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "${SNS_ARN}" \
  --region "${REGION}"
echo "  ✅ daily-brief duration alarm created"

# ── life-platform-mcp duration alarm ────────────────────────────────────────
echo "Creating p95 duration alarm for life-platform-mcp..."
aws cloudwatch put-metric-alarm \
  --alarm-name "life-platform-mcp-duration-p95" \
  --alarm-description "R13-F08-dur: MCP Lambda p95 duration >25s. Soft timeout is 30s — sustained elevation means tools are timing out." \
  --namespace "AWS/Lambda" \
  --metric-name "Duration" \
  --dimensions Name=FunctionName,Value=life-platform-mcp \
  --extended-statistic p95 \
  --period 300 \
  --evaluation-periods 3 \
  --datapoints-to-alarm 3 \
  --threshold 25000 \
  --comparison-operator GreaterThanThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "${SNS_ARN}" \
  --region "${REGION}"
echo "  ✅ life-platform-mcp duration alarm created"

echo ""
echo "=== Verifying alarms ==="
aws cloudwatch describe-alarms \
  --alarm-names \
    "life-platform-daily-brief-duration-p95" \
    "life-platform-mcp-duration-p95" \
  --region "${REGION}" \
  --query "MetricAlarms[*].{Name:AlarmName,State:StateValue,Threshold:Threshold}" \
  --output table

echo ""
echo "✅ R13-F08-dur complete. Both duration alarms active."
echo "   daily-brief: fires if p95 >240,000ms for 3 consecutive 5-min windows"
echo "   mcp:         fires if p95 >25,000ms for 3 consecutive 5-min windows"
