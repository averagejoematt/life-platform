#!/bin/bash
# deploy_garmin.sh — Deploy Garmin ingestion Lambda + IAM role + EventBridge schedule
#
# Garmin requires third-party libraries (garminconnect, garth) which must be
# bundled into the Lambda zip. This script handles that automatically.
#
# Prerequisites:
#   1. Run setup_garmin_auth.py first to store credentials in Secrets Manager
#   2. Python 3.12 + pip available locally
#
# Schedule: 9:30 AM PT daily (17:30 UTC)
#   Garmin syncs device data on morning wear; 9:30 AM PT safely covers
#   overnight HRV, body battery, and prior-day stress.

set -e
REGION="us-west-2"
ACCOUNT="205930651321"
FUNCTION_NAME="garmin-data-ingestion"
ROLE_NAME="lambda-garmin-ingestion-role"
ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/${ROLE_NAME}"
RULE_NAME="garmin-daily-ingestion"
ZIP_FILE="garmin_lambda.zip"

cd "$(dirname "$0")"

# ── IAM Role ───────────────────────────────────────────────────────────────────
echo "=== Ensuring IAM Role ==="
if ! aws iam get-role --role-name "$ROLE_NAME" --region "$REGION" &>/dev/null; then
    echo "Creating IAM role: $ROLE_NAME"
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
        --region "$REGION"

    aws iam attach-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
        --region "$REGION"

    # Inline policy: DynamoDB, S3, Secrets Manager (scoped to garmin secret)
    aws iam put-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-name "garmin-ingestion-policy" \
        --policy-document "{
            \"Version\": \"2012-10-17\",
            \"Statement\": [
                {
                    \"Effect\": \"Allow\",
                    \"Action\": [\"dynamodb:PutItem\", \"dynamodb:GetItem\"],
                    \"Resource\": \"arn:aws:dynamodb:${REGION}:${ACCOUNT}:table/life-platform\"
                },
                {
                    \"Effect\": \"Allow\",
                    \"Action\": [\"s3:PutObject\"],
                    \"Resource\": \"arn:aws:s3:::matthew-life-platform/raw/garmin/*\"
                },
                {
                    \"Effect\": \"Allow\",
                    \"Action\": [
                        \"secretsmanager:GetSecretValue\",
                        \"secretsmanager:UpdateSecret\"
                    ],
                    \"Resource\": \"arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:life-platform/garmin*\"
                }
            ]
        }" \
        --region "$REGION"

    echo "IAM role created. Waiting 15s for propagation..."
    sleep 15
else
    echo "IAM role already exists: $ROLE_NAME"
fi

# ── Package Lambda with dependencies ──────────────────────────────────────────
echo ""
echo "=== Packaging Lambda with dependencies ==="

# Create temp build directory
BUILD_DIR=$(mktemp -d)
echo "Build dir: $BUILD_DIR"

# Install garminconnect + garth into build dir
echo "Installing garminconnect and garth..."
pip3 install garminconnect garth --target "$BUILD_DIR" --quiet

# Copy Lambda handler
cp garmin_lambda.py "$BUILD_DIR/"

# Zip everything
echo "Creating zip..."
cd "$BUILD_DIR"
zip -r "${OLDPWD}/${ZIP_FILE}" . --quiet
cd -

# Clean up
rm -rf "$BUILD_DIR"

ZIP_SIZE=$(du -sh "$ZIP_FILE" | cut -f1)
echo "Package created: $ZIP_FILE ($ZIP_SIZE)"

# ── Deploy Lambda ──────────────────────────────────────────────────────────────
echo ""
echo "=== Deploying Lambda ==="
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" &>/dev/null; then
    echo "Updating existing function..."
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file "fileb://${ZIP_FILE}" \
        --region "$REGION"
else
    echo "Creating new function..."
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.12 \
        --role "$ROLE_ARN" \
        --handler garmin_lambda.lambda_handler \
        --zip-file "fileb://${ZIP_FILE}" \
        --timeout 120 \
        --memory-size 256 \
        --region "$REGION"
fi

# Wait for update to complete
echo "Waiting for function update..."
aws lambda wait function-updated \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION"

# ── CloudWatch Log Retention ───────────────────────────────────────────────────
echo ""
echo "=== Setting log retention (30 days) ==="
LOG_GROUP="/aws/lambda/${FUNCTION_NAME}"
aws logs put-retention-policy \
    --log-group-name "$LOG_GROUP" \
    --retention-in-days 30 \
    --region "$REGION" 2>/dev/null || echo "Log group not yet created (will be set on first invocation)"

# ── EventBridge Schedule (9:30 AM PT = 17:30 UTC) ─────────────────────────────
echo ""
echo "=== Setting EventBridge Schedule (9:30 AM PT daily) ==="
FUNCTION_ARN="arn:aws:lambda:${REGION}:${ACCOUNT}:function:${FUNCTION_NAME}"

aws events put-rule \
    --name "$RULE_NAME" \
    --schedule-expression "cron(30 17 * * ? *)" \
    --state ENABLED \
    --region "$REGION"

aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "EventBridgeInvoke-garmin" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "arn:aws:events:${REGION}:${ACCOUNT}:rule/${RULE_NAME}" \
    --region "$REGION" 2>/dev/null || echo "Permission already exists, skipping."

aws events put-targets \
    --rule "$RULE_NAME" \
    --targets "Id=GarminLambda,Arn=${FUNCTION_ARN}" \
    --region "$REGION"

# ── CloudWatch Alarm ───────────────────────────────────────────────────────────
echo ""
echo "=== Adding CloudWatch alarm for Lambda errors ==="
aws cloudwatch put-metric-alarm \
    --alarm-name "${FUNCTION_NAME}-errors" \
    --alarm-description "Garmin ingestion Lambda error alarm" \
    --metric-name Errors \
    --namespace AWS/Lambda \
    --dimensions Name=FunctionName,Value="$FUNCTION_NAME" \
    --statistic Sum \
    --period 86400 \
    --threshold 1 \
    --comparison-operator GreaterThanOrEqualToThreshold \
    --evaluation-periods 1 \
    --alarm-actions "arn:aws:sns:${REGION}:${ACCOUNT}:life-platform-alerts" \
    --treat-missing-data notBreaching \
    --region "$REGION"

echo ""
echo "=== Done ==="
echo "Function : $FUNCTION_NAME"
echo "Role     : $ROLE_NAME"
echo "Schedule : 9:30 AM PT daily (cron 30 17 * * ? *)"
echo ""
echo "Test with:"
echo "  aws lambda invoke \\"
echo "    --function-name $FUNCTION_NAME \\"
echo "    --payload '{\"date\": \"$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d yesterday +%Y-%m-%d)\"}' \\"
echo "    --region $REGION /tmp/garmin_test.json"
echo "  cat /tmp/garmin_test.json"
echo ""
echo "Expected fields in response:"
echo "  resting_heart_rate, hrv_last_night, hrv_status,"
echo "  avg_stress, body_battery_end, body_battery_high, steps"
