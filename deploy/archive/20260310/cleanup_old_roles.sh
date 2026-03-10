#!/bin/bash
# cleanup_old_roles.sh — Delete orphaned console-created IAM roles
# ONLY run after verify_iam_migration.sh passes + 24h clean CloudWatch
set -euo pipefail
echo "═══ Old IAM Role Cleanup ═══"
echo "⚠️  DESTRUCTIVE. Press Enter to continue, Ctrl+C to abort."
read -r
OLD_ROLES=(lambda-whoop-role lambda-garmin-ingestion-role lambda-notion-ingestion-role lambda-withings-role lambda-habitify-ingestion-role lambda-strava-role lambda-journal-enrichment-role lambda-todoist-role lambda-eightsleep-role lambda-enrichment-role lambda-macrofactor-role lambda-weather-role lambda-dropbox-poll-role lambda-apple-health-role lambda-health-auto-export-role lambda-daily-metrics-role lambda-daily-insight-role lambda-adaptive-mode-role lambda-hypothesis-engine-role lambda-anomaly-detector-role life-platform-compute-role lambda-daily-brief-role lambda-weekly-digest-role-v2 lambda-monthly-digest-role lambda-nutrition-review-role lambda-wednesday-chronicle-role lambda-weekly-plate-role lambda-monday-compass-role life-platform-email-role lambda-dlq-consumer-role lambda-canary-role lambda-pip-audit-role lambda-qa-smoke-role lambda-key-rotator-role lambda-data-export-role lambda-data-reconciliation-role lambda-mcp-server-role lambda-freshness-checker-role lambda-insight-email-parser-role)
DEL=0; FAIL=0
for role in "${OLD_ROLES[@]}"; do
    echo -n "  $role... "
    for p in $(aws iam list-role-policies --role-name "$role" --query "PolicyNames[]" --output text 2>/dev/null); do aws iam delete-role-policy --role-name "$role" --policy-name "$p" 2>/dev/null || true; done
    for a in $(aws iam list-attached-role-policies --role-name "$role" --query "AttachedPolicies[].PolicyArn" --output text 2>/dev/null); do aws iam detach-role-policy --role-name "$role" --policy-arn "$a" 2>/dev/null || true; done
    if aws iam delete-role --role-name "$role" 2>/dev/null; then echo "✅"; ((DEL++)); else echo "skip"; ((FAIL++)); fi
done
echo ""; echo "Done: $DEL deleted, $FAIL skipped"
