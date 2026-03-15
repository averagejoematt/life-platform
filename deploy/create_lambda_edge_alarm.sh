#!/usr/bin/env bash
# deploy/create_lambda_edge_alarm.sh
#
# Creates a CloudWatch alarm for Lambda@Edge invocation errors.
#
# Lambda@Edge metrics ONLY appear in us-east-1 — this is an AWS requirement.
# The cf-auth function runs in every CloudFront edge location, but its metrics
# are aggregated to us-east-1 under the Lambda service namespace.
#
# Alarm fires when ErrorRate > 5% over a 5-minute window across 2 periods.
# This catches: Secrets Manager connectivity issues, password validation bugs,
# or cold-start failures that would silently lock users out of the dashboard.
#
# PREREQUISITES:
#   - The cf-auth Lambda function must be deployed in us-east-1
#   - Run: aws lambda list-functions --region us-east-1 | grep cf-auth
#     to get the exact function name before running this script
#
# USAGE:
#   bash deploy/create_lambda_edge_alarm.sh
#
# WHAT IT DOES:
#   1. Lists Lambda@Edge functions in us-east-1 to find the cf-auth name
#   2. Creates CloudWatch alarm: life-platform-cf-auth-errors
#   3. Routes to SNS: life-platform-alerts (same as other platform alarms)
#
# v1.0.0 — 2026-03-15 (R12 Yael — Lambda@Edge audit)

set -euo pipefail

REGION_EDGE="us-east-1"
REGION_MAIN="us-west-2"
SNS_ARN="arn:aws:sns:${REGION_MAIN}:205930651321:life-platform-alerts"

echo "══════════════════════════════════════════════════════"
echo "  Lambda@Edge Alarm Setup"
echo "══════════════════════════════════════════════════════"
echo ""

# Step 1: Find the cf-auth Lambda function name in us-east-1
echo "🔍 Finding cf-auth Lambda function in us-east-1..."
CF_AUTH_FUNCTION=$(aws lambda list-functions \
    --region "${REGION_EDGE}" \
    --query "Functions[?contains(FunctionName, 'cf-auth')].FunctionName" \
    --output text 2>/dev/null | head -1)

if [ -z "$CF_AUTH_FUNCTION" ] || [ "$CF_AUTH_FUNCTION" = "None" ]; then
    echo "❌ No cf-auth Lambda found in us-east-1."
    echo "   Lambda@Edge functions may be listed under a different name."
    echo "   Run: aws lambda list-functions --region us-east-1 --query 'Functions[*].FunctionName'"
    echo "   Then update this script with the correct function name."
    exit 1
fi
echo "   Found: ${CF_AUTH_FUNCTION}"
echo ""

# Step 2: Verify the life-platform/cf-auth secret exists in us-east-1
echo "🔐 Verifying life-platform/cf-auth secret in us-east-1..."
SECRET_STATUS=$(aws secretsmanager describe-secret \
    --secret-id "life-platform/cf-auth" \
    --region "${REGION_EDGE}" \
    --query "Name" \
    --output text 2>/dev/null || echo "NOT_FOUND")

if [ "$SECRET_STATUS" = "NOT_FOUND" ]; then
    echo "⚠️  Secret 'life-platform/cf-auth' not found in us-east-1."
    echo "   Lambda@Edge requires secrets in us-east-1 (cannot read us-west-2 secrets)."
    echo "   Create it: aws secretsmanager create-secret \\"
    echo "     --name 'life-platform/cf-auth' \\"
    echo "     --secret-string '{\"password\": \"<your-dashboard-password>\"}' \\"
    echo "     --region us-east-1"
    echo ""
    echo "   Then rotate the password by updating the secret value."
else
    echo "   ✅ Secret exists: ${SECRET_STATUS}"
fi
echo ""

# Step 3: Create CloudWatch alarm for Lambda@Edge errors (in us-east-1)
echo "🔔 Creating CloudWatch alarm: life-platform-cf-auth-errors..."

aws cloudwatch put-metric-alarm \
    --alarm-name "life-platform-cf-auth-errors" \
    --alarm-description "Lambda@Edge cf-auth invocation errors — dashboard/blog may be inaccessible" \
    --namespace "AWS/Lambda" \
    --metric-name "Errors" \
    --dimensions Name=FunctionName,Value="${CF_AUTH_FUNCTION}" \
    --statistic Sum \
    --period 300 \
    --evaluation-periods 2 \
    --threshold 5 \
    --comparison-operator GreaterThanOrEqualToThreshold \
    --treat-missing-data notBreaching \
    --alarm-actions "${SNS_ARN}" \
    --ok-actions "${SNS_ARN}" \
    --region "${REGION_EDGE}"

echo "   ✅ Alarm created: life-platform-cf-auth-errors (us-east-1)"
echo ""

# Step 4: Summary
echo "══════════════════════════════════════════════════════"
echo "  Lambda@Edge audit complete."
echo ""
echo "  Function:   ${CF_AUTH_FUNCTION} (us-east-1)"
echo "  Secret:     life-platform/cf-auth (us-east-1)"
echo "  Alarm:      life-platform-cf-auth-errors"
echo "  Threshold:  ≥5 errors in 2 consecutive 5-min windows"
echo "  Alert to:   life-platform-alerts SNS"
echo ""
echo "  NOTE: The buddy page (buddy.averagejoematt.com) is intentionally"
echo "  PUBLIC — no auth Lambda@Edge is needed. It shows non-sensitive"
echo "  accountability data for the Tom buddy system."
echo ""
echo "  NOTE: Lambda@Edge metrics are ONLY in us-east-1, not us-west-2."
echo "  To check logs: aws logs tail /aws/lambda/us-east-1.${CF_AUTH_FUNCTION} --region us-east-1"
echo "══════════════════════════════════════════════════════"
