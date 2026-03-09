#!/usr/bin/env bash
# deploy/prepare_cdk_import.sh
# ─────────────────────────────────────────────────────────────────────────────
# Pre-flight script for cdk import on LifePlatformIngestion, LifePlatformCompute,
# and LifePlatformEmail stacks.
#
# What this does:
#   1. Looks up the garth Lambda Layer ARN and patches ingestion_stack.py
#   2. Verifies actual Lambda handler strings in AWS vs what CDK expects
#   3. Looks up actual EventBridge rule names (needed during `cdk import` prompts)
#   4. Verifies actual IAM role ARNs (catches pre-SEC-1 shared-role Lambdas)
#   5. Prints a cheat sheet of physical resource IDs for cdk import prompts
#
# Usage:
#   bash deploy/prepare_cdk_import.sh [--stack ingestion|compute|email|all]
#
# Run from project root:
#   cd ~/Documents/Claude/life-platform
#   bash deploy/prepare_cdk_import.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REGION="us-west-2"
STACK="${1:-all}"

# ── Colour helpers ──────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${CYAN}ℹ ${NC} $*"; }
ok()    { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC}  $*"; }
err()   { echo -e "${RED}✗${NC} $*"; }
header(){ echo -e "\n${BOLD}══ $* ══${NC}"; }

# ── 1. GARTH LAYER ARN ──────────────────────────────────────────────────────
header "Garth Layer ARN"

GARTH_ARN=$(aws lambda list-layers \
    --region "$REGION" \
    --query 'Layers[?contains(LayerName, `garth`)].LatestMatchingVersion.LayerVersionArn' \
    --output text --no-cli-pager 2>/dev/null | tr -d '[:space:]')

if [[ -z "$GARTH_ARN" || "$GARTH_ARN" == "None" ]]; then
    err "No garth layer found. Check layer name:"
    aws lambda list-layers --region "$REGION" \
        --query 'Layers[].LayerName' --output text --no-cli-pager
    warn "Update GARTH_LAYER_ARN in cdk/stacks/ingestion_stack.py manually."
else
    ok "Found: $GARTH_ARN"

    # Patch ingestion_stack.py if the placeholder is still there
    STACK_FILE="cdk/stacks/ingestion_stack.py"
    CURRENT=$(grep 'GARTH_LAYER_ARN' "$STACK_FILE" | grep -o '"arn:.*"' | tr -d '"' || true)

    if [[ "$CURRENT" == "$GARTH_ARN" ]]; then
        ok "GARTH_LAYER_ARN in $STACK_FILE is already correct."
    else
        info "Patching GARTH_LAYER_ARN in $STACK_FILE..."
        # Escape slashes and colons for sed
        ESCAPED=$(echo "$GARTH_ARN" | sed 's/[\/&]/\\&/g')
        sed -i.bak \
            "s|GARTH_LAYER_ARN = \"arn:aws:lambda:.*\"  # UPDATE BEFORE IMPORT|GARTH_LAYER_ARN = \"${GARTH_ARN}\"|" \
            "$STACK_FILE"
        ok "Patched. Old file saved as ${STACK_FILE}.bak"
    fi
fi

# ── 2. HANDLER VERIFICATION ─────────────────────────────────────────────────
header "Lambda Handler Verification"

# Expected handlers — must match what's actually deployed in AWS
declare -A EXPECTED_HANDLERS

# Ingestion
EXPECTED_HANDLERS["whoop-data-ingestion"]="whoop_lambda.lambda_handler"
EXPECTED_HANDLERS["garmin-data-ingestion"]="garmin_lambda.lambda_handler"
EXPECTED_HANDLERS["notion-journal-ingestion"]="notion_lambda.lambda_handler"
EXPECTED_HANDLERS["withings-data-ingestion"]="withings_lambda.lambda_handler"
EXPECTED_HANDLERS["habitify-data-ingestion"]="habitify_lambda.lambda_handler"
EXPECTED_HANDLERS["strava-data-ingestion"]="strava_lambda.lambda_handler"
EXPECTED_HANDLERS["journal-enrichment"]="journal_enrichment_lambda.lambda_handler"
EXPECTED_HANDLERS["todoist-data-ingestion"]="todoist_lambda.lambda_handler"
EXPECTED_HANDLERS["eightsleep-data-ingestion"]="eightsleep_lambda.lambda_handler"
EXPECTED_HANDLERS["activity-enrichment"]="enrichment_lambda.lambda_handler"
EXPECTED_HANDLERS["macrofactor-data-ingestion"]="macrofactor_lambda.lambda_handler"
EXPECTED_HANDLERS["weather-data-ingestion"]="weather_handler.lambda_handler"
EXPECTED_HANDLERS["dropbox-poll"]="dropbox_poll_lambda.lambda_handler"
EXPECTED_HANDLERS["apple-health-ingestion"]="apple_health_lambda.lambda_handler"
EXPECTED_HANDLERS["health-auto-export-webhook"]="health_auto_export_lambda.lambda_handler"

# Compute
EXPECTED_HANDLERS["anomaly-detector"]="anomaly_detector_lambda.lambda_handler"
EXPECTED_HANDLERS["character-sheet-compute"]="character_sheet_lambda.lambda_handler"
EXPECTED_HANDLERS["daily-metrics-compute"]="daily_metrics_compute_lambda.lambda_handler"
EXPECTED_HANDLERS["daily-insight-compute"]="daily_insight_compute_lambda.lambda_handler"
EXPECTED_HANDLERS["adaptive-mode-compute"]="adaptive_mode_lambda.lambda_handler"
EXPECTED_HANDLERS["hypothesis-engine"]="hypothesis_engine_lambda.lambda_handler"
EXPECTED_HANDLERS["dashboard-refresh"]="dashboard_refresh_lambda.lambda_handler"

# Email
EXPECTED_HANDLERS["daily-brief"]="daily_brief_lambda.lambda_handler"
EXPECTED_HANDLERS["weekly-digest"]="digest_handler.lambda_handler"
EXPECTED_HANDLERS["monthly-digest"]="monthly_digest_lambda.lambda_handler"
EXPECTED_HANDLERS["nutrition-review"]="nutrition_review_lambda.lambda_handler"
EXPECTED_HANDLERS["wednesday-chronicle"]="wednesday_chronicle_lambda.lambda_handler"
EXPECTED_HANDLERS["weekly-plate"]="weekly_plate_lambda.lambda_handler"
EXPECTED_HANDLERS["monday-compass"]="monday_compass_lambda.lambda_handler"
EXPECTED_HANDLERS["brittany-weekly-email"]="brittany_email_lambda.lambda_handler"

HANDLER_MISMATCHES=0
echo ""
printf "%-40s %-45s %-45s %s\n" "Lambda" "Expected Handler" "Actual Handler" "Status"
printf "%s\n" "$(printf '─%.0s' {1..150})"

for fn in "${!EXPECTED_HANDLERS[@]}"; do
    expected="${EXPECTED_HANDLERS[$fn]}"
    actual=$(aws lambda get-function-configuration \
        --function-name "$fn" \
        --region "$REGION" \
        --query "Handler" --output text --no-cli-pager 2>/dev/null || echo "NOT_FOUND")

    if [[ "$actual" == "NOT_FOUND" ]]; then
        printf "%-40s %-45s %-45s %s\n" "$fn" "$expected" "NOT_FOUND" "⚠  (not deployed)"
    elif [[ "$actual" == "$expected" ]]; then
        printf "%-40s %-45s %-45s %s\n" "$fn" "$expected" "$actual" "✓"
    else
        printf "%-40s %-45s %-45s %s\n" "$fn" "$expected" "$actual" "✗ MISMATCH"
        HANDLER_MISMATCHES=$((HANDLER_MISMATCHES + 1))
    fi
done | sort

echo ""
if [[ $HANDLER_MISMATCHES -gt 0 ]]; then
    err "$HANDLER_MISMATCHES handler mismatch(es) found."
    warn "Update the CDK stack handler strings to match actual AWS values BEFORE running cdk import."
    warn "After import, a cdk deploy with wrong handlers would change the Lambda handler string in AWS."
else
    ok "All handlers match."
fi

# ── 3. IAM ROLE VERIFICATION ─────────────────────────────────────────────────
header "IAM Role Verification (spot-check pre-SEC-1 Lambdas)"

echo ""
info "Checking roles that may still use shared pre-SEC-1 roles..."
printf "%-40s %s\n" "Lambda" "Actual Role"
printf "%s\n" "$(printf '─%.0s' {1..90})"

for fn in anomaly-detector character-sheet-compute dashboard-refresh \
          brittany-weekly-email; do
    role=$(aws lambda get-function-configuration \
        --function-name "$fn" \
        --region "$REGION" \
        --query "Role" --output text --no-cli-pager 2>/dev/null || echo "NOT_FOUND")
    role_name=$(echo "$role" | awk -F'/' '{print $NF}')
    printf "%-40s %s\n" "$fn" "$role_name"
done

warn "Update ROLE_ARNS in compute_stack.py / email_stack.py if the above differ from CDK definitions."

# ── 4. EVENTBRIDGE RULE NAMES (for cdk import prompts) ──────────────────────
header "EventBridge Rule Names (needed for cdk import prompts)"

echo ""
info "Rules that invoke ingestion Lambdas:"
aws events list-rules \
    --region "$REGION" \
    --query 'Rules[].{Name:Name,State:State,Schedule:ScheduleExpression}' \
    --output table --no-cli-pager 2>/dev/null | \
    grep -E "whoop|garmin|notion|withings|habitify|strava|journal|todoist|eightsleep|activity|macrofactor|weather|dropbox|apple|health|RULE_NAME|──" || \
    echo "(no rules found matching ingestion pattern)"

echo ""
info "Rules that invoke compute Lambdas:"
aws events list-rules \
    --region "$REGION" \
    --query 'Rules[].{Name:Name,State:State,Schedule:ScheduleExpression}' \
    --output table --no-cli-pager 2>/dev/null | \
    grep -E "anomaly|character|daily-metrics|daily-insight|adaptive|hypothesis|dashboard|RULE_NAME|──" || \
    echo "(no rules found matching compute pattern)"

echo ""
info "Rules that invoke email Lambdas:"
aws events list-rules \
    --region "$REGION" \
    --query 'Rules[].{Name:Name,State:State,Schedule:ScheduleExpression}' \
    --output table --no-cli-pager 2>/dev/null | \
    grep -E "daily-brief|weekly-digest|monthly-digest|nutrition|chronicle|weekly-plate|monday|brittany|RULE_NAME|──" || \
    echo "(no rules found matching email pattern)"

# ── 5. CDK SYNTH CHECK ────────────────────────────────────────────────────────
header "CDK Synth (quick validation)"

echo ""
info "Running cdk synth on all three stacks to catch any issues before import..."
echo "  (This does NOT change anything in AWS)"
echo ""

cd cdk
source .venv/bin/activate 2>/dev/null || { warn "venv not active — run: cd cdk && source .venv/bin/activate"; }

if command -v npx &>/dev/null; then
    npx cdk synth LifePlatformIngestion LifePlatformCompute LifePlatformEmail \
        --quiet 2>&1 | tail -5 \
        && ok "cdk synth passed for all 3 stacks." \
        || err "cdk synth FAILED. Fix errors before running cdk import."
else
    warn "npx not found. Run manually from cdk/: npx cdk synth LifePlatformIngestion LifePlatformCompute LifePlatformEmail"
fi

cd ..

# ── 6. IMPORT SEQUENCE REMINDER ─────────────────────────────────────────────
header "Import Sequence"

echo ""
echo -e "${BOLD}When ready to import, run these commands from cdk/ with venv active:${NC}"
echo ""
echo "  # 1. Ingestion stack (15 Lambdas)"
echo "  npx cdk import LifePlatformIngestion"
echo ""
echo "  # 2. Compute stack (7 Lambdas)"
echo "  npx cdk import LifePlatformCompute"
echo ""
echo "  # 3. Email stack (8 Lambdas)"
echo "  npx cdk import LifePlatformEmail"
echo ""
echo -e "${BOLD}During each import, CDK will prompt for physical resource IDs:${NC}"
echo "  - AWS::Lambda::Function   → enter the exact Lambda function name"
echo "  - AWS::Events::Rule       → enter the exact EventBridge rule name (see section 4 above)"
echo "  - AWS::CloudWatch::Alarm  → enter the alarm name (format: ingestion-error-<function-name>)"
echo "  - AWS::Lambda::Permission → skip (CDK generates statement IDs, import map handles this)"
echo ""
echo -e "${YELLOW}⚠  IMPORTANT: cdk import does NOT redeploy code. It only brings resources under CFn management.${NC}"
echo -e "${YELLOW}   After import, run drift detection before any cdk deploy:${NC}"
echo "  aws cloudformation detect-stack-drift --stack-name LifePlatformIngestion"
echo "  aws cloudformation detect-stack-drift --stack-name LifePlatformCompute"
echo "  aws cloudformation detect-stack-drift --stack-name LifePlatformEmail"
echo ""

ok "Pre-flight checks complete."
