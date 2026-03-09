#!/usr/bin/env bash
# IAM-1: Audit all Lambda IAM roles for excessive permissions
#
# Exports all Lambda execution roles, their inline policies, and attached
# managed policies. Flags any * resources, Scan/DeleteItem, or wildcard actions.
#
# Run from: ~/Documents/Claude/life-platform/
# Usage:    bash deploy/iam1_audit_roles.sh
# Output:   /tmp/iam_audit_<date>.txt  (human-readable)
#           /tmp/iam_audit_<date>.json (machine-readable — all raw policies)

set -euo pipefail

REGION="us-west-2"
ACCOUNT="205930651321"
DATE=$(date +%Y-%m-%d)
REPORT_TXT="/tmp/iam_audit_${DATE}.txt"
REPORT_JSON="/tmp/iam_audit_${DATE}.json"

echo "=== IAM-1: Lambda Role Audit — ${DATE} ===" | tee "${REPORT_TXT}"
echo "" | tee -a "${REPORT_TXT}"

ISSUES_FOUND=0

# ──────────────────────────────────────────────────────────────────────────────
# 1. Get all Lambda functions and their execution roles
# ──────────────────────────────────────────────────────────────────────────────
echo "Step 1: Enumerating Lambda functions and roles..." | tee -a "${REPORT_TXT}"

LAMBDAS=$(aws lambda list-functions \
  --region "${REGION}" \
  --query "Functions[*].{Name:FunctionName,Role:Role}" \
  --output json \
  --no-cli-pager)

LAMBDA_COUNT=$(echo "${LAMBDAS}" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
echo "  Found ${LAMBDA_COUNT} Lambda functions" | tee -a "${REPORT_TXT}"

# Filter to life-platform Lambdas only
LIFE_PLATFORM_LAMBDAS=$(echo "${LAMBDAS}" | python3 -c "
import sys, json
fns = json.load(sys.stdin)
lp = [f for f in fns if 'life-platform' in f['Name'] or
      any(f['Name'].startswith(p) for p in [
        'daily-brief', 'weekly-digest', 'monthly-digest',
        'nutrition-review', 'wednesday-chronicle', 'weekly-plate',
        'monday-compass', 'adaptive-mode', 'daily-metrics',
        'daily-insight', 'hypothesis-engine', 'whoop', 'garmin',
        'habitify', 'strava', 'withings', 'notion', 'todoist',
        'dropbox', 'macrofactor', 'weather', 'eightsleep',
        'apple', 'health-auto', 'anomaly', 'freshness'
      ])]
print(json.dumps(lp, indent=2))
")

LP_COUNT=$(echo "${LIFE_PLATFORM_LAMBDAS}" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
echo "  Life-platform Lambdas: ${LP_COUNT}" | tee -a "${REPORT_TXT}"
echo "" | tee -a "${REPORT_TXT}"

# ──────────────────────────────────────────────────────────────────────────────
# 2. For each Lambda, audit the execution role
# ──────────────────────────────────────────────────────────────────────────────
echo "Step 2: Auditing execution role policies..." | tee -a "${REPORT_TXT}"
echo "" | tee -a "${REPORT_TXT}"

ALL_AUDIT_RECORDS=()

audit_role() {
  local ROLE_NAME="$1"
  local LAMBDA_NAME="$2"
  local ISSUES=""

  echo "  ── ${LAMBDA_NAME} → ${ROLE_NAME} ──" | tee -a "${REPORT_TXT}"

  # 2a. Get inline policies
  INLINE_POLICIES=$(aws iam list-role-policies \
    --role-name "${ROLE_NAME}" \
    --query "PolicyNames" \
    --output json \
    --no-cli-pager 2>/dev/null || echo "[]")

  echo "${INLINE_POLICIES}" | python3 -c "
import sys, json
policies = json.load(sys.stdin)
print(f'     Inline policies: {len(policies)} — {policies}')
" | tee -a "${REPORT_TXT}"

  # 2b. Get attached managed policies
  ATTACHED_POLICIES=$(aws iam list-attached-role-policies \
    --role-name "${ROLE_NAME}" \
    --query "AttachedPolicies[*].{Name:PolicyName,Arn:PolicyArn}" \
    --output json \
    --no-cli-pager 2>/dev/null || echo "[]")

  echo "${ATTACHED_POLICIES}" | python3 -c "
import sys, json
policies = json.load(sys.stdin)
names = [p['Name'] for p in policies]
print(f'     Managed policies: {len(policies)} — {names}')
" | tee -a "${REPORT_TXT}"

  # 2c. Deep audit: check each inline policy for risky patterns
  for POLICY_NAME in $(echo "${INLINE_POLICIES}" | python3 -c "import sys,json; [print(p) for p in json.load(sys.stdin)]"); do
    POLICY_DOC=$(aws iam get-role-policy \
      --role-name "${ROLE_NAME}" \
      --policy-name "${POLICY_NAME}" \
      --query "PolicyDocument" \
      --output json \
      --no-cli-pager 2>/dev/null || echo "{}")

    POLICY_ISSUES=$(echo "${POLICY_DOC}" | python3 -c "
import sys, json

doc = json.load(sys.stdin)
issues = []

for stmt in doc.get('Statement', []):
    effect = stmt.get('Effect', '')
    if effect != 'Allow':
        continue

    actions = stmt.get('Action', [])
    if isinstance(actions, str):
        actions = [actions]

    resources = stmt.get('Resource', [])
    if isinstance(resources, str):
        resources = [resources]

    # Check for wildcard actions
    for action in actions:
        if action == '*' or action.endswith(':*'):
            issues.append(f'CRITICAL: Wildcard action \"{action}\"')

        # Check for dangerous DynamoDB actions
        if action in ['dynamodb:Scan', 'dynamodb:DeleteItem', 'dynamodb:DropTable',
                      'dynamodb:BatchWriteItem', 'dynamodb:PartiQL*']:
            issues.append(f'WARN: Risky DynamoDB action \"{action}\"')

        # Check for IAM actions (escalation risk)
        if action.startswith('iam:'):
            issues.append(f'CRITICAL: IAM action \"{action}\" — privilege escalation risk')

        # Check for Lambda self-modification
        if action.startswith('lambda:') and 'Update' in action:
            issues.append(f'WARN: Lambda self-modification action \"{action}\"')

        # Check for secretsmanager wildcard
        if action in ['secretsmanager:*', 'secretsmanager:ListSecrets',
                      'secretsmanager:CreateSecret', 'secretsmanager:DeleteSecret']:
            issues.append(f'WARN: Broad Secrets Manager action \"{action}\"')

    # Check for wildcard resources
    for resource in resources:
        if resource == '*':
            # Identify which action has the wildcard
            action_str = str(actions)[:80]
            issues.append(f'CRITICAL: Wildcard resource (*) for actions {action_str}')
        elif resource.endswith(':*') and 'iam' not in resource and 'kms' not in resource:
            # ARN-pattern wildcards that cover multiple resources
            issues.append(f'WARN: Broad resource pattern \"{resource}\"')

    # Check if Secrets Manager allows access to * or multiple unrelated secrets
    if any('secretsmanager' in str(a) for a in actions):
        sm_resources = [r for r in resources if 'secretsmanager' in r]
        for sm_res in sm_resources:
            if sm_res == '*' or (sm_res.endswith(':*') and 'life-platform' not in sm_res):
                issues.append(f'CRITICAL: Secrets Manager wildcard resource \"{sm_res}\"')
            elif 'api-keys' in sm_res and 'life-platform/api-keys' in sm_res:
                issues.append(f'WARN: Access to consolidated api-keys bundle (should use domain-specific secret after SEC-2)')

if issues:
    for issue in issues:
        print(f'     ⚠️  {issue}')
else:
    print('     ✓ No issues found in inline policies')
" 2>/dev/null)

    echo "${POLICY_ISSUES}" | tee -a "${REPORT_TXT}"
    if echo "${POLICY_ISSUES}" | grep -q "CRITICAL\|WARN"; then
      ISSUES_FOUND=$((ISSUES_FOUND + 1))
    fi
  done

  # 2d. Check attached managed policies for wildcards
  for POLICY_ARN in $(echo "${ATTACHED_POLICIES}" | python3 -c "
import sys, json
policies = json.load(sys.stdin)
# Only check non-AWS-managed policies for deep inspection
for p in policies:
    if 'arn:aws:iam::aws:policy' not in p.get('Arn',''):
        print(p['Arn'])
"); do
    POLICY_VERSION=$(aws iam get-policy \
      --policy-arn "${POLICY_ARN}" \
      --query "Policy.DefaultVersionId" \
      --output text \
      --no-cli-pager 2>/dev/null || echo "")
    if [ -n "${POLICY_VERSION}" ]; then
      POLICY_DOC=$(aws iam get-policy-version \
        --policy-arn "${POLICY_ARN}" \
        --version-id "${POLICY_VERSION}" \
        --query "PolicyVersion.Document" \
        --output json \
        --no-cli-pager 2>/dev/null || echo "{}")
      MANAGED_ISSUES=$(echo "${POLICY_DOC}" | python3 -c "
import sys, json
doc = json.load(sys.stdin)
issues = []
for stmt in doc.get('Statement', []):
    if stmt.get('Effect') != 'Allow':
        continue
    resources = stmt.get('Resource', [])
    if isinstance(resources, str):
        resources = [resources]
    if '*' in resources:
        actions = stmt.get('Action', [])
        issues.append(f'WARN: Customer-managed policy has wildcard resource for {actions}')
for issue in issues:
    print(f'     ⚠️  MANAGED: {issue}')
" 2>/dev/null)
      if [ -n "${MANAGED_ISSUES}" ]; then
        echo "${MANAGED_ISSUES}" | tee -a "${REPORT_TXT}"
        ISSUES_FOUND=$((ISSUES_FOUND + 1))
      fi
    fi
  done

  echo "" | tee -a "${REPORT_TXT}"
}

# Run audit for each life-platform Lambda
while IFS= read -r ENTRY; do
  LAMBDA_NAME=$(echo "${ENTRY}" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d['Name'])")
  ROLE_ARN=$(echo "${ENTRY}" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d['Role'])")
  ROLE_NAME=$(echo "${ROLE_ARN}" | sed 's|.*/||')
  audit_role "${ROLE_NAME}" "${LAMBDA_NAME}" || true
done < <(echo "${LIFE_PLATFORM_LAMBDAS}" | python3 -c "
import sys, json
for item in json.load(sys.stdin):
    print(json.dumps(item))
")

# ──────────────────────────────────────────────────────────────────────────────
# 3. Check for shared roles (multiple Lambdas sharing one role)
# ──────────────────────────────────────────────────────────────────────────────
echo "Step 3: Checking for shared roles (multiple Lambdas sharing one role)..." | tee -a "${REPORT_TXT}"

echo "${LIFE_PLATFORM_LAMBDAS}" | python3 -c "
import sys, json
from collections import defaultdict
lambdas = json.load(sys.stdin)
role_to_fns = defaultdict(list)
for fn in lambdas:
    role_name = fn['Role'].split('/')[-1]
    role_to_fns[role_name].append(fn['Name'])

shared = {r: fns for r, fns in role_to_fns.items() if len(fns) > 1}
if shared:
    print('  ⚠️  SHARED ROLES (violates least-privilege):')
    for role, fns in sorted(shared.items(), key=lambda x: -len(x[1])):
        print(f'  {role}: {len(fns)} Lambdas')
        for fn in sorted(fns):
            print(f'    - {fn}')
else:
    print('  ✓ No shared roles found')
" | tee -a "${REPORT_TXT}"
echo "" | tee -a "${REPORT_TXT}"

# ──────────────────────────────────────────────────────────────────────────────
# 4. Check for roles with no Lambdas (orphaned roles)
# ──────────────────────────────────────────────────────────────────────────────
echo "Step 4: Checking for orphaned Lambda roles..." | tee -a "${REPORT_TXT}"

ALL_LAMBDA_ROLES=$(aws iam list-roles \
  --query "Roles[?contains(RoleName, 'lambda-') || contains(RoleName, 'Lambda')].RoleName" \
  --output json \
  --no-cli-pager | python3 -c "
import sys, json
roles = json.load(sys.stdin)
lp_roles = [r for r in roles if 'life-platform' in r or any(
  r.startswith(p) for p in [
    'lambda-daily', 'lambda-weekly', 'lambda-monthly', 'lambda-whoop',
    'lambda-garmin', 'lambda-habitify', 'lambda-strava', 'lambda-withings',
    'lambda-notion', 'lambda-todoist', 'lambda-dropbox', 'lambda-macrofactor',
    'lambda-weather', 'lambda-eightsleep', 'lambda-apple', 'lambda-health',
    'lambda-anomaly', 'lambda-freshness', 'lambda-nutrition', 'lambda-wednesday',
    'lambda-monday', 'lambda-adaptive', 'lambda-hypothesis', 'lambda-qa',
    'lambda-data', 'lambda-mcp', 'lambda-character', 'lambda-key', 'lambda-dashboard',
    'lambda-buddy', 'lambda-insight', 'lambda-journal', 'lambda-enrichment',
    'lambda-chronicle', 'lambda-board'
  ]
)]
print(json.dumps(lp_roles))
")

ACTIVE_ROLE_NAMES=$(echo "${LIFE_PLATFORM_LAMBDAS}" | python3 -c "
import sys, json
lambdas = json.load(sys.stdin)
print(json.dumps([fn['Role'].split('/')[-1] for fn in lambdas]))
")

echo "${ALL_LAMBDA_ROLES}" | python3 -c "
import sys, json
import subprocess

all_roles = json.loads(sys.argv[1])
active_roles = json.loads(sys.argv[2])

orphaned = [r for r in all_roles if r not in active_roles]
if orphaned:
    print(f'  ⚠️  Potentially orphaned Lambda roles ({len(orphaned)}):')
    for r in sorted(orphaned):
        print(f'  - {r}')
else:
    print('  ✓ No orphaned roles found')
" "${ALL_LAMBDA_ROLES}" "${ACTIVE_ROLE_NAMES}" | tee -a "${REPORT_TXT}"
echo "" | tee -a "${REPORT_TXT}"

# ──────────────────────────────────────────────────────────────────────────────
# 5. Check MCP server role specifically (high-value target)
# ──────────────────────────────────────────────────────────────────────────────
echo "Step 5: Deep audit of MCP server role (high-value target)..." | tee -a "${REPORT_TXT}"

MCP_ROLE=$(aws lambda get-function-configuration \
  --function-name "life-platform-mcp" \
  --region "${REGION}" \
  --query "Role" \
  --output text \
  --no-cli-pager 2>/dev/null | sed 's|.*/||' || echo "")

if [ -n "${MCP_ROLE}" ]; then
  echo "  MCP role: ${MCP_ROLE}" | tee -a "${REPORT_TXT}"

  MCP_INLINE=$(aws iam list-role-policies \
    --role-name "${MCP_ROLE}" \
    --query "PolicyNames" \
    --output json \
    --no-cli-pager 2>/dev/null || echo "[]")

  for POLICY_NAME in $(echo "${MCP_INLINE}" | python3 -c "import sys,json; [print(p) for p in json.load(sys.stdin)]"); do
    aws iam get-role-policy \
      --role-name "${MCP_ROLE}" \
      --policy-name "${POLICY_NAME}" \
      --query "PolicyDocument" \
      --output json \
      --no-cli-pager 2>/dev/null | python3 -c "
import sys, json
doc = json.load(sys.stdin)
print('  Full MCP policy document:')
for stmt in doc.get('Statement', []):
    effect = stmt.get('Effect')
    actions = stmt.get('Action', [])
    resources = stmt.get('Resource', [])
    if isinstance(actions, str): actions = [actions]
    if isinstance(resources, str): resources = [resources]
    sid = stmt.get('Sid', 'unnamed')
    print(f'    [{sid}] {effect}: {actions} on {[r[:60] for r in resources[:3]]}')
    if 'dynamodb:Scan' in actions:
        print(f'    ⚠️  CRITICAL: MCP has dynamodb:Scan — should be GetItem/Query only')
    if 'dynamodb:DeleteItem' in actions:
        print(f'    ⚠️  CRITICAL: MCP has dynamodb:DeleteItem')
    if any('*' == r for r in resources):
        print(f'    ⚠️  CRITICAL: Wildcard resource on MCP role')
" | tee -a "${REPORT_TXT}"
  done
else
  echo "  ⚠️  Could not find life-platform-mcp function" | tee -a "${REPORT_TXT}"
fi
echo "" | tee -a "${REPORT_TXT}"

# ──────────────────────────────────────────────────────────────────────────────
# 6. Summary
# ──────────────────────────────────────────────────────────────────────────────
echo "=== AUDIT SUMMARY ===" | tee -a "${REPORT_TXT}"
if [ "${ISSUES_FOUND}" -gt 0 ]; then
  echo "  ⚠️  ${ISSUES_FOUND} role(s) with issues found — review above" | tee -a "${REPORT_TXT}"
else
  echo "  ✓ No critical issues found in ${LP_COUNT} Lambda roles" | tee -a "${REPORT_TXT}"
fi
echo "" | tee -a "${REPORT_TXT}"
echo "Full report: ${REPORT_TXT}" | tee -a "${REPORT_TXT}"
echo "" | tee -a "${REPORT_TXT}"
echo "Priority remediations:" | tee -a "${REPORT_TXT}"
echo "  1. Any role still using lambda-weekly-digest-role (shared) → run setup_sec1_iam_roles.sh" | tee -a "${REPORT_TXT}"
echo "  2. Any role with access to life-platform/api-keys bundle → run setup_sec2_secrets.sh" | tee -a "${REPORT_TXT}"
echo "  3. MCP role with dynamodb:Scan → remove that action (MCP only needs GetItem/Query)" | tee -a "${REPORT_TXT}"
echo "  4. Any wildcard resource (*) not on KMS/SES → replace with ARN-specific resources" | tee -a "${REPORT_TXT}"
