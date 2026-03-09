#!/bin/bash
# deploy_n1_experiments.sh — N=1 Experiment Framework (Package 2 of 3)
# Version: v2.34.0
#
# What this does:
#   1. Patches MCP server with 4 experiment tools (76 tools total)
#   2. Deploys updated MCP Lambda
#
# Pre-flight: Run from ~/Documents/Claude/life-platform/

set -euo pipefail
cd ~/Documents/Claude/life-platform

echo "═══════════════════════════════════════════════════"
echo "  Package 2/3: N=1 Experiment Framework"
echo "  Version: v2.34.0"
echo "═══════════════════════════════════════════════════"

# ── Step 1: Patch MCP Server ─────────────────────────────────────────────
echo ""
echo "── Step 1: Patching MCP server ──"
python3 patches/patch_n1_experiments.py

# ── Step 2: Verify patches ───────────────────────────────────────────────
echo ""
echo "── Step 2: Verifying patches ──"

for check in "EXPERIMENTS_PK" "def tool_create_experiment" "def tool_list_experiments" "def tool_get_experiment_results" "def tool_end_experiment" "\"create_experiment\":" "\"list_experiments\":" "\"get_experiment_results\":" "\"end_experiment\":"; do
    if grep -q "$check" mcp_server.py; then
        echo "  ✅ Found: $check"
    else
        echo "  ❌ MISSING: $check — aborting"
        exit 1
    fi
done

python3 -c "import py_compile; py_compile.compile('mcp_server.py', doraise=True)" && echo "  ✅ Python syntax valid" || { echo "  ❌ Syntax error"; exit 1; }

# Count tools
TOOL_COUNT=$(grep -c '"fn":' mcp_server.py)
echo "  ℹ️  Tool count: $TOOL_COUNT"

# ── Step 3: Package and deploy ───────────────────────────────────────────
echo ""
echo "── Step 3: Packaging MCP Lambda ──"
rm -f mcp_server.zip
zip mcp_server.zip mcp_server.py

echo "── Step 4: Deploying MCP Lambda ──"
aws lambda update-function-code \
    --function-name life-platform-mcp \
    --zip-file fileb://mcp_server.zip \
    --region us-west-2 \
    --no-cli-pager

echo "  ✅ MCP Lambda deployed"

# ── Step 5: Wait and verify ──────────────────────────────────────────────
echo ""
echo "── Step 5: Waiting for Lambda to stabilize ──"
sleep 5

aws lambda get-function-configuration \
    --function-name life-platform-mcp \
    --query "[LastModified, CodeSize, Handler]" \
    --region us-west-2 \
    --no-cli-pager

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅ Package 2/3 DEPLOYED — N=1 Experiments"
echo ""
echo "  New tools:"
echo "    - create_experiment"
echo "    - list_experiments"
echo "    - get_experiment_results"
echo "    - end_experiment"
echo ""
echo "  Test with:"
echo "    'Create an experiment: no caffeine after 10am'"
echo "    'What experiments am I running?'"
echo ""
echo "  Next: Run deploy_health_trajectory.sh (Package 3/3)"
echo "═══════════════════════════════════════════════════"
