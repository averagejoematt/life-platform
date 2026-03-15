#!/usr/bin/env bash
# deploy/create_cloudfront_5xx_alarm.sh
#
# R14-F07: Creates a CloudWatch alarm for CloudFront 5xx error rate on the
# dashboard distribution (EM5NPX6NJN095 — dash.averagejoematt.com).
#
# WHY THIS IS SEPARATE FROM create_lambda_edge_alarm.sh:
#   create_lambda_edge_alarm.sh monitors Lambda@Edge INVOCATION ERRORS
#   (the cf-auth function failing to execute). This script monitors
#   CloudFront 5xx RESPONSES sent to end users — a different failure mode.
#   Example: Lambda@Edge runs fine but returns HTTP 502 to the client.
#
# CloudFront metrics are only available in us-east-1 (AWS requirement).
# This script creates a dedicated us-east-1 SNS topic + email subscription
# so alarms can actually send notifications.
#
# PREREQUISITES:
#   - AWS credentials for account 205930651321
#   - awsdev@mattsusername.com must confirm the SNS subscription email
#
# USAGE:
#   bash deploy/create_cloudfront_5xx_alarm.sh
#
# WHAT IT DOES:
#   1. Creates SNS topic: life-platform-alerts-us-east-1 (if not exists)
#   2. Subscribes awsdev@mattsusername.com (confirm email after running)
#   3. Creates CloudWatch alarm: life-platform-dash-5xx-rate (us-east-1)
#   4. Creates CloudWatch alarm: life-platform-dash-total-errors (us-east-1)
#
# v1.0.0 — 2026-03-15 (R14-F07)

set -euo pipefail

REGION="us-east-1"
ACCOUNT="205930651321"
DISTRIBUTION_ID="EM5NPX6NJN095"   # dash.averagejoematt.com
ALERT_EMAIL="awsdev@mattsusername.com"
SNS_TOPIC_NAME="life-platform-alerts-us-east-1"

echo "══════════════════════════════════════════════════════"
echo "  CloudFront 5xx Alarm Setup (R14-F07)"
echo "  Distribution: ${DISTRIBUTION_ID} (dash.averagejoematt.com)"
echo "══════════════════════════════════════════════════════"
echo ""

# ── Step 1: Create SNS topic in us-east-1 ──────────────────────────────────
echo "📢 Creating SNS topic in us-east-1..."
SNS_ARN=$(aws sns create-topic \
    --name "${SNS_TOPIC_NAME}" \
    --region "${REGION}" \
    --query "TopicArn" \
    --output text)
echo "   Topic ARN: ${SNS_ARN}"

# ── Step 2: Subscribe email ────────────────────────────────────────────────
echo ""
echo "📧 Subscribing ${ALERT_EMAIL} to SNS topic..."
SUB_ARN=$(aws sns subscribe \
    --topic-arn "${SNS_ARN}" \
    --protocol email \
    --notification-endpoint "${ALERT_EMAIL}" \
    --region "${REGION}" \
    --query "SubscriptionArn" \
    --output text)

if [ "$SUB_ARN" = "pending confirmation" ]; then
    echo "   ⚠️  Subscription pending — check ${ALERT_EMAIL} and confirm the email."
    echo "      The alarms below will work but won't send email until confirmed."
else
    echo "   ✅ Subscribed: ${SUB_ARN}"
fi

# ── Step 3: 5xx error RATE alarm ──────────────────────────────────────────
echo ""
echo "🔔 Creating alarm: life-platform-dash-5xx-rate..."
aws cloudwatch put-metric-alarm \
    --alarm-name "life-platform-dash-5xx-rate" \
    --alarm-description "CloudFront dash.averagejoematt.com 5xx error rate >5% — dashboard may be broken. Check: CloudFront distribution ${DISTRIBUTION_ID} error pages + Lambda@Edge logs." \
    --namespace "AWS/CloudFront" \
    --metric-name "5xxErrorRate" \
    --dimensions \
        Name=DistributionId,Value="${DISTRIBUTION_ID}" \
        Name=Region,Value="Global" \
    --statistic Average \
    --period 300 \
    --evaluation-periods 2 \
    --threshold 5 \
    --comparison-operator GreaterThanOrEqualToThreshold \
    --treat-missing-data notBreaching \
    --alarm-actions "${SNS_ARN}" \
    --ok-actions "${SNS_ARN}" \
    --region "${REGION}"
echo "   ✅ Alarm created: 5xx rate ≥5% over 2 × 5-min windows"

# ── Step 4: Total error count alarm (catch bursts) ────────────────────────
echo ""
echo "🔔 Creating alarm: life-platform-dash-total-errors..."
aws cloudwatch put-metric-alarm \
    --alarm-name "life-platform-dash-total-errors" \
    --alarm-description "CloudFront dash.averagejoematt.com returned ≥20 total errors in 5 min. Check: CloudFront error pages + origin health." \
    --namespace "AWS/CloudFront" \
    --metric-name "TotalErrorRate" \
    --dimensions \
        Name=DistributionId,Value="${DISTRIBUTION_ID}" \
        Name=Region,Value="Global" \
    --statistic Average \
    --period 300 \
    --evaluation-periods 1 \
    --threshold 10 \
    --comparison-operator GreaterThanOrEqualToThreshold \
    --treat-missing-data notBreaching \
    --alarm-actions "${SNS_ARN}" \
    --region "${REGION}"
echo "   ✅ Alarm created: total error rate ≥10% in any 5-min window"

# ── Summary ──────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════"
echo "  CloudFront alarm setup complete."
echo ""
echo "  SNS topic:  ${SNS_ARN}"
echo "  Email:      ${ALERT_EMAIL}"
echo ""
echo "  Alarms (us-east-1):"
echo "    life-platform-dash-5xx-rate    — 5xx ≥5% for 2 × 5-min windows"
echo "    life-platform-dash-total-errors — total error rate ≥10% any 5-min window"
echo ""
echo "  ⚠️  ACTION REQUIRED: Confirm the subscription email sent to ${ALERT_EMAIL}."
echo "     Without confirmation, alarms fire but no email is sent."
echo ""
echo "  Check alarm state:"
echo "    aws cloudwatch describe-alarms \\"
echo "      --alarm-names life-platform-dash-5xx-rate life-platform-dash-total-errors \\"
echo "      --region us-east-1"
echo ""
echo "  NOTE: CloudFront metrics have up to 1-min delay in us-east-1."
echo "  NOTE: blog (E1JOC1V6E6DDYI) and buddy (ETTJ44FT0Z4GO) are public —"
echo "        add alarms for those distributions separately if desired."
echo "══════════════════════════════════════════════════════"
