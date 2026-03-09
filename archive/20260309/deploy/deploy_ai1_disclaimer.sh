#!/usr/bin/env bash
# deploy_ai1_disclaimer.sh — Deploy AI-1 health disclaimer to all 8 email Lambdas
#
# Modified files:
#   html_builder.py           → Daily Brief footer
#   weekly_digest_lambda.py   → Weekly Digest footer
#   monday_compass_lambda.py  → Monday Compass footer
#   nutrition_review_lambda.py → Nutrition Review footer
#   wednesday_chronicle_lambda.py → Chronicle footer
#   weekly_plate_lambda.py    → Weekly Plate footer
#   monthly_digest_lambda.py  → Monthly Digest footer
#   anomaly_detector_lambda.py → Anomaly Detector footer

set -euo pipefail

ROOT="$HOME/Documents/Claude/life-platform"
LAMBDAS="$ROOT/lambdas"

echo "════════════════════════════════════════"
echo "  AI-1: Health Disclaimer Deploy"
echo "  Deploying to 7 Lambdas + 1 standalone"
echo "════════════════════════════════════════"
echo ""

# ── Daily Brief (html_builder.py is bundled with daily-brief) ───────────────
echo "1/8  daily-brief (includes html_builder.py)..."
bash "$ROOT/deploy/deploy_lambda.sh" daily-brief \
    "$LAMBDAS/daily_brief_lambda.py" \
    --extra-files \
        "$LAMBDAS/html_builder.py" \
        "$LAMBDAS/ai_calls.py" \
        "$LAMBDAS/output_writers.py" \
        "$LAMBDAS/board_loader.py" \
        "$LAMBDAS/insight_writer.py" \
        "$LAMBDAS/scoring_engine.py" \
        "$LAMBDAS/character_engine.py" \
        "$LAMBDAS/retry_utils.py"

sleep 10

# ── Weekly Digest ────────────────────────────────────────────────────────────
echo ""
echo "2/8  weekly-digest..."
bash "$ROOT/deploy/deploy_lambda.sh" weekly-digest \
    "$LAMBDAS/weekly_digest_lambda.py" \
    --extra-files \
        "$LAMBDAS/board_loader.py" \
        "$LAMBDAS/insight_writer.py" \
        "$LAMBDAS/scoring_engine.py" \
        "$LAMBDAS/character_engine.py" \
        "$LAMBDAS/retry_utils.py"

sleep 10

# ── Monthly Digest ───────────────────────────────────────────────────────────
echo ""
echo "3/8  monthly-digest..."
bash "$ROOT/deploy/deploy_lambda.sh" monthly-digest \
    "$LAMBDAS/monthly_digest_lambda.py" \
    --extra-files \
        "$LAMBDAS/board_loader.py" \
        "$LAMBDAS/insight_writer.py" \
        "$LAMBDAS/retry_utils.py"

sleep 10

# ── Monday Compass ───────────────────────────────────────────────────────────
echo ""
echo "4/8  monday-compass..."
bash "$ROOT/deploy/deploy_lambda.sh" monday-compass \
    "$LAMBDAS/monday_compass_lambda.py" \
    --extra-files \
        "$LAMBDAS/board_loader.py" \
        "$LAMBDAS/retry_utils.py"

sleep 10

# ── Nutrition Review ─────────────────────────────────────────────────────────
echo ""
echo "5/8  nutrition-review..."
bash "$ROOT/deploy/deploy_lambda.sh" nutrition-review \
    "$LAMBDAS/nutrition_review_lambda.py" \
    --extra-files \
        "$LAMBDAS/board_loader.py" \
        "$LAMBDAS/retry_utils.py"

sleep 10

# ── Wednesday Chronicle ──────────────────────────────────────────────────────
echo ""
echo "6/8  wednesday-chronicle..."
bash "$ROOT/deploy/deploy_lambda.sh" wednesday-chronicle \
    "$LAMBDAS/wednesday_chronicle_lambda.py" \
    --extra-files \
        "$LAMBDAS/board_loader.py" \
        "$LAMBDAS/insight_writer.py" \
        "$LAMBDAS/retry_utils.py"

sleep 10

# ── Weekly Plate ─────────────────────────────────────────────────────────────
echo ""
echo "7/8  weekly-plate..."
bash "$ROOT/deploy/deploy_lambda.sh" weekly-plate \
    "$LAMBDAS/weekly_plate_lambda.py" \
    --extra-files \
        "$LAMBDAS/board_loader.py" \
        "$LAMBDAS/insight_writer.py" \
        "$LAMBDAS/retry_utils.py"

sleep 10

# ── Anomaly Detector ─────────────────────────────────────────────────────────
echo ""
echo "8/8  anomaly-detector..."
bash "$ROOT/deploy/deploy_lambda.sh" anomaly-detector \
    "$LAMBDAS/anomaly_detector_lambda.py"

echo ""
echo "════════════════════════════════════════"
echo "  ✅ All 8 Lambdas deployed."
echo "════════════════════════════════════════"
