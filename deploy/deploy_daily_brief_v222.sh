#!/bin/bash
set -euo pipefail

# Deploy Daily Brief v2.2.2 — Strava Activity Deduplication
# Fixes: Multi-device duplicate activities (WHOOP + Garmin recording same walk)
# Affects: Training report display, movement scoring, AI prompts

cd ~/Documents/Claude/life-platform

REGION="us-west-2"
FUNCTION="daily-brief"

echo "═══════════════════════════════════════════════════"
echo " Daily Brief v2.2.2 — Activity Dedup"
echo " Same sport + <15min gap → keep richer record"
echo "═══════════════════════════════════════════════════"
echo ""

# Step 1: Apply patch
echo "Step 1: Applying patch..."
python3 patch_activity_dedup.py
echo ""

# Step 2: Package
echo "Step 2: Packaging..."
cp daily_brief_lambda.py lambda_function.py
rm -f daily_brief_lambda.zip
zip -q daily_brief_lambda.zip lambda_function.py
rm lambda_function.py
echo "  ✅ Packaged"

# Step 3: Deploy code
echo "Step 3: Deploying Lambda code..."
aws lambda update-function-code \
    --function-name "$FUNCTION" \
    --zip-file "fileb://daily_brief_lambda.zip" \
    --region "$REGION" > /dev/null
aws lambda wait function-updated --function-name "$FUNCTION" --region "$REGION"
echo "  ✅ Code updated"

# Step 4: Test invoke
echo "Step 4: Test invoke (sends real email)..."
aws lambda invoke \
    --function-name "$FUNCTION" \
    --payload '{}' \
    --cli-binary-format raw-in-base64-out \
    --region "$REGION" \
    /tmp/daily-brief-v222-test.json > /dev/null 2>&1

echo "  Response:"
cat /tmp/daily-brief-v222-test.json
echo ""

# Step 5: Check for errors + dedup log
echo ""
echo "Step 5: Checking logs..."
sleep 12
LOGS=$(aws logs filter-log-events \
    --log-group-name "/aws/lambda/$FUNCTION" \
    --start-time $(python3 -c "import time; print(int((time.time()-60)*1000))") \
    --filter-pattern "Dedup" \
    --region "$REGION" \
    --query 'events[].message' \
    --output text 2>/dev/null)

if [ -n "$LOGS" ]; then
    echo "  🔀 Dedup activity:"
    echo "$LOGS"
else
    echo "  ℹ️  No duplicates found (or no Strava data)"
fi

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
echo " ✅ v2.2.2 deployed. Check email — duplicate walk"
echo "   should be gone from Training Report."
echo "═══════════════════════════════════════════════════"
