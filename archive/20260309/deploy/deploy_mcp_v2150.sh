#!/bin/bash
# deploy_mcp_v2150.sh — Patch MCP server + deploy to Lambda
# Adds 6 new tools: gait, energy balance, movement score, CGM dashboard, glucose correlations
set -euo pipefail

REGION="us-west-2"
FUNCTION_NAME="life-platform-mcp"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== MCP Server v2.15.0 — 6 new tools ==="
echo ""

# Step 1: Patch
echo "Step 1: Patching mcp_server.py..."
cd "$DIR"
python3 patch_mcp_v2150.py

# Step 2: Package
echo ""
echo "Step 2: Packaging..."
zip -j mcp_server.zip mcp_server.py

# Step 3: Deploy
echo ""
echo "Step 3: Deploying to Lambda..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://mcp_server.zip" \
    --region "$REGION" > /dev/null

aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
rm -f mcp_server.zip

echo ""
echo "✅ MCP server v2.15.0 deployed"
echo ""
echo "New tools:"
echo "  • get_gait_analysis              — walking speed, step length, asymmetry, composite score"
echo "  • get_energy_balance             — Apple Watch TDEE vs MacroFactor intake"
echo "  • get_movement_score             — NEAT estimate, movement composite, sedentary flags"
echo "  • get_cgm_dashboard              — glucose time-in-range, variability, fasting trend"
echo "  • get_glucose_sleep_correlation  — glucose vs Eight Sleep metrics"
echo "  • get_glucose_exercise_correlation — exercise vs rest day glucose patterns"
echo ""
echo "Total tools: ~52 (was 46)"
