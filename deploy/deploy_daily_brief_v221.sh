#!/bin/bash
set -euo pipefail

# Deploy Daily Brief v2.2.1 — Day Grade Zero-Score Fix
# Fixes: journal returns None (not 0) when no entries,
#        hydration treats <118ml as "not tracked" (Apple Health noise)
# Algorithm version: 1.0 → 1.1

cd ~/Documents/Claude/life-platform

REGION="us-west-2"
FUNCTION="daily-brief"

echo "═══════════════════════════════════════════════════"
echo " Daily Brief v2.2.1 — Day Grade Zero-Score Fix"
echo " Journal: None when no entries"
echo " Hydration: <118ml (4oz) = not tracked"
echo "═══════════════════════════════════════════════════"
echo ""

# Step 1: Apply patch
echo "Step 1: Applying patch..."
python3 patch_day_grade_zero_score.py
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
    /tmp/daily-brief-v221-test.json > /dev/null 2>&1

echo "  Response:"
cat /tmp/daily-brief-v221-test.json
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

# Step 6: Verify grade improvement
echo ""
echo "Step 6: Check new day grade vs old..."
echo "  Old grade (Feb 24): 69 C+ (journal=0, hydration=0 included)"
echo "  Expected: ~77 B (journal & hydration excluded from average)"
echo "  Check your email for the updated brief."

echo ""
echo "═══════════════════════════════════════════════════"
echo " ✅ v2.2.1 deployed. Algorithm version 1.1."
echo "   Journal/hydration no longer drag grade to 0."
echo "═══════════════════════════════════════════════════"
