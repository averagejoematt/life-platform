#!/bin/bash
set -e

FUNCTION_NAME="activity-enrichment"
ROLE_NAME="lambda-enrichment-role"
ROLE_ARN="arn:aws:iam::205930651321:role/${ROLE_NAME}"
REGION="us-west-2"
RUNTIME="python3.12"
TIMEOUT=300
MEMORY=256

echo "[INFO]  Packaging Lambda..."
zip -q enrichment_lambda.zip enrichment_lambda.py
echo "[INFO]  Created enrichment_lambda.zip"

# IAM role (reuse pattern from other lambdas)
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
    --policy-name "life-platform-enrichment-access" \
    --policy-document '{
        "Version":"2012-10-17",
        "Statement":[
            {"Effect":"Allow","Action":["dynamodb:Query","dynamodb:UpdateItem"],"Resource":"arn:aws:dynamodb:us-west-2:205930651321:table/life-platform"}
        ]
    }' \
    --region "$REGION"
echo "[INFO]  IAM policy applied."

# Deploy Lambda
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" &>/dev/null; then
    echo "[INFO]  Updating existing Lambda..."
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file fileb://enrichment_lambda.zip \
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
        --handler enrichment_lambda.lambda_handler \
        --zip-file fileb://enrichment_lambda.zip \
        --timeout "$TIMEOUT" \
        --memory-size "$MEMORY" \
        --region "$REGION" > /dev/null
    aws lambda wait function-exists --function-name "$FUNCTION_NAME" --region "$REGION"
fi
echo "[INFO]  Lambda deployed."

# EventBridge rule — 06:00 UTC = 10pm PT (after all daily syncs complete)
RULE_NAME="activity-enrichment-nightly"
echo "[INFO]  Setting up EventBridge schedule..."
aws events put-rule \
    --name "$RULE_NAME" \
    --schedule-expression "cron(0 6 * * ? *)" \
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
    --targets "[{\"Id\":\"enrichment-target\",\"Arn\":\"${LAMBDA_ARN}\"}]" \
    --region "$REGION" > /dev/null

echo ""
echo "════════════════════════════════════════════════════════"
echo " Activity Enrichment deployment complete"
echo "════════════════════════════════════════════════════════"
echo "  Function  : ${FUNCTION_NAME}"
echo "  Schedule  : 06:00 UTC (10pm PT) nightly"
echo ""
echo "  To run a full backfill:"
echo "    aws lambda invoke --function-name ${FUNCTION_NAME} \\"
echo "      --payload '{\"backfill\":true,\"start_date\":\"2020-01-01\"}' \\"
echo "      --cli-binary-format raw-in-base64-out \\"
echo "      --region ${REGION} /tmp/enrichment_out.json && cat /tmp/enrichment_out.json"
echo ""
