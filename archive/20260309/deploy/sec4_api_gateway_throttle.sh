#!/usr/bin/env bash
# SEC-4: Add throttling to Health Auto Export API Gateway (HTTP API v2)
# Sets 100 req/min (≈1.67 req/s) on the $default stage default route
# Run once; safe to re-run.

set -euo pipefail

REGION="us-west-2"
API_NAME="health-auto-export-api"

echo "=== SEC-4: Applying rate limiting to $API_NAME ==="

# Look up the API ID by name
API_ID=$(aws apigatewayv2 get-apis --region "$REGION" \
  --query "Items[?Name=='$API_NAME'].ApiId" \
  --output text)

if [ -z "$API_ID" ] || [ "$API_ID" = "None" ]; then
  echo "ERROR: Could not find API Gateway named '$API_NAME' in $REGION"
  echo "Run: aws apigatewayv2 get-apis --region $REGION --query 'Items[].{Name:Name,Id:ApiId}'"
  exit 1
fi

echo "Found API: $API_ID"

# Apply throttling to the $default stage
# throttlingBurstLimit: max concurrent requests
# throttlingRateLimit: sustained req/sec (100/min = 1.67/sec, so use 2 for burst headroom)
aws apigatewayv2 update-stage \
  --api-id "$API_ID" \
  --stage-name '$default' \
  --region "$REGION" \
  --default-route-settings '{
    "ThrottlingBurstLimit": 10,
    "ThrottlingRateLimit": 1.67
  }'

echo "✅ Throttling applied: 1.67 req/s sustained, burst 10"
echo ""
echo "Verify with:"
echo "  aws apigatewayv2 get-stage --api-id $API_ID --stage-name '\$default' --region $REGION \\"
echo "    --query 'DefaultRouteSettings'"
