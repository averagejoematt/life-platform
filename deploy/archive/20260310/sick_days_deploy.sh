#!/bin/bash
# sick_days_deploy.sh — Full deploy for sick day feature
# Run from project root: bash deploy/sick_days_deploy.sh
set -euo pipefail

echo "=== Sick Day Feature Deploy v1.0.0 ==="
echo ""

# Step 1: Apply Lambda patches
echo "1. Applying Lambda patches..."
python3 deploy/apply_sick_day_patches.py
echo ""

# Step 2: Patch registry.py
echo "2. Patching mcp/registry.py..."
python3 deploy/patch_registry.py
echo ""

# Step 3: Rebuild Lambda Layer (sick_day_checker.py gets included)
echo "3. Rebuilding Lambda Layer..."
bash deploy/build_layer.sh
echo ""

# Step 4: Deploy CDK stacks
echo "4. Deploying LifePlatformCore (new Layer version)..."
cd cdk && cdk deploy LifePlatformCore --require-approval never && cd ..
sleep 10

for STACK in LifePlatformIngestion LifePlatformCompute LifePlatformEmail LifePlatformOperational LifePlatformMcp; do
    echo "  Deploying $STACK..."
    cd cdk && cdk deploy "$STACK" --require-approval never && cd ..
    sleep 10
done
echo ""

# Step 5: Log retroactive sick days (March 8-9)
echo "5. Logging retroactive sick days (March 8-9)..."
bash deploy/sick_days_retroactive.sh
echo ""

# Step 6: Recompute character sheet + daily metrics for March 8-9
echo "6. Recomputing March 8..."
aws lambda invoke --function-name character-sheet-compute \
    --payload '{"date": "2026-03-08", "force": true}' \
    --cli-binary-format raw-in-base64-out /tmp/cs_08.json --region us-west-2
cat /tmp/cs_08.json && echo ""
sleep 3

aws lambda invoke --function-name daily-metrics-compute \
    --payload '{"date": "2026-03-08", "force": true}' \
    --cli-binary-format raw-in-base64-out /tmp/dm_08.json --region us-west-2
cat /tmp/dm_08.json && echo ""
sleep 3

echo "7. Recomputing March 9..."
aws lambda invoke --function-name character-sheet-compute \
    --payload '{"date": "2026-03-09", "force": true}' \
    --cli-binary-format raw-in-base64-out /tmp/cs_09.json --region us-west-2
cat /tmp/cs_09.json && echo ""
sleep 3

aws lambda invoke --function-name daily-metrics-compute \
    --payload '{"date": "2026-03-09", "force": true}' \
    --cli-binary-format raw-in-base64-out /tmp/dm_09.json --region us-west-2
cat /tmp/dm_09.json && echo ""

echo ""
echo "=== Deploy Complete ==="
echo ""
echo "What's live:"
echo "  sick_day_checker.py      — shared Lambda Layer utility"
echo "  log_sick_day MCP tool    — flag sick days in chat"
echo "  get_sick_days MCP tool   — list sick day history"
echo "  clear_sick_day MCP tool  — remove a flag if logged in error"
echo "  character-sheet-compute  — EMA frozen on sick days"
echo "  daily-metrics-compute    — grade='sick', streaks preserved"
echo "  anomaly-detector         — alerts suppressed on sick days"
echo "  freshness-checker        — stale alerts suppressed on sick days"
echo "  daily-brief              — recovery banner sent on sick days"
echo ""
echo "March 8-9 retroactively flagged and recomputed."
echo "Going forward: use 'log_sick_day' MCP tool to flag future sick days."
