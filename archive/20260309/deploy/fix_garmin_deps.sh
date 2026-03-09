#!/bin/bash
# fix_garmin_deps.sh — Rebuild garmin Lambda zip WITH garth/garminconnect deps
# Root cause: hardening deploy stripped 3rd-party deps from the zip
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
LAMBDA_NAME="garmin-data-ingestion"
SOURCE="${ROOT_DIR}/lambdas/garmin_lambda.py"
BUILD_DIR="/tmp/garmin_lambda_build"
ZIP_FILE="${ROOT_DIR}/lambdas/garmin_lambda.zip"

echo "=== Rebuilding Garmin Lambda with dependencies ==="

# Verify source exists
if [ ! -f "$SOURCE" ]; then
    echo "ERROR: $SOURCE not found"
    exit 1
fi

# Clean build dir
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# Install deps into build dir (Lambda needs these bundled)
echo "Installing garminconnect + garth into build dir..."
pip3 install garminconnect garth -t "$BUILD_DIR" --quiet --upgrade \
    --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.12 --implementation cp

# Copy lambda source
cp "$SOURCE" "$BUILD_DIR/garmin_lambda.py"

# Build zip (exclude __pycache__, dist-info, .pyc)
echo "Building zip..."
cd "$BUILD_DIR"
zip -r "$ZIP_FILE" . -x "__pycache__/*" "*.dist-info/*" "*.pyc" "bin/*" > /dev/null
echo "Zip: $(du -h "$ZIP_FILE" | cut -f1)"

# Deploy
echo "Deploying to Lambda: ${LAMBDA_NAME}..."
aws lambda update-function-code \
    --function-name "${LAMBDA_NAME}" \
    --zip-file "fileb://${ZIP_FILE}" \
    --region us-west-2

# Clean up
rm -rf "$BUILD_DIR"

echo ""
echo "=== Garmin Deploy Complete ==="
echo "  Function: ${LAMBDA_NAME}"
echo "  Handler:  garmin_lambda.lambda_handler"
echo ""
echo "Testing invocation..."
aws lambda invoke \
    --function-name "${LAMBDA_NAME}" \
    --region us-west-2 \
    --log-type Tail \
    /tmp/garmin_test.json \
    --query 'LogResult' \
    --output text | base64 -d
echo ""
echo "=== Done ==="
