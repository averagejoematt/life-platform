#!/usr/bin/env bash
# deploy_exercise_sleep_tool.sh — Add get_exercise_sleep_correlation tool (v2.12.0)
#
# Patches mcp_server.py with:
#   1. New function: tool_get_exercise_sleep_correlation
#   2. New registry entry
#   3. Version bump to 2.12.0
# Then deploys to Lambda.
#
# Usage:
#   cd ~/Documents/Claude/life-platform
#   chmod +x deploy_exercise_sleep_tool.sh
#   ./deploy_exercise_sleep_tool.sh

set -euo pipefail

FUNCTION_NAME="life-platform-mcp"
REGION="us-west-2"
ZIP_FILE="mcp_server.zip"

info()  { echo "[INFO]  $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

cd "$(dirname "$0")"

# ── Safety check ──────────────────────────────────────────────────────────────
if grep -q "get_exercise_sleep_correlation" mcp_server.py; then
    error "get_exercise_sleep_correlation already exists in mcp_server.py. Aborting."
fi

# ── 1. Apply patch via Python ─────────────────────────────────────────────────
info "Patching mcp_server.py with get_exercise_sleep_correlation tool..."
python3 patch_exercise_sleep_tool.py || error "Patch script failed"

# ── 2. Verify patch applied ──────────────────────────────────────────────────
if ! grep -q "get_exercise_sleep_correlation" mcp_server.py; then
    error "Patch failed -- function not found in mcp_server.py"
fi

if ! grep -q '"version": "2.12.0"' mcp_server.py; then
    error "Patch failed -- version not updated to 2.12.0"
fi

TOOL_COUNT=$(grep -c '"fn":' mcp_server.py)
info "Tool count after patch: ${TOOL_COUNT} (was 55, expected 56)"

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
    --environment "Variables={DEPLOY_VERSION=2.12.0}" \
    --region "${REGION}" > /dev/null

aws lambda wait function-updated \
    --function-name "${FUNCTION_NAME}" \
    --region "${REGION}"

info "Lambda deployed: v2.12.0"

# ── 4. Verify deployment ─────────────────────────────────────────────────────
LAST_MODIFIED=$(aws lambda get-function-configuration \
    --function-name "${FUNCTION_NAME}" \
    --region "${REGION}" \
    --query "LastModified" --output text)
info "Lambda LastModified: ${LAST_MODIFIED}"

echo ""
echo "================================================================"
echo " v2.12.0 deployed -- get_exercise_sleep_correlation"
echo "================================================================"
echo "  Tool count : ${TOOL_COUNT}"
echo "  Lambda     : ${FUNCTION_NAME}"
echo "  Modified   : ${LAST_MODIFIED}"
echo ""
echo "  Test in Claude Desktop:"
echo '    "Do late workouts hurt my sleep?"'
echo '    "What is my exercise timing cutoff for sleep?"'
echo '    "Exercise vs rest day sleep comparison"'
echo ""
echo "  Note: Uses 180 days of Strava + Eight Sleep by default."
echo "  Filters out activities < 15 min. Optionally exclude sport"
echo "  types (e.g. exclude_sport_types='Walk,Yoga')."
echo ""
