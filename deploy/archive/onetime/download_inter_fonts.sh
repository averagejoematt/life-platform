#!/usr/bin/env bash
# download_inter_fonts.sh — Download and upload Inter woff2 files for self-hosting
# Design Brief DB-07: Inter font for body-signal pages
# Run from project root: bash deploy/download_inter_fonts.sh

set -euo pipefail
cd "$(dirname "$0")/.."

FONT_DIR="site/assets/fonts"
S3_BUCKET="matthew-life-platform"
REGION="us-west-2"

echo "=== Downloading Inter font files ==="

# Inter 400 (Regular)
curl -sL "https://fonts.gstatic.com/s/inter/v18/UcCO3FwrK3iLTeHuS_nVMrMxCp50SjIw2boKoduKmMEVuLyfAZ9hiA.woff2" \
  -o "$FONT_DIR/inter-400.woff2"
echo "✓ inter-400.woff2"

# Inter 500 (Medium)
curl -sL "https://fonts.gstatic.com/s/inter/v18/UcCO3FwrK3iLTeHuS_nVMrMxCp50SjIw2boKoduKmMEVuI6fAZ9hiA.woff2" \
  -o "$FONT_DIR/inter-500.woff2"
echo "✓ inter-500.woff2"

# Inter 600 (Semi-bold)
curl -sL "https://fonts.gstatic.com/s/inter/v18/UcCO3FwrK3iLTeHuS_nVMrMxCp50SjIw2boKoduKmMEVuGKYAZ9hiA.woff2" \
  -o "$FONT_DIR/inter-600.woff2"
echo "✓ inter-600.woff2"

echo ""
echo "=== Uploading to S3 ==="
aws s3 cp "$FONT_DIR/inter-400.woff2" "s3://$S3_BUCKET/site/assets/fonts/inter-400.woff2" --region "$REGION"
aws s3 cp "$FONT_DIR/inter-500.woff2" "s3://$S3_BUCKET/site/assets/fonts/inter-500.woff2" --region "$REGION"
aws s3 cp "$FONT_DIR/inter-600.woff2" "s3://$S3_BUCKET/site/assets/fonts/inter-600.woff2" --region "$REGION"

echo ""
echo "=== Done ==="
echo "Inter 400/500/600 downloaded to $FONT_DIR and uploaded to S3."
echo "Now invalidate CloudFront: aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths '/assets/fonts/*' --region us-east-1"
