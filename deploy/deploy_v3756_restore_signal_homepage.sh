#!/bin/bash
# deploy_v3756_restore_signal_homepage.sh
# Restores the Signal-aesthetic homepage (averagejoematt-site/) as the live site.
# Also fixes the /api/subscribe route (CDK LifePlatformWeb).
#
# What happened: v3.7.55 wrote site/index.html (minimal amber design) to S3 /site/
# and the CloudFront origin for E3S424OXQZ8NBE points to /site.
# The real Signal homepage lives in averagejoematt-site/ and was the live site before.
# This script: (1) re-deploys the Signal homepage to S3 root, (2) redeploys CDK.
#
# Usage: bash deploy/deploy_v3756_restore_signal_homepage.sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SITE_REPO="/Users/matthewwalker/Documents/Claude/averagejoematt-site"
BUCKET="matthew-life-platform"
DIST_ID="E3S424OXQZ8NBE"

echo "=== Restore Signal homepage + wire /api/subscribe ==="
echo ""

# ── 1. Sync Signal site to S3 root (this IS the site, served from /)
echo "[1/4] Syncing averagejoematt-site/ to S3 root..."
aws s3 sync "$SITE_REPO/" "s3://$BUCKET/" \
  --exclude "*.DS_Store" \
  --exclude ".git/*" \
  --exclude "*.md" \
  --cache-control "max-age=300" \
  --delete
echo "      ✓ Signal site synced"
echo ""

# ── 2. CDK LifePlatformWeb — fix DLQ region issue + wire subscriber origin
echo "[2/4] CDK deploy LifePlatformWeb..."
cd "$ROOT/cdk"
source .venv/bin/activate
npx cdk deploy LifePlatformWeb --require-approval never
cd "$ROOT"
echo "      ✓ LifePlatformWeb deployed"
echo ""

# ── 3. Post-CDK smoke
echo "[3/4] Smoke test..."
bash deploy/post_cdk_reconcile_smoke.sh
echo ""

# ── 4. CloudFront invalidation
echo "[4/4] CloudFront invalidation..."
aws cloudfront create-invalidation \
  --distribution-id "$DIST_ID" \
  --paths "/*" \
  --query "Invalidation.{Id:Id,Status:Status}" \
  --output table
echo ""

echo "=== Done ==="
echo ""
echo "Live at: https://averagejoematt.com"
echo ""
echo "Test subscribe: enter email in hero form at https://averagejoematt.com"
echo "Expected: button → 'check your inbox ✓'"
