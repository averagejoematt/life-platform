#!/usr/bin/env bash
# deploy/delete_old_ingestion_secrets.sh
# COST-B: Delete the 4 individual secrets after LifePlatformIngestion CDK deploy
#         has been verified working. Run ONLY after confirming Lambda invocations succeed.
#
# Saves: 3 secrets × $0.40 = $1.20/month (habitify was already being kept;
#        todoist + notion + dropbox are eliminated → ingestion-keys)
#
# NOTE: Secrets Manager has a recovery window. These will be scheduled for
#       deletion with a 7-day recovery window, not immediately deleted.

set -euo pipefail
REGION="us-west-2"

echo "=== COST-B: Delete old individual ingestion secrets ==="
echo ""
echo "WARNING: Only run this AFTER verifying CDK deploy + Lambda invocations work."
echo "Press Ctrl-C to cancel. Proceeding in 5 seconds..."
sleep 5

SECRETS=(
  "life-platform/todoist"
  "life-platform/notion"
  "life-platform/dropbox"
  "life-platform/habitify"
)

for secret in "${SECRETS[@]}"; do
  EXISTS=$(aws secretsmanager describe-secret \
    --secret-id "$secret" \
    --region "$REGION" \
    --query Name --output text 2>/dev/null || echo "NOT_FOUND")

  if [[ "$EXISTS" != "NOT_FOUND" ]]; then
    echo "  Scheduling deletion (7-day recovery): $secret"
    aws secretsmanager delete-secret \
      --secret-id "$secret" \
      --recovery-window-in-days 7 \
      --region "$REGION" > /dev/null
    echo "  [OK] $secret — will be permanently deleted in 7 days"
  else
    echo "  Skipping: $secret (not found)"
  fi
done

echo ""
echo "Done. Savings: ~\$1.20/month once billing period rolls over."
echo "Remaining secrets: life-platform/{whoop,garmin,withings,strava,eightsleep,ai-keys,mcp-api-key,ingestion-keys} = 8 active"
echo ""
echo "Note: life-platform/api-keys still pending deletion ~2026-04-07 (saves another \$0.40)"
