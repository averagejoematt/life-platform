#!/usr/bin/env bash
# deploy/setup_p3_iam_roles.sh
# Create dedicated IAM roles for P3 Lambdas not covered by SEC-1:
#   - lambda-data-reconciliation-role  (DATA-3)
#   - lambda-pip-audit-role            (SEC-5)
#
# Run BEFORE deploy_p3_lambdas.sh.
# Usage: bash deploy/setup_p3_iam_roles.sh
# Safe to re-run — already-exists errors are skipped.

set -euo pipefail

REGION="us-west-2"
ACCOUNT="205930651321"
TABLE_ARN="arn:aws:dynamodb:us-west-2:${ACCOUNT}:table/life-platform"
BUCKET="matthew-life-platform"
KMS_KEY_ID="444438d1-a5e0-43b8-9391-3cd2d70dde4d"
SES_IDENTITY="arn:aws:ses:us-west-2:${ACCOUNT}:identity/mattsusername.com"
BASIC_EXEC="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

TRUST_POLICY='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

create_role() {
  local ROLE_NAME="$1"
  echo "  Creating role: ${ROLE_NAME}"
  aws iam create-role \
    --role-name "${ROLE_NAME}" \
    --assume-role-policy-document "${TRUST_POLICY}" \
    --region "${REGION}" \
    --no-cli-pager \
    2>/dev/null || echo "    (role already exists — skipping create)"
  aws iam attach-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-arn "${BASIC_EXEC}" \
    --no-cli-pager 2>/dev/null || true
}

put_policy() {
  local ROLE_NAME="$1"
  local POLICY_NAME="$2"
  local POLICY_DOC="$3"
  aws iam put-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-name "${POLICY_NAME}" \
    --policy-document "${POLICY_DOC}" \
    --no-cli-pager
  echo "    ✓ policy ${POLICY_NAME}"
}

echo "=== P3 IAM Roles: data-reconciliation + pip-audit ==="
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 1. lambda-data-reconciliation-role
#    Needs: DDB read (check source coverage), SES (send gap report email),
#           KMS (decrypt DDB), S3 read (config)
# ─────────────────────────────────────────────────────────────────────────────
RECON_ROLE="lambda-data-reconciliation-role"
echo "── ${RECON_ROLE}"
create_role "${RECON_ROLE}"

put_policy "${RECON_ROLE}" "recon-permissions" "{
  \"Version\": \"2012-10-17\",
  \"Statement\": [
    {
      \"Sid\": \"DDBRead\",
      \"Effect\": \"Allow\",
      \"Action\": [\"dynamodb:GetItem\", \"dynamodb:Query\"],
      \"Resource\": \"${TABLE_ARN}\"
    },
    {
      \"Sid\": \"KMSDecrypt\",
      \"Effect\": \"Allow\",
      \"Action\": [\"kms:Decrypt\", \"kms:GenerateDataKey\"],
      \"Resource\": \"arn:aws:kms:${REGION}:${ACCOUNT}:key/${KMS_KEY_ID}\"
    },
    {
      \"Sid\": \"SESEmail\",
      \"Effect\": \"Allow\",
      \"Action\": \"ses:SendEmail\",
      \"Resource\": \"${SES_IDENTITY}\"
    },
    {
      \"Sid\": \"S3ConfigRead\",
      \"Effect\": \"Allow\",
      \"Action\": \"s3:GetObject\",
      \"Resource\": \"arn:aws:s3:::${BUCKET}/config/*\"
    }
  ]
}"

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 2. lambda-pip-audit-role
#    Needs: SES (send vulnerability report), S3 write (store audit results)
#    No DDB access — installs pip-audit at runtime and emails results
# ─────────────────────────────────────────────────────────────────────────────
AUDIT_ROLE="lambda-pip-audit-role"
echo "── ${AUDIT_ROLE}"
create_role "${AUDIT_ROLE}"

put_policy "${AUDIT_ROLE}" "pip-audit-permissions" "{
  \"Version\": \"2012-10-17\",
  \"Statement\": [
    {
      \"Sid\": \"SESEmail\",
      \"Effect\": \"Allow\",
      \"Action\": \"ses:SendEmail\",
      \"Resource\": \"${SES_IDENTITY}\"
    },
    {
      \"Sid\": \"S3AuditResults\",
      \"Effect\": \"Allow\",
      \"Action\": [\"s3:PutObject\", \"s3:GetObject\"],
      \"Resource\": \"arn:aws:s3:::${BUCKET}/audit-results/*\"
    }
  ]
}"

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Add both new roles to the DynamoDB KMS key policy
# ─────────────────────────────────────────────────────────────────────────────
echo "── Adding roles to KMS key policy..."

RECON_ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/${RECON_ROLE}"
AUDIT_ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/${AUDIT_ROLE}"

CURRENT_POLICY=$(aws kms get-key-policy \
  --key-id "${KMS_KEY_ID}" \
  --policy-name default \
  --query Policy \
  --output text \
  --region "${REGION}")

if echo "$CURRENT_POLICY" | grep -q "${RECON_ROLE}"; then
  echo "  Roles already in KMS policy — skipping"
else
  UPDATED_POLICY=$(echo "$CURRENT_POLICY" | python3 -c "
import json, sys
policy = json.load(sys.stdin)
new_roles = [
  '${RECON_ROLE_ARN}',
  '${AUDIT_ROLE_ARN}'
]
for stmt in policy['Statement']:
  principals = stmt.get('Principal', {})
  aws = principals.get('AWS', []) if isinstance(principals, dict) else []
  if isinstance(aws, str):
    aws = [aws]
  for r in new_roles:
    if r not in aws:
      aws.append(r)
  if aws:
    stmt['Principal']['AWS'] = aws
print(json.dumps(policy))
")
  aws kms put-key-policy \
    --key-id "${KMS_KEY_ID}" \
    --policy-name default \
    --policy "$UPDATED_POLICY" \
    --region "${REGION}" \
    --no-cli-pager
  echo "  ✓ Both roles added to KMS key policy"
fi

echo ""
echo "=== P3 IAM roles created ==="
echo ""
echo "Verifying roles exist:"
for ROLE in "${RECON_ROLE}" "${AUDIT_ROLE}"; do
  RESULT=$(aws iam get-role --role-name "${ROLE}" \
    --query "Role.RoleName" --output text --no-cli-pager 2>/dev/null || echo "NOT FOUND")
  echo "  ${ROLE}: ${RESULT}"
done
echo ""
echo "Next: bash deploy/deploy_p3_lambdas.sh"
