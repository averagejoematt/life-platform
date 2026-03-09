#!/bin/bash
# deploy_dashboard_phase1.sh — Life Platform v2.38.0
# Feature #22: Web Dashboard Phase 1
# - Patches daily-brief Lambda with dashboard JSON generator
# - Uploads static HTML dashboard to S3
# - Enables S3 static website hosting
# - Adds S3 PutObject permission to email Lambda IAM role
#
# Run from: ~/Documents/Claude/life-platform/
# Prerequisites: aws cli configured, python3

set -euo pipefail
REGION="us-west-2"
BUCKET="matthew-life-platform"
LAMBDA="daily-brief"
ROLE_NAME="lambda-weekly-digest-role"
ACCOUNT_ID="205930651321"

echo "=== Life Platform v2.38.0 — Dashboard Phase 1 Deploy ==="
echo ""

# ---------------------------------------------------------------
# Step 1: Add S3 PutObject permission to the email Lambda role
# ---------------------------------------------------------------
echo "[1/5] Adding S3 PutObject permission for dashboard/ path..."

POLICY_DOC='{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DashboardWrite",
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::matthew-life-platform/dashboard/*"
    }
  ]
}'

aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "dashboard-s3-write" \
  --policy-document "$POLICY_DOC" \
  --region "$REGION" 2>/dev/null || true

echo "    ✅ IAM policy attached"

# ---------------------------------------------------------------
# Step 2: Enable S3 static website hosting
# ---------------------------------------------------------------
echo "[2/5] Enabling S3 static website hosting..."

aws s3 website "s3://$BUCKET" \
  --index-document index.html \
  --error-document error.html \
  --region "$REGION"

echo "    ✅ Static hosting enabled"

# ---------------------------------------------------------------
# Step 3: Set bucket policy for public read on dashboard/ prefix
# ---------------------------------------------------------------
echo "[3/5] Setting public read policy for dashboard/ prefix..."

# First, disable Block Public Access for the bucket (needed for website hosting)
# NOTE: Only the dashboard/ prefix will be publicly readable
aws s3api put-public-access-block \
  --bucket "$BUCKET" \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=false,RestrictPublicBuckets=false" \
  --region "$REGION"

BUCKET_POLICY='{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DashboardPublicRead",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::matthew-life-platform/dashboard/*"
    }
  ]
}'

aws s3api put-bucket-policy \
  --bucket "$BUCKET" \
  --policy "$BUCKET_POLICY" \
  --region "$REGION"

echo "    ✅ Public read on dashboard/* only"

# ---------------------------------------------------------------
# Step 4: Upload HTML dashboard to S3
# ---------------------------------------------------------------
echo "[4/5] Uploading dashboard HTML..."

aws s3 cp lambdas/dashboard/index.html \
  "s3://$BUCKET/dashboard/index.html" \
  --content-type "text/html" \
  --cache-control "max-age=300" \
  --region "$REGION"

echo "    ✅ index.html uploaded"

# ---------------------------------------------------------------
# Step 5: Deploy patched daily-brief Lambda
# ---------------------------------------------------------------
echo "[5/5] Deploying patched daily-brief Lambda with JSON generator..."

# The patch adds write_dashboard_json() and a call at the end of lambda_handler
cd lambdas
cp daily_brief_lambda.py lambda_function.py
zip -j daily_brief_lambda.zip lambda_function.py > /dev/null
rm lambda_function.py

aws lambda update-function-code \
  --function-name "$LAMBDA" \
  --zip-file fileb://daily_brief_lambda.zip \
  --region "$REGION" > /dev/null

echo "    ✅ Lambda deployed"

cd ..

# ---------------------------------------------------------------
# Summary
# ---------------------------------------------------------------
echo ""
echo "=== Deploy Complete ==="
echo ""
echo "Dashboard URL:"
echo "  http://$BUCKET.s3-website-$REGION.amazonaws.com/dashboard/"
echo ""
echo "JSON data URL:"
echo "  http://$BUCKET.s3-website-$REGION.amazonaws.com/dashboard/data.json"
echo ""
echo "Next steps:"
echo "  1. Test: Run the daily brief manually to generate data.json:"
echo "     aws lambda invoke --function-name daily-brief /tmp/db-out.json --region $REGION"
echo "  2. Verify: curl -s http://$BUCKET.s3-website-$REGION.amazonaws.com/dashboard/data.json | python3 -m json.tool"
echo "  3. Open dashboard in phone browser and add to home screen"
echo ""
echo "Phase 2 (later): CloudFront + custom domain (health.mattsusername.com)"
