#!/usr/bin/env bash
# deploy.sh – Create or update the Whoop data ingestion Lambda function.
#
# Prerequisites:
#   - AWS CLI configured with credentials that have IAM, Lambda, S3,
#     DynamoDB, Secrets Manager, and EventBridge permissions.
#   - lambda_function.py in the same directory as this script.
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
FUNCTION_NAME="whoop-data-ingestion"
REGION="us-west-2"
ACCOUNT_ID="205930651321"
ROLE_NAME="lambda-whoop-ingestion-role"
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
RUNTIME="python3.12"
HANDLER="lambda_function.lambda_handler"
TIMEOUT=60        # seconds
MEMORY=256        # MB
ZIP_FILE="whoop_lambda.zip"

# EventBridge: run daily at 14:00 UTC (6 AM PT / 9 AM ET).
# Adjust to taste; Whoop data is typically scored by morning.
SCHEDULE="cron(0 14 * * ? *)"
RULE_NAME="whoop-daily-ingestion"

# ── Helpers ───────────────────────────────────────────────────────────────────
info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

# ── 1. Package ────────────────────────────────────────────────────────────────
info "Packaging Lambda function..."
rm -f "${ZIP_FILE}"
zip -j "${ZIP_FILE}" lambda_function.py
info "Created ${ZIP_FILE}"

# ── 2. IAM role ───────────────────────────────────────────────────────────────
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
    info "Role created. Waiting 15 s for IAM propagation..."
    sleep 15
fi

# ── 3. Attach policies ────────────────────────────────────────────────────────
info "Attaching AWSLambdaBasicExecutionRole (CloudWatch Logs)..."
aws iam attach-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
    2>/dev/null || warn "Policy may already be attached – continuing."

info "Putting inline policy for Secrets Manager / S3 / DynamoDB..."
INLINE_POLICY=$(cat <<'EOF'
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "SecretsManager",
            "Effect": "Allow",
            "Action": [
                "secretsmanager:GetSecretValue",
                "secretsmanager:UpdateSecret"
            ],
            "Resource": "arn:aws:secretsmanager:us-west-2:205930651321:secret:life-platform/whoop*"
        },
        {
            "Sid": "S3Write",
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject"
            ],
            "Resource": "arn:aws:s3:::matthew-life-platform/*"
        },
        {
            "Sid": "DynamoDB",
            "Effect": "Allow",
            "Action": [
                "dynamodb:PutItem",
                "dynamodb:GetItem",
                "dynamodb:UpdateItem"
            ],
            "Resource": "arn:aws:dynamodb:us-west-2:205930651321:table/life-platform"
        }
    ]
}
EOF
)

aws iam put-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-name "whoop-ingestion-permissions" \
    --policy-document "${INLINE_POLICY}"
info "Inline policy applied."

# ── 4. Deploy Lambda ──────────────────────────────────────────────────────────
if aws lambda get-function --function-name "${FUNCTION_NAME}" --region "${REGION}" > /dev/null 2>&1; then
    info "Updating existing Lambda function code..."
    aws lambda update-function-code \
        --function-name "${FUNCTION_NAME}" \
        --zip-file "fileb://${ZIP_FILE}" \
        --region "${REGION}" > /dev/null

    info "Waiting for code update to complete..."
    aws lambda wait function-updated \
        --function-name "${FUNCTION_NAME}" \
        --region "${REGION}"

    info "Updating function configuration..."
    aws lambda update-function-configuration \
        --function-name "${FUNCTION_NAME}" \
        --runtime "${RUNTIME}" \
        --handler "${HANDLER}" \
        --timeout "${TIMEOUT}" \
        --memory-size "${MEMORY}" \
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
        --description "Whoop health data ingestion – fetches daily recovery and sleep metrics" \
        > /dev/null
fi

info "Lambda function deployed."

# ── 5. EventBridge daily trigger ──────────────────────────────────────────────
info "Setting up EventBridge schedule: ${SCHEDULE}..."
aws events put-rule \
    --name "${RULE_NAME}" \
    --schedule-expression "${SCHEDULE}" \
    --state ENABLED \
    --description "Trigger Whoop ingestion daily at 14:00 UTC" \
    --region "${REGION}" > /dev/null

LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"

# Grant EventBridge permission to invoke the function.
aws lambda add-permission \
    --function-name "${FUNCTION_NAME}" \
    --statement-id "EventBridgeDailyTrigger" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "arn:aws:events:${REGION}:${ACCOUNT_ID}:rule/${RULE_NAME}" \
    --region "${REGION}" > /dev/null 2>&1 \
    || warn "EventBridge permission may already exist – continuing."

aws events put-targets \
    --rule "${RULE_NAME}" \
    --targets "Id=WhoopLambda,Arn=${LAMBDA_ARN}" \
    --region "${REGION}" > /dev/null

info "EventBridge rule '${RULE_NAME}' configured."

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════"
echo " Deployment complete"
echo "════════════════════════════════════════"
echo "  Function : ${FUNCTION_NAME}"
echo "  Region   : ${REGION}"
echo "  Role     : ${ROLE_ARN}"
echo "  Schedule : ${SCHEDULE} (14:00 UTC daily)"
echo ""
echo "  Test with:"
echo "    aws lambda invoke \\"
echo "      --function-name ${FUNCTION_NAME} \\"
echo "      --region ${REGION} \\"
echo "      output.json && cat output.json"
echo ""
echo "  Tail logs with:"
echo "    aws logs tail /aws/lambda/${FUNCTION_NAME} \\"
echo "      --region ${REGION} --follow"
