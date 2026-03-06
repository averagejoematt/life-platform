#!/bin/bash
# Features #12 + #25 — Social Connection + Meditation MCP Tools
# Adds 3 new MCP tools: get_social_connection_trend, get_social_isolation_risk, get_meditation_correlation
# v2.37.0

set -euo pipefail
REGION="us-west-2"
FUNCTION_NAME="life-platform-mcp"
LAMBDA_DIR="$HOME/Documents/Claude/life-platform/lambdas"
MCP_SOURCE="$HOME/Documents/Claude/life-platform/mcp_server.py"
DEPLOY_DIR="$HOME/Documents/Claude/life-platform/deploy"

echo "═══════════════════════════════════════════════════════════"
echo "Features #12 + #25 — MCP Tools"
echo "  #12: get_social_connection_trend, get_social_isolation_risk"
echo "  #25: get_meditation_correlation"
echo "═══════════════════════════════════════════════════════════"

# ── Step 1: Patch mcp_server.py ──
echo ""
echo "Step 1: Patching mcp_server.py..."
python3 "$DEPLOY_DIR/patch_mcp_features_12_25.py"

# ── Step 2: Package ──
echo ""
echo "Step 2: Packaging MCP server..."
TMPDIR=$(mktemp -d)
cp "$MCP_SOURCE" "$TMPDIR/mcp_server.py"
cd "$TMPDIR"
zip -r mcp_server.zip mcp_server.py
cp mcp_server.zip "$LAMBDA_DIR/mcp_server.zip"

# ── Step 3: Deploy ──
echo ""
echo "Step 3: Deploying to Lambda..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://mcp_server.zip" \
    --region "$REGION" \
    --query "[FunctionName,CodeSize,LastModified]" \
    --output table

echo ""
echo "Step 4: Waiting for update..."
aws lambda wait function-updated \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" 2>/dev/null || sleep 10

# ── Step 5: Verify ──
echo ""
echo "Step 5: Verifying tool count..."
aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --payload '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
    /tmp/mcp_tools_verify.json \
    --query "StatusCode" --output text > /dev/null

python3 -c "
import json
d = json.load(open('/tmp/mcp_tools_verify.json'))
tools = [t['name'] for t in d.get('result',{}).get('tools',[])]
print(f'  Total tools: {len(tools)}')
for t in ['get_social_connection_trend', 'get_social_isolation_risk', 'get_meditation_correlation']:
    s = '✅' if t in tools else '❌'
    print(f'  {s} {t}')
"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ Features #12 + #25 MCP tools deployed!"
echo ""
echo "New tools:"
echo "  get_social_connection_trend  — PERMA social quality trend"
echo "  get_social_isolation_risk    — isolation episode detection"
echo "  get_meditation_correlation   — mindfulness health impact"
echo "═══════════════════════════════════════════════════════════"

rm -rf "$TMPDIR"
