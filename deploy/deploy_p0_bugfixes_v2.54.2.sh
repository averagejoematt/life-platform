#!/bin/bash
# Deploy: P0 Bug Fixes — Dashboard JSON + Buddy IAM
# v2.54.2: Fix write_dashboard_json NameError + buddy S3 permissions
set -euo pipefail

LAMBDA_NAME="daily-brief"
LAMBDA_DIR="$HOME/Documents/Claude/life-platform/lambdas"
DEPLOY_DIR="$HOME/Documents/Claude/life-platform/deploy"
ROLE_NAME="lambda-weekly-digest-role"

echo "=== P0 Bug Fix Deploy ==="

# --- Fix 1: Update IAM policy to allow buddy/* writes ---
echo ""
echo "[1/3] Updating IAM policy: adding s3:PutObject for buddy/*..."

aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name dashboard-s3-write \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Sid": "DashboardAndBuddyWrite",
        "Effect": "Allow",
        "Action": "s3:PutObject",
        "Resource": [
          "arn:aws:s3:::matthew-life-platform/dashboard/*",
          "arn:aws:s3:::matthew-life-platform/buddy/*"
        ]
      }
    ]
  }'

echo "  ✅ IAM policy updated"

# Verify
echo "  Verifying..."
aws iam get-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name dashboard-s3-write \
  --query 'PolicyDocument.Statement[0].Resource' \
  --output text
echo ""

# --- Fix 2: Deploy updated Daily Brief Lambda ---
echo "[2/3] Packaging Daily Brief Lambda..."
cd "$LAMBDA_DIR"
zip -j "$DEPLOY_DIR/daily_brief_lambda.zip" daily_brief_lambda.py
echo "  ✅ Zip created"

echo ""
echo "[3/3] Deploying Lambda..."
aws lambda update-function-code \
  --function-name "$LAMBDA_NAME" \
  --zip-file "fileb://$DEPLOY_DIR/daily_brief_lambda.zip" \
  --query '{FunctionName: FunctionName, LastModified: LastModified, CodeSize: CodeSize}' \
  --output table

echo ""
echo "=== Deploy complete ==="
echo ""
echo "Changes:"
echo "  1. IAM: lambda-weekly-digest-role can now write to buddy/* in S3"
echo "  2. Lambda: write_dashboard_json() now receives component_details parameter"
echo "     - Fixes NameError that prevented dashboard tile data from populating"
echo "     - Safe default (empty dict) if component_details is None"
echo ""
echo "Both fixes are non-fatal (try/except wrapped), so tomorrow's brief will"
echo "silently succeed on dashboard+buddy JSON writes instead of logging warnings."
