#!/bin/bash
# Deploy Buddy Page v2.60.0 — Character Sheet tile
# Run from: ~/Documents/Claude/life-platform/

set -e

echo "🚀 Deploying Buddy Page v2.60.0 (Character Sheet tile)..."

# Upload buddy page
aws s3 cp lambdas/buddy/index.html s3://matthew-life-platform/buddy/index.html \
  --content-type "text/html" \
  --cache-control "max-age=300"

echo "✅ Buddy page uploaded to S3"

# Invalidate CloudFront if distribution exists
DIST_ID=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Aliases.Items, 'buddy.averagejoematt.com')].Id" --output text 2>/dev/null || true)
if [ -n "$DIST_ID" ] && [ "$DIST_ID" != "None" ]; then
  aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/index.html" > /dev/null
  echo "✅ CloudFront cache invalidated"
else
  echo "ℹ️  No CloudFront distribution found for buddy — S3 serving directly"
fi

echo ""
echo "🎮 Buddy page deployed with Character Sheet tile!"
echo "   View at: https://buddy.averagejoematt.com"
