#!/bin/bash
# generate_review_bundle.sh — Generates a timestamped snapshot for architecture review
# Usage: bash deploy/generate_review_bundle.sh

set -e
DATE=$(date +%Y-%m-%d)
BUNDLE="review_bundle_${DATE}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Generating review bundle: ${BUNDLE}/"
mkdir -p "${PROJECT_ROOT}/${BUNDLE}"

# 1. Core docs
echo "  Copying documentation..."
for doc in ARCHITECTURE SCHEMA PROJECT_PLAN INFRASTRUCTURE RUNBOOK INCIDENT_LOG COST_TRACKER CHANGELOG; do
  [ -f "${PROJECT_ROOT}/docs/${doc}.md" ] && cp "${PROJECT_ROOT}/docs/${doc}.md" "${PROJECT_ROOT}/${BUNDLE}/"
done

# 2. Code inventory
echo "  Generating code inventory..."
ls -la "${PROJECT_ROOT}/lambdas/"*.py 2>/dev/null > "${PROJECT_ROOT}/${BUNDLE}/lambdas_listing.txt" || true
ls -la "${PROJECT_ROOT}/deploy/" > "${PROJECT_ROOT}/${BUNDLE}/deploy_listing.txt"
ls -la "${PROJECT_ROOT}/mcp/" > "${PROJECT_ROOT}/${BUNDLE}/mcp_listing.txt"
wc -l "${PROJECT_ROOT}/lambdas/"*.py 2>/dev/null | tail -1 > "${PROJECT_ROOT}/${BUNDLE}/lambda_line_counts.txt" || true
wc -l "${PROJECT_ROOT}/mcp/"*.py 2>/dev/null | tail -1 >> "${PROJECT_ROOT}/${BUNDLE}/lambda_line_counts.txt" || true

# 3. Code samples (first 80 lines of key files)
echo "  Sampling source code..."
head -80 "${PROJECT_ROOT}/mcp/handler.py" > "${PROJECT_ROOT}/${BUNDLE}/sample_handler.py" 2>/dev/null || true
head -80 "${PROJECT_ROOT}/lambdas/daily_brief_lambda.py" > "${PROJECT_ROOT}/${BUNDLE}/sample_daily_brief.py" 2>/dev/null || true
head -80 "${PROJECT_ROOT}/lambdas/whoop_lambda.py" > "${PROJECT_ROOT}/${BUNDLE}/sample_whoop.py" 2>/dev/null || true

# 4. AWS state snapshot
echo "  Capturing AWS state..."
aws iam list-roles --query 'Roles[?starts_with(RoleName,`lambda-`)].RoleName' --output json \
  > "${PROJECT_ROOT}/${BUNDLE}/iam_roles.json" 2>/dev/null || echo "[] # IAM query failed" > "${PROJECT_ROOT}/${BUNDLE}/iam_roles.json"

aws lambda list-functions --region us-west-2 \
  --query 'Functions[].{Name:FunctionName,Role:Role,Memory:MemorySize,Runtime:Runtime,Timeout:Timeout}' \
  --output json > "${PROJECT_ROOT}/${BUNDLE}/lambda_inventory.json" 2>/dev/null || echo "[] # Lambda query failed" > "${PROJECT_ROOT}/${BUNDLE}/lambda_inventory.json"

aws cloudwatch describe-alarms --region us-west-2 \
  --query 'MetricAlarms[].{Name:AlarmName,State:StateValue}' \
  --output json > "${PROJECT_ROOT}/${BUNDLE}/alarm_states.json" 2>/dev/null || echo "[] # Alarm query failed" > "${PROJECT_ROOT}/${BUNDLE}/alarm_states.json"

aws secretsmanager list-secrets --region us-west-2 \
  --query 'SecretList[].Name' \
  --output json > "${PROJECT_ROOT}/${BUNDLE}/secrets_list.json" 2>/dev/null || echo "[] # Secrets query failed" > "${PROJECT_ROOT}/${BUNDLE}/secrets_list.json"

aws dynamodb describe-table --table-name life-platform --region us-west-2 \
  --query 'Table.{ItemCount:ItemCount,TableSizeBytes:TableSizeBytes,Status:TableStatus}' \
  --output json > "${PROJECT_ROOT}/${BUNDLE}/dynamodb_stats.json" 2>/dev/null || echo "{} # DDB query failed" > "${PROJECT_ROOT}/${BUNDLE}/dynamodb_stats.json"

# 5. Git stats
echo "  Capturing git stats..."
cd "${PROJECT_ROOT}"
git log --oneline -20 > "${BUNDLE}/git_recent_commits.txt" 2>/dev/null || true
git shortlog -sn --since="30 days ago" > "${BUNDLE}/git_contributors_30d.txt" 2>/dev/null || true

echo ""
echo "Review bundle ready: ${PROJECT_ROOT}/${BUNDLE}/"
echo "Files:"
ls -la "${PROJECT_ROOT}/${BUNDLE}/"
echo ""
echo "Next: Open a Claude session and use docs/REVIEW_METHODOLOGY.md prompt template."
