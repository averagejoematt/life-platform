#!/bin/bash
# SIMP-2: Rebuild Layer v4 with correct zip structure (python/ subdir preserved)
# and redeploy weather Lambda.
# Root cause: previous builds used `zip -j` which strips python/ prefix.
# Lambda Layers require files at python/*.py inside the zip.
# Run: bash deploy/simp2_layer_v4_fixed.sh

set -euo pipefail

REGION="us-west-2"
LAYER_NAME="life-platform-shared-utils"
WEATHER_FUNCTION="weather-data-ingestion"
BUILD_DIR="/tmp/shared_utils_layer_v4"
ZIP_FILE="/tmp/shared_utils_layer_v4.zip"
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
    "ingestion_framework.py"
    "ingestion_validator.py"
    "item_size_guard.py"
)

echo "=== Step 1: Rebuild Layer v4 (correct zip structure) ==="

for mod in "${SHARED_MODULES[@]}"; do
    [ -f "$LAMBDAS_DIR/$mod" ] || { echo "❌ Missing: $LAMBDAS_DIR/$mod"; exit 1; }
done
echo "All ${#SHARED_MODULES[@]} modules found."

rm -rf "$BUILD_DIR" && mkdir -p "$BUILD_DIR/python"
for mod in "${SHARED_MODULES[@]}"; do
    cp "$LAMBDAS_DIR/$mod" "$BUILD_DIR/python/$mod"
done

rm -f "$ZIP_FILE"
# CRITICAL: -r not -j — preserves python/ directory so Lambda can find modules
(cd "$BUILD_DIR" && zip -r "$ZIP_FILE" python/ -q)
echo "Layer zip size: $(du -h "$ZIP_FILE" | cut -f1)"

# Verify structure
echo "Zip contents (first 5):"
unzip -l "$ZIP_FILE" | grep "\.py" | head -5

LAYER_ARN=$(aws lambda publish-layer-version \
    --layer-name "$LAYER_NAME" \
    --description "v4: correct python/ zip structure; adds ingestion_framework, ingestion_validator, item_size_guard (2026-03-09)" \
    --zip-file "fileb://$ZIP_FILE" \
    --compatible-runtimes python3.12 \
    --compatible-architectures x86_64 \
    --region "$REGION" \
    --query "LayerVersionArn" \
    --output text)
echo "✅ Layer v4 published: $LAYER_ARN"

rm -rf "$BUILD_DIR" "$ZIP_FILE"

echo ""
echo "=== Step 2: Attach Layer v4 to weather Lambda ==="

WEATHER_ZIP="/tmp/weather_handler_final.zip"
rm -f "$WEATHER_ZIP"
zip -j "$WEATHER_ZIP" "$LAMBDAS_DIR/weather_handler.py"
echo "Weather zip size: $(du -h "$WEATHER_ZIP" | cut -f1)"

aws lambda update-function-code \
    --function-name "$WEATHER_FUNCTION" \
    --zip-file "fileb://$WEATHER_ZIP" \
    --region "$REGION" \
    --output table \
    --query '{FunctionName: FunctionName, CodeSize: CodeSize}'

aws lambda wait function-updated --function-name "$WEATHER_FUNCTION" --region "$REGION"

aws lambda update-function-configuration \
    --function-name "$WEATHER_FUNCTION" \
    --layers "$LAYER_ARN" \
    --region "$REGION" \
    --output table \
    --query '{FunctionName: FunctionName, Layers: Layers[0].Arn}'

aws lambda wait function-updated --function-name "$WEATHER_FUNCTION" --region "$REGION"
echo "✅ weather-data-ingestion on Layer v4"

echo ""
echo "=== Step 3: Smoke test ==="
aws lambda invoke \
    --function-name "$WEATHER_FUNCTION" \
    --region "$REGION" \
    --log-type Tail \
    --output json \
    /tmp/weather_v4_out.json \
    | python3 -c "
import sys, json, base64
d = json.load(sys.stdin)
log = base64.b64decode(d.get('LogResult', '')).decode('utf-8', errors='replace')
lines = [l for l in log.split('\n') if l.strip()]
for l in lines[-10:]: print(l)
"
python3 -c "
import json
with open('/tmp/weather_v4_out.json') as f:
    d = json.load(f)
body = json.loads(d.get('body', '{}'))
print(f'\nStatus: {d.get(\"statusCode\")} | Records: {body.get(\"records_written\")} | Errors: {body.get(\"errors\")}')
if 'DATA-2' in str(body):
    print('⚠️  DATA-2 warning present')
else:
    print('✅ No DATA-2 warnings')
"

echo ""
echo "Layer ARN (use for Phase 2 Lambdas): $LAYER_ARN"
