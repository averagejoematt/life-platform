#!/usr/bin/env bash
# validate_amj_cert.sh — Add DNS validation CNAME records to Route 53
#
# Run this after request_amj_cert.sh once you have the certificate ARN
# and know your Route 53 hosted zone ID.
#
# Usage:
#   CERT_ARN=arn:aws:acm:us-east-1:... HOSTED_ZONE_ID=Z... bash deploy/validate_amj_cert.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

CERT_ARN="${CERT_ARN:?Set CERT_ARN env var}"
HOSTED_ZONE_ID="${HOSTED_ZONE_ID:?Set HOSTED_ZONE_ID env var}"

echo "Fetching DNS validation records for $CERT_ARN..."

CNAME_NAME=$(aws acm describe-certificate \
  --certificate-arn "$CERT_ARN" \
  --region us-east-1 \
  --query "Certificate.DomainValidationOptions[0].ResourceRecord.Name" \
  --output text)

CNAME_VALUE=$(aws acm describe-certificate \
  --certificate-arn "$CERT_ARN" \
  --region us-east-1 \
  --query "Certificate.DomainValidationOptions[0].ResourceRecord.Value" \
  --output text)

echo "CNAME: $CNAME_NAME → $CNAME_VALUE"
echo "Adding to Route 53 hosted zone $HOSTED_ZONE_ID..."

aws route53 change-resource-record-sets \
  --hosted-zone-id "$HOSTED_ZONE_ID" \
  --change-batch "{
    \"Changes\": [{
      \"Action\": \"UPSERT\",
      \"ResourceRecordSet\": {
        \"Name\": \"$CNAME_NAME\",
        \"Type\": \"CNAME\",
        \"TTL\": 300,
        \"ResourceRecords\": [{\"Value\": \"$CNAME_VALUE\"}]
      }
    }]
  }"

echo ""
echo "✅ CNAME record added. Waiting for certificate validation (~2 min)..."
echo "   Check status: aws acm describe-certificate --certificate-arn $CERT_ARN --region us-east-1 --query Certificate.Status --output text"
