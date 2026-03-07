#!/bin/bash
# deploy_prompt_intelligence.sh — v2.85.0
# Deploys: ai_calls.py (P2-P5), weekly_plate_lambda (P1), daily-brief (multi-module), life-platform-mcp (IC-1)
#
# Usage: bash deploy/deploy_prompt_intelligence.sh

set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== v2.85.0: Prompt Intelligence + Platform Memory Deploy ==="
echo ""

# 1. Daily Brief (multi-module — must include all 5 files)
echo "1/3 Deploying daily-brief (multi-module)..."
bash deploy/deploy_lambda.sh daily-brief lambdas/daily_brief_lambda.py \
    --extra-files \
    lambdas/ai_calls.py \
    lambdas/html_builder.py \
    lambdas/output_writers.py \
    lambdas/board_loader.py
echo "    ✅ daily-brief"
sleep 10

# 2. Weekly Plate (P1: plate memory)
echo "2/3 Deploying weekly-plate-schedule (P1 plate memory)..."
bash deploy/deploy_lambda.sh weekly-plate lambdas/weekly_plate_lambda.py
echo "    ✅ weekly-plate"
sleep 10

# 3. MCP server (IC-1: platform_memory module)
echo "3/3 Deploying life-platform-mcp (IC-1 memory tools)..."
bash deploy/deploy_lambda.sh life-platform-mcp lambdas/mcp_server.py
echo "    ✅ life-platform-mcp"

echo ""
echo "=== Deploy complete ==="
echo ""
echo "Post-deploy verification:"
echo "  1. Invoke daily-brief with {\"demo_mode\": true} and confirm no ImportError in CloudWatch"
echo "  2. MCP: call list_memory_categories — should return {categories: [], total_records: 0}"
echo "  3. MCP: call write_platform_memory with category='insight', content={'note': 'deploy test'}"
echo "  4. MCP: call read_platform_memory with category='insight' — should return the record"
echo "  5. Check CloudWatch for weekly-plate-schedule — no import errors"
echo ""
echo "Daily brief AI changes (P2-P5) will be visible in tomorrow's brief."
echo "Plate memory will start accumulating from next Friday's send."
