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
#   4. Restores bucket-root config/ twins (#2019) to the ref's bytes by re-running
#      deploy/config_twin_sync.py --apply --strict against the restored config/
#      tree — the SECOND prefix site-deploy.yml writes on every run, the gap
#      #3654 filed. A config/ twin the bad deploy ADDED (no counterpart at REF)
#      has no prior bytes to restore, and config/* is DELETE-protected for
#      matthew-admin by bucket policy (ADR-032/033/046) — this can never delete
#      it, so it is named EXPLICITLY in the run log instead of silently staying
#      live (docs/CONVENTIONS.md §4b).
#   5. Restores the working tree to its original state
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
ORIG_HEAD_PRECHECK=$(git rev-parse HEAD)
echo "Restoring site/ from $REF ($TARGET_SHA)..."

# ── #3654: bucket-root config/ twins (#2019) are the OTHER prefix site-deploy.yml
# writes ("Sync bucket-root config/ twins" step, config_twin_sync.py --apply
# --strict). A twin the bad deploy ADDED — a repo config/ file present at
# ORIG_HEAD with no counterpart at REF — has no prior bytes for this script to
# push back, and config/* is DELETE-protected for matthew-admin by bucket policy
# (ADR-032/033/046), so it can never be removed either. Computed from git objects
# (ref-to-ref), independent of working-tree state, so it is safe to run before
# any checkout below and safe to report even in --dry-run.
ADDED_CONFIG_KEYS="$(git diff --name-only --diff-filter=A "$REF" "$ORIG_HEAD_PRECHECK" -- config/ 2>/dev/null | \
  python3 -c "
import sys
sys.path.insert(0, 'deploy')
from config_twin_registry import _is_not_twin
from config_ownership_audit import uploadable
for line in sys.stdin:
    path = line.strip()
    if not path or _is_not_twin(path) or not uploadable(path):
        continue
    print(path)
" 2>/dev/null || true)"

if [ "$DRY_RUN" = "--dry-run" ]; then
  echo "[DRY RUN] Would checkout site/ from $REF ($TARGET_SHA)"
  echo "[DRY RUN] Would re-run deploy/sync_site_to_s3.sh (re-hash + stamp version.json=$TARGET_SHA + invalidate CloudFront)"
  echo "[DRY RUN] Would restore config/ from $REF and re-run deploy/config_twin_sync.py --apply --strict (#3654)"
  if [ -n "$ADDED_CONFIG_KEYS" ]; then
    echo "[DRY RUN] Would LEAVE LIVE (config/ twin added since $REF — no prior bytes, delete-protected):"
    echo "$ADDED_CONFIG_KEYS" | sed 's/^/  - /'
  else
    echo "[DRY RUN] No config/ twins were added since $REF — nothing would be left live"
  fi
  exit 0
fi

# Snapshot the current site/ + config/ so we can restore the working tree
# afterward (config/ joined the stash with #3654 — see item 4 above).
STASH_REF=""
if ! git diff --quiet -- site/ config/ || [ -n "$(git ls-files --others --exclude-standard site/ config/)" ]; then
  git stash push --include-untracked -q -- site/ config/ 2>/dev/null && STASH_REF="1" || true
fi
ORIG_HEAD=$(git rev-parse HEAD)

restore_tree() {
  git checkout "$ORIG_HEAD" -- site/ config/ 2>/dev/null || true
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

# ── #3654: restore bucket-root config/ twins to $REF's bytes ──────────────────
echo ""
echo "Restoring bucket-root config/ twins from $REF (#2019/#3654)..."
if git cat-file -e "$REF:config" 2>/dev/null; then
  git checkout "$REF" -- config/
  echo "Re-applying config twin sync (pushes any twin still on the bad deploy's bytes back to $REF)..."
  python3 deploy/config_twin_sync.py --apply --strict
else
  echo "  (no config/ tree at $REF — nothing to restore)"
fi

if [ -n "$ADDED_CONFIG_KEYS" ]; then
  echo ""
  echo "⚠️  LEFT LIVE — config/ twins the rolled-back deploy ADDED, with no bytes at"
  echo "   $REF to restore. config/* is DELETE-protected for matthew-admin by bucket"
  echo "   policy (ADR-032/033/046), so this rollback can PUT over them but never"
  echo "   remove them; they stay live under s3://matthew-life-platform/:"
  echo "$ADDED_CONFIG_KEYS" | sed 's/^/     - /'
else
  echo "  No config/ twins were added since $REF — nothing left live in config/."
fi

echo ""
echo "✓ Rolled site back to $REF ($TARGET_SHA)"
echo "  Verify: curl -s https://averagejoematt.com/version.json  (build should == $TARGET_SHA)"
echo "  CloudFront invalidation in progress (~30s)"
