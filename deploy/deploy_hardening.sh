#!/bin/bash
# deploy_hardening.sh — Apply Lambda parameterization + DLQ fixes
# Covers: Item #1 (parameterize), #4 (DLQ gaps), #5 (logging consistency)
set -e

REGION="us-west-2"
PROJECT_DIR="$HOME/Documents/Claude/life-platform"
LAMBDAS_DIR="$PROJECT_DIR/lambdas"
DLQ_ARN="arn:aws:sqs:us-west-2:205930651321:life-platform-ingestion-dlq"

cd "$PROJECT_DIR"

# ═══════════════════════════════════════════════════════════════
# Phase 1: Extract parameterized Lambda files
# ═══════════════════════════════════════════════════════════════
echo "═══ Phase 1: Extract parameterized Lambda files ═══"

if [ ! -f "lambda_parameterization.tar.gz" ]; then
    echo "❌ lambda_parameterization.tar.gz not found in $PROJECT_DIR"
    echo "   Download it from Claude and place it here first."
    exit 1
fi

# Backup originals
BACKUP_DIR="$LAMBDAS_DIR/backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
echo "Backing up originals to $BACKUP_DIR..."

for f in anomaly_detector_lambda.py apple_health_lambda.py dropbox_poll_lambda.py \
         eightsleep_lambda.py enrichment_lambda.py garmin_lambda.py habitify_lambda.py \
         health_auto_export_lambda.py insight_email_parser_lambda.py \
         journal_enrichment_lambda.py macrofactor_lambda.py monthly_digest_lambda.py \
         strava_lambda.py todoist_lambda.py weather_lambda.py \
         weekly_digest_v2_lambda.py whoop_lambda.py freshness_checker.py; do
    [ -f "$LAMBDAS_DIR/$f" ] && cp "$LAMBDAS_DIR/$f" "$BACKUP_DIR/$f"
done
echo "  ✅ Backed up to $BACKUP_DIR"

# Extract new files
echo "Extracting parameterized files..."
tar xzf lambda_parameterization.tar.gz -C "$LAMBDAS_DIR/"
echo "  ✅ Files extracted to $LAMBDAS_DIR/"

# Syntax check all extracted files
echo "Syntax checking..."
ERRORS=0
for f in "$LAMBDAS_DIR"/*.py; do
    fname=$(basename "$f")
    python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" 2>/dev/null
    if [ $? -ne 0 ]; then
        echo "  ❌ $fname failed syntax check"
        ERRORS=$((ERRORS + 1))
    fi
done
if [ $ERRORS -gt 0 ]; then
    echo "❌ $ERRORS files failed syntax check. Aborting."
    exit 1
fi
echo "  ✅ All files pass syntax check"

# ═══════════════════════════════════════════════════════════════
# Phase 2: Deploy all modified Lambdas
# CRITICAL: Each Lambda has a specific handler module name.
# The source file MUST be zipped with the correct entry-point
# filename matching the Lambda's Handler configuration.
# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══ Phase 2: Deploy modified Lambdas ═══"

deploy_lambda() {
    local FUNC_NAME="$1"
    local SOURCE_FILE="$2"
    local ZIP_ENTRY="$3"   # Must match the module in Lambda Handler config
    
    echo "  Deploying $FUNC_NAME ($SOURCE_FILE → $ZIP_ENTRY)..."
    
    TMPDIR=$(mktemp -d)
    cp "$LAMBDAS_DIR/$SOURCE_FILE" "$TMPDIR/$ZIP_ENTRY"
    
    (cd "$TMPDIR" && zip -q "$TMPDIR/deploy.zip" "$ZIP_ENTRY")
    
    aws lambda update-function-code \
        --function-name "$FUNC_NAME" \
        --zip-file "fileb://$TMPDIR/deploy.zip" \
        --region "$REGION" \
        --query "FunctionName" --output text > /dev/null
    
    rm -rf "$TMPDIR"
    echo "    ✅ $FUNC_NAME deployed"
}

# ── Handler: lambda_function.lambda_handler ──
deploy_lambda "whoop-data-ingestion"               "whoop_lambda.py"               "lambda_function.py"
sleep 3
deploy_lambda "apple-health-ingestion"             "apple_health_lambda.py"         "lambda_function.py"
sleep 3
deploy_lambda "todoist-data-ingestion"             "todoist_lambda.py"              "lambda_function.py"
sleep 3
deploy_lambda "anomaly-detector"                   "anomaly_detector_lambda.py"     "lambda_function.py"
sleep 3
deploy_lambda "monthly-digest"                     "monthly_digest_lambda.py"       "lambda_function.py"
sleep 3
deploy_lambda "insight-email-parser"               "insight_email_parser_lambda.py" "lambda_function.py"
sleep 3
deploy_lambda "life-platform-freshness-checker"    "freshness_checker_lambda.py"    "lambda_function.py"
sleep 3

# ── Handler: <source_filename>.lambda_handler ──
deploy_lambda "strava-data-ingestion"              "strava_lambda.py"               "strava_lambda.py"
sleep 3
deploy_lambda "garmin-data-ingestion"              "garmin_lambda.py"               "garmin_lambda.py"
sleep 3
deploy_lambda "eightsleep-data-ingestion"          "eightsleep_lambda.py"           "eightsleep_lambda.py"
sleep 3
deploy_lambda "macrofactor-data-ingestion"         "macrofactor_lambda.py"          "macrofactor_lambda.py"
sleep 3
deploy_lambda "withings-data-ingestion"            "withings_lambda.py"             "withings_lambda.py"
sleep 3
deploy_lambda "habitify-data-ingestion"            "habitify_lambda.py"             "habitify_lambda.py"
sleep 3
deploy_lambda "weather-data-ingestion"             "weather_lambda.py"              "weather_lambda.py"
sleep 3
deploy_lambda "dropbox-poll"                       "dropbox_poll_lambda.py"         "dropbox_poll_lambda.py"
sleep 3
deploy_lambda "activity-enrichment"                "enrichment_lambda.py"           "enrichment_lambda.py"
sleep 3
deploy_lambda "journal-enrichment"                 "journal_enrichment_lambda.py"   "journal_enrichment_lambda.py"
sleep 3
deploy_lambda "health-auto-export-webhook"         "health_auto_export_lambda.py"   "health_auto_export_lambda.py"
sleep 3

# ── Handler: digest_handler.lambda_handler (special case) ──
deploy_lambda "weekly-digest"                      "weekly_digest_v2_lambda.py"     "digest_handler.py"
sleep 3

echo "  ✅ All 19 Lambdas deployed"

# ═══════════════════════════════════════════════════════════════
# Phase 3: Add DLQ to Lambdas missing it
# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══ Phase 3: Add Dead Letter Queues ═══"

for FUNC in "monthly-digest" "anomaly-detector" "daily-brief" \
            "life-platform-freshness-checker" "weekly-digest"; do
    echo "  Adding DLQ to $FUNC..."
    aws lambda update-function-configuration \
        --function-name "$FUNC" \
        --dead-letter-config "TargetArn=$DLQ_ARN" \
        --region "$REGION" \
        --query "FunctionName" --output text > /dev/null 2>&1
    
    if [ $? -eq 0 ]; then
        echo "    ✅ $FUNC → DLQ configured"
    else
        echo "    ⚠️  $FUNC — DLQ config failed (may need retry after deploy settles)"
    fi
    sleep 5
done

echo "  ✅ DLQ configuration complete"

# ═══════════════════════════════════════════════════════════════
# Phase 4: Verify
# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══ Phase 4: Verification ═══"

echo "Checking DLQ configuration..."
aws lambda list-functions \
    --query "Functions[].{Name:FunctionName,DLQ:DeadLetterConfig.TargetArn}" \
    --output table --region "$REGION"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  ✅ HARDENING COMPLETE"
echo ""
echo "  Changes applied:"
echo "    • 19 Lambda files parameterized (os.environ with defaults)"
echo "    • All USER#matthew PKs use USER_ID variable"
echo "    • Logging added to all Lambdas"
echo "    • DLQ added to 5 scheduled Lambdas"
echo "    • Freshness checker extracted to proper Lambda source"
echo ""
echo "  Rollback: cp $BACKUP_DIR/*.py $LAMBDAS_DIR/"
echo "═══════════════════════════════════════════════════════════"
