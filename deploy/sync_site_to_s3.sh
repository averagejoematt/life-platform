#!/usr/bin/env bash
# sync_site_to_s3.sh — Sync site/ to S3 and invalidate CloudFront
#
# Handles three categories of files with appropriate cache-control headers:
#   - HTML pages:     max-age=300   (5 min — allows quick content updates)
#   - CSS/JS assets:  max-age=86400 (1 day — invalidate on deploy)
#   - Data JSON:      max-age=86400 (1 day — Lambda overwrites daily anyway)
#   - Everything else: max-age=3600
#
# Usage:
#   bash deploy/sync_site_to_s3.sh
#   bash deploy/sync_site_to_s3.sh --dry-run   (preview only)
#
# ⚠️  Cost warning: CloudFront invalidations are free for the first 1000 paths/month.
#     This script invalidates /* which counts as 1 wildcard path. Safe.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

BUCKET="matthew-life-platform"
SITE_DIR="/Users/matthewwalker/Documents/Claude/life-platform/site"
S3_PREFIX="site"
REGION="us-west-2"
DRY_RUN="${1:-}"

# Find CloudFront distribution ID for averagejoematt.com
CF_DIST_ID=$(aws cloudformation describe-stacks \
  --stack-name LifePlatformWeb \
  --region us-east-1 \
  --query "Stacks[0].Outputs[?OutputKey=='AmjDistributionId'].OutputValue" \
  --output text 2>/dev/null || echo "")

[[ -z "$CF_DIST_ID" ]] && echo "⚠️  CloudFront distribution ID not found — skipping invalidation."

if [[ "$DRY_RUN" == "--dry-run" ]]; then
  echo "DRY RUN — showing what would be synced:"
  aws s3 sync "$SITE_DIR/" "s3://$BUCKET/$S3_PREFIX/" \
    --exclude "data/*" \
    --exclude ".git/*" \
    --exclude ".DS_Store" \
    --dryrun \
    --region "$REGION"
  echo "(dry run complete, no changes made)"
  exit 0
fi

echo "=== Syncing averagejoematt-site → s3://$BUCKET/$S3_PREFIX/ ==="
echo ""

# ── HTML pages (short TTL — supports fast content updates) ───────────────────
echo "→ HTML files (max-age=300)..."
aws s3 sync "$SITE_DIR/" "s3://$BUCKET/$S3_PREFIX/" \
  --exclude "*" \
  --include "*.html" \
  --cache-control "max-age=300, public" \
  --content-type "text/html; charset=utf-8" \
  --region "$REGION"

# ── CSS / JS assets (long TTL — update filenames when content changes) ────────
echo "→ CSS files (max-age=31536000)..."
aws s3 sync "$SITE_DIR/assets/" "s3://$BUCKET/$S3_PREFIX/assets/" \
  --exclude "*.map" \
  --cache-control "max-age=31536000, public, immutable" \
  --region "$REGION"

# ── Data JSON (daily Lambda overwrites these, so 24h TTL is fine) ─────────────
echo "→ Data JSON (max-age=86400)..."
aws s3 sync "$SITE_DIR/data/" "s3://$BUCKET/$S3_PREFIX/data/" \
  --cache-control "max-age=86400, public" \
  --content-type "application/json" \
  --region "$REGION"

# ── Everything else (DEPLOY.md etc) ──────────────────────────────────────────
echo "→ Other files..."
aws s3 sync "$SITE_DIR/" "s3://$BUCKET/$S3_PREFIX/" \
  --exclude "*.html" \
  --exclude "assets/*" \
  --exclude "data/*" \
  --exclude ".git/*" \
  --exclude ".DS_Store" \
  --cache-control "max-age=3600, public" \
  --region "$REGION"

echo ""
echo "✅ S3 sync complete."

# ── CloudFront invalidation ───────────────────────────────────────────────────
if [[ -n "$CF_DIST_ID" ]]; then
  echo "Invalidating CloudFront distribution $CF_DIST_ID..."
  INVALIDATION_ID=$(aws cloudfront create-invalidation \
    --distribution-id "$CF_DIST_ID" \
    --paths "/*" \
    --query "Invalidation.Id" \
    --output text)
  echo "✅ Invalidation created: $INVALIDATION_ID (takes ~30s to propagate)"
fi

echo ""
echo "Site live at: https://averagejoematt.com"
