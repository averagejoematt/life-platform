#!/bin/bash
# deploy_micronutrient_sufficiency.sh — Derived Metrics Phase 1e: micronutrient_sufficiency
#
# 1. Patch macrofactor_lambda.py with micronutrient sufficiency calculation
# 2. Zip and deploy Lambda
# 3. Backfill historical MacroFactor data
#
# Prerequisite: Phase 1d (protein_distribution) must already be applied.
#
# Usage: cd ~/Documents/Claude/life-platform && bash deploy_micronutrient_sufficiency.sh

set -euo pipefail

FUNCTION_NAME="macrofactor-data-ingestion"
LAMBDA_FILE="macrofactor_lambda.py"
ZIP_FILE="macrofactor_lambda.zip"

echo "═══════════════════════════════════════════════════════════"
echo " Phase 1e: Micronutrient Sufficiency"
echo "═══════════════════════════════════════════════════════════"

# ── Step 1: Verify Phase 1d is applied ──
echo ""
echo "▶ Step 1: Checking prerequisite (Phase 1d)..."
if grep -q "compute_protein_distribution" "${LAMBDA_FILE}"; then
    echo "  ✅ Phase 1d (protein distribution) present"
else
    echo "  ❌ Phase 1d not found — apply deploy_protein_distribution.sh first"
    exit 1
fi

# ── Step 2: Patch Lambda ──
echo ""
echo "▶ Step 2: Patching ${LAMBDA_FILE}..."
python3 patch_micronutrient_sufficiency.py

# ── Step 3: Verify patch ──
echo ""
echo "▶ Step 3: Verifying patch..."
if grep -q "compute_micronutrient_sufficiency" "${LAMBDA_FILE}"; then
    echo "  ✅ compute_micronutrient_sufficiency function found"
else
    echo "  ❌ Patch verification failed"
    exit 1
fi

if grep -q "MICRONUTRIENT_TARGETS" "${LAMBDA_FILE}"; then
    echo "  ✅ MICRONUTRIENT_TARGETS config found"
else
    echo "  ❌ Patch verification failed"
    exit 1
fi

# ── Step 4: Verify handler matches ──
echo ""
echo "▶ Step 4: Checking Lambda handler..."
HANDLER=$(aws lambda get-function-configuration \
    --function-name "${FUNCTION_NAME}" \
    --query Handler --output text --region us-west-2)
echo "  Handler: ${HANDLER}"
if [[ "${HANDLER}" != "macrofactor_lambda.lambda_handler" ]]; then
    echo "  ❌ Handler mismatch!"
    exit 1
fi
echo "  ✅ Handler matches filename"

# ── Step 5: Zip and deploy ──
echo ""
echo "▶ Step 5: Deploying Lambda..."
zip -j "${ZIP_FILE}" "${LAMBDA_FILE}"

aws lambda update-function-code \
    --function-name "${FUNCTION_NAME}" \
    --zip-file "fileb://${ZIP_FILE}" \
    --region us-west-2 \
    --output text \
    --query 'LastModified'

echo "  ✅ Lambda updated"

echo "  Waiting for Lambda to stabilize..."
aws lambda wait function-updated --function-name "${FUNCTION_NAME}" --region us-west-2
echo "  ✅ Lambda ready"

# ── Step 6: Backfill historical data ──
echo ""
echo "▶ Step 6: Backfilling historical MacroFactor data..."
python3 backfill_micronutrient_sufficiency.py

echo ""
echo "═══════════════════════════════════════════════════════════"
echo " ✅ Phase 1e complete!"
echo "  - Lambda patched with micronutrient_sufficiency"
echo "  - 5 nutrients tracked: Fiber, Potassium, Magnesium,"
echo "    Vitamin D (4000 IU), Omega-3"
echo "  - Historical MacroFactor days backfilled"
echo "  - New CSV uploads will auto-compute sufficiency"
echo "═══════════════════════════════════════════════════════════"
