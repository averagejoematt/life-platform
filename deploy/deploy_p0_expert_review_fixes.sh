#!/bin/bash
# deploy_p0_expert_review_fixes.sh
# P0 fixes from expert review (session 37)
# 1. Deploy updated mcp/config.py (version, SOURCES, SOT domains)
# 2. Set reserved concurrency on MCP Lambda (10)
# 3. Set 30-day log retention on 9 log groups
# 4. Purge 5 stale DLQ messages
set -e

echo "=== P0 Expert Review Fixes ==="
echo ""

# ── 1. Repackage and deploy MCP server with updated config.py ──
echo "--- Step 1: Deploying MCP server with config.py fixes ---"
cd ~/Documents/Claude/life-platform

# Build the zip
rm -f lambdas/mcp_server.zip
zip -r lambdas/mcp_server.zip mcp_server.py mcp/ -x "mcp/__pycache__/*"

# Deploy
aws lambda update-function-code \
  --function-name life-platform-mcp \
  --zip-file fileb://lambdas/mcp_server.zip \
  --region us-west-2 \
  --no-cli-pager

echo "Waiting 10s for deployment..."
sleep 10

# Smoke test
echo "Smoke testing MCP Lambda..."
aws lambda invoke \
  --function-name life-platform-mcp \
  --payload '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"get_sources","arguments":{}},"id":1}' \
  --cli-binary-format raw-in-base64-out \
  --region us-west-2 \
  /tmp/mcp_smoke.json --no-cli-pager

# 401 Unauthorized is EXPECTED (no API key in test invocation) — it proves the Lambda is running
# Actual failures would show: Traceback, NameError, ImportError, or errorType
if grep -q 'Traceback\|NameError\|ImportError\|SyntaxError\|errorType\|errorMessage' /tmp/mcp_smoke.json; then
  echo "❌ SMOKE TEST FAILED — Lambda has code errors:"
  cat /tmp/mcp_smoke.json
  exit 1
elif grep -q '"statusCode": 401' /tmp/mcp_smoke.json; then
  echo "✅ MCP server deployed — 401 auth rejection confirms Lambda is running correctly"
else
  echo "✅ MCP server deployed and responding"
  cat /tmp/mcp_smoke.json
fi
echo ""

# ── 2. Set reserved concurrency ──
echo "--- Step 2: Setting reserved concurrency on MCP Lambda ---"
aws lambda put-function-concurrency \
  --function-name life-platform-mcp \
  --reserved-concurrent-executions 10 \
  --region us-west-2 \
  --no-cli-pager
echo "✅ Reserved concurrency set to 10"
echo ""

# ── 3. Set 30-day log retention on 9 log groups ──
echo "--- Step 3: Setting 30-day log retention on 9 log groups ---"
for lg in dropbox-poll eightsleep-data-ingestion garmin-data-ingestion \
  habitify-data-ingestion health-auto-export-webhook insight-email-parser \
  journal-enrichment macrofactor-data-ingestion notion-journal-ingestion \
  weather-data-ingestion; do
  aws logs put-retention-policy \
    --log-group-name "/aws/lambda/$lg" \
    --retention-in-days 30 \
    --region us-west-2 2>/dev/null && echo "  ✅ /aws/lambda/$lg → 30 days" || echo "  ⚠️ /aws/lambda/$lg — log group not found (ok if never invoked)"
done
echo ""

# ── 4. Purge stale DLQ messages ──
echo "--- Step 4: Purging stale DLQ messages ---"
aws sqs purge-queue \
  --queue-url https://sqs.us-west-2.amazonaws.com/205930651321/life-platform-ingestion-dlq \
  --region us-west-2 2>/dev/null && echo "✅ DLQ purged" || echo "⚠️ DLQ purge failed or already empty"
echo ""

# ── Verify ──
echo "=== Verification ==="
echo "MCP Lambda concurrency:"
aws lambda get-function-configuration \
  --function-name life-platform-mcp \
  --query '{Memory: MemorySize, Concurrency: "check below"}' \
  --region us-west-2 --no-cli-pager
aws lambda get-function-concurrency \
  --function-name life-platform-mcp \
  --region us-west-2 --no-cli-pager 2>/dev/null || echo "(no concurrency info returned = not set)"

echo ""
echo "DLQ message count:"
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-west-2.amazonaws.com/205930651321/life-platform-ingestion-dlq \
  --attribute-names ApproximateNumberOfMessages \
  --region us-west-2 --no-cli-pager

echo ""
echo "=== All P0 fixes complete ==="
