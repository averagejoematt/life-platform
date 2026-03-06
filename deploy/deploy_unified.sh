#!/usr/bin/env bash
# deploy_unified.sh — Unified deployment for all Life Platform Lambdas
#
# Usage:
#   ./deploy/deploy_unified.sh <target>
#
# Targets:
#   mcp           — MCP server (package: mcp_server.py + mcp/)
#   daily-brief   — Daily Brief email
#   weekly-digest — Weekly Digest email
#   whoop         — Whoop ingestion
#   garmin        — Garmin ingestion
#   strava        — Strava ingestion
#   ... (any Lambda short name)
#   all           — Deploy everything (with 10s pauses)
#   list          — Show all available targets
#
# v1.0.0 — 2026-02-28

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
REGION="us-west-2"

info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

# ── Lambda registry ──────────────────────────────────────────────────────────
# Format: SHORT_NAME|AWS_FUNCTION_NAME|SOURCE_FILE|ZIP_ENTRY_NAME
# ZIP_ENTRY_NAME: what the file is called inside the zip (must match handler module)
# Special: "PACKAGE" means the MCP package deploy
REGISTRY=(
    "mcp|life-platform-mcp|PACKAGE|PACKAGE"
    "daily-brief|daily-brief|lambdas/daily_brief_lambda.py|lambda_function.py"
    "weekly-digest|weekly-digest|lambdas/weekly_digest_v2_lambda.py|digest_handler.py"
    "monthly-digest|monthly-digest|lambdas/monthly_digest_lambda.py|lambda_function.py"
    "anomaly|anomaly-detector|lambdas/anomaly_detector_lambda.py|lambda_function.py"
    "freshness|life-platform-freshness-checker|lambdas/freshness_checker_lambda.py|lambda_function.py"
    "whoop|whoop-data-ingestion|lambdas/whoop_lambda.py|lambda_function.py"
    "garmin|garmin-data-ingestion|lambdas/garmin_lambda.py|garmin_lambda.py"
    "strava|strava-data-ingestion|lambdas/strava_lambda.py|strava_lambda.py"
    "eightsleep|eightsleep-data-ingestion|lambdas/eightsleep_lambda.py|eightsleep_lambda.py"
    "withings|withings-data-ingestion|lambdas/withings_lambda.py|withings_lambda.py"
    "macrofactor|macrofactor-data-ingestion|lambdas/macrofactor_lambda.py|macrofactor_lambda.py"
    "todoist|todoist-data-ingestion|lambdas/todoist_lambda.py|lambda_function.py"
    "notion|notion-journal-ingestion|lambdas/notion_lambda.py|notion_lambda.py"
    "habitify|habitify-data-ingestion|lambdas/habitify_lambda.py|habitify_lambda.py"
    "apple-health|apple-health-ingestion|lambdas/apple_health_lambda.py|lambda_function.py"
    "hae-webhook|health-auto-export-webhook|lambdas/health_auto_export_lambda.py|health_auto_export_lambda.py"
    "enrichment|activity-enrichment|lambdas/enrichment_lambda.py|enrichment_lambda.py"
    "journal-enrich|journal-enrichment|lambdas/journal_enrichment_lambda.py|journal_enrichment_lambda.py"
    "dropbox|dropbox-poll|lambdas/dropbox_poll_lambda.py|dropbox_poll_lambda.py"
    "weather|weather-data-ingestion|lambdas/weather_lambda.py|weather_lambda.py"
    "insight-email|insight-email-parser|lambdas/insight_email_parser_lambda.py|lambda_function.py"
)

# ── Functions ─────────────────────────────────────────────────────────────────

list_targets() {
    echo "Available targets:"
    echo ""
    printf "  %-18s %-40s %s\n" "SHORT NAME" "AWS FUNCTION" "SOURCE"
    printf "  %-18s %-40s %s\n" "──────────" "────────────" "──────"
    for entry in "${REGISTRY[@]}"; do
        IFS='|' read -r short aws_name source zip_name <<< "$entry"
        printf "  %-18s %-40s %s\n" "$short" "$aws_name" "$source"
    done
    echo ""
    echo "  all               Deploy everything (with 10s pauses)"
}

deploy_single_lambda() {
    local source_file="$1"
    local zip_entry="$2"
    local aws_name="$3"
    local zip_file="/tmp/${aws_name}.zip"

    # Verify source exists
    [ -f "$PROJECT_DIR/$source_file" ] || error "Source not found: $source_file"

    # Syntax check
    python3 -c "import py_compile; py_compile.compile('$PROJECT_DIR/$source_file', doraise=True)" 2>/dev/null \
        || error "Syntax error in $source_file"

    # Create zip with correct entry name
    rm -f "$zip_file"
    if [ "$source_file" = "$zip_entry" ] || [ "$(basename "$source_file")" = "$zip_entry" ]; then
        # Source name matches zip entry — zip directly
        (cd "$PROJECT_DIR" && zip -j "$zip_file" "$source_file")
    else
        # Need to rename: copy to temp, zip with correct name
        local tmp_dir=$(mktemp -d)
        cp "$PROJECT_DIR/$source_file" "$tmp_dir/$zip_entry"
        (cd "$tmp_dir" && zip -j "$zip_file" "$zip_entry")
        rm -rf "$tmp_dir"
    fi

    # Deploy
    aws lambda update-function-code \
        --function-name "$aws_name" \
        --zip-file "fileb://$zip_file" \
        --region "$REGION" \
        --output text --query 'FunctionName' > /dev/null

    aws lambda wait function-updated \
        --function-name "$aws_name" \
        --region "$REGION"

    rm -f "$zip_file"
    info "✅ $aws_name deployed"
}

deploy_mcp_package() {
    info "Deploying MCP package..."
    # Use the dedicated MCP split deploy script if available
    if [ -x "$SCRIPT_DIR/deploy_mcp_split.sh" ]; then
        "$SCRIPT_DIR/deploy_mcp_split.sh"
    else
        # Inline MCP deploy
        cd "$PROJECT_DIR"
        [ -d "mcp" ] || error "mcp/ package not found"
        local zip_file="/tmp/mcp_server.zip"
        rm -f "$zip_file"
        zip -j "$zip_file" mcp_server.py
        zip -r "$zip_file" mcp/ -x "mcp/__pycache__/*" "mcp/*.pyc"
        aws lambda update-function-code \
            --function-name "life-platform-mcp" \
            --zip-file "fileb://$zip_file" \
            --region "$REGION" \
            --output text --query 'FunctionName' > /dev/null
        aws lambda wait function-updated \
            --function-name "life-platform-mcp" \
            --region "$REGION"
        rm -f "$zip_file"
        info "✅ life-platform-mcp deployed"
    fi
}

deploy_target() {
    local target="$1"
    for entry in "${REGISTRY[@]}"; do
        IFS='|' read -r short aws_name source zip_name <<< "$entry"
        if [ "$short" = "$target" ]; then
            if [ "$source" = "PACKAGE" ]; then
                deploy_mcp_package
            else
                deploy_single_lambda "$source" "$zip_name" "$aws_name"
            fi
            return 0
        fi
    done
    error "Unknown target: $target. Run with 'list' to see available targets."
}

# ── Main ──────────────────────────────────────────────────────────────────────
[ $# -ge 1 ] || { list_targets; exit 0; }
TARGET="$1"

cd "$PROJECT_DIR"

case "$TARGET" in
    list)
        list_targets
        ;;
    all)
        info "Deploying ALL ${#REGISTRY[@]} Lambdas..."
        DEPLOYED=0
        FAILED=0
        for entry in "${REGISTRY[@]}"; do
            IFS='|' read -r short aws_name source zip_name <<< "$entry"
            info "── Deploying $short ($aws_name) ──"
            if deploy_target "$short" 2>/dev/null; then
                DEPLOYED=$((DEPLOYED + 1))
            else
                warn "Failed: $short"
                FAILED=$((FAILED + 1))
            fi
            sleep 10
        done
        echo ""
        info "Complete: $DEPLOYED deployed, $FAILED failed"
        ;;
    *)
        deploy_target "$TARGET"
        ;;
esac
