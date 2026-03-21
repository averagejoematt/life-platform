#!/bin/bash
# rollback_site.sh — Roll back website to a tagged version
#
# Usage:
#   bash deploy/rollback_site.sh site-v3.7.84
#   bash deploy/rollback_site.sh site-v3.7.84 --dry-run
#
# What it does:
#   1. Checks out the site/ directory from the specified git tag
#   2. Syncs to S3
#   3. Invalidates CloudFront
#   4. Restores the working tree
#
set -euo pipefail

TAG="${1:?Usage: rollback_site.sh <git-tag> [--dry-run]}"
DRY_RUN="${2:-}"
BUCKET="matthew-life-platform"
DIST_ID="E3S424OXQZ8NBE"

cd "$(dirname "$0")/.."

echo "=== Site Rollback ==="
echo "Tag: $TAG"

# Verify tag exists
if ! git rev-parse "$TAG" >/dev/null 2>&1; then
  echo "ERROR: Tag '$TAG' not found. Available site tags:"
  git tag -l 'site-*' | tail -10
  exit 1
fi

echo "Checking out site/ from $TAG..."
if [ "$DRY_RUN" = "--dry-run" ]; then
  echo "[DRY RUN] Would checkout site/ from $TAG"
  echo "[DRY RUN] Would sync to s3://$BUCKET/site/"
  echo "[DRY RUN] Would invalidate CloudFront $DIST_ID"
  exit 0
fi

# Stash any current changes
git stash --include-untracked -q 2>/dev/null || true

# Checkout site/ from the tag
git checkout "$TAG" -- site/

# Sync to S3
echo "Syncing to S3..."
aws s3 sync site/ "s3://$BUCKET/site/" --delete

# Invalidate CloudFront
echo "Invalidating CloudFront..."
aws cloudfront create-invalidation \
  --distribution-id "$DIST_ID" \
  --paths "/*" \
  --query 'Invalidation.Id' \
  --output text

# Restore working tree
echo "Restoring working tree..."
git checkout HEAD -- site/
git stash pop -q 2>/dev/null || true

echo ""
echo "✓ Rolled back to $TAG"
echo "  CloudFront invalidation in progress (~30s)"
