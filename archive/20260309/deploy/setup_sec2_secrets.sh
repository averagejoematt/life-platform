#!/usr/bin/env bash
# SEC-2: Split consolidated api-keys secret into domain-specific secrets
#
# Reads the current life-platform/api-keys bundle and distributes values into
# dedicated secrets. Updates Lambda env vars (ANTHROPIC_SECRET, SECRET_NAME)
# so each Lambda reads only from its own secret.
#
# Current api-keys bundle fields:
#   anthropic_api_key        → life-platform/ai-keys (already exists from P0)
#   todoist_api_token        → life-platform/todoist  (NEW)
#   habitify_api_key         → stays in api-keys for now (ingestion uses own secret)
#   health_auto_export_api_key → stays in api-keys (only webhook Lambda needs it)
#   notion_api_key           → life-platform/notion  (NEW)
#   notion_database_id       → life-platform/notion  (NEW, alongside key)
#   dropbox_app_key          → life-platform/dropbox (NEW)
#   dropbox_app_secret       → life-platform/dropbox (NEW)
#   dropbox_refresh_token    → life-platform/dropbox (NEW)
#
# Run from: ~/Documents/Claude/life-platform/
# Usage:    bash deploy/setup_sec2_secrets.sh
#
# Prerequisite: SEC-1 roles must exist first (setup_sec1_iam_roles.sh)
# Cost: +3 secrets × $0.40/month = $1.20/month additional

set -euo pipefail

REGION="us-west-2"
ACCOUNT="205930651321"

echo "=== SEC-2: Splitting consolidated api-keys secret ==="
echo ""
echo "Step 1: Reading current api-keys bundle..."
echo "(You'll need to confirm each new secret value — pulling from Secrets Manager)"
echo ""

# Read the full api-keys bundle
API_KEYS_JSON=$(aws secretsmanager get-secret-value \
  --secret-id "life-platform/api-keys" \
  --region "${REGION}" \
  --query "SecretString" \
  --output text \
  --no-cli-pager)

echo "  ✓ Read api-keys bundle"

# Extract individual values using Python (handles JSON cleanly)
TODOIST_TOKEN=$(echo "$API_KEYS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('todoist_api_token',''))" 2>/dev/null || echo "")
NOTION_KEY=$(echo "$API_KEYS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('notion_api_key',''))" 2>/dev/null || echo "")
NOTION_DB=$(echo "$API_KEYS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('notion_database_id',''))" 2>/dev/null || echo "")
DROPBOX_KEY=$(echo "$API_KEYS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('dropbox_app_key',''))" 2>/dev/null || echo "")
DROPBOX_SECRET=$(echo "$API_KEYS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('dropbox_app_secret',''))" 2>/dev/null || echo "")
DROPBOX_REFRESH=$(echo "$API_KEYS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('dropbox_refresh_token',''))" 2>/dev/null || echo "")
ANTHROPIC_KEY=$(echo "$API_KEYS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('anthropic_api_key',''))" 2>/dev/null || echo "")

echo "  Extracted: todoist=$([ -n "$TODOIST_TOKEN" ] && echo '✓' || echo '✗ MISSING')"
echo "  Extracted: notion=$([ -n "$NOTION_KEY" ] && echo '✓' || echo '✗ MISSING')"
echo "  Extracted: dropbox=$([ -n "$DROPBOX_KEY" ] && echo '✓' || echo '✗ MISSING')"
echo "  Extracted: anthropic=$([ -n "$ANTHROPIC_KEY" ] && echo '✓' || echo '✗ MISSING')"

# ══════════════════════════════════════════════════════════════════════════════
# Create/update life-platform/todoist
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "Step 2: Creating life-platform/todoist..."
if [ -n "$TODOIST_TOKEN" ]; then
  TODOIST_JSON=$(python3 -c "import json; print(json.dumps({'todoist_api_token': '$TODOIST_TOKEN'}))")
  aws secretsmanager create-secret \
    --name "life-platform/todoist" \
    --description "Todoist API token for Monday Compass and Todoist ingestion Lambda" \
    --secret-string "${TODOIST_JSON}" \
    --region "${REGION}" \
    --no-cli-pager 2>/dev/null || \
  aws secretsmanager update-secret \
    --secret-id "life-platform/todoist" \
    --secret-string "${TODOIST_JSON}" \
    --region "${REGION}" \
    --no-cli-pager
  echo "  ✓ life-platform/todoist created/updated"
else
  echo "  ✗ SKIPPED: todoist_api_token not found in api-keys bundle"
fi

# ══════════════════════════════════════════════════════════════════════════════
# Create/update life-platform/notion
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "Step 3: Creating life-platform/notion..."
if [ -n "$NOTION_KEY" ]; then
  NOTION_JSON=$(python3 -c "import json; print(json.dumps({'notion_api_key': '$NOTION_KEY', 'notion_database_id': '$NOTION_DB'}))")
  aws secretsmanager create-secret \
    --name "life-platform/notion" \
    --description "Notion API credentials for journal ingestion Lambda" \
    --secret-string "${NOTION_JSON}" \
    --region "${REGION}" \
    --no-cli-pager 2>/dev/null || \
  aws secretsmanager update-secret \
    --secret-id "life-platform/notion" \
    --secret-string "${NOTION_JSON}" \
    --region "${REGION}" \
    --no-cli-pager
  echo "  ✓ life-platform/notion created/updated"
else
  echo "  ✗ SKIPPED: notion_api_key not found in api-keys bundle"
fi

# ══════════════════════════════════════════════════════════════════════════════
# Create/update life-platform/dropbox
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "Step 4: Creating life-platform/dropbox..."
if [ -n "$DROPBOX_KEY" ]; then
  DROPBOX_JSON=$(python3 -c "import json; print(json.dumps({
    'dropbox_app_key': '$DROPBOX_KEY',
    'dropbox_app_secret': '$DROPBOX_SECRET',
    'dropbox_refresh_token': '$DROPBOX_REFRESH'
  }))")
  aws secretsmanager create-secret \
    --name "life-platform/dropbox" \
    --description "Dropbox OAuth credentials for dropbox-poll Lambda (MacroFactor CSV ingestion)" \
    --secret-string "${DROPBOX_JSON}" \
    --region "${REGION}" \
    --no-cli-pager 2>/dev/null || \
  aws secretsmanager update-secret \
    --secret-id "life-platform/dropbox" \
    --secret-string "${DROPBOX_JSON}" \
    --region "${REGION}" \
    --no-cli-pager
  echo "  ✓ life-platform/dropbox created/updated"
else
  echo "  ✗ SKIPPED: dropbox credentials not found in api-keys bundle"
fi

# ══════════════════════════════════════════════════════════════════════════════
# Confirm life-platform/ai-keys has the Anthropic key
# (was created in P0 hardening; verify it's current)
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "Step 5: Verifying life-platform/ai-keys (P0 hardening secret)..."
AI_KEYS_CHECK=$(aws secretsmanager get-secret-value \
  --secret-id "life-platform/ai-keys" \
  --region "${REGION}" \
  --query "SecretString" \
  --output text \
  --no-cli-pager 2>/dev/null || echo "")

if [ -n "$AI_KEYS_CHECK" ]; then
  HAS_KEY=$(echo "$AI_KEYS_CHECK" | python3 -c "import sys,json; d=json.load(sys.stdin); print('yes' if d.get('anthropic_api_key') else 'NO KEY')" 2>/dev/null || echo "parse error")
  echo "  life-platform/ai-keys: ${HAS_KEY}"
  if [ "$HAS_KEY" = "yes" ] && [ -n "$ANTHROPIC_KEY" ]; then
    # Ensure key is in sync with api-keys bundle
    AI_KEY_CURRENT=$(echo "$AI_KEYS_CHECK" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('anthropic_api_key',''))" 2>/dev/null || echo "")
    if [ "$AI_KEY_CURRENT" != "$ANTHROPIC_KEY" ]; then
      echo "  ⚠ ai-keys Anthropic key differs from api-keys — updating ai-keys to match..."
      AI_SYNC_JSON=$(python3 -c "import json; print(json.dumps({'anthropic_api_key': '$ANTHROPIC_KEY'}))")
      aws secretsmanager update-secret \
        --secret-id "life-platform/ai-keys" \
        --secret-string "${AI_SYNC_JSON}" \
        --region "${REGION}" \
        --no-cli-pager
      echo "  ✓ ai-keys updated"
    else
      echo "  ✓ ai-keys is in sync with api-keys"
    fi
  fi
else
  echo "  ✗ life-platform/ai-keys not found — creating..."
  if [ -n "$ANTHROPIC_KEY" ]; then
    AI_CREATE_JSON=$(python3 -c "import json; print(json.dumps({'anthropic_api_key': '$ANTHROPIC_KEY'}))")
    aws secretsmanager create-secret \
      --name "life-platform/ai-keys" \
      --description "Anthropic API key (isolated from api-keys bundle)" \
      --secret-string "${AI_CREATE_JSON}" \
      --region "${REGION}" \
      --no-cli-pager
    echo "  ✓ life-platform/ai-keys created"
  fi
fi

# ══════════════════════════════════════════════════════════════════════════════
# Update Lambda env vars to use dedicated secrets
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "Step 6: Updating Lambda env vars to use dedicated secrets..."
echo "(Each Lambda now reads from its own secret instead of the consolidated bundle)"

update_env_var() {
  local FUNC="$1"
  local ENV_KEY="$2"
  local ENV_VAL="$3"
  echo "  ${FUNC}: ${ENV_KEY}=${ENV_VAL}"

  # Get current env vars
  CURRENT_ENV=$(aws lambda get-function-configuration \
    --function-name "${FUNC}" \
    --region "${REGION}" \
    --query "Environment.Variables" \
    --output json \
    --no-cli-pager 2>/dev/null || echo "{}")

  # Merge new var with existing vars using Python
  MERGED_ENV=$(python3 -c "
import sys, json
current = json.loads(sys.argv[1])
current['${ENV_KEY}'] = '${ENV_VAL}'
print(json.dumps({'Variables': current}))
" "$CURRENT_ENV")

  aws lambda update-function-configuration \
    --function-name "${FUNC}" \
    --environment "${MERGED_ENV}" \
    --region "${REGION}" \
    --no-cli-pager \
    2>/dev/null || echo "    (Lambda not found — skipping)"
  sleep 3
}

# All email/compute Lambdas: point ANTHROPIC_SECRET to ai-keys
for FUNC in daily-brief weekly-digest monthly-digest nutrition-review \
            wednesday-chronicle weekly-plate adaptive-mode-compute \
            daily-metrics-compute daily-insight-compute hypothesis-engine; do
  update_env_var "${FUNC}" "ANTHROPIC_SECRET" "life-platform/ai-keys"
done

# monday-compass: update ANTHROPIC_SECRET; add TODOIST_SECRET
update_env_var "monday-compass" "ANTHROPIC_SECRET" "life-platform/ai-keys"
update_env_var "monday-compass" "TODOIST_SECRET" "life-platform/todoist"

# notion ingestion: update to use dedicated notion secret
update_env_var "notion-journal-ingestion" "SECRET_NAME" "life-platform/notion"

# dropbox-poll: update to use dedicated dropbox secret
update_env_var "dropbox-poll" "SECRET_NAME" "life-platform/dropbox"

# ══════════════════════════════════════════════════════════════════════════════
# Update IAM policies: add todoist secret access to monday-compass role
# (already included in SEC-1 script via SECRET_API_KEYS — update to todoist-specific)
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "Step 7: Updating monday-compass IAM policy to include todoist secret..."
TODOIST_SECRET_ARN="arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:life-platform/todoist*"
AI_KEYS_ARN="arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:life-platform/ai-keys*"
TABLE_ARN="arn:aws:dynamodb:${REGION}:${ACCOUNT}:table/life-platform"
SES_IDENTITY="arn:aws:ses:${REGION}:${ACCOUNT}:identity/mattsusername.com"
SQS_DLQ="arn:aws:sqs:${REGION}:${ACCOUNT}:life-platform-ingestion-dlq"
KMS_KEY_ID="444438d1-a5e0-43b8-9391-3cd2d70dde4d"
BUCKET="matthew-life-platform"

aws iam put-role-policy \
  --role-name "lambda-monday-compass-role" \
  --policy-name "life-platform-monday-compass" \
  --policy-document "$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDB",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem","dynamodb:Query","dynamodb:PutItem"],
      "Resource": "${TABLE_ARN}"
    },
    {
      "Sid": "KMS",
      "Effect": "Allow",
      "Action": ["kms:Decrypt","kms:GenerateDataKey"],
      "Resource": "arn:aws:kms:${REGION}:${ACCOUNT}:key/${KMS_KEY_ID}"
    },
    {
      "Sid": "S3Read",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::${BUCKET}/config/*"
    },
    {
      "Sid": "Secrets",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": [
        "${AI_KEYS_ARN}",
        "${TODOIST_SECRET_ARN}"
      ]
    },
    {
      "Sid": "SES",
      "Effect": "Allow",
      "Action": "ses:SendEmail",
      "Resource": "${SES_IDENTITY}"
    },
    {
      "Sid": "SQS",
      "Effect": "Allow",
      "Action": "sqs:SendMessage",
      "Resource": "${SQS_DLQ}"
    }
  ]
}
EOF
)" \
  --no-cli-pager
echo "  ✓ monday-compass policy updated (todoist-specific secret)"

# ══════════════════════════════════════════════════════════════════════════════
# Secret count update
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "=== Secret inventory after SEC-2 ==="
aws secretsmanager list-secrets \
  --region "${REGION}" \
  --query "SecretList[?starts_with(Name, 'life-platform/')].{Name:Name}" \
  --output table \
  --no-cli-pager

echo ""
echo "=== SEC-2 complete ==="
echo ""
echo "Cost impact: +3 new secrets × \$0.40/month = \$1.20/month additional"
echo ""
echo "Next steps:"
echo "  1. Update monday_compass_lambda.py to read todoist token from TODOIST_SECRET env var"
echo "     (currently reads from SECRET_NAME which returns the full api-keys bundle)"
echo "  2. Test each Lambda manually after role + secret changes:"
echo "     aws lambda invoke --function-name daily-brief --payload '{}' /tmp/brief_out.json --region ${REGION}"
echo "  3. After 7 days of clean operation, remove todoist/notion/dropbox from api-keys bundle"
echo "     (keep api-keys for habitify_api_key and health_auto_export_api_key for now)"
