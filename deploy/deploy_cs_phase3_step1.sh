#!/bin/bash
# Deploy script: Character Sheet Phase 3 — Step 1
# Fix avatar weight fallback + deploy Daily Brief Lambda with _build_avatar_data()
# Version: v2.69.0
# Date: 2026-03-04

set -e

echo "=== Character Sheet Phase 3 Step 1: Daily Brief Avatar Fix ==="
echo ""

# --- Step 1: Deploy Daily Brief Lambda ---
echo "[1/3] Packaging Daily Brief Lambda..."
cd ~/Documents/Claude/life-platform/lambdas

# Clean up any old zip
rm -f daily_brief_lambda.zip

# Package as lambda_function.py (CRITICAL: handler expects this name)
cp daily_brief_lambda.py lambda_function.py
zip daily_brief_lambda.zip lambda_function.py
rm lambda_function.py

echo "       Zip created: $(du -h daily_brief_lambda.zip | cut -f1)"

echo "[2/3] Deploying Daily Brief Lambda..."
aws lambda update-function-code \
    --function-name daily-brief \
    --zip-file fileb://daily_brief_lambda.zip \
    --region us-west-2 \
    --no-cli-pager

echo "       Waiting 10s for propagation..."
sleep 10

echo "[3/3] Verifying deployment..."
LAST_MOD=$(aws lambda get-function-configuration \
    --function-name daily-brief \
    --region us-west-2 \
    --query 'LastModified' \
    --output text \
    --no-cli-pager)
echo "       daily-brief LastModified: $LAST_MOD"

# --- Done ---
echo ""
echo "=== Deploy Complete ==="
echo ""
echo "What changed:"
echo "  1. _build_avatar_data() now deployed (was missing since v2.64.0)"
echo "  2. Avatar weight uses 30-day lookback (was 7-day, fell back to 302)"
echo "  3. Dashboard + buddy JSON now receive proper avatar state"
echo ""
echo "Verify tomorrow's Daily Brief:"
echo "  - Check dash.averagejoematt.com → avatar should show Foundation tier, frame 1"
echo "  - Check buddy.averagejoematt.com → avatar tile should render"
echo "  - data.json should have 'avatar' key with tier/body_frame/badges"
echo ""
echo "Optional: Test invoke to verify avatar data in output:"
echo "  aws lambda invoke --function-name daily-brief --payload '{}' --region us-west-2 /tmp/brief-test.json --no-cli-pager"
