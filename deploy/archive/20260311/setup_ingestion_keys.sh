#!/usr/bin/env bash
# deploy/setup_ingestion_keys.sh
# COST-B + Habitify Secret: Merge todoist/notion/dropbox/habitify API keys
# into life-platform/ingestion-keys.
#
# WHY: CDK v3.4.7 already deployed Lambda env vars pointing to ingestion-keys
# for these 4 Lambdas. Without this merge, those Lambdas are currently broken.
#
# After merge:
#   - life-platform/todoist   -> schedule deletion (saves $0.40/mo)
#   - life-platform/notion    -> schedule deletion (saves $0.40/mo)
#   - life-platform/dropbox   -> schedule deletion (saves $0.40/mo)
#   Total savings: $1.20/mo
#
# life-platform/habitify is NOT created separately (superseded: habitify_api_key
# goes into ingestion-keys per role_policies.py COST-B update 2026-03-10).
#
# Usage: bash deploy/setup_ingestion_keys.sh

set -euo pipefail
REGION="us-west-2"

echo "=== COST-B + Habitify: Merging keys into life-platform/ingestion-keys ==="
echo ""

# ── Step 1: Read current ingestion-keys ─────────────────────────────────────
echo "Reading current life-platform/ingestion-keys..."
INGESTION_CURRENT=$(aws secretsmanager get-secret-value \
  --secret-id "life-platform/ingestion-keys" \
  --region "$REGION" \
  --query 'SecretString' \
  --output text)
echo "  Current keys: $(echo "$INGESTION_CURRENT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(list(d.keys()))")"

# ── Step 2: Read source secrets ─────────────────────────────────────────────
echo ""
echo "Reading source secrets..."
API_KEYS=$(aws secretsmanager get-secret-value \
  --secret-id "life-platform/api-keys" \
  --region "$REGION" \
  --query 'SecretString' \
  --output text 2>/dev/null || echo "{}")

# Helper: read secret only if it exists AND is not marked for deletion
read_secret_safe() {
  local secret_id="$1"
  local status
  status=$(aws secretsmanager describe-secret --secret-id "$secret_id" --region "$REGION" \
    --query 'DeletedDate' --output text 2>/dev/null || echo "NOTFOUND")
  if [[ "$status" == "NOTFOUND" || "$status" == "None" && $? -ne 0 ]]; then
    echo "{}"
    return
  fi
  # DeletedDate is set -> marked for deletion, skip
  if [[ "$status" != "None" && "$status" != "NOTFOUND" && -n "$status" ]]; then
    echo "  Skipping $secret_id (already marked for deletion: $status)" >&2
    echo "{}"
    return
  fi
  aws secretsmanager get-secret-value \
    --secret-id "$secret_id" --region "$REGION" --query 'SecretString' --output text 2>/dev/null || echo "{}"
}

TODOIST_SECRET=$(read_secret_safe "life-platform/todoist")
NOTION_SECRET=$(read_secret_safe "life-platform/notion")
DROPBOX_SECRET=$(read_secret_safe "life-platform/dropbox")

# ── Step 3: Merge all keys ───────────────────────────────────────────────────
echo ""
echo "Merging keys..."
MERGE_OUTPUT=$(python3 - <<PYTHON
import json, sys

current  = json.loads('$INGESTION_CURRENT'.replace("'", "\\'"))
api_keys = json.loads('$API_KEYS'.replace("'", "\\'"))
todoist  = json.loads('$TODOIST_SECRET'.replace("'", "\\'"))
notion   = json.loads('$NOTION_SECRET'.replace("'", "\\'"))
dropbox  = json.loads('$DROPBOX_SECRET'.replace("'", "\\'"))

merged = dict(current)
warnings = []

# todoist_api_token
val = (todoist.get("todoist_api_token") or todoist.get("api_token")
       or api_keys.get("todoist_api_token"))
if val:
    merged["todoist_api_token"] = val
    print("  + todoist_api_token", file=sys.stderr)
else:
    warnings.append("todoist_api_token NOT FOUND")

# notion keys
nkey = notion.get("notion_api_key") or notion.get("api_key") or api_keys.get("notion_api_key")
ndb  = notion.get("notion_database_id") or notion.get("database_id") or api_keys.get("notion_database_id")
if nkey:
    merged["notion_api_key"] = nkey
    print("  + notion_api_key", file=sys.stderr)
else:
    warnings.append("notion_api_key NOT FOUND")
if ndb:
    merged["notion_database_id"] = ndb
    print("  + notion_database_id", file=sys.stderr)

# dropbox keys
for key in ["dropbox_app_key", "dropbox_app_secret", "dropbox_refresh_token"]:
    val = dropbox.get(key) or api_keys.get(key)
    if val:
        merged[key] = val
        print(f"  + {key}", file=sys.stderr)
    else:
        warnings.append(f"{key} NOT FOUND")

# habitify
hab = api_keys.get("habitify_api_key")
if hab:
    merged["habitify_api_key"] = hab
    print("  + habitify_api_key", file=sys.stderr)
else:
    warnings.append("habitify_api_key NOT FOUND in api-keys bundle")

if warnings:
    print("  WARNINGS:", file=sys.stderr)
    for w in warnings:
        print(f"    - {w}", file=sys.stderr)

print(f"  Final keys: {list(merged.keys())}", file=sys.stderr)
print(json.dumps(merged))
PYTHON
)

echo ""
echo "Updating life-platform/ingestion-keys..."
aws secretsmanager put-secret-value \
  --secret-id "life-platform/ingestion-keys" \
  --region "$REGION" \
  --secret-string "$MERGE_OUTPUT"
echo "  ✅ ingestion-keys updated"

# ── Step 4: Schedule old individual secrets for deletion ─────────────────────
echo ""
echo "=== Scheduling old individual secrets for deletion (30-day recovery) ==="

for SECRET_ID in "life-platform/todoist" "life-platform/notion" "life-platform/dropbox"; do
  if aws secretsmanager describe-secret --secret-id "$SECRET_ID" --region "$REGION" &>/dev/null; then
    aws secretsmanager delete-secret \
      --secret-id "$SECRET_ID" \
      --region "$REGION" \
      --recovery-window-in-days 30
    echo "  ✅ $SECRET_ID -> scheduled deletion (~2026-04-10, saves \$0.40/mo)"
  else
    echo "  SKIP: $SECRET_ID not found (already deleted or never existed)"
  fi
done

# ── Step 5: Verify Lambda env vars ───────────────────────────────────────────
echo ""
echo "=== Verifying Lambda env vars ==="

check_lambda() {
  local FN="$1"
  local VAR="$2"
  local VAL
  VAL=$(aws lambda get-function-configuration \
    --function-name "$FN" --region "$REGION" \
    --query "Environment.Variables.${VAR}" \
    --output text 2>/dev/null || echo "None")
  if [[ "$VAL" == "life-platform/ingestion-keys" ]]; then
    echo "  ✅ $FN ($VAR) -> $VAL"
  else
    echo "  ⚠️  $FN ($VAR) -> $VAL (expected life-platform/ingestion-keys)"
  fi
}

check_lambda "todoist-data-ingestion" "SECRET_NAME"
check_lambda "notion-journal-ingestion" "NOTION_SECRET_NAME"
check_lambda "dropbox-poll" "SECRET_NAME"
check_lambda "habitify-data-ingestion" "HABITIFY_SECRET_NAME"

echo ""
echo "=== COST-B + Habitify Complete ==="
echo "Savings: ~\$1.20/month (3 secrets deleted at \$0.40/month each)"
echo "Note: life-platform/api-keys still pending permanent deletion ~2026-04-07"
