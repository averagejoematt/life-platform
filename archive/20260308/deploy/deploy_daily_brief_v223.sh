#!/bin/bash
set -euo pipefail

# Deploy Daily Brief v2.2.3 — Activity Dedup + Demo Mode
# Chains: v2.2.2 (dedup patch) → v2.2.3 (demo mode patch)
# New: invoke with {"demo_mode": true} for sanitized shareable version

cd ~/Documents/Claude/life-platform

REGION="us-west-2"
FUNCTION="daily-brief"

echo "═══════════════════════════════════════════════════"
echo " Daily Brief v2.2.3 — Dedup + Demo Mode"
echo " Chain: v2.2.1 → v2.2.2 (dedup) → v2.2.3 (demo)"
echo "═══════════════════════════════════════════════════"
echo ""

# Step 0: Seed demo mode rules to profile
echo "Step 0: Seeding demo_mode_rules to profile..."
python3 seed_demo_mode_rules.py
echo ""

# Step 1: Apply dedup patch (v2.2.2)
echo "Step 1: Applying dedup patch..."
python3 patch_activity_dedup.py
echo ""

# Step 2: Apply demo mode patch (v2.2.3)
echo "Step 2: Applying demo mode patch..."
python3 patch_demo_mode.py
echo ""

# Step 3: Package
echo "Step 3: Packaging..."
cp daily_brief_lambda.py lambda_function.py
rm -f daily_brief_lambda.zip
zip -q daily_brief_lambda.zip lambda_function.py
rm lambda_function.py
echo "  ✅ Packaged"

# Step 4: Deploy
echo "Step 4: Deploying Lambda code..."
aws lambda update-function-code \
    --function-name "$FUNCTION" \
    --zip-file "fileb://daily_brief_lambda.zip" \
    --region "$REGION" > /dev/null
aws lambda wait function-updated --function-name "$FUNCTION" --region "$REGION"
echo "  ✅ Code updated"

# Step 5: Test normal invoke
echo "Step 5: Test normal invoke (sends real email)..."
aws lambda invoke \
    --function-name "$FUNCTION" \
    --payload '{}' \
    --cli-binary-format raw-in-base64-out \
    --region "$REGION" \
    /tmp/daily-brief-v223-normal.json > /dev/null 2>&1
echo "  Normal response:"
cat /tmp/daily-brief-v223-normal.json
echo ""

# Step 6: Test demo invoke
echo ""
echo "Step 6: Test DEMO invoke (sends sanitized email)..."
aws lambda invoke \
    --function-name "$FUNCTION" \
    --payload '{"demo_mode": true}' \
    --cli-binary-format raw-in-base64-out \
    --region "$REGION" \
    /tmp/daily-brief-v223-demo.json > /dev/null 2>&1
echo "  Demo response:"
cat /tmp/daily-brief-v223-demo.json
echo ""

# Step 7: Check for errors
echo ""
echo "Step 7: Checking logs..."
sleep 12
ERRORS=$(aws logs filter-log-events \
    --log-group-name "/aws/lambda/$FUNCTION" \
    --start-time $(python3 -c "import time; print(int((time.time()-120)*1000))") \
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

DEMO_LOG=$(aws logs filter-log-events \
    --log-group-name "/aws/lambda/$FUNCTION" \
    --start-time $(python3 -c "import time; print(int((time.time()-120)*1000))") \
    --filter-pattern "DEMO" \
    --region "$REGION" \
    --query 'events[].message' \
    --output text 2>/dev/null)

if [ -n "$DEMO_LOG" ]; then
    echo "  🔒 Demo mode log:"
    echo "$DEMO_LOG"
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo " ✅ v2.2.3 deployed!"
echo ""
echo " Check your email for TWO briefs:"
echo "   1. Normal version (real data)"
echo "   2. [DEMO] version (sanitized for sharing)"
echo ""
echo " To send a demo anytime:"
echo "   aws lambda invoke --function-name daily-brief \\"
echo "     --payload '{\"demo_mode\": true}' \\"
echo "     --cli-binary-format raw-in-base64-out \\"
echo "     --region us-west-2 /tmp/demo.json"
echo ""
echo " To update rules (no deploy needed):"
echo "   Edit demo_mode_rules in DynamoDB profile"
echo "═══════════════════════════════════════════════════"
