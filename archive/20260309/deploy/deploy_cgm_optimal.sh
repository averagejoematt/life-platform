#!/bin/bash
# deploy_cgm_optimal.sh — Derived Metrics Phase 1c: blood_glucose_time_in_optimal_pct
#
# 1. Patch health_auto_export_lambda.py with optimal range calculation
# 2. Zip and deploy Lambda
# 3. Backfill historical CGM data from S3
#
# Usage: cd ~/Documents/Claude/life-platform && bash deploy_cgm_optimal.sh

set -euo pipefail

FUNCTION_NAME="health-auto-export-webhook"
LAMBDA_FILE="health_auto_export_lambda.py"
ZIP_FILE="health_auto_export_lambda.zip"

echo "═══════════════════════════════════════════════════════════"
echo " Phase 1c: CGM Time-in-Optimal (70-120 mg/dL)"
echo "═══════════════════════════════════════════════════════════"

# ── Step 1: Patch Lambda ──
echo ""
echo "▶ Step 1: Patching ${LAMBDA_FILE}..."
python3 patch_cgm_optimal.py

# ── Step 2: Verify patch ──
echo ""
echo "▶ Step 2: Verifying patch..."
if grep -q "in_optimal" "${LAMBDA_FILE}"; then
    echo "  ✅ in_optimal counter found"
else
    echo "  ❌ Patch verification failed"
    exit 1
fi

if grep -q "blood_glucose_time_in_optimal_pct" "${LAMBDA_FILE}"; then
    echo "  ✅ blood_glucose_time_in_optimal_pct field found"
else
    echo "  ❌ Patch verification failed"
    exit 1
fi

# ── Step 3: Zip and deploy ──
echo ""
echo "▶ Step 3: Deploying Lambda..."
zip -j "${ZIP_FILE}" "${LAMBDA_FILE}"

aws lambda update-function-code \
    --function-name "${FUNCTION_NAME}" \
    --zip-file "fileb://${ZIP_FILE}" \
    --region us-west-2 \
    --output text \
    --query 'LastModified'

echo "  ✅ Lambda updated"

# Wait for update to complete
echo "  Waiting for Lambda to stabilize..."
aws lambda wait function-updated --function-name "${FUNCTION_NAME}" --region us-west-2
echo "  ✅ Lambda ready"

# ── Step 4: Backfill historical data ──
echo ""
echo "▶ Step 4: Backfilling historical CGM data..."
python3 backfill_cgm_optimal.py

echo ""
echo "═══════════════════════════════════════════════════════════"
echo " ✅ Phase 1c complete!"
echo "  - Lambda patched with blood_glucose_time_in_optimal_pct"
echo "  - Historical CGM days backfilled from S3"
echo "  - New webhook payloads will auto-compute optimal %"
echo "═══════════════════════════════════════════════════════════"
