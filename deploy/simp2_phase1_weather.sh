#!/bin/bash
# SIMP-2 Phase 1: Migrate weather Lambda to ingestion framework (proof of concept)
# Deploys weather_handler.py alongside the existing weather_lambda.py.
# Old Lambda is NOT deleted — runs in parallel for 2 weeks, then cutover.
# Run: bash deploy/simp2_phase1_weather.sh

set -euo pipefail

REGION="us-west-2"
FUNCTION_NAME="weather-data-ingestion"
LAYER_ARN=$(aws lambda list-layers \
    --region "$REGION" \
    --query "Layers[?LayerName=='life-platform-shared'].LatestMatchingVersion.LayerVersionArn" \
    --output text 2>/dev/null || echo "")

ZIPFILE="/tmp/weather_handler_simp2.zip"

echo "=== SIMP-2 Phase 1: Weather Lambda → ingestion framework ==="

# ── 1. Check Lambda exists ────────────────────────────────────────────────────
echo "[1/5] Verifying Lambda exists..."
CURRENT_HANDLER=$(aws lambda get-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --query "Handler" --output text)
echo "  Current handler: $CURRENT_HANDLER"
echo "  Target handler:  weather_handler.lambda_handler"

# ── 2. Archive the old Lambda file ───────────────────────────────────────────
echo "[2/5] Archiving old weather_lambda.py..."
if [ -f lambdas/weather_lambda.py ]; then
    cp lambdas/weather_lambda.py lambdas/weather_lambda.py.archived
    echo "  Archived to lambdas/weather_lambda.py.archived"
else
    echo "  lambdas/weather_lambda.py not found — skipping archive"
fi

# ── 3. Build new package ──────────────────────────────────────────────────────
echo "[3/5] Building package with weather_handler.py..."
rm -f "$ZIPFILE"

# Handler file
zip -j "$ZIPFILE" lambdas/weather_handler.py

# Include ingestion_framework.py if NOT in a Lambda Layer
if [ -z "$LAYER_ARN" ]; then
    echo "  WARNING: life-platform-shared layer not found — bundling framework inline"
    zip -j "$ZIPFILE" lambdas/ingestion_framework.py
    # Also bundle dependencies the framework needs
    [ -f lambdas/ingestion_validator.py ]  && zip -j "$ZIPFILE" lambdas/ingestion_validator.py
    [ -f lambdas/item_size_guard.py ]      && zip -j "$ZIPFILE" lambdas/item_size_guard.py
    [ -f lambdas/platform_logger.py ]      && zip -j "$ZIPFILE" lambdas/platform_logger.py
    echo "  Bundled framework inline (add to Layer in SIMP-2 Phase 2)"
else
    echo "  Using Lambda Layer: $LAYER_ARN"
fi

echo "  Package size: $(du -sh $ZIPFILE | cut -f1)"

# ── 4. Update function code + handler ─────────────────────────────────────────
echo "[4/5] Deploying..."

aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIPFILE" \
    --region "$REGION" \
    --output table \
    --query '{FunctionName: FunctionName, CodeSize: CodeSize, LastModified: LastModified}'

aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"

# Update handler name from weather_lambda.lambda_handler → weather_handler.lambda_handler
aws lambda update-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --handler "weather_handler.lambda_handler" \
    --region "$REGION" \
    --output table \
    --query '{FunctionName: FunctionName, Handler: Handler, LastModified: LastModified}'

aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
echo "  Handler updated to weather_handler.lambda_handler"

# ── 5. Smoke test ─────────────────────────────────────────────────────────────
echo "[5/5] Smoke test — invoking with no payload..."
aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --log-type Tail \
    --output json \
    /tmp/weather_simp2_out.json \
    | python3 -c "
import sys, json, base64
d = json.load(sys.stdin)
log = base64.b64decode(d.get('LogResult', '')).decode('utf-8', errors='replace')
print('=== Log tail ===')
print(log[-2000:])
"

STATUS=$(python3 -c "
import json
with open('/tmp/weather_simp2_out.json') as f:
    d = json.load(f)
body = json.loads(d.get('body', '{}'))
print(f'Status: {d.get(\"statusCode\", \"?\")}')
print(f'Body:   {json.dumps(body, indent=2)}')
")
echo "$STATUS"

echo ""
echo "=== SIMP-2 Phase 1 complete ==="
echo ""
echo "Next steps:"
echo "  1. Verify DDB record written: check DynamoDB life-platform for"
echo "     pk=USER#matthew#SOURCE#weather sk=DATE#$(date +%Y-%m-%d)"
echo "  2. Monitor for 2 weeks — old weather_lambda.py.archived as rollback"
echo "  3. Proceed to SIMP-2 Phase 2: whoop, strava, garmin"
echo ""
echo "ci/lambda_map.json update needed:"
echo "  'weather-data-ingestion': 'lambdas/weather_handler.py'"
