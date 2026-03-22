#!/usr/bin/env bash
# deploy/deploy_daily_brief_fix.sh
# Deploys the patched daily_brief_lambda.py (D1-FIX + hardcode removal)
# Run from repo root: bash deploy/deploy_daily_brief_fix.sh

set -e

FUNCTION_NAME="daily-brief"
REGION="us-west-2"
TMPZIP=/tmp/daily_brief_fix.zip

echo "[deploy] Packaging ${FUNCTION_NAME}..."
cd "$(dirname "$0")/.."

rm -f "$TMPZIP"

zip -j "$TMPZIP" \
  lambdas/daily_brief_lambda.py \
  lambdas/html_builder.py \
  lambdas/ai_calls.py \
  lambdas/output_writers.py \
  lambdas/site_writer.py \
  lambdas/board_loader.py \
  lambdas/insight_writer.py \
  lambdas/sick_day_checker.py \
  lambdas/ai_output_validator.py \
  lambdas/platform_logger.py \
  lambdas/retry_utils.py \
  lambdas/scoring_engine.py \
  lambdas/ingestion_validator.py

echo "[deploy] Updating Lambda function code..."
aws lambda update-function-code \
  --function-name "$FUNCTION_NAME" \
  --zip-file fileb://"$TMPZIP" \
  --region "$REGION" \
  --no-cli-pager

echo "[deploy] Waiting for update to complete..."
sleep 8

STATUS=$(aws lambda get-function-configuration \
  --function-name "$FUNCTION_NAME" \
  --region "$REGION" \
  --query "LastUpdateStatus" \
  --output text \
  --no-cli-pager)

echo "[deploy] Status: $STATUS"

if [ "$STATUS" = "Successful" ]; then
  echo "[deploy] ✅ Done. D1-FIX + hardcode removal deployed to ${FUNCTION_NAME}."
else
  echo "[deploy] ⚠ Status is '${STATUS}' — check CloudWatch logs."
fi
