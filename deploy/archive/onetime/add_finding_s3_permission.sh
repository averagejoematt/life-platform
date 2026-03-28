#!/bin/bash
# deploy/add_finding_s3_permission.sh
# Adds s3:PutObject permission for site/findings/* to the site-api Lambda role.
# Run this ONCE before deploying the Lambda with submit_finding support.
#
# Usage: bash deploy/add_finding_s3_permission.sh

set -euo pipefail

FUNCTION_NAME="life-platform-site-api"
BUCKET="matthew-life-platform"
REGION="us-west-2"

echo "=== Adding s3:PutObject permission for site/findings/* ==="

# Get the Lambda execution role ARN
ROLE_ARN=$(aws lambda get-function-configuration \
  --function-name "$FUNCTION_NAME" \
  --region "$REGION" \
  --query 'Role' --output text --no-cli-pager)

ROLE_NAME=$(echo "$ROLE_ARN" | awk -F'/' '{print $NF}')
echo "Lambda role: $ROLE_NAME"

# Create inline policy for findings writes
POLICY_JSON=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "FindingsS3Write",
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::${BUCKET}/site/findings/*"
    }
  ]
}
EOF
)

aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "site-api-findings-write" \
  --policy-document "$POLICY_JSON" \
  --no-cli-pager

echo "✓ Policy 'site-api-findings-write' attached to $ROLE_NAME"
echo ""
echo "Now deploy the Lambda:"
echo "  bash deploy/deploy_lambda.sh life-platform-site-api lambdas/site_api_lambda.py"
echo ""
echo "Then sync the explorer page:"
echo "  aws s3 sync site/ s3://matthew-life-platform/site/ --delete --region us-west-2"
echo "  aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths '/explorer/*' '/api/*' --no-cli-pager"
