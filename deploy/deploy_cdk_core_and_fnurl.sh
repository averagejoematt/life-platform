#!/bin/bash
# deploy_cdk_core_and_fnurl.sh — Import SQS+SNS into CoreStack, publish Layer, import Function URL
#
# CoreStack: SQS DLQ + SNS topic imported, Lambda Layer created new
# McpStack: Function URL imported
set -euo pipefail
cd ~/Documents/Claude/life-platform/cdk

echo "═══════════════════════════════════════════════════════════════"
echo " CDK Core + Function URL Migration"
echo "═══════════════════════════════════════════════════════════════"

# ── Phase 1: Import + Deploy CoreStack ──
echo ""
echo "▸ Phase 1: Importing SQS + SNS + creating Lambda Layer..."
echo ""
echo "  cdk import will prompt you. Answer:"
echo "    IngestionDLQ → enter the queue URL when prompted"
echo "    AlertsTopic  → enter the topic ARN when prompted"
echo "    SharedUtilsLayer → this is NEW, CDK will create it (not import)"
echo ""

npx cdk import LifePlatformCore --resource-mapping core-import-map.json

echo ""
echo "  ✅ CoreStack imported. Now deploying to create Lambda Layer..."
npx cdk deploy LifePlatformCore --require-approval never
echo "  ✅ CoreStack deployed"

# ── Phase 2: Import Function URL into MCP Stack ──
echo ""
echo "▸ Phase 2: Importing Function URL into LifePlatformMcp..."
echo ""
echo "  cdk import will prompt for the Function URL resource."
echo "  When asked for the physical resource ID, enter:"
echo "    life-platform-mcp"
echo ""

npx cdk import LifePlatformMcp

echo ""
echo "  ✅ Function URL imported. Deploying to wire output..."
npx cdk deploy LifePlatformMcp --require-approval never
echo "  ✅ MCP stack deployed"

# ── Verify ──
echo ""
echo "▸ Verifying..."
LAYER_ARN=$(aws lambda list-layers --query "Layers[?LayerName=='life-platform-shared-utils'].LatestMatchingVersion.LayerVersionArn" --output text)
echo "  Layer: $LAYER_ARN"
FN_URL=$(aws lambda get-function-url-config --function-name life-platform-mcp --query "FunctionUrl" --output text 2>/dev/null || echo "NOT FOUND")
echo "  Function URL: $FN_URL"

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo " Done! CDK now manages:"
echo "   ✅ SQS DLQ (life-platform-ingestion-dlq)"
echo "   ✅ SNS Topic (life-platform-alerts)"  
echo "   ✅ Lambda Layer (life-platform-shared-utils)"
echo "   ✅ MCP Function URL"
echo ""
echo " Deliberately unmanaged (by design):"
echo "   - DynamoDB table (stateful — too risky)"
echo "   - S3 bucket (stateful — too risky)"
echo "   - CloudFront distributions (complex, stable)"
echo "═══════════════════════════════════════════════════════════════"
