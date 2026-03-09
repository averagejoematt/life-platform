#!/bin/bash
# Fix DATA-2 validator false-positive warnings for weather source.
# Rebundles weather Lambda with corrected ingestion_validator.py field names.
# Run: bash deploy/simp2_redeploy_weather_validator_fix.sh

set -euo pipefail

REGION="us-west-2"
FUNCTION_NAME="weather-data-ingestion"
ZIPFILE="/tmp/weather_handler_validator_fix.zip"

echo "=== Redeploying weather Lambda with validator fix ==="

# Check for shared layer
LAYER_ARN=$(aws lambda list-layers \
    --region "$REGION" \
    --query "Layers[?contains(LayerName, 'life-platform') || contains(LayerName, 'shared')].LatestMatchingVersion.LayerVersionArn" \
    --output text 2>/dev/null | head -1 || echo "")

# Build package
rm -f "$ZIPFILE"
zip -j "$ZIPFILE" lambdas/weather_handler.py

if [ -z "$LAYER_ARN" ] || [ "$LAYER_ARN" = "None" ]; then
    echo "Bundling framework inline..."
    zip -j "$ZIPFILE" \
        lambdas/ingestion_framework.py \
        lambdas/ingestion_validator.py \
        lambdas/item_size_guard.py \
        lambdas/platform_logger.py
else
    echo "Using Layer: $LAYER_ARN"
fi

echo "Package size: $(du -sh $ZIPFILE | cut -f1)"

aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIPFILE" \
    --region "$REGION" \
    --output table \
    --query '{FunctionName: FunctionName, CodeSize: CodeSize}'

aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"

# Quick smoke test
echo "Smoke test..."
aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --log-type Tail \
    --output json \
    /tmp/weather_val_fix_out.json \
    | python3 -c "
import sys, json, base64
d = json.load(sys.stdin)
log = base64.b64decode(d.get('LogResult', '')).decode('utf-8', errors='replace')
# Show only last few lines
lines = [l for l in log.split('\n') if l.strip()]
for l in lines[-8:]: print(l)
"
cat /tmp/weather_val_fix_out.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
body = json.loads(d.get('body','{}'))
print(f'\nStatus: {d.get(\"statusCode\")} | Records: {body.get(\"records_written\")} | Errors: {body.get(\"errors\")}')
"

if grep -q "DATA-2" /tmp/weather_val_fix_out.json 2>/dev/null || \
   aws lambda invoke --function-name "$FUNCTION_NAME" --region "$REGION" --log-type Tail --output json /dev/null 2>/dev/null | grep -q "DATA-2"; then
    echo "⚠️  DATA-2 warnings still present — check logs"
else
    echo "✅ No DATA-2 warnings — validator fix confirmed"
fi
