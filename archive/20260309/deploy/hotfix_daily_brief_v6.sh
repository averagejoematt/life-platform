#!/bin/bash
# HOTFIX v6: Use the fixed file already placed at lambdas directory
set -e
LAMBDA_DIR="$HOME/Documents/Claude/life-platform/lambdas"
echo "=== Daily Brief Hotfix v6 ==="
echo "[1/3] Verifying syntax..."
python3 -m py_compile "$LAMBDA_DIR/daily_brief_lambda.py"
echo "  ✅ Syntax OK"
echo "[2/3] Deploying..."
cd "$LAMBDA_DIR"
cp daily_brief_lambda.py lambda_function.py
zip -j daily_brief_lambda.zip lambda_function.py
rm lambda_function.py
aws lambda update-function-code \
    --function-name daily-brief \
    --zip-file "fileb://$LAMBDA_DIR/daily_brief_lambda.zip" \
    --region us-west-2 \
    --output text --query 'LastModified'
sleep 5
echo "[3/3] Invoking..."
aws lambda invoke \
    --function-name daily-brief \
    --region us-west-2 \
    --payload '{}' \
    /tmp/daily-brief-hotfix-output.json \
    --output text --query 'StatusCode'
echo ""
cat /tmp/daily-brief-hotfix-output.json 2>/dev/null | python3 -m json.tool 2>/dev/null || true
echo "✅ Check your email!"
