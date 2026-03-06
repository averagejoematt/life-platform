#!/bin/bash
# deploy_glucose_meal_response.sh — Add glucose meal response tool to MCP server
# New tool: get_glucose_meal_response (Levels-style postprandial spike analysis)
set -euo pipefail

REGION="us-west-2"
FUNCTION_NAME="life-platform-mcp"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== MCP Server v2.26.0 — Glucose Meal Response Tool ==="
echo ""

# Step 0: Ensure MCP Lambda role has S3 read access
echo "Step 0: Checking IAM permissions..."
CURRENT_POLICY=$(aws iam get-role-policy --role-name lambda-mcp-server-role --policy-name mcp-server-permissions --region "$REGION" --query 'PolicyDocument' --output json 2>/dev/null)

if echo "$CURRENT_POLICY" | grep -q "s3:GetObject"; then
    echo "  ✅ S3 read permission already exists"
else
    echo "  Adding S3 read permission for CGM readings..."
    cat > /tmp/mcp-policy.json << 'POLICY'
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "DynamoDBRead",
            "Effect": "Allow",
            "Action": ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan", "dynamodb:PutItem"],
            "Resource": "arn:aws:dynamodb:us-west-2:205930651321:table/life-platform"
        },
        {
            "Sid": "SecretsRead",
            "Effect": "Allow",
            "Action": ["secretsmanager:GetSecretValue"],
            "Resource": "arn:aws:secretsmanager:us-west-2:205930651321:secret:life-platform/mcp-api-key*"
        },
        {
            "Sid": "S3ReadCGM",
            "Effect": "Allow",
            "Action": ["s3:GetObject"],
            "Resource": "arn:aws:s3:::matthew-life-platform/raw/cgm_readings/*"
        }
    ]
}
POLICY
    aws iam put-role-policy \
        --role-name lambda-mcp-server-role \
        --policy-name mcp-server-permissions \
        --policy-document file:///tmp/mcp-policy.json \
        --region "$REGION"
    echo "  ✅ S3 read permission added"
fi

# Step 1: Patch
echo ""
echo "Step 1: Patching mcp_server.py..."
cd "$DIR"
python3 patch_glucose_meal_response.py

# Step 2: Package
echo ""
echo "Step 2: Packaging..."
zip -j mcp_server.zip mcp_server.py

ZIP_SIZE=$(du -sh mcp_server.zip | cut -f1)
echo "  → mcp_server.zip ($ZIP_SIZE)"

# Step 3: Deploy
echo ""
echo "Step 3: Deploying to Lambda..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://mcp_server.zip" \
    --region "$REGION" > /dev/null

echo ""
echo "Step 4: Waiting for update..."
aws lambda wait function-updated \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION"

echo ""
echo "Step 5: Verifying..."
aws lambda get-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --query '{LastModified: LastModified, MemorySize: MemorySize, Timeout: Timeout}' \
    --output table

echo ""
echo "=== ✅ MCP Server v2.26.0 deployed (59 tools) ==="
echo ""
echo "Test via Claude Desktop:"
echo "  'Which foods spike my glucose the most?'"
echo "  'Show me my meal glucose responses'"
