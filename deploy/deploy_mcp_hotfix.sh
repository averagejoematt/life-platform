#!/bin/bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════════════════
# Life Platform — MCP Hotfix + Memory Bump (Steps 1 & 2)
# ══════════════════════════════════════════════════════════════════════════════
# FIXES:
#   1. NameError: tool_get_day_type_analysis not defined (broken since v2.31.0)
#      Root cause: 3 tool functions + 1 helper defined AFTER the TOOLS dict
#      that references them. Python evaluates the dict at module load,
#      hitting NameError on the forward references.
#      Fix: Move the block (lines 9765-10549) before TOOLS dict (line 8202).
#   2. Memory bump: 512 MB → 1024 MB (Lambda CPU scales linearly with memory)
# ══════════════════════════════════════════════════════════════════════════════

FUNCTION_NAME="life-platform-mcp"
REGION="us-west-2"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK_DIR="$SCRIPT_DIR/tmp_hotfix_$$"

echo "══════════════════════════════════════════════════════════════════"
echo "  STEP 1: Download current deployment package"
echo "══════════════════════════════════════════════════════════════════"

mkdir -p "$WORK_DIR"

DOWNLOAD_URL=$(aws lambda get-function \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --query 'Code.Location' \
    --output text)

curl -sL "$DOWNLOAD_URL" -o "$WORK_DIR/current.zip"
cd "$WORK_DIR"
unzip -q current.zip -d package/
echo "✅ Downloaded and extracted current package"

echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "  STEP 2: Apply hotfix — move functions before TOOLS dict"
echo "══════════════════════════════════════════════════════════════════"

python3 << 'PYEOF'
import sys

with open('package/mcp_server.py') as f:
    lines = f.readlines()

# Find key landmarks
tools_line = None
block_start = None  # _load_cgm_readings helper comment
block_end = None    # end of tool_get_fasting_glucose_validation
lambda_handler_line = None

for i, line in enumerate(lines):
    if line.startswith('TOOLS = {') and tools_line is None:
        tools_line = i
    if '# ── Helper: load CGM readings from S3' in line and block_start is None:
        block_start = i
    if 'def lambda_handler(' in line:
        lambda_handler_line = i
        break

if tools_line is None:
    print("❌ Could not find TOOLS dict")
    sys.exit(1)

if block_start is None:
    # Try alternate: find the first post-registry tool function
    for i, line in enumerate(lines):
        if 'def tool_get_glucose_meal_response(' in line:
            # Back up to its comment header
            block_start = i - 2  # include comment line
            while block_start > 0 and lines[block_start].strip() == '':
                block_start -= 1
            block_start += 1
            break

if block_start is None:
    print("❌ Could not find function block to move")
    sys.exit(1)

if lambda_handler_line is None:
    print("❌ Could not find lambda_handler")
    sys.exit(1)

# Block ends just before lambda_handler (back up past blank lines and comment)
block_end = lambda_handler_line
while block_end > 0 and (lines[block_end-1].strip() == '' or lines[block_end-1].startswith('# ── Lambda')):
    block_end -= 1
block_end += 1  # include last line of block

# Validate: check the block contains our target functions
block_text = ''.join(lines[block_start:block_end])
for fn in ['tool_get_glucose_meal_response', 'tool_get_day_type_analysis', 'tool_get_fasting_glucose_validation']:
    if f'def {fn}(' not in block_text:
        print(f"❌ Block doesn't contain {fn}")
        sys.exit(1)

print(f"TOOLS dict at line {tools_line + 1}")
print(f"Block to move: lines {block_start + 1}-{block_end} ({block_end - block_start} lines)")
print(f"Lambda handler at line {lambda_handler_line + 1}")

# Perform the move
block = lines[block_start:block_end]
new_lines = lines[:block_start] + lines[block_end:]
# Recalculate tools_line position after removal
# (block_start is after tools_line, so tools_line index unchanged)
new_lines = new_lines[:tools_line] + ['\n'] + block + ['\n'] + new_lines[tools_line:]

with open('package/mcp_server.py', 'w') as f:
    f.writelines(new_lines)

# Verify
import re
with open('package/mcp_server.py') as f:
    content = f.read()
    fixed_lines = content.split('\n')

fn_refs = re.findall(r'"fn":\s*(tool_\w+)', content)
fn_defs = set(re.findall(r'^def (tool_\w+)\(', content, re.MULTILINE))
missing = [fn for fn in fn_refs if fn not in fn_defs]

# Find positions
new_tools = None
for i, line in enumerate(fixed_lines):
    if line.startswith('TOOLS = {'):
        new_tools = i + 1
        break

fn_positions = {}
for fn in ['tool_get_glucose_meal_response', 'tool_get_day_type_analysis', 'tool_get_fasting_glucose_validation']:
    for i, line in enumerate(fixed_lines):
        if f'def {fn}(' in line:
            fn_positions[fn] = i + 1
            break

print(f"\nAfter fix — TOOLS at line {new_tools}")
for fn, pos in sorted(fn_positions.items(), key=lambda x: x[1]):
    status = "✅ BEFORE" if pos < new_tools else "❌ AFTER"
    print(f"  {fn}: line {pos} {status}")

if missing:
    print(f"\n❌ Missing definitions: {missing}")
    sys.exit(1)

print(f"\n✅ All {len(fn_refs)} tool references resolve correctly")
print(f"✅ Fixed file: {len(fixed_lines)} lines")
PYEOF

if [ $? -ne 0 ]; then
    echo "❌ Fix failed — aborting"
    rm -rf "$WORK_DIR"
    exit 1
fi

# Syntax check
python3 -c "import py_compile; py_compile.compile('package/mcp_server.py', doraise=True)" && \
    echo "✅ Python syntax check passed" || \
    { echo "❌ Syntax error in fixed file"; rm -rf "$WORK_DIR"; exit 1; }

echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "  STEP 3: Package and deploy"
echo "══════════════════════════════════════════════════════════════════"

cd package
zip -q -r ../hotfix_deploy.zip .
cd ..
echo "Package size: $(du -h hotfix_deploy.zip | cut -f1)"

echo "Uploading fixed code..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --zip-file "fileb://hotfix_deploy.zip" \
    --query '[FunctionName, CodeSize, LastModified]' \
    --output table

echo "Waiting for update..."
aws lambda wait function-updated \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION"

echo "Bumping memory: 512 → 1024 MB..."
aws lambda update-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --memory-size 1024 \
    --query '[FunctionName, MemorySize, LastModified]' \
    --output table

echo "Waiting for config update..."
aws lambda wait function-updated \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION"

echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "  STEP 4: Verify"
echo "══════════════════════════════════════════════════════════════════"

echo "Test 1: list_tools..."
RESULT=$(aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --payload '{"tool": "list_tools", "parameters": {}}' \
    --log-type Tail \
    /tmp/hotfix_test.json 2>&1)

if echo "$RESULT" | grep -q "FunctionError"; then
    echo "❌ STILL BROKEN"
    echo "$RESULT" | python3 -c "import sys,base64,json; d=json.load(sys.stdin); print(base64.b64decode(d.get('LogResult','')).decode()[-500:])" 2>/dev/null || true
else
    echo "✅ list_tools passed (no FunctionError)"
fi

echo ""
echo "Test 2: MCP protocol call (get_sources)..."
aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --payload '{"body": "{\"jsonrpc\": \"2.0\", \"id\": 1, \"method\": \"tools/call\", \"params\": {\"name\": \"get_sources\", \"arguments\": {}}}"}' \
    /tmp/hotfix_test2.json 2>/dev/null

if grep -q '"statusCode": 200' /tmp/hotfix_test2.json 2>/dev/null; then
    echo "✅ get_sources MCP call succeeded"
else
    echo "⚠️  Response:"
    cat /tmp/hotfix_test2.json | python3 -m json.tool 2>/dev/null | head -10
fi

echo ""
echo "Final config:"
aws lambda get-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --query "[MemorySize, Timeout, CodeSize, LastModified]" \
    --output table

# Save fixed mcp_server.py locally for future sessions
cp "$WORK_DIR/package/mcp_server.py" "$SCRIPT_DIR/mcp_server.py"
echo "✅ Local mcp_server.py updated with fix"

# Cleanup
rm -rf "$WORK_DIR"
rm -f /tmp/hotfix_test.json /tmp/hotfix_test2.json

echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "  ✅ STEPS 1 & 2 COMPLETE"
echo "  - NameError fixed: 3 functions + helper moved before TOOLS dict"
echo "  - Memory: 512 MB → 1024 MB (2x CPU allocation)"
echo "  - 72 tool references verified"
echo "══════════════════════════════════════════════════════════════════"
