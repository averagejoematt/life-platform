#!/bin/bash
set -euo pipefail

# R18-F05: Canonical site deployment script
# Replaces ad-hoc "aws s3 sync" commands with validation + sync + invalidation
# Usage: bash deploy/deploy_site.sh

BUCKET="matthew-life-platform"
DISTRIBUTION_ID="E3S424OXQZ8NBE"
SITE_DIR="site"
S3_PREFIX="site"
REGION="us-west-2"

echo "=== Site Deploy ==="
echo "Source: $SITE_DIR/"
echo "Target: s3://$BUCKET/$S3_PREFIX/"

# 1. Validate site directory exists and has index.html
if [ ! -f "$SITE_DIR/index.html" ]; then
  echo "❌ $SITE_DIR/index.html not found. Are you in the project root?"
  exit 1
fi

PAGE_COUNT=$(find "$SITE_DIR" -name 'index.html' | wc -l | tr -d ' ')
echo "Pages: $PAGE_COUNT"

# 2. Check for broken internal links (basic)
echo ""
echo "[1/4] Checking for obviously broken internal links..."
BROKEN=0
for f in $(find "$SITE_DIR" -name '*.html'); do
  grep -oP 'href="/([^"#?]+)"' "$f" 2>/dev/null | sed 's|href="/||;s|"||' | while read -r link; do
    [[ "$link" == http* ]] && continue
    [[ "$link" == api/* ]] && continue
    [[ "$link" == mailto* ]] && continue
    [[ "$link" == rss* ]] && continue
    TARGET="$SITE_DIR/$link"
    if [ ! -f "$TARGET" ] && [ ! -f "${TARGET}index.html" ] && [ ! -f "${TARGET%/}/index.html" ]; then
      echo "  ⚠️  Broken link in $(basename "$f"): /$link"
      BROKEN=$((BROKEN + 1))
    fi
  done
done
if [ "$BROKEN" -gt 0 ]; then
  echo "  $BROKEN broken links found (warnings only — not blocking deploy)"
else
  echo "  ✓ No broken links detected"
fi

# 3. Sync to S3 (delegates to sync_site_to_s3.sh for proper cache headers)
echo ""
echo "[2/4] Syncing to S3..."
if [ -f "deploy/sync_site_to_s3.sh" ]; then
  bash deploy/sync_site_to_s3.sh
else
  echo "❌ deploy/sync_site_to_s3.sh not found"
  exit 1
fi

# 4. Summary
echo ""
echo "[4/4] Done."
echo "  Pages deployed: $PAGE_COUNT"
echo "  Target: https://averagejoematt.com/"
