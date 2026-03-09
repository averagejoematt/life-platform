#!/bin/bash
# PROD-2 Phase 2: Deploy updated Lambdas
# Run AFTER migrate_s3_prod2_phase2.sh completes successfully.

set -e

D="deploy/deploy_lambda.sh"

echo "=== PROD-2 Phase 2: Lambda deploys ==="
echo ""

deploy() {
    local NAME=$1
    shift
    echo "━━━ Deploying $NAME ━━━"
    bash "$D" "$NAME" "$@"
    echo "✅ $NAME deployed"
    echo "Waiting 10s..."
    sleep 10
}

# ── Ingestion Lambdas (raw/ write paths changed) ──
echo "--- Ingestion Lambdas ---"
deploy "health-auto-export-webhook" lambdas/health_auto_export_lambda.py
deploy "whoop-data-ingestion"       lambdas/whoop_lambda.py
deploy "strava-data-ingestion"      lambdas/strava_lambda.py
deploy "garmin-data-ingestion"      lambdas/garmin_lambda.py
deploy "macrofactor-data-ingestion" lambdas/macrofactor_lambda.py
deploy "apple-health-ingestion"     lambdas/apple_health_lambda.py
deploy "withings-data-ingestion"    lambdas/withings_lambda.py
deploy "eightsleep-data-ingestion"  lambdas/eightsleep_lambda.py

# ── Character Sheet compute (uses character_engine.load_character_config) ──
echo "--- Compute Lambdas ---"
deploy "character-sheet-compute" lambdas/character_sheet_lambda.py \
    --extra-files lambdas/character_engine.py lambdas/board_loader.py

# ── MCP server (tools_cgm, tools_board, tools_character all changed) ──
echo "--- MCP server ---"
deploy "life-platform-mcp" mcp_server.py

echo ""
echo "=== Deploy complete (10 Lambdas) ==="
echo ""
echo "Verification steps:"
echo "  1. Confirm new S3 writes go to raw/matthew/:"
echo "     aws s3 ls s3://matthew-life-platform/raw/matthew/ --recursive | tail -5"
echo "  2. Check MCP CGM tools still work — invoke get_glucose_summary in Claude"
echo "  3. Check board/character config loads — invoke get_board_of_directors in Claude"
echo "  4. Check CloudWatch for any errors:"
echo "     aws logs describe-log-streams --log-group-name /aws/lambda/health-auto-export-webhook \\"
echo "       --order-by LastEventTime --descending --limit 1"
