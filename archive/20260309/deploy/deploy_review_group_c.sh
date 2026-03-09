#!/bin/bash
# deploy_review_group_c.sh — Expert Review Group C: Daily Brief hardening
# Finding: F5.8 — Graceful degradation for daily brief sections
#
# Prerequisites: Run patch_daily_brief_hardening.py first!
#
# Steps:
#   1. Run the Python patch script (modifies daily_brief_lambda.py in-place)
#   2. Create zip with lambda_function.py (Lambda handler convention)
#   3. Deploy to AWS Lambda

set -euo pipefail
REGION="us-west-2"
BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=========================================="
echo "Group C: Daily Brief Hardening"
echo "=========================================="

# Step 1: Apply patch
echo "── Step 1/3: Applying hardening patch ──"
python3 "$BASE_DIR/deploy/patch_daily_brief_hardening.py"
echo ""

# Step 2: Create zip
echo "── Step 2/3: Creating deployment zip ──"
cd "$BASE_DIR/lambdas"
cp daily_brief_lambda.py lambda_function.py
zip -j daily_brief_lambda.zip lambda_function.py
rm lambda_function.py
echo "✅ daily_brief_lambda.zip created ($(du -h daily_brief_lambda.zip | cut -f1))"

# Step 3: Deploy
echo ""
echo "── Step 3/3: Deploying to Lambda ──"
aws lambda update-function-code \
  --function-name daily-brief \
  --zip-file "fileb://daily_brief_lambda.zip" \
  --region $REGION \
  --query 'FunctionName' --output text
echo "✅ daily-brief Lambda updated"

echo ""
echo "=========================================="
echo "Group C Complete"
echo "=========================================="
echo ""
echo "Changes applied:"
echo "  Handler: compute_day_grade, compute_readiness,"
echo "           compute_habit_streaks, store_* wrapped in try/except"
echo "  build_html: fallback minimal email if entire builder crashes"
echo "  Sections: Training, Nutrition, Habits, CGM, Weight Phase,"
echo "            Gait, Anomaly all wrapped with error placeholders"
echo "  Bug fix: duplicate dedup_activities removed"
echo ""
echo "Test: Invoke manually with demo_mode=true:"
echo '  aws lambda invoke --function-name daily-brief \'
echo '    --payload '"'"'{"demo_mode": true}'"'"' \'
echo '    --region us-west-2 /tmp/brief-output.json'
