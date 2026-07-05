#!/bin/bash
# rollback_site.sh — Roll back the public website to a prior git ref (tag or commit).
#
# Usage:
#   bash deploy/rollback_site.sh site-v3.7.84        # a site tag
#   bash deploy/rollback_site.sh HEAD~1              # the previous commit (CI auto-rollback)
#   bash deploy/rollback_site.sh <ref> --dry-run
#
# What it does:
#   1. Restores site/ from the specified ref into the working tree
#   2. Re-runs the CANONICAL build+sync (deploy/sync_site_to_s3.sh) so the asset
#      graph is re-hashed and version.json is re-stamped to the restored ref —
#      /version.json truthfully returns to the prior build stamp
#   3. Invalidates CloudFront (done by sync_site_to_s3.sh)
#   4. Restores the working tree to its original state
#
# History (#418/ADR-117): previously this synced the raw site/ tree via safe_sync
# with NO re-hash and NO version.json regen — which, in the v4 content-hashed-asset
# era, would leave the live version.json on the BAD build and pair fresh HTML with
# stale hashed-asset URLs (the "frozen page" class). It is now wired as the CI site
# auto-rollback path and goes through the same hashing+stamp build as a normal deploy.
set -euo pipefail

REF="${1:?Usage: rollback_site.sh <git-ref> [--dry-run]}"
DRY_RUN="${2:-}"

cd "$(dirname "$0")/.."

echo "=== Site Rollback ==="
echo "Ref: $REF"

# Verify ref exists
if ! git rev-parse --verify "$REF" >/dev/null 2>&1; then
  echo "ERROR: Ref '$REF' not found. Recent site tags:"
  git tag -l 'site-*' | tail -10
  exit 1
fi

TARGET_SHA=$(git rev-parse --short "$REF")
echo "Restoring site/ from $REF ($TARGET_SHA)..."

if [ "$DRY_RUN" = "--dry-run" ]; then
  echo "[DRY RUN] Would checkout site/ from $REF ($TARGET_SHA)"
  echo "[DRY RUN] Would re-run deploy/sync_site_to_s3.sh (re-hash + stamp version.json=$TARGET_SHA + invalidate CloudFront)"
  exit 0
fi

# Snapshot the current site/ so we can restore the working tree afterward.
STASH_REF=""
if ! git diff --quiet -- site/ || [ -n "$(git ls-files --others --exclude-standard site/)" ]; then
  git stash push --include-untracked -q -- site/ 2>/dev/null && STASH_REF="1" || true
fi
ORIG_HEAD=$(git rev-parse HEAD)

restore_tree() {
  git checkout "$ORIG_HEAD" -- site/ 2>/dev/null || true
  [ -n "$STASH_REF" ] && git stash pop -q 2>/dev/null || true
}
trap restore_tree EXIT

# Restore site/ from the target ref
git checkout "$REF" -- site/

# Re-run the canonical build+sync. ALLOW_STALE_SITE=1 bypasses the clobber guard
# (this is a deliberate rollback), OVERRIDE_BUILD_SHA stamps the restored build's
# SHA into version.json + the page <meta build> tags.
echo "Re-running canonical build+sync (rollback)..."
ALLOW_STALE_SITE=1 OVERRIDE_BUILD_SHA="$TARGET_SHA" bash deploy/sync_site_to_s3.sh

echo ""
echo "✓ Rolled site back to $REF ($TARGET_SHA)"
echo "  Verify: curl -s https://averagejoematt.com/version.json  (build should == $TARGET_SHA)"
echo "  CloudFront invalidation in progress (~30s)"
