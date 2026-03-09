#!/bin/bash
# Deploy OBS-1 + AI-3 rollout to remaining email Lambdas
# v3.1.7: OBS-1 (platform_logger) + AI-3 (ai_output_validator) wired into all email Lambdas
# Lambdas: wednesday-chronicle, nutrition-review, monday-compass, monthly-digest, weekly-plate, anomaly-detector

set -e
REGION="us-west-2"
LAYER_ARN=$(aws lambda list-layers --region $REGION --query "Layers[?LayerName=='life-platform-shared'].LatestMatchingVersion.LayerVersionArn" --output text)

LAMBDAS=(
  "wednesday-chronicle:lambdas/wednesday_chronicle_lambda.py:wednesday_chronicle_lambda"
  "nutrition-review:lambdas/nutrition_review_lambda.py:nutrition_review_lambda"
  "monday-compass:lambdas/monday_compass_lambda.py:monday_compass_lambda"
  "monthly-digest:lambdas/monthly_digest_lambda.py:monthly_digest_lambda"
  "weekly-plate:lambdas/weekly_plate_lambda.py:weekly_plate_lambda"
  "anomaly-detector:lambdas/anomaly_detector_lambda.py:anomaly_detector_lambda"
)

cd "$(dirname "$0")/.."

for entry in "${LAMBDAS[@]}"; do
  IFS=: read -r FUNC_NAME SOURCE_FILE HANDLER_BASE <<< "$entry"
  echo "━━━ Deploying $FUNC_NAME ━━━"
  bash deploy/deploy_lambda.sh "$FUNC_NAME"
  echo "✅ $FUNC_NAME deployed"
  echo "Waiting 10s..."
  sleep 10
done

echo ""
echo "✅ All 6 email Lambdas deployed with OBS-1 + AI-3"
echo "Check CloudWatch logs for [AI-3] and correlation_id fields to confirm."
