#!/bin/bash
set -e

FUNCTION_NAME="apple-health-ingestion"
ROLE_ARN="arn:aws:iam::205930651321:role/lambda-whoop-ingestion-role"
S3_BUCKET="matthew-life-platform"
REGION="us-west-2"

echo "=== Deploying Apple Health Lambda ==="

# Package
cp apple_health_lambda.py lambda_function.py
zip -q apple_health_lambda.zip lambda_function.py
rm lambda_function.py

# Upload to S3
aws s3 cp apple_health_lambda.zip s3://${S3_BUCKET}/deployments/apple_health_lambda.zip \
  --region ${REGION}

# Create or update Lambda
EXISTING=$(aws lambda get-function --function-name ${FUNCTION_NAME} \
  --region ${REGION} 2>/dev/null || echo "NOT_FOUND")

if echo "$EXISTING" | grep -q "NOT_FOUND"; then
  echo "Creating Lambda..."
  aws lambda create-function \
    --function-name ${FUNCTION_NAME} \
    --runtime python3.12 \
    --role ${ROLE_ARN} \
    --handler lambda_function.lambda_handler \
    --code S3Bucket=${S3_BUCKET},S3Key=deployments/apple_health_lambda.zip \
    --timeout 600 \
    --memory-size 1024 \
    --environment "Variables={S3_BUCKET=${S3_BUCKET},DYNAMODB_TABLE=life-platform}" \
    --region ${REGION}
else
  echo "Updating Lambda..."
  aws lambda update-function-code \
    --function-name ${FUNCTION_NAME} \
    --s3-bucket ${S3_BUCKET} \
    --s3-key deployments/apple_health_lambda.zip \
    --region ${REGION}
  
  aws lambda update-function-configuration \
    --function-name ${FUNCTION_NAME} \
    --timeout 600 \
    --memory-size 1024 \
    --environment "Variables={S3_BUCKET=${S3_BUCKET},DYNAMODB_TABLE=life-platform}" \
    --region ${REGION}
fi

echo "Waiting for Lambda to be active..."
aws lambda wait function-active --function-name ${FUNCTION_NAME} --region ${REGION}

# Create the S3 import prefix (just drop a placeholder)
aws s3api put-object \
  --bucket ${S3_BUCKET} \
  --key "imports/apple_health/" \
  --region ${REGION} 2>/dev/null || true

# Add S3 trigger: any file put into imports/apple_health/ triggers Lambda
echo "Adding S3 trigger..."

# Grant S3 permission to invoke Lambda
aws lambda add-permission \
  --function-name ${FUNCTION_NAME} \
  --statement-id S3TriggerAppleHealth \
  --action lambda:InvokeFunction \
  --principal s3.amazonaws.com \
  --source-arn arn:aws:s3:::${S3_BUCKET} \
  --source-account 205930651321 \
  --region ${REGION} 2>/dev/null || echo "Permission already exists"

# Configure S3 bucket notification
# Get existing notifications first, then merge
EXISTING_NOTIF=$(aws s3api get-bucket-notification-configuration \
  --bucket ${S3_BUCKET} \
  --region ${REGION} 2>/dev/null || echo "{}")

LAMBDA_ARN=$(aws lambda get-function --function-name ${FUNCTION_NAME} \
  --region ${REGION} --query 'Configuration.FunctionArn' --output text)

# Write notification config
cat > /tmp/s3_notification.json << EOF
{
  "LambdaFunctionConfigurations": [
    {
      "LambdaFunctionArn": "${LAMBDA_ARN}",
      "Events": ["s3:ObjectCreated:*"],
      "Filter": {
        "Key": {
          "FilterRules": [
            {"Name": "prefix", "Value": "imports/apple_health/"},
            {"Name": "suffix", "Value": ".xml"}
          ]
        }
      }
    },
    {
      "LambdaFunctionArn": "${LAMBDA_ARN}",
      "Events": ["s3:ObjectCreated:*"],
      "Filter": {
        "Key": {
          "FilterRules": [
            {"Name": "prefix", "Value": "imports/apple_health/"},
            {"Name": "suffix", "Value": ".xml.gz"}
          ]
        }
      }
    }
  ]
}
EOF

aws s3api put-bucket-notification-configuration \
  --bucket ${S3_BUCKET} \
  --notification-configuration file:///tmp/s3_notification.json \
  --region ${REGION}

echo ""
echo "=== Deployment complete ==="
echo ""
echo "Lambda: ${FUNCTION_NAME}"
echo "Memory: 1024MB | Timeout: 600s (10 min)"
echo ""
echo "To trigger: upload export.xml to:"
echo "  s3://${S3_BUCKET}/imports/apple_health/export.xml"
echo ""
echo "Commands:"
echo "  aws s3 cp ~/Documents/Claude/apple_health_export/export.xml \\"
echo "    s3://${S3_BUCKET}/imports/apple_health/export.xml --region ${REGION}"
echo ""
echo "Archived exports land in:"
echo "  s3://${S3_BUCKET}/imports/apple_health/processed/"

rm -f apple_health_lambda.zip
