#!/bin/bash
# Deploy OBS-1 + AI-3 rollout to remaining email Lambdas
# v3.1.7: OBS-1 (platform_logger) + AI-3 (ai_output_validator) wired into all email Lambdas
# Lambdas: wednesday-chronicle, nutrition-review, monday-compass, monthly-digest, weekly-plate, anomaly-detector

set -e
REGION="us-west-2"
LAYER_ARN=$(aws lambda list-layers --region $REGION --query "Layers[?LayerName=='life-platform-shared'].LatestMatchingVersion.LayerVersionArn" --output text)

# Parallel arrays (bash 3.2 compatible — no declare -A)
LAMBDA_NAMES=(
  "wednesday-chronicle"
  "nutrition-review"
  "monday-compass"
  "monthly-digest"
  "weekly-plate"
  "anomaly-detector"
)
LAMBDA_FILES=(
  "lambdas/wednesday_chronicle_lambda.py"
  "lambdas/nutrition_review_lambda.py"
  "lambdas/monday_compass_lambda.py"
  "lambdas/monthly_digest_lambda.py"
  "lambdas/weekly_plate_lambda.py"
  "lambdas/anomaly_detector_lambda.py"
)

cd "$(dirname "$0")/.."

for i in "${!LAMBDA_NAMES[@]}"; do
  FUNC_NAME="${LAMBDA_NAMES[$i]}"
  SOURCE_FILE="${LAMBDA_FILES[$i]}"
  echo "━━━ Deploying $FUNC_NAME ━━━"
  bash deploy/deploy_lambda.sh "$FUNC_NAME" "$SOURCE_FILE"
  echo "✅ $FUNC_NAME deployed"
  echo "Waiting 10s..."
  sleep 10
done

echo ""
echo "✅ All 6 email Lambdas deployed with OBS-1 + AI-3"
echo "Check CloudWatch logs for [AI-3] and correlation_id fields to confirm."
