#!/usr/bin/env bash
# deploy_mcp_split.sh — Deploy the split MCP server package
#
# What this does:
#   1. Copies the new mcp_server.py (thin entry point) + mcp/ package
#   2. Creates the Lambda zip with both mcp_server.py and the mcp/ directory
#   3. Deploys to AWS Lambda (same function name, same handler path)
#
# The Lambda handler remains mcp_server.lambda_handler — zero config change.
#
# Usage:
#   chmod +x deploy/deploy_mcp_split.sh
#   ./deploy/deploy_mcp_split.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
FUNCTION_NAME="life-platform-mcp"
REGION="us-west-2"
ZIP_FILE="mcp_server.zip"

info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

cd "$PROJECT_DIR"

# ── 0. Safety checks ─────────────────────────────────────────────────────────
[ -d "mcp" ]             || error "mcp/ directory not found."
[ -f "mcp_server.py" ]   || error "mcp_server.py entry point not found."
[ -f "mcp/__init__.py" ] || error "mcp/__init__.py not found."

MODULE_COUNT=$(find mcp -name "*.py" | wc -l | tr -d ' ')
info "Found mcp/ package with $MODULE_COUNT modules"

LINE_COUNT=$(wc -l < mcp_server.py | tr -d ' ')
if [ "$LINE_COUNT" -gt 50 ]; then
    error "mcp_server.py has $LINE_COUNT lines — looks like the monolith. Expected thin entry point."
fi
info "Entry point: $LINE_COUNT lines (thin wrapper ✓)"

# ── 1. Syntax check ──────────────────────────────────────────────────────────
info "Syntax checking all modules..."
ERRORS=0
for f in mcp_server.py mcp/*.py; do
    if ! python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" 2>/dev/null; then
        echo "  ❌ $f"
        ERRORS=$((ERRORS + 1))
    fi
done
[ "$ERRORS" -eq 0 ] || error "$ERRORS file(s) failed syntax check"
info "All modules compile clean ✓"

# ── 2. Create Lambda zip ─────────────────────────────────────────────────────
info "Creating $ZIP_FILE..."
rm -f "$ZIP_FILE"
zip -j "$ZIP_FILE" mcp_server.py
zip -r "$ZIP_FILE" mcp/ -x "mcp/__pycache__/*" "mcp/*.pyc"
ZIP_SIZE=$(du -h "$ZIP_FILE" | cut -f1)
info "Zip created: $ZIP_FILE ($ZIP_SIZE)"

# ── 3. Deploy ─────────────────────────────────────────────────────────────────
info "Deploying to $FUNCTION_NAME..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP_FILE" \
    --region "$REGION" \
    --output text --query 'FunctionName'

info "Waiting for update..."
aws lambda wait function-updated \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION"

# ── 4. Smoke test ─────────────────────────────────────────────────────────────
info "Smoke test: tools/list..."
PAYLOAD='{"method":"tools/list","params":{}}'
STATUS=$(aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --payload "$(echo "$PAYLOAD" | base64)" \
    --cli-binary-format raw-in-base64-out \
    /tmp/mcp_smoke.json \
    --query 'StatusCode' --output text 2>/dev/null || echo "FAIL")

if [ "$STATUS" = "200" ]; then
    TOOL_COUNT=$(python3 -c "
import json
with open('/tmp/mcp_smoke.json') as f:
    d = json.load(f)
body = json.loads(d.get('body','{}')) if isinstance(d.get('body'), str) else d
tools = body.get('result',{}).get('tools', body.get('tools',[]))
print(len(tools))
" 2>/dev/null || echo "?")
    info "Smoke test passed ✓ — $TOOL_COUNT tools"
else
    warn "Smoke test status $STATUS — check CloudWatch"
fi

# ── 5. Cleanup ────────────────────────────────────────────────────────────────
rm -f "$ZIP_FILE"

echo ""
info "════════════════════════════════════════════════════"
info "MCP split deployed!"
info "  Function: $FUNCTION_NAME"
info "  Handler:  mcp_server.lambda_handler (unchanged)"
info "  Modules:  $MODULE_COUNT files"
info "  Next:     Restart Claude Desktop, test MCP tools"
info "════════════════════════════════════════════════════"
