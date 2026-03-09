#!/bin/bash
# PROD-2 Phase 2: S3 data migration
# Copies existing raw/ and config/ data to prefixed paths (raw/matthew/, config/matthew/)
# Run BEFORE deploying updated Lambda code.
#
# This is non-destructive — old paths are preserved until you explicitly delete them.
# After 7+ days of verified operation, run the cleanup at the bottom.

set -e

BUCKET="matthew-life-platform"
USER_ID="matthew"
REGION="us-west-2"

echo "=== PROD-2 Phase 2: S3 path migration ==="
echo "Bucket: s3://$BUCKET"
echo "User: $USER_ID"
echo ""

# ──────────────────────────────────────────────────────────────
# Step 1: Config files (small, fast)
# ──────────────────────────────────────────────────────────────
echo "--- Step 1: Config files ---"
echo "Copying config/*.json → config/$USER_ID/*.json"

for key in board_of_directors.json character_sheet.json profile.json project_pillar_map.json; do
    src="config/$key"
    dst="config/$USER_ID/$key"

    # Check source exists
    if aws s3api head-object --bucket "$BUCKET" --key "$src" --region "$REGION" 2>/dev/null; then
        aws s3 cp "s3://$BUCKET/$src" "s3://$BUCKET/$dst" --region "$REGION"
        echo "  ✅ $src → $dst"
    else
        echo "  ⚠️  $src not found (skipping)"
    fi
done

echo ""

# ──────────────────────────────────────────────────────────────
# Step 2: raw/ data (bulk sync)
# ──────────────────────────────────────────────────────────────
echo "--- Step 2: raw/ data (bulk copy) ---"
echo "Copying s3://$BUCKET/raw/ → s3://$BUCKET/raw/$USER_ID/"
echo "Note: This may take a minute depending on how many files exist."
echo ""

# Count objects first
COUNT=$(aws s3api list-objects-v2 \
    --bucket "$BUCKET" \
    --prefix "raw/" \
    --region "$REGION" \
    --query 'length(Contents[?!contains(Key, `/'"$USER_ID"'`)])' \
    --output text 2>/dev/null || echo "unknown")
echo "  Objects to copy: $COUNT"
echo ""

# Do the copy (sync is not appropriate here — we want to copy all raw/ objects
# to raw/matthew/ without moving them, preserving originals)
aws s3 cp \
    "s3://$BUCKET/raw/" \
    "s3://$BUCKET/raw/$USER_ID/" \
    --recursive \
    --region "$REGION" \
    --exclude "raw/$USER_ID/*" \
    2>&1 | tail -5

echo ""
echo "--- Step 2 complete ---"

# ──────────────────────────────────────────────────────────────
# Step 3: Verify
# ──────────────────────────────────────────────────────────────
echo ""
echo "--- Step 3: Verification ---"
echo "Config files at new paths:"
aws s3 ls "s3://$BUCKET/config/$USER_ID/" --region "$REGION" 2>/dev/null || echo "  (no files found at config/$USER_ID/)"

echo ""
echo "Sample raw/$USER_ID/ objects:"
aws s3 ls "s3://$BUCKET/raw/$USER_ID/" --recursive --region "$REGION" 2>/dev/null | head -10 || echo "  (no files found at raw/$USER_ID/)"

echo ""
echo "=== Migration complete ==="
echo ""
echo "Next steps:"
echo "  1. Deploy updated Lambda code:  bash deploy/deploy_prod2_phase2.sh"
echo "  2. Wait 7+ days to verify normal operation"
echo "  3. When ready to clean up old paths (IRREVERSIBLE):"
echo "     aws s3 rm s3://$BUCKET/raw/ --recursive --exclude 'raw/$USER_ID/*'"
echo "     (plus manually delete old config/*.json if desired)"
echo ""
echo "NOTE: insight_email_parser S3 trigger still fires on raw/inbound_email/"
echo "  → Update SES receipt rule + S3 event notification manually after verifying:"
echo "    SES rule: change S3 prefix from raw/inbound_email/ to raw/matthew/inbound_email/"
echo "    S3 notification: update trigger prefix from raw/ to raw/matthew/ for that Lambda"
