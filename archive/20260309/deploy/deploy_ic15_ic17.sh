#!/bin/bash
# deploy_ic15_ic17.sh — Deploy IC-15 Insight Ledger + IC-17 Red Team
#
# IC-15: insight_writer.py — new shared module bundled with daily-brief
# IC-17: Contrarian analysis pass — ai_calls.py prompt changes
#
# Also re-deploys IC-3 + IC-6 changes from ai_calls.py (already deployed,
# but ai_calls.py has new IC-17 additions).

set -euo pipefail

REGION="us-west-2"

echo "🧠 Deploying IC-15 (Insight Ledger) + IC-17 (Red Team)"
echo "======================================================="

# ── Deploy daily-brief with insight_writer.py added to the bundle ──
echo ""
echo "📧 Deploying daily-brief (ai_calls.py + insight_writer.py + daily_brief_lambda.py)"

bash deploy/deploy_lambda.sh daily-brief lambdas/daily_brief_lambda.py \
    --extra-files lambdas/ai_calls.py lambdas/html_builder.py \
    lambdas/output_writers.py lambdas/board_loader.py lambdas/scoring_engine.py \
    lambdas/insight_writer.py

echo ""
echo "======================================================="
echo "✅ Done. Changes deployed:"
echo ""
echo "IC-15 — Insight Ledger:"
echo "  • insight_writer.py bundled with daily-brief"
echo "  • After each email, extracts BoD, TL;DR, guidance, training, nutrition, journal insights"
echo "  • Writes to pk=USER#matthew#SOURCE#insights, sk=INSIGHT#<timestamp>#daily_brief"
echo "  • 180-day TTL, non-fatal (try/except wrapped)"
echo ""
echo "IC-17 — Red Team:"
echo "  • IC-3 analysis pass now includes 'challenge' field (devil's advocate)"
echo "  • BoD + TL;DR prompts include RED TEAM CHECK instruction"
echo "  • Coaching adjusts confidence when pattern may be misleading"
echo ""
echo "Verify tomorrow's brief:"
echo "  1. Check CloudWatch after 10 AM PT for 'IC-15: X/Y insights persisted'"
echo "  2. BoD coaching should reference Red Team challenge if signal is weak"
echo ""
echo "To check insight records manually:"
echo "  aws dynamodb query \\"
echo "    --table-name life-platform \\"
echo "    --key-condition-expression 'pk = :pk AND begins_with(sk, :sk)' \\"
echo "    --expression-attribute-values '{\":pk\":{\"S\":\"USER#matthew#SOURCE#insights\"},\":sk\":{\"S\":\"INSIGHT#\"}}' \\"
echo "    --scan-index-forward false --limit 10 --region us-west-2 --no-cli-pager"
