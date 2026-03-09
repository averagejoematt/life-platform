#!/bin/bash
# fix_garmin.sh — Fix Garmin Lambda: re-auth + repackage + redeploy
#
# Fixes:
#   1. Expired OAuth tokens → re-auth interactively via garth
#   2. pydantic_core binary mismatch → install with Linux x86_64 platform target
#   3. display_name = None → updated auth flow in Lambda code
#
# Run: bash fix_garmin.sh

set -e

REGION="us-west-2"
ACCOUNT="205930651321"
FUNCTION_NAME="garmin-data-ingestion"
ZIP_FILE="garmin_lambda.zip"

cd "$(dirname "$0")"

echo "══════════════════════════════════════════════════════════════"
echo "  Garmin Lambda Fix — Re-auth + Repackage + Redeploy"
echo "══════════════════════════════════════════════════════════════"

# ── Step 0: Set up Python venv with dependencies ────────────────────────────
VENV_DIR="/tmp/garmin-venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python venv at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
pip install --quiet --upgrade garminconnect garth boto3
echo "  ✅ Python venv ready with garminconnect + garth"

# ── Step 1: Re-authenticate Garmin OAuth tokens ─────────────────────────────
echo ""
echo "Step 1: Re-authenticating Garmin Connect..."
echo "  (You may be prompted for MFA if Garmin requires it)"
echo ""

python3 setup_garmin_auth.py

echo ""
echo "  ✅ Garmin tokens refreshed in Secrets Manager"

# ── Step 2: Build Lambda package with Linux x86_64 binaries ─────────────────
echo ""
echo "Step 2: Building Lambda package with Linux-compatible binaries..."

BUILD_DIR=$(mktemp -d)
echo "  Build dir: $BUILD_DIR"

# Install ALL dependencies targeting Lambda's Linux x86_64 runtime
# This ensures pydantic_core gets the correct compiled .so files
pip install \
    garminconnect garth \
    --platform manylinux2014_x86_64 \
    --implementation cp \
    --python-version 3.12 \
    --only-binary=:all: \
    --target "$BUILD_DIR" \
    --quiet

# Copy updated Lambda handler
cp garmin_lambda.py "$BUILD_DIR/garmin_lambda.py"

# Create zip
echo "  Creating zip..."
cd "$BUILD_DIR"
zip -r "${OLDPWD}/${ZIP_FILE}" . --quiet
cd "$OLDPWD"

rm -rf "$BUILD_DIR"

ZIP_SIZE=$(du -sh "$ZIP_FILE" | cut -f1)
echo "  ✅ Package created: $ZIP_FILE ($ZIP_SIZE)"

# ── Step 3: Deploy to Lambda ────────────────────────────────────────────────
echo ""
echo "Step 3: Deploying Lambda code..."

aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://${ZIP_FILE}" \
    --region "$REGION" \
    --query "[FunctionName,CodeSize,LastModified]"

echo "  Waiting for update to propagate..."
aws lambda wait function-updated \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION"

echo "  ✅ Lambda code deployed"

# ── Step 4: Test with yesterday's date ──────────────────────────────────────
echo ""
echo "Step 4: Testing with yesterday's date..."
echo ""

YESTERDAY=$(python3 -c "from datetime import datetime, timedelta; print((datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'))")

aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --payload "{\"date\": \"$YESTERDAY\"}" \
    --cli-binary-format raw-in-base64-out \
    --region "$REGION" \
    --log-type Tail \
    /tmp/garmin_test.json \
    --query "LogResult" \
    --output text | base64 -d | tail -30

echo ""
echo "Response:"
cat /tmp/garmin_test.json | python3 -m json.tool

echo ""
echo "══════════════════════════════════════════════════════════════"
echo "  Garmin Lambda fix complete!"
echo "══════════════════════════════════════════════════════════════"
echo ""
echo "If successful, backfill the gap since Jan 18:"
echo "  python3 backfill_garmin.py --start 2026-01-19 --end $YESTERDAY"
