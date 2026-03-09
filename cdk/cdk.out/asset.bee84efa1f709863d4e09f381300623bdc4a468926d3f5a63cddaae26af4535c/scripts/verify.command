#!/bin/bash
# verify.command — Confirm the deployed Lambda version and list tools
# Double-click in Finder to run, or: bash scripts/verify.command

set -euo pipefail
cd "$(dirname "$0")/.."

FUNCTION_NAME="life-platform-mcp"
REGION="us-west-2"
SECRET_NAME="life-platform/mcp-api-key"

echo "════════════════════════════════════════════"
echo "  Life Platform — Verify"
echo "════════════════════════════════════════════"
echo ""

# Fetch API key
echo "▶ Fetching API key..."
API_KEY=$(aws secretsmanager get-secret-value \
  --secret-id "$SECRET_NAME" \
  --region "$REGION" \
  --query SecretString \
  --output text)
echo "  ✅ API key retrieved"
echo ""

# Call initialize
echo "▶ Calling initialize..."
PAYLOAD=$(python3 -c "import json; print(json.dumps({'headers': {'x-api-key': '$API_KEY'}, 'body': json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{}})}))")

aws lambda invoke \
  --function-name "$FUNCTION_NAME" \
  --region "$REGION" \
  --payload "$PAYLOAD" \
  --cli-binary-format raw-in-base64-out \
  /tmp/lp_verify.json > /dev/null

VERSION=$(python3 -c "
import json
resp = json.loads(open('/tmp/lp_verify.json').read())
body = json.loads(resp['body'])
print(body.get('result', {}).get('serverInfo', {}).get('version', 'unknown'))
")
echo "  ✅ Server version : $VERSION"
echo ""

# Call tools/list
echo "▶ Listing tools..."
PAYLOAD2=$(python3 -c "import json; print(json.dumps({'headers': {'x-api-key': '$API_KEY'}, 'body': json.dumps({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})}))")

aws lambda invoke \
  --function-name "$FUNCTION_NAME" \
  --region "$REGION" \
  --payload "$PAYLOAD2" \
  --cli-binary-format raw-in-base64-out \
  /tmp/lp_tools.json > /dev/null

python3 -c "
import json
resp = json.loads(open('/tmp/lp_tools.json').read())
body = json.loads(resp['body'])
tools = body.get('result', {}).get('tools', [])
print(f'  ✅ {len(tools)} tools registered:')
for t in tools:
    print(f'       - {t[\"name\"]}')
"

echo ""
echo "════════════════════════════════════════════"
echo "  ✅ Verification complete"
echo "════════════════════════════════════════════"
echo ""
read -p "Press Enter to close..."
