#!/usr/bin/env bash
# safe_sync.sh — wrapper for aws s3 sync --delete with safety gates
# Source this in deploy scripts: source deploy/lib/safe_sync.sh

safe_sync() {
  local src="$1" dst="$2"
  shift 2

  # Block syncs to bucket root
  if [[ "$dst" =~ ^s3://[^/]+/?$ ]]; then
    echo "FATAL: Refusing to sync --delete to bucket root: $dst"
    echo "Always target a prefix, e.g. s3://bucket/site/"
    return 1
  fi

  # Dryrun and count deletions
  local delete_count
  delete_count=$(aws s3 sync "$src" "$dst" --delete --dryrun "$@" 2>&1 | grep -c "^(dryrun) delete:" || true)

  if [[ "$delete_count" -gt 100 ]]; then
    echo "ABORT: dryrun shows $delete_count deletions — this looks wrong."
    echo "Review manually or raise the threshold if intentional."
    return 1
  fi

  if [[ "$delete_count" -gt 0 ]]; then
    echo "  Dryrun: $delete_count deletions, proceeding..."
  fi

  aws s3 sync "$src" "$dst" --delete "$@"
}
