#!/bin/bash
# HOTFIX v3: Apply indentation fix directly to existing source, then deploy
set -e

LAMBDA_DIR="$HOME/Documents/Claude/life-platform/lambdas"
SRC="$LAMBDA_DIR/daily_brief_lambda.py"

echo "=== Daily Brief Hotfix v3 ==="

# Backup
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
cp "$SRC" "$SRC.backup-${TIMESTAMP}"
echo "[1/5] Backup created"

# Apply fix
echo "[2/5] Applying indentation fix..."
python3 << 'PYFIX'
import os
filepath = os.path.expanduser("~/Documents/Claude/life-platform/lambdas/daily_brief_lambda.py")

with open(filepath, 'r') as f:
    content = f.read()
    lines = content.split('\n')

# Convert to list with newlines for processing  
with open(filepath, 'r') as f:
    lines = f.readlines()

fixed_count = 0
i = 0
while i < len(lines):
    line = lines[i]
    stripped = line.rstrip()
    indent = len(line) - len(line.lstrip()) if stripped else 0
    
    # Find try: at 4-space indent
    if stripped.endswith('try:') and indent == 4:
        try_idx = i
        j = i + 1
        # Skip blank lines
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j < len(lines):
            first_body = lines[j]
            first_indent = len(first_body) - len(first_body.lstrip())
            if first_indent == 6:
                # This try block uses 6-space body indent
                # Fix any lines that drop to 4-space before the except
                k = j + 1
                while k < len(lines):
                    kline = lines[k]
                    kstripped = kline.rstrip()
                    kind = len(kline) - len(kline.lstrip()) if kstripped else 0
                    
                    if kstripped.startswith('except ') and kind == 4:
                        break  # Found matching except
                    
                    if kstripped and kind == 4 and not kstripped.lstrip().startswith('#'):
                        # This line is at 4-space but should be at 6-space
                        lines[k] = '  ' + lines[k]
                        fixed_count += 1
                    k += 1
    i += 1

with open(filepath, 'w') as f:
    f.writelines(lines)

print(f"  Fixed {fixed_count} lines")
PYFIX

# Verify
echo "[3/5] Verifying syntax..."
python3 -m py_compile "$SRC"
echo "  ✅ Syntax OK"

# Create zip
echo "[4/5] Creating zip and deploying..."
cd "$LAMBDA_DIR"
cp daily_brief_lambda.py lambda_function.py
zip -j daily_brief_lambda.zip lambda_function.py
rm lambda_function.py

aws lambda update-function-code \
    --function-name daily-brief \
    --zip-file "fileb://$LAMBDA_DIR/daily_brief_lambda.zip" \
    --region us-west-2 \
    --output text --query 'LastModified'

# Wait and invoke
echo ""
echo "Waiting 5s..."
sleep 5

echo "[5/5] Invoking Daily Brief..."
STATUS=$(aws lambda invoke \
    --function-name daily-brief \
    --region us-west-2 \
    --payload '{}' \
    /tmp/daily-brief-hotfix-output.json \
    --output text --query 'StatusCode')

echo "Status: $STATUS"
if [ "$STATUS" = "200" ]; then
    FUNC_ERROR=$(cat /tmp/daily-brief-hotfix-output.json 2>/dev/null | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('FunctionError',''))" 2>/dev/null)
    if [ -z "$FUNC_ERROR" ]; then
        echo "✅ Success! Check your email."
    else
        echo "⚠️ Lambda returned an error. Check logs:"
        cat /tmp/daily-brief-hotfix-output.json
    fi
else
    echo "❌ Invoke failed with status $STATUS"
fi
