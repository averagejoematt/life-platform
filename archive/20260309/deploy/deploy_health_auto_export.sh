#!/bin/bash
# deploy_health_auto_export.sh — Deploy Health Auto Export webhook Lambda
# 
# Creates:
#   1. Secrets Manager secret with API key
#   2. IAM role for the Lambda
#   3. Lambda function
#   4. API Gateway HTTP endpoint (POST /ingest)
#   No EventBridge schedule (webhook-triggered, not scheduled)
#
# Usage: bash deploy_health_auto_export.sh

set -euo pipefail

REGION="us-west-2"
ACCOUNT_ID="205930651321"
FUNCTION_NAME="health-auto-export-webhook"
ROLE_NAME="lambda-health-auto-export-role"
SECRET_NAME="life-platform/health-auto-export"
S3_BUCKET="matthew-life-platform"
DYNAMODB_TABLE="life-platform"
ZIP_FILE="health_auto_export_lambda.zip"
LAMBDA_FILE="health_auto_export_lambda.py"
API_NAME="health-auto-export-api"
TIMEOUT=30
MEMORY=256

echo "=== Deploy Health Auto Export Webhook ==="
echo ""

# ── Step 1: Generate API key and create/update secret ──────────────────────────
echo "Step 1: Setting up Secrets Manager..."

# Generate a random API key
API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

# Check if secret exists
if aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$REGION" 2>/dev/null; then
    echo "  Secret exists, updating..."
    aws secretsmanager update-secret \
        --secret-id "$SECRET_NAME" \
        --secret-string "{\"api_key\": \"$API_KEY\"}" \
        --region "$REGION"
else
    echo "  Creating new secret..."
    aws secretsmanager create-secret \
        --name "$SECRET_NAME" \
        --secret-string "{\"api_key\": \"$API_KEY\"}" \
        --region "$REGION"
fi
echo "  ✓ API key generated and stored"
echo ""

# ── Step 2: Create IAM role ────────────────────────────────────────────────────
echo "Step 2: Creating IAM role..."

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
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" \
    --region "$REGION" 2>/dev/null || echo "  Role already exists"

# Attach basic Lambda execution
aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

# Inline policy for DynamoDB, S3, Secrets Manager
INLINE_POLICY='{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:UpdateItem",
        "dynamodb:GetItem",
        "dynamodb:PutItem"
      ],
      "Resource": "arn:aws:dynamodb:'"$REGION"':'"$ACCOUNT_ID"':table/'"$DYNAMODB_TABLE"'"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject"
      ],
      "Resource": "arn:aws:s3:::'"$S3_BUCKET"'/raw/*"
    },
    {
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "arn:aws:secretsmanager:'"$REGION"':'"$ACCOUNT_ID"':secret:'"$SECRET_NAME"'*"
    }
  ]
}'

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "health-auto-export-access" \
    --policy-document "$INLINE_POLICY"

echo "  ✓ IAM role configured"
echo ""

# Wait for role propagation
echo "  Waiting 10s for IAM propagation..."
sleep 10

# ── Step 3: Package Lambda ─────────────────────────────────────────────────────
echo "Step 3: Packaging Lambda..."

cd "$(dirname "$0")"
zip -j "$ZIP_FILE" "$LAMBDA_FILE"
echo "  ✓ Packaged $ZIP_FILE"
echo ""

# ── Step 4: Create or update Lambda function ───────────────────────────────────
echo "Step 4: Deploying Lambda function..."

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" 2>/dev/null; then
    echo "  Updating existing function..."
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file "fileb://$ZIP_FILE" \
        --region "$REGION" > /dev/null

    # Wait for update to complete
    aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"

    aws lambda update-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --timeout "$TIMEOUT" \
        --memory-size "$MEMORY" \
        --environment "Variables={S3_BUCKET=$S3_BUCKET,DYNAMODB_TABLE=$DYNAMODB_TABLE,SECRET_NAME=$SECRET_NAME}" \
        --region "$REGION" > /dev/null
else
    echo "  Creating new function..."
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.12 \
        --handler "health_auto_export_lambda.lambda_handler" \
        --role "$ROLE_ARN" \
        --zip-file "fileb://$ZIP_FILE" \
        --timeout "$TIMEOUT" \
        --memory-size "$MEMORY" \
        --environment "Variables={S3_BUCKET=$S3_BUCKET,DYNAMODB_TABLE=$DYNAMODB_TABLE,SECRET_NAME=$SECRET_NAME}" \
        --region "$REGION" > /dev/null

    # Wait for function to be active
    aws lambda wait function-active --function-name "$FUNCTION_NAME" --region "$REGION"
fi
echo "  ✓ Lambda deployed"
echo ""

# ── Step 5: Create API Gateway HTTP API ────────────────────────────────────────
echo "Step 5: Setting up API Gateway..."

# Check if API already exists
API_ID=$(aws apigatewayv2 get-apis --region "$REGION" \
    | python3 -c "
import sys, json
apis = json.load(sys.stdin)['Items']
match = [a for a in apis if a['Name'] == '$API_NAME']
print(match[0]['ApiId'] if match else '')
" 2>/dev/null || echo "")

if [ -n "$API_ID" ]; then
    echo "  API Gateway already exists: $API_ID"
    ENDPOINT=$(aws apigatewayv2 get-api --api-id "$API_ID" --region "$REGION" \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['ApiEndpoint'])")
else
    echo "  Creating HTTP API..."
    API_RESULT=$(aws apigatewayv2 create-api \
        --name "$API_NAME" \
        --protocol-type HTTP \
        --region "$REGION")
    API_ID=$(echo "$API_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['ApiId'])")
    ENDPOINT=$(echo "$API_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['ApiEndpoint'])")

    # Create integration
    INTEGRATION_ID=$(aws apigatewayv2 create-integration \
        --api-id "$API_ID" \
        --integration-type AWS_PROXY \
        --integration-uri "arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}" \
        --payload-format-version 2.0 \
        --region "$REGION" \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['IntegrationId'])")

    # Create route
    aws apigatewayv2 create-route \
        --api-id "$API_ID" \
        --route-key "POST /ingest" \
        --target "integrations/$INTEGRATION_ID" \
        --region "$REGION" > /dev/null

    # Create default stage with auto-deploy
    aws apigatewayv2 create-stage \
        --api-id "$API_ID" \
        --stage-name '$default' \
        --auto-deploy \
        --region "$REGION" > /dev/null

    # Grant API Gateway permission to invoke Lambda
    aws lambda add-permission \
        --function-name "$FUNCTION_NAME" \
        --statement-id "ApiGatewayInvoke" \
        --action "lambda:InvokeFunction" \
        --principal "apigateway.amazonaws.com" \
        --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT_ID}:${API_ID}/*/*" \
        --region "$REGION" 2>/dev/null || echo "  Permission already exists"

    echo "  ✓ API Gateway created"
fi

WEBHOOK_URL="${ENDPOINT}/ingest"
echo "  ✓ Webhook URL: $WEBHOOK_URL"
echo ""

# ── Step 6: Cleanup ────────────────────────────────────────────────────────────
rm -f "$ZIP_FILE"

# ── Done ───────────────────────────────────────────────────────────────────────
echo "============================================================"
echo "Deployment complete!"
echo ""
echo "Webhook URL: $WEBHOOK_URL"
echo ""
echo "API Key: $API_KEY"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  SAVE THIS API KEY — you'll need it for the iOS app."
echo "  It's also stored in Secrets Manager: $SECRET_NAME"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Health Auto Export iOS app configuration:"
echo "  1. Install 'Health Auto Export' from App Store"
echo "  2. Purchase Premium (lifetime option available) or use 7-day trial"
echo "  3. Go to Automations → Create New → REST API"
echo "  4. URL: ${WEBHOOK_URL}"
echo "  5. Headers: Authorization = Bearer $API_KEY"
echo "  6. Data Type: Health Metrics"
echo "  7. Select Health Metrics: All Selected (or at minimum Blood Glucose)"
echo "  8. Export Format: JSON"
echo "  9. Export Version: v2"
echo " 10. Date Range: Since Last Sync"
echo " 11. Summarize Data: OFF (want individual CGM readings)"
echo " 12. Batch Requests: OFF"
echo " 13. Sync Cadence: 4 hours"
echo ""
echo "Test with curl:"
echo "  curl -X POST ${WEBHOOK_URL} \\"
echo "    -H 'Authorization: Bearer $API_KEY' \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"data\":{\"metrics\":[{\"name\":\"Blood Glucose\",\"units\":\"mg/dL\",\"data\":[{\"date\":\"2026-02-24 12:00:00 -0800\",\"qty\":105}]}]}}'"
echo ""
echo "============================================================"
