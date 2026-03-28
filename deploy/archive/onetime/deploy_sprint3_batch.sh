#!/bin/bash
# deploy_sprint3_batch.sh — Deploy Sprint 3 remaining items (v3.7.67)
set -e

cd ~/Documents/Claude/life-platform
echo "=== Sprint 3 Batch Deploy (v3.7.67) ==="
echo ""

# ── Step 1: Text-based registry validation ──
echo "[1/6] Validating registry (text-based)..."
python3 << 'PYEOF'
import re, sys

with open("mcp/registry.py") as f:
    reg = f.read()

tool_keys = re.findall(r'^\s+"([a-z_]+)":\s*\{', reg, re.MULTILINE)
fn_refs = re.findall(r'"fn":\s*([\w.]+)', reg)

expected_new = [
    "get_deficit_sustainability",
    "get_metabolic_adaptation",
    "get_sleep_environment_analysis",
    "get_autonomic_balance",
    "get_journal_sentiment_trajectory",
]

errors = []
for tool in expected_new:
    if tool not in tool_keys:
        errors.append(f"  MISSING tool key: {tool}")
    fn_name = f"tool_{tool}"
    if fn_name not in fn_refs:
        errors.append(f"  MISSING fn ref: {fn_name}")

checks = [
    ("mcp/tools_nutrition.py", "def tool_get_deficit_sustainability"),
    ("mcp/tools_nutrition.py", "def tool_get_metabolic_adaptation"),
    ("mcp/tools_sleep.py",     "def tool_get_sleep_environment_analysis"),
    ("mcp/tools_health.py",    "def tool_get_autonomic_balance"),
    ("mcp/tools_journal.py",   "def tool_get_journal_sentiment_trajectory"),
]
for filepath, funcdef in checks:
    with open(filepath) as f:
        if funcdef not in f.read():
            errors.append(f"  MISSING function: {funcdef} in {filepath}")

if errors:
    print("FAIL:")
    for e in errors:
        print(e)
    sys.exit(1)

print(f"PASS — {len(tool_keys)} tool keys found, all 5 new tools verified")
PYEOF

if [ $? -ne 0 ]; then
    echo "❌ Registry validation FAILED."
    exit 1
fi
echo "✅ Registry validation passed."
echo ""

# ── Step 2: Deploy MCP Lambda (full package build) ──
echo "[2/6] Deploying MCP Lambda (life-platform-mcp)..."
ZIP=/tmp/mcp_deploy.zip
rm -f $ZIP
zip -j $ZIP mcp_server.py mcp_bridge.py
zip -r $ZIP mcp/ -x 'mcp/__pycache__/*' 'mcp/*.pyc'
aws lambda update-function-code \
    --function-name life-platform-mcp \
    --zip-file fileb://$ZIP \
    --region us-west-2 \
    --no-cli-pager > /dev/null
echo "✅ MCP Lambda deployed."
echo ""

# ── Step 3: Wait 10s between deploys ──
echo "[3/6] Waiting 10s..."
sleep 10

# ── Step 4: Deploy daily-brief Lambda (hero paragraph fix in site_writer.py) ──
echo "[4/6] Deploying daily-brief Lambda..."
bash deploy/deploy_lambda.sh daily-brief lambdas/daily_brief_lambda.py \
    --extra-files lambdas/ai_calls.py lambdas/html_builder.py lambdas/output_writers.py lambdas/board_loader.py lambdas/site_writer.py
echo "✅ daily-brief Lambda deployed."
echo ""

# ── Step 5: Update PLATFORM_FACTS tool count ──
echo "[5/6] Updating PLATFORM_FACTS tool count..."
python3 -c "
import re
path = 'deploy/sync_doc_metadata.py'
with open(path) as f:
    content = f.read()
old = re.search(r'\"mcp_tools\":\s*(\d+)', content)
if old:
    old_count = old.group(1)
    content = content.replace('\"mcp_tools\": ' + old_count, '\"mcp_tools\": 95')
    with open(path, 'w') as f:
        f.write(content)
    print(f'   mcp_tools: {old_count} -> 95')
else:
    print('   WARNING: Could not find mcp_tools. Update manually.')
"
echo ""

# ── Step 6: Sync docs ──
echo "[6/6] Running doc metadata sync..."
python3 deploy/sync_doc_metadata.py --apply
echo "✅ Doc metadata synced."
echo ""

echo "=== Deploy complete! ==="
echo ""
echo "Next steps:"
echo "  1. Update docs/CHANGELOG.md"
echo "  2. Write handovers/HANDOVER_v3.7.67.md"
echo "  3. Update handovers/HANDOVER_LATEST.md"
echo "  4. git add -A && git commit -m 'v3.7.67: Sprint 3 complete — BS-12 BS-SL1 BS-MP1 BS-MP2 IC-29 hero-fix' && git push"
