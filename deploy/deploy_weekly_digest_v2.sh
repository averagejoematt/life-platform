#!/bin/bash
# Deploy Weekly Digest v4.0 (Weekly Digest v2 rewrite)
# v2.24.0 — Day grades, profile-driven, Habitify, MF workouts, CGM, batch queries
set -e

FUNCTION_NAME="weekly-digest"
REGION="us-west-2"
ZIP_FILE="weekly_digest_lambda.zip"
LAMBDA_FILE="weekly_digest_v2_lambda.py"

echo "=== Weekly Digest v4.0 Deploy ==="
echo ""

# Safety: check the new lambda file exists
if [ ! -f "$LAMBDA_FILE" ]; then
    echo "ERROR: $LAMBDA_FILE not found"
    exit 1
fi

# Backup current
echo "[1/4] Backing up current weekly_digest_lambda.py..."
cp weekly_digest_lambda.py weekly_digest_lambda_v33_backup.py 2>/dev/null || true

# Replace the lambda source file
echo "[2/4] Replacing lambda source..."
cp "$LAMBDA_FILE" weekly_digest_lambda.py

# Package
echo "[3/4] Packaging..."
rm -f "$ZIP_FILE"
cd /tmp && rm -rf weekly_digest_pkg && mkdir weekly_digest_pkg && cd weekly_digest_pkg
cp ~/Documents/Claude/life-platform/weekly_digest_lambda.py digest_handler.py
zip -q ../weekly_digest_lambda.zip digest_handler.py
cp /tmp/weekly_digest_lambda.zip ~/Documents/Claude/life-platform/

echo "[4/4] Deploying to Lambda..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$HOME/Documents/Claude/life-platform/$ZIP_FILE" \
    --region "$REGION" \
    --no-cli-pager

echo ""
echo "✅ Deployed $FUNCTION_NAME v4.0"
echo ""
echo "Test with:"
echo "  aws lambda invoke --function-name $FUNCTION_NAME --payload '{}' \\"
echo "    --cli-binary-format raw-in-base64-out --region $REGION /tmp/digest.json"
echo ""
echo "  cat /tmp/digest.json"
