#!/usr/bin/env bash
# deploy_challenges_overhaul.sh — Arena v2 deployment
set -euo pipefail

BUCKET="matthew-life-platform"
REGION="us-west-2"
DIST_ID="E3S424OXQZ8NBE"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Arena v2 Deployment ==="

echo "[1/4] Uploading challenges catalog to S3..."
aws s3 cp "$PROJECT_ROOT/seeds/challenges_catalog.json" \
  "s3://$BUCKET/site/config/challenges_catalog.json" \
  --content-type "application/json" \
  --region "$REGION" --no-cli-pager
echo "  Done"

echo "[2/4] Deploying site-api Lambda..."
bash "$PROJECT_ROOT/deploy/deploy_lambda.sh" life-platform-site-api "$PROJECT_ROOT/lambdas/site_api_lambda.py"
echo "  Done"
sleep 10

echo "[3/4] Syncing site to S3..."
aws s3 sync "$PROJECT_ROOT/site/" "s3://$BUCKET/site/" \
  --region "$REGION" --no-cli-pager \
  --exclude ".DS_Store" --exclude "*.swp"
echo "  Done"

echo "[4/4] Invalidating CloudFront..."
aws cloudfront create-invalidation \
  --distribution-id "$DIST_ID" \
  --paths "/challenges/*" "/api/challenge_catalog" "/api/challenges" \
  --region us-east-1 --no-cli-pager
echo "  Done"

echo ""
echo "=== Arena v2 deployed ==="
echo "Verify: https://averagejoematt.com/challenges/"
