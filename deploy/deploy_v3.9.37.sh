#!/bin/bash
# deploy_v3.9.37.sh — Product Board Pre-Launch Punch List (all 23 items)
# Run from project root: bash deploy/deploy_v3.9.37.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "═══════════════════════════════════════════════════════════"
echo "  v3.9.37 — Product Board Pre-Launch Punch List"
echo "  23 items: bug fixes, UX, content, features"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Step 1: Run the comprehensive Python patch
echo "▶ Running Python patch script..."
python3 deploy/patch_v3.9.37_product_board.py
echo ""

# Step 2: Sync site to S3
echo "▶ Syncing site to S3..."
# CRITICAL: exclude dynamically-generated files that live in S3 but not in local site/
aws s3 sync site/ s3://matthew-life-platform/site/ \
  --delete \
  --exclude ".DS_Store" \
  --exclude "public_stats.json" \
  --exclude "config/experiment_library.json" \
  --exclude "config/challenges_catalog.json" \
  --exclude "data/character_stats.json" \
  --cache-control "public, max-age=300" \
  --region us-west-2

# Step 3: Set long cache on static assets
echo "▶ Setting asset cache headers..."
aws s3 sync site/assets/ s3://matthew-life-platform/site/assets/ \
  --cache-control "public, max-age=31536000, immutable" \
  --region us-west-2

# Step 4: Set no-cache on HTML files
echo "▶ Setting HTML no-cache..."
for f in $(find site -name "*.html" -type f); do
  KEY="site/${f#site/}"
  aws s3 cp "s3://matthew-life-platform/$KEY" "s3://matthew-life-platform/$KEY" \
    --cache-control "public, max-age=60" \
    --content-type "text/html" \
    --metadata-directive REPLACE \
    --region us-west-2 2>/dev/null || true
done

# Step 5: Invalidate CloudFront
echo "▶ Invalidating CloudFront..."
aws cloudfront create-invalidation \
  --distribution-id E3S424OXQZ8NBE \
  --paths "/*" \
  --region us-east-1 \
  --no-cli-pager

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  ✅ v3.9.37 deployed!"
echo ""
echo "  Manual follow-ups:"
echo "  1. Check SES subscriber confirmation (Item 4)"
echo "  2. Schedule: bash deploy/warmup_lambdas.sh for March 31 11:55 PM"  
echo "  3. Run pipeline manually March 31 night"
echo "  4. Test: curl -s https://averagejoematt.com/start/ (should redirect)"
echo "  5. Test: curl -s https://averagejoematt.com/journal/ (should redirect)"
echo "  6. Test: Visit /subscribe/confirm/ page"
echo "  7. Test: Dark/light toggle in nav"
echo "═══════════════════════════════════════════════════════════"
