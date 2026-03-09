#!/bin/bash
# Deploy radar chart fix — wider viewBox + readable labels
# v2.65.0 → v2.65.1
set -euo pipefail

echo "=== Deploying radar chart fix ==="

# 1. Upload updated dashboard HTML
echo "[1/2] Uploading dashboard index.html..."
aws s3 cp ~/Documents/Claude/life-platform/lambdas/dashboard/index.html \
  s3://matthew-life-platform/dashboard/index.html \
  --content-type "text/html" \
  --cache-control "max-age=300"

# 2. Invalidate CloudFront cache
echo "[2/2] Invalidating CloudFront (dashboard)..."
aws cloudfront create-invalidation \
  --distribution-id EM5NPX6NJN095 \
  --paths "/index.html" \
  --query 'Invalidation.Id' --output text

echo ""
echo "=== Done! Radar chart fix deployed ==="
echo "Changes:"
echo "  - SVG viewBox: 240x240 → 300x290 (labels no longer clipped)"
echo "  - Labels: Sleep, Move, Nutrition, Metabolic, Mind, Social, Habits"
echo "  - Label distance: maxR+16 → maxR+22 (more breathing room)"
echo "  - Badge positions: adjusted for new center point"
echo ""
echo "Verify at: https://dash.averagejoematt.com/"
