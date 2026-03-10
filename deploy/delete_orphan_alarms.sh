#!/usr/bin/env bash
# deploy/delete_orphan_alarms.sh
# COST-A: Delete pre-CDK orphan alarms identified by audit_alarms.sh.
# Populated 2026-03-10 from audit output — 48 alarms to delete, 2 kept.
#
# KEPT (not deleted):
#   health-auto-export-no-invocations-24h  — unique webhook silence detection
#   life-platform-recursive-loop           — safety alarm, unknown metric
#
# Saves: ~$4.80/month (48 alarms × $0.10)

set -euo pipefail
REGION="us-west-2"

TO_DELETE=(
  # AI token per-Lambda (consolidated to daily-brief + platform-total)
  "ai-tokens-adaptive-mode-compute-daily"
  "ai-tokens-anomaly-detector-daily"
  "ai-tokens-character-sheet-compute-daily"
  "ai-tokens-daily-insight-compute-daily"
  "ai-tokens-hypothesis-engine-daily"
  "ai-tokens-monday-compass-daily"
  "ai-tokens-monthly-digest-daily"
  "ai-tokens-nutrition-review-daily"
  "ai-tokens-wednesday-chronicle-daily"
  "ai-tokens-weekly-digest-daily"
  "ai-tokens-weekly-plate-daily"

  # CDK duplicates (removed from stacks)
  "ingestion-error-daily-brief"
  "life-platform-daily-brief-invocations"
  "life-platform-canary-any-failure"

  # Duplicate error alarms (covered by ingestion-error-* CDK alarms)
  "adaptive-mode-compute-errors"
  "character-sheet-compute-errors"
  "daily-metrics-compute-errors"
  "dashboard-refresh-errors"
  "life-platform-anomaly-detector-errors"
  "life-platform-character-sheet-compute-errors"
  "life-platform-daily-insight-compute-errors"
  "life-platform-daily-metrics-compute-errors"
  "life-platform-monthly-digest-errors"
  "life-platform-weekly-digest-errors"
  "life-platform-ingestion-failures"
  "life-platform-lambda-errors"
  "monday-compass-errors"
  "nutrition-review-errors"
  "wednesday-chronicle-errors"
  "weekly-plate-errors"

  # Orphan invocation monitors (no CDK equivalent, low value)
  "life-platform-anomaly-detector-invocations"
  "life-platform-character-sheet-compute-invocations"
  "life-platform-daily-insight-compute-invocations"
  "life-platform-daily-metrics-compute-invocations"
  "life-platform-daily-metrics-compute-missed"
  "life-platform-hypothesis-engine-invocations"
  "life-platform-weekly-digest-invocations"
  "life-platform-life-platform-freshness-checker-invocations"

  # Lambdas with alerts_topic=None in CDK (low-priority ingestion sources)
  "dropbox-poll-errors"
  "garmin-data-ingestion-errors"
  "habitify-ingestion-errors"
  "journal-enrichment-errors"
  "notion-ingestion-errors"
  "insight-email-parser-errors"
  "weather-data-ingestion-errors"

  # Misc orphans
  "ai-anthropic-api-failures"           # overlaps with slo-ai-coaching-success
  "daily-metrics-compute-duration-high" # orphan duration alarm, pre-CDK remnant
  "ingestion-error-brittany-weekly-email" # CDK will recreate when Brittany deploys
)

echo "=== Deleting ${#TO_DELETE[@]} orphan alarms ==="
echo "Region: $REGION"
echo ""

DELETED=0
SKIPPED=0

for alarm in "${TO_DELETE[@]}"; do
  EXISTS=$(aws cloudwatch describe-alarms \
    --alarm-names "$alarm" \
    --region "$REGION" \
    --query 'MetricAlarms[0].AlarmName' \
    --output text 2>/dev/null || echo "None")

  if [[ "$EXISTS" != "None" && -n "$EXISTS" ]]; then
    echo "  Deleting: $alarm"
    aws cloudwatch delete-alarms \
      --alarm-names "$alarm" \
      --region "$REGION"
    ((DELETED+=1))
  else
    echo "  Skipping: $alarm (not found)"
    ((SKIPPED+=1))
  fi
done

echo ""
echo "Done. Deleted: $DELETED  |  Skipped (not found): $SKIPPED"
echo "Savings: ~\$$(echo "$DELETED * 0.10" | bc)/month"
echo ""
echo "Next: cd cdk && cdk deploy LifePlatformMonitoring LifePlatformEmail LifePlatformOperational"
