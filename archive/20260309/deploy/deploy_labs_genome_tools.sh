#!/usr/bin/env bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════════════════
# deploy_labs_genome_tools.sh — v2.11.0
# 1. Patches mcp_server.py with 8 new labs/DEXA/genome tools
# 2. Packages and deploys to Lambda
#
# New tools (47 → 55):
#   get_lab_results, get_lab_trends, get_out_of_range_history, search_biomarker,
#   get_genome_insights, get_body_composition_snapshot, get_health_risk_profile,
#   get_next_lab_priorities
# ═══════════════════════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MCP="$SCRIPT_DIR/mcp_server.py"
ZIP="$SCRIPT_DIR/mcp_server.zip"
LAMBDA_FN="life-platform-mcp"
REGION="us-west-2"

echo "═══════════════════════════════════════════════"
echo " Life Platform — Labs/Genome Tools Deploy"
echo " v2.11.0 — 8 new tools"
echo "═══════════════════════════════════════════════"

# Safety check
if grep -q "def tool_get_lab_results" "$MCP"; then
    echo "ERROR: Tools already patched. Aborting."
    exit 1
fi

# Step 1: Patch
echo ""
echo "[1/3] Patching mcp_server.py..."
python3 "$SCRIPT_DIR/patch_labs_genome_tools.py" --apply

# Step 2: Package
echo ""
echo "[2/3] Packaging Lambda..."
cd "$SCRIPT_DIR"
cp mcp_server.py lambda_function.py

pip install boto3 -t /tmp/mcp_pkg --quiet --upgrade 2>/dev/null || true
rm -f "$ZIP"
cd /tmp/mcp_pkg 2>/dev/null && zip -r "$ZIP" . -x '*.pyc' '__pycache__/*' > /dev/null || true
cd "$SCRIPT_DIR"
zip -g "$ZIP" lambda_function.py > /dev/null
rm lambda_function.py

ZIPSIZE=$(du -h "$ZIP" | cut -f1)
echo "  Package size: $ZIPSIZE"

# Step 3: Deploy
echo ""
echo "[3/3] Deploying to Lambda..."
aws lambda update-function-code \
    --function-name "$LAMBDA_FN" \
    --zip-file "fileb://$ZIP" \
    --region "$REGION" \
    --no-cli-pager

# Verify
TOOL_COUNT=$(grep -c '"fn":' "$MCP")
VERSION=$(grep -o '"version": "[^"]*"' "$MCP" | head -1)

echo ""
echo "═══════════════════════════════════════════════"
echo " ✅ Deployed v2.11.0"
echo " Tools: $TOOL_COUNT"
echo " Version: $VERSION"
echo ""
echo " New tools:"
echo "   1. get_lab_results"
echo "   2. get_lab_trends"
echo "   3. get_out_of_range_history"
echo "   4. search_biomarker"
echo "   5. get_genome_insights"
echo "   6. get_body_composition_snapshot"
echo "   7. get_health_risk_profile"
echo "   8. get_next_lab_priorities"
echo "═══════════════════════════════════════════════"
