#!/usr/bin/env bash
# deploy/deploy_obs1_remaining.sh
# Deploys all 17 Lambdas patched with OBS-1 structured logging.
# Run AFTER patch_obs1_remaining.py.
#
# Usage: bash deploy/deploy_obs1_remaining.sh

set -euo pipefail

cd "$(dirname "$0")/.."

LAMBDA_NAMES=(
  "apple-health-ingestion"
  "character-sheet-compute"
  "daily-insight-compute"
  "daily-metrics-compute"
  "dashboard-refresh"
  "life-platform-dlq-consumer"
  "dropbox-poll"
  "life-platform-freshness-checker"
  "hypothesis-engine"
  "life-platform-canary"
  "adaptive-mode-compute"
  "insight-email-parser"
  "life-platform-key-rotator"
  "life-platform-qa-smoke"
  # data-export, data-reconciliation, pip-audit not yet created in AWS
)

LAMBDA_FILES=(
  "lambdas/apple_health_lambda.py"
  "lambdas/character_sheet_lambda.py"
  "lambdas/daily_insight_compute_lambda.py"
  "lambdas/daily_metrics_compute_lambda.py"
  "lambdas/dashboard_refresh_lambda.py"
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

# Extra files needed per Lambda (parallel array, empty string = none)
LAMBDA_EXTRAS=(
  ""                                  # apple-health-ingestion
  "lambdas/character_engine.py"       # character-sheet-compute
  ""                                  # daily-insight-compute
  "lambdas/scoring_engine.py"         # daily-metrics-compute
  ""                                  # dashboard-refresh
  ""                                  # life-platform-dlq-consumer
  ""                                  # dropbox-poll
  ""                                  # life-platform-freshness-checker
  ""                                  # hypothesis-engine
  ""                                  # life-platform-canary
  ""                                  # adaptive-mode-compute
  ""                                  # insight-email-parser
  ""                                  # life-platform-key-rotator
  ""                                  # life-platform-qa-smoke
)

echo "=== OBS-1 Lambda Deploy ==="
echo "Deploying ${#LAMBDA_NAMES[@]} Lambdas..."
echo ""

for i in "${!LAMBDA_NAMES[@]}"; do
  FUNC_NAME="${LAMBDA_NAMES[$i]}"
  SOURCE_FILE="${LAMBDA_FILES[$i]}"
  EXTRAS="${LAMBDA_EXTRAS[$i]}"

  echo "━━━ [$((i+1))/${#LAMBDA_NAMES[@]}] Deploying $FUNC_NAME ━━━"

  if [ -n "$EXTRAS" ]; then
    bash deploy/deploy_lambda.sh "$FUNC_NAME" "$SOURCE_FILE" --extra-files $EXTRAS
  else
    bash deploy/deploy_lambda.sh "$FUNC_NAME" "$SOURCE_FILE"
  fi

  echo "✅ $FUNC_NAME deployed"

  if [ $i -lt $((${#LAMBDA_NAMES[@]} - 1)) ]; then
    echo "Waiting 10s..."
    sleep 10
  fi
done

echo ""
echo "=== All ${#LAMBDA_NAMES[@]} OBS-1 Lambdas deployed ==="
echo "Check CloudWatch logs for structured JSON output with source + date/correlation_id fields."
