#!/bin/bash
set -euo pipefail

# Feature #15: MCP API Key Rotation — 90-day auto-rotation
# Creates rotator Lambda, configures Secrets Manager rotation, updates MCP handler Bearer cache TTL.
#
# What this does:
# 1. Creates IAM role for the rotator Lambda
# 2. Packages & deploys the rotator Lambda
# 3. Grants Secrets Manager permission to invoke the rotator
# 4. Configures 90-day auto-rotation on the MCP API key secret
# 5. Repackages & deploys the MCP Lambda (handler.py already edited with Bearer cache TTL)
#
# After rotation happens (or manual trigger):
#   ./sync_bridge_key.sh   (updates .config.json for bridge transport)

REGION="us-west-2"
ACCOUNT_ID="205930651321"
SECRET_ID="life-platform/mcp-api-key"
ROTATOR_FUNCTION="life-platform-key-rotator"
ROTATOR_ROLE="lambda-key-rotator-role"
MCP_FUNCTION="life-platform-mcp"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "═══════════════════════════════════════════════════"
echo "Feature #15: MCP API Key Rotation"
echo "═══════════════════════════════════════════════════"

# ── Phase 1: IAM Role for Rotator Lambda ──────────────────────────────────────
echo ""
echo "Phase 1: Creating IAM role for rotator Lambda..."

TRUST_POLICY='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}'

# Create role (ignore if exists)
aws iam create-role \
  --role-name "$ROTATOR_ROLE" \
  --assume-role-policy-document "$TRUST_POLICY" \
  --region "$REGION" 2>/dev/null || echo "  Role already exists"

# Attach basic Lambda execution
aws iam attach-role-policy \
  --role-name "$ROTATOR_ROLE" \
  --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" 2>/dev/null || true

# Inline policy for Secrets Manager rotation operations
ROTATION_POLICY='{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:PutSecretValue",
        "secretsmanager:DescribeSecret",
        "secretsmanager:UpdateSecretVersionStage"
      ],
      "Resource": "arn:aws:secretsmanager:'"$REGION"':'"$ACCOUNT_ID"':secret:life-platform/mcp-api-key-*"
    }
  ]
}'

aws iam put-role-policy \
  --role-name "$ROTATOR_ROLE" \
  --policy-name "SecretsManagerRotation" \
  --policy-document "$ROTATION_POLICY"

echo "  ✅ Role ready: $ROTATOR_ROLE"

# Wait for role propagation
echo "  Waiting 10s for IAM propagation..."
sleep 10

# ── Phase 2: Package & Deploy Rotator Lambda ─────────────────────────────────
echo ""
echo "Phase 2: Deploying rotator Lambda..."

cd "$PROJECT_DIR/lambdas"

# Package
cp key_rotator_lambda.py lambda_function.py
zip -q key_rotator.zip lambda_function.py
rm lambda_function.py

# Create or update
if aws lambda get-function --function-name "$ROTATOR_FUNCTION" --region "$REGION" 2>/dev/null; then
  echo "  Updating existing Lambda..."
  aws lambda update-function-code \
    --function-name "$ROTATOR_FUNCTION" \
    --zip-file fileb://key_rotator.zip \
    --region "$REGION" > /dev/null
  sleep 5
  aws lambda update-function-configuration \
    --function-name "$ROTATOR_FUNCTION" \
    --timeout 30 \
    --memory-size 128 \
    --runtime python3.12 \
    --region "$REGION" > /dev/null
else
  echo "  Creating new Lambda..."
  aws lambda create-function \
    --function-name "$ROTATOR_FUNCTION" \
    --runtime python3.12 \
    --handler lambda_function.lambda_handler \
    --role "arn:aws:iam::${ACCOUNT_ID}:role/${ROTATOR_ROLE}" \
    --zip-file fileb://key_rotator.zip \
    --timeout 30 \
    --memory-size 128 \
    --region "$REGION" > /dev/null
fi

echo "  ✅ Rotator Lambda deployed: $ROTATOR_FUNCTION"

# ── Phase 3: Grant Secrets Manager Permission to Invoke ──────────────────────
echo ""
echo "Phase 3: Adding Secrets Manager invoke permission..."

aws lambda add-permission \
  --function-name "$ROTATOR_FUNCTION" \
  --statement-id "SecretsManagerInvoke" \
  --action "lambda:InvokeFunction" \
  --principal "secretsmanager.amazonaws.com" \
  --source-arn "arn:aws:secretsmanager:${REGION}:${ACCOUNT_ID}:secret:life-platform/mcp-api-key-*" \
  --region "$REGION" 2>/dev/null || echo "  Permission already exists"

echo "  ✅ Permission granted"

# ── Phase 4: Configure 90-Day Auto-Rotation ──────────────────────────────────
echo ""
echo "Phase 4: Configuring 90-day auto-rotation..."

aws secretsmanager rotate-secret \
  --secret-id "$SECRET_ID" \
  --rotation-lambda-arn "arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${ROTATOR_FUNCTION}" \
  --rotation-rules '{"AutomaticallyAfterDays": 90}' \
  --region "$REGION" > /dev/null

echo "  ✅ Auto-rotation configured: every 90 days"

# ── Phase 5: Repackage & Deploy MCP Lambda ───────────────────────────────────
echo ""
echo "Phase 5: Repackaging MCP Lambda with Bearer cache TTL..."

cd "$PROJECT_DIR"
zip -r lambdas/mcp_server.zip mcp_server.py mcp/ -x '*__pycache__*' > /dev/null

aws lambda update-function-code \
  --function-name "$MCP_FUNCTION" \
  --zip-file fileb://lambdas/mcp_server.zip \
  --region "$REGION" > /dev/null

echo "  ✅ MCP Lambda updated with Bearer cache TTL"

# ── Phase 6: Verify ──────────────────────────────────────────────────────────
echo ""
echo "Phase 6: Verification..."

echo "  Rotation config:"
aws secretsmanager describe-secret \
  --secret-id "$SECRET_ID" \
  --region "$REGION" \
  --query '{RotationEnabled: RotationEnabled, RotationRules: RotationRules, RotationLambdaARN: RotationLambdaARN}' \
  --output json

echo ""
echo "═══════════════════════════════════════════════════"
echo "✅ Feature #15 complete!"
echo ""
echo "  Rotation:      Every 90 days (automatic)"
echo "  Rotator:       $ROTATOR_FUNCTION"
echo "  Bearer TTL:    5 min (warm containers pick up new key)"
echo "  Bridge sync:   ./deploy/sync_bridge_key.sh"
echo ""
echo "  Test rotation: aws secretsmanager rotate-secret --secret-id $SECRET_ID --region $REGION"
echo "  Then run:      ./deploy/sync_bridge_key.sh"
echo "═══════════════════════════════════════════════════"
