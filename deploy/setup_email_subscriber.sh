#!/bin/bash
# setup_email_subscriber.sh — First-time create for email-subscriber Lambda (BS-03)
# Run ONCE before deploy_v3755_session.sh
# After this script succeeds, subsequent deploys use deploy_lambda.sh normally.
set -e
ACCT="205930651321"
REGION="us-west-2"
TABLE_ARN="arn:aws:dynamodb:${REGION}:${ACCT}:table/life-platform"
KMS_KEY_ARN="arn:aws:kms:${REGION}:${ACCT}:key/444438d1-a5e0-43b8-9391-3cd2d70dde4d"
SES_IDENTITY="arn:aws:ses:${REGION}:${ACCT}:identity/mattsusername.com"
DLQ_ARN="arn:aws:sqs:${REGION}:${ACCT}:life-platform-ingestion-dlq"
ROLE_NAME="lambda-email-subscriber-role"
FUNCTION_NAME="email-subscriber"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== email-subscriber First-Time Setup ==="
echo ""

# ── 1. Check if Lambda already exists (idempotent)
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" > /dev/null 2>&1; then
  echo "  ✓ $FUNCTION_NAME already exists — skipping creation."
  echo "    Run deploy_v3755_session.sh directly."
  exit 0
fi

# ── 2. Create IAM role
echo "[1/4] Creating IAM role $ROLE_NAME..."
ROLE_EXISTS=$(aws iam get-role --role-name "$ROLE_NAME" --query "Role.Arn" --output text 2>/dev/null || echo "")
if [ -z "$ROLE_EXISTS" ]; then
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document '{
      "Version": "2012-10-17",
      "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "lambda.amazonaws.com"},
        "Action": "sts:AssumeRole"
      }]
    }' \
    --region "$REGION" > /dev/null
  echo "    ✓ Role created"
else
  echo "    ✓ Role already exists"
fi
ROLE_ARN="arn:aws:iam::${ACCT}:role/${ROLE_NAME}"

# ── 3. Attach inline policies
echo "[2/4] Attaching inline policies..."

aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name "DynamoDB" \
  --policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [{
      \"Sid\": \"DynamoDB\",
      \"Effect\": \"Allow\",
      \"Action\": [\"dynamodb:GetItem\",\"dynamodb:PutItem\",\"dynamodb:UpdateItem\",\"dynamodb:Query\"],
      \"Resource\": \"${TABLE_ARN}\"
    }]
  }"

aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name "KMS" \
  --policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [{
      \"Sid\": \"KMS\",
      \"Effect\": \"Allow\",
      \"Action\": [\"kms:Decrypt\",\"kms:GenerateDataKey\"],
      \"Resource\": \"${KMS_KEY_ARN}\"
    }]
  }"

aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name "SES" \
  --policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [{
      \"Sid\": \"SES\",
      \"Effect\": \"Allow\",
      \"Action\": [\"ses:SendEmail\",\"sesv2:SendEmail\"],
      \"Resource\": \"${SES_IDENTITY}\"
    }]
  }"

aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name "DLQ" \
  --policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [{
      \"Sid\": \"DLQ\",
      \"Effect\": \"Allow\",
      \"Action\": \"sqs:SendMessage\",
      \"Resource\": \"${DLQ_ARN}\"
    }]
  }"

aws iam attach-role-policy --role-name "$ROLE_NAME" \
  --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

echo "    ✓ Policies attached"
echo "    Waiting 15s for IAM propagation..."
sleep 15

# ── 4. Zip and create Lambda
echo "[3/4] Zipping email_subscriber_lambda.py..."
zip -j /tmp/email_subscriber_setup.zip lambdas/email_subscriber_lambda.py
echo "    ✓ Zip created"

echo "[4/4] Creating Lambda function..."
aws lambda create-function \
  --function-name "$FUNCTION_NAME" \
  --runtime python3.12 \
  --handler email_subscriber_lambda.lambda_handler \
  --role "$ROLE_ARN" \
  --environment "Variables={USER_ID=matthew,TABLE_NAME=life-platform,S3_BUCKET=matthew-life-platform,EMAIL_SENDER=lifeplatform@mattsusername.com,SITE_URL=https://averagejoematt.com}" \
  --timeout 15 \
  --memory-size 256 \
  --region "$REGION" \
  --zip-file fileb:///tmp/email_subscriber_setup.zip \
  > /dev/null
echo "    ✓ Lambda created"

echo ""
echo "=== email-subscriber setup complete ==="
echo "Now run: bash deploy/deploy_v3755_session.sh"
