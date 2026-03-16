#!/usr/bin/env bash
# point_route53_to_cloudfront.sh — Create Route 53 A + AAAA alias records
#                                   for averagejoematt.com → CloudFront
#
# Prerequisites:
#   - deploy_web_stack.sh has been run (CloudFront distribution exists)
#   - averagejoematt.com hosted zone exists in Route 53
#
# Usage:
#   CLOUDFRONT_DOMAIN=abc123.cloudfront.net bash deploy/point_route53_to_cloudfront.sh
#
#   Or let the script fetch it from CDK outputs automatically.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

REGION="us-east-1"  # LifePlatformWeb deploys to us-east-1 (CloudFront requirement)
ACCT="205930651321"
STACK_NAME="LifePlatformWeb"

# CloudFront hosted zone ID is always Z2FDTNDATAQYW2 for all distributions
CF_HOSTED_ZONE_ID="Z2FDTNDATAQYW2"

# ── Fetch CloudFront domain from CDK outputs if not provided ──────────────────
if [[ -z "${CLOUDFRONT_DOMAIN:-}" ]]; then
  echo "Fetching CloudFront domain from CDK stack outputs..."
  CLOUDFRONT_DOMAIN=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='AmjDistributionDomain'].OutputValue" \
    --output text)
  echo "CloudFront domain: $CLOUDFRONT_DOMAIN"
fi

[[ -z "$CLOUDFRONT_DOMAIN" ]] && { echo "❌ Could not find CloudFront domain. Set CLOUDFRONT_DOMAIN env var."; exit 1; }

# ── Find the averagejoematt.com hosted zone ───────────────────────────────────
echo "Finding Route 53 hosted zone for averagejoematt.com..."
HOSTED_ZONE_ID=$(aws route53 list-hosted-zones \
  --query "HostedZones[?Name=='averagejoematt.com.'].Id" \
  --output text | sed 's|/hostedzone/||')

[[ -z "$HOSTED_ZONE_ID" ]] && { echo "❌ No hosted zone found for averagejoematt.com in Route 53. Create it first."; exit 1; }
echo "Hosted zone ID: $HOSTED_ZONE_ID"

# ── Create A + AAAA alias records for root domain + www ──────────────────────
echo ""
echo "Creating A + AAAA alias records: averagejoematt.com → $CLOUDFRONT_DOMAIN"

aws route53 change-resource-record-sets \
  --hosted-zone-id "$HOSTED_ZONE_ID" \
  --change-batch "{
    \"Comment\": \"averagejoematt.com → CloudFront (v3.7.50)\",
    \"Changes\": [
      {
        \"Action\": \"UPSERT\",
        \"ResourceRecordSet\": {
          \"Name\": \"averagejoematt.com\",
          \"Type\": \"A\",
          \"AliasTarget\": {
            \"HostedZoneId\": \"$CF_HOSTED_ZONE_ID\",
            \"DNSName\": \"$CLOUDFRONT_DOMAIN\",
            \"EvaluateTargetHealth\": false
          }
        }
      },
      {
        \"Action\": \"UPSERT\",
        \"ResourceRecordSet\": {
          \"Name\": \"averagejoematt.com\",
          \"Type\": \"AAAA\",
          \"AliasTarget\": {
            \"HostedZoneId\": \"$CF_HOSTED_ZONE_ID\",
            \"DNSName\": \"$CLOUDFRONT_DOMAIN\",
            \"EvaluateTargetHealth\": false
          }
        }
      },
      {
        \"Action\": \"UPSERT\",
        \"ResourceRecordSet\": {
          \"Name\": \"www.averagejoematt.com\",
          \"Type\": \"A\",
          \"AliasTarget\": {
            \"HostedZoneId\": \"$CF_HOSTED_ZONE_ID\",
            \"DNSName\": \"$CLOUDFRONT_DOMAIN\",
            \"EvaluateTargetHealth\": false
          }
        }
      },
      {
        \"Action\": \"UPSERT\",
        \"ResourceRecordSet\": {
          \"Name\": \"www.averagejoematt.com\",
          \"Type\": \"AAAA\",
          \"AliasTarget\": {
            \"HostedZoneId\": \"$CF_HOSTED_ZONE_ID\",
            \"DNSName\": \"$CLOUDFRONT_DOMAIN\",
            \"EvaluateTargetHealth\": false
          }
        }
      }
    ]
  }"

echo ""
echo "✅ Route 53 records created. DNS propagation takes 1-5 min."
echo ""
echo "Test:"
echo "  dig averagejoematt.com A"
echo "  curl -I https://averagejoematt.com"
echo "  curl https://averagejoematt.com/api/status"
