#!/bin/bash
# Deploy v2.78.0 — Fitness Intelligence Features
# Features: #27 Lactate Threshold, #30 Hydration Score, #39 Exercise Efficiency,
#           Monthly Digest Character Sheet section + model upgrade (Haiku → Sonnet 4.6)
# MCP Server: +3 new tools → 124 total
# Files changed: mcp/tools_training.py, mcp/tools_health.py, mcp/registry.py, lambdas/monthly_digest_lambda.py
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
REGION="us-west-2"
ACCOUNT="205930651321"

cd ~/Documents/Claude/life-platform
chmod +x deploy/deploy_lambda.sh
echo "=== v2.78.0 Deploy: Fitness Intelligence + Monthly Digest Character Sheet ==="
echo ""

# ── 1. MCP Server (3 new tools: lactate, hydration, efficiency) ──────────────
echo "[1/2] Deploying MCP Server (tools_training.py + tools_health.py + registry.py)..."
cd "$PROJECT_ROOT"
rm -f /tmp/mcp-deploy.zip
zip -r /tmp/mcp-deploy.zip mcp/ mcp_server.py \
  -x "*/__pycache__/*" "*.pyc" ".DS_Store" \
  --quiet
aws lambda update-function-code \
  --function-name life-platform-mcp \
  --zip-file fileb:///tmp/mcp-deploy.zip \
  --region us-west-2 \
  --no-cli-pager \
  --query 'LastModified' \
  --output text
echo "  ✅ MCP Server deployed (124 tools)"

sleep 10

# ── 2. Monthly Digest (character sheet section + Sonnet 4.6 model upgrade) ───
echo "[2/2] Deploying monthly-digest Lambda..."
bash deploy/deploy_lambda.sh monthly-digest lambdas/monthly_digest_lambda.py
echo "  ✅ monthly-digest deployed"

echo ""
echo "=== v2.78.0 Deploy Complete ==="
echo ""
echo "New MCP tools:"
echo "  get_lactate_threshold_estimate  — Zone 2 cardiac efficiency + aerobic base trend"
echo "  get_exercise_efficiency_trend   — pace-at-HR by sport type, improvement detection"
echo "  get_hydration_score             — bodyweight-adjusted target, deficit days, exercise correlation"
echo ""
echo "Monthly Digest changes:"
echo "  + Character Sheet section (level, XP delta, all 7 pillars with prior-month deltas)"
echo "  + Model: Haiku → Sonnet 4.6 (was missed in v2.77.1 model sweep)"
echo ""
echo "Verify MCP tools by asking Claude: 'get_exercise_efficiency_trend' or 'hydration score'"
