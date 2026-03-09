#!/usr/bin/env bash
# deploy_ingestion_stack.sh — First deploy of LifePlatformIngestion CDK stack
#
# What this does:
#   - Locks in all handler/schedule fixes from the cdk import session
#   - Creates 7 missing CloudWatch alarms (garmin, notion, habitify,
#     journal-enrichment, weather, dropbox-poll, hae-webhook)
#   - Adds Lambda::Permission resources (S3/API Gateway invoke permissions)
#
# Handler note: The 7 old-convention Lambdas (whoop, withings, habitify,
#   strava, todoist, eightsleep, apple-health) already have
#   lambda_function.lambda_handler set in ingestion_stack.py to match AWS.
#   No handler changes will occur on this deploy.
#
# Usage: bash deploy/deploy_ingestion_stack.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CDK_DIR="$SCRIPT_DIR/../cdk"

echo "=== LifePlatformIngestion — First Deploy ==="
echo "Stack: LifePlatformIngestion"
echo "Creating: 7 missing alarms + Lambda permissions"
echo ""

cd "$CDK_DIR"
source .venv/bin/activate

echo "--- cdk diff (review before applying) ---"
npx cdk diff LifePlatformIngestion 2>&1 | head -100
echo ""
read -p "Proceed with deploy? (y/N) " confirm
[[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

echo "--- Deploying ---"
npx cdk deploy LifePlatformIngestion --require-approval never

echo ""
echo "=== Deploy complete ==="
echo "Verifying alarms:"
aws cloudwatch describe-alarms \
  --alarm-name-prefix "ingestion-error-" \
  --query 'MetricAlarms[].{Name:AlarmName,State:StateValue}' \
  --output table \
  --region us-west-2
