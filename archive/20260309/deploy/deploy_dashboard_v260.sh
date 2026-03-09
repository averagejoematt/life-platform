#!/bin/bash
# Deploy Dashboard v2.60.0 — Character Sheet Radar Chart
# Uploads updated index.html to S3 dashboard

set -euo pipefail

BUCKET="matthew-life-platform"
DASHBOARD_DIR="$HOME/Documents/Claude/life-platform/lambdas/dashboard"

echo "=== Dashboard v2.60.0: Character Sheet Radar Chart ==="
echo ""

# Upload dashboard HTML
echo "[1/2] Uploading index.html..."
aws s3 cp "$DASHBOARD_DIR/index.html" "s3://$BUCKET/dashboard/index.html" \
  --content-type "text/html" \
  --cache-control "max-age=300"

echo "[2/2] Invalidating CloudFront cache (if distribution exists)..."
DIST_ID=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Aliases.Items, 'dash.averagejoematt.com')].Id" --output text 2>/dev/null || echo "")
if [ -n "$DIST_ID" ] && [ "$DIST_ID" != "None" ]; then
  aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/index.html" > /dev/null
  echo "  CloudFront invalidation created"
else
  echo "  No CloudFront distribution found — S3 will serve directly"
fi

echo ""
echo "✅ Dashboard deployed with Character Sheet radar chart"
echo "   View: https://dash.averagejoematt.com"
