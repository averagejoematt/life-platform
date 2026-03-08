#!/usr/bin/env bash
# SEC-2 FIX: Handle previously-deleted domain secrets
# Restores any life-platform/* secrets pending deletion, then re-runs SEC-2
#
# Run from: ~/Documents/Claude/life-platform/
# Usage:    bash deploy/fix_sec2_secrets.sh

set -euo pipefail
REGION="us-west-2"

echo "=== SEC-2 Fix: Restore deleted secrets + split ==="
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Show ALL secrets including pending-deletion (need --include-planned-deletion)
# ─────────────────────────────────────────────────────────────────────────────
echo "--- All life-platform/* secrets (including pending deletion) ---"
aws secretsmanager list-secrets \
  --region "${REGION}" \
  --include-planned-deletion \
  --query "SecretList[?starts_with(Name, 'life-platform/')].{Name:Name,Status:DeletedDate}" \
  --output table \
  --no-cli-pager
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Restore any pending-deletion secrets that we need
# ─────────────────────────────────────────────────────────────────────────────
echo "--- Restoring any pending-deletion domain secrets ---"

for SECRET in "life-platform/todoist" "life-platform/notion" "life-platform/dropbox" "life-platform/api-keys"; do
  RESULT=$(aws secretsmanager restore-secret \
    --secret-id "${SECRET}" \
    --region "${REGION}" \
    --no-cli-pager 2>&1) || true

  if echo "${RESULT}" | grep -q '"ARN"'; then
    echo "  ✓ Restored: ${SECRET}"
  elif echo "${RESULT}" | grep -q "not scheduled\|is not scheduled"; then
    echo "  ✓ Active (not deleted): ${SECRET}"
  elif echo "${RESULT}" | grep -q "ResourceNotFoundException\|Secrets Manager can't find"; then
    echo "  — Not found (will be created fresh): ${SECRET}"
  else
    echo "  ? ${SECRET}: ${RESULT}"
  fi
done
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Read the api-keys bundle
# ─────────────────────────────────────────────────────────────────────────────
echo "--- Reading api-keys bundle ---"
API_KEYS_JSON=$(aws secretsmanager get-secret-value \
  --secret-id "life-platform/api-keys" \
  --region "${REGION}" \
  --query "SecretString" \
  --output text \
  --no-cli-pager)
echo "  ✓ Read api-keys bundle"

# Also check ingestion-keys (may hold todoist/notion/dropbox after P0 consolidation)
echo ""
echo "--- Checking life-platform/ingestion-keys for credentials ---"
INGESTION_KEYS_JSON=$(aws secretsmanager get-secret-value \
  --secret-id "life-platform/ingestion-keys" \
  --region "${REGION}" \
  --query "SecretString" \
  --output text \
  --no-cli-pager 2>/dev/null || echo "{}")

echo "${INGESTION_KEYS_JSON}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'  ingestion-keys fields: {list(d.keys())}')
"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Extract credentials — check both api-keys and ingestion-keys
# ─────────────────────────────────────────────────────────────────────────────
TODOIST_TOKEN=$(python3 -c "
import json
api = json.loads('''${API_KEYS_JSON}''')
ing = json.loads('''${INGESTION_KEYS_JSON}''')
val = api.get('todoist_api_token') or ing.get('todoist_api_token') or ''
print(val)
" 2>/dev/null || echo "")

NOTION_KEY=$(python3 -c "
import json
api = json.loads('''${API_KEYS_JSON}''')
ing = json.loads('''${INGESTION_KEYS_JSON}''')
val = api.get('notion_api_key') or ing.get('notion_api_key') or ''
print(val)
" 2>/dev/null || echo "")

NOTION_DB=$(python3 -c "
import json
api = json.loads('''${API_KEYS_JSON}''')
ing = json.loads('''${INGESTION_KEYS_JSON}''')
val = api.get('notion_database_id') or ing.get('notion_database_id') or ''
print(val)
" 2>/dev/null || echo "")

DROPBOX_KEY=$(python3 -c "
import json
api = json.loads('''${API_KEYS_JSON}''')
ing = json.loads('''${INGESTION_KEYS_JSON}''')
val = api.get('dropbox_app_key') or ing.get('dropbox_app_key') or ''
print(val)
" 2>/dev/null || echo "")

DROPBOX_SECRET=$(python3 -c "
import json
api = json.loads('''${API_KEYS_JSON}''')
ing = json.loads('''${INGESTION_KEYS_JSON}''')
val = api.get('dropbox_app_secret') or ing.get('dropbox_app_secret') or ''
print(val)
" 2>/dev/null || echo "")

DROPBOX_REFRESH=$(python3 -c "
import json
api = json.loads('''${API_KEYS_JSON}''')
ing = json.loads('''${INGESTION_KEYS_JSON}''')
val = api.get('dropbox_refresh_token') or ing.get('dropbox_refresh_token') or ''
print(val)
" 2>/dev/null || echo "")

echo "--- Credentials found ---"
echo "  todoist:  $([ -n "${TODOIST_TOKEN}" ] && echo '✓' || echo '✗ MISSING')"
echo "  notion:   $([ -n "${NOTION_KEY}" ] && echo '✓' || echo '✗ MISSING')"
echo "  dropbox:  $([ -n "${DROPBOX_KEY}" ] && echo '✓' || echo '✗ MISSING')"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Create/update each domain secret
# (After restore above, these either exist cleanly or don't exist yet)
# ─────────────────────────────────────────────────────────────────────────────
upsert_secret() {
  local NAME="$1"
  local JSON="$2"
  local DESC="$3"

  # Try update first (exists), then create (doesn't exist)
  if aws secretsmanager update-secret \
    --secret-id "${NAME}" \
    --secret-string "${JSON}" \
    --region "${REGION}" \
    --no-cli-pager \
    --query "ARN" --output text 2>/dev/null | grep -q "arn:"; then
    echo "  ✓ Updated: ${NAME}"
  else
    aws secretsmanager create-secret \
      --name "${NAME}" \
      --description "${DESC}" \
      --secret-string "${JSON}" \
      --region "${REGION}" \
      --no-cli-pager \
      --query "ARN" --output text 2>/dev/null
    echo "  ✓ Created: ${NAME}"
  fi
}

echo "--- Creating/updating domain secrets ---"

if [ -n "${TODOIST_TOKEN}" ]; then
  upsert_secret "life-platform/todoist" \
    "{\"todoist_api_token\":\"${TODOIST_TOKEN}\"}" \
    "Todoist API token for Monday Compass and Todoist ingestion Lambda"
else
  echo "  ✗ SKIPPED life-platform/todoist — token not found in either bundle"
fi

if [ -n "${NOTION_KEY}" ]; then
  upsert_secret "life-platform/notion" \
    "{\"notion_api_key\":\"${NOTION_KEY}\",\"notion_database_id\":\"${NOTION_DB}\"}" \
    "Notion API credentials for journal ingestion Lambda"
else
  echo "  ✗ SKIPPED life-platform/notion — key not found in either bundle"
fi

if [ -n "${DROPBOX_KEY}" ]; then
  upsert_secret "life-platform/dropbox" \
    "{\"dropbox_app_key\":\"${DROPBOX_KEY}\",\"dropbox_app_secret\":\"${DROPBOX_SECRET}\",\"dropbox_refresh_token\":\"${DROPBOX_REFRESH}\"}" \
    "Dropbox OAuth credentials for dropbox-poll Lambda"
else
  echo "  ✗ SKIPPED life-platform/dropbox — credentials not found in either bundle"
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Update Lambda env vars
# ─────────────────────────────────────────────────────────────────────────────
echo "--- Updating Lambda ANTHROPIC_SECRET env vars ---"

update_env() {
  local FUNC="$1"
  local KEY="$2"
  local VAL="$3"

  CURRENT=$(aws lambda get-function-configuration \
    --function-name "${FUNC}" --region "${REGION}" \
    --query "Environment.Variables" --output json --no-cli-pager 2>/dev/null || echo "{}")

  MERGED=$(python3 -c "
import sys, json
e = json.loads(sys.argv[1])
e['${KEY}'] = '${VAL}'
print(json.dumps({'Variables': e}))
" "${CURRENT}")

  aws lambda update-function-configuration \
    --function-name "${FUNC}" \
    --environment "${MERGED}" \
    --region "${REGION}" \
    --no-cli-pager \
    --query "FunctionName" --output text 2>/dev/null | xargs -I{} echo "  ✓ {}: ${KEY}=${VAL}"
  sleep 2
}

for FUNC in daily-brief weekly-digest monthly-digest nutrition-review \
            wednesday-chronicle weekly-plate adaptive-mode-compute \
            daily-metrics-compute daily-insight-compute hypothesis-engine; do
  update_env "${FUNC}" "ANTHROPIC_SECRET" "life-platform/ai-keys"
done

update_env "monday-compass" "ANTHROPIC_SECRET" "life-platform/ai-keys"
[ -n "${TODOIST_TOKEN}" ] && update_env "monday-compass" "TODOIST_SECRET" "life-platform/todoist"

[ -n "${NOTION_KEY}" ] && update_env "notion-journal-ingestion" "SECRET_NAME" "life-platform/notion"
[ -n "${DROPBOX_KEY}" ] && update_env "dropbox-poll" "SECRET_NAME" "life-platform/dropbox"

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Final inventory
# ─────────────────────────────────────────────────────────────────────────────
echo "--- Final secrets inventory ---"
aws secretsmanager list-secrets \
  --region "${REGION}" \
  --include-planned-deletion \
  --query "SecretList[?starts_with(Name, 'life-platform/')].{Name:Name,Deleted:DeletedDate}" \
  --output table \
  --no-cli-pager

echo ""
echo "=== SEC-2 fix complete ==="
echo ""
echo "Next:"
echo "  bash deploy/deploy_mcp.sh          # SEC-3"
echo "  bash deploy/rel1_compute_alarm.sh  # REL-1"
echo "  bash deploy/iam1_audit_roles.sh    # IAM-1 audit"
echo ""
echo "Then commit:"
echo "  git add -A && git commit -m 'v3.1.0: Security hardening — SEC-1/2/3, IAM-1, REL-1' && git push"
