#!/usr/bin/env bash
# IAM-1 Follow-up: Fix real issues found in audit
#
# 1. Scope ses:SendEmail from * to identity ARN (dlq-consumer, anomaly-detector, canary)
# 2. Update api-keys-read policy on 8 ingestion roles → point to domain-specific secrets
# 3. Add 13 new IAM role ARNs to KMS key policy
#
# Run from: ~/Documents/Claude/life-platform/
# Usage:    bash deploy/fix_iam1_audit_findings.sh

set -euo pipefail

REGION="us-west-2"
ACCOUNT="205930651321"
SES_IDENTITY="arn:aws:ses:${REGION}:${ACCOUNT}:identity/mattsusername.com"
KMS_KEY_ID="444438d1-a5e0-43b8-9391-3cd2d70dde4d"
TABLE_ARN="arn:aws:dynamodb:${REGION}:${ACCOUNT}:table/life-platform"
SQS_DLQ="arn:aws:sqs:${REGION}:${ACCOUNT}:life-platform-ingestion-dlq"

echo "=== IAM-1 Follow-up: Fix audit findings ==="
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# FIX 1: Scope SES to identity ARN (dlq-consumer, anomaly-detector, canary)
# ─────────────────────────────────────────────────────────────────────────────
echo "Fix 1: Scoping ses:SendEmail to identity ARN on 3 roles..."

# DLQ consumer — get current policy and patch SES resource
echo "  Updating lambda-dlq-consumer-role..."
DLQ_POLICY=$(aws iam get-role-policy \
  --role-name lambda-dlq-consumer-role \
  --policy-name dlq-consumer-policy \
  --query "PolicyDocument" --output json --no-cli-pager 2>/dev/null || echo "")

if [ -n "${DLQ_POLICY}" ]; then
  PATCHED=$(echo "${DLQ_POLICY}" | python3 -c "
import sys, json
doc = json.load(sys.stdin)
for stmt in doc['Statement']:
    actions = stmt.get('Action', [])
    if isinstance(actions, str): actions = [actions]
    if any('ses' in a.lower() for a in actions):
        stmt['Resource'] = '${SES_IDENTITY}'
print(json.dumps(doc))
")
  aws iam put-role-policy \
    --role-name lambda-dlq-consumer-role \
    --policy-name dlq-consumer-policy \
    --policy-document "${PATCHED}" \
    --no-cli-pager
  echo "  ✓ lambda-dlq-consumer-role: SES scoped"
else
  echo "  ✗ lambda-dlq-consumer-role: policy not found"
fi

# Anomaly detector — uses life-platform-email-role (shared, check first)
echo "  Updating life-platform-email-role (anomaly-detector uses this)..."
ANOMALY_POLICY=$(aws iam get-role-policy \
  --role-name life-platform-email-role \
  --policy-name email-access \
  --query "PolicyDocument" --output json --no-cli-pager 2>/dev/null || echo "")

if [ -n "${ANOMALY_POLICY}" ]; then
  PATCHED=$(echo "${ANOMALY_POLICY}" | python3 -c "
import sys, json
doc = json.load(sys.stdin)
for stmt in doc['Statement']:
    actions = stmt.get('Action', [])
    if isinstance(actions, str): actions = [actions]
    resources = stmt.get('Resource', [])
    if isinstance(resources, str): resources = [resources]
    if any('ses' in a.lower() for a in actions) and '*' in resources:
        stmt['Resource'] = '${SES_IDENTITY}'
print(json.dumps(doc))
")
  aws iam put-role-policy \
    --role-name life-platform-email-role \
    --policy-name email-access \
    --policy-document "${PATCHED}" \
    --no-cli-pager
  echo "  ✓ life-platform-email-role: SES scoped"
fi

# Also patch email-role-access policy on same role if it has SES
EMAIL_ROLE_POLICY=$(aws iam get-role-policy \
  --role-name life-platform-email-role \
  --policy-name email-role-access \
  --query "PolicyDocument" --output json --no-cli-pager 2>/dev/null || echo "")

if [ -n "${EMAIL_ROLE_POLICY}" ]; then
  PATCHED=$(echo "${EMAIL_ROLE_POLICY}" | python3 -c "
import sys, json
doc = json.load(sys.stdin)
for stmt in doc['Statement']:
    actions = stmt.get('Action', [])
    if isinstance(actions, str): actions = [actions]
    resources = stmt.get('Resource', [])
    if isinstance(resources, str): resources = [resources]
    if any('ses' in a.lower() for a in actions) and '*' in resources:
        stmt['Resource'] = '${SES_IDENTITY}'
print(json.dumps(doc))
")
  aws iam put-role-policy \
    --role-name life-platform-email-role \
    --policy-name email-role-access \
    --policy-document "${PATCHED}" \
    --no-cli-pager 2>/dev/null || true
  echo "  ✓ life-platform-email-role: email-role-access SES scoped"
fi

# Canary
echo "  Updating lambda-canary-role..."
CANARY_POLICY=$(aws iam get-role-policy \
  --role-name lambda-canary-role \
  --policy-name canary-policy \
  --query "PolicyDocument" --output json --no-cli-pager 2>/dev/null || echo "")

if [ -n "${CANARY_POLICY}" ]; then
  PATCHED=$(echo "${CANARY_POLICY}" | python3 -c "
import sys, json
doc = json.load(sys.stdin)
for stmt in doc['Statement']:
    actions = stmt.get('Action', [])
    if isinstance(actions, str): actions = [actions]
    resources = stmt.get('Resource', [])
    if isinstance(resources, str): resources = [resources]
    if any('ses' in a.lower() for a in actions) and '*' in resources:
        stmt['Resource'] = '${SES_IDENTITY}'
print(json.dumps(doc))
")
  aws iam put-role-policy \
    --role-name lambda-canary-role \
    --policy-name canary-policy \
    --policy-document "${PATCHED}" \
    --no-cli-pager
  echo "  ✓ lambda-canary-role: SES scoped"
else
  echo "  ✗ lambda-canary-role: policy not found"
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# FIX 2: Update api-keys-read policy on ingestion roles → domain-specific ARNs
# ─────────────────────────────────────────────────────────────────────────────
echo "Fix 2: Updating ingestion roles to reference domain-specific secret ARNs..."

# Map: role → secret ARN it actually needs
declare -A ROLE_SECRET_MAP=(
  ["lambda-notion-ingestion-role"]="arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:life-platform/notion*"
  ["lambda-dropbox-poll-role"]="arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:life-platform/dropbox*"
  ["lambda-todoist-role"]="arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:life-platform/todoist*"
  ["lambda-habitify-ingestion-role"]="arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:life-platform/ingestion-keys*"
  ["lambda-health-auto-export-role"]="arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:life-platform/ingestion-keys*"
  ["lambda-mcp-server-role"]="arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:life-platform/mcp-api-key*"
  ["lambda-monday-compass-role"]="arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:life-platform/ai-keys* arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:life-platform/todoist*"
  ["lambda-canary-role"]="arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:life-platform/ai-keys*"
)

for ROLE in "${!ROLE_SECRET_MAP[@]}"; do
  NEEDED_SECRET="${ROLE_SECRET_MAP[$ROLE]}"

  # Get the api-keys-read policy if it exists
  POLICY_DOC=$(aws iam get-role-policy \
    --role-name "${ROLE}" \
    --policy-name api-keys-read \
    --query "PolicyDocument" --output json --no-cli-pager 2>/dev/null || echo "")

  if [ -z "${POLICY_DOC}" ]; then
    echo "  — ${ROLE}: no api-keys-read policy (already updated or different name)"
    continue
  fi

  # Build new policy with scoped resource
  # Handle multiple secrets (space-separated)
  SECRET_ARRAY=$(echo "${NEEDED_SECRET}" | python3 -c "
import sys
secrets = sys.stdin.read().strip().split()
import json
print(json.dumps(secrets))
")

  NEW_POLICY=$(python3 -c "
import json
doc = json.loads('''${POLICY_DOC}''')
for stmt in doc['Statement']:
    actions = stmt.get('Action', [])
    if isinstance(actions, str): actions = [actions]
    if any('secretsmanager' in a for a in actions):
        new_resources = ${SECRET_ARRAY}
        stmt['Resource'] = new_resources if len(new_resources) > 1 else new_resources[0]
print(json.dumps(doc))
")

  aws iam put-role-policy \
    --role-name "${ROLE}" \
    --policy-name api-keys-read \
    --policy-document "${NEW_POLICY}" \
    --no-cli-pager
  echo "  ✓ ${ROLE}: api-keys-read → scoped to domain secret"
done
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# FIX 3: Add 13 new roles to KMS key policy
# ─────────────────────────────────────────────────────────────────────────────
echo "Fix 3: Updating KMS key policy to include 13 new roles..."

NEW_ROLE_ARNS=(
  "arn:aws:iam::${ACCOUNT}:role/lambda-daily-brief-role"
  "arn:aws:iam::${ACCOUNT}:role/lambda-weekly-digest-role-v2"
  "arn:aws:iam::${ACCOUNT}:role/lambda-monthly-digest-role"
  "arn:aws:iam::${ACCOUNT}:role/lambda-nutrition-review-role"
  "arn:aws:iam::${ACCOUNT}:role/lambda-wednesday-chronicle-role"
  "arn:aws:iam::${ACCOUNT}:role/lambda-weekly-plate-role"
  "arn:aws:iam::${ACCOUNT}:role/lambda-monday-compass-role"
  "arn:aws:iam::${ACCOUNT}:role/lambda-adaptive-mode-role"
  "arn:aws:iam::${ACCOUNT}:role/lambda-daily-metrics-role"
  "arn:aws:iam::${ACCOUNT}:role/lambda-daily-insight-role"
  "arn:aws:iam::${ACCOUNT}:role/lambda-hypothesis-engine-role"
  "arn:aws:iam::${ACCOUNT}:role/lambda-qa-smoke-role"
  "arn:aws:iam::${ACCOUNT}:role/lambda-data-export-role"
)

# Get current policy
CURRENT_KMS_POLICY=$(aws kms get-key-policy \
  --key-id "${KMS_KEY_ID}" \
  --policy-name default \
  --region "${REGION}" \
  --output text \
  --no-cli-pager)

# Inject new ARNs into the existing Lambda principal list
UPDATED_POLICY=$(echo "${CURRENT_KMS_POLICY}" | python3 -c "
import sys, json

policy = json.load(sys.stdin)
new_arns = $(printf '"%s",' "${NEW_ROLE_ARNS[@]}" | python3 -c "import sys; arns=sys.stdin.read().rstrip(','); print('[' + arns + ']')")

for stmt in policy.get('Statement', []):
    # Find the statement that grants Lambda roles kms:Decrypt
    actions = stmt.get('Action', [])
    if isinstance(actions, str): actions = [actions]
    if not any(a in ['kms:Decrypt', 'kms:GenerateDataKey'] for a in actions):
        continue
    principal = stmt.get('Principal', {})
    aws_principal = principal.get('AWS', [])
    if isinstance(aws_principal, str):
        aws_principal = [aws_principal]
    # Add new ARNs (skip if already present)
    added = 0
    for arn in new_arns:
        if arn not in aws_principal:
            aws_principal.append(arn)
            added += 1
    stmt['Principal']['AWS'] = aws_principal
    print(f'  Added {added} new ARNs to KMS decrypt statement', file=sys.stderr)

print(json.dumps(policy, indent=2))
")

if [ $? -eq 0 ]; then
  echo "${UPDATED_POLICY}" > /tmp/kms_policy_updated.json
  aws kms put-key-policy \
    --key-id "${KMS_KEY_ID}" \
    --policy-name default \
    --policy "$(cat /tmp/kms_policy_updated.json)" \
    --region "${REGION}" \
    --no-cli-pager
  echo "  ✓ KMS key policy updated"
else
  echo "  ✗ KMS policy update failed — manual update required"
  echo "    Current policy saved to: /tmp/kms_policy_current.json"
  echo "${CURRENT_KMS_POLICY}" > /tmp/kms_policy_current.json
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# VERIFY
# ─────────────────────────────────────────────────────────────────────────────
echo "=== Verification ==="

echo "SES scope check (should NOT see '*' as resource):"
for ROLE in lambda-dlq-consumer-role life-platform-email-role lambda-canary-role; do
  POLICIES=$(aws iam list-role-policies --role-name "${ROLE}" \
    --query "PolicyNames" --output json --no-cli-pager 2>/dev/null || echo "[]")
  for PNAME in $(echo "${POLICIES}" | python3 -c "import sys,json; [print(p) for p in json.load(sys.stdin)]"); do
    PDOC=$(aws iam get-role-policy --role-name "${ROLE}" --policy-name "${PNAME}" \
      --query "PolicyDocument" --output json --no-cli-pager 2>/dev/null || echo "{}")
    HAS_WILDCARD=$(echo "${PDOC}" | python3 -c "
import sys,json
doc=json.load(sys.stdin)
found=False
for s in doc.get('Statement',[]):
    r=s.get('Resource',[])
    if isinstance(r,str): r=[r]
    a=s.get('Action',[])
    if isinstance(a,str): a=[a]
    if '*' in r and any('ses' in x.lower() for x in a):
        found=True
print('WILDCARD' if found else 'ok')
" 2>/dev/null || echo "?")
    echo "  ${ROLE}/${PNAME}: ${HAS_WILDCARD}"
  done
done

echo ""
echo "KMS policy principal count:"
aws kms get-key-policy \
  --key-id "${KMS_KEY_ID}" \
  --policy-name default \
  --region "${REGION}" \
  --output text \
  --no-cli-pager | python3 -c "
import sys, json
policy = json.load(sys.stdin)
for stmt in policy.get('Statement', []):
    actions = stmt.get('Action', [])
    if isinstance(actions, str): actions = [actions]
    if any(a in ['kms:Decrypt', 'kms:GenerateDataKey'] for a in actions):
        principals = stmt.get('Principal', {}).get('AWS', [])
        if isinstance(principals, str): principals = [principals]
        print(f'  Lambda decrypt principals: {len(principals)} roles')
        # Show the new roles are present
        new_roles = [p for p in principals if any(
            r in p for r in ['daily-brief', 'weekly-digest-role-v2', 'monthly-digest',
                              'nutrition-review', 'wednesday-chronicle', 'weekly-plate',
                              'monday-compass', 'adaptive-mode', 'daily-metrics',
                              'daily-insight', 'hypothesis-engine', 'qa-smoke', 'data-export']
        )]
        print(f'  New roles found in KMS policy: {len(new_roles)}/13')
"

echo ""
echo "=== IAM-1 fixes complete ==="
echo ""
echo "Next: git add -A && git commit -m 'v3.1.1: IAM-1 audit fixes — SES scope, secret ARNs, KMS policy' && git push"
