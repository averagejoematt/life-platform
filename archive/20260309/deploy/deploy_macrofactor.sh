#!/bin/bash
set -e

FUNCTION_NAME="macrofactor-data-ingestion"
REGION="us-west-2"
ROLE_ARN="arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/lambda-whoop-ingestion-role"
S3_BUCKET="matthew-life-platform"
UPLOAD_PREFIX="uploads/macrofactor/"

echo "=== MacroFactor Lambda Deploy ==="
echo "Function: $FUNCTION_NAME"
echo "Region:   $REGION"
echo "Role:     $ROLE_ARN"

# Package
echo ""
echo "--- Packaging Lambda ---"
rm -f macrofactor_lambda.zip
zip macrofactor_lambda.zip macrofactor_lambda.py
echo "Created macrofactor_lambda.zip"

# Deploy or update
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" &>/dev/null; then
    echo ""
    echo "--- Updating existing function ---"
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file fileb://macrofactor_lambda.zip \
        --region "$REGION"
    echo "Waiting for update to complete..."
    aws lambda wait function-updated \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION"
    echo "Function updated."
else
    echo ""
    echo "--- Creating new function ---"
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.11 \
        --role "$ROLE_ARN" \
        --handler macrofactor_lambda.lambda_handler \
        --zip-file fileb://macrofactor_lambda.zip \
        --timeout 300 \
        --memory-size 256 \
        --region "$REGION"
    echo "Function created."
fi

# -------------------------------------------------------------------------
# S3 trigger setup
# The Lambda must be given permission to be invoked by S3, then we add the
# bucket notification.  Both steps are idempotent (errors ignored on 2nd run).
# -------------------------------------------------------------------------

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"

echo ""
echo "--- Setting up S3 trigger on s3://$S3_BUCKET/$UPLOAD_PREFIX*.csv ---"

# Allow S3 to invoke Lambda (idempotent: remove existing statement first)
aws lambda remove-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "S3-macrofactor-invoke" \
    --region "$REGION" 2>/dev/null || true

aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "S3-macrofactor-invoke" \
    --action lambda:InvokeFunction \
    --principal s3.amazonaws.com \
    --source-arn "arn:aws:s3:::${S3_BUCKET}" \
    --region "$REGION"

echo "Lambda invoke permission granted to S3."

# Get current bucket notification config, merge new rule, put it back.
# NOTE: If the bucket already has other notifications this approach preserves them
# by using a named configuration ID.  If the bucket notification config is
# complex, you may prefer to manage it via the AWS console instead.

echo ""
echo "Adding bucket notification..."
aws s3api put-bucket-notification-configuration \
    --bucket "$S3_BUCKET" \
    --notification-configuration "{
        \"LambdaFunctionConfigurations\": [
            {
                \"Id\": \"MacroFactorCSVIngest\",
                \"LambdaFunctionArn\": \"${LAMBDA_ARN}\",
                \"Events\": [\"s3:ObjectCreated:*\"],
                \"Filter\": {
                    \"Key\": {
                        \"FilterRules\": [
                            {\"Name\": \"prefix\", \"Value\": \"${UPLOAD_PREFIX}\"},
                            {\"Name\": \"suffix\", \"Value\": \".csv\"}
                        ]
                    }
                }
            }
        ]
    }"

echo "✓ S3 trigger configured."
echo ""
echo "=== Deploy complete ==="
echo ""
echo "NEXT STEPS:"
echo "  1. Export MacroFactor Quick Export (all time) and run the backfill:"
echo "       python3 backfill_macrofactor.py ~/Downloads/macrofactor_export.csv --dry-run"
echo "       python3 backfill_macrofactor.py ~/Downloads/macrofactor_export.csv"
echo ""
echo "  2. For ongoing sync, drop a fresh Quick Export CSV to:"
echo "       s3://$S3_BUCKET/${UPLOAD_PREFIX}"
echo "     e.g.: aws s3 cp macrofactor_export.csv s3://$S3_BUCKET/${UPLOAD_PREFIX}"
echo "     Lambda will trigger automatically."
echo ""
echo "  3. Add 'macrofactor' to SOURCES in mcp_server.py and redeploy:"
echo "       bash deploy_mcp.sh"
