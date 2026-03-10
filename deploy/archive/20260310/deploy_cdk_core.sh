#!/bin/bash
# deploy_cdk_core.sh — Import SQS+SNS into CoreStack + create Lambda Layer
set -euo pipefail
cd ~/Documents/Claude/life-platform

echo "═══════════════════════════════════════════════════════════════"
echo " CDK Core Stack — Import SQS+SNS + Create Lambda Layer"
echo "═══════════════════════════════════════════════════════════════"

# ── Step 1: Build layer ──
echo ""
echo "▸ Step 1: Building Lambda Layer..."
bash deploy/build_layer.sh

# ── Step 2: Synth + generate import map ──
echo ""
echo "▸ Step 2: Synthesizing template..."
cd cdk
npx cdk synth LifePlatformCore --quiet

TEMPLATE="cdk.out/LifePlatformCore.template.json"
if [ ! -f "$TEMPLATE" ]; then
    echo "❌ Template not found at $TEMPLATE"
    exit 1
fi

SQS_ID=$(python3 -c "
import json
t = json.load(open('$TEMPLATE'))
for k, v in t.get('Resources', {}).items():
    if v.get('Type') == 'AWS::SQS::Queue':
        print(k); break
")
SNS_ID=$(python3 -c "
import json
t = json.load(open('$TEMPLATE'))
for k, v in t.get('Resources', {}).items():
    if v.get('Type') == 'AWS::SNS::Topic':
        print(k); break
")

echo "  SQS logical ID: $SQS_ID"
echo "  SNS logical ID: $SNS_ID"

cat > core-import-map.json << EOF
{
    "$SQS_ID": {
        "QueueUrl": "https://sqs.us-west-2.amazonaws.com/205930651321/life-platform-ingestion-dlq"
    },
    "$SNS_ID": {
        "TopicArn": "arn:aws:sns:us-west-2:205930651321:life-platform-alerts"
    }
}
EOF
echo "  Import map:"
cat core-import-map.json

# ── Step 3: Import ──
echo ""
echo "▸ Step 3: Importing SQS + SNS into LifePlatformCore..."
echo "  (Layer is new — CDK creates it alongside the imports)"
echo ""

npx cdk import LifePlatformCore --resource-mapping core-import-map.json

echo ""
echo "  ✅ CoreStack imported"

# ── Step 4: Deploy ──
echo ""
echo "▸ Step 4: Deploying LifePlatformCore..."
npx cdk deploy LifePlatformCore --require-approval never

echo ""
LAYER_ARN=$(aws lambda list-layers --query "Layers[?LayerName=='life-platform-shared-utils'].LatestMatchingVersion.LayerVersionArn" --output text)
echo "  ✅ Done. Latest Layer ARN: $LAYER_ARN"
