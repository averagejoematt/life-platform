#!/bin/bash
# deploy_gap_fill.sh — Deploy gap-aware backfill to 5 ingestion Lambdas
set -euo pipefail

LAMBDAS_DIR="$HOME/Documents/Claude/life-platform/lambdas"
REGION="us-west-2"

echo "═══════════════════════════════════════════════════════"
echo "  Deploying Gap-Aware Backfill to 5 Ingestion Lambdas"
echo "═══════════════════════════════════════════════════════"
echo ""

echo "[1/6] Verifying source files..."
for f in whoop_lambda.py eightsleep_lambda.py strava_lambda.py withings_lambda.py habitify_lambda.py; do
  if grep -q "LOOKBACK_DAYS" "$LAMBDAS_DIR/$f" 2>/dev/null; then
    echo "  ✅ $f"
  else
    echo "  ❌ $f missing gap-fill code — aborting"
    exit 1
  fi
done
echo ""

echo "[2/6] Deploying whoop-data-ingestion..."
cd /tmp && rm -rf whoop_deploy && mkdir whoop_deploy && cd whoop_deploy
cp "$LAMBDAS_DIR/whoop_lambda.py" lambda_function.py
zip -q whoop_lambda.zip lambda_function.py
aws lambda update-function-code \
  --function-name whoop-data-ingestion \
  --zip-file fileb://whoop_lambda.zip \
  --region $REGION --output text --query 'LastModified'
echo "  ✅ Whoop deployed"
sleep 10

echo "[3/6] Deploying eightsleep-data-ingestion..."
cd /tmp && rm -rf eightsleep_deploy && mkdir eightsleep_deploy && cd eightsleep_deploy
cp "$LAMBDAS_DIR/eightsleep_lambda.py" lambda_function.py
zip -q eightsleep_lambda.zip lambda_function.py
aws lambda update-function-code \
  --function-name eightsleep-data-ingestion \
  --zip-file fileb://eightsleep_lambda.zip \
  --region $REGION --output text --query 'LastModified'
echo "  ✅ Eight Sleep deployed"
sleep 10

echo "[4/6] Deploying strava-data-ingestion..."
cd /tmp && rm -rf strava_deploy && mkdir strava_deploy && cd strava_deploy
cp "$LAMBDAS_DIR/strava_lambda.py" lambda_function.py
zip -q strava_lambda.zip lambda_function.py
aws lambda update-function-code \
  --function-name strava-data-ingestion \
  --zip-file fileb://strava_lambda.zip \
  --region $REGION --output text --query 'LastModified'
echo "  ✅ Strava deployed"
sleep 10

echo "[5/6] Deploying withings-data-ingestion..."
cd /tmp && rm -rf withings_deploy && mkdir withings_deploy && cd withings_deploy
cp "$LAMBDAS_DIR/withings_lambda.py" lambda_function.py
zip -q withings_lambda.zip lambda_function.py
aws lambda update-function-code \
  --function-name withings-data-ingestion \
  --zip-file fileb://withings_lambda.zip \
  --region $REGION --output text --query 'LastModified'
echo "  ✅ Withings deployed"
sleep 10

echo "[6/6] Deploying habitify-data-ingestion..."
cd /tmp && rm -rf habitify_deploy && mkdir habitify_deploy && cd habitify_deploy
cp "$LAMBDAS_DIR/habitify_lambda.py" lambda_function.py
zip -q habitify_lambda.zip lambda_function.py
aws lambda update-function-code \
  --function-name habitify-data-ingestion \
  --zip-file fileb://habitify_lambda.zip \
  --region $REGION --output text --query 'LastModified'
echo "  ✅ Habitify deployed"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  All 5 Lambdas deployed with gap-aware backfill!"
echo ""
echo "  Test: aws lambda invoke --function-name whoop-data-ingestion \\"
echo "    --payload '{}' --region us-west-2 /tmp/test.json && cat /tmp/test.json"
echo "═══════════════════════════════════════════════════════"
