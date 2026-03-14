#!/bin/bash
# deploy/deploy_tb7_apikeys_fixes.sh
# Deploys the 6 Lambdas with api-keys → correct secret defaults (TB7-4)
# Run: bash deploy/deploy_tb7_apikeys_fixes.sh

set -euo pipefail
cd "$(dirname "$0")/.."

echo "═══ TB7-4: Deploying 6 api-keys break-risk fixes ═══"
echo ""

LAMBDAS=(
  "daily-insight-compute:lambdas/daily_insight_compute_lambda.py"
  "health-auto-export-webhook:lambdas/health_auto_export_lambda.py"
  "life-platform-data-reconciliation:lambdas/data_reconciliation_lambda.py"
  "dropbox-poll:lambdas/dropbox_poll_lambda.py"
)

for entry in "${LAMBDAS[@]}"; do
  FUNC="${entry%%:*}"
  SRC="${entry##*:}"
  echo "→ Deploying $FUNC..."
  bash deploy/deploy_lambda.sh "$FUNC" "$SRC"
  echo "  ✅ $FUNC deployed"
  sleep 5
done

# MCP server (special — needs full mcp/ package)
echo "→ Deploying life-platform-mcp (tools_todoist.py fix)..."
WORK_DIR=$(mktemp -d)
HANDLER=$(aws lambda get-function-configuration --function-name life-platform-mcp --query "Handler" --output text --region us-west-2)
MODULE_NAME=$(echo "$HANDLER" | cut -d'.' -f1)
cp mcp_server.py "$WORK_DIR/${MODULE_NAME}.py"
cp -r mcp/ "$WORK_DIR/mcp/"
(cd "$WORK_DIR" && zip -r deploy.zip "${MODULE_NAME}.py" mcp/ -q)
aws lambda update-function-code --function-name life-platform-mcp --zip-file "fileb://$WORK_DIR/deploy.zip" --region us-west-2 > /dev/null
aws lambda wait function-updated --function-name life-platform-mcp --region us-west-2
echo "  ✅ life-platform-mcp deployed"
rm -rf "$WORK_DIR"

# CDK redeploy for canary env var fix
echo ""
echo "→ CDK deploy LifePlatformOperational (canary MCP_SECRET_NAME fix)..."
cd cdk
source .venv/bin/activate 2>/dev/null || true
npx cdk deploy LifePlatformOperational --require-approval never
cd ..

echo ""
echo "═══ All 6 api-keys fixes deployed ✅ ═══"
echo "Safe through March 17 permanent deletion."
