#!/bin/bash
# p3_build_garmin_layer.sh — Build and publish garmin-deps Lambda Layer
#
# Bundles garminconnect + garth for linux/x86_64 Python 3.12.
# Lambdas using this layer no longer need to bundle these deps in their zip.
#
# After running this:
#   1. Record the Layer ARN + version number printed at the end
#   2. Run p3_attach_garmin_layer.sh to attach to garmin-data-ingestion
#
# Layer name: life-platform-garmin-deps
# ~15 MB zipped, ~60 MB unzipped (within 250 MB Lambda limit)

set -euo pipefail
chmod +x "$0"
REGION="us-west-2"
LAYER_NAME="life-platform-garmin-deps"
BUILD_DIR="/tmp/garmin_layer_build"
ZIP_FILE="/tmp/garmin_layer.zip"

echo "═══ Building Garmin Lambda Layer ═══"
echo "  Layer: $LAYER_NAME"
echo "  Packages: garminconnect, garth"
echo ""

# Lambda layers must use python/ subdirectory for Python packages
rm -rf "$BUILD_DIR" && mkdir -p "$BUILD_DIR/python"

echo "Installing garminconnect + garth (linux/x86_64, Python 3.12)..."
pip3 install garminconnect garth \
    -t "$BUILD_DIR/python" \
    --quiet \
    --upgrade \
    --platform manylinux2014_x86_64 \
    --only-binary=:all: \
    --python-version 3.12 \
    --implementation cp \
    --break-system-packages

# Strip unnecessary files to reduce size
find "$BUILD_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR" -name "*.pyc" -delete 2>/dev/null || true
find "$BUILD_DIR" -name "*.dist-info" -type d -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR" -name "bin" -type d -exec rm -rf {} + 2>/dev/null || true

echo "Zipping layer..."
rm -f "$ZIP_FILE"
(cd "$BUILD_DIR" && zip -r "$ZIP_FILE" python/ -q)
echo "  Zip size: $(du -h "$ZIP_FILE" | cut -f1)"

echo "Publishing layer to Lambda..."
LAYER_VERSION_ARN=$(aws lambda publish-layer-version \
    --layer-name "$LAYER_NAME" \
    --description "garminconnect + garth for garmin-data-ingestion (Python 3.12, x86_64)" \
    --zip-file "fileb://$ZIP_FILE" \
    --compatible-runtimes python3.12 \
    --compatible-architectures x86_64 \
    --region "$REGION" \
    --query "LayerVersionArn" \
    --output text \
    --no-cli-pager)

echo ""
echo "═══ Layer Published ═══"
echo "  ARN: $LAYER_VERSION_ARN"
echo ""
echo "Next: attach to garmin-data-ingestion"
echo "  aws lambda update-function-configuration \\"
echo "    --function-name garmin-data-ingestion \\"
echo "    --layers $LAYER_VERSION_ARN \\"
echo "    --region $REGION"
echo ""
echo "Then redeploy garmin WITHOUT deps bundled (just garmin_lambda.py):"
echo "  ./deploy/deploy_lambda.sh garmin-data-ingestion lambdas/garmin_lambda.py"

# Cleanup
rm -rf "$BUILD_DIR" "$ZIP_FILE"
