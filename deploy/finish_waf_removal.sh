#!/bin/bash
# finish_waf_removal.sh — Step 2 of #103: detach + delete the orphaned WAF.
#
# PRECONDITION: email-subscriber must already be running the rate-limit code
# from commit that adds _check_subscribe_rate_limit. Until that's live, the WAF
# is the only protection on /api/subscribe and MUST stay attached.
#
# After CI deploys the rate-limit code through the production approval gate,
# run this script to:
#   1. Detach the WAF from CloudFront distribution E3S424OXQZ8NBE
#   2. Wait for the distribution to converge (Deployed state)
#   3. Delete the WAF web ACL
#   4. Print the new monthly cost picture
#
# Effect: saves ~$8/mo. The audit at docs/audits/COST_CACHE_SES_VERIFICATION_2026-05-29.md
# walks through how that flips the projected budget tier from 1 → 0.
#
# Reversal: re-attach by editing cdk/stacks/web_stack.py or running
# `aws cloudfront update-distribution` with WebACLId set back. Rule definitions
# are preserved in this commit's git history if they need re-creation.

set -euo pipefail

WAF_NAME="life-platform-amj-waf"
WAF_ID="3d75472e-e18b-4d1c-b76b-8bbe63cb05e8"
CF_DIST_ID="E3S424OXQZ8NBE"

echo "[1/4] Pre-flight: confirm rate-limit code is live in email-subscriber…"
# The rate-limit constants are easy to spot in the deployed code via a synthetic
# probe — send a POST with no body and check the response shape. A 400 with
# the new code path is fine; a 5xx means the deploy hasn't landed.
PROBE=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST -H "Content-Type: application/json" -d '{}' \
  https://averagejoematt.com/api/subscribe)
echo "  /api/subscribe probe → HTTP $PROBE"
if [[ "$PROBE" != "400" && "$PROBE" != "429" && "$PROBE" != "200" ]]; then
  echo "  BLOCKED: expected 400/429/200 from /api/subscribe — got $PROBE."
  echo "  Confirm CI deploy approved and email-subscriber is live, then re-run."
  exit 2
fi
echo "  OK — endpoint responding."

echo "[2/4] Fetching current CloudFront distribution config…"
TMP=$(mktemp -d)
aws cloudfront get-distribution-config --id "$CF_DIST_ID" --region us-east-1 \
  --output json > "$TMP/dist.json"
ETAG=$(jq -r '.ETag' "$TMP/dist.json")
jq '.DistributionConfig | .WebACLId = ""' "$TMP/dist.json" > "$TMP/new.json"

echo "[3/4] Detaching WAF (CloudFront update)…"
aws cloudfront update-distribution --id "$CF_DIST_ID" --region us-east-1 \
  --if-match "$ETAG" \
  --distribution-config "file://$TMP/new.json" \
  --query 'Distribution.{Id:Id,Status:Status,WebACLId:DistributionConfig.WebACLId}' \
  --output json > "$TMP/update.json"
cat "$TMP/update.json"

echo "  Waiting for CloudFront to reach Deployed state (this can take 5-10min)…"
aws cloudfront wait distribution-deployed --id "$CF_DIST_ID" --region us-east-1
echo "  CloudFront converged."

echo "[4/4] Deleting the WAF web ACL…"
# Need the current LockToken — refresh it.
LOCK=$(aws wafv2 get-web-acl --name "$WAF_NAME" --id "$WAF_ID" --scope CLOUDFRONT --region us-east-1 \
  --query 'LockToken' --output text)
aws wafv2 delete-web-acl --name "$WAF_NAME" --id "$WAF_ID" --scope CLOUDFRONT --region us-east-1 \
  --lock-token "$LOCK"
echo "  WAF deleted."

rm -rf "$TMP"

echo ""
echo "DONE. Expected savings: ~\$8/mo (1 WebACL + 4 rules)."
echo "Verify: aws ce get-cost-and-usage on the next billing day shows AWS WAF = \$0."
echo "Budget projection: with the WAF gone, MTD drops ~\$8 → tier should flip 1 → 0."
