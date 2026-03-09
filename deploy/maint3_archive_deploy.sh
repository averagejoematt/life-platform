#!/usr/bin/env bash
# MAINT-3: Archive stale one-off scripts from deploy/ and deploy/zips/
#
# Strategy: archive everything EXCEPT the curated active set below.
# Nothing is deleted — all files move to archive/YYYYMMDD/deploy/.
# To undo: mv archive/YYYYMMDD/deploy/* deploy/
#
# Run from project root: bash deploy/maint3_archive_deploy.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY="$ROOT/deploy"
ARCHIVE_DIR="$ROOT/archive/$(date +%Y%m%d)/deploy"
mkdir -p "$ARCHIVE_DIR" "$ARCHIVE_DIR/zips"

echo "════════════════════════════════════════"
echo "  MAINT-3: deploy/ archive cleanup"
echo "  Archive: $ARCHIVE_DIR"
echo "════════════════════════════════════════"
echo ""

# ── Curated KEEP set ──────────────────────────────────────────────────────────
# These files stay in deploy/. Everything else gets archived.
KEEP=(
  # Universal helpers (used every session)
  "deploy_lambda.sh"
  "MANIFEST.md"
  "SMOKE_TEST_TEMPLATE.sh"
  "generate_review_bundle.sh"

  # Lambda Layer rebuild scripts (needed when layer changes)
  "p3_build_shared_utils_layer.sh"
  "p3_build_garmin_layer.sh"
  "p3_attach_shared_utils_layer.sh"

  # Pending work (SEC-4 — about to be run)
  "sec4_apigw_rate_limit.sh"

  # This script itself
  "maint3_archive_deploy.sh"
)

# ── Archive all .sh / .py files not in KEEP ───────────────────────────────────
echo "Archiving stale scripts..."
ARCHIVED=0
SKIPPED=0

for f in "$DEPLOY"/*.sh "$DEPLOY"/*.py "$DEPLOY"/*.md; do
  [ -f "$f" ] || continue
  BASENAME="$(basename "$f")"

  # Check if in KEEP list
  KEEP_IT=false
  for k in "${KEEP[@]}"; do
    if [ "$BASENAME" = "$k" ]; then
      KEEP_IT=true
      break
    fi
  done

  if $KEEP_IT; then
    echo "  KEEP  $BASENAME"
    SKIPPED=$((SKIPPED + 1))
  else
    mv "$f" "$ARCHIVE_DIR/"
    echo "  arch  $BASENAME"
    ARCHIVED=$((ARCHIVED + 1))
  fi
done

echo ""
echo "Scripts: archived=$ARCHIVED  kept=$SKIPPED"
echo ""

# ── deploy/zips/ — archive all except garmin_lambda.zip ──────────────────────
echo "Archiving stale zips from deploy/zips/..."
ZIP_ARCHIVED=0
ZIP_KEPT=0

for f in "$DEPLOY/zips"/*.zip; do
  [ -f "$f" ] || continue
  BASENAME="$(basename "$f")"

  if [ "$BASENAME" = "garmin_lambda.zip" ]; then
    echo "  KEEP  zips/$BASENAME  (native deps — hard to rebuild)"
    ZIP_KEPT=$((ZIP_KEPT + 1))
  else
    mv "$f" "$ARCHIVE_DIR/zips/"
    echo "  arch  zips/$BASENAME"
    ZIP_ARCHIVED=$((ZIP_ARCHIVED + 1))
  fi
done

echo ""
echo "Zips: archived=$ZIP_ARCHIVED  kept=$ZIP_KEPT"
echo ""

# ── Final summary ─────────────────────────────────────────────────────────────
echo "════════════════════════════════════════"
echo "  ✅  MAINT-3 complete"
echo ""
echo "  Archived → $ARCHIVE_DIR"
echo "  Total archived: $((ARCHIVED + ZIP_ARCHIVED)) files"
echo ""
echo "  Active deploy/ contents:"
ls "$DEPLOY"/*.sh "$DEPLOY"/*.py "$DEPLOY"/*.md 2>/dev/null | xargs -I{} basename {} | sort | sed 's/^/    /'
echo ""
echo "  Active zips:"
ls "$DEPLOY/zips/" | sed 's/^/    /'
echo ""
echo "  To undo: mv $ARCHIVE_DIR/* $DEPLOY/"
echo "════════════════════════════════════════"
