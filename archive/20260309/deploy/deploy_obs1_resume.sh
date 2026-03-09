#!/usr/bin/env bash
# deploy/deploy_obs1_resume.sh
# Resumes OBS-1 deploy from item 6 — skips the 3 Lambdas not yet created in AWS
# (data-export, data-reconciliation, pip-audit — these need creation scripts first).
#
# Covers items 6-17 minus the 3 missing functions = 9 Lambdas.
# Usage: bash deploy/deploy_obs1_resume.sh

set -euo pipefail

cd "$(dirname "$0")/.."

LAMBDA_NAMES=(
  "life-platform-dlq-consumer"
  "dropbox-poll"
  "life-platform-freshness-checker"
  "hypothesis-engine"
  "life-platform-canary"
  "adaptive-mode-compute"
  "insight-email-parser"
  "life-platform-key-rotator"
  "life-platform-qa-smoke"
)

LAMBDA_FILES=(
  "lambdas/dlq_consumer_lambda.py"
  "lambdas/dropbox_poll_lambda.py"
  "lambdas/freshness_checker_lambda.py"
  "lambdas/hypothesis_engine_lambda.py"
  "lambdas/canary_lambda.py"
  "lambdas/adaptive_mode_lambda.py"
  "lambdas/insight_email_parser_lambda.py"
  "lambdas/key_rotator_lambda.py"
  "lambdas/qa_smoke_lambda.py"
)

echo "=== OBS-1 Resume Deploy (9 remaining) ==="
echo "Skipped (not yet created in AWS): data-export, data-reconciliation, pip-audit"
echo ""

for i in "${!LAMBDA_NAMES[@]}"; do
  FUNC_NAME="${LAMBDA_NAMES[$i]}"
  SOURCE_FILE="${LAMBDA_FILES[$i]}"

  echo "━━━ [$((i+1))/${#LAMBDA_NAMES[@]}] Deploying $FUNC_NAME ━━━"
  bash deploy/deploy_lambda.sh "$FUNC_NAME" "$SOURCE_FILE"
  echo "✅ $FUNC_NAME deployed"

  if [ $i -lt $((${#LAMBDA_NAMES[@]} - 1)) ]; then
    echo "Waiting 10s..."
    sleep 10
  fi
done

echo ""
echo "=== OBS-1 resume complete (9/9) ==="
echo ""
echo "OBS-1 status:"
echo "  ✅ 14/17 Lambdas deployed (5 already done + 9 this run)"
echo "  ⏭️  data-export       — Lambda not yet created in AWS"
echo "  ⏭️  data-reconciliation — Lambda not yet created in AWS"
echo "  ⏭️  pip-audit          — Lambda not yet created in AWS"
echo ""
echo "These 3 will get OBS-1 automatically when their creation scripts are run."
