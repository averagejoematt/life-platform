#!/bin/bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════════════════
# Deploy Notion Lambda v1.1.0 — Body Text Extraction
#
# Adds: page body text fetching, body_text field in DynamoDB, enriched raw_text
# The ingestion Lambda now captures free-form writing from the Notion page body,
# not just structured property fields.
# ══════════════════════════════════════════════════════════════════════════════

cd ~/Documents/Claude/life-platform

REGION="us-west-2"
FUNCTION_NAME="notion-journal-ingestion"

echo "═══════════════════════════════════════════════════"
echo "  Deploying Notion Lambda v1.1.0 — Body Text"
echo "═══════════════════════════════════════════════════"
echo ""

# ── Package Lambda ───────────────────────────────────────────────────────────
echo "Packaging Lambda..."
cd lambdas
zip -j notion-journal-ingestion.zip notion_lambda.py
echo "  ✓ Package: notion-journal-ingestion.zip"

# ── Deploy ───────────────────────────────────────────────────────────────────
echo ""
echo "Deploying to AWS..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file fileb://notion-journal-ingestion.zip \
    --region "$REGION" > /dev/null
echo "  ✓ Lambda updated: $FUNCTION_NAME"

# ── Wait for propagation ────────────────────────────────────────────────────
echo ""
echo "Waiting 10s for propagation..."
sleep 10

# ── Test with today's entry ──────────────────────────────────────────────────
echo ""
echo "Testing with today's journal entry..."
aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --payload '{"date": "2026-03-03"}' \
    --cli-binary-format raw-in-base64-out \
    --region "$REGION" \
    /tmp/notion_body_test.json > /dev/null

echo "  Lambda response:"
python3 -m json.tool /tmp/notion_body_test.json
echo ""

# ── Verify DynamoDB ─────────────────────────────────────────────────────────
echo "Checking DynamoDB for body_text..."
aws dynamodb get-item \
    --table-name life-platform \
    --key '{"pk": {"S": "USER#matthew#SOURCE#notion"}, "sk": {"S": "DATE#2026-03-03#journal#morning"}}' \
    --projection-expression "sk, body_text, raw_text" \
    --region "$REGION" | python3 -c "
import json, sys
data = json.load(sys.stdin)
item = data.get('Item', {})
body = item.get('body_text', {}).get('S', '')
raw = item.get('raw_text', {}).get('S', '')
print(f'  SK: {item.get(\"sk\", {}).get(\"S\", \"?\")}')
print(f'  body_text: {len(body)} chars')
if body:
    print(f'  Preview: {body[:200]}...' if len(body) > 200 else f'  Preview: {body}')
print(f'  raw_text: {len(raw)} chars')
if raw:
    print(f'  Preview: {raw[:200]}...' if len(raw) > 200 else f'  Preview: {raw}')
"

# ── Test enrichment ──────────────────────────────────────────────────────────
echo ""
read -p "Run Haiku enrichment on this entry now? (y/N): " ENRICH
if [[ "$ENRICH" == "y" || "$ENRICH" == "Y" ]]; then
    echo ""
    echo "Running journal-enrichment Lambda..."
    aws lambda invoke \
        --function-name journal-enrichment \
        --payload '{"date": "2026-03-03", "force": true}' \
        --cli-binary-format raw-in-base64-out \
        --region "$REGION" \
        /tmp/enrichment_test.json > /dev/null
    echo "  Enrichment response:"
    python3 -m json.tool /tmp/enrichment_test.json
    echo ""

    echo "Checking enriched fields..."
    aws dynamodb get-item \
        --table-name life-platform \
        --key '{"pk": {"S": "USER#matthew#SOURCE#notion"}, "sk": {"S": "DATE#2026-03-03#journal#morning"}}' \
        --projection-expression "enriched_mood, enriched_energy, enriched_stress, enriched_sentiment, enriched_themes, enriched_notable_quote, enriched_at" \
        --region "$REGION" | python3 -c "
import json, sys
data = json.load(sys.stdin)
item = data.get('Item', {})
for k, v in sorted(item.items()):
    val = v.get('S') or v.get('N') or v.get('L') or v.get('BOOL')
    if isinstance(val, list):
        val = [x.get('S', x) for x in val]
    print(f'  {k}: {val}')
"
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✓ Notion Lambda v1.1.0 deployed!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  What changed:"
echo "    - Lambda now fetches page body text (free writing)"
echo "    - body_text field stored in DynamoDB"
echo "    - raw_text includes body text for Haiku enrichment"
echo ""
echo "  Journaling workflow:"
echo "    1. Open Notion database, click New → Empty"
echo "    2. Set Template (Morning/Evening/etc) and Date"
echo "    3. Write freely in the page body"
echo "    4. Lambda picks it up at 6 AM PT"
echo "    5. Haiku enriches at 6:30 AM PT"
echo ""
echo "  Manual test:"
echo "    aws lambda invoke --function-name notion-journal-ingestion \\"
echo "      --payload '{\"date\": \"2026-03-03\"}' --region us-west-2 /tmp/result.json"
echo ""
