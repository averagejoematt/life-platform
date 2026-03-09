#!/bin/bash
# fix_p1_infra.sh
# Fixes 4 P1 infrastructure items:
#   1. 30-day log retention on 10 log groups
#   2. Error alarms for 5 unmonitored Lambdas
#   3. Redeploys MCP Lambda (config.py version bump 2.50.0 → 2.74.0)
#   4. Redeploys weekly-digest (parameterised AWS clients)
#
# Usage:
#   cd ~/Documents/Claude/life-platform
#   bash deploy/fix_p1_infra.sh

set -euo pipefail
REGION="us-west-2"
REGION_USE1="us-east-1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
SNS_ARN="arn:aws:sns:us-west-2:205930651321:life-platform-alerts"

echo "=================================================="
echo "P1 Infra Fix: log retention + alarms + redeploys"
echo "=================================================="

# ── 1. Log retention (us-west-2 Lambdas) ─────────────
echo ""
echo "▶ Step 1/4: Setting 30-day log retention on 10 log groups..."

for LG in \
  "/aws/lambda/adaptive-mode-compute" \
  "/aws/lambda/character-sheet-compute" \
  "/aws/lambda/dashboard-refresh" \
  "/aws/lambda/life-platform-data-export" \
  "/aws/lambda/life-platform-key-rotator" \
  "/aws/lambda/nutrition-review" \
  "/aws/lambda/wednesday-chronicle" \
  "/aws/lambda/weekly-plate"; do
  aws logs put-retention-policy \
    --log-group-name "$LG" \
    --retention-in-days 30 \
    --region "$REGION" --no-cli-pager
  echo "   ✅ $LG"
done

# CloudFront auth functions live in us-east-1
for LG in \
  "/aws/lambda/us-east-1.life-platform-buddy-auth" \
  "/aws/lambda/us-east-1.life-platform-cf-auth"; do
  aws logs put-retention-policy \
    --log-group-name "$LG" \
    --retention-in-days 30 \
    --region "$REGION_USE1" --no-cli-pager
  echo "   ✅ $LG (us-east-1)"
done

# ── 2. Error alarms for 5 unmonitored Lambdas ─────
echo ""
echo "▶ Step 2/4: Creating error alarms for 5 unmonitored Lambdas..."

create_alarm() {
  local FN="$1"
  local PERIOD="$2"
  local ALARM_NAME="${FN}-errors"
  aws cloudwatch put-metric-alarm \
    --alarm-name "$ALARM_NAME" \
    --alarm-description "Errors in ${FN} Lambda" \
    --metric-name Errors \
    --namespace AWS/Lambda \
    --dimensions Name=FunctionName,Value="$FN" \
    --statistic Sum \
    --period "$PERIOD" \
    --evaluation-periods 1 \
    --threshold 1 \
    --comparison-operator GreaterThanOrEqualToThreshold \
    --treat-missing-data notBreaching \
    --alarm-actions "$SNS_ARN" \
    --region "$REGION" --no-cli-pager
  echo "   ✅ $ALARM_NAME (period: ${PERIOD}s)"
}

create_alarm "adaptive-mode-compute"      86400
create_alarm "character-sheet-compute"    86400
create_alarm "dashboard-refresh"          86400
create_alarm "life-platform-data-export"  86400     # 1-day window, catches monthly run errors within 24h
create_alarm "weekly-plate"               86400

# ── 3. Redeploy MCP Lambda (config.py version bump) ───
echo ""
echo "▶ Step 3/4: Redeploying life-platform-mcp (version bump 2.50.0 → 2.74.0)..."
# MCP is a multi-file package — must zip mcp_server.py + mcp/ directory together
MCP_WORK=$(mktemp -d)
cp "$ROOT_DIR/lambdas/mcp_server.py" "$MCP_WORK/mcp_server.py"
cp -r "$ROOT_DIR/mcp" "$MCP_WORK/mcp"
# Also copy board_loader.py which some Lambdas import directly
cp "$ROOT_DIR/lambdas/board_loader.py" "$MCP_WORK/board_loader.py" 2>/dev/null || true
(cd "$MCP_WORK" && zip -q -r deploy.zip mcp_server.py mcp/ board_loader.py 2>/dev/null || zip -q -r deploy.zip mcp_server.py mcp/)
aws lambda update-function-code \
  --function-name life-platform-mcp \
  --zip-file "fileb://$MCP_WORK/deploy.zip" \
  --region "$REGION" --no-cli-pager > /dev/null
LAST_MOD=$(aws lambda get-function-configuration --function-name life-platform-mcp --region "$REGION" --query LastModified --output text --no-cli-pager)
echo "   ✅ Deployed life-platform-mcp (modified: $LAST_MOD)"
rm -rf "$MCP_WORK"
sleep 10

# ── 4. Redeploy weekly-digest (env var fix) ────────────
echo ""
echo "▶ Step 4/4: Redeploying weekly-digest (parameterised AWS clients)..."
bash "$SCRIPT_DIR/deploy_lambda.sh" weekly-digest "$ROOT_DIR/lambdas/weekly_digest_lambda.py"

# ── Summary ──────────────────────────────────────────
echo ""
echo "=================================================="
echo "✅ P1 infra fix complete."
echo ""
echo "Verify:"
echo "  Alarms:    aws cloudwatch describe-alarms --alarm-names adaptive-mode-compute-errors character-sheet-compute-errors dashboard-refresh-errors life-platform-data-export-errors weekly-plate-errors --region us-west-2 --query 'MetricAlarms[].{Name:AlarmName,State:StateValue}'"
echo "  MCP ver:   aws lambda invoke --function-name life-platform-mcp --payload '{\"body\":\"{\\\"jsonrpc\\\":\\\"2.0\\\",\\\"method\\\":\\\"initialize\\\",\\\"params\\\":{},\\\"id\\\":1}\"}' --region us-west-2 --cli-binary-format raw-in-base64-out /tmp/mcp_ver.json && cat /tmp/mcp_ver.json"
echo "=================================================="
