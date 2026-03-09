#!/usr/bin/env bash
# deploy/prod2_phase1_deploy_all.sh
# Deploys all 40 Lambdas after PROD-2 Phase 1 changes.
# Usage: bash deploy/prod2_phase1_deploy_all.sh
# Estimated time: ~15 minutes

set -euo pipefail

REGION="us-west-2"
L="lambdas"
SUCCEEDED=0
FAILED=()

deploy() {
  local NAME="$1"
  local SRC="$2"
  shift 2
  local EXTRAS=("$@")

  echo ""
  echo "── $NAME ──"
  if [ ${#EXTRAS[@]} -gt 0 ]; then
    bash deploy/deploy_lambda.sh "$NAME" "$L/$SRC" --extra-files "${EXTRAS[@]}"
  else
    bash deploy/deploy_lambda.sh "$NAME" "$L/$SRC"
  fi
  SUCCEEDED=$((SUCCEEDED + 1))
  sleep 10
}

fail() {
  local NAME="$1"
  echo "  ❌ $NAME FAILED"
  FAILED+=("$NAME")
}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PROD-2 Phase 1 — Bulk Deploy (40 Lambdas)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Email / AI Lambdas (with bundled extras) ──────────────────────────────────

deploy "daily-brief" "daily_brief_lambda.py" \
  "$L/html_builder.py" "$L/ai_calls.py" "$L/output_writers.py" \
  "$L/scoring_engine.py" "$L/character_engine.py" "$L/board_loader.py" \
  "$L/retry_utils.py" "$L/insight_writer.py"

deploy "weekly-digest" "weekly_digest_lambda.py" \
  "$L/ai_calls.py" "$L/output_writers.py" \
  "$L/scoring_engine.py" "$L/character_engine.py" "$L/board_loader.py" \
  "$L/retry_utils.py" "$L/insight_writer.py"

deploy "monday-compass" "monday_compass_lambda.py" \
  "$L/board_loader.py" "$L/insight_writer.py"

deploy "weekly-plate" "weekly_plate_lambda.py" \
  "$L/board_loader.py" "$L/retry_utils.py" "$L/insight_writer.py"

deploy "nutrition-review"      "nutrition_review_lambda.py"
deploy "wednesday-chronicle"   "wednesday_chronicle_lambda.py"
deploy "monthly-digest"        "monthly_digest_lambda.py"
deploy "anomaly-detector"      "anomaly_detector_lambda.py"

# ── MCP + Compute ─────────────────────────────────────────────────────────────

deploy "life-platform-mcp"         "mcp_server.py"
deploy "character-sheet-compute"   "character_sheet_lambda.py"
deploy "dashboard-refresh"         "dashboard_refresh_lambda.py"
deploy "daily-metrics-compute"     "daily_metrics_compute_lambda.py"
deploy "daily-insight-compute"     "daily_insight_compute_lambda.py"
deploy "adaptive-mode-compute"     "adaptive_mode_lambda.py"
deploy "hypothesis-engine"         "hypothesis_engine_lambda.py"

# ── Ingestion Lambdas ─────────────────────────────────────────────────────────

deploy "whoop-data-ingestion"      "whoop_lambda.py"
deploy "withings-data-ingestion"   "withings_lambda.py"
deploy "eightsleep-data-ingestion" "eightsleep_lambda.py"
deploy "strava-data-ingestion"     "strava_lambda.py"
deploy "garmin-data-ingestion"     "garmin_lambda.py"
deploy "habitify-data-ingestion"   "habitify_lambda.py"
deploy "macrofactor-data-ingestion" "macrofactor_lambda.py"
deploy "todoist-data-ingestion"    "todoist_lambda.py"
deploy "notion-journal-ingestion"  "notion_lambda.py"
deploy "apple-health-ingestion"    "apple_health_lambda.py"
deploy "weather-data-ingestion"    "weather_lambda.py"
deploy "health-auto-export-webhook" "health_auto_export_lambda.py"

# ── Support / Utility Lambdas ─────────────────────────────────────────────────

deploy "activity-enrichment"              "enrichment_lambda.py"
deploy "journal-enrichment"               "journal_enrichment_lambda.py"
deploy "insight-email-parser"             "insight_email_parser_lambda.py"
deploy "life-platform-freshness-checker"  "freshness_checker_lambda.py"
deploy "life-platform-data-export"        "data_export_lambda.py"
deploy "life-platform-data-reconciliation" "data_reconciliation_lambda.py"
deploy "life-platform-dlq-consumer"       "dlq_consumer_lambda.py"
deploy "life-platform-pip-audit"          "pip_audit_lambda.py"
deploy "life-platform-qa-smoke"           "qa_smoke_lambda.py"
deploy "life-platform-canary"             "canary_lambda.py"
deploy "life-platform-key-rotator"        "key_rotator_lambda.py"
deploy "dropbox-poll"                     "dropbox_poll_lambda.py"
deploy "brittany-weekly-email"            "brittany_email_lambda.py"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Done: $SUCCEEDED/40 succeeded"

if [ ${#FAILED[@]} -gt 0 ]; then
  echo "Failed:"
  for f in "${FAILED[@]}"; do
    echo "  ❌ $f"
  done
  exit 1
else
  echo "All 40 Lambdas deployed. ✅"
fi
