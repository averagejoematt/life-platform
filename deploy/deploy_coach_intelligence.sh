#!/usr/bin/env bash
# deploy_coach_intelligence.sh — Deploy Coach Intelligence Architecture Lambdas
# Usage: bash deploy/deploy_coach_intelligence.sh [--skip-seed] [--skip-configs]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

SKIP_SEED=false
SKIP_CONFIGS=false
for arg in "$@"; do
  case "$arg" in
    --skip-seed) SKIP_SEED=true ;;
    --skip-configs) SKIP_CONFIGS=true ;;
  esac
done

echo "════════════════════════════════════════════════════════════"
echo "  Coach Intelligence Architecture — Deploy"
echo "════════════════════════════════════════════════════════════"
echo

# Step 1: Upload config files to S3
if [ "$SKIP_CONFIGS" = false ]; then
  echo "📁 Step 1: Uploading config files to S3..."
  aws s3 cp "$ROOT_DIR/config/computation/ewma_params.json" \
    s3://matthew-life-platform/config/computation/ewma_params.json
  aws s3 cp "$ROOT_DIR/config/computation/seasonal_adjustments.json" \
    s3://matthew-life-platform/config/computation/seasonal_adjustments.json
  aws s3 cp "$ROOT_DIR/config/coaches/influence_graph.json" \
    s3://matthew-life-platform/config/coaches/influence_graph.json
  aws s3 cp "$ROOT_DIR/config/narrative/arc_definitions.json" \
    s3://matthew-life-platform/config/narrative/arc_definitions.json

  # Upload coach voice specs — every non-stance JSON, matching build_bundle's
  # glob exactly (v2 roster added _shared_standard.json + eli_marsh.json, which
  # the old *_coach.json glob silently skipped — S3-first reads would then serve
  # a stale substrate forever). Stance files stay S3-only, engine-written.
  for f in "$ROOT_DIR"/config/coaches/*.json; do
    case "$(basename "$f")" in *_stance.json) continue ;; esac
    [ -f "$f" ] && aws s3 cp "$f" "s3://matthew-life-platform/config/coaches/$(basename "$f")"
  done
  # The persona registry itself (the known ADD_A_COACH.md §10 gap, now closed).
  aws s3 cp "$ROOT_DIR/config/personas.json" s3://matthew-life-platform/config/personas.json
  echo "✅ Config files uploaded"
  echo
else
  echo "⏭️  Skipping config upload (--skip-configs)"
  echo
fi

# Step 2: Deploy Lambdas
echo "🚀 Step 2: Deploying Lambdas..."

bash "$SCRIPT_DIR/deploy_lambda.sh" coach-computation-engine \
  "$ROOT_DIR/lambdas/coach/coach_computation_engine.py"
sleep 2

bash "$SCRIPT_DIR/deploy_lambda.sh" coach-narrative-orchestrator \
  "$ROOT_DIR/lambdas/coach/coach_narrative_orchestrator.py"
sleep 2

bash "$SCRIPT_DIR/deploy_lambda.sh" coach-state-updater \
  "$ROOT_DIR/lambdas/coach/coach_state_updater.py"

echo
echo "✅ All Lambdas deployed"
echo

# Step 3: Seed initial state
if [ "$SKIP_SEED" = false ]; then
  echo "🌱 Step 3: Seeding initial coach state..."
  cd "$ROOT_DIR"
  python3 seeds/seed_coach_state.py
  echo "✅ Seed complete"
  echo
else
  echo "⏭️  Skipping seed (--skip-seed)"
  echo
fi

echo "════════════════════════════════════════════════════════════"
echo "  Deploy complete"
echo "════════════════════════════════════════════════════════════"
