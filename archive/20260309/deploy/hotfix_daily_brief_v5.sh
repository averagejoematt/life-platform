#!/bin/bash
# HOTFIX v5: Deploy the pre-verified fixed file (downloaded from Claude)
set -e

LAMBDA_DIR="$HOME/Documents/Claude/life-platform/lambdas"
DOWNLOADED="$HOME/Downloads/daily_brief_lambda.py"

echo "=== Daily Brief Hotfix v5 ==="

# Check for downloaded file
if [ ! -f "$DOWNLOADED" ]; then
    echo "❌ File not found: $DOWNLOADED"
    echo "Please download the file from Claude's output first."
    exit 1
fi

# Verify syntax of downloaded file
echo "[1/3] Verifying syntax of downloaded file..."
python3 -m py_compile "$DOWNLOADED"
echo "  ✅ Syntax OK"

# Copy into place
echo "[2/3] Deploying..."
cp "$DOWNLOADED" "$LAMBDA_DIR/daily_brief_lambda.py"
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

# Invoke
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
