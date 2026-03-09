#!/usr/bin/env bash
# deploy_zone2_tool.sh — Add get_zone2_breakdown tool (v2.13.0)
#
# Patches mcp_server.py with:
#   1. New function: tool_get_zone2_breakdown
#   2. New registry entry
#   3. Version bump to 2.13.0
# Then deploys to Lambda.
#
# Usage:
#   cd ~/Documents/Claude/life-platform
#   chmod +x deploy_zone2_tool.sh
#   ./deploy_zone2_tool.sh

set -euo pipefail

FUNCTION_NAME="life-platform-mcp"
REGION="us-west-2"
ZIP_FILE="mcp_server.zip"

info()  { echo "[INFO]  $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

cd "$(dirname "$0")"

# ── Safety check ──────────────────────────────────────────────────────────────
if grep -q "get_zone2_breakdown" mcp_server.py; then
    error "get_zone2_breakdown already exists in mcp_server.py. Aborting."
fi

# ── 1. Apply patch via Python ─────────────────────────────────────────────────
info "Patching mcp_server.py with get_zone2_breakdown tool..."
python3 patch_zone2_tool.py || error "Patch script failed"

# ── 2. Verify patch applied ──────────────────────────────────────────────────
if ! grep -q "get_zone2_breakdown" mcp_server.py; then
    error "Patch failed -- function not found in mcp_server.py"
fi

if ! grep -q '"version": "2.13.0"' mcp_server.py; then
    error "Patch failed -- version not updated to 2.13.0"
fi

TOOL_COUNT=$(grep -c '"fn":' mcp_server.py)
info "Tool count after patch: ${TOOL_COUNT} (was 56, expected 57)"

# ── 3. Package and deploy ────────────────────────────────────────────────────
info "Packaging Lambda..."
rm -f "${ZIP_FILE}"
zip -j "${ZIP_FILE}" mcp_server.py
info "Created ${ZIP_FILE}"

info "Deploying to Lambda..."
aws lambda update-function-code \
    --function-name "${FUNCTION_NAME}" \
    --zip-file "fileb://${ZIP_FILE}" \
    --region "${REGION}" > /dev/null

aws lambda wait function-updated \
    --function-name "${FUNCTION_NAME}" \
    --region "${REGION}"

aws lambda update-function-configuration \
    --function-name "${FUNCTION_NAME}" \
    --environment "Variables={DEPLOY_VERSION=2.13.0}" \
    --region "${REGION}" > /dev/null

aws lambda wait function-updated \
    --function-name "${FUNCTION_NAME}" \
    --region "${REGION}"

info "Lambda deployed: v2.13.0"

# ── 4. Verify deployment ─────────────────────────────────────────────────────
LAST_MODIFIED=$(aws lambda get-function-configuration \
    --function-name "${FUNCTION_NAME}" \
    --region "${REGION}" \
    --query "LastModified" --output text)
info "Lambda LastModified: ${LAST_MODIFIED}"

echo ""
echo "================================================================"
echo " v2.13.0 deployed -- get_zone2_breakdown"
echo "================================================================"
echo "  Tool count : ${TOOL_COUNT}"
echo "  Lambda     : ${FUNCTION_NAME}"
echo "  Modified   : ${LAST_MODIFIED}"
echo ""
echo "  Test in Claude Desktop:"
echo '    "How much Zone 2 am I doing?"'
echo '    "Show my training zone distribution"'
echo '    "Am I hitting my Zone 2 target?"'
echo ""
echo "  Zone 2 HR range: $(python3 -c "print(f'{183*0.6:.0f}-{183*0.7:.0f} bpm')")"
echo "  Weekly target: 150 min (configurable)"
echo ""
