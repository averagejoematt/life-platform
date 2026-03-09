#!/bin/bash
# deploy_garmin_phase1.sh — Deploy Garmin Lambda v1.5.0 (Phase 1 API gap closure)
#
# Changes:
#   - extract_sleep: 2 → 18 fields (stages, timing, SpO2, respiration, sub-scores)
#   - extract_activities: +5 fields (avg_hr, max_hr, calories, avg/max speed)
#   - Garmin becomes a complete second sleep source alongside Eight Sleep
#
# Prerequisites:
#   - python3 patch_garmin_phase1.py  (must be run first to patch garmin_lambda.py)
#
# Run from: ~/Documents/Claude/life-platform/

set -euo pipefail

FUNCTION_NAME="garmin-data-ingestion"
REGION="us-west-2"
ZIP_FILE="garmin_lambda.zip"
VENV_DIR="/tmp/garmin-venv"

echo "=== Deploying Garmin Lambda v1.5.0 (Phase 1: Sleep + Activity + VO2max) ==="
echo "Expands sleep from 2→18 fields, adds activity HR/calories"
echo ""

# ── Step 1: Verify patch was applied ──────────────────────────────────────
if ! grep -q "v1.5.0" garmin_lambda.py; then
    echo "ERROR: garmin_lambda.py is not patched to v1.5.0"
    echo "Run: python3 patch_garmin_phase1.py"
    exit 1
fi
echo "Step 1: ✅ garmin_lambda.py is v1.5.0 (patch applied)"

# ── Step 2: Set up Python venv ────────────────────────────────────────────
echo ""
echo "Step 2: Setting up build environment..."
if [ ! -d "$VENV_DIR" ]; then
    echo "  Creating Python venv at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
pip install --quiet --upgrade garminconnect garth boto3
echo "  ✅ Python venv ready"

# ── Step 3: Build Lambda package ──────────────────────────────────────────
echo ""
echo "Step 3: Building Lambda package with Linux-compatible binaries..."

BUILD_DIR=$(mktemp -d)

pip install \
    garminconnect garth \
    --platform manylinux2014_x86_64 \
    --implementation cp \
    --python-version 3.12 \
    --only-binary=:all: \
    --target "$BUILD_DIR" \
    --quiet

cp garmin_lambda.py "$BUILD_DIR/garmin_lambda.py"

cd "$BUILD_DIR"
rm -f "${OLDPWD}/${ZIP_FILE}"
zip -r "${OLDPWD}/${ZIP_FILE}" . --quiet
cd "$OLDPWD"
rm -rf "$BUILD_DIR"

ZIP_SIZE=$(du -sh "$ZIP_FILE" | cut -f1)
echo "  ✅ Package created: $ZIP_FILE ($ZIP_SIZE)"

# ── Step 4: Deploy to Lambda ─────────────────────────────────────────────
echo ""
echo "Step 4: Deploying to Lambda..."

aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://${ZIP_FILE}" \
    --region "$REGION" \
    --output json | head -20

echo ""
echo "Step 5: Waiting for update..."
aws lambda wait function-updated \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION"

echo ""
echo "Step 6: Verifying..."
aws lambda get-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --query '{LastModified: LastModified, Runtime: Runtime, MemorySize: MemorySize, Timeout: Timeout}' \
    --output table

echo ""
echo "=== ✅ Garmin Lambda v1.5.0 deployed ==="
echo ""
echo "Test with:"
echo "  aws lambda invoke --function-name $FUNCTION_NAME \\"
echo "    --payload '{\"date\": \"2026-02-23\"}' \\"
echo "    --cli-binary-format raw-in-base64-out \\"
echo "    --region $REGION /tmp/garmin-test.json && cat /tmp/garmin-test.json"
echo ""
echo "Check new sleep fields:"
echo "  aws dynamodb get-item --table-name life-platform \\"
echo "    --key '{\"pk\":{\"S\":\"USER#matthew#SOURCE#garmin\"},\"sk\":{\"S\":\"DATE#2026-02-23\"}}' \\"
echo "    --region $REGION \\"
echo "    --query 'Item.{sleep_score:sleep_score,deep:deep_sleep_seconds,rem:rem_sleep_seconds,start:sleep_start_local}'"
