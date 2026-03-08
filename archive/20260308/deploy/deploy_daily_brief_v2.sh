#!/bin/bash
set -euo pipefail

# Deploy Daily Brief v2.0 Lambda — FIXED
# Fix: zip file as lambda_function.py (handler expects lambda_function.lambda_handler)

cd ~/Documents/Claude/life-platform

REGION="us-west-2"
FUNCTION="daily-brief"

echo "═══════════════════════════════════════════════════"
echo " Daily Brief v2.0 Deployment (fixed)"
echo "═══════════════════════════════════════════════════"
echo ""

# Step 1: Copy source to lambda_function.py and zip
echo "Step 1: Packaging as lambda_function.py..."
cp daily_brief_lambda.py lambda_function.py
rm -f daily_brief_lambda.zip
zip -q daily_brief_lambda.zip lambda_function.py
rm lambda_function.py
echo "  ✅ Packaged (handler: lambda_function.lambda_handler)"

# Step 2: Deploy Lambda code
echo ""
echo "Step 2: Deploying Lambda code..."
aws lambda update-function-code \
    --function-name "$FUNCTION" \
    --zip-file "fileb://daily_brief_lambda.zip" \
    --region "$REGION" > /dev/null
aws lambda wait function-updated --function-name "$FUNCTION" --region "$REGION"
echo "  ✅ Lambda code updated"

# Step 3: Ensure config (timeout + memory)
echo ""
echo "Step 3: Verifying Lambda configuration..."
aws lambda update-function-configuration \
    --function-name "$FUNCTION" \
    --timeout 120 \
    --memory-size 256 \
    --region "$REGION" > /dev/null
aws lambda wait function-updated --function-name "$FUNCTION" --region "$REGION"
echo "  ✅ Timeout: 120s, Memory: 256MB"

# Step 4: Test invoke
echo ""
echo "Step 4: Test invoke (sends real email)..."
aws lambda invoke \
    --function-name "$FUNCTION" \
    --payload '{}' \
    --cli-binary-format raw-in-base64-out \
    --region "$REGION" \
    /tmp/daily-brief-v2-test.json > /dev/null 2>&1

echo "  Response:"
cat /tmp/daily-brief-v2-test.json
echo ""

# Step 5: Check for errors
echo ""
echo "Step 5: Checking logs for errors..."
sleep 8
LOG_GROUP="/aws/lambda/$FUNCTION"
ERRORS=$(aws logs filter-log-events \
    --log-group-name "$LOG_GROUP" \
    --start-time $(python3 -c "import time; print(int((time.time()-30)*1000))") \
    --filter-pattern "ERROR" \
    --region "$REGION" \
    --query 'events[].message' \
    --output text 2>/dev/null)

if [ -z "$ERRORS" ]; then
    echo "  ✅ No errors in logs"
else
    echo "  ⚠️  Errors found:"
    echo "$ERRORS"
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo " ✅ Deploy complete. Check your email for the test brief."
echo "═══════════════════════════════════════════════════"
