#!/bin/bash
# redeploy_all_cdk_lambdas.sh
# Redeploys all CDK-managed Lambdas using deploy_lambda.sh (correct zip packaging).
# CDK's Code.from_asset bundles files incorrectly for Lambda's handler resolution.
# deploy_lambda.sh produces the correct zip. Run this after any CDK deploy.
#
# Usage: bash deploy/redeploy_all_cdk_lambdas.sh

set -e
cd "$(dirname "$0")/.."

D="bash deploy/deploy_lambda.sh"
DELAY=10

echo "=== Redeploying all CDK-managed Lambdas ==="

# ── Compute stack (all self-contained, no --extra-files needed) ───────────────
echo "--- Compute stack ---"
$D adaptive-mode-compute       lambdas/adaptive_mode_lambda.py;      sleep $DELAY
$D anomaly-detector            lambdas/anomaly_detector_lambda.py;   sleep $DELAY
$D character-sheet-compute     lambdas/character_sheet_lambda.py;    sleep $DELAY
$D daily-insight-compute       lambdas/daily_insight_compute_lambda.py; sleep $DELAY
$D daily-metrics-compute       lambdas/daily_metrics_compute_lambda.py; sleep $DELAY
$D dashboard-refresh           lambdas/dashboard_refresh_lambda.py;  sleep $DELAY
$D hypothesis-engine           lambdas/hypothesis_engine_lambda.py;  sleep $DELAY

# ── Email stack (all import ai_calls + output_writers) ────────────────────────
echo ""
echo "--- Email stack ---"
SHARED="--extra-files lambdas/ai_calls.py lambdas/output_writers.py lambdas/board_loader.py lambdas/html_builder.py"
$D brittany-weekly-email       lambdas/brittany_email_lambda.py     $SHARED; sleep $DELAY
$D daily-brief                 lambdas/daily_brief_lambda.py        $SHARED; sleep $DELAY
$D monday-compass              lambdas/monday_compass_lambda.py     $SHARED; sleep $DELAY
$D monthly-digest              lambdas/monthly_digest_lambda.py     $SHARED; sleep $DELAY
$D nutrition-review            lambdas/nutrition_review_lambda.py   $SHARED; sleep $DELAY
$D wednesday-chronicle         lambdas/wednesday_chronicle_lambda.py $SHARED; sleep $DELAY
$D weekly-digest               lambdas/weekly_digest_lambda.py      $SHARED; sleep $DELAY
$D weekly-plate                lambdas/weekly_plate_lambda.py       $SHARED; sleep $DELAY

# ── Mcp stack ─────────────────────────────────────────────────────────────────
echo ""
echo "--- Mcp stack ---"
$D life-platform-mcp           lambdas/mcp_server.py; sleep $DELAY

# ── Operational stack (all self-contained) ────────────────────────────────────
echo ""
echo "--- Operational stack ---"
$D life-platform-dlq-consumer        lambdas/dlq_consumer_lambda.py;      sleep $DELAY
$D life-platform-canary              lambdas/canary_lambda.py;             sleep $DELAY
$D life-platform-pip-audit           lambdas/pip_audit_lambda.py;          sleep $DELAY
$D life-platform-qa-smoke            lambdas/qa_smoke_lambda.py;           sleep $DELAY
$D life-platform-key-rotator         lambdas/key_rotator_lambda.py;        sleep $DELAY
$D life-platform-data-export         lambdas/data_export_lambda.py;        sleep $DELAY
$D life-platform-data-reconciliation lambdas/data_reconciliation_lambda.py

echo ""
echo "=== All CDK-managed Lambdas redeployed ==="
