#!/bin/bash
# Deploy body composition deltas to Withings Lambda + backfill
# Phase 1b of Derived Metrics Plan
#
# New fields added to Withings daily records:
#   - lean_mass_delta_14d (float): lean mass change vs ~14 days ago (lbs)
#   - fat_mass_delta_14d (float): fat mass change vs ~14 days ago (lbs)
#
# Rollback: Fields are additive. Redeploy from git to remove computation.

set -euo pipefail
cd "$(dirname "$0")"

echo "═══════════════════════════════════════════════════"
echo "  Phase 1b: Body Composition Deltas"
echo "  Derived Metrics Plan — v2.29.0"
echo "═══════════════════════════════════════════════════"
echo ""

# Step 1: Apply patch
echo "Step 1: Patching withings_lambda.py..."
python3 patch_body_comp_deltas.py
echo ""

# Step 2: Create zip and deploy
echo "Step 2: Deploying Lambda..."
rm -f withings_lambda.zip
zip withings_lambda.zip withings_lambda.py
aws lambda update-function-code \
    --function-name withings-data-ingestion \
    --zip-file fileb://withings_lambda.zip \
    --region us-west-2 \
    --no-cli-pager
echo ""
echo "✅ Lambda updated"
echo ""

# Step 3: Test invocation
echo "Step 3: Test invocation (yesterday)..."
aws lambda invoke \
    --function-name withings-data-ingestion \
    --payload '{}' \
    --log-type Tail \
    --region us-west-2 \
    /tmp/withings_delta_test.json \
    --no-cli-pager \
    --query 'LogResult' \
    --output text | base64 --decode | grep -E "(delta|ERROR)" || true
echo ""

# Step 4: Backfill
echo "Step 4: Backfilling historical records..."
echo "  Running dry-run first..."
python3 backfill_body_comp_deltas.py --dry-run 2>&1 | tail -15
echo ""
read -p "  Proceed with live backfill? (y/N) " confirm
if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
    python3 backfill_body_comp_deltas.py
else
    echo "  Skipped. Run manually: python3 backfill_body_comp_deltas.py"
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Phase 1b complete!"
echo "  "
echo "  New fields: lean_mass_delta_14d, fat_mass_delta_14d"
echo "  Key insight: During a cut, lean_mass_delta_14d ≥ 0 = muscle preserved"
echo "  Next: Phase 1c (time_in_optimal_pct) or Phase 1d (protein distribution)"
echo "═══════════════════════════════════════════════════"
