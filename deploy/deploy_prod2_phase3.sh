#!/bin/bash
# PROD-2 Phase 3: Deploy Lambdas + sync HTML files after S3 path migration
# Run AFTER migrate_s3_paths.sh

set -euo pipefail

BUCKET="matthew-life-platform"
REGION="us-west-2"
DASHBOARD_CF_ID="EM5NPX6NJN095"

echo "=== PROD-2 Phase 3: Deploy ==="
echo ""

echo "--- Step 1: Deploy daily-brief Lambda ---"
bash deploy/deploy_lambda.sh daily-brief lambdas/daily_brief_lambda.py \
    --extra-files \
        lambdas/ai_calls.py \
        lambdas/html_builder.py \
        lambdas/output_writers.py \
        lambdas/board_loader.py \
        lambdas/insight_writer.py \
        lambdas/platform_logger.py \
        lambdas/retry_utils.py \
        lambdas/ai_output_validator.py \
        lambdas/character_engine.py \
        lambdas/scoring_engine.py
echo ""
sleep 10

echo "--- Step 2: Deploy dashboard-refresh Lambda ---"
bash deploy/deploy_lambda.sh dashboard-refresh lambdas/dashboard_refresh_lambda.py \
    --extra-files lambdas/platform_logger.py
echo ""
sleep 10

echo "--- Step 3: Sync updated dashboard HTML files to S3 ---"
aws s3 cp lambdas/dashboard/index.html \
    "s3://$BUCKET/dashboard/index.html" \
    --region "$REGION" \
    --content-type "text/html" \
    --cache-control "max-age=300" \
    --no-progress
echo "  ✅ dashboard/index.html"

aws s3 cp lambdas/dashboard/clinical.html \
    "s3://$BUCKET/dashboard/clinical.html" \
    --region "$REGION" \
    --content-type "text/html" \
    --cache-control "max-age=300" \
    --no-progress
echo "  ✅ dashboard/clinical.html"

echo ""
echo "--- Step 4: Sync updated buddy HTML ---"
aws s3 cp lambdas/buddy/index.html \
    "s3://$BUCKET/buddy/index.html" \
    --region "$REGION" \
    --content-type "text/html" \
    --cache-control "max-age=300" \
    --no-progress
echo "  ✅ buddy/index.html"

echo ""
echo "--- Step 5: CloudFront invalidation ---"
aws cloudfront create-invalidation \
    --distribution-id "$DASHBOARD_CF_ID" \
    --paths "/index.html" "/clinical.html" "/matthew/*" \
    --region us-east-1 \
    --no-cli-pager \
    --query "Invalidation.Id" --output text
echo "  ✅ Dashboard CloudFront invalidated"

echo ""
echo "=== Deploy complete ==="
echo ""
echo "Verify:"
echo "  https://dash.averagejoematt.com/         (loads matthew/data.json)"
echo "  https://dash.averagejoematt.com/clinical.html  (loads matthew/clinical.json)"
echo "  https://buddy.averagejoematt.com/        (loads matthew/data.json)"
