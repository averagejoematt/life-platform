#!/usr/bin/env bash
# deploy/prepare_cdk_import.sh
# ─────────────────────────────────────────────────────────────────────────────
# Pre-flight script for cdk import on LifePlatformIngestion.
#
# What this does:
#   1. Checks for garth Lambda Layer (may be bundled in zip instead)
#   2. Verifies actual Lambda handler strings in AWS vs what CDK expects
#   3. Looks up actual EventBridge rule names (needed during `cdk import` prompts)
#   4. Verifies actual IAM role ARNs
#   5. Runs cdk synth as final validation
#   6. Prints import cheat sheet
#
# Usage:
#   bash deploy/prepare_cdk_import.sh
#
# Run from project root:
#   cd ~/Documents/Claude/life-platform
#   bash deploy/prepare_cdk_import.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REGION="us-west-2"

# ── Colour helpers ──────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${CYAN}ℹ ${NC} $*"; }
ok()    { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC}  $*"; }
err()   { echo -e "${RED}✗${NC} $*"; }
header(){ echo -e "\n${BOLD}══ $* ══${NC}"; }

# ── 1. GARTH LAYER CHECK ──────────────────────────────────────────────────
header "Garth Layer Check"

GARTH_ARN=$(aws lambda list-layers \
    --region "$REGION" \
    --query 'Layers[?contains(LayerName, `garth`)].LatestMatchingVersion.LayerVersionArn' \
    --output text --no-cli-pager 2>/dev/null | tr -d '[:space:]')

if [[ -z "$GARTH_ARN" || "$GARTH_ARN" == "None" ]]; then
    info "No dedicated garth layer found in AWS."
    info "Checking if garth is bundled directly in garmin-data-ingestion Lambda..."

    GARMIN_LAYERS=$(aws lambda get-function-configuration \
        --function-name garmin-data-ingestion \
        --region "$REGION" \
        --query 'Layers[].Arn' \
        --output text --no-cli-pager 2>/dev/null || echo "none")

    echo "  Layers attached to garmin-data-ingestion: ${GARMIN_LAYERS:-none}"

    warn "garth is not a separate Layer — it is bundled in the garmin Lambda zip."
    warn "Removing GARTH_LAYER_ARN reference from ingestion_stack.py..."

    # Remove the garth layer wiring from CDK stack
    STACK_FILE="cdk/stacks/ingestion_stack.py"
    if grep -q "GarthLayer\|garth_layer\|GARTH_LAYER_ARN" "$STACK_FILE"; then
        warn "garth layer references found in $STACK_FILE — these need manual removal."
        warn "Claude will handle this in the next step."
    else
        ok "No garth layer references in $STACK_FILE — already clean."
    fi
else
    ok "Found garth layer: $GARTH_ARN"
    STACK_FILE="cdk/stacks/ingestion_stack.py"
    CURRENT=$(grep 'GARTH_LAYER_ARN' "$STACK_FILE" 2>/dev/null | grep -o '"arn:.*"' | tr -d '"' || echo "")
    if [[ "$CURRENT" == "$GARTH_ARN" ]]; then
        ok "GARTH_LAYER_ARN already correct in $STACK_FILE."
    else
        info "Patching GARTH_LAYER_ARN..."
        ESCAPED=$(echo "$GARTH_ARN" | sed 's/[\/&]/\\&/g')
        sed -i.bak "s|GARTH_LAYER_ARN = \"arn:.*\".*|GARTH_LAYER_ARN = \"${GARTH_ARN}\"|" "$STACK_FILE"
        ok "Patched."
    fi
fi

# ── 2. HANDLER VERIFICATION ─────────────────────────────────────────────────
header "Lambda Handler Verification (ingestion stack)"

echo ""
printf "%-40s %-50s %-50s %s\n" "Lambda" "Expected Handler" "Actual Handler" "Status"
printf "%s\n" "$(python3 -c "print('-'*160)")"

HANDLER_MISMATCHES=0

check_handler() {
    local fn="$1"
    local expected="$2"
    local actual
    actual=$(aws lambda get-function-configuration \
        --function-name "$fn" \
        --region "$REGION" \
        --query "Handler" --output text --no-cli-pager 2>/dev/null || echo "NOT_FOUND")

    if [[ "$actual" == "NOT_FOUND" ]]; then
        printf "%-40s %-50s %-50s %s\n" "$fn" "$expected" "NOT_FOUND" "⚠  not deployed"
    elif [[ "$actual" == "$expected" ]]; then
        printf "%-40s %-50s %-50s %s\n" "$fn" "$expected" "$actual" "✓"
    else
        printf "%-40s %-50s %-50s %s\n" "$fn" "$expected" "$actual" "✗ MISMATCH"
        HANDLER_MISMATCHES=$((HANDLER_MISMATCHES + 1))
    fi
}

check_handler "whoop-data-ingestion"       "lambda_function.lambda_handler"
check_handler "garmin-data-ingestion"      "garmin_lambda.lambda_handler"
check_handler "notion-journal-ingestion"   "notion_lambda.lambda_handler"
check_handler "withings-data-ingestion"    "lambda_function.lambda_handler"
check_handler "habitify-data-ingestion"    "lambda_function.lambda_handler"
check_handler "strava-data-ingestion"      "lambda_function.lambda_handler"
check_handler "journal-enrichment"         "journal_enrichment_lambda.lambda_handler"
check_handler "todoist-data-ingestion"     "lambda_function.lambda_handler"
check_handler "eightsleep-data-ingestion"  "lambda_function.lambda_handler"
check_handler "activity-enrichment"        "enrichment_lambda.lambda_handler"
check_handler "macrofactor-data-ingestion" "macrofactor_lambda.lambda_handler"
check_handler "weather-data-ingestion"     "weather_handler.lambda_handler"
check_handler "dropbox-poll"               "dropbox_poll_lambda.lambda_handler"
check_handler "apple-health-ingestion"     "lambda_function.lambda_handler"
check_handler "health-auto-export-webhook" "health_auto_export_lambda.lambda_handler"

echo ""
if [[ $HANDLER_MISMATCHES -gt 0 ]]; then
    err "$HANDLER_MISMATCHES handler mismatch(es). Update ingestion_stack.py BEFORE running cdk import."
else
    ok "All handlers match."
fi

# ── 3. IAM ROLE VERIFICATION ─────────────────────────────────────────────────
header "IAM Role Verification (ingestion stack)"

echo ""
printf "%-40s %-50s %s\n" "Lambda" "Actual Role" "Status"
printf "%s\n" "$(python3 -c "print('-'*100)")"

check_role() {
    local fn="$1"
    local expected_suffix="$2"
    local actual
    actual=$(aws lambda get-function-configuration \
        --function-name "$fn" \
        --region "$REGION" \
        --query "Role" --output text --no-cli-pager 2>/dev/null | awk -F'/' '{print $NF}')

    if [[ "$actual" == "$expected_suffix" ]]; then
        printf "%-40s %-50s %s\n" "$fn" "$actual" "✓"
    else
        printf "%-40s %-50s %s\n" "$fn" "$actual" "⚠  expected: $expected_suffix"
    fi
}

check_role "whoop-data-ingestion"       "lambda-whoop-role"
check_role "garmin-data-ingestion"      "lambda-garmin-ingestion-role"
check_role "notion-journal-ingestion"   "lambda-notion-ingestion-role"
check_role "withings-data-ingestion"    "lambda-withings-role"
check_role "habitify-data-ingestion"    "lambda-habitify-ingestion-role"
check_role "strava-data-ingestion"      "lambda-strava-role"
check_role "journal-enrichment"         "lambda-journal-enrichment-role"
check_role "todoist-data-ingestion"     "lambda-todoist-role"
check_role "eightsleep-data-ingestion"  "lambda-eightsleep-role"
check_role "activity-enrichment"        "lambda-enrichment-role"
check_role "macrofactor-data-ingestion" "lambda-macrofactor-role"
check_role "weather-data-ingestion"     "lambda-weather-role"
check_role "dropbox-poll"               "lambda-dropbox-poll-role"
check_role "apple-health-ingestion"     "lambda-apple-health-role"
check_role "health-auto-export-webhook" "lambda-health-auto-export-role"

# ── 4. EVENTBRIDGE RULE NAMES ────────────────────────────────────────────────
header "EventBridge Rule Names (for cdk import prompts)"

echo ""
info "All rules (filter for ingestion-related ones):"
aws events list-rules \
    --region "$REGION" \
    --query 'Rules[].{Name:Name,Schedule:ScheduleExpression}' \
    --output table --no-cli-pager 2>/dev/null | \
    grep -E "whoop|garmin|notion|withings|habitify|strava|journal|todoist|eightsleep|activity|macrofactor|weather|dropbox|apple|health|Name|─" || \
    echo "  (none found)"

# ── 5. CDK SYNTH ─────────────────────────────────────────────────────────────
header "CDK Synth"

echo ""
cd cdk
source .venv/bin/activate 2>/dev/null || true

if command -v npx &>/dev/null; then
    echo "Running: npx cdk synth LifePlatformIngestion --quiet"
    if npx cdk synth LifePlatformIngestion --quiet 2>&1 | tail -3; then
        ok "cdk synth passed."
    else
        err "cdk synth FAILED. Fix before running cdk import."
    fi
else
    warn "npx not found. Run manually: cd cdk && npx cdk synth LifePlatformIngestion"
fi

cd ..

# ── 6. IMPORT CHEAT SHEET ────────────────────────────────────────────────────
header "Import Cheat Sheet"

echo ""
echo -e "${BOLD}Run from cdk/ with venv active:${NC}"
echo "  npx cdk import LifePlatformIngestion"
echo ""
echo -e "${BOLD}CDK will prompt for physical resource IDs:${NC}"
echo "  AWS::Lambda::Function   → exact Lambda function name (e.g. whoop-data-ingestion)"
echo "  AWS::Events::Rule       → exact EventBridge rule name (see section 4 above)"
echo "  AWS::CloudWatch::Alarm  → ingestion-error-<function-name>"
echo ""
echo -e "${YELLOW}⚠  cdk import does NOT redeploy code. After import, run drift detection:${NC}"
echo "  aws cloudformation detect-stack-drift --stack-name LifePlatformIngestion"
echo ""
ok "Pre-flight complete."
