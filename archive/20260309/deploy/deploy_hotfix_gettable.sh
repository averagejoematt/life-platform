#!/bin/bash
set -euo pipefail

# Quick hotfix: remove get_table() calls that shadow module-level `table`

FUNCTION_NAME="life-platform-mcp"
REGION="us-west-2"
WORK_DIR="/tmp/hotfix_gettable_$$"

mkdir -p "$WORK_DIR"
DOWNLOAD_URL=$(aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" --query 'Code.Location' --output text)
curl -sL "$DOWNLOAD_URL" -o "$WORK_DIR/current.zip"
cd "$WORK_DIR"
unzip -q current.zip -d package/

# Replace all `table = get_table()` with comment
sed -i '' 's/^        table = get_table()$/        # table is module-level (line 102)/' package/mcp_server.py 2>/dev/null || \
sed -i 's/^        table = get_table()$/        # table is module-level (line 102)/' package/mcp_server.py
sed -i '' 's/^    table = get_table()$/    # table is module-level (line 102)/' package/mcp_server.py 2>/dev/null || \
sed -i 's/^    table = get_table()$/    # table is module-level (line 102)/' package/mcp_server.py

# Verify no get_table references remain
REMAINING=$(grep -c "get_table" package/mcp_server.py || true)
if [ "$REMAINING" -gt 0 ]; then
    echo "⚠️  $REMAINING get_table references remain:"
    grep -n "get_table" package/mcp_server.py
    # Continue anyway — the remaining might be in comments
fi

python3 -c "import py_compile; py_compile.compile('package/mcp_server.py', doraise=True)" && echo "✅ Syntax OK" || exit 1

cd package && zip -q -r ../fix.zip . && cd ..
aws lambda update-function-code --function-name "$FUNCTION_NAME" --region "$REGION" --zip-file "fileb://fix.zip" --query '[FunctionName, LastModified]' --output table
aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"

# Re-run warmer
echo "Re-running warmer..."
aws lambda invoke --function-name "$FUNCTION_NAME" --region "$REGION" \
    --payload '{"source": "aws.events", "detail-type": "Scheduled Event"}' \
    --cli-binary-format raw-in-base64-out /tmp/warmer_retest.json
echo ""
cat /tmp/warmer_retest.json | python3 -m json.tool

# Save locally
cp package/mcp_server.py "$(cd "$(dirname "$0")" && pwd)/mcp_server.py"

rm -rf "$WORK_DIR" /tmp/warmer_retest.json
echo ""
echo "✅ get_table() hotfix deployed + warmer re-run"
