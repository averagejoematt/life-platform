#!/usr/bin/env bash
# safe_sync.sh — wrapper for aws s3 sync --delete with safety gates
# Source this in deploy scripts: source deploy/lib/safe_sync.sh
#
# Protects dynamically-generated files that exist in S3 but not in the
# local site/ directory (written by Lambdas at runtime):
#   - public_stats.json   (site-stats-refresh Lambda)
#   - pulse.json          (daily-brief Lambda)
#   - og-*.png            (og-image-generator Lambda)
#   - avatar/*            (character avatar assets)

# ADR-046: Lambda-generated content now lives in generated/ prefix (not site/).
# The only remaining exclude is config/ — manually-uploaded config files that
# live in site/config/ but not in the local site/ directory.
# All other generated files (public_stats, character_stats, OG images, journal
# posts) are structurally isolated in generated/ and cannot be affected by
# site/ deploys.
SAFE_SYNC_EXCLUDES=(
  "--exclude" "config/*"
)

safe_sync() {
  local src="$1" dst="$2"
  shift 2

  # Block syncs to bucket root
  if [[ "$dst" =~ ^s3://[^/]+/?$ ]]; then
    echo "FATAL: Refusing to sync --delete to bucket root: $dst"
    echo "Always target a prefix, e.g. s3://bucket/site/"
    return 1
  fi

  # Build full args: user args + exclude list
  local all_args=("$@" "${SAFE_SYNC_EXCLUDES[@]}")

  # Dryrun and count deletions
  local delete_count
  delete_count=$(aws s3 sync "$src" "$dst" --delete --dryrun "${all_args[@]}" 2>&1 | grep -c "^(dryrun) delete:" || true)

  if [[ "$delete_count" -gt 100 ]]; then
    echo "ABORT: dryrun shows $delete_count deletions — this looks wrong."
    echo "Review manually or raise the threshold if intentional."
    return 1
  fi

  if [[ "$delete_count" -gt 0 ]]; then
    echo "  Dryrun: $delete_count deletions, proceeding..."
  fi

  aws s3 sync "$src" "$dst" --delete "${all_args[@]}"
}
