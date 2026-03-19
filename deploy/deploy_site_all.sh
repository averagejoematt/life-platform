#!/bin/bash
# deploy_site_all.sh — Full website enhancement deploy (all 5 builds)
set -e

PROJ="/Users/matthewwalker/Documents/Claude/life-platform"
cd "$PROJ"

echo "=== Full Website Enhancement Deploy ==="
echo ""

source .venv/bin/activate

echo "--- 1/6: Fix OG tags + nav consistency ---"
python3 deploy/fix_site_meta.py --apply

echo ""
echo "--- 2/6: Generate RSS feed ---"
python3 deploy/generate_rss.py --apply

echo ""
echo "--- 3/6: Regenerate OG image ---"
python3 deploy/generate_og_image.py --from-s3

echo ""
echo "--- 4/6: Inline latest stats ---"
python3 deploy/inline_stats.py --apply --from-s3

echo ""
echo "--- 5/6: Sync site to S3 ---"
deactivate 2>/dev/null || true
aws s3 sync site/ s3://matthew-life-platform/site/ \
  --exclude "data/*" \
  --exclude "DEPLOY.md" \
  --cache-control "max-age=3600" \
  --region us-west-2

echo ""
echo "--- 6/6: Invalidate CloudFront ---"
aws cloudfront create-invalidation \
  --distribution-id E3S424OXQZ8NBE \
  --paths "/*" \
  --no-cli-pager

echo ""
echo "=== DEPLOY COMPLETE ==="
echo ""
echo "What's live now:"
echo "  ✓ N=1 disclaimers on all data pages"
echo "  ✓ OG/Twitter meta tags on all sub-pages"
echo "  ✓ Nav + footer consistency"
echo "  ✓ Homepage sparklines (weight/HRV/recovery)"
echo "  ✓ 'What Claude Sees' AI brief widget (populates after 10am PT daily-brief)"
echo "  ✓ /ask/ page — Ask the Platform (live, Haiku 4.5 powered)"
echo "  ✓ RSS feed at /rss.xml"
echo "  ✓ Story page with detailed writing prompts"
echo "  ✓ Updated sitemap"
echo "  ✓ Dual-path CTAs (Follow the Journey / See the Platform)"
echo "  ✓ Press section on /about"
echo "  ✓ Scroll entrance animations (reveal.js)"
echo "  ✓ Self-hosted fonts (no Google Fonts ping)"
echo "  ✓ /biology noindex"
echo ""
echo "REMAINING:"
echo "  - /story page content (Matthew — 5 chapters, prompts in place)"
echo "  - WR-17 OG image Function URL 403 (Lambda works, debug needed)"
echo "  - DIST-1 HN/Twitter post (gated on /story)"
