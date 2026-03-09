#!/usr/bin/env bash
# v2.97.0: Deploy P1 hardening — SEC-3, REL-1, DATA-1, AI-2
# Deploys: mcp_server (SEC-3+AI-2), daily-brief + html_builder (REL-1+DATA-1), whoop (DATA-1)
#
# Run AFTER:
#   bash deploy/p3_build_shared_utils_layer.sh        (MAINT-2 — build layer)
#   LAYER_ARN=$(...)
#   bash deploy/p3_attach_shared_utils_layer.sh $LAYER_ARN   (MAINT-2 — attach)
#   bash deploy/sec2_split_secrets.sh                 (SEC-2 — secret split)
#   bash deploy/data1_backfill_schema_version.sh      (DATA-1 — backfill existing items)
#
# Run from project root: bash deploy/deploy_v2.97.0.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REGION="us-west-2"

deploy_lambda() {
  local NAME="$1"
  local HANDLER_FILE="$2"
  shift 2
  local EXTRAS=("$@")

  echo ""
  echo "── Deploying $NAME ──"
  cd /tmp
  rm -rf deploy_tmp && mkdir deploy_tmp
  cp "$ROOT/lambdas/$HANDLER_FILE" deploy_tmp/
  for f in "${EXTRAS[@]:-}"; do
    [ -n "$f" ] && cp "$ROOT/lambdas/$f" deploy_tmp/ 2>/dev/null || true
  done
  cd deploy_tmp
  zip -q -r "/tmp/${NAME}.zip" .
  aws lambda update-function-code \
    --function-name "$NAME" \
    --zip-file "fileb:///tmp/${NAME}.zip" \
    --region "$REGION" \
    --output text --query 'FunctionName'
  echo "  ✅ $NAME deployed"
  sleep 10
}

echo "=== v2.97.0: P1 Hardening Deploy ==="
echo ""
echo "Changes:"
echo "  SEC-3  — MCP input validation (_validate_tool_args in mcp_server.py)"
echo "  REL-1  — Compute staleness detection in daily_brief + html_builder"
echo "  DATA-1 — schema_version=1 on DDB writes (daily_brief, whoop)"
echo "  AI-2   — Correlational language in tool descriptions (mcp_server.py)"
echo ""

# MCP server — SEC-3 + AI-2
deploy_lambda "life-platform-mcp" "mcp_server.py"

# Daily Brief — REL-1 + DATA-1
deploy_lambda "daily-brief" "daily_brief_lambda.py" \
  "html_builder.py" "ai_calls.py" "output_writers.py" \
  "scoring_engine.py" "character_engine.py" "board_loader.py" \
  "retry_utils.py" "insight_writer.py"

# Whoop — DATA-1
deploy_lambda "whoop-data-ingestion" "whoop_lambda.py"

echo ""
echo "=== Deploy complete ==="
echo ""
echo "Verify:"
echo "  1. Invoke daily-brief manually and check CloudWatch for REL-1 log lines"
echo "  2. Call a MCP tool with bad args — should get {error: invalid_arguments}"
echo "  3. Check whoop DDB items have schema_version=1"
echo "     aws dynamodb get-item --table-name life-platform --region us-west-2 \\"
echo "       --key '{\"pk\":{\"S\":\"USER#matthew#SOURCE#whoop\"},\"sk\":{\"S\":\"DATE#$(date +%Y-%m-%d)\"}}' \\"
echo "       --query 'Item.schema_version'"
