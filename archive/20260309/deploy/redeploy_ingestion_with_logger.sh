#!/bin/bash
# redeploy_ingestion_with_logger.sh
# Fixes AttributeError: 'Logger' object has no attribute 'set_date'
# All old-convention ingestion Lambdas have a stale bundled logger missing set_date().
# Fix: redeploy each with --extra-files lambdas/platform_logger.py

set -e
cd "$(dirname "$0")/.."

D="bash deploy/deploy_lambda.sh"
DELAY=10
LOG="--extra-files lambdas/platform_logger.py"

echo "=== Redeploying ingestion Lambdas with platform_logger fix ==="

$D whoop-data-ingestion          lambdas/whoop_lambda.py          $LOG; sleep $DELAY
$D eightsleep-data-ingestion     lambdas/eightsleep_lambda.py     $LOG; sleep $DELAY
$D withings-data-ingestion       lambdas/withings_lambda.py       $LOG; sleep $DELAY
$D strava-data-ingestion         lambdas/strava_lambda.py         $LOG; sleep $DELAY
$D todoist-data-ingestion        lambdas/todoist_lambda.py        $LOG; sleep $DELAY
$D macrofactor-data-ingestion    lambdas/macrofactor_lambda.py    $LOG; sleep $DELAY
$D garmin-data-ingestion         lambdas/garmin_lambda.py         $LOG; sleep $DELAY
$D habitify-data-ingestion       lambdas/habitify_lambda.py       $LOG; sleep $DELAY
$D notion-journal-ingestion      lambdas/notion_lambda.py         $LOG; sleep $DELAY
$D journal-enrichment            lambdas/journal_enrichment_lambda.py $LOG; sleep $DELAY
$D dropbox-poll                  lambdas/dropbox_poll_lambda.py   $LOG; sleep $DELAY
$D weather-data-ingestion        lambdas/weather_handler.py       $LOG; sleep $DELAY
$D activity-enrichment           lambdas/enrichment_lambda.py     $LOG

echo ""
echo "=== Ingestion logger fix complete ==="
