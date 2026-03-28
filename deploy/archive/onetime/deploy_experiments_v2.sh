#!/usr/bin/env bash
# deploy_experiments_v2.sh — Lab v2 page deployment (HTML only, no config changes)
set -euo pipefail

BUCKET="matthew-life-platform"
REGION="us-west-2"
DIST_ID="E3S424OXQZ8NBE"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Lab v2 Deployment ==="

echo "[1/2] Syncing site to S3..."
aws s3 sync "$PROJECT_ROOT/site/" "s3://$BUCKET/site/" \
  --region "$REGION" --no-cli-pager \
  --exclude ".DS_Store" --exclude "*.swp"
echo "  Done"

echo "[2/2] Invalidating CloudFront..."
aws cloudfront create-invalidation \
  --distribution-id "$DIST_ID" \
  --paths "/experiments/*" \
  --region us-east-1 --no-cli-pager
echo "  Done"

echo ""
echo "=== Lab v2 deployed ==="
echo "Verify: https://averagejoematt.com/experiments/"
