#!/bin/bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════════════════
# Day Grade Regrade — Feb 24 to Mar 2
#
# Hydration data was missing/partial due to Health Auto Export not pushing
# Dietary Water in automatic syncs. Now backfilled via forced push.
# This script deploys the regrade-capable Lambda and re-runs day grades.
# ══════════════════════════════════════════════════════════════════════════════

cd ~/Documents/Claude/life-platform

REGION="us-west-2"

echo "═══════════════════════════════════════════════════"
echo "  Day Grade Regrade (hydration backfill)"
echo "═══════════════════════════════════════════════════"
echo ""

# ── 1. Deploy Lambda with regrade mode ──────────────────────────────────────
echo "[1/3] Packaging Daily Brief Lambda (with regrade handler)..."
cd lambdas
cp daily_brief_lambda.py lambda_function.py
zip -j daily_brief_lambda.zip lambda_function.py
rm lambda_function.py

aws lambda update-function-code \
    --function-name daily-brief \
    --zip-file fileb://daily_brief_lambda.zip \
    --region "$REGION" > /dev/null
echo "  ✓ Lambda deployed with regrade mode"

# ── 2. Wait for propagation ─────────────────────────────────────────────────
echo ""
echo "[2/3] Waiting 10s for propagation..."
sleep 10

# ── 3. Invoke regrade ──────────────────────────────────────────────────────
echo ""
echo "[3/3] Regrading Feb 24 → Mar 2..."

PAYLOAD='{"regrade_dates":["2026-02-24","2026-02-25","2026-02-26","2026-02-27","2026-02-28","2026-03-01","2026-03-02"]}'

aws lambda invoke \
    --function-name daily-brief \
    --payload "$PAYLOAD" \
    --cli-binary-format raw-in-base64-out \
    --region "$REGION" \
    /tmp/regrade_result.json > /dev/null

echo ""
echo "Results:"
python3 -c "
import json
with open('/tmp/regrade_result.json') as f:
    data = json.load(f)
for r in data.get('results', []):
    if 'error' in r:
        print(f'  ❌ {r[\"date\"]}: {r[\"error\"]}')
    else:
        hyd = r.get('hydration', '—')
        print(f'  ✅ {r[\"date\"]}: {r[\"score\"]} ({r[\"grade\"]}) — hydration: {hyd}')
"

# ── Verify ───────────────────────────────────────────────────────────────────
echo ""
echo "Verifying stored grades..."
python3 -c "
import boto3, json
from decimal import Decimal

class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal): return float(o)
        return super().default(o)

ddb = boto3.resource('dynamodb', region_name='us-west-2')
table = ddb.Table('life-platform')
r = table.query(
    KeyConditionExpression='pk = :pk AND sk BETWEEN :s AND :e',
    ExpressionAttributeValues={
        ':pk': 'USER#matthew#SOURCE#day_grade',
        ':s': 'DATE#2026-02-24',
        ':e': 'DATE#2026-03-02',
    }
)
print(f'  {\"Date\":<12} {\"Grade\":<8} {\"Score\":<7} {\"Hydration\":<10}')
print(f'  {\"─\"*12} {\"─\"*8} {\"─\"*7} {\"─\"*10}')
for item in r['Items']:
    d = item.get('date','?')
    g = item.get('letter_grade','?')
    s = item.get('total_score','?')
    h = item.get('component_hydration','—')
    print(f'  {d:<12} {g:<8} {s:<7} {h}')
"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✓ Regrade complete!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  The regrade_dates feature is now permanently"
echo "  available for future use:"
echo ""
echo "    aws lambda invoke --function-name daily-brief \\"
echo "      --payload '{\"regrade_dates\":[\"2026-03-03\"]}' \\"
echo "      --cli-binary-format raw-in-base64-out \\"
echo "      --region us-west-2 /tmp/out.json"
echo ""
