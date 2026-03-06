#!/bin/bash
# Deploy v2.73.0 — Adaptive Email Frequency (#50)
# New Lambda: adaptive-mode-compute (29th)
# Modified: daily_brief_lambda (brief_mode integration)
# New MCP module: tools_adaptive.py (1 tool → 121 total)
# New EventBridge: adaptive-mode-compute at 9:36 AM PT (17:36 UTC)

set -e
REGION="us-west-2"
ACCOUNT="205930651321"
LAMBDA_ROLE=$(aws lambda get-function-configuration \
    --function-name character-sheet-compute \
    --region $REGION \
    --output text --query 'Role' 2>/dev/null || \
  aws lambda get-function-configuration \
    --function-name life-platform-mcp \
    --region $REGION \
    --output text --query 'Role')
echo "  Using IAM role: $LAMBDA_ROLE"
DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
LAMBDAS_DIR="${DEPLOY_DIR}/../lambdas"
MCP_DIR="${DEPLOY_DIR}/../"

echo "=== Life Platform v2.73.0 Deploy: Adaptive Email Frequency ==="

# ── 1. Deploy adaptive-mode-compute Lambda (NEW) ──────────────────────────────
echo ""
echo "Step 1: Create/update adaptive-mode-compute Lambda..."
cd /tmp && rm -rf adaptive_mode_build && mkdir adaptive_mode_build
cp "${LAMBDAS_DIR}/adaptive_mode_lambda.py" adaptive_mode_build/lambda_function.py
cd adaptive_mode_build && zip -q adaptive_mode.zip lambda_function.py

# Check if Lambda exists
if aws lambda get-function --function-name adaptive-mode-compute --region $REGION 2>/dev/null; then
    echo "  Updating existing Lambda..."
    aws lambda update-function-code \
        --function-name adaptive-mode-compute \
        --zip-file fileb:///tmp/adaptive_mode_build/adaptive_mode.zip \
        --region $REGION > /dev/null
else
    echo "  Creating new Lambda..."
    aws lambda create-function \
        --function-name adaptive-mode-compute \
        --runtime python3.12 \
        --role $LAMBDA_ROLE \
        --handler lambda_function.lambda_handler \
        --zip-file fileb:///tmp/adaptive_mode_build/adaptive_mode.zip \
        --timeout 60 \
        --memory-size 256 \
        --environment "Variables={TABLE_NAME=life-platform,USER_ID=matthew}" \
        --region $REGION > /dev/null
fi
echo "  ✓ adaptive-mode-compute deployed"
sleep 10

# ── 2. Deploy daily_brief_lambda (MODIFIED) ───────────────────────────────────
echo ""
echo "Step 2: Deploy updated daily_brief_lambda..."
cd /tmp && rm -rf daily_brief_build && mkdir daily_brief_build
cp "${LAMBDAS_DIR}/daily_brief_lambda.py" daily_brief_build/lambda_function.py
# board_loader is a dependency
cp "${LAMBDAS_DIR}/board_loader.py" daily_brief_build/board_loader.py 2>/dev/null || true
cd daily_brief_build && zip -q daily_brief.zip *.py

aws lambda update-function-code \
    --function-name daily-brief \
    --zip-file fileb:///tmp/daily_brief_build/daily_brief.zip \
    --region $REGION > /dev/null
echo "  ✓ daily-brief updated"
sleep 10

# ── 3. Deploy MCP server (tools_adaptive.py added) ────────────────────────────
echo ""
echo "Step 3: Deploy MCP server with tools_adaptive module..."
cd /tmp && rm -rf mcp_build && mkdir mcp_build
cp "${MCP_DIR}/mcp_server.py" mcp_build/
cp "${MCP_DIR}/mcp_bridge.py" mcp_build/
cp -r "${MCP_DIR}/mcp/" mcp_build/mcp/
# Include board_loader if present
cp "${LAMBDAS_DIR}/board_loader.py" mcp_build/ 2>/dev/null || true
cd mcp_build && zip -qr mcp_server.zip . --exclude "*.pyc" --exclude "__pycache__/*"

aws lambda update-function-code \
    --function-name life-platform-mcp \
    --zip-file fileb:///tmp/mcp_build/mcp_server.zip \
    --region $REGION > /dev/null
echo "  ✓ MCP server updated (121 tools)"
sleep 10

# ── 4. Create EventBridge rule: 9:36 AM PT = 17:36 UTC ───────────────────────
echo ""
echo "Step 4: Create EventBridge rule for adaptive-mode-compute..."
aws events put-rule \
    --name "adaptive-mode-compute" \
    --schedule-expression "cron(36 17 * * ? *)" \
    --state ENABLED \
    --description "Compute adaptive brief mode daily at 9:36 AM PT" \
    --region $REGION > /dev/null

ADAPTIVE_ARN="arn:aws:lambda:${REGION}:${ACCOUNT}:function:adaptive-mode-compute"

# Add Lambda permission for EventBridge (ignore if already exists)
aws lambda add-permission \
    --function-name adaptive-mode-compute \
    --statement-id EventBridgeAdaptiveMode \
    --action lambda:InvokeFunction \
    --principal events.amazonaws.com \
    --source-arn "arn:aws:events:${REGION}:${ACCOUNT}:rule/adaptive-mode-compute" \
    --region $REGION 2>/dev/null || echo "  (permission already exists)"

aws events put-targets \
    --rule adaptive-mode-compute \
    --targets "Id=1,Arn=${ADAPTIVE_ARN}" \
    --region $REGION > /dev/null
echo "  ✓ EventBridge rule created: adaptive-mode-compute at 9:36 AM PT"

# ── 5. Backfill last 7 days ───────────────────────────────────────────────────
echo ""
echo "Step 5: Backfill adaptive mode for last 7 days..."
for i in 7 6 5 4 3 2 1; do
    DATE=$(date -v-${i}d '+%Y-%m-%d' 2>/dev/null || date -d "${i} days ago" '+%Y-%m-%d')
    echo "  Computing ${DATE}..."
    RESULT=$(aws lambda invoke \
        --function-name adaptive-mode-compute \
        --payload "{\"date\":\"${DATE}\"}" \
        --region $REGION \
        /tmp/adaptive_out_${i}.json 2>&1)
    cat /tmp/adaptive_out_${i}.json | python3 -c "import sys,json; d=json.load(sys.stdin); print('    ' + d.get('date','?') + ': ' + d.get('brief_mode','?') + ' (score=' + str(d.get('engagement_score','?')) + ')')" 2>/dev/null || echo "    (check output)"
    sleep 2
done

# ── 6. Smoke test MCP ─────────────────────────────────────────────────────────
echo ""
echo "Step 6: Smoke test MCP server..."
aws lambda invoke \
    --function-name life-platform-mcp \
    --payload '{"type":"tools/call","name":"get_adaptive_mode","arguments":{"days":7}}' \
    --region $REGION \
    /tmp/mcp_smoke.json > /dev/null 2>&1
echo "  MCP smoke test response:"
cat /tmp/mcp_smoke.json | python3 -c "import sys,json; d=json.load(sys.stdin); print('  ' + str(d)[:200])" 2>/dev/null || cat /tmp/mcp_smoke.json | head -3

echo ""
echo "=== v2.73.0 Deploy Complete ==="
echo ""
echo "What was deployed:"
echo "  ✓ adaptive-mode-compute Lambda (29th Lambda)"
echo "  ✓ daily-brief Lambda (brief_mode integration + adaptive banners)"
echo "  ✓ MCP server (121 tools: +get_adaptive_mode)"
echo "  ✓ EventBridge rule: 9:36 AM PT daily"
echo "  ✓ 7-day backfill"
echo ""
echo "Next daily brief will show:"
echo "  🌟 Flourishing banner (score ≥ 70) — celebratory BoD tone"
echo "  💛 Rough Patch banner (score < 40) — gentle, recovery-focused BoD"
echo "  No banner (standard mode, score 40-69) — current behaviour"
