#!/usr/bin/env bash
# sync_site_to_s3.sh — Build content-hashed assets, sync to S3, invalidate CloudFront
#
# Content-hash strategy (ADR-039 fix):
#   - CSS/JS files get an 8-char MD5 hash in their filename (base.css → base.a1b2c3d4.css)
#   - Hashed files: max-age=31536000 (1 year, immutable) — browser never re-downloads
#   - Original filenames still uploaded with max-age=86400 (fallback for dynamic JS loads)
#   - HTML: max-age=300 (5 min) — references hashed filenames, updates quickly on deploy
#   - Data JSON: max-age=86400 (Lambda overwrites daily)
#
# Usage:
#   bash deploy/sync_site_to_s3.sh
#   bash deploy/sync_site_to_s3.sh --dry-run   (preview only)
#
# ⚠️  Cost: CloudFront invalidations free for first 1000 paths/month (we use 1 wildcard).
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# Regenerate rss.xml from the live published chronicle (best-effort — never block a
# deploy if offline). Keeps the feed's pubDates/lastBuildDate correct on every sync.
if [ "${1:-}" != "--dry-run" ]; then
  python3 "$(dirname "$0")/../scripts/v4_build_rss.py" || echo "  ⚠️  rss build skipped (offline?) — keeping existing site/rss.xml"
fi

BUCKET="matthew-life-platform"
SITE_DIR="$(cd "$(dirname "$0")/.." && pwd)/site"
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

# ── Phase 1: Build content-hashed assets in temp directory ─────────────────
echo "=== Building content-hashed assets ==="
BUILD_DIR=$(mktemp -d)
trap 'rm -rf "$BUILD_DIR"' EXIT
cp -r "$SITE_DIR"/* "$BUILD_DIR/"

# Collect all CSS/JS files to hash
SED_EXPR=""
FILE_COUNT=0

for f in "$BUILD_DIR"/assets/css/*.css "$BUILD_DIR"/assets/js/*.js; do
  [[ -f "$f" ]] || continue
  HASH=$(md5 -q "$f" | cut -c1-8)
  BASE=$(basename "$f")
  NAME="${BASE%.*}"
  EXT="${BASE##*.}"
  HASHED="${NAME}.${HASH}.${EXT}"

  # Create hashed copy alongside the original
  cp "$f" "$(dirname "$f")/${HASHED}"

  # Build sed expression for this file
  SED_EXPR="${SED_EXPR}s|${BASE}|${HASHED}|g;"

  echo "  ${BASE} → ${HASHED}"
  FILE_COUNT=$((FILE_COUNT + 1))
done

echo "  Hashed ${FILE_COUNT} files."

# Update all HTML references to use hashed filenames
if [[ -n "$SED_EXPR" ]]; then
  echo "→ Updating HTML references (excluding /legacy — its assets stay unhashed)..."
  # v4: legacy/ is served verbatim with UNHASHED assets at /legacy/assets/*. Never
  # rewrite its references to the hashed v4 names, or legacy CSS/JS 404s.
  find "$BUILD_DIR" -name "*.html" -not -path "*/legacy/*" -exec sed -i '' "$SED_EXPR" {} +
  echo "  Done."
fi

echo ""
echo "=== Syncing to s3://$BUCKET/$S3_PREFIX/ ==="
echo ""

# ── Phase 2: Sync to S3 ───────────────────────────────────────────────────

# HTML pages — short TTL, references hashed asset filenames
echo "→ HTML files (max-age=300)..."
aws s3 sync "$BUILD_DIR/" "s3://$BUCKET/$S3_PREFIX/" \
  --exclude "*" \
  --include "*.html" \
  --cache-control "max-age=300, public" \
  --content-type "text/html; charset=utf-8" \
  --region "$REGION"

# Hashed CSS/JS — immutable 1-year cache (filename changes when content changes)
echo "→ Hashed CSS/JS (max-age=31536000, immutable)..."
aws s3 sync "$BUILD_DIR/assets/" "s3://$BUCKET/$S3_PREFIX/assets/" \
  --exclude "*" \
  --include "*.????????.css" \
  --include "*.????????.js" \
  --cache-control "max-age=31536000, public, immutable" \
  --region "$REGION"

# Original CSS/JS — 1-day cache (fallback for dynamic loads like countdown.js)
echo "→ Original CSS/JS (max-age=86400, fallback)..."
aws s3 sync "$BUILD_DIR/assets/" "s3://$BUCKET/$S3_PREFIX/assets/" \
  --exclude "*.????????.css" \
  --exclude "*.????????.js" \
  --exclude "*.map" \
  --cache-control "max-age=86400, public" \
  --region "$REGION"

# Data JSON — Lambda overwrites daily, 24h TTL is fine
echo "→ Data JSON (max-age=86400)..."
aws s3 sync "$BUILD_DIR/data/" "s3://$BUCKET/$S3_PREFIX/data/" \
  --cache-control "max-age=86400, public" \
  --content-type "application/json" \
  --region "$REGION" 2>/dev/null || true

# Everything else (images, fonts, etc.)
echo "→ Other files..."
aws s3 sync "$BUILD_DIR/" "s3://$BUCKET/$S3_PREFIX/" \
  --exclude "*.html" \
  --exclude "assets/*" \
  --exclude "data/*" \
  --exclude ".git/*" \
  --exclude ".DS_Store" \
  --exclude "*.webmanifest" \
  --exclude "sw.js" \
  --cache-control "max-age=3600, public" \
  --region "$REGION"

# PWA control files MUST NOT be long-cached: a stale manifest = silent install
# failure, and a service worker must always re-check for updates.
echo "→ PWA manifest + service worker (max-age=300, must-revalidate)..."
aws s3 sync "$BUILD_DIR/" "s3://$BUCKET/$S3_PREFIX/" \
  --exclude "*" \
  --include "*.webmanifest" \
  --include "sw.js" \
  --cache-control "max-age=300, must-revalidate, public" \
  --region "$REGION"

echo ""
echo "✅ S3 sync complete."

# ── Phase 3: CloudFront invalidation ──────────────────────────────────────
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
