#!/bin/bash
# deploy_review_group_a.sh — Expert Review Group A: CLI-only fixes
# Platform: v2.53.0 → v2.53.1
# Findings: F5.4, F5.5, F5.6, F6.1, F6.3b, F6.4
# 12 items: timeout right-sizing (5), memory fix (1), daily brief timeout (1),
#           missing error alarms (2), duration alarms (2), DLQ retention (1)
#
# NO code changes — pure AWS CLI configuration updates.
# Safe to run idempotently.

set -euo pipefail
REGION="us-west-2"
SNS_ARN="arn:aws:sns:us-west-2:205930651321:life-platform-alerts"
DLQ_URL="https://sqs.us-west-2.amazonaws.com/205930651321/life-platform-ingestion-dlq"

echo "=========================================="
echo "Group A: Expert Review CLI Fixes"
echo "=========================================="
echo ""

# ──────────────────────────────────────────────
# 1-5. Right-size Lambda timeouts (F5.4)
# ──────────────────────────────────────────────
echo "── Step 1/12: Todoist timeout 300s → 30s ──"
aws lambda update-function-configuration \
  --function-name todoist-data-ingestion \
  --timeout 30 \
  --region $REGION \
  --query 'FunctionName' --output text
echo "✅ Done"

echo "── Step 2/12: Strava timeout 300s → 120s ──"
aws lambda update-function-configuration \
  --function-name strava-data-ingestion \
  --timeout 120 \
  --region $REGION \
  --query 'FunctionName' --output text
echo "✅ Done"

echo "── Step 3/12: Activity Enrichment timeout 300s → 180s ──"
aws lambda update-function-configuration \
  --function-name activity-enrichment \
  --timeout 180 \
  --region $REGION \
  --query 'FunctionName' --output text
echo "✅ Done"

echo "── Step 4/12: Journal Enrichment timeout 300s → 120s ──"
aws lambda update-function-configuration \
  --function-name journal-enrichment \
  --timeout 120 \
  --region $REGION \
  --query 'FunctionName' --output text
echo "✅ Done"

echo "── Step 5/12: MacroFactor timeout 300s → 60s ──"
aws lambda update-function-configuration \
  --function-name macrofactor-data-ingestion \
  --timeout 60 \
  --region $REGION \
  --query 'FunctionName' --output text
echo "✅ Done"

# ──────────────────────────────────────────────
# 6. Journal Enrichment memory 128 → 256 MB (F5.5)
# ──────────────────────────────────────────────
echo ""
echo "── Step 6/12: Journal Enrichment memory 128 → 256 MB ──"
# Wait for any in-progress config update from step 4 to complete
echo "   Waiting 5s for step 4 config update to settle..."
sleep 5
aws lambda update-function-configuration \
  --function-name journal-enrichment \
  --memory-size 256 \
  --region $REGION \
  --query '[FunctionName,MemorySize]' --output text
echo "✅ Done"

# ──────────────────────────────────────────────
# 7. Daily Brief timeout 210 → 300s (F5.6)
# ──────────────────────────────────────────────
echo ""
echo "── Step 7/12: Daily Brief timeout 210s → 300s ──"
aws lambda update-function-configuration \
  --function-name daily-brief \
  --timeout 300 \
  --region $REGION \
  --query 'FunctionName' --output text
echo "✅ Done"

# ──────────────────────────────────────────────
# 8-9. Missing error alarms (F6.1)
# ──────────────────────────────────────────────
echo ""
echo "── Step 8/12: Error alarm for weather-data-ingestion ──"
aws cloudwatch put-metric-alarm \
  --alarm-name "weather-data-ingestion-errors" \
  --alarm-description "Weather ingestion Lambda errors (>= 1 in 24h)" \
  --namespace "AWS/Lambda" \
  --metric-name "Errors" \
  --dimensions Name=FunctionName,Value=weather-data-ingestion \
  --statistic Sum \
  --period 86400 \
  --evaluation-periods 1 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "$SNS_ARN" \
  --region $REGION
echo "✅ Done"

echo "── Step 9/12: Error alarm for freshness-checker (meta-monitor) ──"
aws cloudwatch put-metric-alarm \
  --alarm-name "freshness-checker-errors" \
  --alarm-description "Freshness checker Lambda errors — who watches the watchman? (>= 1 in 24h)" \
  --namespace "AWS/Lambda" \
  --metric-name "Errors" \
  --dimensions Name=FunctionName,Value=life-platform-freshness-checker \
  --statistic Sum \
  --period 86400 \
  --evaluation-periods 1 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "$SNS_ARN" \
  --region $REGION
echo "✅ Done"

# ──────────────────────────────────────────────
# 10-11. Duration alarms (F6.4)
# ──────────────────────────────────────────────
echo ""
echo "── Step 10/12: Duration alarm for daily-brief (>240s) ──"
aws cloudwatch put-metric-alarm \
  --alarm-name "daily-brief-duration-high" \
  --alarm-description "Daily Brief approaching 300s timeout — p99 duration > 240s" \
  --namespace "AWS/Lambda" \
  --metric-name "Duration" \
  --dimensions Name=FunctionName,Value=daily-brief \
  --extended-statistic "p99" \
  --period 86400 \
  --evaluation-periods 1 \
  --threshold 240000 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "$SNS_ARN" \
  --region $REGION
echo "✅ Done"

echo "── Step 11/12: Duration alarm for MCP server (>240s) ──"
aws cloudwatch put-metric-alarm \
  --alarm-name "mcp-server-duration-high" \
  --alarm-description "MCP server approaching 300s timeout — p99 duration > 240s" \
  --namespace "AWS/Lambda" \
  --metric-name "Duration" \
  --dimensions Name=FunctionName,Value=life-platform-mcp \
  --extended-statistic "p99" \
  --period 86400 \
  --evaluation-periods 1 \
  --threshold 240000 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "$SNS_ARN" \
  --region $REGION
echo "✅ Done"

# ──────────────────────────────────────────────
# 12. DLQ message retention 4 days → 14 days (F6.3b)
# ──────────────────────────────────────────────
echo ""
echo "── Step 12/12: DLQ retention → 14 days (1209600s) ──"
aws sqs set-queue-attributes \
  --queue-url "$DLQ_URL" \
  --attributes '{"MessageRetentionPeriod":"1209600"}' \
  --region $REGION
echo "✅ Done"

# ──────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────
echo ""
echo "=========================================="
echo "Group A Complete — 12/12 items applied"
echo "=========================================="
echo ""
echo "Timeouts right-sized:"
echo "  todoist:     300s → 30s"
echo "  strava:      300s → 120s"
echo "  activity:    300s → 180s"
echo "  journal:     300s → 120s"
echo "  macrofactor: 300s → 60s"
echo "  daily-brief: 210s → 300s"
echo ""
echo "Memory fix:"
echo "  journal-enrichment: 128MB → 256MB"
echo ""
echo "New alarms (22 → 26):"
echo "  weather-data-ingestion-errors"
echo "  freshness-checker-errors"
echo "  daily-brief-duration-high (>240s)"
echo "  mcp-server-duration-high (>240s)"
echo ""
echo "DLQ retention: 4 days → 14 days"
echo ""
echo "Next: Run Group B (API Gateway usage plan)"
