#!/bin/bash
# ============================================================
#  Set 30-day CloudWatch log retention on all Lambda log groups
# ============================================================

set -e

REGION="us-west-2"
RETENTION_DAYS=30

LOG_GROUPS=(
  "/aws/lambda/activity-enrichment"
  "/aws/lambda/anomaly-detector"
  "/aws/lambda/apple-health-ingestion"
  "/aws/lambda/daily-brief"
  "/aws/lambda/life-platform-freshness-checker"
  "/aws/lambda/life-platform-mcp"
  "/aws/lambda/monthly-digest"
  "/aws/lambda/strava-data-ingestion"
  "/aws/lambda/todoist-data-ingestion"
  "/aws/lambda/weekly-digest"
  "/aws/lambda/whoop-data-ingestion"
  "/aws/lambda/withings-data-ingestion"
)

echo ""
echo "Setting ${RETENTION_DAYS}-day retention on ${#LOG_GROUPS[@]} log groups..."
echo ""

for LG in "${LOG_GROUPS[@]}"; do
  aws logs put-retention-policy \
    --log-group-name "$LG" \
    --retention-in-days "$RETENTION_DAYS" \
    --region "$REGION"
  echo "  ✓ $LG"
done

echo ""
echo "Verifying..."
aws logs describe-log-groups \
  --region "$REGION" \
  --query "logGroups[].{Name:logGroupName,RetentionDays:retentionInDays}" \
  --output table
