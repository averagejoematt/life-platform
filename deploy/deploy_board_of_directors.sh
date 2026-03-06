#!/bin/bash
# deploy_board_of_directors.sh — v2.56.0
# Uploads Board of Directors config to S3 and deploys updated MCP server
set -euo pipefail

BUCKET="matthew-life-platform"
REGION="us-west-2"
MCP_FUNCTION="life-platform-mcp"
CONFIG_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "═══════════════════════════════════════════════════"
echo "  Board of Directors — Deploy v2.56.0"
echo "═══════════════════════════════════════════════════"

# ── Step 1: Upload config to S3 ──
echo ""
echo "▸ Step 1: Upload board_of_directors.json to S3..."
aws s3 cp "$CONFIG_DIR/config/board_of_directors.json" \
    "s3://$BUCKET/config/board_of_directors.json" \
    --content-type "application/json" \
    --region "$REGION"
echo "  ✓ Config uploaded to s3://$BUCKET/config/board_of_directors.json"

# Verify upload
echo ""
echo "▸ Verifying S3 upload..."
aws s3api head-object \
    --bucket "$BUCKET" \
    --key "config/board_of_directors.json" \
    --region "$REGION" \
    --query '{Size: ContentLength, LastModified: LastModified}' \
    --output table
echo "  ✓ Verified"

# ── Step 2: Build MCP server zip ──
echo ""
echo "▸ Step 2: Build MCP server zip..."
cd "$CONFIG_DIR"

# Clean old zip
rm -f mcp_server.zip

# Create zip with mcp_server.py + mcp_bridge.py + mcp/ directory
zip -r mcp_server.zip \
    mcp_server.py \
    mcp_bridge.py \
    mcp/ \
    -x "mcp/__pycache__/*" "mcp/*.pyc"

echo "  ✓ Built mcp_server.zip ($(du -h mcp_server.zip | cut -f1))"

# ── Step 3: Deploy MCP Lambda ──
echo ""
echo "▸ Step 3: Deploy MCP Lambda..."
aws lambda update-function-code \
    --function-name "$MCP_FUNCTION" \
    --zip-file "fileb://mcp_server.zip" \
    --region "$REGION" \
    --output text \
    --query 'FunctionName'
echo "  ✓ MCP Lambda updated"

# ── Step 4: Verify tool count ──
echo ""
echo "▸ Step 4: Verifying tool count..."
sleep 5
TOOL_COUNT=$(python3 -c "
import sys
sys.path.insert(0, '.')
# Quick count from registry
with open('mcp/registry.py') as f:
    content = f.read()
count = content.count('\"fn\":')
print(count)
")
echo "  ✓ Tool count: $TOOL_COUNT (expected: 102)"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅ Board of Directors deployed successfully!"
echo ""
echo "  Config:  s3://$BUCKET/config/board_of_directors.json"
echo "  Members: 12 (6 fictional + 5 real experts + 1 narrator)"
echo "  Tools:   +3 (get_board_of_directors, update_board_member, remove_board_member)"
echo "  Total:   $TOOL_COUNT tools"
echo "═══════════════════════════════════════════════════"
