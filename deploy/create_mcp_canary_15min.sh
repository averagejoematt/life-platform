#!/bin/bash
# deploy/create_mcp_canary_15min.sh
# R13-F14: MCP endpoint canary — synthetic probe every 15 minutes.
#
# The existing life-platform-canary runs every 4 hours and includes DDB, S3, and
# MCP checks. R13-F14 asks specifically for MCP Function URL probing at 15-min
# cadence to catch MCP-specific outages (deploy failures, handler crashes, OOM)
# before a human notices a tool call failing in their session.
#
# Approach:
#   1. New EventBridge rule: rate(15 minutes) → life-platform-canary
#      Passes {"mcp_only": true} to signal canary to run only the MCP check.
#      (The canary handler already supports skipping checks based on event payload
#      via the check order; a lightweight "ping" mode is added in the same lambda.)
#   2. CloudWatch alarm: CanaryMCPFail >= 1 in any 15-min window → SNS
#   3. CloudWatch alarm: CanaryMCPLatencyP95 > 10,000ms → SNS (latency degradation)
#
# Usage: bash deploy/create_mcp_canary_15min.sh
# Requires: AWS CLI with credentials for account 205930651321

set -euo pipefail

REGION="us-west-2"
ACCOUNT="205930651321"
SNS_ARN="arn:aws:sns:${REGION}:${ACCOUNT}:life-platform-alerts"
CANARY_FUNCTION="life-platform-canary"
RULE_NAME="life-platform-mcp-canary-15min"

echo "=== R13-F14: Creating MCP 15-minute canary ==="
echo ""

# ── Get canary Lambda ARN ─────────────────────────────────────────────────────
CANARY_ARN=$(aws lambda get-function \
  --function-name "${CANARY_FUNCTION}" \
  --region "${REGION}" \
  --query "Configuration.FunctionArn" \
  --output text)
echo "Canary Lambda ARN: ${CANARY_ARN}"

# ── Create/update EventBridge rule ───────────────────────────────────────────
echo ""
echo "Creating EventBridge rule: ${RULE_NAME} (every 15 min)..."
aws events put-rule \
  --name "${RULE_NAME}" \
  --schedule-expression "rate(15 minutes)" \
  --state ENABLED \
  --description "R13-F14: MCP endpoint canary — synthetic probe every 15 min" \
  --region "${REGION}"
echo "  ✅ Rule created"

# ── Add Lambda permission for this rule ──────────────────────────────────────
echo "Adding Lambda invoke permission for ${RULE_NAME}..."
aws lambda add-permission \
  --function-name "${CANARY_FUNCTION}" \
  --statement-id "EB-${RULE_NAME}" \
  --action "lambda:InvokeFunction" \
  --principal "events.amazonaws.com" \
  --source-arn "arn:aws:events:${REGION}:${ACCOUNT}:rule/${RULE_NAME}" \
  --region "${REGION}" 2>/dev/null || echo "  (permission already exists — skipping)"
echo "  ✅ Permission OK"

# ── Add Lambda as target with mcp_only payload ────────────────────────────────
echo "Adding Lambda target with mcp_only=true payload..."
aws events put-targets \
  --rule "${RULE_NAME}" \
  --targets "[{
    \"Id\": \"CanaryMcpTarget\",
    \"Arn\": \"${CANARY_ARN}\",
    \"Input\": \"{\\\"mcp_only\\\": true}\"
  }]" \
  --region "${REGION}"
echo "  ✅ Target added"

# ── CloudWatch alarm: MCP failures ───────────────────────────────────────────
echo ""
echo "Creating CloudWatch alarm: MCP canary failure..."
aws cloudwatch put-metric-alarm \
  --alarm-name "life-platform-mcp-canary-failure-15min" \
  --alarm-description "R13-F14: MCP Function URL probe failed. Tool calls from Claude may be broken." \
  --namespace "LifePlatform/Canary" \
  --metric-name "CanaryMCPFail" \
  --statistic Sum \
  --period 900 \
  --evaluation-periods 1 \
  --datapoints-to-alarm 1 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "${SNS_ARN}" \
  --region "${REGION}"
echo "  ✅ MCP failure alarm created"

# ── CloudWatch alarm: MCP latency degradation ────────────────────────────────
echo "Creating CloudWatch alarm: MCP canary latency..."
aws cloudwatch put-metric-alarm \
  --alarm-name "life-platform-mcp-canary-latency-15min" \
  --alarm-description "R13-F14: MCP Lambda tools/list p95 latency >10s. Silent timeout risk for tool calls." \
  --namespace "LifePlatform/Canary" \
  --metric-name "CanaryLatencyMCP_ms" \
  --extended-statistic p95 \
  --period 900 \
  --evaluation-periods 2 \
  --datapoints-to-alarm 2 \
  --threshold 10000 \
  --comparison-operator GreaterThanThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "${SNS_ARN}" \
  --region "${REGION}"
echo "  ✅ MCP latency alarm created"

# ── Verify ────────────────────────────────────────────────────────────────────
echo ""
echo "=== Verifying ==="
aws cloudwatch describe-alarms \
  --alarm-names \
    "life-platform-mcp-canary-failure-15min" \
    "life-platform-mcp-canary-latency-15min" \
  --region "${REGION}" \
  --query "MetricAlarms[*].{Name:AlarmName,State:StateValue,Threshold:Threshold}" \
  --output table

echo ""
echo "=== EventBridge rule ==="
aws events describe-rule \
  --name "${RULE_NAME}" \
  --region "${REGION}" \
  --query "{Name:Name,State:State,Schedule:ScheduleExpression}" \
  --output table

echo ""
echo "✅ R13-F14 complete."
echo "   MCP is now probed every 15 minutes via ${RULE_NAME}"
echo "   Alarms:"
echo "     life-platform-mcp-canary-failure-15min  (any failure → SNS)"
echo "     life-platform-mcp-canary-latency-15min  (p95 >10s × 2 windows → SNS)"
