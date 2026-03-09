#!/usr/bin/env bash
# v2.98.0: DATA-1 follow-on — schema_version=1 on all remaining ingestion Lambdas
#          + attach shared-utils layer to dashboard-refresh
#
# Does NOT use deploy_unified.sh (requires bash 4+ associative arrays, fails on macOS bash 3.2).
# All deploys are direct aws lambda update-function-code calls.
#
# Run from project root: bash deploy/deploy_v2.98.0.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REGION="us-west-2"
LAYER_ARN="arn:aws:lambda:us-west-2:205930651321:layer:life-platform-shared-utils:1"

# ── Helper: package + deploy a single-file Lambda ─────────────────────────────
deploy_single() {
  local FN="$1"          # AWS function name
  local SRC="$2"         # source file in lambdas/
  local HANDLER="$3"     # handler filename inside zip (what Lambda expects)
  echo -n "  $FN ... "
  local TMP
  TMP=$(mktemp -d /tmp/deploy_XXXXXX)
  cp "$ROOT/lambdas/$SRC" "$TMP/$HANDLER"
  zip -j -q "$TMP/${FN}.zip" "$TMP/$HANDLER"
  aws lambda update-function-code \
    --function-name "$FN" \
    --zip-file "fileb://$TMP/${FN}.zip" \
    --region "$REGION" \
    --output text --query 'FunctionName' > /dev/null
  rm -rf "$TMP"
  echo "✅"
  sleep 10
}

echo "=== v2.98.0: DATA-1 follow-on + layer attach ==="
echo ""

# ── Step 1: Attach layer to dashboard-refresh ─────────────────────────────────
# Note: the Lambda is "dashboard-refresh"; the EventBridge rules are the ones
# named afternoon/evening. There is only one Lambda function.
echo "── Attaching shared-utils layer to dashboard-refresh ──"
EXISTING=$(aws lambda get-function-configuration \
  --function-name "dashboard-refresh" --region "$REGION" \
  --query "Layers[*].Arn" --output json --no-cli-pager 2>/dev/null || echo "[]")
NEW_LAYERS=$(python3 -c "
import json
try:
    existing = json.loads('''$EXISTING''')
except Exception:
    existing = []
if not isinstance(existing, list):
    existing = []
layer_base = ':'.join('$LAYER_ARN'.split(':')[:-1])
filtered = [a for a in existing if not a.startswith(layer_base)]
filtered.append('$LAYER_ARN')
print(' '.join(filtered))
")
aws lambda update-function-configuration \
  --function-name "dashboard-refresh" --region "$REGION" \
  --layers $NEW_LAYERS --no-cli-pager > /dev/null && echo "  ✅ dashboard-refresh" || echo "  ❌ dashboard-refresh"
sleep 5
echo ""

# ── Step 2: Deploy ingestion Lambdas ──────────────────────────────────────────
# Handler filename: the zip entry AWS will invoke.
# Most ingest Lambdas use lambda_function.py (renamed at zip time) or the actual filename
# depending on their FunctionConfiguration.Handler. We deploy with the original filename
# and match what's already registered in Lambda config.
# All these are single-file deploys — no shared extras needed (ingestion doesn't use board_loader etc.)

echo "── Deploying ingestion Lambdas (schema_version=1 added) ──"

# For each Lambda, determine the correct handler filename by checking the existing config
for pair in \
  "eightsleep-data-ingestion:eightsleep_lambda.py" \
  "strava-data-ingestion:strava_lambda.py" \
  "habitify-data-ingestion:habitify_lambda.py" \
  "withings-data-ingestion:withings_lambda.py" \
  "macrofactor-data-ingestion:macrofactor_lambda.py" \
  "notion-journal-ingestion:notion_lambda.py" \
  "todoist-data-ingestion:todoist_lambda.py" \
  "weather-data-ingestion:weather_lambda.py" \
  "apple-health-ingestion:apple_health_lambda.py"
do
  FN="${pair%%:*}"
  SRC="${pair##*:}"
  echo -n "  $FN ... "

  # Read the existing handler config to know what filename to use in the zip
  HANDLER_CFG=$(aws lambda get-function-configuration \
    --function-name "$FN" --region "$REGION" \
    --query "Handler" --output text --no-cli-pager 2>/dev/null || echo "lambda_function.lambda_handler")
  # Handler format is "filename.function_name" — extract the module part
  HANDLER_MODULE="${HANDLER_CFG%%.*}"
  HANDLER_FILE="${HANDLER_MODULE}.py"

  TMP=$(mktemp -d /tmp/deploy_XXXXXX)
  cp "$ROOT/lambdas/$SRC" "$TMP/$HANDLER_FILE"
  zip -j -q "$TMP/${FN}.zip" "$TMP/$HANDLER_FILE"
  aws lambda update-function-code \
    --function-name "$FN" \
    --zip-file "fileb://$TMP/${FN}.zip" \
    --region "$REGION" \
    --output text --query 'FunctionName' > /dev/null
  rm -rf "$TMP"
  echo "✅ (handler: $HANDLER_FILE)"
  sleep 10
done

echo ""
echo "  (garmin skipped — requires garminconnect/garth bundle; run: bash deploy/deploy_unified.sh garmin)"
echo "  (health_auto_export skipped — uses update_item not put_item; no change needed)"
echo ""
echo "=== v2.98.0 deploy complete ==="
echo ""

# ── Cleanup commands ──────────────────────────────────────────────────────────
echo "── Cleanup: paste these into your terminal ──"
echo ""
echo "# Delete deprecated lambda-weekly-digest-role:"
cat << 'CLEANUP'
ROLE="lambda-weekly-digest-role"
for policy in $(aws iam list-role-policies --role-name "$ROLE" --query 'PolicyNames[]' --output text 2>/dev/null); do
  aws iam delete-role-policy --role-name "$ROLE" --policy-name "$policy" && echo "  Deleted policy: $policy"
done
for arn in $(aws iam list-attached-role-policies --role-name "$ROLE" --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null); do
  aws iam detach-role-policy --role-name "$ROLE" --policy-arn "$arn" && echo "  Detached: $arn"
done
aws iam delete-role --role-name "$ROLE" && echo "  ✅ Deleted role: $ROLE"
CLEANUP

echo ""
echo "# Delete frozen api-keys bundle (7-day recovery window):"
echo "aws secretsmanager delete-secret --secret-id life-platform/api-keys --region us-west-2 --recovery-window-in-days 7"
