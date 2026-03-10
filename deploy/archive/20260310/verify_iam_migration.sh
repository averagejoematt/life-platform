#!/bin/bash
# verify_iam_migration.sh — Confirm all Lambdas use CDK-managed roles
set -euo pipefail
echo "═══ IAM Role Migration Verification ═══"
LAMBDAS=(whoop-data-ingestion garmin-data-ingestion notion-journal-ingestion withings-data-ingestion habitify-data-ingestion strava-data-ingestion journal-enrichment todoist-data-ingestion eightsleep-data-ingestion activity-enrichment macrofactor-data-ingestion weather-data-ingestion dropbox-poll apple-health-ingestion health-auto-export-webhook anomaly-detector character-sheet-compute daily-metrics-compute daily-insight-compute adaptive-mode-compute hypothesis-engine dashboard-refresh daily-brief weekly-digest monthly-digest nutrition-review wednesday-chronicle weekly-plate monday-compass brittany-weekly-email life-platform-dlq-consumer life-platform-canary life-platform-pip-audit life-platform-qa-smoke life-platform-key-rotator life-platform-data-export life-platform-data-reconciliation life-platform-mcp)
OLD_PREFIXES=("lambda-" "life-platform-email-role" "life-platform-compute-role")
PASS=0; FAIL=0; SKIP=0
for fn in "${LAMBDAS[@]}"; do
    role_arn=$(aws lambda get-function-configuration --function-name "$fn" --query "Role" --output text 2>/dev/null || echo "NOT_FOUND")
    if [ "$role_arn" = "NOT_FOUND" ]; then echo "  ⚠️  $fn — not found"; ((SKIP++)); continue; fi
    role_name=$(echo "$role_arn" | sed 's/.*:role\///')
    is_old=false
    for prefix in "${OLD_PREFIXES[@]}"; do [[ "$role_name" == "$prefix"* ]] && is_old=true && break; done
    if [ "$is_old" = true ]; then echo "  ❌ $fn → $role_name (OLD)"; ((FAIL++)); else echo "  ✅ $fn → $role_name"; ((PASS++)); fi
done
echo ""; echo "Results: $PASS passed, $FAIL failed, $SKIP skipped"
[ "$FAIL" -gt 0 ] && echo "⚠️  Some Lambdas still use old roles." && exit 1
echo "✅ All Lambdas migrated to CDK-managed roles."
