
cd /tmp/freshness_build
zip -r /tmp/freshness_checker.zip .
echo "Package created."

echo "Deploying to Lambda..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file fileb:///tmp/freshness_checker.zip \
    --region "$REGION" \
    --query "[FunctionName,CodeSize,LastModified]"

echo ""
echo "✅ Done! Testing the function..."
aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --log-type Tail \
    /tmp/freshness_response.json \
    --query "LogResult" \
    --output text | base64 -d | tail -20

echo ""
cat /tmp/freshness_response.json
