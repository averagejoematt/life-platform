#!/usr/bin/env bash
# deploy/setup_github_oidc.sh — One-time OIDC setup for GitHub Actions CI/CD
#
# Creates:
#   1. GitHub OIDC identity provider in AWS IAM
#   2. github-actions-deploy-role IAM role with scoped permissions
#
# Run ONCE per AWS account. Idempotent — safe to re-run if interrupted.
# After running, add the role ARN to your repo secrets (not needed — it's
# hardcoded in ci-cd.yml as arn:aws:iam::205930651321:role/github-actions-deploy-role).
#
# Prerequisites:
#   - AWS CLI configured with admin credentials
#   - jq installed
#
# Usage:
#   bash deploy/setup_github_oidc.sh
#
# What the role can do (see POLICY below for full list):
#   - Lambda: update-code, get-config, invoke (for smoke tests + I3/I10)
#   - S3: get/put on matthew-life-platform (deploy artifacts + config reads)
#   - CloudFormation: describe (CDK diff)
#   - sts:AssumeRole on cdk-* roles (required for cdk diff --all)
#   - DDB: describe-table (I4 integration check)
#   - SNS: get-attrs + publish (notify-failure job)
#   - SQS: get-queue-attrs (I9 DLQ check)
#   - KMS: describe-key (plan job stateful resource check)
#   - EventBridge: describe-rule (I6)
#   - CloudWatch: describe-alarms (I7)
#   - Secrets Manager: describe + get-value (I5 existence check, I12 MCP auth)
#   - IAM: read-only (CDK diff IAM change detection)
#
# v1.0.0 — 2026-03-15 (R13-F01 CI/CD enablement)

set -euo pipefail

ACCOUNT="205930651321"
REGION="us-west-2"
ROLE_NAME="github-actions-deploy-role"
GITHUB_ORG="averagejoematt"
GITHUB_REPO="life-platform"
OIDC_URL="https://token.actions.githubusercontent.com"
OIDC_THUMBPRINT="6938fd4d98bab03faadb97b34396831e3780aea1"  # GitHub Actions OIDC thumbprint

echo "═══════════════════════════════════════════════════════"
echo "  Life Platform — GitHub Actions OIDC Setup"
echo "  Account: $ACCOUNT  Region: $REGION"
echo "═══════════════════════════════════════════════════════"
echo ""

# ── Step 1: Create OIDC provider (idempotent) ─────────────────────────────────
echo "Step 1: GitHub OIDC identity provider"

EXISTING_PROVIDER=$(aws iam list-open-id-connect-providers \
  --query "OpenIDConnectProviderList[?ends_with(Arn, 'oidc-provider/token.actions.githubusercontent.com')].Arn" \
  --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_PROVIDER" ]; then
  echo "  ✅ OIDC provider already exists: $EXISTING_PROVIDER"
  OIDC_ARN="$EXISTING_PROVIDER"
else
  echo "  Creating OIDC provider..."
  OIDC_ARN=$(aws iam create-open-id-connect-provider \
    --url "$OIDC_URL" \
    --client-id-list "sts.amazonaws.com" \
    --thumbprint-list "$OIDC_THUMBPRINT" \
    --query "OpenIDConnectProviderArn" \
    --output text)
  echo "  ✅ Created: $OIDC_ARN"
fi

# ── Step 2: Trust policy ──────────────────────────────────────────────────────
echo ""
echo "Step 2: Trust policy"

TRUST_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "$OIDC_ARN"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:${GITHUB_ORG}/${GITHUB_REPO}:*"
        }
      }
    }
  ]
}
EOF
)

# ── Step 3: Permission policy ─────────────────────────────────────────────────
PERMISSION_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "LambdaDeploy",
      "Effect": "Allow",
      "Action": [
        "lambda:UpdateFunctionCode",
        "lambda:UpdateFunctionConfiguration",
        "lambda:GetFunctionConfiguration",
        "lambda:GetFunction",
        "lambda:ListFunctions",
        "lambda:InvokeFunction",
        "lambda:WaitForFunctionUpdated",
        "lambda:ListLayerVersions",
        "lambda:GetLayerVersion",
        "lambda:PublishLayerVersion",
        "lambda:AddLayerVersionPermission",
        "lambda:GetLayerVersionPolicy",
        "lambda:ListTags"
      ],
      "Resource": [
        "arn:aws:lambda:us-west-2:${ACCOUNT}:function:*",
        "arn:aws:lambda:us-west-2:${ACCOUNT}:layer:*"
      ]
    },
    {
      "Sid": "S3DeployArtifacts",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:HeadObject",
        "s3:HeadBucket",
        "s3:ListBucket",
        "s3:GetBucketLocation"
      ],
      "Resource": [
        "arn:aws:s3:::matthew-life-platform",
        "arn:aws:s3:::matthew-life-platform/*"
      ]
    },
    {
      "Sid": "DynamoDB",
      "Effect": "Allow",
      "Action": [
        "dynamodb:DescribeTable",
        "dynamodb:DescribeContinuousBackups"
      ],
      "Resource": "arn:aws:dynamodb:us-west-2:${ACCOUNT}:table/life-platform"
    },
    {
      "Sid": "SNS",
      "Effect": "Allow",
      "Action": [
        "sns:GetTopicAttributes",
        "sns:Publish"
      ],
      "Resource": "arn:aws:sns:us-west-2:${ACCOUNT}:life-platform-alerts"
    },
    {
      "Sid": "SQS",
      "Effect": "Allow",
      "Action": [
        "sqs:GetQueueAttributes",
        "sqs:GetQueueUrl"
      ],
      "Resource": "arn:aws:sqs:us-west-2:${ACCOUNT}:life-platform-ingestion-dlq"
    },
    {
      "Sid": "KMS",
      "Effect": "Allow",
      "Action": [
        "kms:DescribeKey"
      ],
      "Resource": "arn:aws:kms:us-west-2:${ACCOUNT}:key/444438d1-a5e0-43b8-9391-3cd2d70dde4d"
    },
    {
      "Sid": "EventBridge",
      "Effect": "Allow",
      "Action": [
        "events:DescribeRule",
        "events:ListRules",
        "events:ListTargetsByRule"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CloudWatch",
      "Effect": "Allow",
      "Action": [
        "cloudwatch:DescribeAlarms",
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:ListMetrics",
        "cloudwatch:GetMetricData"
      ],
      "Resource": "*"
    },
    {
      "Sid": "SecretsManager",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:DescribeSecret",
        "secretsmanager:GetSecretValue",
        "secretsmanager:ListSecrets"
      ],
      "Resource": [
        "arn:aws:secretsmanager:us-west-2:${ACCOUNT}:secret:life-platform/*"
      ]
    },
    {
      "Sid": "CloudFormationDiff",
      "Effect": "Allow",
      "Action": [
        "cloudformation:DescribeStacks",
        "cloudformation:DescribeStackResource",
        "cloudformation:GetTemplate",
        "cloudformation:ListStackResources",
        "cloudformation:DescribeStackEvents",
        "cloudformation:ListStacks",
        "cloudformation:DescribeStackSet",
        "cloudformation:ValidateTemplate"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CDKBootstrapRoleAssume",
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::${ACCOUNT}:role/cdk-*"
    },
    {
      "Sid": "IAMReadOnly",
      "Effect": "Allow",
      "Action": [
        "iam:GetRole",
        "iam:ListRolePolicies",
        "iam:GetRolePolicy",
        "iam:ListAttachedRolePolicies",
        "iam:GetPolicy",
        "iam:GetPolicyVersion",
        "iam:ListRoles",
        "iam:SimulatePrincipalPolicy"
      ],
      "Resource": "*"
    }
  ]
}
EOF
)

# ── Step 4: Create or update the IAM role ─────────────────────────────────────
echo ""
echo "Step 3: IAM role — $ROLE_NAME"

EXISTING_ROLE=$(aws iam get-role --role-name "$ROLE_NAME" \
  --query "Role.Arn" --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_ROLE" ]; then
  echo "  Role already exists: $EXISTING_ROLE"
  echo "  Updating trust policy..."
  aws iam update-assume-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-document "$TRUST_POLICY"
  echo "  ✅ Trust policy updated"
else
  echo "  Creating role..."
  ROLE_ARN=$(aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" \
    --description "GitHub Actions OIDC role for life-platform CI/CD (averagejoematt/life-platform)" \
    --max-session-duration 3600 \
    --query "Role.Arn" \
    --output text)
  echo "  ✅ Created: $ROLE_ARN"
fi

# ── Step 5: Attach permission policy ──────────────────────────────────────────
echo ""
echo "Step 4: Permission policy"

# Put as inline policy (simpler than managed policy for single-role use)
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "life-platform-cicd-permissions" \
  --policy-document "$PERMISSION_POLICY"
echo "  ✅ Permissions applied"

# ── Step 6: Verify ────────────────────────────────────────────────────────────
echo ""
echo "Step 5: Verification"

FINAL_ARN=$(aws iam get-role --role-name "$ROLE_NAME" \
  --query "Role.Arn" --output text)
echo "  ✅ Role ARN: $FINAL_ARN"

POLICY_NAMES=$(aws iam list-role-policies --role-name "$ROLE_NAME" \
  --query "PolicyNames[]" --output text)
echo "  ✅ Inline policies: $POLICY_NAMES"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ✅ OIDC setup complete"
echo ""
echo "  Role ARN: $FINAL_ARN"
echo ""
echo "  Next steps:"
echo "  1. Verify the role ARN matches ci-cd.yml:"
echo "     role-to-assume: arn:aws:iam::${ACCOUNT}:role/${ROLE_NAME}"
echo "  2. Create the GitHub 'production' Environment in repo settings"
echo "     (required for the manual approval gate on deploy jobs):"
echo "     https://github.com/${GITHUB_ORG}/${GITHUB_REPO}/settings/environments"
echo "  3. Push a change to main to trigger the first pipeline run"
echo "  4. Monitor the Actions tab:"
echo "     https://github.com/${GITHUB_ORG}/${GITHUB_REPO}/actions"
echo "═══════════════════════════════════════════════════════"
