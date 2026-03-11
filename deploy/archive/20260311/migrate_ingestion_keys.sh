#!/usr/bin/env bash
# deploy/migrate_ingestion_keys.sh
# COST-B: Bundle life-platform/{todoist,notion,dropbox,habitify} into
#         life-platform/ingestion-keys. Saves $1.20/month (3 secrets eliminated).
#
# Usage: bash deploy/migrate_ingestion_keys.sh
#
# Steps:
#   1. Read existing secrets
#   2. Create life-platform/ingestion-keys bundle
#   3. Verify read-back
#   (CDK deploy + old secret deletion handled separately)

set -euo pipefail
REGION="us-west-2"

echo "=== COST-B: Ingestion Keys Bundle Migration ==="
echo "Region: $REGION"
echo ""

# ── Step 1: Read existing secrets ──────────────────────────────────────────
echo "Reading existing secrets..."

TODOIST=$(aws secretsmanager get-secret-value \
  --secret-id "life-platform/todoist" \
  --region "$REGION" \
  --query SecretString --output text)

NOTION=$(aws secretsmanager get-secret-value \
  --secret-id "life-platform/notion" \
  --region "$REGION" \
  --query SecretString --output text)

DROPBOX=$(aws secretsmanager get-secret-value \
  --secret-id "life-platform/dropbox" \
  --region "$REGION" \
  --query SecretString --output text)

HABITIFY=$(aws secretsmanager get-secret-value \
  --secret-id "life-platform/habitify" \
  --region "$REGION" \
  --query SecretString --output text)

echo "  life-platform/todoist   [OK]"
echo "  life-platform/notion    [OK]"
echo "  life-platform/dropbox   [OK]"
echo "  life-platform/habitify  [OK]"
echo ""

# ── Step 2: Merge into one JSON bundle ─────────────────────────────────────
echo "Building bundle..."

BUNDLE=$(python3 - <<PYEOF
import json, sys

todoist  = json.loads('''$TODOIST''')
notion   = json.loads('''$NOTION''')
dropbox  = json.loads('''$DROPBOX''')
habitify = json.loads('''$HABITIFY''')

bundle = {}

# Todoist — canonical key: todoist_api_token
bundle["todoist_api_token"] = (
    todoist.get("todoist_api_token") or todoist.get("api_token")
)

# Notion — canonical keys: notion_api_key, notion_database_id
bundle["notion_api_key"]     = notion.get("notion_api_key")     or notion.get("api_key")
bundle["notion_database_id"] = notion.get("notion_database_id") or notion.get("database_id")

# Dropbox — canonical keys already prefixed in secret
bundle["dropbox_app_key"]      = dropbox.get("dropbox_app_key")
bundle["dropbox_app_secret"]   = dropbox.get("dropbox_app_secret")
bundle["dropbox_refresh_token"] = dropbox.get("dropbox_refresh_token")

# Habitify — canonical key: habitify_api_key
bundle["habitify_api_key"] = (
    habitify.get("habitify_api_key") or habitify.get("api_key")
)

# Validate nothing is None
for k, v in bundle.items():
    if v is None:
        print(f"ERROR: {k} is None — check source secret", file=sys.stderr)
        sys.exit(1)

print(json.dumps(bundle))
PYEOF
)

if [[ -z "$BUNDLE" ]]; then
  echo "ERROR: Bundle is empty — aborting."
  exit 1
fi

echo "  Keys bundled:"
echo "$BUNDLE" | python3 -c "
import json, sys
b = json.load(sys.stdin)
for k in b:
    print(f'    {k}: {\"*\" * 6}...{str(b[k])[-4:] if b[k] else \"[EMPTY]\"}')
"
echo ""

# ── Step 3: Create the new secret ──────────────────────────────────────────
echo "Creating life-platform/ingestion-keys..."

# Check if it already exists
EXISTS=$(aws secretsmanager describe-secret \
  --secret-id "life-platform/ingestion-keys" \
  --region "$REGION" \
  --query Name --output text 2>/dev/null || echo "NOT_FOUND")

if [[ "$EXISTS" == "NOT_FOUND" ]]; then
  aws secretsmanager create-secret \
    --name "life-platform/ingestion-keys" \
    --description "Bundled static API keys: todoist, notion, dropbox, habitify. Non-OAuth, non-rotating. See ADR-014 + COST-B 2026-03-10." \
    --secret-string "$BUNDLE" \
    --region "$REGION"
  echo "  Created: life-platform/ingestion-keys"
else
  aws secretsmanager put-secret-value \
    --secret-id "life-platform/ingestion-keys" \
    --secret-string "$BUNDLE" \
    --region "$REGION"
  echo "  Updated: life-platform/ingestion-keys (already existed)"
fi

# ── Step 4: Verify read-back ────────────────────────────────────────────────
echo ""
echo "Verifying read-back..."
VERIFY=$(aws secretsmanager get-secret-value \
  --secret-id "life-platform/ingestion-keys" \
  --region "$REGION" \
  --query SecretString --output text)

python3 -c "
import json
b = json.loads('$VERIFY'.replace(\"'\", \"'\"))
required = ['todoist_api_token','notion_api_key','notion_database_id',
            'dropbox_app_key','dropbox_app_secret','dropbox_refresh_token',
            'habitify_api_key']
ok = True
for k in required:
    if k in b and b[k]:
        print(f'  [OK]    {k}')
    else:
        print(f'  [FAIL]  {k} — MISSING OR EMPTY')
        ok = False
if not ok:
    exit(1)
"

echo ""
echo "=== Bundle created successfully ==="
echo ""
echo "Next steps:"
echo "  1. cd cdk && cdk deploy LifePlatformIngestion   (updates IAM + env vars)"
echo "  2. Verify Lambda invocations in CloudWatch (wait for next ingestion run or trigger manually)"
echo "  3. bash deploy/delete_old_ingestion_secrets.sh  (deletes the 4 individual secrets)"
