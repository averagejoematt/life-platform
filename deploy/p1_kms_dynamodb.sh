#!/bin/bash
# p1_kms_dynamodb.sh — P1.5: KMS CMK for DynamoDB table encryption
#
# Replaces AWS-owned default encryption with a Customer Managed Key (CMK).
# Applies to the entire life-platform DynamoDB table — genome, lab, and all
# other health data now encrypted under a key you control.
#
# Benefits over default AWS-owned keys:
#   - You control key rotation (annual automatic rotation enabled)
#   - CloudTrail logs every Decrypt/GenerateDataKey call
#   - Key can be disabled to revoke all data access instantly
#   - Satisfies HIPAA/GDPR key management requirements
#
# Cost: ~$1/month (CMK) + $0.03/10K API calls (negligible at our scale)
#
# NOTE: Table update is transparent to application code — no Lambda changes needed.
#       DynamoDB handles encryption/decryption transparently at rest.
#
# Usage: cd ~/Documents/Claude/life-platform && bash deploy/p1_kms_dynamodb.sh

set -euo pipefail
REGION="us-west-2"
ACCOUNT="205930651321"
TABLE="life-platform"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  P1.5: KMS CMK for DynamoDB encryption                     ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Check current encryption state ────────────────────────────────────
echo "── Step 1: Current DynamoDB encryption state ──"
CURRENT_KEY=$(aws dynamodb describe-table \
    --table-name "$TABLE" --region "$REGION" \
    --query "Table.SSEDescription" --output json --no-cli-pager 2>/dev/null || echo "null")
echo "  $CURRENT_KEY"
echo ""

# ── Step 2: Create KMS CMK ────────────────────────────────────────────────────
echo "── Step 2: Creating KMS Customer Managed Key ──"

# Check if key already exists (idempotency)
EXISTING_KEY=$(aws kms list-aliases --region "$REGION" --no-cli-pager \
    --query "Aliases[?AliasName=='alias/life-platform-dynamodb'].TargetKeyId" \
    --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_KEY" ] && [ "$EXISTING_KEY" != "None" ]; then
    KEY_ID="$EXISTING_KEY"
    echo "  ✅ Key already exists: $KEY_ID"
else
    KEY_ID=$(aws kms create-key \
        --region "$REGION" \
        --description "Life Platform DynamoDB encryption — health data at rest (genome, lab, all sources)" \
        --key-usage ENCRYPT_DECRYPT \
        --origin AWS_KMS \
        --no-cli-pager \
        --query "KeyMetadata.KeyId" --output text)

    echo "  Created key: $KEY_ID"

    # Create alias for easy reference
    aws kms create-alias \
        --alias-name "alias/life-platform-dynamodb" \
        --target-key-id "$KEY_ID" \
        --region "$REGION" \
        --no-cli-pager
    echo "  Alias: alias/life-platform-dynamodb"
fi

KEY_ARN="arn:aws:kms:$REGION:$ACCOUNT:key/$KEY_ID"
echo ""

# ── Step 3: Enable automatic key rotation (annual) ───────────────────────────
echo "── Step 3: Enabling automatic key rotation ──"
aws kms enable-key-rotation \
    --key-id "$KEY_ID" \
    --region "$REGION" \
    --no-cli-pager
echo "  ✅ Annual key rotation enabled"
echo ""

# ── Step 4: Add key policy allowing Lambda roles to use the key ───────────────
echo "── Step 4: Updating key policy (grant Lambda roles decrypt access) ──"

KEY_POLICY=$(python3 - <<PYEOF
import json

policy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "KeyAdminAccess",
            "Effect": "Allow",
            "Principal": {
                "AWS": "arn:aws:iam::205930651321:root"
            },
            "Action": "kms:*",
            "Resource": "*"
        },
        {
            "Sid": "LambdaDynamoDBAccess",
            "Effect": "Allow",
            "Principal": {
                "AWS": [
                    "arn:aws:iam::205930651321:role/life-platform-compute-role",
                    "arn:aws:iam::205930651321:role/life-platform-email-role",
                    "arn:aws:iam::205930651321:role/life-platform-digest-role",
                    "arn:aws:iam::205930651321:role/lambda-strava-role",
                    "arn:aws:iam::205930651321:role/lambda-weekly-digest-role"
                ]
            },
            "Action": [
                "kms:Decrypt",
                "kms:GenerateDataKey",
                "kms:DescribeKey"
            ],
            "Resource": "*"
        },
        {
            "Sid": "DynamoDBServiceAccess",
            "Effect": "Allow",
            "Principal": {
                "Service": "dynamodb.amazonaws.com"
            },
            "Action": [
                "kms:Decrypt",
                "kms:GenerateDataKey",
                "kms:DescribeKey"
            ],
            "Resource": "*"
        }
    ]
}
print(json.dumps(policy))
PYEOF
)

aws kms put-key-policy \
    --key-id "$KEY_ID" \
    --policy-name "default" \
    --policy "$KEY_POLICY" \
    --region "$REGION" \
    --no-cli-pager
echo "  ✅ Key policy updated (root admin + Lambda roles + DynamoDB service)"
echo ""

# ── Step 5: Get ALL Lambda execution roles and add them to the key policy ─────
echo "── Step 5: Discovering all Lambda execution roles ──"
ALL_ROLES=$(aws lambda list-functions \
    --region "$REGION" --no-cli-pager \
    --query "Functions[].Role" --output text | tr '\t' '\n' | sort -u)

echo "  Lambda roles found:"
echo "$ALL_ROLES" | while read -r role; do echo "    $role"; done
echo ""

# Build an updated policy with all discovered roles
KEY_POLICY_FULL=$(python3 - "$ALL_ROLES" <<PYEOF
import json, sys

roles_raw = sys.argv[1]
roles = [r.strip() for r in roles_raw.strip().splitlines() if r.strip()]

policy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "KeyAdminAccess",
            "Effect": "Allow",
            "Principal": {"AWS": "arn:aws:iam::205930651321:root"},
            "Action": "kms:*",
            "Resource": "*"
        },
        {
            "Sid": "LambdaDecryptAccess",
            "Effect": "Allow",
            "Principal": {"AWS": roles},
            "Action": ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"],
            "Resource": "*"
        },
        {
            "Sid": "DynamoDBServiceAccess",
            "Effect": "Allow",
            "Principal": {"Service": "dynamodb.amazonaws.com"},
            "Action": ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"],
            "Resource": "*"
        }
    ]
}
print(json.dumps(policy))
PYEOF
)

aws kms put-key-policy \
    --key-id "$KEY_ID" \
    --policy-name "default" \
    --policy "$KEY_POLICY_FULL" \
    --region "$REGION" \
    --no-cli-pager
echo "  ✅ Key policy updated with all Lambda roles"
echo ""

# ── Step 6: Enable SSE on DynamoDB table with CMK ────────────────────────────
echo "── Step 6: Updating DynamoDB table SSE → CMK ──"
echo "  (This is a live table update — takes 5-10 seconds, zero downtime)"

aws dynamodb update-table \
    --table-name "$TABLE" \
    --region "$REGION" \
    --no-cli-pager \
    --sse-specification "Enabled=true,SSEType=KMS,KMSMasterKeyId=$KEY_ARN" > /dev/null

echo -n "  Waiting for table to become ACTIVE..."
while true; do
    STATUS=$(aws dynamodb describe-table \
        --table-name "$TABLE" --region "$REGION" \
        --query "Table.TableStatus" --output text --no-cli-pager)
    if [ "$STATUS" = "ACTIVE" ]; then
        break
    fi
    echo -n "."
    sleep 3
done
echo " done"

# ── Step 7: Verify ────────────────────────────────────────────────────────────
echo ""
echo "── Step 7: Verification ──"
aws dynamodb describe-table \
    --table-name "$TABLE" --region "$REGION" \
    --query "Table.SSEDescription" --output json --no-cli-pager

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✅ P1.5 KMS Encryption Complete                            ║"
echo "║                                                              ║"
echo "║  Key: alias/life-platform-dynamodb                          ║"
echo "║  Table: life-platform (all health data now under CMK)       ║"
echo "║  Rotation: Annual (automatic)                               ║"
echo "║  Audit: Every Decrypt/GenerateDataKey in CloudTrail          ║"
echo "║                                                              ║"
echo "║  Save the key ID for INFRASTRUCTURE.md:                     ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo "  Key ID: $KEY_ID"
echo "  Key ARN: $KEY_ARN"
