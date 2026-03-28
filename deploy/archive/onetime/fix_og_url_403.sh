#!/bin/bash
# deploy/fix_og_url_403.sh
# WR-17: Re-apply Function URL public access permission on og-image Lambda.
# Fixes 403 on https://fj5u62xcm2bk2fwuiyvf3wzqqm0mwcmk.lambda-url.us-east-1.on.aws/
# Run: bash deploy/fix_og_url_403.sh

set -e
FUNCTION="life-platform-og-image"
REGION="us-east-1"
STMT="FunctionURLPublicAccess"
FURL="https://fj5u62xcm2bk2fwuiyvf3wzqqm0mwcmk.lambda-url.us-east-1.on.aws/"

echo "=== WR-17: Fix OG Lambda Function URL 403 ==="
echo "Function: $FUNCTION ($REGION)"

# Remove existing permission (ignore error if not found)
echo ""
echo "1. Removing existing permission statement (if any)..."
aws lambda remove-permission \
  --function-name "$FUNCTION" \
  --statement-id "$STMT" \
  --region "$REGION" 2>/dev/null && echo "   Removed." || echo "   Not found (safe to continue)."

# Re-add the permission
echo ""
echo "2. Adding public Function URL permission..."
aws lambda add-permission \
  --function-name "$FUNCTION" \
  --statement-id "$STMT" \
  --action lambda:InvokeFunctionUrl \
  --principal "*" \
  --function-url-auth-type NONE \
  --region "$REGION"

echo ""
echo "3. Sleeping 5s for propagation..."
sleep 5

# Test it
echo ""
echo "4. Smoke test..."
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$FURL")
CONTENT_TYPE=$(curl -sI "$FURL" | grep -i content-type | head -1)

echo "   HTTP status: $HTTP_STATUS"
echo "   Content-Type: $CONTENT_TYPE"

if [ "$HTTP_STATUS" = "200" ]; then
  echo ""
  echo "✅ WR-17 FIXED — Function URL returning 200."
  echo "   Dynamic OG card live at: $FURL"
  echo "   CloudFront path: https://averagejoematt.com/og"
else
  echo ""
  echo "⚠️  Still returning $HTTP_STATUS — check CloudWatch logs:"
  echo "   aws logs describe-log-groups --log-group-name-prefix '/aws/lambda/$FUNCTION' --region $REGION"
fi
