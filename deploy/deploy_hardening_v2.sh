#!/bin/bash
# deploy_hardening_v2.sh — Simplified hardening deploy
# Files already extracted to lambdas/ — just deploy + DLQ
set -euo pipefail

REGION="us-west-2"
PROJECT_DIR="$HOME/Documents/Claude/life-platform"
DLQ_ARN="arn:aws:sqs:us-west-2:205930651321:life-platform-ingestion-dlq"
cd "$PROJECT_DIR"

deploy() {
    local FUNC="$1" SRC="$2" ZIP_NAME="$3"
    echo -n "  $FUNC ... "
    TMPDIR=$(mktemp -d)
    cp "lambdas/$SRC" "$TMPDIR/$ZIP_NAME"
    (cd "$TMPDIR" && zip -q deploy.zip "$ZIP_NAME")
    aws lambda update-function-code \
        --function-name "$FUNC" \
        --zip-file "fileb://$TMPDIR/deploy.zip" \
        --region "$REGION" \
        --query "CodeSize" --output text
    rm -rf "$TMPDIR"
    sleep 3
}

echo "═══ Deploying 19 parameterized Lambdas ═══"

# handler: lambda_function.lambda_handler
deploy "whoop-data-ingestion"            "whoop_lambda.py"               "lambda_function.py"
deploy "apple-health-ingestion"          "apple_health_lambda.py"        "lambda_function.py"
deploy "todoist-data-ingestion"          "todoist_lambda.py"             "lambda_function.py"
deploy "anomaly-detector"                "anomaly_detector_lambda.py"    "lambda_function.py"
deploy "monthly-digest"                  "monthly_digest_lambda.py"      "lambda_function.py"
deploy "insight-email-parser"            "insight_email_parser_lambda.py" "lambda_function.py"
deploy "life-platform-freshness-checker" "freshness_checker_lambda.py"   "lambda_function.py"

# handler: <filename>.lambda_handler
deploy "strava-data-ingestion"           "strava_lambda.py"              "strava_lambda.py"
deploy "garmin-data-ingestion"           "garmin_lambda.py"              "garmin_lambda.py"
deploy "eightsleep-data-ingestion"       "eightsleep_lambda.py"          "eightsleep_lambda.py"
deploy "macrofactor-data-ingestion"      "macrofactor_lambda.py"         "macrofactor_lambda.py"
deploy "withings-data-ingestion"         "withings_lambda.py"            "withings_lambda.py"
deploy "habitify-data-ingestion"         "habitify_lambda.py"            "habitify_lambda.py"
deploy "weather-data-ingestion"          "weather_lambda.py"             "weather_lambda.py"
deploy "dropbox-poll"                    "dropbox_poll_lambda.py"        "dropbox_poll_lambda.py"
deploy "activity-enrichment"             "enrichment_lambda.py"          "enrichment_lambda.py"
deploy "journal-enrichment"              "journal_enrichment_lambda.py"  "journal_enrichment_lambda.py"
deploy "health-auto-export-webhook"      "health_auto_export_lambda.py"  "health_auto_export_lambda.py"

# handler: digest_handler.lambda_handler
deploy "weekly-digest"                   "weekly_digest_v2_lambda.py"    "digest_handler.py"

echo ""
echo "═══ Adding DLQ to 5 scheduled Lambdas ═══"
for FUNC in monthly-digest anomaly-detector daily-brief life-platform-freshness-checker weekly-digest; do
    echo -n "  $FUNC ... "
    aws lambda update-function-configuration \
        --function-name "$FUNC" \
        --dead-letter-config "TargetArn=$DLQ_ARN" \
        --region "$REGION" \
        --query "FunctionName" --output text 2>/dev/null || echo "RETRY NEEDED"
    sleep 5
done

echo ""
echo "═══ Verifying ═══"
aws lambda list-functions --region "$REGION" \
    --query "Functions[].{Name:FunctionName,Modified:LastModified}" \
    --output table

echo ""
echo "✅ Done. Test with: aws lambda invoke --function-name anomaly-detector --region us-west-2 /tmp/test.json"
