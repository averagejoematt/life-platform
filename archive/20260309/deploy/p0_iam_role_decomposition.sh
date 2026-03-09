#!/bin/bash
# p0_iam_role_decomposition.sh — P0: Decompose lambda-weekly-digest-role into 3 scoped roles
#
# PROBLEM: lambda-weekly-digest-role is shared by 10+ Lambdas. Any compromise
#          of one Lambda gives blast radius across all of them.
#
# SOLUTION: Three purpose-scoped roles with least-privilege permissions:
#   life-platform-compute-role  — compute Lambdas (DDB read+write, no SES)
#   life-platform-email-role    — email Lambdas (DDB read-only, SES, S3 write dashboard/buddy)
#   life-platform-digest-role   — digest Lambdas (DDB read-only, SES, S3 write blog/dashboard)
#
# SAFE TO RE-RUN: role/policy creation is idempotent (update if exists).
#
# Prerequisites: ./deploy/p0_split_secret.sh must have run first (creates ai-keys secret).
#
# Usage: cd ~/Documents/Claude/life-platform && ./deploy/p0_iam_role_decomposition.sh

set -euo pipefail
REGION="us-west-2"
ACCOUNT="205930651321"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  P0: IAM Role Decomposition — 3 scoped Lambda roles         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Trust policy (same for all Lambda execution roles) ────────────────────────
TRUST_POLICY='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}'

# ── Helper: create or update a role ──────────────────────────────────────────
ensure_role() {
    local role_name="$1"
    local description="$2"
    if aws iam get-role --role-name "$role_name" --no-cli-pager > /dev/null 2>&1; then
        echo "  Role $role_name already exists — skipping create"
    else
        aws iam create-role \
            --role-name "$role_name" \
            --assume-role-policy-document "$TRUST_POLICY" \
            --description "$description" \
            --no-cli-pager > /dev/null
        echo "  ✅ Created role: $role_name"
    fi

    # Always attach basic execution policy (CloudWatch Logs)
    aws iam attach-role-policy \
        --role-name "$role_name" \
        --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
        --no-cli-pager 2>/dev/null || true
}

# ── Helper: assign Lambda to role ─────────────────────────────────────────────
assign_role() {
    local fn="$1"
    local role_arn="$2"
    echo -n "  $fn → $(echo "$role_arn" | sed 's|.*role/||') ... "
    aws lambda update-function-configuration \
        --function-name "$fn" \
        --role "$role_arn" \
        --region "$REGION" \
        --no-cli-pager > /dev/null
    echo "✅"
    sleep 3  # avoid ResourceConflictException
}


# ════════════════════════════════════════════════════════════════════════════════
# ROLE 1: life-platform-compute-role
# Compute Lambdas — read+write DDB, no SES, no blog S3
# character-sheet-compute, adaptive-mode-compute, daily-metrics-compute,
# daily-insight-compute, hypothesis-engine
# ════════════════════════════════════════════════════════════════════════════════
echo "── Role 1: life-platform-compute-role ──"
ensure_role "life-platform-compute-role" "Life Platform compute Lambdas - DDB read/write, no SES"

aws iam put-role-policy \
    --role-name "life-platform-compute-role" \
    --policy-name "compute-access" \
    --policy-document "{
  \"Version\": \"2012-10-17\",
  \"Statement\": [
    {
      \"Sid\": \"DynamoDBReadWrite\",
      \"Effect\": \"Allow\",
      \"Action\": [
        \"dynamodb:GetItem\",
        \"dynamodb:Query\",
        \"dynamodb:PutItem\",
        \"dynamodb:UpdateItem\",
        \"dynamodb:BatchGetItem\"
      ],
      \"Resource\": [
        \"arn:aws:dynamodb:$REGION:$ACCOUNT:table/life-platform\",
        \"arn:aws:dynamodb:$REGION:$ACCOUNT:table/life-platform/index/*\"
      ]
    },
    {
      \"Sid\": \"S3ConfigRead\",
      \"Effect\": \"Allow\",
      \"Action\": \"s3:GetObject\",
      \"Resource\": \"arn:aws:s3:::matthew-life-platform/config/*\"
    },
    {
      \"Sid\": \"SecretsAI\",
      \"Effect\": \"Allow\",
      \"Action\": \"secretsmanager:GetSecretValue\",
      \"Resource\": \"arn:aws:secretsmanager:$REGION:$ACCOUNT:secret:life-platform/ai-keys*\"
    }
  ]
}" --no-cli-pager
echo "  ✅ Inline policy applied"
echo ""

COMPUTE_ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/life-platform-compute-role"


# ════════════════════════════════════════════════════════════════════════════════
# ROLE 2: life-platform-email-role
# Email Lambdas — DDB read-only, SES, S3 read config/dashboard/buddy, S3 write dashboard/buddy
# daily-brief, nutrition-review, wednesday-chronicle, weekly-plate,
# monday-compass, anomaly-detector
# ════════════════════════════════════════════════════════════════════════════════
echo "── Role 2: life-platform-email-role ──"
ensure_role "life-platform-email-role" "Life Platform email Lambdas - DDB read-only, SES, S3 dashboard/buddy"

aws iam put-role-policy \
    --role-name "life-platform-email-role" \
    --policy-name "email-access" \
    --policy-document "{
  \"Version\": \"2012-10-17\",
  \"Statement\": [
    {
      \"Sid\": \"DynamoDBRead\",
      \"Effect\": \"Allow\",
      \"Action\": [
        \"dynamodb:GetItem\",
        \"dynamodb:Query\",
        \"dynamodb:BatchGetItem\"
      ],
      \"Resource\": [
        \"arn:aws:dynamodb:$REGION:$ACCOUNT:table/life-platform\",
        \"arn:aws:dynamodb:$REGION:$ACCOUNT:table/life-platform/index/*\"
      ]
    },
    {
      \"Sid\": \"S3Read\",
      \"Effect\": \"Allow\",
      \"Action\": [\"s3:GetObject\", \"s3:HeadObject\"],
      \"Resource\": [
        \"arn:aws:s3:::matthew-life-platform/config/*\",
        \"arn:aws:s3:::matthew-life-platform/dashboard/*\",
        \"arn:aws:s3:::matthew-life-platform/buddy/*\",
        \"arn:aws:s3:::matthew-life-platform/avatar/*\"
      ]
    },
    {
      \"Sid\": \"S3Write\",
      \"Effect\": \"Allow\",
      \"Action\": \"s3:PutObject\",
      \"Resource\": [
        \"arn:aws:s3:::matthew-life-platform/dashboard/*\",
        \"arn:aws:s3:::matthew-life-platform/buddy/*\"
      ]
    },
    {
      \"Sid\": \"Email\",
      \"Effect\": \"Allow\",
      \"Action\": [\"ses:SendEmail\", \"sesv2:SendEmail\"],
      \"Resource\": \"*\"
    },
    {
      \"Sid\": \"SecretsAI\",
      \"Effect\": \"Allow\",
      \"Action\": \"secretsmanager:GetSecretValue\",
      \"Resource\": \"arn:aws:secretsmanager:$REGION:$ACCOUNT:secret:life-platform/ai-keys*\"
    }
  ]
}" --no-cli-pager
echo "  ✅ Inline policy applied"
echo ""

EMAIL_ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/life-platform-email-role"


# ════════════════════════════════════════════════════════════════════════════════
# ROLE 3: life-platform-digest-role
# Digest Lambdas — DDB read-only, SES, S3 read+write config/dashboard/blog/buddy
# weekly-digest, monthly-digest
# ════════════════════════════════════════════════════════════════════════════════
echo "── Role 3: life-platform-digest-role ──"
ensure_role "life-platform-digest-role" "Life Platform digest Lambdas - DDB read-only, SES, S3 blog+dashboard"

aws iam put-role-policy \
    --role-name "life-platform-digest-role" \
    --policy-name "digest-access" \
    --policy-document "{
  \"Version\": \"2012-10-17\",
  \"Statement\": [
    {
      \"Sid\": \"DynamoDBRead\",
      \"Effect\": \"Allow\",
      \"Action\": [
        \"dynamodb:GetItem\",
        \"dynamodb:Query\",
        \"dynamodb:BatchGetItem\"
      ],
      \"Resource\": [
        \"arn:aws:dynamodb:$REGION:$ACCOUNT:table/life-platform\",
        \"arn:aws:dynamodb:$REGION:$ACCOUNT:table/life-platform/index/*\"
      ]
    },
    {
      \"Sid\": \"S3Read\",
      \"Effect\": \"Allow\",
      \"Action\": [\"s3:GetObject\", \"s3:HeadObject\"],
      \"Resource\": [
        \"arn:aws:s3:::matthew-life-platform/config/*\",
        \"arn:aws:s3:::matthew-life-platform/dashboard/*\",
        \"arn:aws:s3:::matthew-life-platform/blog/*\",
        \"arn:aws:s3:::matthew-life-platform/buddy/*\",
        \"arn:aws:s3:::matthew-life-platform/avatar/*\"
      ]
    },
    {
      \"Sid\": \"S3Write\",
      \"Effect\": \"Allow\",
      \"Action\": \"s3:PutObject\",
      \"Resource\": [
        \"arn:aws:s3:::matthew-life-platform/dashboard/*\",
        \"arn:aws:s3:::matthew-life-platform/blog/*\",
        \"arn:aws:s3:::matthew-life-platform/buddy/*\"
      ]
    },
    {
      \"Sid\": \"Email\",
      \"Effect\": \"Allow\",
      \"Action\": [\"ses:SendEmail\", \"sesv2:SendEmail\"],
      \"Resource\": \"*\"
    },
    {
      \"Sid\": \"SecretsAI\",
      \"Effect\": \"Allow\",
      \"Action\": \"secretsmanager:GetSecretValue\",
      \"Resource\": \"arn:aws:secretsmanager:$REGION:$ACCOUNT:secret:life-platform/ai-keys*\"
    }
  ]
}" --no-cli-pager
echo "  ✅ Inline policy applied"
echo ""

DIGEST_ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/life-platform-digest-role"


# ════════════════════════════════════════════════════════════════════════════════
# ASSIGN ROLES TO LAMBDAS
# ════════════════════════════════════════════════════════════════════════════════
echo "── Assigning roles to Lambdas ──"
echo ""

echo "  [ compute-role ]"
for fn in \
    "character-sheet-compute" \
    "adaptive-mode-compute" \
    "daily-metrics-compute" \
    "daily-insight-compute" \
    "hypothesis-engine"; do
    assign_role "$fn" "$COMPUTE_ROLE_ARN"
done
echo ""

echo "  [ email-role ]"
for fn in \
    "daily-brief" \
    "nutrition-review" \
    "wednesday-chronicle" \
    "weekly-plate" \
    "monday-compass" \
    "anomaly-detector"; do
    assign_role "$fn" "$EMAIL_ROLE_ARN"
done
echo ""

echo "  [ digest-role ]"
for fn in \
    "weekly-digest" \
    "monthly-digest"; do
    assign_role "$fn" "$DIGEST_ROLE_ARN"
done
echo ""


# ════════════════════════════════════════════════════════════════════════════════
# VERIFICATION
# ════════════════════════════════════════════════════════════════════════════════
echo "── Verification ──"
echo ""
echo "  Roles created:"
aws iam list-roles \
    --path-prefix "/" \
    --no-cli-pager \
    --query "Roles[?contains(RoleName, 'life-platform-') && contains(['life-platform-compute-role','life-platform-email-role','life-platform-digest-role'], RoleName)].{Name:RoleName,ARN:Arn}" \
    --output table 2>/dev/null || \
aws iam list-roles --no-cli-pager \
    --query "Roles[?contains(RoleName, 'life-platform-compute-role') || contains(RoleName, 'life-platform-email-role') || contains(RoleName, 'life-platform-digest-role')].RoleName" \
    --output table

echo ""
echo "  Spot-check Lambda roles:"
for fn in "daily-brief" "weekly-digest" "hypothesis-engine"; do
    role=$(aws lambda get-function-configuration \
        --function-name "$fn" --region "$REGION" \
        --query "Role" --output text --no-cli-pager 2>/dev/null | sed 's|.*role/||')
    echo "    $fn → $role"
done

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✅ P0 IAM Role Decomposition Complete                      ║"
echo "║                                                              ║"
echo "║  3 scoped roles now active:                                  ║"
echo "║    compute-role  → 5 compute Lambdas (no SES)               ║"
echo "║    email-role    → 6 email Lambdas                           ║"
echo "║    digest-role   → 2 digest Lambdas (+ blog S3 write)       ║"
echo "║                                                              ║"
echo "║  NEXT STEPS:                                                 ║"
echo "║  1. Run Daily Brief (11 AM) — verify it still sends         ║"
echo "║  2. Run Weekly Digest (next Sunday) — verify it sends       ║"
echo "║  3. Monitor CloudWatch for AccessDenied errors              ║"
echo "║  4. After 48h clean run, deprecate lambda-weekly-digest-role║"
echo "╚══════════════════════════════════════════════════════════════╝"
