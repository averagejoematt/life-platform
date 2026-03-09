#!/bin/bash
# deploy_feature7_training_rec.sh — Deploy Feature #7: Readiness-Based Training Recommendation
# Adds tool_get_training_recommendation to MCP server
# MCP-only change — no Lambda pipeline changes needed
set -euo pipefail

echo "═══════════════════════════════════════════════════════════════"
echo "  Feature #7: Readiness-Based Training Recommendation"
echo "  MCP server update only"
echo "═══════════════════════════════════════════════════════════════"

cd ~/Documents/Claude/life-platform

# ── Step 1: Backup ──────────────────────────────────────────────────────────
cp mcp_server.py mcp_server.py.bak.f7
echo "✅ Backup: mcp_server.py.bak.f7"

# ── Step 2: Insert tool function before TOOLS dict ──────────────────────────
python3 -c "
import re

with open('mcp_server.py', 'r') as f:
    content = f.read()

# Read the patch
with open('patches/patch_training_recommendation.py', 'r') as f:
    patch = f.read()

# Extract tool function code
import ast
module = ast.parse(patch)
for node in ast.walk(module):
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if hasattr(target, 'id') and target.id == 'TRAINING_REC_CODE':
                code_str = ast.literal_eval(node.value)
                break

# Insert before TOOLS = {
insert_point = content.find('\nTOOLS = {')
if insert_point == -1:
    print('ERROR: Could not find TOOLS dict')
    exit(1)

content = content[:insert_point] + '\n' + code_str + '\n' + content[insert_point:]
print('Inserted tool_get_training_recommendation function')

# Now add the TOOLS entry — find the closing of the TOOLS dict
# We'll insert before the final }
# Find the last entry in TOOLS and add after it
tools_entry = '''
    \"get_training_recommendation\": {
        \"fn\": tool_get_training_recommendation,
        \"schema\": {
            \"name\": \"get_training_recommendation\",
            \"description\": (
                \"Readiness-based training recommendation. Synthesizes Whoop recovery, Eight Sleep quality, \"
                \"Garmin Body Battery, training load (CTL/ATL/TSB), recent activity history, and muscle group \"
                \"recency into a specific workout suggestion: type (Zone 2, intervals, strength upper/lower, \"
                \"active recovery, rest), intensity, duration, HR targets, and muscle groups to target. \"
                \"Board of Directors provides rationale. Warns about injury risk (ACWR), consecutive training days, \"
                \"and sleep debt. Use for: 'what should I do today?', 'workout recommendation', 'should I train today?', \"
                \"'am I recovered enough for a hard workout?', 'readiness-based training', 'what workout today?'.\"
            ),
            \"inputSchema\": {
                \"type\": \"object\",
                \"properties\": {
                    \"date\": {\"type\": \"string\", \"description\": \"Date YYYY-MM-DD (default: today).\"},
                },
                \"required\": [],
            },
        },
    },'''

# Find the health_trajectory entry and add after its closing brace
marker = '\"get_health_trajectory\":'
idx = content.find(marker)
if idx == -1:
    print('ERROR: Could not find get_health_trajectory in TOOLS')
    exit(1)

# Find the closing of that entry (matching braces)
depth = 0
i = idx
found_first = False
end_idx = idx
for i in range(idx, len(content)):
    if content[i] == '{':
        depth += 1
        found_first = True
    elif content[i] == '}':
        depth -= 1
        if found_first and depth == 0:
            end_idx = i + 1
            break

# Insert after the comma following the closing
# Look for the comma or add one
if content[end_idx:end_idx+1] == ',':
    insert_at = end_idx + 1
else:
    content = content[:end_idx] + ',' + content[end_idx:]
    insert_at = end_idx + 1

content = content[:insert_at] + tools_entry + content[insert_at:]
print('Inserted TOOLS entry for get_training_recommendation')

with open('mcp_server.py', 'w') as f:
    f.write(content)

print('mcp_server.py updated successfully')
"

echo "✅ Tool function + TOOLS entry inserted"

# ── Step 3: Package MCP server ──────────────────────────────────────────────
cp mcp_server.py lambdas/mcp_server.py
cd lambdas
rm -f mcp_server.zip
zip mcp_server.zip mcp_server.py
cd ..
echo "✅ Packaged: lambdas/mcp_server.zip"

# ── Step 4: Deploy ──────────────────────────────────────────────────────────
aws lambda update-function-code \
  --function-name life-platform-mcp \
  --zip-file fileb://lambdas/mcp_server.zip \
  --region us-west-2

echo "✅ Deployed: life-platform-mcp Lambda"

# ── Step 5: Quick verify ────────────────────────────────────────────────────
echo ""
echo "Verifying tool count..."
TOOL_COUNT=$(grep -c '"fn":' mcp_server.py)
echo "Tool count in source: $TOOL_COUNT"
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Feature #7 deployed! Tool: get_training_recommendation"
echo "  Try: 'What should I do for a workout today?'"
echo "═══════════════════════════════════════════════════════════════"
