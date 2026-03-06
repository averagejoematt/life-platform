#!/bin/bash
# HOTFIX v4: Restore from clean backup FIRST, then apply targeted fix
set -e

LAMBDA_DIR="$HOME/Documents/Claude/life-platform/lambdas"
CLEAN_BACKUP="$LAMBDA_DIR/daily_brief_lambda.py.backup-20260301-123650"
SRC="$LAMBDA_DIR/daily_brief_lambda.py"

echo "=== Daily Brief Hotfix v4 ==="

# Step 1: Restore from CLEAN backup (before any fix attempts)
echo "[1/5] Restoring from clean backup..."
cp "$CLEAN_BACKUP" "$SRC"
echo "  Restored v2.53.1 from backup"

# Step 2: Verify this is the original broken file
echo "[2/5] Confirming original file (should fail syntax check)..."
if python3 -m py_compile "$SRC" 2>/dev/null; then
    echo "  ⚠️ File already passes syntax — deploying as-is"
else
    echo "  Confirmed: original has syntax error, applying fix..."
    
    # Apply targeted indentation fix
    python3 << 'PYFIX'
import os
filepath = os.path.expanduser("~/Documents/Claude/life-platform/lambdas/daily_brief_lambda.py")

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
                    
                    # Line is at 4-space indent but should be 6-space
                    # (not a comment at try-level, not blank)
                    if kstripped and kind == 4 and not kstripped.startswith('except') and not kstripped.startswith('finally'):
                        lines[k] = '  ' + lines[k]
                        fixed_count += 1
                    k += 1
    i += 1

with open(filepath, 'w') as f:
    f.writelines(lines)

print(f"  Fixed {fixed_count} lines")
PYFIX
fi

# Step 3: Verify syntax
echo "[3/5] Verifying syntax..."
python3 -m py_compile "$SRC"
echo "  ✅ Syntax OK"

# Step 4: Create zip and deploy
echo "[4/5] Deploying..."
cd "$LAMBDA_DIR"
cp daily_brief_lambda.py lambda_function.py
zip -j daily_brief_lambda.zip lambda_function.py
rm lambda_function.py

aws lambda update-function-code \
    --function-name daily-brief \
    --zip-file "fileb://$LAMBDA_DIR/daily_brief_lambda.zip" \
    --region us-west-2 \
    --output text --query 'LastModified'

echo "  Waiting 5s for propagation..."
sleep 5

# Step 5: Invoke
echo "[5/5] Invoking Daily Brief..."
aws lambda invoke \
    --function-name daily-brief \
    --region us-west-2 \
    --payload '{}' \
    /tmp/daily-brief-hotfix-output.json \
    --output text --query 'StatusCode'

echo ""
cat /tmp/daily-brief-hotfix-output.json 2>/dev/null | python3 -m json.tool 2>/dev/null || true
echo ""
echo "✅ Done — check your email!"
