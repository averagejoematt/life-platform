#!/bin/bash
# PROD-2 Phase 3: Migrate S3 paths to user-prefixed layout
#
# Before:  dashboard/data.json          → dashboard/matthew/data.json
#          dashboard/clinical.json      → dashboard/matthew/clinical.json
#          buddy/data.json              → buddy/matthew/data.json
#          config/board_of_directors.json → config/matthew/board_of_directors.json
#          config/character_sheet.json  → config/matthew/character_sheet.json
#          config/profile.json          → config/matthew/profile.json
#
# After migration, the original flat paths are intentionally left in place
# as a fallback — remove them manually once the new paths are confirmed working.

set -euo pipefail

BUCKET="matthew-life-platform"
REGION="us-west-2"

echo "=== PROD-2 Phase 3: S3 path migration ==="
echo "Bucket: $BUCKET"
echo ""

copy_if_exists() {
    local src="$1"
    local dst="$2"
    echo -n "  $src → $dst ... "
    if aws s3 cp "s3://$BUCKET/$src" "s3://$BUCKET/$dst" \
        --region "$REGION" \
        --no-progress \
        --content-type "application/json" 2>/dev/null; then
        echo "✅"
    else
        echo "⚠️  (source not found — OK if Lambda hasn't run yet)"
    fi
}

echo "--- Dashboard data ---"
copy_if_exists "dashboard/data.json"          "dashboard/matthew/data.json"
copy_if_exists "dashboard/clinical.json"      "dashboard/matthew/clinical.json"

echo ""
echo "--- Buddy data ---"
copy_if_exists "buddy/data.json"              "buddy/matthew/data.json"

echo ""
echo "--- Config files ---"
copy_if_exists "config/board_of_directors.json"  "config/matthew/board_of_directors.json"
copy_if_exists "config/character_sheet.json"     "config/matthew/character_sheet.json"
copy_if_exists "config/profile.json"             "config/matthew/profile.json"

echo ""
echo "--- Verification (new paths) ---"
for key in \
    "dashboard/matthew/data.json" \
    "dashboard/matthew/clinical.json" \
    "buddy/matthew/data.json" \
    "config/matthew/board_of_directors.json" \
    "config/matthew/character_sheet.json" \
    "config/matthew/profile.json"; do
    if aws s3 ls "s3://$BUCKET/$key" --region "$REGION" &>/dev/null; then
        echo "  ✅ $key"
    else
        echo "  ❌ $key (missing)"
    fi
done

echo ""
echo "Migration complete."
echo ""
echo "Next steps:"
echo "  1. bash deploy/deploy_prod2_phase3.sh"
echo "  2. Test dashboard — should load from matthew/data.json"
echo "  3. Once confirmed working, optionally delete old flat-path files"
