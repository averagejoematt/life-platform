#!/usr/bin/env bash
# deploy_obs1_ai3_apikeys.sh
# Deploys: OBS-1 + AI-3 rollout to brittany-weekly-email
#          api-keys pre-deletion fixes (journal-enrichment, habitify CDK bug)
#
# Lambda code changes:
#   brittany_email_lambda.py   — add platform_logger (OBS-1) + ai_output_validator (AI-3)
#   journal_enrichment_lambda.py — fix ANTHROPIC_SECRET default (api-keys → ai-keys)
#   habitify_lambda.py           — fix SECRET_NAME default (api-keys → habitify)
#   notion_lambda.py             — fix SECRET_NAME default (api-keys → ingestion-keys)
#   todoist_lambda.py            — fix SECRET_NAME default (api-keys → ingestion-keys)
#
# CDK changes (deploy separately via cdk deploy):
#   ingestion_stack.py — JournalEnrichment: add ANTHROPIC_SECRET=life-platform/ai-keys
#   ingestion_stack.py — HabitifyIngestion: HABITIFY_SECRET_NAME=life-platform/habitify
#
# Usage:
#   bash deploy/deploy_obs1_ai3_apikeys.sh
#
set -euo pipefail

REGION="us-west-2"
LAYER_ARN="arn:aws:lambda:us-west-2:205930651321:layer:life-platform-shared-utils:4"

deploy_lambda() {
  local fn="$1"
  local src="$2"
  echo ""
  echo "── Deploying $fn ──"
  cd "$(dirname "$0")/.."
  zip -q /tmp/${fn}.zip lambdas/${src}
  aws lambda update-function-code \
    --function-name "$fn" \
    --zip-file fileb:///tmp/${fn}.zip \
    --region "$REGION" \
    --query 'FunctionName' --output text
  echo "  ✓ Code uploaded"
  sleep 10
}

echo "=== OBS-1 + AI-3 + api-keys pre-deletion fixes ==="
echo ""

# 1. brittany-weekly-email — OBS-1 + AI-3
deploy_lambda "brittany-weekly-email" "brittany_email_lambda.py"

# 2. journal-enrichment — fix ANTHROPIC_SECRET default (api-keys → ai-keys)
deploy_lambda "journal-enrichment" "journal_enrichment_lambda.py"

# 3. habitify-data-ingestion — fix SECRET_NAME default
deploy_lambda "habitify-data-ingestion" "habitify_lambda.py"

# 4. notion-journal-ingestion — fix SECRET_NAME default
deploy_lambda "notion-journal-ingestion" "notion_lambda.py"

# 5. todoist-data-ingestion — fix SECRET_NAME default
deploy_lambda "todoist-data-ingestion" "todoist_lambda.py"

echo ""
echo "=== Lambda deploys complete ==="
echo ""
echo "NEXT STEP — CDK deploy for env var changes (journal-enrichment + habitify):"
echo "  cd cdk && cdk deploy IngestionStack --require-approval never"
echo ""
echo "REMAINING api-keys checklist before deletion (~2026-04-07):"
echo "  ✅ journal_enrichment default → ai-keys (code + CDK)"
echo "  ✅ habitify default → habitify secret (code + CDK)"
echo "  ✅ notion default → ingestion-keys (code only — CDK already correct)"
echo "  ✅ todoist default → ingestion-keys (code only — CDK already correct)"
echo "  ⬜ Confirm 'life-platform/api-keys' still exists in Secrets Manager"
echo "  ⬜ Run: aws secretsmanager describe-secret --secret-id life-platform/api-keys"
echo "  ⬜ Delete after CDK deploy confirms journal-enrichment running with ai-keys"
