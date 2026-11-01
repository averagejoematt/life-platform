#!/usr/bin/env bash
# deploy/www_build_target.sh — build the v9 tree for ONE target and scan it (#5534).
#
#   preview   WEB_BASE=/next/v9/ WEB_NOINDEX=1 (sitemap off, noindex on every page), scan requires noindex
#   root      WEB_BASE=/ (sitemap on, self-canonical), scan requires NO noindex, and the LIVE build's
#             routes are checked against the kept site/ pages (deploy/www_owned_paths.py --check-dist)
#
# The snapshot must already be in www/content/snapshot (the workflow exports the LIVE one first).
# Usage: bash deploy/www_build_target.sh preview|root
set -euo pipefail
TARGET="${1:?Usage: www_build_target.sh preview|root}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

case "$TARGET" in
  preview)
    (cd "$REPO/www" && npm run build:preview)
    python3 "$REPO/scripts/check_www_build.py" --scan-only
    ;;
  root)
    (cd "$REPO/www" && npm run build)
    python3 "$REPO/scripts/check_www_build.py" --scan-only --no-noindex
    python3 "$HERE/www_owned_paths.py" --check-dist "$REPO/www/dist"
    ;;
  *) echo "www_build_target: target must be preview or root (got '$TARGET')" >&2; exit 3 ;;
esac
echo "www_build_target: $TARGET build in www/dist passed the scan"
