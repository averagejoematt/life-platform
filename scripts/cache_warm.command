#!/bin/bash
# cache_warm.command — Manually trigger the nightly cache warmer Lambda
# Double-click in Finder to run, or: bash scripts/cache_warm.command

set -euo pipefail
cd "$(dirname "$0")/.."

FUNCTION_NAME="life-platform-mcp"
REGION="us-west-2"
SECRET_NAME="life-platform/mcp-api-key"

echo "════════════════════════════════════════════"
echo "  Life Platform — Trigger Cache Warmer"
echo "════════════════════════════════════════════"
echo ""

echo "▶ Fetching API key..."
API_KEY=$(aws secretsmanager get-secret-value \
  --secret-id "$SECRET_NAME" \
  --region "$REGION" \
  --query SecretString \
  --output text)
echo "  ✅ API key retrieved"
echo ""

echo "▶ Invoking cache warmer (this may take up to 2 minutes)..."
PAYLOAD=$(python3 -c "
import json
print(json.dumps({
    'headers': {'x-api-key': '$API_KEY'},
    'body': json.dumps({
        'jsonrpc': '2.0',
        'id': 1,
        'method': 'tools/call',
        'params': {
            'name': 'warm_cache',
            'arguments': {}
        }
    })
}))
")

aws lambda invoke \
  --function-name "$FUNCTION_NAME" \
  --region "$REGION" \
  --payload "$PAYLOAD" \
  --cli-binary-format raw-in-base64-out \
  --timeout 300 \
  /tmp/lp_warm.json > /dev/null

echo ""
echo "▶ Result:"
echo "────────────────────────────────────────────"
python3 -c "
import json
resp = json.loads(open('/tmp/lp_warm.json').read())
body = json.loads(resp.get('body', '{}'))
result = body.get('result', {})
content = result.get('content', [{}])
text = content[0].get('text', json.dumps(result, indent=2)) if content else json.dumps(result, indent=2)
try:
    parsed = json.loads(text)
    print(json.dumps(parsed, indent=2))
except:
    print(text)
"
echo "────────────────────────────────────────────"
echo ""
echo "✅ Cache warm complete."
echo ""
read -p "Press Enter to close..."
