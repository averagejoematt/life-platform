#!/bin/bash
# deploy_derived_phase1f_2c.sh — Derived Metrics Phase 1f (ASCVD) + Phase 2c (Day Type)
# Version: v2.31.0
#
# What this does:
#   1. Patches labs records with ASCVD 10-year risk scores (Phase 1f)
#   2. Patches MCP server with day_type utility + tool + ASCVD in health risk profile
#   3. Deploys updated MCP Lambda
#
# Pre-flight: Run from ~/Documents/Claude/life-platform/

set -euo pipefail
cd ~/Documents/Claude/life-platform

echo "═══════════════════════════════════════════════════"
echo "  Life Platform — Derived Metrics Phase 1f + 2c"
echo "  Version: v2.31.0"
echo "═══════════════════════════════════════════════════"

# ── Step 1: ASCVD Risk Scores on Labs Records ──────────────────────────────
echo ""
echo "── Step 1: Computing ASCVD 10yr risk on labs records ──"
python3 patch_ascvd_risk.py

# ── Step 2: Patch MCP Server ──────────────────────────────────────────────
echo ""
echo "── Step 2: Patching MCP server (day_type + ASCVD display) ──"
python3 patch_day_type_ascvd.py

# ── Step 3: Verify patches ──────────────────────────────────────────────────
echo ""
echo "── Step 3: Verifying patches ──"

if grep -q "def classify_day_type" mcp_server.py; then
    echo "  ✅ classify_day_type utility found"
else
    echo "  ❌ classify_day_type utility NOT found — aborting"
    exit 1
fi

if grep -q "def tool_get_day_type_analysis" mcp_server.py; then
    echo "  ✅ tool_get_day_type_analysis found"
else
    echo "  ❌ tool_get_day_type_analysis NOT found — aborting"
    exit 1
fi

if grep -q "ASCVD 10yr Risk" mcp_server.py; then
    echo "  ✅ ASCVD in health_risk_profile found"
else
    echo "  ❌ ASCVD in health_risk_profile NOT found — aborting"
    exit 1
fi

if grep -q "get_day_type_analysis" mcp_server.py; then
    echo "  ✅ get_day_type_analysis in tool registry"
else
    echo "  ❌ get_day_type_analysis NOT in registry — aborting"
    exit 1
fi

python3 -c "import py_compile; py_compile.compile('mcp_server.py', doraise=True)" && echo "  ✅ Python syntax valid" || { echo "  ❌ Syntax error"; exit 1; }

# ── Step 4: Package and deploy MCP Lambda ──────────────────────────────────
echo ""
echo "── Step 4: Packaging MCP Lambda ──"
rm -f mcp_server.zip
zip mcp_server.zip mcp_server.py

echo "── Step 5: Deploying MCP Lambda ──"
aws lambda update-function-code \
    --function-name life-platform-mcp \
    --zip-file fileb://mcp_server.zip \
    --region us-west-2 \
    --no-cli-pager

echo "  ✅ MCP Lambda deployed"

# ── Step 6: Wait and verify ──────────────────────────────────────────────
echo ""
echo "── Step 6: Waiting for Lambda to stabilize ──"
sleep 5

aws lambda get-function-configuration \
    --function-name life-platform-mcp \
    --query "[LastModified, CodeSize, Handler]" \
    --region us-west-2 \
    --no-cli-pager

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅ Derived Metrics Phase 1f + 2c DEPLOYED"
echo ""
echo "  New capabilities:"
echo "    - ASCVD 10yr risk stored on 2 labs records"
echo "    - ASCVD displayed in get_health_risk_profile"
echo "    - classify_day_type() utility available"
echo "    - get_day_type_analysis MCP tool (60th tool)"
echo ""
echo "  Test with:"
echo "    Claude Desktop → 'Segment my sleep by training day type'"
echo "    Claude Desktop → 'Show my cardiovascular risk profile'"
echo "═══════════════════════════════════════════════════"
