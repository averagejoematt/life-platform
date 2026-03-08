#!/usr/bin/env bash
# deploy_unified.sh — Canonical deploy tool for all Life Platform Lambdas
#
# Delegates to deploy_lambda.sh (which auto-reads handler config from AWS
# to determine correct zip entry filename — prevents handler mismatch bugs).
#
# Usage:
#   ./deploy/deploy_unified.sh <target>
#   ./deploy/deploy_unified.sh list
#   ./deploy/deploy_unified.sh all
#
# Examples:
#   ./deploy/deploy_unified.sh daily-brief
#   ./deploy/deploy_unified.sh mcp
#   ./deploy/deploy_unified.sh garmin          # (uses fix_garmin_deps.sh for layer)
#
# v2.0.0 — 2026-03-08 — Updated for v2.93.0 (35 Lambdas), delegates to deploy_lambda.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
REGION="us-west-2"

info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

# ── Lambda registry ──────────────────────────────────────────────────────────
# Format: SHORT_NAME|AWS_FUNCTION_NAME|SOURCE_FILE|EXTRA_FILES (space-separated, or "PACKAGE" for MCP)
#
# EXTRA_FILES are bundled alongside the main source in the zip.
# Shared modules (retry_utils, board_loader, insight_writer) should be listed
# as extras for the Lambdas that need them.
#
# Note: Garmin uses fix_garmin_deps.sh (not deploy_lambda.sh) due to
# garminconnect/garth dependency bundle. See "garmin" case below.

declare -A REGISTRY
declare -a REGISTRY_ORDER

register() {
    local short="$1" aws_name="$2" source="$3" extras="${4:-}"
    REGISTRY["$short"]="$aws_name|$source|$extras"
    REGISTRY_ORDER+=("$short")
}

# ── Ingestion ──
register "whoop"         "whoop-data-ingestion"      "lambdas/whoop_lambda.py"
register "eightsleep"    "eightsleep-data-ingestion"  "lambdas/eightsleep_lambda.py"
# garmin: registered but handled specially (deps bundle required)
register "garmin"        "garmin-data-ingestion"      "lambdas/garmin_lambda.py"
register "strava"        "strava-data-ingestion"      "lambdas/strava_lambda.py"
register "withings"      "withings-data-ingestion"    "lambdas/withings_lambda.py"
register "habitify"      "habitify-data-ingestion"    "lambdas/habitify_lambda.py"
register "macrofactor"   "macrofactor-data-ingestion" "lambdas/macrofactor_lambda.py"
register "notion"        "notion-journal-ingestion"   "lambdas/notion_lambda.py"
register "todoist"       "todoist-data-ingestion"     "lambdas/todoist_lambda.py"
register "weather"       "weather-data-ingestion"     "lambdas/weather_lambda.py"
register "apple-health" "apple-health-ingestion"     "lambdas/apple_health_lambda.py"
register "hae-webhook"   "health-auto-export-webhook" "lambdas/health_auto_export_lambda.py"
register "enrichment"    "activity-enrichment"        "lambdas/enrichment_lambda.py"
register "journal-enrich" "journal-enrichment"        "lambdas/journal_enrichment_lambda.py"

# ── Email / Digest ──
# AI Lambdas need retry_utils + board_loader bundled
AI_SHARED="lambdas/retry_utils.py lambdas/board_loader.py lambdas/insight_writer.py"
register "daily-brief"   "daily-brief"                "lambdas/daily_brief_lambda.py"         "lambdas/ai_calls.py lambdas/html_builder.py lambdas/output_writers.py lambdas/board_loader.py lambdas/scoring_engine.py lambdas/retry_utils.py lambdas/insight_writer.py"
register "weekly-digest" "weekly-digest"              "lambdas/weekly_digest_v2_lambda.py"    "$AI_SHARED"
register "monthly-digest" "monthly-digest"            "lambdas/monthly_digest_lambda.py"      "$AI_SHARED"
register "nutrition-review" "nutrition-review"        "lambdas/nutrition_review_lambda.py"    "$AI_SHARED"
register "chronicle"     "wednesday-chronicle"        "lambdas/wednesday_chronicle_lambda.py" "$AI_SHARED"
register "weekly-plate"  "weekly-plate"               "lambdas/weekly_plate_lambda.py"        "$AI_SHARED"
register "monday-compass" "monday-compass"            "lambdas/monday_compass_lambda.py"      "$AI_SHARED"
register "anomaly"       "anomaly-detector"           "lambdas/anomaly_detector_lambda.py"    "lambdas/board_loader.py"

# ── Compute ──
register "character-sheet" "character-sheet-compute"  "lambdas/character_sheet_compute_lambda.py" "lambdas/scoring_engine.py"
register "adaptive-mode"   "adaptive-mode-compute"    "lambdas/adaptive_mode_compute_lambda.py"
register "daily-metrics"   "daily-metrics-compute"    "lambdas/daily_metrics_compute_lambda.py"
register "daily-insight"   "daily-insight-compute"    "lambdas/daily_insight_compute_lambda.py"   "lambdas/insight_writer.py"
register "hypothesis"      "hypothesis-engine"        "lambdas/hypothesis_engine_lambda.py"        "lambdas/insight_writer.py"

# ── Infrastructure ──
register "freshness"     "life-platform-freshness-checker" "lambdas/freshness_checker_lambda.py"
register "dropbox"       "dropbox-poll"               "lambdas/dropbox_poll_lambda.py"
register "insight-email" "insight-email-parser"       "lambdas/insight_email_parser_lambda.py"
register "key-rotator"   "life-platform-key-rotator"  "lambdas/key_rotator_lambda.py"
register "dashboard-refresh" "dashboard-refresh"      "lambdas/dashboard_refresh_lambda.py"
register "data-export"   "life-platform-data-export"  "lambdas/data_export_lambda.py"
register "qa-smoke"      "life-platform-qa-smoke"     "lambdas/qa_smoke_lambda.py"

# ── MCP (special package deploy) ──
register "mcp"           "life-platform-mcp"          "PACKAGE"

# ── Helpers ──────────────────────────────────────────────────────────────────

list_targets() {
    echo ""
    echo "Life Platform Lambda Registry (v2.93.0 — 35 Lambdas)"
    echo "══════════════════════════════════════════════════════"
    printf "  %-18s  %s\n" "SHORT NAME" "AWS FUNCTION NAME"
    printf "  %-18s  %s\n" "──────────" "─────────────────"
    for short in "${REGISTRY_ORDER[@]}"; do
        IFS='|' read -r aws_name source extras <<< "${REGISTRY[$short]}"
        printf "  %-18s  %s\n" "$short" "$aws_name"
    done
    echo ""
    echo "  Special: 'all' deploys everything with 10s pauses"
    echo ""
    echo "Usage: ./deploy/deploy_unified.sh <target>"
}

deploy_mcp_package() {
    info "Deploying MCP package (mcp_server.py + mcp/ directory)..."
    cd "$PROJECT_DIR"
    [ -d "mcp" ] || error "mcp/ package directory not found"
    local zip_file="/tmp/life-platform-mcp.zip"
    rm -f "$zip_file"
    zip -j "$zip_file" mcp_server.py > /dev/null
    zip -r "$zip_file" mcp/ -x "mcp/__pycache__/*" "mcp/*.pyc" > /dev/null
    aws lambda update-function-code \
        --function-name "life-platform-mcp" \
        --zip-file "fileb://$zip_file" \
        --region "$REGION" \
        --no-cli-pager > /dev/null
    rm -f "$zip_file"
    info "✅ life-platform-mcp deployed"
}

deploy_garmin_with_deps() {
    info "Deploying garmin-data-ingestion with garminconnect/garth bundle..."
    info "(This takes ~60s to pip install deps for linux/x86_64)"
    bash "$SCRIPT_DIR/fix_garmin_deps.sh"
}

deploy_target() {
    local target="$1"
    [ "${REGISTRY[$target]+exists}" ] || error "Unknown target: '$target'. Run 'list' for options."

    IFS='|' read -r aws_name source extras <<< "${REGISTRY[$target]}"

    if [ "$source" = "PACKAGE" ]; then
        deploy_mcp_package
        return
    fi

    if [ "$target" = "garmin" ]; then
        deploy_garmin_with_deps
        return
    fi

    # Build --extra-files args
    local extra_args=()
    if [ -n "$extras" ]; then
        extra_args=(--extra-files)
        for f in $extras; do
            [ -f "$PROJECT_DIR/$f" ] && extra_args+=("$PROJECT_DIR/$f") || warn "Extra file not found: $f (skipping)"
        done
    fi

    cd "$PROJECT_DIR"
    bash "$SCRIPT_DIR/deploy_lambda.sh" "$aws_name" "$source" "${extra_args[@]+"${extra_args[@]}"}"
}

# ── Main ──────────────────────────────────────────────────────────────────────
[ $# -ge 1 ] || { list_targets; exit 0; }
TARGET="$1"

case "$TARGET" in
    list)
        list_targets
        ;;
    all)
        info "Deploying ALL ${#REGISTRY_ORDER[@]} Lambdas..."
        DEPLOYED=0
        FAILED=0
        FAILED_NAMES=()
        for short in "${REGISTRY_ORDER[@]}"; do
            info "── $short ──"
            if deploy_target "$short"; then
                DEPLOYED=$((DEPLOYED + 1))
            else
                warn "FAILED: $short"
                FAILED=$((FAILED + 1))
                FAILED_NAMES+=("$short")
            fi
            sleep 10
        done
        echo ""
        info "Complete: $DEPLOYED deployed, $FAILED failed"
        [ $FAILED -eq 0 ] || warn "Failed: ${FAILED_NAMES[*]}"
        ;;
    *)
        deploy_target "$TARGET"
        ;;
esac
