#!/usr/bin/env bash
# deploy_alcohol_sleep_tool.sh — Add get_alcohol_sleep_correlation tool (v2.14.0)
#
# Usage:
#   cd ~/Documents/Claude/life-platform
#   chmod +x deploy_alcohol_sleep_tool.sh
#   ./deploy_alcohol_sleep_tool.sh

set -euo pipefail

FUNCTION_NAME="life-platform-mcp"
REGION="us-west-2"
ZIP_FILE="mcp_server.zip"

info()  { echo "[INFO]  $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

cd "$(dirname "$0")"

# ── Safety check ──────────────────────────────────────────────────────────────
if grep -q "get_alcohol_sleep_correlation" mcp_server.py; then
    error "get_alcohol_sleep_correlation already exists in mcp_server.py. Aborting."
fi

# ── 1. Apply patch via Python ─────────────────────────────────────────────────
info "Patching mcp_server.py with get_alcohol_sleep_correlation tool..."
python3 patch_alcohol_sleep_tool.py || error "Patch script failed"

# ── 2. Verify patch applied ──────────────────────────────────────────────────
if ! grep -q "get_alcohol_sleep_correlation" mcp_server.py; then
    error "Patch failed -- function not found in mcp_server.py"
fi

if ! grep -q '"version": "2.14.0"' mcp_server.py; then
    error "Patch failed -- version not updated to 2.14.0"
fi

TOOL_COUNT=$(grep -c '"fn":' mcp_server.py)
info "Tool count after patch: ${TOOL_COUNT} (was 57, expected 58)"

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
    --environment "Variables={DEPLOY_VERSION=2.14.0}" \
    --region "${REGION}" > /dev/null

aws lambda wait function-updated \
    --function-name "${FUNCTION_NAME}" \
    --region "${REGION}"

info "Lambda deployed: v2.14.0"

# ── 4. Verify deployment ─────────────────────────────────────────────────────
LAST_MODIFIED=$(aws lambda get-function-configuration \
    --function-name "${FUNCTION_NAME}" \
    --region "${REGION}" \
    --query "LastModified" --output text)
info "Lambda LastModified: ${LAST_MODIFIED}"

echo ""
echo "================================================================"
echo " v2.14.0 deployed -- get_alcohol_sleep_correlation"
echo "================================================================"
echo "  Tool count : ${TOOL_COUNT}"
echo "  Lambda     : ${FUNCTION_NAME}"
echo "  Modified   : ${LAST_MODIFIED}"
echo ""
echo "  Test in Claude Desktop:"
echo '    "Is alcohol affecting my sleep?"'
echo '    "How does drinking affect my recovery?"'
echo '    "Drinking vs sober sleep comparison"'
echo ""
echo "  Note: Only ~6 days of real MacroFactor data exists."
echo "  Results will be limited until 2-3 weeks of food logging"
echo "  accumulates. The tool will surface meaningful patterns"
echo "  as more data arrives."
echo ""
