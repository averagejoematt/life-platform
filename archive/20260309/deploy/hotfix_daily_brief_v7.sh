#!/bin/bash
# HOTFIX v7: Restore backup + sed to fix exact line numbers
set -e
LAMBDA_DIR="$HOME/Documents/Claude/life-platform/lambdas"
SRC="$LAMBDA_DIR/daily_brief_lambda.py"
BACKUP="$LAMBDA_DIR/daily_brief_lambda.py.backup-20260301-123650"

echo "=== Daily Brief Hotfix v7 ==="

# Step 1: Restore clean backup
echo "[1/4] Restoring clean backup..."
cp "$BACKUP" "$SRC"

# Step 2: Add 2 spaces to EXACTLY these lines (from verified diff)
echo "[2/4] Applying surgical indentation fix (26 lines)..."
# Using sed to prepend 2 spaces to specific line numbers
sed -i '' \
  -e '1862,1869s/^/  /' \
  -e '1871,1874s/^/  /' \
  -e '1963,1965s/^/  /' \
  -e '1984s/^/  /' \
  -e '1994,1998s/^/  /' \
  -e '2035s/^/  /' \
  -e '2111,2112s/^/  /' \
  -e '2118s/^/  /' \
  -e '2131s/^/  /' \
  "$SRC"

echo "  Done"

# Step 3: Verify
echo "[3/4] Verifying syntax..."
python3 -m py_compile "$SRC"
echo "  ✅ Syntax OK"

# Step 4: Deploy + invoke
echo "[4/4] Deploying..."
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
echo "Invoking..."
aws lambda invoke \
    --function-name daily-brief \
    --region us-west-2 \
    --payload '{}' \
    /tmp/daily-brief-hotfix-output.json \
    --output text --query 'StatusCode'
echo ""
cat /tmp/daily-brief-hotfix-output.json 2>/dev/null | python3 -m json.tool 2>/dev/null || true
echo "✅ Check your email!"
