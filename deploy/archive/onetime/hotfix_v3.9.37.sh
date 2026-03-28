#!/bin/bash
# hotfix_v3.9.37.sh — Fix S3 deletions + deploy subscriber Lambda fix
# Run from project root: bash deploy/hotfix_v3.9.37.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "═══════════════════════════════════════════════════════════"
echo "  HOTFIX: Restore deleted S3 files + deploy sub Lambda fix"
echo "═══════════════════════════════════════════════════════════"

# ── 1. Restore public_stats.json by invoking site-stats-refresh ──
echo ""
echo "▶ Restoring public_stats.json via site-stats-refresh Lambda..."
aws lambda invoke \
  --function-name site-stats-refresh \
  --invocation-type RequestResponse \
  --region us-west-2 \
  --no-cli-pager \
  /tmp/stats_refresh_out.json
echo "  Response:"
cat /tmp/stats_refresh_out.json
echo ""

# Verify it's back
echo "▶ Verifying public_stats.json exists in S3..."
aws s3 ls s3://matthew-life-platform/site/public_stats.json --region us-west-2 || {
  echo "  ⚠ public_stats.json still missing! Trying daily-brief Lambda..."
  aws lambda invoke \
    --function-name daily-brief \
    --invocation-type RequestResponse \
    --region us-west-2 \
    --no-cli-pager \
    /tmp/daily_brief_out.json
  echo "  Response:"
  cat /tmp/daily_brief_out.json
  echo ""
  sleep 5
  aws s3 ls s3://matthew-life-platform/site/public_stats.json --region us-west-2
}

# ── 2. Deploy subscriber Lambda fix (journal→chronicle in welcome email) ──
echo ""
echo "▶ Deploying email-subscriber Lambda fix..."
# email-subscriber is CDK-managed but we can update the code directly
# First find the region — check us-west-2 first, then us-east-1
SUBSCRIBER_REGION=""
if aws lambda get-function --function-name email-subscriber --region us-west-2 --no-cli-pager >/dev/null 2>&1; then
  SUBSCRIBER_REGION="us-west-2"
elif aws lambda get-function --function-name email-subscriber --region us-east-1 --no-cli-pager >/dev/null 2>&1; then
  SUBSCRIBER_REGION="us-east-1"
else
  echo "  ⚠ email-subscriber Lambda not found in us-west-2 or us-east-1!"
  echo "  Try: aws lambda list-functions --region us-west-2 --query 'Functions[?contains(FunctionName,\`subscriber\`)].FunctionName' --no-cli-pager"
  SUBSCRIBER_REGION=""
fi

if [ -n "$SUBSCRIBER_REGION" ]; then
  echo "  Found in ${SUBSCRIBER_REGION}"
  zip -j /tmp/email_subscriber_deploy.zip lambdas/email_subscriber_lambda.py
  aws lambda update-function-code \
    --function-name email-subscriber \
    --zip-file fileb:///tmp/email_subscriber_deploy.zip \
    --region "${SUBSCRIBER_REGION}" \
    --no-cli-pager
  echo "  ✓ Deployed email-subscriber to ${SUBSCRIBER_REGION}"
  rm -f /tmp/email_subscriber_deploy.zip
fi

# ── 3. Invalidate CloudFront again for the restored files ──
echo ""
echo "▶ Invalidating CloudFront..."
aws cloudfront create-invalidation \
  --distribution-id E3S424OXQZ8NBE \
  --paths "/public_stats.json" "/config/*" "/data/*" \
  --region us-east-1 \
  --no-cli-pager

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  ✅ Hotfix complete"
echo ""
echo "  Verify:"
echo "  curl -s https://averagejoematt.com/public_stats.json | head -5"
echo "═══════════════════════════════════════════════════════════"
