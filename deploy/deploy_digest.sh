#!/bin/bash
set -e

FUNCTION_NAME="weekly-digest"
ROLE_NAME="lambda-weekly-digest-role"
ROLE_ARN="arn:aws:iam::205930651321:role/${ROLE_NAME}"
REGION="us-west-2"
RUNTIME="python3.12"
TIMEOUT=120
MEMORY=256

echo "[INFO]  Packaging Lambda..."
cp weekly_digest_lambda.py digest_handler.py
zip -q weekly_digest_lambda.zip digest_handler.py
rm digest_handler.py
echo "[INFO]  Created weekly_digest_lambda.zip"

# IAM role
echo "[INFO]  Checking IAM role: ${ROLE_NAME}..."
if aws iam get-role --role-name "$ROLE_NAME" --region "$REGION" &>/dev/null; then
    echo "[INFO]  Role already exists – skipping creation."
else
    echo "[INFO]  Creating IAM role..."
    aws iam create-role \
        --role-name "$ROLE_NAME" \
        --assume-role-policy-document '{
            "Version":"2012-10-17",
            "Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]
        }' \
        --region "$REGION" > /dev/null
    sleep 5
fi

aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
    --region "$REGION" 2>/dev/null || true

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "weekly-digest-access" \
    --policy-document '{
        "Version":"2012-10-17",
        "Statement":[
            {
                "Effect":"Allow",
                "Action":["dynamodb:GetItem","dynamodb:Query"],
                "Resource":"arn:aws:dynamodb:us-west-2:205930651321:table/life-platform"
            },
            {
                "Effect":"Allow",
                "Action":["secretsmanager:GetSecretValue"],
                "Resource":"arn:aws:secretsmanager:us-west-2:205930651321:secret:life-platform/anthropic*"
            },
            {
                "Effect":"Allow",
                "Action":["ses:SendEmail","sesv2:SendEmail"],
                "Resource":"*"
            }
        ]
    }' \
    --region "$REGION"
echo "[INFO]  IAM policy applied."

# Deploy Lambda
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" &>/dev/null; then
    echo "[INFO]  Updating existing Lambda..."
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file fileb://weekly_digest_lambda.zip \
        --region "$REGION" > /dev/null
    aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
    aws lambda update-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --timeout "$TIMEOUT" \
        --memory-size "$MEMORY" \
        --region "$REGION" > /dev/null
else
    echo "[INFO]  Creating Lambda..."
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime "$RUNTIME" \
        --role "$ROLE_ARN" \
        --handler digest_handler.lambda_handler \
        --zip-file fileb://weekly_digest_lambda.zip \
        --timeout "$TIMEOUT" \
        --memory-size "$MEMORY" \
        --region "$REGION" > /dev/null
    aws lambda wait function-exists --function-name "$FUNCTION_NAME" --region "$REGION"
fi
echo "[INFO]  Lambda deployed."

# EventBridge rule — Sunday 16:00 UTC = 8:00 AM PT
RULE_NAME="weekly-digest-sunday"
echo "[INFO]  Setting up EventBridge schedule (Sundays 8am PT)..."
aws events put-rule \
    --name "$RULE_NAME" \
    --schedule-expression "cron(0 16 ? * SUN *)" \
    --state ENABLED \
    --region "$REGION" > /dev/null

LAMBDA_ARN=$(aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" --query 'Configuration.FunctionArn' --output text)
aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "EventBridgeInvoke" \
    --action lambda:InvokeFunction \
    --principal events.amazonaws.com \
    --source-arn "arn:aws:events:${REGION}:205930651321:rule/${RULE_NAME}" \
    --region "$REGION" 2>/dev/null || true

aws events put-targets \
    --rule "$RULE_NAME" \
    --targets "[{\"Id\":\"digest-target\",\"Arn\":\"${LAMBDA_ARN}\"}]" \
    --region "$REGION" > /dev/null

echo ""
echo "════════════════════════════════════════════════════════"
echo " Weekly Digest deployment complete"
echo "════════════════════════════════════════════════════════"
echo "  Function  : ${FUNCTION_NAME}"
echo "  Schedule  : Sundays 16:00 UTC (8:00 AM PT)"
echo "  Recipient : awsdev@mattsusername.com"
echo ""
echo "  To send a test digest right now:"
echo "    aws lambda invoke --function-name ${FUNCTION_NAME} \\"
echo "      --payload '{}' \\"
echo "      --cli-binary-format raw-in-base64-out \\"
echo "      --region ${REGION} /tmp/digest_out.json && cat /tmp/digest_out.json"
echo ""
