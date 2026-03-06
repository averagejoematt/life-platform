#!/bin/bash
# HOTFIX: Fix Daily Brief Lambda syntax error (broken indentation in CGM section)
# The build_html function had 8 sections where 6-space indented try blocks
# had their body lines drop to 4-space indent, causing Python SyntaxError.
# 
# Run this immediately to restore the daily brief.

set -e

LAMBDA_DIR="$HOME/Documents/Claude/life-platform/lambdas"
DEPLOY_DIR="$HOME/Documents/Claude/life-platform/deploy"

echo "=== Daily Brief Hotfix Deploy ==="

# Step 1: Backup current file
echo "[1/4] Backing up current file..."
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
cp "$LAMBDA_DIR/daily_brief_lambda.py" "$LAMBDA_DIR/daily_brief_lambda.py.backup-${TIMESTAMP}"

# Step 2: Apply indentation fix using Python
echo "[2/4] Applying indentation fix..."
python3 << 'PYFIX'
import sys
filepath = sys.argv[1] if len(sys.argv) > 1 else None
if not filepath:
    # Use the lambda source
    import os
    filepath = os.path.expanduser("~/Documents/Claude/life-platform/lambdas/daily_brief_lambda.py")

with open(filepath, 'r') as f:
    lines = f.readlines()

# Find all try blocks at 4-space indent with 6-space body
# where subsequent lines drop to 4-space (breaking Python syntax)
fixes = []
i = 0
while i < len(lines):
    stripped = lines[i].rstrip()
    indent = len(lines[i]) - len(lines[i].lstrip()) if stripped else 0
    
    if stripped.endswith('try:') and indent == 4:
        try_idx = i
        i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i < len(lines):
            first_body_indent = len(lines[i]) - len(lines[i].lstrip())
            if first_body_indent == 6:
                i += 1
                while i < len(lines):
                    s = lines[i].rstrip()
                    ind = len(lines[i]) - len(lines[i].lstrip()) if s else 0
                    if s.startswith('    except ') and ind == 4:
                        break
                    if s and ind == 4 and not s.lstrip().startswith('#'):
                        fixes.append(i)
                    i += 1
    i += 1

print(f"  Fixed {len(fixes)} lines with broken indentation")
for idx in fixes:
    if lines[idx].strip():
        lines[idx] = '  ' + lines[idx]

with open(filepath, 'w') as f:
    f.writelines(lines)
PYFIX

# Step 3: Verify syntax
echo "[3/4] Verifying Python syntax..."
python3 -m py_compile "$LAMBDA_DIR/daily_brief_lambda.py"
echo "  ✅ Syntax OK"

# Step 4: Create zip and deploy
echo "[4/4] Creating zip and deploying..."
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
echo ""

# Step 5: Test invoke
echo "Invoking Daily Brief now to send today's email..."
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
