#!/bin/bash
# Deploy sleep onset consistency to Whoop Lambda + backfill historical data
# Phase 1a of Derived Metrics Plan
#
# What this does:
#   1. Patches whoop_lambda.py with sleep_onset_minutes + sleep_onset_consistency_7d
#   2. Creates zip and updates Lambda function
#   3. Runs backfill for all historical Whoop records
#
# New fields added to Whoop daily records:
#   - sleep_onset_minutes (int): minutes from midnight UTC of sleep_start
#   - sleep_onset_consistency_7d (float): StdDev of last 7 nights' onset times
#
# Rollback: Fields are additive. If issues, redeploy from git (fields ignored if present).

set -euo pipefail
cd "$(dirname "$0")"

echo "═══════════════════════════════════════════════════"
echo "  Phase 1a: Sleep Onset Consistency"
echo "  Derived Metrics Plan — v2.29.0"
echo "═══════════════════════════════════════════════════"
echo ""

# Step 1: Apply patch
echo "Step 1: Patching whoop_lambda.py..."
python3 patch_sleep_consistency.py
echo ""

# Step 2: Create zip and deploy
echo "Step 2: Deploying Lambda..."
rm -f whoop_lambda.zip
# Handler expects lambda_function.py — zip with correct filename
cp whoop_lambda.py lambda_function.py
zip whoop_lambda.zip lambda_function.py
rm lambda_function.py
aws lambda update-function-code \
    --function-name whoop-data-ingestion \
    --zip-file fileb://whoop_lambda.zip \
    --region us-west-2 \
    --no-cli-pager
echo ""
echo "✅ Lambda updated"
echo ""

# Step 3: Test invocation (today's data)
echo "Step 3: Test invocation..."
aws lambda invoke \
    --function-name whoop-data-ingestion \
    --payload '{"date_override": "today"}' \
    --log-type Tail \
    --region us-west-2 \
    /tmp/whoop_sleep_test.json \
    --no-cli-pager \
    --query 'LogResult' \
    --output text | base64 --decode | grep -E "(sleep_onset|ERROR)" || true
echo ""

# Step 4: Verify the new fields were written
echo "Step 4: Verifying DynamoDB record..."
TODAY=$(date -u +%Y-%m-%d)
aws dynamodb get-item \
    --table-name life-platform \
    --key "{\"pk\": {\"S\": \"USER#matthew#SOURCE#whoop\"}, \"sk\": {\"S\": \"DATE#${TODAY}\"}}" \
    --projection-expression "sleep_onset_minutes, sleep_onset_consistency_7d" \
    --region us-west-2 \
    --no-cli-pager
echo ""

# Step 5: Backfill historical records
echo "Step 5: Backfilling historical records..."
echo "  Running dry-run first..."
python3 backfill_sleep_consistency.py --dry-run 2>&1 | tail -15
echo ""
read -p "  Proceed with live backfill? (y/N) " confirm
if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
    python3 backfill_sleep_consistency.py
else
    echo "  Skipped backfill. Run manually: python3 backfill_sleep_consistency.py"
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Phase 1a complete!"
echo "  "
echo "  New fields: sleep_onset_minutes, sleep_onset_consistency_7d"
echo "  Clinical thresholds: <30m excellent, 30-60m fair, >60m poor"
echo "  Next: Phase 1b (lean_mass_delta_14d) or test via MCP"
echo "═══════════════════════════════════════════════════"
