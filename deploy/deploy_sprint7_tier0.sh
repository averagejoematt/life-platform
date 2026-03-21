#!/bin/bash
# deploy_sprint7_tier0.sh — Deploy Sprint 7 Tier 0 website changes
# Run from project root: bash deploy/deploy_sprint7_tier0.sh
#
# Changes deployed:
#   WR-28: CloudFront 404/403 error response fix (CDK change — needs cdk deploy)
#   WR-29: Fixed /site/public_stats.json double-path bug on homepage + about
#   WR-30: Real daily brief excerpt on homepage (replaces "coming soon")
#   WR-31: "New here? Start with the story" CTA on homepage
#   WR-32: Newsletter sample page at /journal/sample/
#   WR-35: Cost transparency section on /platform/
#   WR-37: Scoring methodology transparency on /character/
#   WR-40: Response safety filter on /api/ask (Lambda deploy needed)
#   Plus: Updated 404.html, sitemap.xml, sample links across pages

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=== Sprint 7 Tier 0 Deploy ==="
echo ""

# 1. Sync site to S3
echo "[1/4] Syncing site/ to S3..."
aws s3 sync site/ s3://matthew-life-platform/site/ \
  --delete \
  --exclude ".DS_Store" \
  --exclude "data/*" \
  --cache-control "max-age=300" \
  --region us-west-2
echo "  ✓ Site synced"

# 2. Deploy site-api Lambda (WR-40: safety filter)
# NOTE: site-api is in us-east-1 (CDK WebStack), not us-west-2.
echo ""
echo "[2/4] Deploying site-api Lambda (us-east-1, WR-40 safety filter)..."
TMPZIP="/tmp/site_api_deploy_$$.zip"
cp lambdas/site_api_lambda.py /tmp/site_api_lambda.py
cd /tmp && zip -j "$TMPZIP" site_api_lambda.py > /dev/null
aws lambda update-function-code \
  --function-name life-platform-site-api \
  --zip-file "fileb://$TMPZIP" \
  --region us-east-1 \
  --output text --query 'FunctionArn'
rm -f "$TMPZIP" /tmp/site_api_lambda.py
cd "$PROJECT_ROOT"
echo "  ✓ site-api Lambda deployed (us-east-1)"

# 3. Invalidate CloudFront cache
echo ""
echo "[3/4] Invalidating CloudFront cache..."
aws cloudfront create-invalidation \
  --distribution-id E3S424OXQZ8NBE \
  --paths "/*" \
  --output text --query 'Invalidation.Id'
echo "  ✓ CloudFront invalidation started"

# 4. CDK deploy for WR-28 (CloudFront error response fix)
echo ""
echo "[4/4] CDK deploy for WR-28 (CloudFront 404/403 fix)..."
echo "  Run manually:"
echo "    cd cdk && source .venv/bin/activate && npx cdk deploy LifePlatformWeb --require-approval never"
echo ""
echo "=== Deploy complete (except CDK step) ==="
echo ""
echo "Verify:"
echo "  curl -sI https://averagejoematt.com/story/ | head -5"
echo "  curl -s https://averagejoematt.com/public_stats.json | head -3"
echo "  curl -s https://averagejoematt.com/journal/sample/ | head -5"
