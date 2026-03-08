#!/usr/bin/env bash
# SEC-2: Audit and complete the api-keys secret split
#
# PHASE 1 (already done): life-platform/ai-keys created, all AI Lambdas updated.
# PHASE 2 (this script): Verify Phase 1, create ingestion-keys + webhook-key secrets,
#   update ingestion Lambda env vars, tighten IAM role policies.
#
# After this runs:
#   life-platform/ai-keys        → Anthropic key only  (AI-calling Lambdas)
#   life-platform/ingestion-keys → Todoist, Habitify, Notion, Dropbox tokens
#   life-platform/webhook-key    → HAE API key  (health-auto-export-webhook only)
#   life-platform/api-keys       → FROZEN — delete after 2026-04-08
#
# Run from project root: bash deploy/sec2_split_secrets.sh

set -euo pipefail
REGION="us-west-2"
ACCOUNT="205930651321"

# ── Helpers ───────────────────────────────────────────────────────────────────
upsert_secret() {
  local secret_id="$1" description="$2" value="$3"
  if aws secretsmanager describe-secret --secret-id "$secret_id" \
      --region "$REGION" --no-cli-pager &>/dev/null; then
    aws secretsmanager put-secret-value --secret-id "$secret_id" \
      --secret-string "$value" --region "$REGION" --no-cli-pager > /dev/null
    echo "  Updated: $secret_id"
  else
    aws secretsmanager create-secret --name "$secret_id" \
      --description "$description" --secret-string "$value" \
      --region "$REGION" --no-cli-pager > /dev/null
    echo "  Created: $secret_id"
  fi
}

update_lambda_secret_env() {
  local fn="$1" env_key="$2" secret_name="$3"
  echo -n "  $fn ($env_key → $secret_name) ... "
  local CURRENT_ENV
  CURRENT_ENV=$(aws lambda get-function-configuration \
    --function-name "$fn" --region "$REGION" \
    --query "Environment.Variables" --output json --no-cli-pager 2>/dev/null || echo "{}")
  local TMPFILE
  TMPFILE=$(mktemp /tmp/lambda-env-XXXXXX.json)
  python3 -c "
import sys, json
env = json.loads(sys.argv[1])
env[sys.argv[3]] = sys.argv[4]
print(json.dumps({'FunctionName': sys.argv[2], 'Environment': {'Variables': env}}))
" "$CURRENT_ENV" "$fn" "$env_key" "$secret_name" > "$TMPFILE"
  aws lambda update-function-configuration \
    --cli-input-json "file://$TMPFILE" --region "$REGION" --no-cli-pager > /dev/null
  rm -f "$TMPFILE"
  echo "✅"
  sleep 3
}

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  SEC-2: Complete Secret Split                                ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Phase 1: Verify ai-keys ────────────────────────────────────────────────────
echo "── Phase 1: Verifying life-platform/ai-keys ──"
AI_KEYS_ARN=$(aws secretsmanager describe-secret \
  --secret-id "life-platform/ai-keys" --region "$REGION" \
  --query "ARN" --output text --no-cli-pager 2>/dev/null || echo "MISSING")

if [ "$AI_KEYS_ARN" = "MISSING" ]; then
  echo "  ❌ life-platform/ai-keys not found — run p0_split_secret.sh first, then retry"
  exit 1
fi
echo "  ✅ life-platform/ai-keys: $AI_KEYS_ARN"

for fn in "daily-brief" "weekly-digest" "monday-compass" "brittany-weekly-email"; do
  SECRET=$(aws lambda get-function-configuration \
    --function-name "$fn" --region "$REGION" \
    --query "Environment.Variables.ANTHROPIC_SECRET" --output text --no-cli-pager 2>/dev/null || echo "N/A")
  if [ "$SECRET" = "life-platform/ai-keys" ]; then
    echo "  ✅ $fn → ANTHROPIC_SECRET=life-platform/ai-keys"
  else
    echo "  ⚠️  $fn → ANTHROPIC_SECRET='$SECRET' (expected life-platform/ai-keys — fixing)"
    update_lambda_secret_env "$fn" "ANTHROPIC_SECRET" "life-platform/ai-keys"
  fi
done
echo ""

# ── Phase 2: Read bundle to extract remaining keys ─────────────────────────────
echo "── Phase 2: Reading life-platform/api-keys bundle ──"
BUNDLE=$(aws secretsmanager get-secret-value \
  --secret-id "life-platform/api-keys" --region "$REGION" \
  --query "SecretString" --output text --no-cli-pager)
echo "  ✅ Bundle read. Keys present:"
python3 -c "import json,sys; print('     ' + ', '.join(json.loads(sys.argv[1]).keys()))" "$BUNDLE"
echo ""

# ── Phase 3: Create life-platform/webhook-key ──────────────────────────────────
echo "── Phase 3: life-platform/webhook-key ──"
WEBHOOK_VAL=$(python3 -c "
import json, sys
d = json.loads(sys.argv[1])
for k in ['health_auto_export_api_key', 'hae_api_key', 'webhook_api_key', 'hae_key']:
    if k in d:
        print(json.dumps({'api_key': d[k]}))
        sys.exit(0)
print('NOT_FOUND')
" "$BUNDLE")

if [ "$WEBHOOK_VAL" = "NOT_FOUND" ]; then
  echo "  ⚠️  HAE webhook key not found in bundle by known names — skipping"
  echo "     Manually check api-keys and create: aws secretsmanager create-secret --name life-platform/webhook-key ..."
else
  upsert_secret "life-platform/webhook-key" \
    "Health Auto Export webhook API key — split from api-keys $(date +%Y-%m-%d)" \
    "$WEBHOOK_VAL"
  update_lambda_secret_env "health-auto-export-webhook" "API_KEY_SECRET" "life-platform/webhook-key"
fi
echo ""

# ── Phase 4: Create life-platform/ingestion-keys ──────────────────────────────
echo "── Phase 4: life-platform/ingestion-keys ──"
INGESTION_VAL=$(python3 -c "
import json, sys
d = json.loads(sys.argv[1])
# Exclude the keys now in dedicated secrets
skip = {'anthropic_api_key', 'health_auto_export_api_key', 'hae_api_key', 'webhook_api_key', 'hae_key'}
ing = {k: v for k, v in d.items() if k not in skip}
print(json.dumps(ing))
" "$BUNDLE")

echo "  Ingestion keys:"
python3 -c "import json,sys; print('     ' + ', '.join(json.loads(sys.argv[1]).keys()))" "$INGESTION_VAL"

upsert_secret "life-platform/ingestion-keys" \
  "Ingestion API keys (Todoist, Habitify, Notion, Dropbox, etc.) — split from api-keys $(date +%Y-%m-%d)" \
  "$INGESTION_VAL"

# Update Lambdas that use the bundle for non-OAuth credentials
for fn in "todoist-data-ingestion" "notion-journal-ingestion" "dropbox-poll" \
          "activity-enrichment" "journal-enrichment"; do
  update_lambda_secret_env "$fn" "SECRET_NAME" "life-platform/ingestion-keys"
done
echo ""

# ── Phase 5: Tighten IAM policies now that secrets are split ──────────────────
echo "── Phase 5: Tightening IAM role secret access ──"

# compute-role: ai-keys only
aws iam put-role-policy \
  --role-name "life-platform-compute-role" \
  --policy-name "compute-access" \
  --policy-document "{
  \"Version\": \"2012-10-17\",
  \"Statement\": [
    {\"Sid\": \"DynamoDBReadWrite\",\"Effect\": \"Allow\",
      \"Action\": [\"dynamodb:GetItem\",\"dynamodb:Query\",\"dynamodb:PutItem\",
                  \"dynamodb:UpdateItem\",\"dynamodb:BatchGetItem\"],
      \"Resource\": [\"arn:aws:dynamodb:$REGION:$ACCOUNT:table/life-platform\",
                    \"arn:aws:dynamodb:$REGION:$ACCOUNT:table/life-platform/index/*\"]},
    {\"Sid\": \"S3ConfigRead\",\"Effect\": \"Allow\",\"Action\": \"s3:GetObject\",
      \"Resource\": \"arn:aws:s3:::matthew-life-platform/config/*\"},
    {\"Sid\": \"SecretsAI\",\"Effect\": \"Allow\",\"Action\": \"secretsmanager:GetSecretValue\",
      \"Resource\": \"arn:aws:secretsmanager:$REGION:$ACCOUNT:secret:life-platform/ai-keys*\"}
  ]}" --no-cli-pager
echo "  ✅ compute-role: ai-keys only"

# email-role: ai-keys only (no ingestion credentials needed)
aws iam put-role-policy \
  --role-name "life-platform-email-role" \
  --policy-name "email-access" \
  --policy-document "{
  \"Version\": \"2012-10-17\",
  \"Statement\": [
    {\"Sid\": \"DynamoDBRead\",\"Effect\": \"Allow\",
      \"Action\": [\"dynamodb:GetItem\",\"dynamodb:Query\",\"dynamodb:BatchGetItem\"],
      \"Resource\": [\"arn:aws:dynamodb:$REGION:$ACCOUNT:table/life-platform\",
                    \"arn:aws:dynamodb:$REGION:$ACCOUNT:table/life-platform/index/*\"]},
    {\"Sid\": \"S3Read\",\"Effect\": \"Allow\",\"Action\": [\"s3:GetObject\",\"s3:HeadObject\"],
      \"Resource\": [\"arn:aws:s3:::matthew-life-platform/config/*\",
                    \"arn:aws:s3:::matthew-life-platform/dashboard/*\",
                    \"arn:aws:s3:::matthew-life-platform/buddy/*\",
                    \"arn:aws:s3:::matthew-life-platform/avatar/*\"]},
    {\"Sid\": \"S3Write\",\"Effect\": \"Allow\",\"Action\": \"s3:PutObject\",
      \"Resource\": [\"arn:aws:s3:::matthew-life-platform/dashboard/*\",
                    \"arn:aws:s3:::matthew-life-platform/buddy/*\"]},
    {\"Sid\": \"Email\",\"Effect\": \"Allow\",
      \"Action\": [\"ses:SendEmail\",\"sesv2:SendEmail\"],\"Resource\": \"*\"},
    {\"Sid\": \"SecretsAI\",\"Effect\": \"Allow\",\"Action\": \"secretsmanager:GetSecretValue\",
      \"Resource\": \"arn:aws:secretsmanager:$REGION:$ACCOUNT:secret:life-platform/ai-keys*\"}
  ]}" --no-cli-pager
echo "  ✅ email-role: ai-keys only"

# digest-role: ai-keys only
aws iam put-role-policy \
  --role-name "life-platform-digest-role" \
  --policy-name "digest-access" \
  --policy-document "{
  \"Version\": \"2012-10-17\",
  \"Statement\": [
    {\"Sid\": \"DynamoDBRead\",\"Effect\": \"Allow\",
      \"Action\": [\"dynamodb:GetItem\",\"dynamodb:Query\",\"dynamodb:BatchGetItem\"],
      \"Resource\": [\"arn:aws:dynamodb:$REGION:$ACCOUNT:table/life-platform\",
                    \"arn:aws:dynamodb:$REGION:$ACCOUNT:table/life-platform/index/*\"]},
    {\"Sid\": \"S3Read\",\"Effect\": \"Allow\",\"Action\": [\"s3:GetObject\",\"s3:HeadObject\"],
      \"Resource\": [\"arn:aws:s3:::matthew-life-platform/config/*\",
                    \"arn:aws:s3:::matthew-life-platform/dashboard/*\",
                    \"arn:aws:s3:::matthew-life-platform/blog/*\",
                    \"arn:aws:s3:::matthew-life-platform/buddy/*\",
                    \"arn:aws:s3:::matthew-life-platform/avatar/*\"]},
    {\"Sid\": \"S3Write\",\"Effect\": \"Allow\",\"Action\": \"s3:PutObject\",
      \"Resource\": [\"arn:aws:s3:::matthew-life-platform/dashboard/*\",
                    \"arn:aws:s3:::matthew-life-platform/blog/*\",
                    \"arn:aws:s3:::matthew-life-platform/buddy/*\"]},
    {\"Sid\": \"Email\",\"Effect\": \"Allow\",
      \"Action\": [\"ses:SendEmail\",\"sesv2:SendEmail\"],\"Resource\": \"*\"},
    {\"Sid\": \"SecretsAI\",\"Effect\": \"Allow\",\"Action\": \"secretsmanager:GetSecretValue\",
      \"Resource\": \"arn:aws:secretsmanager:$REGION:$ACCOUNT:secret:life-platform/ai-keys*\"}
  ]}" --no-cli-pager
echo "  ✅ digest-role: ai-keys only"
echo ""

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✅ SEC-2 Complete                                           ║"
echo "║                                                              ║"
echo "║  Secrets:                                                    ║"
echo "║    life-platform/ai-keys        AI-calling Lambdas          ║"
echo "║    life-platform/ingestion-keys Todoist, Notion, Dropbox    ║"
echo "║    life-platform/webhook-key    HAE webhook Lambda only      ║"
echo "║    life-platform/api-keys       FROZEN → delete 2026-04-08  ║"
echo "║                                                              ║"
echo "║  IAM roles now scoped to ai-keys only (no bundle access)    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
