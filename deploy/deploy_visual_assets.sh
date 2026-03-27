#!/bin/bash
# deploy_visual_assets.sh — Syncs visual assets + updated pages to S3/CloudFront
# Run from project root: bash deploy/deploy_visual_assets.sh

set -euo pipefail

BUCKET="matthew-life-platform"
DIST_ID="E3S424OXQZ8NBE"

echo "━━━ Syncing site assets to S3 ━━━"

# Sync icons
echo "  → Icons..."
aws s3 sync site/assets/icons/custom/ s3://${BUCKET}/site/assets/icons/custom/ \
  --content-type "image/svg+xml" \
  --cache-control "public, max-age=86400" \
  --no-cli-pager

# Sync badges
echo "  → Badges..."
aws s3 sync site/assets/img/badges/ s3://${BUCKET}/site/assets/img/badges/ \
  --content-type "image/svg+xml" \
  --cache-control "public, max-age=86400" \
  --no-cli-pager

# Sync updated HTML pages
echo "  → Updated pages..."
for PAGE in achievements/index.html live/index.html character/index.html; do
  aws s3 cp "site/${PAGE}" "s3://${BUCKET}/site/${PAGE}" \
    --content-type "text/html" \
    --cache-control "public, max-age=300" \
    --no-cli-pager
  echo "    ✓ ${PAGE}"
done

echo ""
echo "━━━ Invalidating CloudFront cache ━━━"
INVALIDATION_ID=$(aws cloudfront create-invalidation \
  --distribution-id ${DIST_ID} \
  --paths "/assets/icons/custom/*" "/assets/img/badges/*" "/achievements/*" "/live/*" "/character/*" \
  --query 'Invalidation.Id' --output text --no-cli-pager)

echo "  ✓ Invalidation: ${INVALIDATION_ID}"
echo ""
echo "━━━ Done! Assets should be live within 1-2 minutes. ━━━"
echo "  Verify: https://averagejoematt.com/achievements/"
echo "  Verify: https://averagejoematt.com/live/"
echo "  Verify: https://averagejoematt.com/character/"
