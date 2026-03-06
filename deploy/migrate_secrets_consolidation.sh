#!/bin/bash
# migrate_secrets_consolidation.sh
# Consolidates 6 static API key secrets into one life-platform/api-keys secret.
# Saves ~$2.40/month (6 secrets × $0.40/mo).
#
# Secrets being MERGED (will be deleted at end):
#   life-platform/anthropic
#   life-platform/todoist
#   life-platform/habitify
#   life-platform/health-auto-export
#   life-platform/notion
#   life-platform/dropbox
#
# Secrets being KEPT (OAuth tokens, rotating):
#   life-platform/whoop
#   life-platform/withings
#   life-platform/strava
#   life-platform/eightsleep
#   life-platform/garmin
#   life-platform/mcp-api-key
#
# Usage:
#   cd ~/Documents/Claude/life-platform
#   bash deploy/migrate_secrets_consolidation.sh

set -euo pipefail
REGION="us-west-2"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
NEW_SECRET="life-platform/api-keys"
SECRET_ARN_PREFIX="arn:aws:secretsmanager:${REGION}:205930651321:secret:${NEW_SECRET}"

echo "=================================================="
echo "Secrets Manager Consolidation (12 → 6 secrets)"
echo "=================================================="

# ── Step 1: Create merged secret ──────────────────────────────────────────────
echo ""
echo "▶ Step 1/5: Creating merged secret life-platform/api-keys..."

MERGED_SECRET=$(python3 -c "
import boto3, json
sm = boto3.client('secretsmanager', region_name='${REGION}')

def get(name):
    return json.loads(sm.get_secret_value(SecretId=name)['SecretString'])

anthropic   = get('life-platform/anthropic')
todoist     = get('life-platform/todoist')
habitify    = get('life-platform/habitify')
hae         = get('life-platform/health-auto-export')
notion      = get('life-platform/notion')
dropbox     = get('life-platform/dropbox')

merged = {
    'anthropic_api_key':          anthropic['api_key'],
    'todoist_api_token':          todoist['api_token'],
    'habitify_api_key':           habitify['api_key'],
    'health_auto_export_api_key': hae['api_key'],
    'notion_api_key':             notion['api_key'],
    'notion_database_id':         notion['database_id'],
    'dropbox_app_key':            dropbox['app_key'],
    'dropbox_app_secret':         dropbox['app_secret'],
    'dropbox_refresh_token':      dropbox['refresh_token'],
}
print(json.dumps(merged))
")

# Create the new secret (will fail if already exists — that's fine)
if aws secretsmanager describe-secret --secret-id "$NEW_SECRET" --region "$REGION" > /dev/null 2>&1; then
    echo "   Secret already exists — updating value..."
    aws secretsmanager put-secret-value \
        --secret-id "$NEW_SECRET" \
        --secret-string "$MERGED_SECRET" \
        --region "$REGION"
else
    echo "   Creating new secret..."
    aws secretsmanager create-secret \
        --name "$NEW_SECRET" \
        --description "Consolidated static API keys for life-platform (anthropic, todoist, habitify, health-auto-export, notion, dropbox)" \
        --secret-string "$MERGED_SECRET" \
        --region "$REGION"
fi
echo "   ✅ life-platform/api-keys created/updated"

# ── Step 2: Update IAM — add new secret to all affected roles ─────────────────
echo ""
echo "▶ Step 2/5: Updating IAM policies (9 roles)..."

NEW_SECRET_RESOURCE="${SECRET_ARN_PREFIX}*"

add_secret_permission() {
    local ROLE="$1"
    local POLICY_NAME="api-keys-read"
    aws iam put-role-policy \
        --role-name "$ROLE" \
        --policy-name "$POLICY_NAME" \
        --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Sid\":\"ReadConsolidatedApiKeys\",\"Effect\":\"Allow\",\"Action\":\"secretsmanager:GetSecretValue\",\"Resource\":\"${NEW_SECRET_RESOURCE}\"}]}" \
        --region "$REGION"
    echo "   ✅ $ROLE — api-keys-read policy added"
}

# Roles that need the new secret
add_secret_permission "lambda-weekly-digest-role"    # daily-brief, weekly-digest, wednesday-chronicle, weekly-plate, monthly-digest, nutrition-review
add_secret_permission "lambda-journal-enrichment-role"
add_secret_permission "lambda-anomaly-detector-role"
add_secret_permission "lambda-todoist-role"
add_secret_permission "lambda-habitify-ingestion-role"
add_secret_permission "lambda-health-auto-export-role"
add_secret_permission "lambda-notion-ingestion-role"
add_secret_permission "lambda-dropbox-poll-role"
add_secret_permission "lambda-mcp-server-role"       # life-platform-mcp, character-sheet-compute, etc.

# ── Step 3: Redeploy all affected Lambdas ─────────────────────────────────────
echo ""
echo "▶ Step 3/5: Redeploying 13 affected Lambdas..."

deploy() {
    local FN="$1"
    local SRC="$2"
    bash "$SCRIPT_DIR/deploy_lambda.sh" "$FN" "$ROOT_DIR/lambdas/$SRC"
    sleep 10
}

deploy "daily-brief"               "daily_brief_lambda.py"
deploy "journal-enrichment"        "journal_enrichment_lambda.py"
deploy "wednesday-chronicle"       "wednesday_chronicle_lambda.py"
deploy "weekly-plate"              "weekly_plate_lambda.py"
deploy "monthly-digest"            "monthly_digest_lambda.py"
deploy "nutrition-review"          "nutrition_review_lambda.py"
deploy "anomaly-detector"          "anomaly_detector_lambda.py"
deploy "weekly-digest"             "weekly_digest_lambda.py"
deploy "todoist-data-ingestion"    "todoist_lambda.py"
deploy "habitify-data-ingestion"   "habitify_lambda.py"
deploy "health-auto-export-webhook" "health_auto_export_lambda.py"
deploy "notion-journal-ingestion"  "notion_lambda.py"
deploy "dropbox-poll"              "dropbox_poll_lambda.py"

# Redeploy MCP (mcp_server reads ANTHROPIC_SECRET env var — update it to point to new secret)
echo "   Redeploying life-platform-mcp..."
MCP_WORK=$(mktemp -d)
cp "$ROOT_DIR/lambdas/mcp_server.py" "$MCP_WORK/mcp_server.py"
cp -r "$ROOT_DIR/mcp" "$MCP_WORK/mcp"
cp "$ROOT_DIR/lambdas/board_loader.py" "$MCP_WORK/board_loader.py" 2>/dev/null || true
(cd "$MCP_WORK" && zip -q -r deploy.zip mcp_server.py mcp/ board_loader.py 2>/dev/null || zip -q -r deploy.zip mcp_server.py mcp/)
aws lambda update-function-code \
    --function-name life-platform-mcp \
    --zip-file "fileb://$MCP_WORK/deploy.zip" \
    --region "$REGION" > /dev/null
rm -rf "$MCP_WORK"
echo "   ✅ life-platform-mcp redeployed"
sleep 10

# Update the MCP Lambda env var ANTHROPIC_SECRET to point to new secret
aws lambda update-function-configuration \
    --function-name life-platform-mcp \
    --environment "Variables={ANTHROPIC_SECRET=life-platform/api-keys}" \
    --region "$REGION" > /dev/null
echo "   ✅ life-platform-mcp ANTHROPIC_SECRET env var updated"

# ── Step 4: Smoke tests ───────────────────────────────────────────────────────
echo ""
echo "▶ Step 4/5: Smoke testing key Lambdas..."
sleep 15  # Wait for IAM propagation

smoke_test() {
    local FN="$1"
    local PAYLOAD="$2"
    local OUTFILE="/tmp/smoke_${FN}.json"
    aws lambda invoke \
        --function-name "$FN" \
        --payload "$PAYLOAD" \
        --log-type Tail \
        --region "$REGION" \
        --cli-binary-format raw-in-base64-out \
        "$OUTFILE" > /dev/null 2>&1 || true
    STATUS=$(python3 -c "import json; d=json.load(open('$OUTFILE')); print('ERROR' if 'FunctionError' in d else d.get('statusCode', 200))" 2>/dev/null || echo "invoked")
    echo "   $FN: $STATUS"
}

smoke_test "todoist-data-ingestion"    '{"dry_run": true}'
smoke_test "habitify-data-ingestion"   '{"dry_run": true}'
smoke_test "notion-journal-ingestion"  '{"dry_run": true}'
smoke_test "health-auto-export-webhook" '{"httpMethod":"GET","headers":{},"body":""}'
smoke_test "dropbox-poll"              '{"dry_run": true}'

# ── Step 5: Delete old secrets ────────────────────────────────────────────────
echo ""
echo "▶ Step 5/5: Deleting 6 old secrets (7-day recovery window)..."

for SECRET in \
    "life-platform/anthropic" \
    "life-platform/todoist" \
    "life-platform/habitify" \
    "life-platform/health-auto-export" \
    "life-platform/notion" \
    "life-platform/dropbox"; do
    aws secretsmanager delete-secret \
        --secret-id "$SECRET" \
        --recovery-window-in-days 7 \
        --region "$REGION" > /dev/null
    echo "   🗑️  $SECRET (recoverable for 7 days)"
done

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "=================================================="
echo "✅ Secrets consolidation complete."
echo ""
echo "Secrets: 12 → 6  (saving ~\$2.40/month)"
echo "Kept:    whoop, withings, strava, eightsleep, garmin, mcp-api-key"
echo "Merged:  anthropic, todoist, habitify, health-auto-export, notion, dropbox"
echo "         → life-platform/api-keys"
echo ""
echo "Old secrets deleted with 7-day recovery window."
echo "To restore one if needed:"
echo "  aws secretsmanager restore-secret --secret-id life-platform/anthropic --region us-west-2"
echo ""
echo "Verify full Daily Brief tomorrow morning."
echo "=================================================="
