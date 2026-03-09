#!/bin/bash
# deploy_ic_phase2.sh — Deploy IC-23/24/25 + IC-16 (all digests) + IC-19 (Decision Journal)
#
# What's deployed:
#   1. daily-brief: IC-23 (surprise scoring), IC-24 (data quality), IC-25 (diminishing returns)
#      via updated ai_calls.py
#   2. weekly-digest: IC-16 (progressive context + insight write) + insight_writer.py
#   3. monthly-digest: IC-16 + insight_writer.py
#   4. wednesday-chronicle: IC-16 + insight_writer.py
#   5. nutrition-review: IC-16 + insight_writer.py
#   6. weekly-plate: IC-16 + insight_writer.py
#   7. life-platform-mcp: IC-19 (Decision Journal — 3 new tools, 139→142)
#
# Uses deploy_lambda.sh which auto-reads handler config from AWS.

set -euo pipefail

echo "🧠 IC Phase 2: IC-23/24/25 + IC-16 (all digests) + IC-19 (Decision Journal)"
echo "=============================================================================="

# ── 1. Daily Brief (IC-23, IC-24, IC-25 in ai_calls.py) ──
echo ""
echo "📧 1/7: daily-brief (IC-23 Surprise Scoring + IC-24 Data Quality + IC-25 Diminishing Returns)"
bash deploy/deploy_lambda.sh daily-brief lambdas/daily_brief_lambda.py \
    --extra-files lambdas/ai_calls.py lambdas/html_builder.py \
    lambdas/output_writers.py lambdas/board_loader.py lambdas/scoring_engine.py \
    lambdas/insight_writer.py

sleep 10

# ── 2. Weekly Digest (IC-16) ──
echo ""
echo "📊 2/7: weekly-digest (IC-16 Progressive Context)"
bash deploy/deploy_lambda.sh weekly-digest lambdas/weekly_digest_lambda.py \
    --extra-files lambdas/board_loader.py lambdas/insight_writer.py

sleep 10

# ── 3. Monthly Digest (IC-16) ──
echo ""
echo "📅 3/7: monthly-digest (IC-16 Progressive Context — 90-day window)"
bash deploy/deploy_lambda.sh monthly-digest lambdas/monthly_digest_lambda.py \
    --extra-files lambdas/board_loader.py lambdas/insight_writer.py

sleep 10

# ── 4. Wednesday Chronicle (IC-16) ──
echo ""
echo "📝 4/7: wednesday-chronicle (IC-16 Progressive Context — narrative threads)"
bash deploy/deploy_lambda.sh wednesday-chronicle lambdas/wednesday_chronicle_lambda.py \
    --extra-files lambdas/board_loader.py lambdas/insight_writer.py

sleep 10

# ── 5. Nutrition Review (IC-16) ──
echo ""
echo "🥗 5/7: nutrition-review (IC-16 Progressive Context — nutrition insights)"
bash deploy/deploy_lambda.sh nutrition-review lambdas/nutrition_review_lambda.py \
    --extra-files lambdas/board_loader.py lambdas/insight_writer.py

sleep 10

# ── 6. Weekly Plate (IC-16) ──
echo ""
echo "🍽️ 6/7: weekly-plate (IC-16 Progressive Context — meal planning)"
bash deploy/deploy_lambda.sh weekly-plate lambdas/weekly_plate_lambda.py \
    --extra-files lambdas/board_loader.py lambdas/insight_writer.py

sleep 10

# ── 7. MCP Server (IC-19 Decision Journal) ──
echo ""
echo "🔧 7/7: life-platform-mcp (IC-19 Decision Journal — 3 new tools)"
bash deploy/deploy_lambda.sh life-platform-mcp mcp_server.py \
    --extra-files mcp_bridge.py mcp/

echo ""
echo "=============================================================================="
echo "✅ All 7 Lambdas deployed."
echo ""
echo "IC-23 (Attention-Weighted Prompting)  → daily-brief"
echo "IC-24 (Data Quality Scoring)          → daily-brief, BoD, TL;DR, training coach"
echo "IC-25 (Diminishing Returns)           → daily-brief BoD + TL;DR"
echo "IC-16 (Progressive Context)           → all 6 email Lambdas"
echo "IC-19 (Decision Journal)              → MCP (142 tools)"
echo ""
echo "Verification:"
echo "  1. Tomorrow's daily brief: check CloudWatch for IC-24/23/25 context blocks"
echo "  2. Sunday weekly digest: IC-16 progressive context from daily brief insights"
echo "  3. MCP: test 'log_decision' tool immediately"
echo ""
echo "  # Quick MCP test:"
echo "  curl -s \$(aws lambda get-function-url-config --function-name life-platform-mcp \\"
echo "    --region us-west-2 --query 'FunctionUrl' --output text) \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\",\"params\":{}}' | python3 -m json.tool | grep -c name"
echo "  # Should show 142 tools (was 139)"
