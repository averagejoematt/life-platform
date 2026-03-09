#!/bin/bash
# deploy_v2.40.0_travel_bp.sh — Deploy Features #23 (Travel) + #24 (Blood Pressure)
# Deploys: MCP server (93 tools), anomaly detector v2.1.0, webhook v1.4.0, daily brief v2.5.0
# Created: 2026-02-27

set -euo pipefail
cd ~/Documents/Claude/life-platform

echo "═══════════════════════════════════════════════════════════════"
echo "  Life Platform v2.40.0 — Travel & Blood Pressure Deploy"
echo "═══════════════════════════════════════════════════════════════"

# ── Step 0: Backup ────────────────────────────────────────────────────────────
echo ""
echo "── Step 0: Creating backups..."
cp mcp_server.py mcp_server.py.bak.f23f24
echo "   ✓ Root mcp_server.py backed up"

# ── Step 1: Sync root → lambdas/ ──────────────────────────────────────────────
echo ""
echo "── Step 1: Syncing mcp_server.py to lambdas/..."
cp mcp_server.py lambdas/mcp_server.py
echo "   ✓ lambdas/mcp_server.py synced ($(wc -c < lambdas/mcp_server.py) bytes)"

# ── Step 2: Deploy MCP Server Lambda (93 tools) ──────────────────────────────
echo ""
echo "── Step 2: Deploying MCP server (93 tools)..."
cd lambdas
rm -f mcp_server.zip
zip mcp_server.zip mcp_server.py
aws lambda update-function-code \
    --function-name life-platform-mcp \
    --zip-file fileb://mcp_server.zip \
    --region us-west-2 \
    --no-cli-pager
echo "   ✓ MCP server deployed"
cd ..

# Wait between deploys to avoid throttling
echo "   Waiting 10s..."
sleep 10

# ── Step 3: Deploy Anomaly Detector v2.1.0 ───────────────────────────────────
echo ""
echo "── Step 3: Deploying anomaly detector v2.1.0 (travel awareness)..."
cd lambdas
rm -f anomaly_detector_lambda.zip
zip anomaly_detector_lambda.zip anomaly_detector_lambda.py
aws lambda update-function-code \
    --function-name anomaly-detector \
    --zip-file fileb://anomaly_detector_lambda.zip \
    --region us-west-2 \
    --no-cli-pager
echo "   ✓ Anomaly detector v2.1.0 deployed"
cd ..

echo "   Waiting 10s..."
sleep 10

# ── Step 4: Deploy Webhook Lambda v1.4.0 ─────────────────────────────────────
echo ""
echo "── Step 4: Deploying webhook Lambda v1.4.0 (blood pressure)..."
cd lambdas
rm -f health_auto_export_lambda.zip
zip health_auto_export_lambda.zip health_auto_export_lambda.py
aws lambda update-function-code \
    --function-name health-auto-export-webhook \
    --zip-file fileb://health_auto_export_lambda.zip \
    --region us-west-2 \
    --no-cli-pager
echo "   ✓ Webhook v1.4.0 deployed"
cd ..

echo "   Waiting 10s..."
sleep 10

# ── Step 5: Deploy Daily Brief v2.5.0 ────────────────────────────────────────
echo ""
echo "── Step 5: Deploying daily brief v2.5.0 (travel banner + BP tile)..."
cd lambdas
rm -f daily_brief_lambda.zip
# Daily Brief requires lambda_function.py filename (convention)
cp daily_brief_lambda.py lambda_function.py
zip daily_brief_lambda.zip lambda_function.py
rm lambda_function.py
aws lambda update-function-code \
    --function-name daily-brief \
    --zip-file fileb://daily_brief_lambda.zip \
    --region us-west-2 \
    --no-cli-pager
echo "   ✓ Daily Brief v2.5.0 deployed"
cd ..

# ── Step 6: Verify ────────────────────────────────────────────────────────────
echo ""
echo "── Step 6: Verification..."
echo "   Checking tool count via MCP..."

TOOL_COUNT=$(aws lambda invoke \
    --function-name life-platform-mcp \
    --payload '{"method":"tools/list","params":{},"jsonrpc":"2.0","id":"verify"}' \
    --region us-west-2 \
    --cli-binary-format raw-in-base64-out \
    /tmp/mcp_verify.json \
    --no-cli-pager 2>/dev/null && python3 -c "
import json
with open('/tmp/mcp_verify.json') as f:
    data = json.load(f)
    tools = data.get('result', {}).get('tools', [])
    print(len(tools))
" 2>/dev/null || echo "?")

echo "   Tools registered: ${TOOL_COUNT} (expected: 93)"

# Check for new tools
echo ""
echo "   New tools to verify:"
echo "   - log_travel"
echo "   - get_travel_log"
echo "   - get_jet_lag_recovery"
echo "   - get_blood_pressure_dashboard"
echo "   - get_blood_pressure_correlation"

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  ✅ Deploy complete! v2.40.0"
echo ""
echo "  Post-deploy testing:"
echo "  1. In Claude Desktop: 'I'm traveling to London next week'"
echo "  2. In Claude Desktop: 'show my BP status'"
echo "  3. Check anomaly detector: 'show anomaly record for today'"
echo "  4. Verify daily brief email tomorrow morning"
echo "═══════════════════════════════════════════════════════════════"
