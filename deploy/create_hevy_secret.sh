#!/bin/bash
# create_hevy_secret.sh — Create the life-platform/hevy secret in AWS Secrets Manager.
#
# Per ADR-014: dedicated secret, NOT bundled into api-keys (mirrors life-platform/habitify).
# Run once. Re-run only when the API key or webhook secret rotates.
#
# Prerequisites:
#   1. Hevy Pro subscription active
#   2. API key generated at https://hevy.com/settings?developer
#   3. Webhook secret — pick a random string yourself (used to sign webhook POSTs).
#      Suggestion: `openssl rand -hex 32`
#
# Usage:
#   bash deploy/create_hevy_secret.sh
#
# Authored 2026-05-25 per SPEC_HEVY_AND_NUTRITION_BRIDGE_2026_05_25.

set -euo pipefail

REGION="us-west-2"
SECRET_NAME="life-platform/hevy"

echo "═══════════════════════════════════════════════════════════════"
echo "  Hevy secret creator — life-platform/hevy"
echo "═══════════════════════════════════════════════════════════════"
echo

# Suggest a webhook secret if the user doesn't have one
SUGGESTED_WEBHOOK_SECRET=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")

echo "Suggested webhook_secret (you'll need this again when registering the"
echo "webhook with Hevy after the FunctionURL exists):"
echo
echo "  $SUGGESTED_WEBHOOK_SECRET"
echo
echo "(Save it somewhere — 1Password etc. — you'll need it twice.)"
echo

read -s -p "Hevy API key (from https://hevy.com/settings?developer): " HEVY_API_KEY
echo
read -p "Webhook secret [press Enter to use the suggestion above]: " WEBHOOK_SECRET
echo

if [ -z "$WEBHOOK_SECRET" ]; then
  WEBHOOK_SECRET="$SUGGESTED_WEBHOOK_SECRET"
  echo "  Using suggested webhook_secret."
fi

if [ -z "$HEVY_API_KEY" ]; then
  echo "ERROR: Hevy API key is required. Aborting."
  exit 1
fi

# Build secret JSON without using `echo -n` (avoid trailing newline quirks).
SECRET_JSON=$(python3 -c "
import json, sys
print(json.dumps({
    'api_key': sys.argv[1],
    'webhook_secret': sys.argv[2],
}))
" "$HEVY_API_KEY" "$WEBHOOK_SECRET")

# Create OR update — the script is re-runnable
if aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "Secret $SECRET_NAME already exists — updating."
  aws secretsmanager put-secret-value \
    --secret-id "$SECRET_NAME" \
    --secret-string "$SECRET_JSON" \
    --region "$REGION" \
    --query 'VersionId' --output text >/dev/null
else
  echo "Creating secret $SECRET_NAME."
  aws secretsmanager create-secret \
    --name "$SECRET_NAME" \
    --description "Hevy workout API credentials. api_key + webhook_secret. Per SPEC_HEVY_AND_NUTRITION_BRIDGE_2026_05_25 + ADR-014." \
    --secret-string "$SECRET_JSON" \
    --region "$REGION" \
    --query 'Name' --output text >/dev/null
fi

echo
echo "✅ Secret $SECRET_NAME written in $REGION."
echo
echo "Next: run the CDK deploy to create the Lambdas that read this secret."
