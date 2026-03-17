#!/bin/bash
# deploy_sprint4.sh — Deploy Sprint 4 items (v3.7.68)
# BS-11, WEB-CE, BS-BM2 (site pages + site_api), BS-14 (design doc only)
set -e

cd ~/Documents/Claude/life-platform
echo "=== Sprint 4 Deploy (v3.7.68) ==="
echo ""

# ── Step 1: Deploy site_api Lambda (us-east-1, direct zip) ──
echo "[1/3] Deploying site_api Lambda (us-east-1)..."
zip -j /tmp/site_api_deploy.zip lambdas/site_api_lambda.py
aws lambda update-function-code \
    --function-name life-platform-site-api \
    --zip-file fileb:///tmp/site_api_deploy.zip \
    --region us-east-1 \
    --no-cli-pager > /dev/null
echo "✅ site_api Lambda deployed (us-east-1)."
echo ""

# ── Step 2: Sync new site pages to S3 ──
echo "[2/3] Syncing new site pages to S3..."
aws s3 sync site/ s3://matthew-life-platform/site/ \
    --exclude "*.DS_Store" \
    --region us-west-2 \
    --no-cli-pager
echo "✅ Site pages synced to S3."
echo ""

# ── Step 3: Invalidate CloudFront cache for new pages ──
echo "[3/3] Invalidating CloudFront cache..."
aws cloudfront create-invalidation \
    --distribution-id E3S424OXQZ8NBE \
    --paths "/live/*" "/explorer/*" "/biology/*" "/api/timeline" "/api/correlations" "/api/genome_risks" \
    --region us-east-1 \
    --no-cli-pager > /dev/null
echo "✅ CloudFront invalidation submitted."
echo ""

echo "=== Sprint 4 Deploy complete! ==="
echo ""
echo "New pages live at:"
echo "  https://averagejoematt.com/live/        (BS-11 Transformation Timeline)"
echo "  https://averagejoematt.com/explorer/     (WEB-CE Correlation Explorer)"
echo "  https://averagejoematt.com/biology/      (BS-BM2 Genome Dashboard)"
echo ""
echo "New API endpoints:"
echo "  /api/timeline"
echo "  /api/correlations"
echo "  /api/genome_risks"
echo ""
echo "Next steps:"
echo "  1. git add -A && git commit -m 'v3.7.68: Sprint 4 complete — BS-11 WEB-CE BS-BM2 BS-14' && git push"
