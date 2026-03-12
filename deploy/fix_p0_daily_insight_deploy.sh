#!/bin/bash
# Deploy fixed daily-insight-compute Lambda (PlatformLogger multi-arg bug fix)
# Run from life-platform project root
# 2026-03-12 v3.7.4

set -euo pipefail
echo "=== Deploying daily-insight-compute ==="
bash deploy/deploy_lambda.sh daily-insight-compute lambdas/daily_insight_compute_lambda.py
echo "✅ daily-insight-compute deployed"
echo ""
echo "Waiting 10s for propagation..."
sleep 10
echo ""
echo "=== Smoke test — invoke with force=true for yesterday ==="
YESTERDAY=$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d yesterday +%Y-%m-%d)
aws lambda invoke \
  --function-name daily-insight-compute \
  --cli-binary-format raw-in-base64-out \
  --payload "{\"force\": true, \"date\": \"$YESTERDAY\"}" \
  --region us-west-2 \
  /tmp/daily_insight_smoke.json
echo "Response:"
cat /tmp/daily_insight_smoke.json
echo ""
echo "✅ Smoke test complete — check for errors above"
