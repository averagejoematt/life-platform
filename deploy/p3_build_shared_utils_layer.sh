#!/bin/bash
# p3_build_shared_utils_layer.sh — Build and publish life-platform-shared-utils Lambda Layer
#
# Bundles the shared Python utility modules used across multiple Lambdas:
#   - retry_utils.py      (Anthropic API retry + CloudWatch metrics)
#   - board_loader.py     (Board of Directors S3 config loader)
#   - insight_writer.py   (DynamoDB insight persistence)
#   - scoring_engine.py   (Character sheet scoring — used by daily-brief + cs-compute)
#
# BENEFITS:
#   - Lambdas no longer need --extra-files for these modules
#   - Single place to update shared code (publish new layer version + attach)
#   - Reduces zip sizes and deploy complexity
#
# IMPORTANT: After attaching this layer, remove these files from Lambda zips.
# Use deploy_unified.sh — it handles extras correctly.
#
# Layer name: life-platform-shared-utils

set -euo pipefail
chmod +x "$0"
REGION="us-west-2"
LAYER_NAME="life-platform-shared-utils"
BUILD_DIR="/tmp/shared_utils_layer_build"
ZIP_FILE="/tmp/shared_utils_layer.zip"

LAMBDAS_DIR="$(cd "$(dirname "$0")/../lambdas" && pwd)"

SHARED_MODULES=(
    "retry_utils.py"
    "board_loader.py"
    "insight_writer.py"
    "scoring_engine.py"
    "character_engine.py"
    "output_writers.py"
    "ai_calls.py"
    "html_builder.py"
    "ai_output_validator.py"
    "platform_logger.py"
)

echo "═══ Building Shared Utils Lambda Layer ═══"
echo "  Layer: $LAYER_NAME"
echo "  Modules: ${SHARED_MODULES[*]}"
echo ""

# Verify all source modules exist
for mod in "${SHARED_MODULES[@]}"; do
    if [ ! -f "$LAMBDAS_DIR/$mod" ]; then
        echo "❌ Missing: $LAMBDAS_DIR/$mod"
        exit 1
    fi
    echo "  ✓ Found: $mod"
done

# Lambda Python layers use python/ subdirectory
rm -rf "$BUILD_DIR" && mkdir -p "$BUILD_DIR/python"

# Copy shared modules into layer
for mod in "${SHARED_MODULES[@]}"; do
    cp "$LAMBDAS_DIR/$mod" "$BUILD_DIR/python/$mod"
    echo "  + $mod"
done

# Syntax check each module
for mod in "${SHARED_MODULES[@]}"; do
    python3 -c "import py_compile; py_compile.compile('$BUILD_DIR/python/$mod', doraise=True)" \
        && echo "  ✓ Syntax OK: $mod" \
        || { echo "❌ Syntax error: $mod"; exit 1; }
done

echo ""
echo "Building zip..."
rm -f "$ZIP_FILE"
(cd "$BUILD_DIR" && zip -j "$ZIP_FILE" python/*.py -q)
echo "  Zip size: $(du -h "$ZIP_FILE" | cut -f1)"

echo "Publishing layer..."
LAYER_VERSION_ARN=$(aws lambda publish-layer-version \
    --layer-name "$LAYER_NAME" \
    --description "Shared utils: retry_utils, board_loader, insight_writer, scoring_engine, character_engine, output_writers, ai_calls, html_builder, ai_output_validator (Python 3.12)" \
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
echo "Next: attach to all AI/compute Lambdas."
echo "Run p3_attach_shared_utils_layer.sh with the ARN above."
echo ""
echo "  LAYER_ARN=\"$LAYER_VERSION_ARN\""

rm -rf "$BUILD_DIR" "$ZIP_FILE"
