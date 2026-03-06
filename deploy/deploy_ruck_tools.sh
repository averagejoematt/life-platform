#!/bin/bash
set -euo pipefail

# Deploy ruck tools cleanup — v2.50.0
# Cleans up duplicate ruck entries from previous failed attempt
# Files changed: tools_lifestyle.py (orphan removal), registry.py (dedup), config.py (dedup)

echo "=== Deploy Ruck Tools v2.50.0 ==="
cd ~/Documents/Claude/life-platform

# ── 1. Package Lambda zip ──
echo "1. Packaging MCP server..."
cd mcp
zip -r ../lambdas/mcp_server.zip . -x '__pycache__/*' '*.pyc'
cd ..
echo "   ✅ Packaged $(du -h lambdas/mcp_server.zip | cut -f1)"

# ── 2. Deploy to Lambda ──
echo "2. Deploying to Lambda..."
aws lambda update-function-code \
  --function-name life-platform-mcp \
  --zip-file fileb://lambdas/mcp_server.zip \
  --region us-west-2 \
  --no-cli-pager
echo "   ✅ Lambda updated"

# ── 3. Wait and verify ──
echo "3. Waiting 10s for propagation..."
sleep 10

echo "4. Smoke test (expect 401 = Lambda running)..."
FUNC_URL=$(aws lambda get-function-url-config \
  --function-name life-platform-mcp \
  --region us-west-2 \
  --query 'FunctionUrl' --output text 2>/dev/null || echo "")
if [ -n "$FUNC_URL" ]; then
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${FUNC_URL}sse" 2>/dev/null || echo "000")
  if [ "$HTTP_CODE" = "401" ]; then
    echo "   ✅ Smoke test passed (401 = auth required = Lambda running)"
  else
    echo "   ⚠️  Got HTTP $HTTP_CODE (expected 401)"
  fi
else
  echo "   ⚠️  Could not get function URL, skipping smoke test"
fi

echo ""
echo "=== Done! 99 tools, ruck logging ready ==="
echo ""
echo "Test with: 'I rucked today with 35lbs'"
echo "Or: 'show my ruck log'"
