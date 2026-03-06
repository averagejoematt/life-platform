#!/bin/bash
set -euo pipefail
BUCKET="matthew-life-platform"
DIST="EM5NPX6NJN095"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Uploading fixed dashboard index.html (absolute sprite URLs)..."
aws s3 cp "$ROOT/lambdas/dashboard/index.html" \
  "s3://$BUCKET/dashboard/index.html" \
  --content-type "text/html" \
  --cache-control "no-cache"

echo "Invalidating CloudFront..."
INV=$(aws cloudfront create-invalidation \
  --distribution-id "$DIST" \
  --paths "/dashboard/index.html" \
  --query 'Invalidation.Id' --output text)
echo "  Invalidation: $INV"

echo "✅ Done — refresh dash.averagejoematt.com"
