#!/bin/bash
# setup_hevy_webhook_subscription.sh — register the deployed FunctionURL with
# Hevy's webhook subscription endpoint so workouts push automatically.
#
# Prereqs (in this order):
#   1. deploy/create_hevy_secret.sh       — secret exists in AWS
#   2. cd cdk && npx cdk deploy LifePlatformIngestion  — Lambdas + FunctionURL exist
#   3. Run this script — once
#
# This script:
#   - reads the FunctionURL from CloudFormation outputs
#   - reads api_key + webhook_secret from life-platform/hevy
#   - POSTs subscription request to Hevy's webhook-management endpoint
#
# IMPORTANT: Hevy's webhook subscription endpoint and payload shape are NOT
# locked in this script. Verify the current docs at
# https://api.hevyapp.com/docs (or developer settings) BEFORE running, and
# adjust SUBSCRIBE_PATH / SUBSCRIBE_BODY if the API differs.

set -euo pipefail

REGION="us-west-2"
SECRET_NAME="life-platform/hevy"
STACK="LifePlatformIngestion"
OUTPUT_KEY="HevyWebhookFunctionUrl"

# ── 1. FunctionURL from CloudFormation ─────────────────────────────────
FN_URL=$(aws cloudformation describe-stacks \
  --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='$OUTPUT_KEY'].OutputValue | [0]" \
  --output text 2>/dev/null)

if [ -z "$FN_URL" ] || [ "$FN_URL" = "None" ]; then
  echo "ERROR: $OUTPUT_KEY not found in stack $STACK."
  echo "Run 'cd cdk && npx cdk deploy LifePlatformIngestion' first."
  exit 1
fi
echo "FunctionURL: $FN_URL"

# ── 2. Credentials from Secrets Manager ────────────────────────────────
SECRET=$(aws secretsmanager get-secret-value \
  --secret-id "$SECRET_NAME" --region "$REGION" \
  --query 'SecretString' --output text 2>/dev/null)

if [ -z "$SECRET" ]; then
  echo "ERROR: Secret $SECRET_NAME not found. Run deploy/create_hevy_secret.sh first."
  exit 1
fi
API_KEY=$(echo "$SECRET" | python3 -c "import json,sys; print(json.load(sys.stdin)['api_key'])")
WEBHOOK_SECRET=$(echo "$SECRET" | python3 -c "import json,sys; print(json.load(sys.stdin)['webhook_secret'])")

# ── 3. Subscribe ────────────────────────────────────────────────────────
SUBSCRIBE_PATH="/v1/webhook-subscription"   # VERIFY against Hevy current docs
SUBSCRIBE_BODY=$(python3 -c "
import json
print(json.dumps({
    'url':         '${FN_URL}',
    'auth_token':  '${WEBHOOK_SECRET}',   # Hevy will include this in webhook headers
}))
")

echo
echo "Subscribing FunctionURL to Hevy webhook feed..."
echo "  endpoint: https://api.hevyapp.com${SUBSCRIBE_PATH}"
echo

HTTP_CODE=$(curl -s -o /tmp/hevy_subscribe_response.json -w "%{http_code}" \
  -X POST "https://api.hevyapp.com${SUBSCRIBE_PATH}" \
  -H "api-key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d "${SUBSCRIBE_BODY}")

echo "HTTP $HTTP_CODE response:"
cat /tmp/hevy_subscribe_response.json
echo

if [ "$HTTP_CODE" -ge 200 ] && [ "$HTTP_CODE" -lt 300 ]; then
  echo "✅ Webhook subscription registered."
  echo
  echo "Test: complete a workout in Hevy. Within ~1 min, check:"
  echo "  aws logs tail /aws/lambda/hevy-webhook --region $REGION --since 5m"
elif [ "$HTTP_CODE" -eq 404 ]; then
  echo "❌ HTTP 404. The path $SUBSCRIBE_PATH may be wrong."
  echo "   Look up Hevy's actual webhook-management endpoint at:"
  echo "   https://hevy.com/settings?developer  (or /docs)"
  echo "   and update SUBSCRIBE_PATH in this script."
  exit 1
else
  echo "❌ Subscription failed."
  exit 1
fi
