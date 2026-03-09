#!/bin/bash
# deploy_protein_distribution.sh — Derived Metrics Phase 1d: protein_distribution_score
#
# 1. Patch macrofactor_lambda.py with meal grouping + protein distribution
# 2. Zip and deploy Lambda
# 3. Backfill historical MacroFactor data
#
# Usage: cd ~/Documents/Claude/life-platform && bash deploy_protein_distribution.sh

set -euo pipefail

FUNCTION_NAME="macrofactor-data-ingestion"
LAMBDA_FILE="macrofactor_lambda.py"
ZIP_FILE="macrofactor_lambda.zip"

echo "═══════════════════════════════════════════════════════════"
echo " Phase 1d: Protein Distribution Score (≥30g/meal)"
echo "═══════════════════════════════════════════════════════════"

# ── Step 1: Patch Lambda ──
echo ""
echo "▶ Step 1: Patching ${LAMBDA_FILE}..."
python3 patch_protein_distribution.py

# ── Step 2: Verify patch ──
echo ""
echo "▶ Step 2: Verifying patch..."
if grep -q "compute_protein_distribution" "${LAMBDA_FILE}"; then
    echo "  ✅ compute_protein_distribution function found"
else
    echo "  ❌ Patch verification failed"
    exit 1
fi

if grep -q "protein_distribution_score" "${LAMBDA_FILE}"; then
    echo "  ✅ protein_distribution_score field found"
else
    echo "  ❌ Patch verification failed"
    exit 1
fi

# ── Step 3: Verify handler matches ──
echo ""
echo "▶ Step 3: Checking Lambda handler..."
HANDLER=$(aws lambda get-function-configuration \
    --function-name "${FUNCTION_NAME}" \
    --query Handler --output text --region us-west-2)
echo "  Handler: ${HANDLER}"
if [[ "${HANDLER}" != "macrofactor_lambda.lambda_handler" ]]; then
    echo "  ❌ Handler mismatch! Expected macrofactor_lambda.lambda_handler"
    exit 1
fi
echo "  ✅ Handler matches filename"

# ── Step 4: Zip and deploy ──
echo ""
echo "▶ Step 4: Deploying Lambda..."
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

# ── Step 5: Backfill historical data ──
echo ""
echo "▶ Step 5: Backfilling historical MacroFactor data..."
python3 backfill_protein_distribution.py

echo ""
echo "═══════════════════════════════════════════════════════════"
echo " ✅ Phase 1d complete!"
echo "  - Lambda patched with protein_distribution_score"
echo "  - Historical MacroFactor days backfilled"
echo "  - New CSV uploads will auto-compute distribution"
echo "═══════════════════════════════════════════════════════════"
