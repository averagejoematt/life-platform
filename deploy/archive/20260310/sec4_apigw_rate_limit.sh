#!/usr/bin/env bash
# sec4_apigw_rate_limit.sh — SEC-4: Add throttling to health-auto-export-webhook API Gateway
#
# Adds rate limiting to prevent accidental flooding / abuse of the Health Auto Export
# webhook endpoint. Limits: 100 req/min burst, 60 req/min steady-state.
# (Phone sends every 4 hours — so normal traffic is ~6/day. This is very generous.)

set -euo pipefail

REGION="us-west-2"
FUNCTION_NAME="health-auto-export-webhook"

echo "════════════════════════════════════════"
echo "  SEC-4: API Gateway Rate Limiting"
echo "  Function: $FUNCTION_NAME"
echo "  Limit: 60 req/min steady / 100 burst"
echo "════════════════════════════════════════"
echo ""

# ── Step 1: Find the API Gateway ID associated with this Lambda ────────────
echo "1. Discovering API Gateway attached to $FUNCTION_NAME..."

LAMBDA_ARN=$(aws lambda get-function \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --query "Configuration.FunctionArn" \
    --output text --no-cli-pager)

echo "   Lambda ARN: $LAMBDA_ARN"
echo ""

ALL_APIS=$(aws apigateway get-rest-apis \
    --region "$REGION" \
    --query "items[].{id:id, name:name}" \
    --output json --no-cli-pager)

echo "   REST APIs found:"
echo "$ALL_APIS" | python3 -c "
import json, sys
apis = json.load(sys.stdin)
for a in apis:
    print(f\"     {a['id']}: {a['name']}\")
"
echo ""

# ── Step 2: Auto-detect API ID by scanning integrations ────────────────────
echo "2. Scanning APIs for Lambda integration..."

API_ID=""
STAGE_NAME=""

while IFS= read -r api_id; do
    resources=$(aws apigateway get-resources \
        --rest-api-id "$api_id" \
        --region "$REGION" \
        --query "items[].id" \
        --output text --no-cli-pager 2>/dev/null || echo "")

    for resource_id in $resources; do
        for method in POST GET PUT; do
            uri=$(aws apigateway get-integration \
                --rest-api-id "$api_id" \
                --resource-id "$resource_id" \
                --http-method "$method" \
                --region "$REGION" \
                --query "uri" \
                --output text --no-cli-pager 2>/dev/null || echo "")

            if echo "$uri" | grep -q "$FUNCTION_NAME"; then
                API_ID="$api_id"
                echo "   ✅ Found API: $api_id (resource $resource_id, method $method)"
                break 3
            fi
        done
    done
done < <(echo "$ALL_APIS" | python3 -c "
import json, sys
apis = json.load(sys.stdin)
for a in apis: print(a['id'])
")

if [ -z "$API_ID" ]; then
    echo "   ⚠️  Could not auto-detect API ID. Set manually and re-run:"
    echo "   export API_ID=<your-api-id> STAGE_NAME=prod"
    exit 1
fi

STAGE_NAME=$(aws apigateway get-stages \
    --rest-api-id "$API_ID" \
    --region "$REGION" \
    --query "item[0].stageName" \
    --output text --no-cli-pager)

echo "   Stage: $STAGE_NAME"
echo ""

# ── Step 3: Show current settings ──────────────────────────────────────────
echo "3. Current throttle settings on stage '$STAGE_NAME'..."
aws apigateway get-stage \
    --rest-api-id "$API_ID" \
    --stage-name "$STAGE_NAME" \
    --region "$REGION" \
    --query "methodSettings" \
    --output json --no-cli-pager || echo "   (no method-level settings)"
echo ""

# ── Step 4: Apply throttling ────────────────────────────────────────────────
echo "4. Applying rate limit: 60 req/min steady, 100 burst..."

aws apigateway update-stage \
    --rest-api-id "$API_ID" \
    --stage-name "$STAGE_NAME" \
    --region "$REGION" \
    --patch-operations \
        op=replace,path="//throttling/rateLimit",value="60" \
        op=replace,path="//throttling/burstLimit",value="100" \
    --no-cli-pager

echo ""
echo "5. Verifying..."
aws apigateway get-stage \
    --rest-api-id "$API_ID" \
    --stage-name "$STAGE_NAME" \
    --region "$REGION" \
    --query "defaultRouteSettings" \
    --output json --no-cli-pager 2>/dev/null || \
aws apigateway get-stage \
    --rest-api-id "$API_ID" \
    --stage-name "$STAGE_NAME" \
    --region "$REGION" \
    --output json --no-cli-pager | python3 -c "
import json, sys
s = json.load(sys.stdin)
print(f\"  throttlingRateLimit: {s.get('defaultRouteSettings', {}).get('throttlingRateLimit', 'N/A')}\")
print(f\"  throttlingBurstLimit: {s.get('defaultRouteSettings', {}).get('throttlingBurstLimit', 'N/A')}\")
" 2>/dev/null || echo "   (check console to verify)"

echo ""
echo "════════════════════════════════════════"
echo "  ✅ Done."
echo "  API: $API_ID  Stage: $STAGE_NAME"
echo "  Rate limit: 60 req/min (burst: 100)"
echo "  Normal traffic: ~6 req/day — safe."
echo "════════════════════════════════════════"
