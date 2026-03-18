#!/bin/bash
# deploy_site_phase2.sh — Deploy all Phase 2 website enhancements
set -e

PROJ="/Users/matthewwalker/Documents/Claude/life-platform"
cd "$PROJ"

echo "=== Phase 2: Website Enhancement Deploy ==="
echo ""

echo "--- Step 1: Fix OG tags + nav consistency ---"
source .venv/bin/activate
python3 deploy/fix_site_meta.py --apply

echo ""
echo "--- Step 2: Regenerate OG image ---"
python3 deploy/generate_og_image.py --from-s3

echo ""
echo "--- Step 3: Inline latest stats ---"
python3 deploy/inline_stats.py --apply --from-s3

echo ""
echo "--- Step 4: Sync ALL site files to S3 ---"
deactivate 2>/dev/null || true
aws s3 sync site/ s3://matthew-life-platform/site/ \
  --exclude "data/*" \
  --exclude "DEPLOY.md" \
  --cache-control "max-age=3600" \
  --region us-west-2

echo ""
echo "--- Step 5: Invalidate CloudFront ---"
aws cloudfront create-invalidation \
  --distribution-id E3S424OXQZ8NBE \
  --paths "/*" \
  --no-cli-pager

echo ""
echo "=== DEPLOY COMPLETE ==="
echo ""
echo "Deployed:"
echo "  ✓ N=1 disclaimers on explorer, experiments, biology, character"
echo "  ✓ OG/Twitter meta tags on all sub-pages"
echo "  ✓ Nav + footer consistency across all pages"
echo "  ✓ /ask/ page (Ask the Platform — frontend ready)"
echo "  ✓ Updated sitemap with /ask/"
echo ""
echo "REMAINING (manual steps):"
echo "  1. /api/ask endpoint: Integrate lambdas/ask_endpoint.py into site_api_lambda.py"
echo "     - Add Anthropic API key to Secrets Manager: life-platform/anthropic-api-key"
echo "     - Add secretsmanager:GetSecretValue IAM permission"
echo "     - Add '/api/ask': handle_ask to ROUTES dict"
echo "     - Deploy site-api Lambda"
echo "  2. Homepage sparklines: Next session (requires expanded public_stats.json)"
echo "  3. Write /story page content (5 chapters — Matthew only)"
