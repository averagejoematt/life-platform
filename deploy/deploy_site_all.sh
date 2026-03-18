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
echo "  ✓ Homepage sparklines section (weight chart from /api/weight_progress)"
echo "  ✓ 'What Claude Sees' AI brief widget (placeholder until next daily brief run)"
echo "  ✓ /ask/ page frontend (Ask the Platform)"
echo "  ✓ RSS feed at /rss.xml"
echo "  ✓ Story page with detailed writing prompts"
echo "  ✓ Updated sitemap"
echo ""
echo "REMAINING (requires separate deploys):"
echo ""
echo "  A. WIRE /api/ask BACKEND (makes Ask page functional):"
echo "     1. Store API key:"
echo "        aws secretsmanager create-secret --name life-platform/anthropic-api-key \\"
echo "          --secret-string 'sk-ant-...' --region us-west-2"
echo "     2. Add IAM permission to site-api role:"
echo "        aws iam put-role-policy --role-name life-platform-site-api-role \\"
echo "          --policy-name ask-secrets --policy-document '{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"secretsmanager:GetSecretValue\",\"Resource\":\"arn:aws:secretsmanager:us-west-2:205930651321:secret:life-platform/anthropic-api-key-*\"}]}'"
echo "     3. Enable DynamoDB TTL (for rate limit cleanup):"
echo "        aws dynamodb update-time-to-live --table-name life-platform \\"
echo "          --time-to-live-specification 'Enabled=true,AttributeName=ttl' --region us-west-2"
echo "     4. Deploy site-api Lambda with updated code"
echo ""
echo "  B. DEPLOY daily_brief_lambda.py (enables trend sparklines + AI brief excerpt)"
echo "     The Lambda code is updated but needs to be deployed to start writing"
echo "     trends + brief_excerpt to public_stats.json."
echo ""
echo "  C. WRITE /story page content (Matthew only — 5 chapters)"
