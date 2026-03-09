#!/bin/bash
# SIMP-2: Rebuild shared-utils Layer v3 (adds ingestion framework files)
# and redeploy weather Lambda using the new Layer.
# Run: bash deploy/simp2_layer_v3_and_weather.sh

set -euo pipefail

REGION="us-west-2"
LAYER_NAME="life-platform-shared-utils"
WEATHER_FUNCTION="weather-data-ingestion"
BUILD_DIR="/tmp/shared_utils_layer_v3"
ZIP_FILE="/tmp/shared_utils_layer_v3.zip"
LAMBDAS_DIR="$(cd "$(dirname "$0")/../lambdas" && pwd)"

echo "=== Step 1: Rebuild Layer v3 with ingestion framework ==="

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

# Verify all modules exist
for mod in "${SHARED_MODULES[@]}"; do
    [ -f "$LAMBDAS_DIR/$mod" ] || { echo "❌ Missing: $LAMBDAS_DIR/$mod"; exit 1; }
done
echo "All 13 modules found."

rm -rf "$BUILD_DIR" && mkdir -p "$BUILD_DIR/python"
for mod in "${SHARED_MODULES[@]}"; do
    cp "$LAMBDAS_DIR/$mod" "$BUILD_DIR/python/$mod"
done

rm -f "$ZIP_FILE"
(cd "$BUILD_DIR" && zip -j "$ZIP_FILE" python/*.py -q)
echo "Layer zip size: $(du -h "$ZIP_FILE" | cut -f1)"

LAYER_ARN=$(aws lambda publish-layer-version \
    --layer-name "$LAYER_NAME" \
    --description "v3: adds ingestion_framework, ingestion_validator, item_size_guard (2026-03-09)" \
    --zip-file "fileb://$ZIP_FILE" \
    --compatible-runtimes python3.12 \
    --compatible-architectures x86_64 \
    --region "$REGION" \
    --query "LayerVersionArn" \
    --output text)
echo "✅ Layer v3 published: $LAYER_ARN"

rm -rf "$BUILD_DIR" "$ZIP_FILE"

echo ""
echo "=== Step 2: Redeploy weather Lambda with just the handler ==="

WEATHER_ZIP="/tmp/weather_handler_v3.zip"
rm -f "$WEATHER_ZIP"
zip -j "$WEATHER_ZIP" "$LAMBDAS_DIR/weather_handler.py"
echo "Weather zip size: $(du -h "$WEATHER_ZIP" | cut -f1)  (handler only — framework comes from Layer)"

aws lambda update-function-code \
    --function-name "$WEATHER_FUNCTION" \
    --zip-file "fileb://$WEATHER_ZIP" \
    --region "$REGION" \
    --output table \
    --query '{FunctionName: FunctionName, CodeSize: CodeSize}'

aws lambda wait function-updated --function-name "$WEATHER_FUNCTION" --region "$REGION"

# Attach the new layer
aws lambda update-function-configuration \
    --function-name "$WEATHER_FUNCTION" \
    --layers "$LAYER_ARN" \
    --region "$REGION" \
    --output table \
    --query '{FunctionName: FunctionName, Layers: Layers[0].Arn}'

aws lambda wait function-updated --function-name "$WEATHER_FUNCTION" --region "$REGION"
echo "✅ weather-data-ingestion now using Layer v3"

echo ""
echo "=== Step 3: Smoke test ==="
aws lambda invoke \
    --function-name "$WEATHER_FUNCTION" \
    --region "$REGION" \
    --log-type Tail \
    --output json \
    /tmp/weather_v3_out.json \
    | python3 -c "
import sys, json, base64
d = json.load(sys.stdin)
log = base64.b64decode(d.get('LogResult', '')).decode('utf-8', errors='replace')
lines = [l for l in log.split('\n') if l.strip()]
for l in lines[-8:]: print(l)
"

python3 -c "
import json
with open('/tmp/weather_v3_out.json') as f:
    d = json.load(f)
body = json.loads(d.get('body', '{}'))
print(f'\nStatus: {d.get(\"statusCode\")} | Records: {body.get(\"records_written\")} | Errors: {body.get(\"errors\")}')
warnings = [v for v in body.get('results', {}).values() if isinstance(v, str) and 'error' in v]
if warnings:
    print(f'Warnings: {warnings}')
else:
    print('No errors or DATA-2 warnings ✅')
"

echo ""
echo "=== SIMP-2 Layer v3 complete ==="
echo "Next step: SIMP-2 Phase 2 — attach this Layer to weather"
echo "then migrate whoop, strava, garmin handlers."
echo ""
echo "Layer ARN for future attaches: $LAYER_ARN"
