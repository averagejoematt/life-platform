#!/bin/bash
set -euo pipefail

# Sync local .config.json with the current API key from Secrets Manager.
# Run this after key rotation to update the bridge transport.
#
# Usage: ./sync_bridge_key.sh

REGION="us-west-2"
SECRET_ID="life-platform/mcp-api-key"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="$(dirname "$SCRIPT_DIR")/.config.json"

echo "Fetching current API key from Secrets Manager..."
NEW_KEY=$(aws secretsmanager get-secret-value \
  --secret-id "$SECRET_ID" \
  --region "$REGION" \
  --query SecretString \
  --output text)

if [ -z "$NEW_KEY" ]; then
  echo "❌ Failed to retrieve API key"
  exit 1
fi

echo "Current key: ${NEW_KEY:0:8}...${NEW_KEY: -4} (${#NEW_KEY} chars)"

# Read existing config, update api_key, write back
if [ ! -f "$CONFIG_FILE" ]; then
  echo "❌ Config file not found: $CONFIG_FILE"
  exit 1
fi

# Use python for safe JSON manipulation
python3 -c "
import json
with open('$CONFIG_FILE') as f:
    config = json.load(f)
old_key = config.get('api_key', '???')
config['api_key'] = '$NEW_KEY'
with open('$CONFIG_FILE', 'w') as f:
    json.dump(config, f, indent=4)
    f.write('\n')
print(f'  Old: {old_key[:8]}...{old_key[-4:]}')
print(f'  New: {config[\"api_key\"][:8]}...{config[\"api_key\"][-4:]}')
"

echo ""
echo "✅ .config.json updated"
echo "⚠️  Restart Claude Desktop to pick up the new key (bridge transport only)"
echo "   Remote MCP (claude.ai/mobile) will auto-negotiate via OAuth within 5 min"
