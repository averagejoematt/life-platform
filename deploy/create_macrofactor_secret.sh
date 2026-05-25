#!/bin/bash
# create_macrofactor_secret.sh — Create the life-platform/macrofactor secret.
#
# Per ADR-014: dedicated secret, NOT bundled into api-keys.
# Per ADR-061: stores the actual MacroFactor account password (Firebase
# email/password auth) — accepted risk of the unofficial-API path.
#
# Usage:
#   bash deploy/create_macrofactor_secret.sh

set -euo pipefail

REGION="us-west-2"
SECRET_NAME="life-platform/macrofactor"

echo "═══════════════════════════════════════════════════════════════"
echo "  MacroFactor secret creator — life-platform/macrofactor"
echo "═══════════════════════════════════════════════════════════════"
echo
echo "This stores your MacroFactor account password in AWS Secrets Manager."
echo "Per ADR-061, this is an accepted risk of the unofficial-API path:"
echo "  - Unlike Hevy, MacroFactor has no scoped API key — the puller has"
echo "    to authenticate as you via Firebase email/password."
echo "  - The secret is encrypted at rest by AWS KMS."
echo "  - Only the mf-puller Lambda role can read it."
echo
read -p "Acknowledge + proceed? [y/N] " ACK
if [ "$ACK" != "y" ] && [ "$ACK" != "Y" ]; then
  echo "Aborted."
  exit 1
fi
echo

read -p   "MacroFactor email: " MF_EMAIL
echo
read -s -p "MacroFactor password: " MF_PASS
echo
echo

if [ -z "$MF_EMAIL" ] || [ -z "$MF_PASS" ]; then
  echo "ERROR: email + password both required. Aborting."
  exit 1
fi

SECRET_JSON=$(python3 -c "
import json, sys
print(json.dumps({
    'username': sys.argv[1],
    'password': sys.argv[2],
}))
" "$MF_EMAIL" "$MF_PASS")

if aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "Secret $SECRET_NAME exists — updating."
  aws secretsmanager put-secret-value \
    --secret-id "$SECRET_NAME" \
    --secret-string "$SECRET_JSON" \
    --region "$REGION" \
    --query 'VersionId' --output text >/dev/null
else
  echo "Creating secret $SECRET_NAME."
  aws secretsmanager create-secret \
    --name "$SECRET_NAME" \
    --description "MacroFactor account credentials for unofficial-API puller (WS-2 Tier 1). Per ADR-014 + ADR-061." \
    --secret-string "$SECRET_JSON" \
    --region "$REGION" \
    --query 'Name' --output text >/dev/null
fi

unset MF_PASS SECRET_JSON

echo
echo "✅ Secret $SECRET_NAME written in $REGION."
echo
echo "Next:"
echo "  cd cdk && npx cdk deploy LifePlatformIngestion --require-approval never"
