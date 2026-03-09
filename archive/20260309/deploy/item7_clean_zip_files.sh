#!/usr/bin/env bash
# Item 7 — Move stale .zip files out of lambdas/ into deploy/zips/
# These are build artifacts that accumulated in the wrong directory.
# Safe to move; deploy_unified.sh always rebuilds from source, never uses these.

set -euo pipefail
cd "$(dirname "$0")/.."

ZIPS=(
  garmin_lambda.zip
  habitify_lambda.zip
  health_auto_export_lambda.zip
  key_rotator.zip
  nutrition_review_lambda.zip
  wednesday_chronicle.zip
)

echo "Moving stale .zip files from lambdas/ to deploy/zips/ ..."
for z in "${ZIPS[@]}"; do
  if [[ -f "lambdas/$z" ]]; then
    mv "lambdas/$z" "deploy/zips/$z"
    echo "  Moved: lambdas/$z → deploy/zips/$z"
  else
    echo "  Skip (not found): lambdas/$z"
  fi
done

echo ""
echo "Done. Remaining .zip files in lambdas/:"
ls lambdas/*.zip 2>/dev/null || echo "  (none)"
