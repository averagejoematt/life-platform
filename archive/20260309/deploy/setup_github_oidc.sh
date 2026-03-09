#!/bin/bash
# deploy/setup_github_oidc.sh — MAINT-4: Create OIDC provider + IAM role for GitHub Actions
#
# Run ONCE to set up GitHub Actions → AWS authentication.
# After running, add the GitHub Environment "production" with Matthew as required reviewer.
#
# Prerequisites:
#   - AWS CLI configured with admin permissions
#   - GitHub repo: averagejoematt/life-platform (private)
set -euo pipefail

REGION="us-west-2"
ACCOUNT_ID="205930651321"
GITHUB_ORG="averagejoematt"
GITHUB_REPO="life-platform"
ROLE_NAME="github-actions-deploy-role"

echo "═══════════════════════════════════════════════════════════"
echo "MAINT-4: GitHub OIDC Setup for CI/CD"
echo "═══════════════════════════════════════════════════════════"

# ── Step 1: Create OIDC Identity Provider (idempotent) ──
echo ""
echo "Step 1: Creating OIDC identity provider for GitHub..."

# Check if already exists
EXISTING_PROVIDER=$(aws iam list-open-id-connect-providers \
  --query "OpenIDConnectProviderList[?ends_with(Arn, 'token.actions.githubusercontent.com')].Arn" \
  --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_PROVIDER" ] && [ "$EXISTING_PROVIDER" != "None" ]; then
  echo "  ✅ OIDC provider already exists: $EXISTING_PROVIDER"
  PROVIDER_ARN="$EXISTING_PROVIDER"
else
  PROVIDER_ARN=$(aws iam create-open-id-connect-provider \
    --url "https://token.actions.githubusercontent.com" \
    --thumbprint-list "6938fd4d98bab03faadb97b34396831e3780aea1" "1c58a3a8518e8759bf075b76b750d4f2df264fcd" \
    --client-id-list "sts.amazonaws.com" \
    --query "OpenIDConnectProviderArn" \
    --output text)
  echo "  ✅ Created OIDC provider: $PROVIDER_ARN"
fi

# ── Step 2: Create IAM Role for GitHub Actions ──
echo ""
echo "Step 2: Creating IAM role: $ROLE_NAME..."

# Check if role exists
if aws iam get-role --role-name "$ROLE_NAME" > /dev/null 2>&1; then
  echo "  ⚠️ Role already exists — updating trust policy..."
else
  echo "  Creating new role..."
fi

# Trust policy: allow GitHub Actions from our repo to assume this role
TRUST_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
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

if aws iam get-role --role-name "$ROLE_NAME" > /dev/null 2>&1; then
  aws iam update-assume-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-document "$TRUST_POLICY"
  echo "  ✅ Trust policy updated"
else
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" \
    --description "GitHub Actions CI/CD for life-platform - OIDC federated" \
    --max-session-duration 3600 > /dev/null
  echo "  ✅ Role created"
fi

# ── Step 3: Attach permissions ──
echo ""
echo "Step 3: Attaching permissions..."

# Lambda deploy permissions
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "lambda-deploy" \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "lambda:UpdateFunctionCode",
          "lambda:GetFunctionConfiguration",
          "lambda:UpdateFunctionConfiguration",
          "lambda:ListLayerVersions",
          "lambda:PublishLayerVersion",
          "lambda:InvokeFunction"
        ],
        "Resource": [
          "arn:aws:lambda:us-west-2:'"$ACCOUNT_ID"':function:*",
          "arn:aws:lambda:us-west-2:'"$ACCOUNT_ID"':layer:life-platform-*"
        ]
      }
    ]
  }'
echo "  ✅ lambda-deploy policy attached"

# S3 read (for MCP server packaging — reads from config/)
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "s3-read" \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "s3:GetObject",
          "s3:ListBucket"
        ],
        "Resource": [
          "arn:aws:s3:::matthew-life-platform",
          "arn:aws:s3:::matthew-life-platform/*"
        ]
      }
    ]
  }'
echo "  ✅ s3-read policy attached"

# CloudWatch for smoke test verification
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "cloudwatch-read" \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "logs:GetLogEvents",
          "logs:DescribeLogStreams",
          "cloudwatch:DescribeAlarms"
        ],
        "Resource": "*"
      }
    ]
  }'
echo "  ✅ cloudwatch-read policy attached"

# ── Summary ──
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ OIDC Setup Complete!"
echo ""
echo "Role ARN: arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
echo ""
echo "Manual steps remaining:"
echo "  1. Go to GitHub → repo Settings → Environments"
echo "  2. Create environment: 'production'"
echo "  3. Add protection rule: Required reviewers → add yourself"
echo "  4. (Optional) Add deployment branch rule: main only"
echo ""
echo "The CI/CD workflow (.github/workflows/ci-cd.yml) will:"
echo "  • Lint on every push to main"
echo "  • Auto-detect changed Lambdas"
echo "  • Wait for your approval before deploying"
echo "  • Run smoke test after deploy"
echo "═══════════════════════════════════════════════════════════"
