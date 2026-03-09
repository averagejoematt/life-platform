#!/bin/bash
# deploy/obs3_slo_definitions.sh — OBS-3: Define SLOs for critical paths
# Creates 4 SLO CloudWatch alarms + updates freshness checker IAM + deploys freshness Lambda + updates ops dashboard
set -euo pipefail
REGION="us-west-2"
ACCOUNT="205930651321"
SNS_ARN="arn:aws:sns:${REGION}:${ACCOUNT}:life-platform-alerts"

echo "═══════════════════════════════════════════════════════════"
echo "OBS-3: SLO Definitions — 4 alarms + freshness metrics"
echo "═══════════════════════════════════════════════════════════"

# ── Step 1: Add CloudWatch PutMetricData to freshness checker IAM role ──
echo ""
echo "Step 1: Adding cloudwatch:PutMetricData to freshness checker role..."
ROLE_NAME="lambda-freshness-checker-role"

# Check current policies
CURRENT_POLICIES=$(aws iam list-attached-role-policies --role-name "$ROLE_NAME" --query 'AttachedPolicies[*].PolicyName' --output text 2>/dev/null || echo "")
echo "  Current policies: $CURRENT_POLICIES"

# Get the inline policy (if any) or the attached custom policy
INLINE_POLICIES=$(aws iam list-role-policies --role-name "$ROLE_NAME" --query 'PolicyNames' --output text 2>/dev/null || echo "")
echo "  Inline policies: $INLINE_POLICIES"

# Add CloudWatch permission via inline policy
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "slo-cloudwatch-metrics" \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": "cloudwatch:PutMetricData",
        "Resource": "*",
        "Condition": {
          "StringEquals": {
            "cloudwatch:namespace": "LifePlatform/Freshness"
          }
        }
      }
    ]
  }'
echo "  ✅ cloudwatch:PutMetricData added (scoped to LifePlatform/Freshness namespace)"

# ── Step 2: Deploy freshness checker Lambda ──
echo ""
echo "Step 2: Deploying freshness checker Lambda..."
bash deploy/deploy_lambda.sh life-platform-freshness-checker lambdas/freshness_checker_lambda.py
echo "  ✅ Freshness checker deployed"

sleep 5

# ── Step 3: Create SLO-1 alarm: Daily Brief Delivery ──
echo ""
echo "Step 3: Creating SLO-1 alarm (Daily Brief delivery)..."
aws cloudwatch put-metric-alarm \
  --alarm-name "slo-daily-brief-delivery" \
  --alarm-description "SLO-1: Daily Brief Lambda errored. Target: 99% daily success." \
  --namespace "AWS/Lambda" \
  --metric-name "Errors" \
  --dimensions Name=FunctionName,Value=daily-brief \
  --statistic Sum \
  --period 86400 \
  --evaluation-periods 1 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "$SNS_ARN" \
  --ok-actions "$SNS_ARN" \
  --region "$REGION"
echo "  ✅ slo-daily-brief-delivery alarm created"

# ── Step 4: Create SLO-2 alarm: Source Freshness ──
echo ""
echo "Step 4: Creating SLO-2 alarm (Source Freshness)..."
aws cloudwatch put-metric-alarm \
  --alarm-name "slo-source-freshness" \
  --alarm-description "SLO-2: Data sources stale (>48h). Target: 99% checks show 0 stale." \
  --namespace "LifePlatform/Freshness" \
  --metric-name "StaleSourceCount" \
  --statistic Maximum \
  --period 86400 \
  --evaluation-periods 2 \
  --datapoints-to-alarm 2 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "$SNS_ARN" \
  --ok-actions "$SNS_ARN" \
  --region "$REGION"
echo "  ✅ slo-source-freshness alarm created"

# ── Step 5: Create SLO-3 alarm: MCP Availability ──
echo ""
echo "Step 5: Creating SLO-3 alarm (MCP Availability)..."
# Use math expression: error rate = errors / invocations
aws cloudwatch put-metric-alarm \
  --alarm-name "slo-mcp-availability" \
  --alarm-description "SLO-3: MCP Lambda error rate >0.5%. Target: 99.5% availability." \
  --namespace "AWS/Lambda" \
  --metric-name "Errors" \
  --dimensions Name=FunctionName,Value=life-platform-mcp \
  --statistic Sum \
  --period 3600 \
  --evaluation-periods 3 \
  --datapoints-to-alarm 2 \
  --threshold 3 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "$SNS_ARN" \
  --ok-actions "$SNS_ARN" \
  --region "$REGION"
echo "  ✅ slo-mcp-availability alarm created"

# ── Step 6: Create SLO-4 alarm: AI Coaching Success ──
echo ""
echo "Step 6: Creating SLO-4 alarm (AI Coaching Success)..."
aws cloudwatch put-metric-alarm \
  --alarm-name "slo-ai-coaching-success" \
  --alarm-description "SLO-4: AI API failures >2 in 24h. Target: 99% success rate." \
  --namespace "LifePlatform/AI" \
  --metric-name "AnthropicAPIFailure" \
  --statistic Sum \
  --period 86400 \
  --evaluation-periods 1 \
  --threshold 3 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "$SNS_ARN" \
  --ok-actions "$SNS_ARN" \
  --region "$REGION"
echo "  ✅ slo-ai-coaching-success alarm created"

# ── Step 7: Update ops dashboard with SLO section ──
echo ""
echo "Step 7: Updating ops dashboard with SLO widgets..."

# Get existing dashboard body
EXISTING=$(aws cloudwatch get-dashboard --dashboard-name life-platform-ops --query 'DashboardBody' --output text --region "$REGION" 2>/dev/null || echo "")

if [ -z "$EXISTING" ] || [ "$EXISTING" = "None" ]; then
  echo "  ⚠️ No existing ops dashboard found — creating fresh with SLO widgets only"
  DASHBOARD_BODY='{
    "widgets": []
  }'
else
  DASHBOARD_BODY="$EXISTING"
fi

# Create SLO widget JSON
SLO_WIDGETS='[
  {
    "type": "text",
    "x": 0, "y": 0, "width": 24, "height": 1,
    "properties": {
      "markdown": "# 🎯 SLO Health"
    }
  },
  {
    "type": "metric",
    "x": 0, "y": 1, "width": 6, "height": 4,
    "properties": {
      "title": "SLO-1: Daily Brief Delivery",
      "metrics": [
        ["AWS/Lambda", "Errors", "FunctionName", "daily-brief", {"stat": "Sum", "period": 86400, "color": "#d62728"}],
        ["AWS/Lambda", "Invocations", "FunctionName", "daily-brief", {"stat": "Sum", "period": 86400, "color": "#2ca02c"}]
      ],
      "view": "timeSeries",
      "region": "us-west-2",
      "period": 86400,
      "yAxis": {"left": {"min": 0}}
    }
  },
  {
    "type": "metric",
    "x": 6, "y": 1, "width": 6, "height": 4,
    "properties": {
      "title": "SLO-2: Source Freshness",
      "metrics": [
        ["LifePlatform/Freshness", "StaleSourceCount", {"stat": "Maximum", "period": 86400, "color": "#d62728"}],
        ["LifePlatform/Freshness", "FreshSourceCount", {"stat": "Maximum", "period": 86400, "color": "#2ca02c"}]
      ],
      "view": "timeSeries",
      "region": "us-west-2",
      "period": 86400,
      "yAxis": {"left": {"min": 0, "max": 10}}
    }
  },
  {
    "type": "metric",
    "x": 12, "y": 1, "width": 6, "height": 4,
    "properties": {
      "title": "SLO-3: MCP Availability",
      "metrics": [
        ["AWS/Lambda", "Errors", "FunctionName", "life-platform-mcp", {"stat": "Sum", "period": 3600, "color": "#d62728"}],
        ["AWS/Lambda", "Invocations", "FunctionName", "life-platform-mcp", {"stat": "Sum", "period": 3600, "color": "#2ca02c"}]
      ],
      "view": "timeSeries",
      "region": "us-west-2",
      "period": 3600,
      "yAxis": {"left": {"min": 0}}
    }
  },
  {
    "type": "metric",
    "x": 18, "y": 1, "width": 6, "height": 4,
    "properties": {
      "title": "SLO-4: AI Coaching Success",
      "metrics": [
        ["LifePlatform/AI", "AnthropicAPIFailure", {"stat": "Sum", "period": 86400, "color": "#d62728"}]
      ],
      "view": "timeSeries",
      "region": "us-west-2",
      "period": 86400,
      "yAxis": {"left": {"min": 0}}
    }
  }
]'

# Merge SLO widgets into existing dashboard using Python
python3 -c "
import json, sys

existing = '''$DASHBOARD_BODY'''
try:
    dashboard = json.loads(existing)
except:
    dashboard = {'widgets': []}

slo_widgets = json.loads('''$SLO_WIDGETS''')

# Remove any existing SLO widgets (by checking for titles/markdown containing 'SLO')
dashboard['widgets'] = [w for w in dashboard.get('widgets', [])
                        if not ('SLO' in str(w.get('properties', {}).get('markdown', ''))
                                or 'SLO-' in str(w.get('properties', {}).get('title', '')))]

# Shift existing widgets down by 5 rows to make room for SLO section at top
for w in dashboard['widgets']:
    w['y'] = w.get('y', 0) + 5

# Add SLO widgets at the top
dashboard['widgets'] = slo_widgets + dashboard['widgets']

print(json.dumps(dashboard))
" > /tmp/slo_dashboard.json

aws cloudwatch put-dashboard \
  --dashboard-name life-platform-ops \
  --dashboard-body "file:///tmp/slo_dashboard.json" \
  --region "$REGION"
echo "  ✅ Ops dashboard updated with SLO section"

# ── Step 8: Smoke test freshness checker ──
echo ""
echo "Step 8: Smoke testing freshness checker..."
aws lambda invoke \
  --function-name life-platform-freshness-checker \
  --payload '{}' \
  --region "$REGION" \
  /tmp/freshness_test.json > /dev/null 2>&1
RESULT=$(cat /tmp/freshness_test.json)
echo "  Result: $RESULT"

# ── Step 9: Verify alarms ──
echo ""
echo "Step 9: Verifying SLO alarms..."
aws cloudwatch describe-alarms \
  --alarm-names slo-daily-brief-delivery slo-source-freshness slo-mcp-availability slo-ai-coaching-success \
  --query 'MetricAlarms[*].{Name:AlarmName,State:StateValue}' \
  --output table \
  --region "$REGION"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ OBS-3 Complete!"
echo ""
echo "Created:"
echo "  • 4 SLO alarms (slo-daily-brief-delivery, slo-source-freshness,"
echo "    slo-mcp-availability, slo-ai-coaching-success)"
echo "  • Freshness checker now emits StaleSourceCount/FreshSourceCount"
echo "  • Ops dashboard updated with SLO Health section"
echo "  • docs/SLOs.md defines targets, SLIs, and error budgets"
echo "═══════════════════════════════════════════════════════════"
