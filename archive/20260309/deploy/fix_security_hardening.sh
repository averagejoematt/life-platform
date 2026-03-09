#!/usr/bin/env bash
# SEC-1 FIX: Re-assign Lambda roles (the create step succeeded, assignment silently failed)
# SEC-2 FIX: Handle api-keys marked for deletion
#
# Run from: ~/Documents/Claude/life-platform/
# Usage:    bash deploy/fix_security_hardening.sh

set -euo pipefail

REGION="us-west-2"
ACCOUNT="205930651321"

echo "=== Security Hardening Fix ==="
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# DIAGNOSIS: List current secrets and Lambda roles
# ─────────────────────────────────────────────────────────────────────────────
echo "--- Current Secrets Manager inventory ---"
aws secretsmanager list-secrets \
  --region "${REGION}" \
  --query "SecretList[?starts_with(Name, 'life-platform/')].{Name:Name, DeletedDate:DeletedDate}" \
  --output table \
  --no-cli-pager
echo ""

echo "--- Checking if api-keys can be restored ---"
aws secretsmanager describe-secret \
  --secret-id "life-platform/api-keys" \
  --region "${REGION}" \
  --no-cli-pager 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
deleted = d.get('DeletedDate')
if deleted:
    print(f'  api-keys marked for deletion at: {deleted}')
    print('  CAN be restored within 30-day window.')
else:
    print('  api-keys exists and is not scheduled for deletion.')
" || echo "  api-keys secret not found or inaccessible."
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# FIX 1: Restore api-keys if it was marked for deletion
# ─────────────────────────────────────────────────────────────────────────────
echo "--- FIX 1: Restore api-keys secret ---"
RESTORE_RESULT=$(aws secretsmanager restore-secret \
  --secret-id "life-platform/api-keys" \
  --region "${REGION}" \
  --no-cli-pager 2>&1) || true

if echo "${RESTORE_RESULT}" | grep -q "ARN\|Name"; then
  echo "  ✓ api-keys restored successfully"
elif echo "${RESTORE_RESULT}" | grep -q "InvalidRequestException.*not scheduled"; then
  echo "  api-keys was not scheduled for deletion (already active)"
else
  echo "  Result: ${RESTORE_RESULT}"
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# FIX 2: Re-assign Lambda roles (with proper error output this time)
# ─────────────────────────────────────────────────────────────────────────────
echo "--- FIX 2: Re-assigning Lambda roles ---"
echo "(The roles were created successfully — just need to assign them)"
echo ""

assign_role() {
  local FUNC_NAME="$1"
  local ROLE_NAME="$2"
  local ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/${ROLE_NAME}"

  echo -n "  ${FUNC_NAME} → ${ROLE_NAME}: "

  # Check Lambda exists first
  EXISTS=$(aws lambda get-function-configuration \
    --function-name "${FUNC_NAME}" \
    --region "${REGION}" \
    --query "FunctionName" \
    --output text \
    --no-cli-pager 2>/dev/null || echo "")

  if [ -z "${EXISTS}" ]; then
    echo "SKIP (Lambda not found)"
    return
  fi

  # Wait for Lambda to be in updatable state
  for i in 1 2 3; do
    STATE=$(aws lambda get-function-configuration \
      --function-name "${FUNC_NAME}" \
      --region "${REGION}" \
      --query "LastUpdateStatus" \
      --output text \
      --no-cli-pager 2>/dev/null || echo "Unknown")
    if [ "${STATE}" = "Successful" ] || [ "${STATE}" = "None" ] || [ "${STATE}" = "null" ] || [ "${STATE}" = "None" ]; then
      break
    fi
    echo -n "(waiting ${STATE})... "
    sleep 5
  done

  RESULT=$(aws lambda update-function-configuration \
    --function-name "${FUNC_NAME}" \
    --role "${ROLE_ARN}" \
    --region "${REGION}" \
    --no-cli-pager \
    --query "Role" \
    --output text 2>&1)

  if echo "${RESULT}" | grep -q "arn:aws:iam"; then
    echo "✓"
  else
    echo "FAILED: ${RESULT}"
  fi

  sleep 3
}

assign_role "daily-brief"           "lambda-daily-brief-role"
assign_role "weekly-digest"         "lambda-weekly-digest-role-v2"
assign_role "monthly-digest"        "lambda-monthly-digest-role"
assign_role "nutrition-review"      "lambda-nutrition-review-role"
assign_role "wednesday-chronicle"   "lambda-wednesday-chronicle-role"
assign_role "weekly-plate"          "lambda-weekly-plate-role"
assign_role "monday-compass"        "lambda-monday-compass-role"
assign_role "adaptive-mode-compute" "lambda-adaptive-mode-role"
assign_role "daily-metrics-compute" "lambda-daily-metrics-role"
assign_role "daily-insight-compute" "lambda-daily-insight-role"
assign_role "hypothesis-engine"     "lambda-hypothesis-engine-role"
assign_role "life-platform-qa-smoke"     "lambda-qa-smoke-role"
assign_role "life-platform-data-export"  "lambda-data-export-role"

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# VERIFY role assignments
# ─────────────────────────────────────────────────────────────────────────────
echo "--- Verification: Lambda execution roles ---"
for FUNC in daily-brief weekly-digest monthly-digest nutrition-review \
            wednesday-chronicle weekly-plate monday-compass \
            adaptive-mode-compute daily-metrics-compute daily-insight-compute \
            hypothesis-engine life-platform-qa-smoke life-platform-data-export; do
  ROLE=$(aws lambda get-function-configuration \
    --function-name "${FUNC}" \
    --region "${REGION}" \
    --query "Role" \
    --output text \
    --no-cli-pager 2>/dev/null | sed 's|.*/||' || echo "NOT FOUND")
  # Flag if still on old shared roles
  if echo "${ROLE}" | grep -qE "email-role|digest-role|compute-role"; then
    echo "  ⚠️  ${FUNC}: ${ROLE}  ← STILL ON OLD ROLE"
  else
    echo "  ✓  ${FUNC}: ${ROLE}"
  fi
done

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# FIX 3: Now run SEC-2 (api-keys should be accessible again)
# ─────────────────────────────────────────────────────────────────────────────
echo "--- FIX 3: Running SEC-2 secret split ---"
echo ""

# Quick test read before proceeding
API_KEYS_TEST=$(aws secretsmanager get-secret-value \
  --secret-id "life-platform/api-keys" \
  --region "${REGION}" \
  --query "SecretString" \
  --output text \
  --no-cli-pager 2>&1)

if echo "${API_KEYS_TEST}" | python3 -c "import sys,json; json.load(sys.stdin); print('readable')" 2>/dev/null | grep -q "readable"; then
  echo "  ✓ api-keys is readable — proceeding with SEC-2"
  echo ""
  bash deploy/setup_sec2_secrets.sh
else
  echo "  ✗ api-keys still not readable: ${API_KEYS_TEST}"
  echo ""
  echo "  MANUAL FALLBACK: The credentials need to be re-entered manually."
  echo "  Run this to see what secrets currently hold the credentials:"
  echo "    aws secretsmanager list-secrets --region ${REGION} --query \"SecretList[?starts_with(Name, 'life-platform/')].Name\" --output text"
  echo ""
  echo "  If you have the Anthropic API key and other creds handy, you can create"
  echo "  the new domain secrets directly:"
  echo ""
  echo "  # Todoist (from your Todoist account → Settings → Integrations → API token)"
  echo "  aws secretsmanager create-secret --name life-platform/todoist \\"
  echo "    --secret-string '{\"todoist_api_token\":\"YOUR_TOKEN\"}' --region ${REGION}"
  echo ""
  echo "  # Notion (from notion.so/my-integrations)"
  echo "  aws secretsmanager create-secret --name life-platform/notion \\"
  echo "    --secret-string '{\"notion_api_key\":\"YOUR_KEY\",\"notion_database_id\":\"YOUR_DB_ID\"}' --region ${REGION}"
  echo ""
  echo "  # Dropbox (from dropbox.com/developers/apps)"
  echo "  aws secretsmanager create-secret --name life-platform/dropbox \\"
  echo "    --secret-string '{\"dropbox_app_key\":\"KEY\",\"dropbox_app_secret\":\"SECRET\",\"dropbox_refresh_token\":\"TOKEN\"}' --region ${REGION}"
fi

echo ""
echo "=== Fix complete ==="
echo ""
echo "After this, continue with:"
echo "  bash deploy/deploy_mcp.sh           # SEC-3: deploy MCP with input validation"
echo "  bash deploy/rel1_compute_alarm.sh   # REL-1: CloudWatch alarms"
echo "  bash deploy/iam1_audit_roles.sh     # IAM-1: audit"
