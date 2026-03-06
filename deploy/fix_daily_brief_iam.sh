#!/bin/bash
set -euo pipefail

# Fix: Add dynamodb:PutItem to daily-brief Lambda role
# The daily-brief Lambda uses lambda-weekly-digest-role which only has
# GetItem + Query. v2.0+ persists day_grade records and needs PutItem.
# This was causing AccessDeniedException on every run since v2.0.

ROLE_NAME="lambda-weekly-digest-role"
POLICY_NAME="weekly-digest-access"

echo "═══════════════════════════════════════════════════"
echo " Fix: Add dynamodb:PutItem to daily-brief role"
echo "═══════════════════════════════════════════════════"

echo ""
echo "Current policy actions: GetItem, Query (missing PutItem)"
echo "Adding: dynamodb:PutItem"
echo ""

# Update the inline policy with PutItem added
aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "$POLICY_NAME" \
    --policy-document '{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "dynamodb:GetItem",
                    "dynamodb:Query",
                    "dynamodb:PutItem"
                ],
                "Resource": "arn:aws:dynamodb:us-west-2:205930651321:table/life-platform"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "secretsmanager:GetSecretValue"
                ],
                "Resource": "arn:aws:secretsmanager:us-west-2:205930651321:secret:life-platform/anthropic*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "ses:SendEmail",
                    "sesv2:SendEmail"
                ],
                "Resource": "*"
            }
        ]
    }'

echo "✅ Policy updated. Verifying..."

# Verify
ACTIONS=$(aws iam get-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "$POLICY_NAME" \
    --query "PolicyDocument.Statement[0].Action" \
    --output text)

echo "  DynamoDB actions: $ACTIONS"
echo ""
echo "═══════════════════════════════════════════════════"
echo " ✅ Done. Day grade persistence will work on next run."
echo "═══════════════════════════════════════════════════"
