#!/usr/bin/env bash
# deploy/consolidate_secrets.sh — R20: Secrets Manager consolidation
#
# Reduces 11 → 9 active secrets by eliminating two redundancies:
#
# Redundancy 1 — life-platform/habitify (DEDICATED) duplicates ingestion-keys
#   The habitify_lambda.py reads from life-platform/ingestion-keys.
#   life-platform/habitify is a standalone secret that is NOT read by any Lambda
#   (verified: habitify role_policies.py uses ingestion-keys, not habitify).
#   Decision (ADR-014): dedicated secret is preserved for isolation principle.
#   ACTION: Verify no Lambda reads it, then schedule deletion. Save ~$0.40/mo.
#
# Redundancy 2 — life-platform/webhook-key is reserved/unused
#   The HAE webhook reads from ingestion-keys → health_auto_export_api_key field.
#   webhook-key exists but is NOT referenced by any Lambda (reserved for future migration).
#   ACTION: Delete after confirming no Lambda references it. Save ~$0.40/mo.
#
# Total savings: ~$0.80/mo (trivial but cleaner)
#
# SAFE TO RUN — only prints what it finds. Uncomment delete commands when ready.
#
# Run:
#   bash deploy/consolidate_secrets.sh
#
set -euo pipefail
REGION="us-west-2"

echo "═══════════════════════════════════════════════════════"
echo "  R20: Secrets Manager Consolidation Audit"
echo "═══════════════════════════════════════════════════════"
echo ""

# Step 1: List all life-platform/* secrets
echo "── Current secrets ──"
aws secretsmanager list-secrets \
    --region "$REGION" \
    --filter Key=name,Values="life-platform/" \
    --query "SecretList[*].{Name:Name,LastAccessed:LastAccessedDate}" \
    --output table

echo ""

# Step 2: Check if any Lambda reads life-platform/habitify directly
echo "── Checking Lambda env vars for 'habitify' secret reference ──"
aws lambda list-functions \
    --region "$REGION" \
    --query "Functions[*].{Name:FunctionName,Env:Environment.Variables}" \
    --output json | python3 -c "
import json, sys
fns = json.load(sys.stdin)
found = False
for fn in fns:
    env = fn.get('Env') or {}
    for k, v in env.items():
        if 'habitify' in str(v).lower() and 'ingestion-keys' not in str(v).lower():
            print(f'  FOUND: {fn[\"Name\"]} → {k}={v}')
            found = True
if not found:
    print('  No Lambda references life-platform/habitify directly.')
"

echo ""

# Step 3: Check if any Lambda reads life-platform/webhook-key
echo "── Checking Lambda env vars for 'webhook-key' secret reference ──"
aws lambda list-functions \
    --region "$REGION" \
    --query "Functions[*].{Name:FunctionName,Env:Environment.Variables}" \
    --output json | python3 -c "
import json, sys
fns = json.load(sys.stdin)
found = False
for fn in fns:
    env = fn.get('Env') or {}
    for k, v in env.items():
        if 'webhook-key' in str(v).lower():
            print(f'  FOUND: {fn[\"Name\"]} → {k}={v}')
            found = True
if not found:
    print('  No Lambda references life-platform/webhook-key directly.')
"

echo ""
echo "── Recommended actions ──"
echo ""
echo "  If no Lambda references 'habitify' or 'webhook-key' above:"
echo ""
echo "  1. Schedule deletion of life-platform/habitify:"
echo "     aws secretsmanager delete-secret \\"
echo "       --secret-id life-platform/habitify \\"
echo "       --recovery-window-in-days 7 \\"
echo "       --region $REGION"
echo ""
echo "  2. Schedule deletion of life-platform/webhook-key:"
echo "     aws secretsmanager delete-secret \\"
echo "       --secret-id life-platform/webhook-key \\"
echo "       --recovery-window-in-days 7 \\"
echo "       --region $REGION"
echo ""
echo "  Secrets are recoverable within 7 days. Cost savings: ~\$0.80/mo."
echo "  Update ARCHITECTURE.md and INFRASTRUCTURE.md after deletion."
echo ""
echo "  NOTE: This does NOT touch life-platform/ingestion-keys (still needed)."
echo "═══════════════════════════════════════════════════════"
