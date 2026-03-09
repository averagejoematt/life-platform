#!/usr/bin/env bash
# MAINT-3 Final: Move remaining stale zip from lambdas/ to archive
# All other MAINT-3 targets were cleaned in prior sessions.
# Run from project root: bash deploy/maint3_final.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ARCHIVE="$ROOT/archive/$(date +%Y%m%d)"
mkdir -p "$ARCHIVE/lambdas"

echo "=== MAINT-3 Final: Archiving stale zip from lambdas/ ==="

# garmin_lambda.zip — stale deploy artifact, already stored in deploy/zips/
if [ -f "$ROOT/lambdas/garmin_lambda.zip" ]; then
    mv "$ROOT/lambdas/garmin_lambda.zip" "$ARCHIVE/lambdas/"
    echo "  archived: lambdas/garmin_lambda.zip → $ARCHIVE/lambdas/"
else
    echo "  already clean: lambdas/garmin_lambda.zip not found"
fi

echo ""
echo "=== Verifying lambdas/ is zip-free ==="
ZIP_COUNT=$(find "$ROOT/lambdas" -maxdepth 1 -name "*.zip" | wc -l | tr -d ' ')
if [ "$ZIP_COUNT" -eq 0 ]; then
    echo "  ✅ lambdas/ contains 0 zip files"
else
    echo "  ⚠️  lambdas/ still contains $ZIP_COUNT zip(s):"
    find "$ROOT/lambdas" -maxdepth 1 -name "*.zip"
fi

echo ""
echo "✅ MAINT-3 complete."
