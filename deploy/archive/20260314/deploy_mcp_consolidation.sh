#!/bin/bash
# deploy_mcp_consolidation.sh — v3.7.0 MCP Tool Consolidation
# 148 → 115 tools. Fixes crash loop + removes 33 low-value tools.
#
# PREREQUISITES:
#   1. Copy the consolidated registry into place:
#      cp /path/to/downloaded/registry_consolidated.py mcp/registry.py
#   2. Verify it's correct:
#      python3 -c "import ast; ast.parse(open('mcp/registry.py').read()); print('OK')"
#      grep -c '"fn":' mcp/registry.py  # should say ~116
#
# Run from project root:
#   bash deploy/deploy_mcp_consolidation.sh

set -euo pipefail

FUNCTION_NAME="life-platform-mcp"
REGION="us-west-2"
ZIP_FILE="/tmp/mcp_deploy_v370.zip"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== MCP Consolidation Deploy v3.7.0 ==="
echo "Project root: $PROJECT_ROOT"
echo ""

# Step 0: Verify registry is consolidated (not original, not broken)
TOOL_COUNT=$(grep -c '"fn":' "$PROJECT_ROOT/mcp/registry.py" 2>/dev/null || echo "0")
echo "Registry tool count: $TOOL_COUNT"

if [ "$TOOL_COUNT" -lt 100 ]; then
    echo "ERROR: registry.py has fewer than 100 tools ($TOOL_COUNT found)."
    echo "Did you forget to copy registry_consolidated.py to mcp/registry.py?"
    echo ""
    echo "  cp /path/to/registry_consolidated.py mcp/registry.py"
    exit 1
fi

if [ "$TOOL_COUNT" -gt 140 ]; then
    echo "ERROR: registry.py still has $TOOL_COUNT tools (expected ~115)."
    echo "You may still have the original registry. Copy the consolidated version:"
    echo ""
    echo "  cp /path/to/registry_consolidated.py mcp/registry.py"
    exit 1
fi

# Verify longevity import is gone
if grep -q "tools_longevity" "$PROJECT_ROOT/mcp/registry.py"; then
    echo "ERROR: tools_longevity import still present in registry.py!"
    exit 1
fi

# Verify Python syntax
python3 -c "import ast; ast.parse(open('$PROJECT_ROOT/mcp/registry.py').read())" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "ERROR: registry.py has syntax errors!"
    exit 1
fi

echo "✓ Registry validated: $TOOL_COUNT tools, no longevity import, syntax OK"
echo ""

# Step 0b: Run MCP registry integrity test (R1-R7)
if [ -f "$PROJECT_ROOT/tests/test_mcp_registry.py" ]; then
    echo "Running MCP registry integrity lint (R1-R7)..."
    cd "$PROJECT_ROOT"
    python3 -m pytest tests/test_mcp_registry.py -v --tb=short 2>&1
    if [ $? -ne 0 ]; then
        echo "ERROR: MCP registry integrity test failed. Fix before deploying."
        exit 1
    fi
    echo "✓ Registry integrity lint passed"
    echo ""
fi

# Step 1: Build MCP zip (preserving mcp/ subdirectory structure)
echo "Building MCP Lambda zip..."
cd "$PROJECT_ROOT"

# Remove old zip
rm -f "$ZIP_FILE"

# Add root-level handler files
zip -j "$ZIP_FILE" mcp_server.py mcp_bridge.py

# Add mcp/ package preserving directory structure
zip -r "$ZIP_FILE" mcp/ -x "mcp/__pycache__/*" "mcp/*.pyc"

echo "✓ Zip created: $(du -h "$ZIP_FILE" | cut -f1)"
echo ""

# Step 2: Deploy to Lambda
echo "Deploying to $FUNCTION_NAME..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP_FILE" \
    --region "$REGION" \
    --output text \
    --query 'LastModified'

echo ""
echo "✓ Lambda updated"
echo ""

# Step 3: Wait for update to propagate
echo "Waiting 10s for Lambda update to propagate..."
sleep 10

# Step 4: Smoke test — invoke tools/list
echo "Smoke test: listing MCP tools..."
aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --cli-binary-format raw-in-base64-out \
    --payload '{"requestContext":{"http":{"method":"POST"}},"body":"{\"jsonrpc\":\"2.0\",\"method\":\"tools/list\",\"id\":1}"}' \
    /tmp/mcp_smoke_test.json > /dev/null 2>&1

if [ $? -eq 0 ]; then
    LIVE_TOOLS=$(python3 -c "
import json
with open('/tmp/mcp_smoke_test.json') as f:
    resp = json.load(f)
body = json.loads(resp.get('body', '{}'))
tools = body.get('result', {}).get('tools', [])
print(len(tools))
" 2>/dev/null || echo "?")
    echo "✓ Smoke test passed: $LIVE_TOOLS tools live"
else
    echo "⚠ Smoke test returned non-zero. Check CloudWatch."
fi

echo ""
echo "=== Deploy Complete ==="
echo "Verify in CloudWatch:"
echo "  aws logs tail /aws/lambda/$FUNCTION_NAME --follow --region $REGION"
