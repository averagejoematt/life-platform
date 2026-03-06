#!/bin/bash
# deploy_workout_ingestion.sh — Deploy HAE webhook v1.6.0 with workout processing
# Deploys updated Lambda, then replays existing workout payloads to backfill data.
set -euo pipefail
cd ~/Documents/Claude/life-platform

echo "=== Deploy Health Auto Export Webhook v1.6.0 (Workout Ingestion) ==="
echo ""

# ── 1. Package and deploy Lambda ──
echo "--- Step 1: Packaging Lambda ---"
ZIP_FILE="lambdas/health_auto_export_lambda.zip"
rm -f "$ZIP_FILE"
cd lambdas
zip "../$ZIP_FILE" health_auto_export_lambda.py
cd ..
echo "Zip: $(du -h "$ZIP_FILE" | cut -f1)"

echo "--- Step 2: Deploying to Lambda ---"
aws lambda update-function-code \
  --function-name health-auto-export-webhook \
  --zip-file "fileb://$ZIP_FILE" \
  --region us-west-2 --no-cli-pager

echo ""
echo "Waiting 10s for deployment..."
sleep 10

# ── 2. Smoke test ──
echo "--- Step 3: Smoke test ---"
aws lambda invoke \
  --function-name health-auto-export-webhook \
  --payload '{"headers":{},"body":"{}"}' \
  --cli-binary-format raw-in-base64-out \
  --region us-west-2 \
  /tmp/hae_smoke.json --no-cli-pager

if grep -q 'Traceback\|NameError\|ImportError\|SyntaxError\|errorType\|errorMessage' /tmp/hae_smoke.json; then
  echo "❌ SMOKE TEST FAILED — Lambda has code errors:"
  cat /tmp/hae_smoke.json
  exit 1
elif grep -q '"statusCode": 401' /tmp/hae_smoke.json; then
  echo "✅ Lambda deployed — 401 auth rejection confirms it's running"
else
  echo "✅ Lambda deployed and responding"
  cat /tmp/hae_smoke.json
fi

echo ""
echo "=== Deploy Complete ==="
echo "  Lambda: health-auto-export-webhook v1.6.0"
echo "  New fields: flexibility_minutes, flexibility_sessions,"
echo "    breathwork_minutes, breathwork_sessions, recovery_workout_minutes, etc."
echo "  S3 storage: raw/workouts/YYYY/MM/DD.json"
echo ""
echo "Next: Run the backfill to replay previously-dropped workouts:"
echo "  python3 backfill/backfill_workouts.py --dry-run"
echo "  python3 backfill/backfill_workouts.py"
