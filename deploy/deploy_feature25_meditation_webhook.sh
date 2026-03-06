#!/bin/bash
# Feature #25 — Meditation & Breathwork Tracking: Webhook Enhancement
# Adds mindful_minutes to Health Auto Export Lambda METRIC_MAP
# v2.37.0

set -euo pipefail
REGION="us-west-2"
FUNCTION_NAME="health-auto-export-webhook"
LAMBDA_DIR="$HOME/Documents/Claude/life-platform/lambdas"
SOURCE_FILE="$LAMBDA_DIR/health_auto_export_lambda.py"

echo "═══════════════════════════════════════════════════════════"
echo "Feature #25 — Add mindful_minutes to HAE webhook"
echo "═══════════════════════════════════════════════════════════"

# ── Step 1: Patch the webhook Lambda source to add Mindful Minutes ──
echo ""
echo "Step 1: Patching health_auto_export_lambda.py..."

# Check if already patched
if grep -q "mindful_minutes" "$SOURCE_FILE"; then
    echo "⚠️  mindful_minutes already present in source. Skipping patch."
else
    # Insert after the caffeine line in _METRIC_DEFS
    # Find the caffeine line and add mindful minutes after it
    sed -i.bak '/dietary_caffeine.*caffeine_mg.*agg.*sum.*tier.*1/a\
    # Mindful minutes (meditation/breathwork apps → Apple Health)\
    ({"Mindful Minutes", "mindful_minutes", "Apple Mindfulness", "apple_mindfulness"},  {"field": "mindful_minutes",           "agg": "sum",         "tier": 1}),' "$SOURCE_FILE"
    echo "✅ Added mindful_minutes to METRIC_MAP (Tier 1, sum aggregation)"
fi

# ── Step 2: Package and deploy ──
echo ""
echo "Step 2: Packaging Lambda..."
TMPDIR=$(mktemp -d)
cp "$SOURCE_FILE" "$TMPDIR/lambda_function.py"
cd "$TMPDIR"
zip -r health_auto_export.zip lambda_function.py
cp health_auto_export.zip "$LAMBDA_DIR/health_auto_export_lambda.zip"

echo ""
echo "Step 3: Deploying to Lambda..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://health_auto_export.zip" \
    --region "$REGION" \
    --query "[FunctionName,CodeSize,LastModified]" \
    --output table

echo ""
echo "Step 4: Waiting for update to complete..."
aws lambda wait function-updated \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" 2>/dev/null || sleep 10

echo ""
echo "Step 5: Smoke test..."
aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --payload '{"headers":{"authorization":"Bearer test"},"body":"{}"}' \
    /tmp/hae_test_response.json \
    --query "StatusCode" --output text

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ Feature #25 webhook patch deployed!"
echo ""
echo "New field: mindful_minutes (daily sum, minutes)"
echo "Source: Apple Health → Health Auto Export → webhook → DynamoDB"
echo "Apps: Apple Mindfulness, Headspace, Calm, Insight Timer"
echo ""
echo "Next: Configure Health Auto Export iOS app to export 'Mindful Minutes'"
echo "      Settings → Health Metrics → enable 'Mindful Minutes'"
echo "═══════════════════════════════════════════════════════════"

# Cleanup
rm -rf "$TMPDIR"
