#!/bin/bash
set -euo pipefail

# Pipeline health check — actively probes each ingestion Lambda
# Catches: dead secrets, expired tokens, missing modules, auth failures
# Run: before launch, weekly, or anytime you suspect an issue

REGION="us-west-2"
PASS=0
FAIL=0
WARN=0

echo "=== Pipeline Health Check ==="
echo "Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

check_lambda() {
  local fn="$1"
  local label="$2"
  printf "  %-35s " "$label"

  local result
  result=$(aws lambda invoke --function-name "$fn" --region "$REGION" "/tmp/hc_${fn}.json" 2>&1)
  local has_error=$(echo "$result" | grep -c "FunctionError" || true)

  if [ "$has_error" -gt 0 ]; then
    local err=$(python3 -c "import json; d=json.load(open('/tmp/hc_${fn}.json')); print(d.get('errorType','?') + ': ' + d.get('errorMessage','?')[:60])" 2>/dev/null || echo "unknown error")
    echo "FAIL — $err"
    FAIL=$((FAIL + 1))
  else
    local body=$(python3 -c "import json; d=json.load(open('/tmp/hc_${fn}.json')); b=d.get('body','') if isinstance(d,dict) else str(d); print(str(b)[:60])" 2>/dev/null || echo "ok")
    echo "OK   — $body"
    PASS=$((PASS + 1))
  fi
}

echo "API-Based Sources:"
check_lambda "whoop-data-ingestion"       "Whoop"
check_lambda "withings-data-ingestion"    "Withings"
check_lambda "eightsleep-data-ingestion"  "Eight Sleep"
check_lambda "garmin-data-ingestion"      "Garmin"
check_lambda "strava-data-ingestion"      "Strava"
check_lambda "habitify-data-ingestion"    "Habitify"
check_lambda "todoist-data-ingestion"     "Todoist"
check_lambda "notion-journal-ingestion"   "Notion"
check_lambda "weather-data-ingestion"     "Weather"

echo ""
echo "Periodic Upload Triggers:"
check_lambda "dropbox-poll"               "Dropbox Poll"
check_lambda "health-auto-export-webhook" "Health Auto Export"

echo ""
echo "Compute Layer:"
check_lambda "character-sheet-compute"    "Character Sheet"
check_lambda "daily-metrics-compute"      "Daily Metrics"
check_lambda "daily-insight-compute"      "Daily Insights"
check_lambda "adaptive-mode-compute"      "Adaptive Mode"

echo ""
echo "Email Digests:"
check_lambda "daily-brief"                "Daily Brief"
check_lambda "weekly-digest"              "Weekly Digest"
check_lambda "monday-compass"             "Monday Compass"
check_lambda "wednesday-chronicle"        "Wednesday Chronicle"
check_lambda "anomaly-detector"           "Anomaly Detector"

echo ""
echo "=== Results ==="
echo "  Pass: $PASS"
echo "  Fail: $FAIL"
echo "  Total: $((PASS + FAIL))"

if [ "$FAIL" -gt 0 ]; then
  echo ""
  echo "⚠️  $FAIL pipeline(s) failed health check. Review errors above."
  exit 1
else
  echo ""
  echo "✅ All pipelines healthy."
fi
