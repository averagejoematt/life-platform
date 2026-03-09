#!/usr/bin/env bash
set -euo pipefail

# Deploy caffeine_mg field to health-auto-export-webhook Lambda

FUNC="health-auto-export-webhook"
REGION="us-west-2"
DIR="$(cd "$(dirname "$0")" && pwd)"
WORK="/tmp/caffeine-deploy"

echo "=== Caffeine Tracking Deploy ==="
echo ""

# Step 1: Download current Lambda
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

# Step 2: Patch
echo "Step 2: Applying caffeine patch..."
cp "$DIR/patch_caffeine.py" src/
cd src
python3 patch_caffeine.py
rm -f patch_caffeine.py
cd ..
echo "  ✅ Patched"

# Step 3: Verify
echo "Step 3: Verifying..."
PATCHED_FILE="src/health_auto_export_lambda.py"
[ ! -f "$PATCHED_FILE" ] && PATCHED_FILE="src/lambda_function.py"
if grep -q "caffeine_mg" "$PATCHED_FILE"; then
    echo "  ✅ caffeine_mg field found"
else
    echo "  ❌ caffeine_mg NOT found — patch failed"
    exit 1
fi

# Step 4: Package
echo "Step 4: Packaging..."
cd src
zip -qr ../deploy.zip .
cd ..
echo "  ✅ Packaged ($(du -h deploy.zip | cut -f1))"

# Step 5: Deploy
echo "Step 5: Deploying..."
aws lambda update-function-code \
  --function-name "$FUNC" \
  --region "$REGION" \
  --zip-file fileb://deploy.zip \
  --query '[FunctionName, LastModified, CodeSize]' \
  --output table

echo ""
echo "Step 6: Verifying deployment..."
sleep 2
aws lambda get-function-configuration \
  --function-name "$FUNC" \
  --region "$REGION" \
  --query '[LastModified, MemorySize, Timeout]' \
  --output table

# Copy back for local reference
cp "$PATCHED_FILE" "$DIR/health_auto_export_lambda.py"
echo "  ✅ Local copy updated"

echo ""
echo "=== ✅ Caffeine tracking deployed ==="
echo "Log a coffee in your water app → Apple Health → webhook → DynamoDB caffeine_mg"
echo "Verify after next webhook push:"
echo "  aws dynamodb get-item --table-name life-platform --key '{\"pk\":{\"S\":\"USER#matthew#SOURCE#apple_health\"},\"sk\":{\"S\":\"DATE#2026-02-26\"}}' --query 'Item.caffeine_mg' --output text"
