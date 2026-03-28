#!/bin/bash
# deploy/deploy_og_image.sh
# WR-17: Deploy the dynamic OG image Lambda to us-east-1.
# Creates the Lambda, Function URL, and wires CloudFront behavior.
#
# Run once to set up. Subsequent code updates:
#   bash deploy/deploy_og_image.sh --update-code
#
# Usage:
#   bash deploy/deploy_og_image.sh          # full setup
#   bash deploy/deploy_og_image.sh --update-code  # code update only

set -euo pipefail

REGION="us-east-1"
FUNCTION_NAME="life-platform-og-image"
BUCKET="matthew-life-platform"
ACCOUNT="205930651321"
CF_DIST="E3S424OXQZ8NBE"
SOURCE="lambdas/og_image_lambda.mjs"
UPDATE_ONLY="${1:-}"

echo "=== OG Image Lambda Deploy (WR-17) ==="

# ── Package ──────────────────────────────────────────────────
echo "📦 Packaging Lambda..."
mkdir -p /tmp/og_image_deploy
cp "$SOURCE" /tmp/og_image_deploy/og_image_lambda.mjs
cd /tmp/og_image_deploy && zip -q deploy.zip og_image_lambda.mjs && cd -
echo "   ✓ Packaged"

if [ "$UPDATE_ONLY" = "--update-code" ]; then
  echo "🚀 Updating code only..."
  aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file fileb:///tmp/og_image_deploy/deploy.zip \
    --region "$REGION" \
    --no-cli-pager
  echo "✅ Code updated."
  exit 0
fi

# ── Create IAM role ───────────────────────────────────────────
echo "🔐 Creating IAM role..."
ROLE_ARN=$(aws iam create-role \
  --role-name life-platform-og-image-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }' \
  --region "$REGION" \
  --query "Role.Arn" --output text --no-cli-pager 2>/dev/null || \
  aws iam get-role --role-name life-platform-og-image-role \
    --query "Role.Arn" --output text --no-cli-pager)

aws iam attach-role-policy \
  --role-name life-platform-og-image-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole \
  --no-cli-pager 2>/dev/null || true

aws iam put-role-policy \
  --role-name life-platform-og-image-role \
  --policy-name s3-read-public-stats \
  --policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [{
      \"Effect\": \"Allow\",
      \"Action\": \"s3:GetObject\",
      \"Resource\": \"arn:aws:s3:::$BUCKET/site/data/public_stats.json\"
    }]
  }" --no-cli-pager

echo "   ✓ IAM role: $ROLE_ARN"
echo "   Waiting 10s for role propagation..."
sleep 10

# ── Create Lambda ─────────────────────────────────────────────
echo "🚀 Creating Lambda function..."
aws lambda create-function \
  --function-name "$FUNCTION_NAME" \
  --runtime nodejs20.x \
  --role "$ROLE_ARN" \
  --handler og_image_lambda.handler \
  --zip-file fileb:///tmp/og_image_deploy/deploy.zip \
  --timeout 10 \
  --memory-size 256 \
  --region "$REGION" \
  --environment "Variables={S3_REGION=us-west-2}" \
  --no-cli-pager

# ── Add Function URL ──────────────────────────────────────────
echo "🌐 Adding Function URL..."
FN_URL=$(aws lambda create-function-url-config \
  --function-name "$FUNCTION_NAME" \
  --auth-type NONE \
  --cors '{
    "AllowMethods": ["GET"],
    "AllowOrigins": ["https://averagejoematt.com", "https://www.averagejoematt.com"]
  }' \
  --region "$REGION" \
  --query "FunctionUrl" --output text --no-cli-pager)

aws lambda add-permission \
  --function-name "$FUNCTION_NAME" \
  --statement-id FunctionURLPublicAccess \
  --action lambda:InvokeFunctionUrl \
  --principal "*" \
  --function-url-auth-type NONE \
  --region "$REGION" \
  --no-cli-pager > /dev/null

echo ""
echo "✅ OG Image Lambda deployed!"
echo ""
echo "   Function URL: $FN_URL"
echo ""
echo "NEXT STEPS:"
echo "  1. Add a CloudFront behavior for /og → og-image Lambda Function URL"
echo "     (add it to web_stack.py CacheBehaviors, before /api/*)"
echo ""
echo "  2. Update OG meta tags across all pages:"
echo "     Change: content=\"https://averagejoematt.com/assets/images/og-image.png\""
echo "     To:     content=\"https://averagejoematt.com/og\""
echo "     Run:    python3 deploy/fix_site_meta.py --og-url"
echo ""
echo "  3. Test with social debuggers:"
echo "     - Twitter: https://cards-dev.twitter.com/validator"
echo "     - Facebook: https://developers.facebook.com/tools/debug/"
echo "     - LinkedIn: https://www.linkedin.com/post-inspector/"
