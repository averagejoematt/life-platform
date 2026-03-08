#!/bin/bash
set -euo pipefail

# Deploy Daily Brief v2.2 Lambda
# Changes: AI-powered Guidance, Hevy in Training Report, TL;DR line,
#          weight weekly delta, sleep architecture, nutrition meal timing

cd ~/Documents/Claude/life-platform

REGION="us-west-2"
FUNCTION="daily-brief"

echo "═══════════════════════════════════════════════════"
echo " Daily Brief v2.2 Deployment"
echo " AI Guidance, Hevy Training, TL;DR, Weight Delta"
echo "═══════════════════════════════════════════════════"
echo ""

# Step 1: Package as lambda_function.py
echo "Step 1: Packaging..."
cp daily_brief_lambda.py lambda_function.py
rm -f daily_brief_lambda.zip
zip -q daily_brief_lambda.zip lambda_function.py
rm lambda_function.py
echo "  ✅ Packaged"

# Step 2: Deploy code
echo "Step 2: Deploying Lambda code..."
aws lambda update-function-code \
    --function-name "$FUNCTION" \
    --zip-file "fileb://daily_brief_lambda.zip" \
    --region "$REGION" > /dev/null
aws lambda wait function-updated --function-name "$FUNCTION" --region "$REGION"
echo "  ✅ Code updated"

# Step 3: Config — 4 AI calls now (BoD, Training+Nutrition, Journal Coach, Guidance)
echo "Step 3: Updating config (timeout 210s for 4 AI calls)..."
aws lambda update-function-configuration \
    --function-name "$FUNCTION" \
    --timeout 210 \
    --memory-size 256 \
    --region "$REGION" > /dev/null
aws lambda wait function-updated --function-name "$FUNCTION" --region "$REGION"
echo "  ✅ Timeout: 210s, Memory: 256MB"

# Step 4: Test invoke
echo "Step 4: Test invoke (sends real email)..."
aws lambda invoke \
    --function-name "$FUNCTION" \
    --payload '{}' \
    --cli-binary-format raw-in-base64-out \
    --region "$REGION" \
    /tmp/daily-brief-v22-test.json > /dev/null 2>&1

echo "  Response:"
cat /tmp/daily-brief-v22-test.json
echo ""

# Step 5: Check for errors
echo ""
echo "Step 5: Checking logs..."
sleep 12
ERRORS=$(aws logs filter-log-events \
    --log-group-name "/aws/lambda/$FUNCTION" \
    --start-time $(python3 -c "import time; print(int((time.time()-60)*1000))") \
    --filter-pattern "ERROR" \
    --region "$REGION" \
    --query 'events[].message' \
    --output text 2>/dev/null)

if [ -z "$ERRORS" ]; then
    echo "  ✅ No errors"
else
    echo "  ⚠️  Errors:"
    echo "$ERRORS"
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo " ✅ v2.2 deployed. Check email for upgraded brief."
echo "═══════════════════════════════════════════════════"
