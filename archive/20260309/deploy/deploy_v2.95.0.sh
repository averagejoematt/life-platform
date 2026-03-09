#!/usr/bin/env bash
# v2.95.0: Deploy quick-win hardening batch
# Deploys updated email Lambdas (AI-1 health disclaimers)
# Run the infra scripts separately (they're idempotent one-shots):
#   bash deploy/cost1_s3_lifecycle.sh
#   bash deploy/sec4_api_gateway_throttle.sh
#   bash deploy/iam2_access_analyzer.sh
#   bash deploy/maint3_cleanup.sh  (review first!)

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REGION="us-west-2"

deploy_lambda() {
  local NAME="$1"
  local HANDLER_FILE="$2"
  local EXTRAS="${3:-}"  # optional extra files

  echo ""
  echo "── Deploying $NAME ──"
  cd /tmp
  rm -rf deploy_tmp && mkdir deploy_tmp
  cp "$ROOT/lambdas/$HANDLER_FILE" deploy_tmp/
  cp "$ROOT/lambdas/board_loader.py" deploy_tmp/ 2>/dev/null || true
  cp "$ROOT/lambdas/retry_utils.py" deploy_tmp/ 2>/dev/null || true
  cp "$ROOT/lambdas/insight_writer.py" deploy_tmp/ 2>/dev/null || true
  for f in $EXTRAS; do
    cp "$ROOT/lambdas/$f" deploy_tmp/ 2>/dev/null || true
  done
  cd deploy_tmp
  zip -q -r "/tmp/${NAME}.zip" .
  aws lambda update-function-code \
    --function-name "$NAME" \
    --zip-file "fileb:///tmp/${NAME}.zip" \
    --region "$REGION" \
    --output text --query 'FunctionName'
  echo "  ✅ $NAME deployed"
  sleep 10
}

echo "=== v2.95.0 Hardening Batch: AI-1 Health Disclaimers ==="

# Daily Brief (uses html_builder.py — the primary change)
deploy_lambda "daily-brief" "daily_brief_lambda.py" \
  "html_builder.py ai_calls.py output_writers.py scoring_engine.py character_engine.py enrichment_lambda.py"

# Weekly Digest
deploy_lambda "weekly-digest" "weekly_digest_lambda.py" \
  "ai_calls.py output_writers.py scoring_engine.py character_engine.py"

# Monday Compass
deploy_lambda "monday-compass" "monday_compass_lambda.py"

# Saturday Nutrition Review
deploy_lambda "nutrition-review" "nutrition_review_lambda.py"

# Wednesday Chronicle
deploy_lambda "wednesday-chronicle" "wednesday_chronicle_lambda.py"

# The Weekly Plate
deploy_lambda "weekly-plate" "weekly_plate_lambda.py"

# Anomaly Detector
deploy_lambda "anomaly-detector" "anomaly_detector_lambda.py"

echo ""
echo "=== All AI-1 Lambda deploys complete ==="
echo ""
echo "Next — run infra scripts:"
echo "  bash deploy/cost1_s3_lifecycle.sh"
echo "  bash deploy/sec4_api_gateway_throttle.sh"
echo "  bash deploy/iam2_access_analyzer.sh"
echo ""
echo "Then review and run:"
echo "  bash deploy/maint3_cleanup.sh"
