#!/bin/bash
# hotfix_move_functions.sh — Move 8 misplaced tool functions from after TOOLS to before TOOLS
# Fixes NameError: name 'tool_get_day_type_analysis' is not defined
set -euo pipefail

echo "═══════════════════════════════════════════════════════════════"
echo "  HOTFIX: Move misplaced tool functions before TOOLS dict"
echo "  Fixes: NameError on tool_get_day_type_analysis (and 7 others)"
echo "═══════════════════════════════════════════════════════════════"

cd ~/Documents/Claude/life-platform

cp mcp_server.py mcp_server.py.bak.hotfix
echo "✅ Backup: mcp_server.py.bak.hotfix"

python3 << 'PYFIX'
with open("mcp_server.py") as f:
    lines = f.readlines()

# Find TOOLS = { line
tools_start = None
for i, line in enumerate(lines):
    if line.strip().startswith("TOOLS = {"):
        tools_start = i
        break

if tools_start is None:
    print("ERROR: Could not find TOOLS = {")
    exit(1)

# Find closing brace of TOOLS dict
depth = 0
tools_end = None
for i in range(tools_start, len(lines)):
    for ch in lines[i]:
        if ch == '{': depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                tools_end = i
                break
    if tools_end is not None:
        break

print(f"TOOLS dict: lines {tools_start+1}-{tools_end+1}")

# Find first "def tool_" AFTER tools_end
first_misplaced = None
for i in range(tools_end + 1, len(lines)):
    if lines[i].startswith("def tool_"):
        first_misplaced = i
        break

if first_misplaced is None:
    print("No misplaced functions found — already fixed?")
    exit(0)

# Extract the block from first misplaced function to end of file
misplaced_block = lines[first_misplaced:]
print(f"Moving lines {first_misplaced+1}-{len(lines)} ({len(misplaced_block)} lines) to before TOOLS dict")

# Count functions being moved
moved_funcs = [l.strip() for l in misplaced_block if l.startswith("def tool_")]
for f in moved_funcs:
    print(f"  Moving: {f}")

# Reconstruct file:
# 1. Everything before TOOLS
# 2. The misplaced function block (with separator)
# 3. TOOLS dict
# 4. Everything between TOOLS end and the misplaced block (handlers, warmer, etc.)
before_tools = lines[:tools_start]
tools_dict = lines[tools_start:tools_end + 1]
between = lines[tools_end + 1:first_misplaced]

separator = [
    "\n",
    "# ══════════════════════════════════════════════════════════════════════════════\n",
    "# Tool functions (relocated from post-TOOLS position)\n",
    "# ══════════════════════════════════════════════════════════════════════════════\n",
    "\n",
]

new_content = before_tools + separator + misplaced_block + ["\n\n"] + tools_dict + between

with open("mcp_server.py", "w") as f:
    f.writelines(new_content)

print(f"\nFile rewritten: {len(new_content)} lines")

# Verify
with open("mcp_server.py") as f:
    verify = f.readlines()

new_tools_line = None
for i, line in enumerate(verify):
    if line.strip().startswith("TOOLS = {"):
        new_tools_line = i
        break

# Check all tool_ functions are before TOOLS
problems = []
for i, line in enumerate(verify):
    if line.startswith("def tool_") and i > new_tools_line:
        problems.append(f"  Line {i+1}: {line.strip()}")

if problems:
    print(f"\nWARNING: {len(problems)} functions still after TOOLS:")
    for p in problems:
        print(p)
else:
    print(f"\n✅ All tool functions are now before TOOLS (line {new_tools_line+1})")

# Count total tools
tool_count = sum(1 for line in verify if '"fn":' in line and 'tool_' in line)
print(f"Total TOOLS entries: {tool_count}")
PYFIX

echo ""
echo "Deploying fixed MCP server..."

cp mcp_server.py lambdas/mcp_server.py
cd lambdas && rm -f mcp_server.zip && zip mcp_server.zip mcp_server.py && cd ..

aws lambda update-function-code \
  --function-name life-platform-mcp \
  --zip-file fileb://lambdas/mcp_server.zip \
  --region us-west-2

echo ""
echo "Waiting 5s for Lambda to stabilize..."
sleep 5

# Quick smoke test
echo "Smoke test..."
aws lambda invoke \
  --function-name life-platform-mcp \
  --payload '{"httpMethod":"POST","headers":{"content-type":"application/json"},"body":"{\"jsonrpc\":\"2.0\",\"method\":\"tools/list\",\"id\":1}"}' \
  --region us-west-2 \
  /dev/stdout 2>/dev/null | python3 -c "
import json, sys
try:
    resp = json.load(sys.stdin)
    if 'FunctionError' in resp:
        print('❌ STILL BROKEN — check CloudWatch')
    else:
        print('✅ Lambda responding (no FunctionError)')
except:
    # Response might be the raw output
    print('⚠️  Could not parse response — check CloudWatch')
"

TOOL_COUNT=$(grep -c '"fn":' mcp_server.py)
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  HOTFIX complete. MCP tool count: $TOOL_COUNT"
echo "═══════════════════════════════════════════════════════════════"
