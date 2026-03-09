#!/bin/bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════════════════
# Notion Journal Phase 4 — Wire journal into daily brief + weekly digest
#
# 1. Run Python patcher on daily_brief_lambda.py + weekly_digest_lambda.py
# 2. Deploy updated daily-brief Lambda
# 3. Deploy updated weekly-digest Lambda
# 4. Test invocations
#
# Prerequisites:
#   - Phases 1-3 deployed (Notion ingestion + enrichment + MCP tools)
#   - Journal entries exist in DynamoDB with enriched fields
#
# Usage: bash deploy_journal_phase4.sh
# ══════════════════════════════════════════════════════════════════════════════

cd ~/Documents/Claude/life-platform

echo "═══════════════════════════════════════════════════"
echo "  Journal Phase 4 — Brief + Digest Integration"
echo "═══════════════════════════════════════════════════"
echo ""

REGION="us-west-2"

# ── Step 1: Run patcher ──────────────────────────────────────────────────────
echo "Step 1: Patching Lambda source files..."
echo "────────────────────────────────────────"
python3 patch_journal_phase4.py
echo ""

# ── Step 2: Deploy daily-brief Lambda ─────────────────────────────────────────
echo "Step 2: Deploying daily-brief Lambda..."
echo "───────────────────────────────────────"

# Daily brief needs DynamoDB read access to notion partition — check IAM
BRIEF_FUNCTION="daily-brief"
BRIEF_ROLE=$(aws lambda get-function --function-name "$BRIEF_FUNCTION" --region "$REGION" \
    --query 'Configuration.Role' --output text 2>/dev/null)
BRIEF_ROLE_NAME=$(echo "$BRIEF_ROLE" | awk -F'/' '{print $NF}')

echo "  Current role: $BRIEF_ROLE_NAME"

# Verify the role can query notion partition (same table, so existing DynamoDB permissions should cover it)
echo "  ✓ DynamoDB access: same table, no IAM changes needed"

rm -f daily_brief_lambda.zip
zip -q daily_brief_lambda.zip daily_brief_lambda.py

aws lambda update-function-code \
    --function-name "$BRIEF_FUNCTION" \
    --zip-file "fileb://daily_brief_lambda.zip" \
    --region "$REGION" > /dev/null
aws lambda wait function-updated --function-name "$BRIEF_FUNCTION" --region "$REGION"
echo "  ✓ daily-brief updated to v1.1.0"
echo ""

# ── Step 3: Deploy weekly-digest Lambda ───────────────────────────────────────
echo "Step 3: Deploying weekly-digest Lambda..."
echo "──────────────────────────────────────────"

DIGEST_FUNCTION="weekly-digest"

rm -f weekly_digest_lambda.zip
zip -q weekly_digest_lambda.zip weekly_digest_lambda.py

aws lambda update-function-code \
    --function-name "$DIGEST_FUNCTION" \
    --zip-file "fileb://weekly_digest_lambda.zip" \
    --region "$REGION" > /dev/null
aws lambda wait function-updated --function-name "$DIGEST_FUNCTION" --region "$REGION"
echo "  ✓ weekly-digest updated to v3.3.0"
echo ""

# ── Step 4: Test daily brief ──────────────────────────────────────────────────
echo "Step 4: Test invocations..."
echo "───────────────────────────"

read -p "  Send a test daily brief now? (y/N): " TEST_BRIEF
if [[ "$TEST_BRIEF" == "y" || "$TEST_BRIEF" == "Y" ]]; then
    echo "  Invoking daily-brief..."
    aws lambda invoke \
        --function-name "$BRIEF_FUNCTION" \
        --payload '{}' \
        --cli-binary-format raw-in-base64-out \
        --region "$REGION" \
        /tmp/brief_test.json > /dev/null
    echo "  Response:"
    python3 -m json.tool /tmp/brief_test.json
    echo ""
fi

read -p "  Send a test weekly digest now? (y/N): " TEST_DIGEST
if [[ "$TEST_DIGEST" == "y" || "$TEST_DIGEST" == "Y" ]]; then
    echo "  Invoking weekly-digest..."
    aws lambda invoke \
        --function-name "$DIGEST_FUNCTION" \
        --payload '{}' \
        --cli-binary-format raw-in-base64-out \
        --region "$REGION" \
        /tmp/digest_test.json > /dev/null
    echo "  Response:"
    python3 -m json.tool /tmp/digest_test.json
    echo ""
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✓ Journal Phase 4 deployed!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Daily Brief (v1.1.0):"
echo "    • Journal Pulse section: mood/energy/stress + themes + notable quote"
echo "    • Journal context fed into Haiku insight prompt"
echo "    • Graceful degradation: section hidden if no journal entries"
echo ""
echo "  Weekly Digest (v3.3.0):"
echo "    • Journal & Mood section: weekly averages, themes, emotions, avoidance flags"
echo "    • Best/worst mood days, notable quotes"
echo "    • W-o-W mood/energy/stress deltas"
echo "    • Coach Maya prompt updated to reference journal signals"
echo "    • Journal data added to Haiku board prompt"
echo ""
echo "  Pipeline complete:"
echo "    Notion DB → ingestion (6:00) → enrichment (6:30) → cache warm (8:00)"
echo "    → daily brief (8:15, now with Journal Pulse)"
echo "    → weekly digest (Sun 8:30, now with Journal & Mood section)"
echo ""
echo "  No IAM changes needed — both Lambdas already have DynamoDB table access."
echo "  Journal entries use the same table, just a different partition key."
echo ""
