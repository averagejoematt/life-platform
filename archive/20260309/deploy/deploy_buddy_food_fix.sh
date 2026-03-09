#!/bin/bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════════════════
# Fix buddy page "No food logged in 99 days" bug
# Root cause: write_buddy_json looked for "calories" / "energy_kcal" fields
# but MacroFactor stores data as "total_calories_kcal" / "total_protein_g"
# ══════════════════════════════════════════════════════════════════════════════

cd ~/Documents/Claude/life-platform

REGION="us-west-2"
FUNCTION_NAME="daily-brief"

echo "═══════════════════════════════════════════════════"
echo "  Fix: Buddy page food logging field name mismatch"
echo "═══════════════════════════════════════════════════"
echo ""

# ── Package ──────────────────────────────────────────────────────────────────
echo "Packaging Daily Brief Lambda..."
cd lambdas
cp daily_brief_lambda.py lambda_function.py
zip -j daily_brief_lambda.zip lambda_function.py
rm lambda_function.py
echo "  ✓ Package ready"

# ── Deploy ───────────────────────────────────────────────────────────────────
echo "Deploying..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file fileb://daily_brief_lambda.zip \
    --region "$REGION" > /dev/null
echo "  ✓ Lambda updated: $FUNCTION_NAME"

# ── Wait ─────────────────────────────────────────────────────────────────────
echo ""
echo "Waiting 10s..."
sleep 10

# ── Re-generate buddy JSON now ───────────────────────────────────────────────
echo ""
echo "Re-running Daily Brief to regenerate buddy/data.json..."
aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --payload '{}' \
    --cli-binary-format raw-in-base64-out \
    --region "$REGION" \
    /tmp/daily_brief_buddy_fix.json > /dev/null

echo "  Response:"
python3 -m json.tool /tmp/daily_brief_buddy_fix.json 2>/dev/null || cat /tmp/daily_brief_buddy_fix.json
echo ""

# ── Verify buddy JSON ───────────────────────────────────────────────────────
echo ""
echo "Checking buddy/data.json..."
aws s3 cp s3://matthew-life-platform/buddy/data.json /tmp/buddy_check.json --region "$REGION" 2>/dev/null
python3 -c "
import json
with open('/tmp/buddy_check.json') as f:
    data = json.load(f)
for s in data.get('status_lines', []):
    emoji = {'green':'🟢','yellow':'🟡','red':'🔴'}.get(s['status'],'⚪')
    print(f'  {emoji} {s[\"area\"]}: {s[\"text\"]}')
print()
print(f'  Beacon: {data.get(\"beacon\")} — {data.get(\"beacon_label\")}')
print(f'  Generated: {data.get(\"generated_at\", \"?\")[:19]}')
"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✓ Done! Refresh buddy.averagejoematt.com"
echo "═══════════════════════════════════════════════════"
