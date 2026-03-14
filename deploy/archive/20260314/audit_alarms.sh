#!/usr/bin/env bash
# deploy/audit_alarms.sh
# COST-A: Audit CloudWatch alarms — identify pre-CDK orphans for deletion.
# Run BEFORE delete_orphan_alarms.sh to verify the orphan list.
# Usage: bash deploy/audit_alarms.sh

set -euo pipefail
REGION="us-west-2"

echo "=== CloudWatch Alarm Audit ==="
echo "Fetching all alarms in $REGION..."
echo ""

# Fetch all alarm names (paginated)
ALL_ALARMS=$(aws cloudwatch describe-alarms \
  --region "$REGION" \
  --output json | python3 -c "
import json, sys
data = json.load(sys.stdin)
alarms = sorted([a['AlarmName'] for a in data['MetricAlarms']])
for a in alarms:
    print(a)
")

TOTAL=$(echo "$ALL_ALARMS" | wc -l | tr -d ' ')
echo "Total alarms found: $TOTAL"
echo ""

# CDK-expected alarm names (post COST-A cleanup — after next cdk deploy)
CDK_EXPECTED=(
  # Ingestion
  ingestion-error-whoop
  ingestion-error-withings
  ingestion-error-strava
  ingestion-error-todoist
  ingestion-error-eightsleep
  ingestion-error-enrichment
  ingestion-error-macrofactor
  ingestion-error-apple-health
  # Compute
  ingestion-error-anomaly-detector
  ingestion-error-character-sheet-compute
  ingestion-error-daily-metrics-compute
  ingestion-error-daily-insight-compute
  ingestion-error-adaptive-mode-compute
  ingestion-error-hypothesis-engine
  ingestion-error-dashboard-refresh
  ingestion-error-failure-pattern-compute
  # Email (daily-brief excluded — owned by MonitoringStack)
  ingestion-error-weekly-digest
  ingestion-error-monthly-digest
  ingestion-error-nutrition-review
  ingestion-error-wednesday-chronicle
  ingestion-error-weekly-plate
  ingestion-error-monday-compass
  # ingestion-error-brittany-weekly-email  (not yet deployed)
  # Operational
  freshness-checker-errors
  key-rotator-errors
  life-platform-data-export-errors
  life-platform-canary-ddb-failure
  life-platform-canary-mcp-failure
  life-platform-canary-s3-failure
  life-platform-dlq-depth-warning
  # Monitoring — SLO
  slo-daily-brief-delivery
  slo-ai-coaching-success
  slo-source-freshness
  # Monitoring — daily-brief operational
  daily-brief-duration-high
  daily-brief-no-invocations-24h
  life-platform-daily-brief-errors
  # Monitoring — AI tokens (consolidated: daily-brief + platform only)
  ai-tokens-daily-brief-daily
  ai-tokens-platform-daily-total
  # Monitoring — DDB
  life-platform-ddb-item-size-warning
  # MCP
  mcp-server-duration-high
  slo-mcp-availability
)

echo "=== CDK-EXPECTED ALARMS (should exist after next cdk deploy) ==="
for name in "${CDK_EXPECTED[@]}"; do
  if echo "$ALL_ALARMS" | grep -qx "$name"; then
    echo "  [OK]      $name"
  else
    echo "  [MISSING] $name  <- will be created by cdk deploy"
  fi
done

echo ""
echo "=== CANDIDATE ORPHANS (not in CDK-expected, likely pre-CDK strays) ==="
ORPHAN_COUNT=0
ORPHAN_LIST=""
while IFS= read -r alarm; do
  FOUND=false
  for expected in "${CDK_EXPECTED[@]}"; do
    if [[ "$alarm" == "$expected" ]]; then
      FOUND=true
      break
    fi
  done
  if [[ "$FOUND" == false ]]; then
    echo "  [ORPHAN]  $alarm"
    ORPHAN_LIST="$ORPHAN_LIST $alarm"
    ((ORPHAN_COUNT+=1))
  fi
done <<< "$ALL_ALARMS"

echo ""
echo "Summary: $ORPHAN_COUNT orphan alarms identified (out of $TOTAL total)"
echo ""
echo "Next steps:"
echo "  1. Review orphans above — confirm none are intentional"
echo "  2. Run: bash deploy/delete_orphan_alarms.sh"
echo "  3. Run: cd cdk && cdk deploy LifePlatformMonitoring LifePlatformEmail LifePlatformOperational"
