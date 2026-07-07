#!/usr/bin/env bash
# deploy_mcp_split.sh — deploy the full MCP package to life-platform-mcp.
#
# The MCP Lambda is a MULTI-MODULE package: mcp_server.py + mcp_bridge.py + the whole mcp/
# directory. A single-file deploy drops the siblings and breaks the import graph, so this
# always ships the full package (the documented build in .claude/commands/deploy.md).
#
# Gate: refuses to deploy unless tests/test_mcp_registry.py is green (tool fns must be wired).
# Rollback: saves the currently-deployed code to /tmp before overwriting.
#
# Usage:  bash deploy/deploy_mcp_split.sh
set -euo pipefail

REGION="${AWS_REGION:-us-west-2}"
FN="life-platform-mcp"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "── 1. Registry gate (tests/test_mcp_registry.py) ──"
python3 -m pytest tests/test_mcp_registry.py -q || { echo "❌ registry test failed — fix wiring before deploy"; exit 1; }

echo "── 2. Rollback artifact (current deployed code) ──"
URL="$(aws lambda get-function --function-name "$FN" --region "$REGION" --query 'Code.Location' --output text 2>/dev/null || true)"
if [[ "$URL" == https* ]]; then
  RB="/tmp/${FN}_rollback_$(date +%s).zip"
  curl -s -o "$RB" "$URL" && echo "   saved → $RB"
else
  echo "   ⚠️  could not fetch current code for rollback (continuing)"
fi

echo "── 3. Build the full MCP bundle (#781: tree + mcp/, one staging implementation) ──"
ZIP="/tmp/mcp_deploy.zip"
python3 deploy/build_bundle.py --mcp --out /tmp/mcp_stage --zip "$ZIP"
echo "   sanity (entry + key modules in zip):"
unzip -l "$ZIP" | grep -E 'mcp_server.py|mcp/registry.py|reading/|hevy_compiler.py' | head -6 | sed 's/^/     /'

echo "── 4. Deploy ──"
aws lambda update-function-code --function-name "$FN" --zip-file "fileb://$ZIP" --region "$REGION" \
  --query '{State:State,LastUpdateStatus:LastUpdateStatus,CodeSize:CodeSize}' --output table
aws lambda wait function-updated --function-name "$FN" --region "$REGION"
echo "✅ $FN deployed (full bundle — shared modules included; no layer dependency)."
