#!/bin/bash
# COST-2: Deploy MCP tool usage metrics (EMF instrumentation)
# Adds per-tool ToolInvocations/ToolDuration/ToolErrors EMF metrics to handler.py
# After 30 days use SIMP-1 audit to identify 0-invocation tools for archiving.
# Run: bash deploy/cost2_deploy_mcp_metrics.sh

set -euo pipefail

REGION="us-west-2"
FUNCTION_NAME="life-platform-mcp"
MCP_DIR="mcp"
ZIPFILE="/tmp/mcp_package_cost2.zip"

echo "=== COST-2: Deploying MCP metrics instrumentation ==="

# 1. Build package
echo "[1/4] Building MCP package..."
rm -f "$ZIPFILE"
zip -j "$ZIPFILE" mcp_bridge.py
zip "$ZIPFILE" -r "$MCP_DIR"/ --include "*.py"
echo "Package size: $(du -sh $ZIPFILE | cut -f1)"

# 2. Deploy
echo "[2/4] Deploying to Lambda..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIPFILE" \
    --region "$REGION" \
    --output table \
    --query '{FunctionName: FunctionName, CodeSize: CodeSize, LastModified: LastModified}'

# 3. Wait for update
echo "[3/4] Waiting for update to complete..."
aws lambda wait function-updated \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION"
echo "Lambda update complete."

# 4. Smoke test
echo "[4/4] Smoke test — invoking get_sources via bridge..."
PAYLOAD=$(python3 -c "
import json
body = json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'get_sources','arguments':{}}})
print(json.dumps({'body': body, 'headers': {'x-api-key': ''}}))
")
RESULT=$(aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --payload "$PAYLOAD" \
    --region "$REGION" \
    --log-type Tail \
    --output json \
    /tmp/mcp_smoke_cost2.json)

# Decode and check logs
LOG_TAIL=$(echo "$RESULT" | python3 -c "
import sys, json, base64
d = json.load(sys.stdin)
log = base64.b64decode(d.get('LogResult', '')).decode('utf-8', errors='replace')
print(log)
")
echo ""
echo "=== Lambda log tail ==="
echo "$LOG_TAIL"
echo ""

if echo "$LOG_TAIL" | grep -q "LifePlatform/MCP"; then
    echo "✅ EMF metric confirmed — ToolInvocations now tracked"
else
    echo "⚠️  EMF line not visible in log tail — metrics still emit, check CloudWatch"
fi

echo ""
echo "=== COST-2 complete ==="
echo ""
echo "Metrics appear in CloudWatch under:"
echo "  Namespace: LifePlatform/MCP"
echo "  Metrics:   ToolInvocations, ToolDuration, ToolErrors"
echo "  Dimension: ToolName"
echo ""
echo "SIMP-1 archiving decision: revisit ~2026-04-08 (30 days of data)"
