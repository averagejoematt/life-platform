#!/bin/bash
# Deploy script: Character Sheet Phase 3 — Step 2
# Add inline avatar PNG to Daily Brief email
# Version: v2.69.0 (amendment)
# Date: 2026-03-04

set -e

echo "=== CS Phase 3 Step 2: Inline Avatar in Daily Brief Email ==="
echo ""

echo "[1/3] Packaging Daily Brief Lambda..."
cd ~/Documents/Claude/life-platform/lambdas

rm -f daily_brief_lambda.zip
cp daily_brief_lambda.py lambda_function.py
zip daily_brief_lambda.zip lambda_function.py
rm lambda_function.py

echo "       Zip: $(du -h daily_brief_lambda.zip | cut -f1)"

echo "[2/3] Deploying..."
aws lambda update-function-code \
    --function-name daily-brief \
    --zip-file fileb://daily_brief_lambda.zip \
    --region us-west-2 \
    --no-cli-pager

sleep 10

echo "[3/3] Verifying..."
LAST_MOD=$(aws lambda get-function-configuration \
    --function-name daily-brief \
    --region us-west-2 \
    --query 'LastModified' \
    --output text \
    --no-cli-pager)
echo "       daily-brief LastModified: $LAST_MOD"

echo ""
echo "=== Deploy Complete ==="
echo ""
echo "Tomorrow's Daily Brief email will include a 96×96 pixel art avatar"
echo "in the Character Sheet section — Foundation tier hoodie guy."
echo ""
echo "Avatar URLs (one per tier):"
echo "  https://dash.averagejoematt.com/avatar/email/foundation-composite.png"
echo "  https://dash.averagejoematt.com/avatar/email/momentum-composite.png"
echo "  https://dash.averagejoematt.com/avatar/email/discipline-composite.png"
echo "  https://dash.averagejoematt.com/avatar/email/mastery-composite.png"
echo "  https://dash.averagejoematt.com/avatar/email/elite-composite.png"
