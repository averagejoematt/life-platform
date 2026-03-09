#!/bin/bash
# deploy_review_group_b.sh — Expert Review Group B: API Gateway throttling
# Finding: F3.5 — Add rate limiting to health-auto-export-api
#
# NOTE: HTTP APIs (v2) don't support usage plans/API keys.
# Using stage-level route throttling instead.
# Health Auto Export sends ~96 req/day (every 15 min).
# Setting: 10 req/sec rate, 20 burst — blocks abuse, allows normal operation.

set -euo pipefail
REGION="us-west-2"
API_ID="a76xwxt2wa"

echo "=========================================="
echo "Group B: API Gateway Route Throttling"
echo "=========================================="

echo "── Setting throttle on POST /ingest: rate=10/s, burst=20 ──"
aws apigatewayv2 update-stage \
  --api-id "$API_ID" \
  --stage-name '$default' \
  --route-settings '{"POST /ingest": {"ThrottlingRateLimit": 10, "ThrottlingBurstLimit": 20}}' \
  --region $REGION \
  --query 'StageName' --output text
echo "✅ Done"

echo ""
echo "=========================================="
echo "Group B Complete"
echo "=========================================="
echo "POST /ingest: 10 req/sec rate limit, 20 burst"
echo "Normal operation (~96 req/day) unaffected"
echo "Abuse/scanning blocked at >10 req/sec"
echo ""
echo "Next: Run Group C (daily brief hardening)"
