#!/bin/bash
set -euo pipefail

# Deploy CloudFront Lambda@Edge password auth
# Creates: Secret, IAM role, Lambda (us-east-1), CloudFront association
#
# Usage:
#   chmod +x deploy/deploy_cf_auth.sh
#   deploy/deploy_cf_auth.sh              # first-time setup
#   deploy/deploy_cf_auth.sh --update     # update Lambda code only
#   deploy/deploy_cf_auth.sh --password   # change password only

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LAMBDA_DIR="$PROJECT_DIR/lambdas/cf-auth"

SECRET_ID="life-platform/cf-auth"
ROLE_NAME="life-platform-cf-auth-edge"
FUNCTION_NAME="life-platform-cf-auth"
CF_DIST_ID="EM5NPX6NJN095"
REGION="us-east-1"  # Lambda@Edge MUST be us-east-1
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo "=== CloudFront Auth Deploy ==="
echo "Account: $ACCOUNT_ID"
echo "Region: $REGION (required for Lambda@Edge)"
echo ""

# ────────────────────────────────────────────────────
# Helper: prompt for password
# ────────────────────────────────────────────────────
prompt_password() {
    echo -n "Enter password for dashboard access: "
    read -s PASS1
    echo ""
    echo -n "Confirm password: "
    read -s PASS2
    echo ""
    if [ "$PASS1" != "$PASS2" ]; then
        echo "❌ Passwords don't match"
        exit 1
    fi
    if [ ${#PASS1} -lt 6 ]; then
        echo "❌ Password must be at least 6 characters"
        exit 1
    fi
    CF_PASSWORD="$PASS1"
}

# ────────────────────────────────────────────────────
# Password-only mode
# ────────────────────────────────────────────────────
if [ "${1:-}" = "--password" ]; then
    echo "Updating password only..."
    prompt_password
    aws secretsmanager update-secret \
        --secret-id "$SECRET_ID" \
        --secret-string "{\"password\":\"$CF_PASSWORD\"}" \
        --region "$REGION" --no-cli-pager
    echo "✅ Password updated. Existing cookies will be invalid within 5 minutes."
    echo "   (Lambda caches password for 5 min across warm invocations)"
    exit 0
fi

# ────────────────────────────────────────────────────
# Update-code-only mode
# ────────────────────────────────────────────────────
if [ "${1:-}" = "--update" ]; then
    echo "Updating Lambda code only..."
    cd "$LAMBDA_DIR"
    zip -j /tmp/cf-auth.zip index.mjs
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file fileb:///tmp/cf-auth.zip \
        --region "$REGION" --no-cli-pager
    echo "   Waiting for update..."
    aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
    VERSION=$(aws lambda publish-version \
        --function-name "$FUNCTION_NAME" \
        --description "Code update $(date +%Y-%m-%d)" \
        --region "$REGION" \
        --query 'Version' --output text)
    echo "✅ Published version $VERSION"
    LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}:${VERSION}"
    echo ""
    echo "⚠️  You need to update CloudFront to use the new version:"
    echo "   Lambda ARN: $LAMBDA_ARN"
    echo "   Run this script without --update for full deploy, or update CF manually."
    exit 0
fi

# ────────────────────────────────────────────────────
# Full deploy
# ────────────────────────────────────────────────────

# Step 1: Password
prompt_password
echo ""

# Step 2: Secrets Manager
echo "1. Setting up Secrets Manager..."
if aws secretsmanager describe-secret --secret-id "$SECRET_ID" --region "$REGION" >/dev/null 2>&1; then
    aws secretsmanager update-secret \
        --secret-id "$SECRET_ID" \
        --secret-string "{\"password\":\"$CF_PASSWORD\"}" \
        --region "$REGION" --no-cli-pager
    echo "   ✅ Secret updated"
else
    aws secretsmanager create-secret \
        --name "$SECRET_ID" \
        --secret-string "{\"password\":\"$CF_PASSWORD\"}" \
        --description "CloudFront dashboard auth password" \
        --region "$REGION" --no-cli-pager
    echo "   ✅ Secret created"
fi

# Step 3: IAM Role
echo "2. Setting up IAM role..."
TRUST_POLICY='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Service": ["lambda.amazonaws.com", "edgelambda.amazonaws.com"]
    },
    "Action": "sts:AssumeRole"
  }]
}'

if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    echo "   ✅ Role exists"
else
    aws iam create-role \
        --role-name "$ROLE_NAME" \
        --assume-role-policy-document "$TRUST_POLICY" \
        --no-cli-pager
    echo "   ✅ Role created"
fi

# Attach policies
aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" 2>/dev/null || true

# Inline policy for Secrets Manager access
SM_POLICY="{
  \"Version\": \"2012-10-17\",
  \"Statement\": [{
    \"Effect\": \"Allow\",
    \"Action\": [\"secretsmanager:GetSecretValue\"],
    \"Resource\": \"arn:aws:secretsmanager:${REGION}:${ACCOUNT_ID}:secret:${SECRET_ID}-*\"
  }]
}"
aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "secrets-read" \
    --policy-document "$SM_POLICY" --no-cli-pager
echo "   ✅ Policies attached"

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

# Step 4: Lambda function
echo "3. Creating/updating Lambda function..."
cd "$LAMBDA_DIR"
zip -j /tmp/cf-auth.zip index.mjs

if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file fileb:///tmp/cf-auth.zip \
        --region "$REGION" --no-cli-pager
    echo "   ✅ Lambda code updated"
    aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
else
    echo "   Waiting 10s for IAM role propagation..."
    sleep 10
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime "nodejs20.x" \
        --role "$ROLE_ARN" \
        --handler "index.handler" \
        --zip-file fileb:///tmp/cf-auth.zip \
        --timeout 5 \
        --memory-size 128 \
        --region "$REGION" --no-cli-pager
    echo "   ✅ Lambda created"
    aws lambda wait function-active --function-name "$FUNCTION_NAME" --region "$REGION"
fi

# Step 5: Publish version (Lambda@Edge requires a published version)
echo "4. Publishing Lambda version..."
VERSION=$(aws lambda publish-version \
    --function-name "$FUNCTION_NAME" \
    --description "Deploy $(date +%Y-%m-%d_%H%M)" \
    --region "$REGION" \
    --query 'Version' --output text)
LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}:${VERSION}"
echo "   ✅ Version $VERSION published"
echo "   ARN: $LAMBDA_ARN"

# Step 6: Update CloudFront distribution
echo "5. Updating CloudFront distribution $CF_DIST_ID..."

# Get current config
ETAG=$(aws cloudfront get-distribution-config --id "$CF_DIST_ID" --region us-east-1 \
    --query 'ETag' --output text)
aws cloudfront get-distribution-config --id "$CF_DIST_ID" --region us-east-1 \
    --query 'DistributionConfig' > /tmp/cf-dist-config.json

# Add Lambda@Edge association to default cache behavior using jq
# (viewer-request with IncludeBody for POST password)
jq --arg arn "$LAMBDA_ARN" '
  .DefaultCacheBehavior.LambdaFunctionAssociations = {
    "Quantity": 1,
    "Items": [{
      "LambdaFunctionARN": $arn,
      "EventType": "viewer-request",
      "IncludeBody": true
    }]
  }
' /tmp/cf-dist-config.json > /tmp/cf-dist-config-updated.json

aws cloudfront update-distribution \
    --id "$CF_DIST_ID" \
    --if-match "$ETAG" \
    --distribution-config file:///tmp/cf-dist-config-updated.json \
    --region us-east-1 --no-cli-pager
echo "   ✅ CloudFront distribution updated"

echo ""
echo "=== Deploy Complete ==="
echo ""
echo "Distribution will take 5-15 minutes to propagate globally."
echo "Once deployed, visiting dash.averagejoematt.com will show a login page."
echo ""
echo "Commands:"
echo "  Change password:  deploy/deploy_cf_auth.sh --password"
echo "  Update code:      deploy/deploy_cf_auth.sh --update"
echo ""
echo "Password change revokes ALL existing sessions (within 5 min)."
