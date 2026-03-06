#!/bin/bash
# Deploy Character Sheet Phase 4 — Daily Brief + Weekly Digest
# Rewards + Protocol Recs in Daily Brief HTML
# Character Section in Weekly Digest
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Character Sheet Phase 4 Deploy ==="

echo ""
echo "[1/2] Deploying Daily Brief Lambda..."
bash deploy/deploy_lambda.sh daily-brief lambdas/daily_brief_lambda.py
echo "  ✅ Daily Brief deployed"

echo ""
echo "Waiting 10s between deploys..."
sleep 10

echo "[2/2] Deploying Weekly Digest Lambda..."
bash deploy/deploy_lambda.sh weekly-digest lambdas/weekly_digest_lambda.py
echo "  ✅ Weekly Digest deployed"

echo ""
echo "=== Phase 4 Deploy Complete ==="
echo "Daily Brief: rewards + protocol recs wired into character sheet HTML"
echo "Weekly Digest: character_section built from weekly character sheet data"
echo ""
echo "Next: test Daily Brief with regrade, verify Weekly Digest on Sunday"
