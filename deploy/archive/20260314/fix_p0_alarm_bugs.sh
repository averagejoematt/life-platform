#!/bin/bash
# P0 Fix: 4 Lambda bugs causing alarm flood
# Run from life-platform project root
# 2026-03-12 v3.7.4

set -euo pipefail
REGION="us-west-2"

echo "=== Fix 1: Freshness checker handler ==="
# CDK reconcile set handler to lambda_function.lambda_handler
# but file is freshness_checker_lambda.py
aws lambda update-function-configuration \
  --function-name life-platform-freshness-checker \
  --handler freshness_checker_lambda.lambda_handler \
  --region $REGION \
  --query 'Handler' --output text
echo "✅ Freshness checker handler fixed"

echo ""
echo "=== Fix 2: Todoist IAM — S3 path mismatch ==="
# CDK reconcile changed policy to raw/matthew/todoist/*
# but Lambda writes to raw/todoist/* (no matthew/ prefix)
aws iam put-role-policy \
  --role-name LifePlatformIngestion-TodoistIngestionRole542F9A6C-NmB0s7tHyVeE \
  --policy-name TodoistIngestionRoleDefaultPolicy343C162F \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Sid": "DynamoDB",
        "Effect": "Allow",
        "Action": ["dynamodb:GetItem","dynamodb:PutItem","dynamodb:Query","dynamodb:UpdateItem"],
        "Resource": "arn:aws:dynamodb:us-west-2:205930651321:table/life-platform"
      },
      {
        "Sid": "KMS",
        "Effect": "Allow",
        "Action": ["kms:Decrypt","kms:GenerateDataKey"],
        "Resource": "arn:aws:kms:us-west-2:205930651321:key/444438d1-a5e0-43b8-9391-3cd2d70dde4d"
      },
      {
        "Sid": "S3Write",
        "Effect": "Allow",
        "Action": "s3:PutObject",
        "Resource": "arn:aws:s3:::matthew-life-platform/raw/todoist/*"
      },
      {
        "Sid": "Secrets",
        "Effect": "Allow",
        "Action": ["secretsmanager:GetSecretValue","secretsmanager:UpdateSecret"],
        "Resource": "arn:aws:secretsmanager:us-west-2:205930651321:secret:life-platform/ingestion-keys*"
      },
      {
        "Sid": "DLQ",
        "Effect": "Allow",
        "Action": "sqs:SendMessage",
        "Resource": "arn:aws:sqs:us-west-2:205930651321:life-platform-ingestion-dlq"
      }
    ]
  }'
echo "✅ Todoist IAM S3 path fixed"

echo ""
echo "=== Fix 3: Reset stale alarms to OK ==="
aws cloudwatch set-alarm-state \
  --alarm-name "ingestion-error-monday-compass" \
  --state-value OK \
  --state-reason "Monday Compass code updated to use ai-keys (not api-keys). Will self-heal Monday 2026-03-16." \
  --region $REGION
echo "  ✅ ingestion-error-monday-compass → OK"

aws cloudwatch set-alarm-state \
  --alarm-name "ingestion-error-failure-pattern-compute" \
  --state-value OK \
  --state-reason "Stale alarm from 2026-03-09 error; Lambda ran successfully same day. No recurrence." \
  --region $REGION
echo "  ✅ ingestion-error-failure-pattern-compute → OK"

echo ""
echo "=== All AWS fixes applied ==="
echo "Remaining: Fix 4 (daily-insight-compute code) needs Lambda redeploy after code fix."
echo "See deploy_p0_fix_daily_insight.sh"
