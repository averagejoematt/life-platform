#!/usr/bin/env bash
# deploy_mcp.sh – Deploy the life-platform MCP server Lambda with a Function URL.
#
# Usage:
#   chmod +x deploy_mcp.sh
#   ./deploy_mcp.sh

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
FUNCTION_NAME="life-platform-mcp"
REGION="us-west-2"
ACCOUNT_ID="205930651321"
ROLE_NAME="lambda-mcp-server-role"
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
RUNTIME="python3.12"
HANDLER="mcp_server.lambda_handler"
TIMEOUT=300
MEMORY=512
ZIP_FILE="mcp_server.zip"
SECRET_NAME="life-platform/mcp-api-key"

# ── Helpers ───────────────────────────────────────────────────────────────────
info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

# ── 0. Read version from mcp_server.py ───────────────────────────────────────
DEPLOY_VERSION=$(python3 -c "
import re, sys
with open('mcp_server.py') as f:
    src = f.read()
m = re.search(r'\"version\": \"([\\d.]+)\"', src)
if not m:
    print('ERROR: could not find version string in mcp_server.py', file=sys.stderr)
    sys.exit(1)
print(m.group(1))
")
info "Detected version: ${DEPLOY_VERSION}"

# ── 1. Package ────────────────────────────────────────────────────────────────
info "Packaging Lambda..."
rm -f "${ZIP_FILE}"
zip -j "${ZIP_FILE}" mcp_server.py
info "Created ${ZIP_FILE}"

# ── 2. API key in Secrets Manager ────────────────────────────────────────────
info "Checking for MCP API key in Secrets Manager..."
if aws secretsmanager describe-secret --secret-id "${SECRET_NAME}" --region "${REGION}" > /dev/null 2>&1; then
    info "Secret already exists – skipping creation."
else
    info "Generating and storing API key..."
    API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    aws secretsmanager create-secret \
        --name "${SECRET_NAME}" \
        --secret-string "${API_KEY}" \
        --region "${REGION}" > /dev/null
    info "API key stored in Secrets Manager: ${SECRET_NAME}"
    info "Key value (save this for Claude Desktop config): ${API_KEY}"
fi

# ── 3. IAM role ───────────────────────────────────────────────────────────────
info "Checking IAM role: ${ROLE_NAME}..."
if aws iam get-role --role-name "${ROLE_NAME}" > /dev/null 2>&1; then
    info "Role already exists – skipping creation."
else
    info "Creating IAM role..."
    aws iam create-role \
        --role-name "${ROLE_NAME}" \
        --assume-role-policy-document '{
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        }' > /dev/null
    info "Role created. Waiting 15s for IAM propagation..."
    sleep 15
fi

# Basic execution (CloudWatch Logs)
aws iam attach-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
    2>/dev/null || warn "Policy may already be attached – continuing."

# Read-only DynamoDB + read Secrets Manager
INLINE_POLICY=$(cat <<'EOF'
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "DynamoDBRead",
            "Effect": "Allow",
            "Action": [
                "dynamodb:GetItem",
                "dynamodb:Query",
                "dynamodb:Scan",
                "dynamodb:PutItem"
            ],
            "Resource": "arn:aws:dynamodb:us-west-2:205930651321:table/life-platform"
        },
        {
            "Sid": "SecretsRead",
            "Effect": "Allow",
            "Action": ["secretsmanager:GetSecretValue"],
            "Resource": "arn:aws:secretsmanager:us-west-2:205930651321:secret:life-platform/mcp-api-key*"
        }
    ]
}
EOF
)

aws iam put-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-name "mcp-server-permissions" \
    --policy-document "${INLINE_POLICY}"
info "IAM policy applied."

# ── 4. Deploy Lambda ──────────────────────────────────────────────────────────
if aws lambda get-function --function-name "${FUNCTION_NAME}" --region "${REGION}" > /dev/null 2>&1; then
    info "Updating existing Lambda..."
    aws lambda update-function-code \
        --function-name "${FUNCTION_NAME}" \
        --zip-file "fileb://${ZIP_FILE}" \
        --region "${REGION}" > /dev/null

    aws lambda wait function-updated \
        --function-name "${FUNCTION_NAME}" \
        --region "${REGION}"

    aws lambda update-function-configuration \
        --function-name "${FUNCTION_NAME}" \
        --runtime "${RUNTIME}" \
        --handler "${HANDLER}" \
        --timeout "${TIMEOUT}" \
        --memory-size "${MEMORY}" \
        --environment "Variables={DEPLOY_VERSION=${DEPLOY_VERSION}}" \
        --region "${REGION}" > /dev/null
else
    info "Creating Lambda function: ${FUNCTION_NAME}..."
    aws lambda create-function \
        --function-name "${FUNCTION_NAME}" \
        --runtime "${RUNTIME}" \
        --role "${ROLE_ARN}" \
        --handler "${HANDLER}" \
        --zip-file "fileb://${ZIP_FILE}" \
        --timeout "${TIMEOUT}" \
        --memory-size "${MEMORY}" \
        --region "${REGION}" \
        --environment "Variables={DEPLOY_VERSION=${DEPLOY_VERSION}}" \
        --description "Life Platform MCP server – surfaces health data to Claude Desktop" \
        > /dev/null
fi

aws lambda wait function-updated \
    --function-name "${FUNCTION_NAME}" \
    --region "${REGION}"

info "Lambda deployed: v${DEPLOY_VERSION}"

# Ensure timeout is always 300s regardless of create vs update path
aws lambda update-function-configuration \
    --function-name "${FUNCTION_NAME}" \
    --timeout 300 \
    --region "${REGION}" > /dev/null
info "Timeout locked to 300s (warmer needs up to 120s; MCP queries finish in <10s)"

# ── 5. Function URL (public HTTPS endpoint) ───────────────────────────────────
info "Setting up Function URL..."
if aws lambda get-function-url-config \
    --function-name "${FUNCTION_NAME}" \
    --region "${REGION}" > /dev/null 2>&1; then
    info "Function URL already exists."
    FUNCTION_URL=$(aws lambda get-function-url-config \
        --function-name "${FUNCTION_NAME}" \
        --region "${REGION}" \
        --query "FunctionUrl" --output text)
else
    FUNCTION_URL=$(aws lambda create-function-url-config \
        --function-name "${FUNCTION_NAME}" \
        --auth-type NONE \
        --region "${REGION}" \
        --query "FunctionUrl" --output text)

    # Allow public invocation via Function URL
    aws lambda add-permission \
        --function-name "${FUNCTION_NAME}" \
        --statement-id "FunctionURLAllowPublicAccess" \
        --action "lambda:InvokeFunctionUrl" \
        --principal "*" \
        --function-url-auth-type NONE \
        --region "${REGION}" > /dev/null
fi

info "Function URL: ${FUNCTION_URL}"

# ── 6. Retrieve API key for Claude Desktop config ─────────────────────────────
API_KEY=$(aws secretsmanager get-secret-value \
    --secret-id "${SECRET_NAME}" \
    --region "${REGION}" \
    --query "SecretString" --output text)

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════"
echo " MCP Server deployment complete"
echo "════════════════════════════════════════════════════════"
echo "  Function     : ${FUNCTION_NAME}"
echo "  Version      : ${DEPLOY_VERSION}"
echo "  Function URL : ${FUNCTION_URL}"
echo ""
echo "  Add this to your Claude Desktop config"
echo "  (~/.config/claude/claude_desktop_config.json):"
echo ""
echo '  "mcpServers": {'
echo '    "life-platform": {'
echo '      "command": "npx",'
echo '      "args": ["-y", "@modelcontextprotocol/server-fetch"],'
echo '      "env": {'
echo "        \"MCP_SERVER_URL\": \"${FUNCTION_URL}\","
echo "        \"MCP_API_KEY\":    \"${API_KEY}\""
echo '      }'
echo '    }'
echo '  }'
echo ""
echo "  Then restart Claude Desktop."
echo ""
echo "  Quick smoke test:"
echo "    curl -s -X POST ${FUNCTION_URL} \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -H \"x-api-key: ${API_KEY}\" \\"
echo "      -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\",\"params\":{}}' | python3 -m json.tool"
