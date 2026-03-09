#!/bin/bash
# p1_invocation_alarms.sh — P1.7: Add invocation-count alarms for critical Lambdas
#
# PROBLEM: If a Lambda silently stops firing (EventBridge rule disabled, function
#          throttled, etc.), TreatMissingData=notBreaching means no alarm fires.
#
# SOLUTION: Alarm fires when invocation count = 0 over the expected window.
#           Uses a 1-day evaluation period with a 1-day data point requirement,
#           so a single missed invocation triggers the alarm.
#
# Lambdas covered (daily triggers — checked over 1-day window):
#   daily-brief, anomaly-detector, character-sheet-compute,
#   daily-metrics-compute, daily-insight-compute, freshness-checker
#
# Weekly triggers — checked over 7-day window:
#   weekly-digest, hypothesis-engine
#
# Usage: cd ~/Documents/Claude/life-platform && bash deploy/p1_invocation_alarms.sh

set -euo pipefail
REGION="us-west-2"
ACCOUNT="205930651321"
SNS_ARN="arn:aws:sns:$REGION:$ACCOUNT:life-platform-alerts"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  P1.7: Invocation-count alarms for critical Lambdas         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Helper: create a "zero invocations" alarm
# Args: function_name  alarm_suffix  period_seconds  eval_periods  datapoints
make_invocation_alarm() {
    local fn="$1"
    local period="$2"        # seconds per evaluation period
    local eval_periods="$3"  # number of periods to evaluate
    local datapoints="$4"    # datapoints required to breach

    local alarm_name="life-platform-${fn}-invocations"
    echo -n "  $alarm_name ... "

    aws cloudwatch put-metric-alarm \
        --alarm-name "$alarm_name" \
        --alarm-description "SILENT FAILURE: $fn has not been invoked in expected window — may have stopped firing" \
        --namespace "AWS/Lambda" \
        --metric-name "Invocations" \
        --dimensions "Name=FunctionName,Value=$fn" \
        --statistic "Sum" \
        --period "$period" \
        --evaluation-periods "$eval_periods" \
        --datapoints-to-alarm "$datapoints" \
        --threshold 1 \
        --comparison-operator "LessThanThreshold" \
        --treat-missing-data "breaching" \
        --alarm-actions "$SNS_ARN" \
        --region "$REGION" \
        --no-cli-pager
    echo "✅"
}

echo "── Daily Lambdas (alarm if 0 invocations in 26h window) ──"
# Period = 26h (93600s) to give a 2h buffer over the expected daily cadence.
# eval_periods=1, datapoints=1: one missed day triggers immediately.
for fn in \
    "daily-brief" \
    "anomaly-detector" \
    "character-sheet-compute" \
    "daily-metrics-compute" \
    "daily-insight-compute" \
    "life-platform-freshness-checker"; do
    make_invocation_alarm "$fn" 93600 1 1
done
echo ""

echo "── Weekly Lambdas (alarm if 0 invocations in 7-day window) ──"
# Period = 7 days (604800s) — CloudWatch max. If a weekly Lambda misses
# an entire week it alarms. datapoints=1: any zero week triggers.
for fn in \
    "weekly-digest" \
    "hypothesis-engine"; do
    make_invocation_alarm "$fn" 604800 1 1
done
echo ""

echo "── Verification: listing new alarms ──"
aws cloudwatch describe-alarms \
    --alarm-name-prefix "life-platform-" \
    --region "$REGION" \
    --no-cli-pager \
    --query "MetricAlarms[?contains(AlarmName, 'invocations')].{Name:AlarmName,State:StateValue}" \
    --output table

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✅ P1.7 Invocation Alarms Complete                         ║"
echo "║                                                              ║"
echo "║  8 alarms created — all route to life-platform-alerts SNS  ║"
echo "║  TreatMissingData=breaching: silence = alarm                ║"
echo "║                                                              ║"
echo "║  NOTE: Alarms will show INSUFFICIENT_DATA until the first   ║"
echo "║  invocation window passes — this is expected.               ║"
echo "╚══════════════════════════════════════════════════════════════╝"
