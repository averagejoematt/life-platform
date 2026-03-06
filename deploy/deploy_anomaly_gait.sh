#!/usr/bin/env bash
set -euo pipefail

# Deploy anomaly detector v1.1.0 — add gait metrics

FUNC="anomaly-detector"
REGION="us-west-2"
DIR="$(cd "$(dirname "$0")" && pwd)"
WORK="/tmp/anomaly-gait-deploy"

echo "=== Anomaly Detector v1.1.0 — Gait Metrics ==="
echo ""

echo "Step 1: Downloading current Lambda..."
rm -rf "$WORK" && mkdir -p "$WORK"
CODE_URL=$(aws lambda get-function \
  --function-name "$FUNC" \
  --region "$REGION" \
  --query 'Code.Location' --output text)
curl -sL "$CODE_URL" -o "$WORK/current.zip"
cd "$WORK"
unzip -qo current.zip -d src/
echo "  ✅ Downloaded"

echo "Step 2: Applying gait patch..."
cp "$DIR/patch_anomaly_gait.py" src/
cd src
python3 patch_anomaly_gait.py
rm -f patch_anomaly_gait.py
cd ..
echo "  ✅ Patched"

echo "Step 3: Verifying..."
PATCHED_FILE="src/anomaly_detector_lambda.py"
[ ! -f "$PATCHED_FILE" ] && PATCHED_FILE="src/lambda_function.py"
if grep -q "walking_speed_mph" "$PATCHED_FILE" && grep -q "walking_asymmetry_pct" "$PATCHED_FILE"; then
    echo "  ✅ Gait metrics found"
else
    echo "  ❌ Gait metrics NOT found — patch failed"
    exit 1
fi

echo "Step 4: Packaging..."
cd src
zip -qr ../deploy.zip .
cd ..
echo "  ✅ Packaged ($(du -h deploy.zip | cut -f1))"

echo "Step 5: Deploying..."
aws lambda update-function-code \
  --function-name "$FUNC" \
  --region "$REGION" \
  --zip-file fileb://deploy.zip \
  --query '[FunctionName, LastModified, CodeSize]' \
  --output table

sleep 2
aws lambda get-function-configuration \
  --function-name "$FUNC" \
  --region "$REGION" \
  --query '[LastModified, MemorySize, Timeout]' \
  --output table

cp "$PATCHED_FILE" "$DIR/anomaly_detector_lambda.py"
echo "  ✅ Local copy updated"

echo ""
echo "=== ✅ Anomaly Detector v1.1.0 deployed (11 metrics) ==="
echo "New: walking_speed_mph + walking_asymmetry_pct"
echo "Note: Needs 7+ days of gait baseline before flagging anomalies"
