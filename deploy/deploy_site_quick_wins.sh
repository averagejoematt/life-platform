#!/bin/bash
# deploy_site_quick_wins.sh — One-shot deploy for website review quick wins
set -e

PROJ="/Users/matthewwalker/Documents/Claude/life-platform"
cd "$PROJ"

echo "=== Step 1: Install Pillow in project venv ==="
source .venv/bin/activate
pip install Pillow -q
echo "✓ Pillow installed"

echo ""
echo "=== Step 2: Generate OG image ==="
python3 deploy/generate_og_image.py --from-s3
echo "✓ OG image generated"

echo ""
echo "=== Step 3: Inline stats into HTML ==="
python3 deploy/inline_stats.py --apply --from-s3
echo "✓ Stats inlined"

echo ""
echo "=== Step 4: Sync site to S3 ==="
deactivate 2>/dev/null || true
aws s3 sync site/ s3://matthew-life-platform/site/ \
  --exclude "data/*" \
  --cache-control "max-age=3600" \
  --region us-west-2
echo "✓ S3 sync complete"

echo ""
echo "=== Step 5: Invalidate CloudFront ==="
aws cloudfront create-invalidation \
  --distribution-id E3S424OXQZ8NBE \
  --paths "/*" \
  --no-cli-pager
echo "✓ CloudFront invalidation started"

echo ""
echo "=== DONE ==="
echo "Remaining manual step: Configure CloudFront 404 error page in the console"
echo "  Distribution → Error Pages → Create → 404 → /404.html"
