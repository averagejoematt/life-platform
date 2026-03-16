#!/bin/bash
# deploy_v3756_subscriber_route.sh — Wire /api/subscribe CloudFront route
# Deploys: CDK LifePlatformWeb (new email-subscriber origin + /api/subscribe* behavior)
# Post-deploy: smoke test + CloudFront invalidation
#
# Usage: bash deploy/deploy_v3756_subscriber_route.sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== v3.7.56 — Wire /api/subscribe route ==="
echo ""

echo "[1/3] CDK deploy LifePlatformWeb..."
source cdk/.venv/bin/activate
cd cdk
npx cdk deploy LifePlatformWeb --require-approval never
cd "$ROOT"
echo "      ✓ LifePlatformWeb deployed"
echo ""

echo "[2/3] Post-CDK smoke..."
bash deploy/post_cdk_reconcile_smoke.sh
echo ""

echo "[3/3] CloudFront invalidation (E3S424OXQZ8NBE)..."
aws cloudfront create-invalidation \
  --distribution-id E3S424OXQZ8NBE \
  --paths "/api/subscribe*" \
  --query "Invalidation.{Id:Id,Status:Status}" \
  --output table
echo ""

echo "=== v3.7.56 deploy complete ==="
echo ""
echo "Test the subscribe flow:"
echo "  curl -X POST https://averagejoematt.com/api/subscribe \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"email\":\"your@email.com\"}'"
echo ""
echo "Expected: {\"status\": \"pending_confirmation\", \"message\": \"Check your inbox.\"}"
