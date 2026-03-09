#!/usr/bin/env bash
# deploy_remote_mcp.sh — Deploy MCP Lambda with remote Streamable HTTP transport
# Adds claude.ai / mobile connector support via Lambda Function URL
#
# What it does:
#   1. Deploys updated MCP Lambda (handler.py with remote transport)
#   2. Updates Function URL CORS to allow HEAD/GET + MCP headers
#
# Usage: ./deploy/deploy_remote_mcp.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
REGION="us-west-2"
FUNCTION_NAME="life-platform-mcp"
ZIP_FILE="/tmp/${FUNCTION_NAME}.zip"

info()  { echo "[INFO]  $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

# ── Step 1: Deploy MCP Lambda ────────────────────────────────────────────────
info "Building MCP package..."
cd "$PROJECT_DIR"

# Clean and build zip with mcp/ package + entry point
rm -f "$ZIP_FILE"
zip -q "$ZIP_FILE" mcp_server.py
zip -qr "$ZIP_FILE" mcp/ -x "mcp/__pycache__/*" "mcp/*.pyc"

info "Deploying Lambda..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP_FILE" \
    --region "$REGION" \
    --output text --query 'FunctionName'

info "Waiting for update to complete..."
aws lambda wait function-updated \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION"

info "Lambda deployed."

# ── Step 2: Update Function URL CORS ─────────────────────────────────────────
info "Updating Function URL CORS for remote MCP transport..."
aws lambda update-function-url-config \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --auth-type NONE \
    --cors '{
        "AllowOrigins": ["*"],
        "AllowMethods": ["POST", "HEAD", "GET"],
        "AllowHeaders": [
            "content-type",
            "x-api-key",
            "accept",
            "authorization",
            "mcp-session-id",
            "mcp-protocol-version"
        ],
        "ExposeHeaders": [
            "mcp-session-id",
            "mcp-protocol-version"
        ],
        "MaxAge": 86400
    }' \
    --output text --query 'FunctionUrl'

info ""
info "═══════════════════════════════════════════════════════════════"
info "  Remote MCP connector deployed!"
info ""
info "  Function URL:"
info "  https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws/"
info ""
info "  To connect from Claude mobile/web:"
info "  1. Go to claude.ai → Settings → Connectors"
info "  2. Click 'Add custom connector'"
info "  3. Paste the Function URL above"
info "  4. Name it 'Life Platform'"
info "  5. Click Connect (auto-approve OAuth flow)"
info ""
info "  It will auto-sync to your iPhone Claude app."
info "═══════════════════════════════════════════════════════════════"
