#!/usr/bin/env bash
set -euo pipefail

# Deploy Daily Brief v2.3.0 — CGM Enhancement + Gait Section
# Patches the existing Lambda with CGM fasting proxy, hypo flag, 7-day trend,
# and new Gait & Mobility section.

FUNC="daily-brief"
REGION="us-west-2"
DIR="$(cd "$(dirname "$0")" && pwd)"
WORK="/tmp/daily-brief-v23-deploy"

echo "=== Daily Brief v2.3.0 Deploy ==="
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
echo "  ✅ Downloaded and extracted"

# Step 2: Patch
echo "Step 2: Applying v2.3.0 patch..."
cp "$DIR/patch_daily_brief_v23.py" src/
cd src
python3 patch_daily_brief_v23.py
rm -f patch_daily_brief_v23.py
cd ..
echo "  ✅ Patched"

# Step 3: Verify patch applied
echo "Step 3: Verifying patch..."
PATCHED_FILE="src/lambda_function.py"
[ ! -f "$PATCHED_FILE" ] && PATCHED_FILE="src/daily_brief_lambda.py"
if grep -q "Gait & Mobility" "$PATCHED_FILE"; then
    echo "  ✅ Gait section found"
else
    echo "  ❌ Gait section NOT found — patch failed"
    exit 1
fi
if grep -q "Overnight Low" "$PATCHED_FILE"; then
    echo "  ✅ CGM fasting proxy found"
else
    echo "  ❌ CGM fasting proxy NOT found — patch failed"
    exit 1
fi
if grep -q "v2.3.0" "$PATCHED_FILE"; then
    echo "  ✅ Version bumped to v2.3.0"
else
    echo "  ❌ Version not bumped"
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

# Step 7: Copy patched source back for local reference
if [ -f src/lambda_function.py ]; then
    cp src/lambda_function.py "$DIR/daily_brief_lambda.py"
else
    cp src/daily_brief_lambda.py "$DIR/daily_brief_lambda.py"
fi
echo "  ✅ Local copy updated"

echo ""
echo "=== ✅ Daily Brief v2.3.0 deployed ==="
echo ""
echo "Changes:"
echo "  - CGM Spotlight: fasting proxy, hypo flag, 7-day trend arrow"
echo "  - New: Gait & Mobility section (speed, step length, asymmetry, double support)"
echo "  - AI prompt: gait data + overnight low context"
echo "  - 14 → 15 sections"
echo ""
echo "Test: Wait for tomorrow's 10 AM brief or invoke manually:"
echo "  aws lambda invoke --function-name daily-brief --region us-west-2 /tmp/brief-test.json && cat /tmp/brief-test.json"
