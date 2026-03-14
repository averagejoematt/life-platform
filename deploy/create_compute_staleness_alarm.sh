#!/usr/bin/env bash
# create_compute_staleness_alarm.sh — Risk-7: alarm when daily-brief detects compute pipeline stale.
# Fires if ComputePipelineStaleness >= 1 for any datapoint in a 24h window.
# Metric emitted by daily_brief_lambda.py after reading computed_metrics partition.
set -euo pipefail
REGION="us-west-2"
SNS_ARN="arn:aws:sns:${REGION}:205930651321:life-platform-alerts"

echo "Creating ComputePipelineStaleness alarm..."
aws cloudwatch put-metric-alarm \
    --alarm-name "life-platform-compute-pipeline-stale" \
    --alarm-description "Daily brief found computed_metrics missing or >4h stale — daily-metrics-compute Lambda may not have run" \
    --namespace "LifePlatform" \
    --metric-name "ComputePipelineStaleness" \
    --dimensions Name=Source,Value=computed_metrics \
    --statistic Maximum \
    --period 86400 \
    --evaluation-periods 1 \
    --threshold 1 \
    --comparison-operator GreaterThanOrEqualToThreshold \
    --treat-missing-data notBreaching \
    --alarm-actions "$SNS_ARN" \
    --region "$REGION"

echo "✅ Alarm created: life-platform-compute-pipeline-stale"
echo "   Fires when: ComputePipelineStaleness >= 1 (MAX) over 24h"
echo "   Action: SNS → life-platform-alerts"
