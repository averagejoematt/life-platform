#!/bin/bash
# TB7-15: Create $5/month AI cost soft alarm in CloudWatch
#
# AWS billing alarms MUST be created in us-east-1 (that's where billing metrics live).
# Alarm fires when estimated monthly AI service charges exceed $5.
#
# Soft alarm = AlarmActions notifies SNS but does not kill anything.
# SNS topic: life-platform-alerts (us-west-2) — bridged via SNS cross-region.
#
# Usage: bash deploy/create_ai_cost_alarm.sh
#
# Note: For Anthropic API charges (not Bedrock), there is no per-service
# CloudWatch metric. The alarm therefore targets total estimated charges
# across all AWS services, filtered to the relevant service dimension where
# available. If you migrate to Amazon Bedrock for AI inference, swap the
# service dimension to "AmazonBedrock".

set -euo pipefail

AWS_ACCOUNT="205930651321"
AWS_BILLING_REGION="us-east-1"     # AWS billing metrics only exist in us-east-1
AWS_HOME_REGION="us-west-2"

BILLING_SNS_TOPIC_NAME="life-platform-billing-alerts"
NOTIFY_EMAIL="awsdev@mattsusername.com"

# ── Step 1: Create us-east-1 SNS topic for billing alerts ──────────────────
# CloudWatch billing alarms require SNS topic in us-east-1 (cross-region not supported)
echo "Creating billing SNS topic in us-east-1..."
BILLING_TOPIC_ARN=$(aws sns create-topic \
  --name "$BILLING_SNS_TOPIC_NAME" \
  --region us-east-1 \
  --query 'TopicArn' --output text)
echo "Topic ARN: $BILLING_TOPIC_ARN"

# Subscribe email (idempotent — re-subscribing existing address is a no-op)
aws sns subscribe \
  --topic-arn "$BILLING_TOPIC_ARN" \
  --protocol email \
  --notification-endpoint "$NOTIFY_EMAIL" \
  --region us-east-1
echo "Email subscription requested for $NOTIFY_EMAIL (confirm via email if first time)"

# ── Step 2: Create total estimated charges alarm ────────────────────────────
echo ""
echo "Creating EstimatedCharges alarm in us-east-1..."
aws cloudwatch put-metric-alarm \
  --alarm-name "life-platform-ai-cost-soft-alarm" \
  --alarm-description "Soft alarm: AWS estimated charges exceeded \$5 this month. Review AI/Lambda spending." \
  --namespace "AWS/Billing" \
  --metric-name "EstimatedCharges" \
  --dimensions Name=Currency,Value=USD \
  --statistic Maximum \
  --period 86400 \
  --evaluation-periods 1 \
  --threshold 5 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "$BILLING_TOPIC_ARN" \
  --ok-actions "$BILLING_TOPIC_ARN" \
  --region "$AWS_BILLING_REGION"

echo "✅ Alarm 'life-platform-ai-cost-soft-alarm' created in us-east-1"

# ── Step 3: Verify alarm exists ─────────────────────────────────────────────
echo ""
echo "Verifying alarm..."
aws cloudwatch describe-alarms \
  --alarm-names "life-platform-ai-cost-soft-alarm" \
  --region "$AWS_BILLING_REGION" \
  --query 'MetricAlarms[0].{Name:AlarmName, State:StateValue, Threshold:Threshold, Period:Period}' \
  --output table

echo ""
echo "⚠️  NOTE: Billing alerts require 'Receive Billing Alerts' to be enabled in"
echo "   AWS Console → Billing → Preferences → Alert Preferences."
echo "   One-time console action if not already done."
