#!/usr/bin/env bash
# SEC-1: Decompose shared IAM role into per-function roles
# IAM-1: Audit + enforce least-privilege per Lambda
#
# Creates 13 dedicated IAM roles replacing lambda-weekly-digest-role (shared by 10+ Lambdas).
# Also adds new roles to the DynamoDB KMS key policy.
#
# Run from: ~/Documents/Claude/life-platform/
# Usage:    bash deploy/setup_sec1_iam_roles.sh
#
# Safe to re-run — role/policy already-exists errors are skipped.
# After this script: run setup_sec2_secrets.sh to update secret access per-role.

set -euo pipefail

REGION="us-west-2"
ACCOUNT="205930651321"
TABLE_ARN="arn:aws:dynamodb:us-west-2:${ACCOUNT}:table/life-platform"
BUCKET="matthew-life-platform"
KMS_KEY_ID="444438d1-a5e0-43b8-9391-3cd2d70dde4d"
SES_IDENTITY="arn:aws:ses:us-west-2:${ACCOUNT}:identity/mattsusername.com"
SQS_DLQ="arn:aws:sqs:us-west-2:${ACCOUNT}:life-platform-ingestion-dlq"
BASIC_EXEC="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

# Secret ARNs
SECRET_AI_KEYS="arn:aws:secretsmanager:us-west-2:${ACCOUNT}:secret:life-platform/ai-keys*"
SECRET_API_KEYS="arn:aws:secretsmanager:us-west-2:${ACCOUNT}:secret:life-platform/api-keys*"

echo "=== SEC-1: Creating per-function IAM roles ==="

# Trust policy — all roles use the same Lambda service principal
TRUST_POLICY='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

# ──────────────────────────────────────────────────────────────────────────────
# Helper: create a role (idempotent)
# ──────────────────────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────────────────────
# Helper: put inline policy (idempotent)
# ──────────────────────────────────────────────────────────────────────────────
put_policy() {
  local ROLE_NAME="$1"
  local POLICY_NAME="$2"
  local POLICY_DOC="$3"
  aws iam put-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-name "${POLICY_NAME}" \
    --policy-document "${POLICY_DOC}" \
    --no-cli-pager
}

# ──────────────────────────────────────────────────────────────────────────────
# Helper: update Lambda execution role
# ──────────────────────────────────────────────────────────────────────────────
update_lambda_role() {
  local FUNC_NAME="$1"
  local ROLE_NAME="$2"
  local ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/${ROLE_NAME}"
  echo "  Updating ${FUNC_NAME} → ${ROLE_NAME}"
  aws lambda update-function-configuration \
    --function-name "${FUNC_NAME}" \
    --role "${ROLE_ARN}" \
    --region "${REGION}" \
    --no-cli-pager \
    2>/dev/null || echo "    (Lambda not found — skipping)"
  sleep 3
}

# ══════════════════════════════════════════════════════════════════════════════
# 1. DAILY BRIEF
#    DDB: R/W | S3: config/ read, dashboard/ + buddy/ write | Secrets: ai-keys | SES: ✓
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── daily-brief ──"
create_role "lambda-daily-brief-role"
put_policy "lambda-daily-brief-role" "life-platform-daily-brief" "$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDB",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem","dynamodb:Query","dynamodb:PutItem","dynamodb:UpdateItem"],
      "Resource": "${TABLE_ARN}"
    },
    {
      "Sid": "KMS",
      "Effect": "Allow",
      "Action": ["kms:Decrypt","kms:GenerateDataKey"],
      "Resource": "arn:aws:kms:${REGION}:${ACCOUNT}:key/${KMS_KEY_ID}"
    },
    {
      "Sid": "S3Read",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": [
        "arn:aws:s3:::${BUCKET}/config/*",
        "arn:aws:s3:::${BUCKET}/raw/cgm_readings/*"
      ]
    },
    {
      "Sid": "S3Write",
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": [
        "arn:aws:s3:::${BUCKET}/dashboard/*",
        "arn:aws:s3:::${BUCKET}/buddy/*"
      ]
    },
    {
      "Sid": "Secrets",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "${SECRET_AI_KEYS}"
    },
    {
      "Sid": "SES",
      "Effect": "Allow",
      "Action": "ses:SendEmail",
      "Resource": "${SES_IDENTITY}"
    },
    {
      "Sid": "SQS",
      "Effect": "Allow",
      "Action": "sqs:SendMessage",
      "Resource": "${SQS_DLQ}"
    }
  ]
}
EOF
)"
update_lambda_role "daily-brief" "lambda-daily-brief-role"

# ══════════════════════════════════════════════════════════════════════════════
# 2. WEEKLY DIGEST
#    DDB: R/W | S3: config/ read, dashboard/ write | Secrets: ai-keys | SES: ✓
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── weekly-digest ──"
create_role "lambda-weekly-digest-role-v2"
put_policy "lambda-weekly-digest-role-v2" "life-platform-weekly-digest" "$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDB",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem","dynamodb:Query","dynamodb:PutItem","dynamodb:UpdateItem"],
      "Resource": "${TABLE_ARN}"
    },
    {
      "Sid": "KMS",
      "Effect": "Allow",
      "Action": ["kms:Decrypt","kms:GenerateDataKey"],
      "Resource": "arn:aws:kms:${REGION}:${ACCOUNT}:key/${KMS_KEY_ID}"
    },
    {
      "Sid": "S3Read",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::${BUCKET}/config/*"
    },
    {
      "Sid": "S3Write",
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::${BUCKET}/dashboard/*"
    },
    {
      "Sid": "Secrets",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "${SECRET_AI_KEYS}"
    },
    {
      "Sid": "SES",
      "Effect": "Allow",
      "Action": "ses:SendEmail",
      "Resource": "${SES_IDENTITY}"
    },
    {
      "Sid": "SQS",
      "Effect": "Allow",
      "Action": "sqs:SendMessage",
      "Resource": "${SQS_DLQ}"
    }
  ]
}
EOF
)"
update_lambda_role "weekly-digest" "lambda-weekly-digest-role-v2"

# ══════════════════════════════════════════════════════════════════════════════
# 3. MONTHLY DIGEST
#    DDB: R/W | S3: config/ read | Secrets: ai-keys | SES: ✓
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── monthly-digest ──"
create_role "lambda-monthly-digest-role"
put_policy "lambda-monthly-digest-role" "life-platform-monthly-digest" "$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDB",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem","dynamodb:Query","dynamodb:PutItem"],
      "Resource": "${TABLE_ARN}"
    },
    {
      "Sid": "KMS",
      "Effect": "Allow",
      "Action": ["kms:Decrypt","kms:GenerateDataKey"],
      "Resource": "arn:aws:kms:${REGION}:${ACCOUNT}:key/${KMS_KEY_ID}"
    },
    {
      "Sid": "S3Read",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::${BUCKET}/config/*"
    },
    {
      "Sid": "Secrets",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "${SECRET_AI_KEYS}"
    },
    {
      "Sid": "SES",
      "Effect": "Allow",
      "Action": "ses:SendEmail",
      "Resource": "${SES_IDENTITY}"
    },
    {
      "Sid": "SQS",
      "Effect": "Allow",
      "Action": "sqs:SendMessage",
      "Resource": "${SQS_DLQ}"
    }
  ]
}
EOF
)"
update_lambda_role "monthly-digest" "lambda-monthly-digest-role"

# ══════════════════════════════════════════════════════════════════════════════
# 4. NUTRITION REVIEW
#    DDB: R-only | S3: config/ read | Secrets: ai-keys | SES: ✓
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── nutrition-review ──"
create_role "lambda-nutrition-review-role"
put_policy "lambda-nutrition-review-role" "life-platform-nutrition-review" "$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDB",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem","dynamodb:Query"],
      "Resource": "${TABLE_ARN}"
    },
    {
      "Sid": "KMS",
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "arn:aws:kms:${REGION}:${ACCOUNT}:key/${KMS_KEY_ID}"
    },
    {
      "Sid": "S3Read",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::${BUCKET}/config/*"
    },
    {
      "Sid": "Secrets",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "${SECRET_AI_KEYS}"
    },
    {
      "Sid": "SES",
      "Effect": "Allow",
      "Action": "ses:SendEmail",
      "Resource": "${SES_IDENTITY}"
    },
    {
      "Sid": "SQS",
      "Effect": "Allow",
      "Action": "sqs:SendMessage",
      "Resource": "${SQS_DLQ}"
    }
  ]
}
EOF
)"
update_lambda_role "nutrition-review" "lambda-nutrition-review-role"

# ══════════════════════════════════════════════════════════════════════════════
# 5. WEDNESDAY CHRONICLE
#    DDB: R/W | S3: config/+blog/ read, blog/ write | Secrets: ai-keys | SES: ✓
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── wednesday-chronicle ──"
create_role "lambda-wednesday-chronicle-role"
put_policy "lambda-wednesday-chronicle-role" "life-platform-wednesday-chronicle" "$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDB",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem","dynamodb:Query","dynamodb:PutItem"],
      "Resource": "${TABLE_ARN}"
    },
    {
      "Sid": "KMS",
      "Effect": "Allow",
      "Action": ["kms:Decrypt","kms:GenerateDataKey"],
      "Resource": "arn:aws:kms:${REGION}:${ACCOUNT}:key/${KMS_KEY_ID}"
    },
    {
      "Sid": "S3Read",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": [
        "arn:aws:s3:::${BUCKET}/config/*",
        "arn:aws:s3:::${BUCKET}/blog/*"
      ]
    },
    {
      "Sid": "S3Write",
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::${BUCKET}/blog/*"
    },
    {
      "Sid": "Secrets",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "${SECRET_AI_KEYS}"
    },
    {
      "Sid": "SES",
      "Effect": "Allow",
      "Action": "ses:SendEmail",
      "Resource": "${SES_IDENTITY}"
    },
    {
      "Sid": "SQS",
      "Effect": "Allow",
      "Action": "sqs:SendMessage",
      "Resource": "${SQS_DLQ}"
    }
  ]
}
EOF
)"
update_lambda_role "wednesday-chronicle" "lambda-wednesday-chronicle-role"

# ══════════════════════════════════════════════════════════════════════════════
# 6. WEEKLY PLATE
#    DDB: R-only | S3: config/ read | Secrets: ai-keys | SES: ✓
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── weekly-plate ──"
create_role "lambda-weekly-plate-role"
put_policy "lambda-weekly-plate-role" "life-platform-weekly-plate" "$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDB",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem","dynamodb:Query"],
      "Resource": "${TABLE_ARN}"
    },
    {
      "Sid": "KMS",
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "arn:aws:kms:${REGION}:${ACCOUNT}:key/${KMS_KEY_ID}"
    },
    {
      "Sid": "S3Read",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::${BUCKET}/config/*"
    },
    {
      "Sid": "Secrets",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "${SECRET_AI_KEYS}"
    },
    {
      "Sid": "SES",
      "Effect": "Allow",
      "Action": "ses:SendEmail",
      "Resource": "${SES_IDENTITY}"
    },
    {
      "Sid": "SQS",
      "Effect": "Allow",
      "Action": "sqs:SendMessage",
      "Resource": "${SQS_DLQ}"
    }
  ]
}
EOF
)"
update_lambda_role "weekly-plate" "lambda-weekly-plate-role"

# ══════════════════════════════════════════════════════════════════════════════
# 7. MONDAY COMPASS
#    DDB: R/W | S3: config/ read | Secrets: ai-keys + api-keys(todoist) | SES: ✓
#    Note: todoist token lives in api-keys; after SEC-2, update to life-platform/todoist
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── monday-compass ──"
create_role "lambda-monday-compass-role"
put_policy "lambda-monday-compass-role" "life-platform-monday-compass" "$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDB",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem","dynamodb:Query","dynamodb:PutItem"],
      "Resource": "${TABLE_ARN}"
    },
    {
      "Sid": "KMS",
      "Effect": "Allow",
      "Action": ["kms:Decrypt","kms:GenerateDataKey"],
      "Resource": "arn:aws:kms:${REGION}:${ACCOUNT}:key/${KMS_KEY_ID}"
    },
    {
      "Sid": "S3Read",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::${BUCKET}/config/*"
    },
    {
      "Sid": "Secrets",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": [
        "${SECRET_AI_KEYS}",
        "${SECRET_API_KEYS}"
      ]
    },
    {
      "Sid": "SES",
      "Effect": "Allow",
      "Action": "ses:SendEmail",
      "Resource": "${SES_IDENTITY}"
    },
    {
      "Sid": "SQS",
      "Effect": "Allow",
      "Action": "sqs:SendMessage",
      "Resource": "${SQS_DLQ}"
    }
  ]
}
EOF
)"
update_lambda_role "monday-compass" "lambda-monday-compass-role"

# ══════════════════════════════════════════════════════════════════════════════
# 8. ADAPTIVE MODE COMPUTE
#    DDB: R/W ONLY — no S3, no Secrets, no SES
#    Most restrictive compute role — this is what least-privilege looks like
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── adaptive-mode-compute ──"
create_role "lambda-adaptive-mode-role"
put_policy "lambda-adaptive-mode-role" "life-platform-adaptive-mode" "$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDB",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem","dynamodb:Query","dynamodb:PutItem"],
      "Resource": "${TABLE_ARN}"
    },
    {
      "Sid": "KMS",
      "Effect": "Allow",
      "Action": ["kms:Decrypt","kms:GenerateDataKey"],
      "Resource": "arn:aws:kms:${REGION}:${ACCOUNT}:key/${KMS_KEY_ID}"
    },
    {
      "Sid": "SQS",
      "Effect": "Allow",
      "Action": "sqs:SendMessage",
      "Resource": "${SQS_DLQ}"
    }
  ]
}
EOF
)"
update_lambda_role "adaptive-mode-compute" "lambda-adaptive-mode-role"

# ══════════════════════════════════════════════════════════════════════════════
# 9. DAILY METRICS COMPUTE
#    DDB: R/W ONLY — no S3, no Secrets, no SES
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── daily-metrics-compute ──"
create_role "lambda-daily-metrics-role"
put_policy "lambda-daily-metrics-role" "life-platform-daily-metrics" "$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDB",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem","dynamodb:Query","dynamodb:PutItem","dynamodb:UpdateItem"],
      "Resource": "${TABLE_ARN}"
    },
    {
      "Sid": "KMS",
      "Effect": "Allow",
      "Action": ["kms:Decrypt","kms:GenerateDataKey"],
      "Resource": "arn:aws:kms:${REGION}:${ACCOUNT}:key/${KMS_KEY_ID}"
    },
    {
      "Sid": "SQS",
      "Effect": "Allow",
      "Action": "sqs:SendMessage",
      "Resource": "${SQS_DLQ}"
    }
  ]
}
EOF
)"
update_lambda_role "daily-metrics-compute" "lambda-daily-metrics-role"

# ══════════════════════════════════════════════════════════════════════════════
# 10. DAILY INSIGHT COMPUTE (IC-2/IC-8)
#     DDB: R/W | Secrets: ai-keys (IC-8 Haiku call) | No S3, No SES
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── daily-insight-compute ──"
create_role "lambda-daily-insight-role"
put_policy "lambda-daily-insight-role" "life-platform-daily-insight" "$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDB",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem","dynamodb:Query","dynamodb:PutItem"],
      "Resource": "${TABLE_ARN}"
    },
    {
      "Sid": "KMS",
      "Effect": "Allow",
      "Action": ["kms:Decrypt","kms:GenerateDataKey"],
      "Resource": "arn:aws:kms:${REGION}:${ACCOUNT}:key/${KMS_KEY_ID}"
    },
    {
      "Sid": "Secrets",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "${SECRET_AI_KEYS}"
    },
    {
      "Sid": "SQS",
      "Effect": "Allow",
      "Action": "sqs:SendMessage",
      "Resource": "${SQS_DLQ}"
    }
  ]
}
EOF
)"
update_lambda_role "daily-insight-compute" "lambda-daily-insight-role"

# ══════════════════════════════════════════════════════════════════════════════
# 11. HYPOTHESIS ENGINE (IC-18)
#     DDB: R/W + UpdateItem | S3: config/ read | Secrets: ai-keys | No SES
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── hypothesis-engine ──"
create_role "lambda-hypothesis-engine-role"
put_policy "lambda-hypothesis-engine-role" "life-platform-hypothesis-engine" "$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDB",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem","dynamodb:Query","dynamodb:PutItem","dynamodb:UpdateItem"],
      "Resource": "${TABLE_ARN}"
    },
    {
      "Sid": "KMS",
      "Effect": "Allow",
      "Action": ["kms:Decrypt","kms:GenerateDataKey"],
      "Resource": "arn:aws:kms:${REGION}:${ACCOUNT}:key/${KMS_KEY_ID}"
    },
    {
      "Sid": "S3Read",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::${BUCKET}/config/*"
    },
    {
      "Sid": "Secrets",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "${SECRET_AI_KEYS}"
    },
    {
      "Sid": "SQS",
      "Effect": "Allow",
      "Action": "sqs:SendMessage",
      "Resource": "${SQS_DLQ}"
    }
  ]
}
EOF
)"
update_lambda_role "hypothesis-engine" "lambda-hypothesis-engine-role"

# ══════════════════════════════════════════════════════════════════════════════
# 12. QA SMOKE
#     DDB: R-only | No S3, No Secrets, No SES — most minimal role
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── qa-smoke ──"
create_role "lambda-qa-smoke-role"
put_policy "lambda-qa-smoke-role" "life-platform-qa-smoke" "$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDB",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem","dynamodb:Query"],
      "Resource": "${TABLE_ARN}"
    },
    {
      "Sid": "KMS",
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "arn:aws:kms:${REGION}:${ACCOUNT}:key/${KMS_KEY_ID}"
    }
  ]
}
EOF
)"
update_lambda_role "life-platform-qa-smoke" "lambda-qa-smoke-role"

# ══════════════════════════════════════════════════════════════════════════════
# 13. DATA EXPORT
#     DDB: R-only (Scan needed for full export) | S3: exports/ write only
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── data-export ──"
create_role "lambda-data-export-role"
put_policy "lambda-data-export-role" "life-platform-data-export" "$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDB",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem","dynamodb:Query","dynamodb:Scan"],
      "Resource": "${TABLE_ARN}"
    },
    {
      "Sid": "KMS",
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "arn:aws:kms:${REGION}:${ACCOUNT}:key/${KMS_KEY_ID}"
    },
    {
      "Sid": "S3Write",
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::${BUCKET}/exports/*"
    }
  ]
}
EOF
)"
update_lambda_role "life-platform-data-export" "lambda-data-export-role"

# ══════════════════════════════════════════════════════════════════════════════
# KMS KEY POLICY: Add new roles to the DynamoDB KMS key policy
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── Updating KMS key policy to include new roles ──"
echo "  Fetching current KMS key policy..."

CURRENT_POLICY=$(aws kms get-key-policy \
  --key-id "${KMS_KEY_ID}" \
  --policy-name default \
  --region "${REGION}" \
  --no-cli-pager \
  --output text 2>/dev/null)

NEW_ROLES=(
  "lambda-daily-brief-role"
  "lambda-weekly-digest-role-v2"
  "lambda-monthly-digest-role"
  "lambda-nutrition-review-role"
  "lambda-wednesday-chronicle-role"
  "lambda-weekly-plate-role"
  "lambda-monday-compass-role"
  "lambda-adaptive-mode-role"
  "lambda-daily-metrics-role"
  "lambda-daily-insight-role"
  "lambda-hypothesis-engine-role"
  "lambda-qa-smoke-role"
  "lambda-data-export-role"
)

echo "  New roles to add to KMS policy:"
for ROLE in "${NEW_ROLES[@]}"; do
  echo "    arn:aws:iam::${ACCOUNT}:role/${ROLE}"
done

echo ""
echo "  NOTE: KMS key policy update requires manual step."
echo "  The new roles above have kms:Decrypt in their inline policies."
echo "  The KMS key policy must also GRANT these ARNs access."
echo ""
echo "  Run this to check the current KMS policy:"
echo "    aws kms get-key-policy --key-id ${KMS_KEY_ID} --policy-name default --region ${REGION} --output text | python3 -m json.tool"
echo ""
echo "  Then add each new role ARN to the existing Principal list in the key policy statement"
echo "  that currently grants Lambda roles kms:Decrypt and kms:GenerateDataKey."
echo "  Use: aws kms put-key-policy --key-id ${KMS_KEY_ID} --policy-name default --policy file://kms_policy_updated.json"

# ══════════════════════════════════════════════════════════════════════════════
# VERIFY
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "=== Verification ==="
echo "Checking new roles exist:"
for ROLE in \
  "lambda-daily-brief-role" \
  "lambda-weekly-digest-role-v2" \
  "lambda-monthly-digest-role" \
  "lambda-nutrition-review-role" \
  "lambda-wednesday-chronicle-role" \
  "lambda-weekly-plate-role" \
  "lambda-monday-compass-role" \
  "lambda-adaptive-mode-role" \
  "lambda-daily-metrics-role" \
  "lambda-daily-insight-role" \
  "lambda-hypothesis-engine-role" \
  "lambda-qa-smoke-role" \
  "lambda-data-export-role"; do
  RESULT=$(aws iam get-role --role-name "${ROLE}" --query "Role.RoleName" --output text --no-cli-pager 2>/dev/null || echo "NOT FOUND")
  echo "  ${ROLE}: ${RESULT}"
done

echo ""
echo "Checking Lambda execution roles:"
for FUNC in daily-brief weekly-digest monthly-digest nutrition-review wednesday-chronicle \
             weekly-plate monday-compass adaptive-mode-compute daily-metrics-compute \
             daily-insight-compute hypothesis-engine life-platform-qa-smoke life-platform-data-export; do
  ROLE=$(aws lambda get-function-configuration \
    --function-name "${FUNC}" \
    --region "${REGION}" \
    --query "Role" \
    --output text \
    --no-cli-pager 2>/dev/null | sed 's|.*/||' || echo "NOT FOUND")
  echo "  ${FUNC}: ${ROLE}"
done

echo ""
echo "=== SEC-1 complete ==="
echo "Next steps:"
echo "  1. Run: bash deploy/setup_sec2_secrets.sh  (split secrets per role)"
echo "  2. Update KMS key policy manually (see instructions above)"
echo "  3. Verify Lambda invocations succeed: check CloudWatch logs after next scheduled run"
echo "  4. After verification: delete lambda-weekly-digest-role (the old shared role)"
echo "     aws iam delete-role-policy --role-name lambda-weekly-digest-role --policy-name <policy>"
echo "     aws iam detach-role-policy --role-name lambda-weekly-digest-role --policy-arn ${BASIC_EXEC}"
echo "     aws iam delete-role --role-name lambda-weekly-digest-role"
