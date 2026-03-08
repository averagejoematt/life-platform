#!/bin/bash
# HOTFIX v2: Deploy the pre-fixed daily_brief_lambda.py from Claude's output
# The fix has been verified to pass py_compile on Claude's side.

set -e

LAMBDA_DIR="$HOME/Documents/Claude/life-platform/lambdas"
FIXED_FILE="$LAMBDA_DIR/daily_brief_lambda_fixed.py"

echo "=== Daily Brief Hotfix v2 ==="

# Step 1: Verify the fixed file exists (copied from Claude's output)
if [ ! -f "$FIXED_FILE" ]; then
    echo "ERROR: $FIXED_FILE not found!"
    echo "Please copy the fixed file from Claude's output first:"
    echo "  cp ~/Downloads/daily_brief_lambda_fixed.py $FIXED_FILE"
    exit 1
fi

# Step 2: Verify syntax of fixed file
echo "[1/4] Verifying syntax..."
python3 -m py_compile "$FIXED_FILE"
echo "  ✅ Syntax OK"

# Step 3: Backup + replace
echo "[2/4] Backing up current file..."
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
cp "$LAMBDA_DIR/daily_brief_lambda.py" "$LAMBDA_DIR/daily_brief_lambda.py.backup-${TIMESTAMP}"
cp "$FIXED_FILE" "$LAMBDA_DIR/daily_brief_lambda.py"

# Step 4: Create zip and deploy
echo "[3/4] Creating zip and deploying..."
cd "$LAMBDA_DIR"
cp daily_brief_lambda.py lambda_function.py
zip -j daily_brief_lambda.zip lambda_function.py
rm lambda_function.py

aws lambda update-function-code \
    --function-name daily-brief \
    --zip-file "fileb://$LAMBDA_DIR/daily_brief_lambda.zip" \
    --region us-west-2 \
    --output text --query 'LastModified'

echo ""
echo "=== Deploy Complete ==="

# Step 5: Wait for update, then invoke
echo "Waiting 5s for Lambda to propagate..."
sleep 5

echo "[4/4] Invoking Daily Brief..."
aws lambda invoke \
    --function-name daily-brief \
    --region us-west-2 \
    --payload '{}' \
    /tmp/daily-brief-hotfix-output.json \
    --output text --query 'StatusCode'

echo ""
cat /tmp/daily-brief-hotfix-output.json 2>/dev/null | python3 -m json.tool 2>/dev/null || cat /tmp/daily-brief-hotfix-output.json 2>/dev/null
echo ""
echo "✅ Check your email for today's brief!"
