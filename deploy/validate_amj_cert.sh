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

echo "Fetching all DNS validation records (handles multiple SANs)..."

# Get all domain validation options as JSON
VALIDATION_OPTIONS=$(aws acm describe-certificate \
  --certificate-arn "$CERT_ARN" \
  --region us-east-1 \
  --query "Certificate.DomainValidationOptions" \
  --output json)

# Count how many domains need validation
NUM_DOMAINS=$(echo "$VALIDATION_OPTIONS" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
echo "Found $NUM_DOMAINS domain(s) to validate."

# Build the Changes array for all domains
CHANGES="[]"
for i in $(seq 0 $((NUM_DOMAINS - 1))); do
  NAME=$(echo "$VALIDATION_OPTIONS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[$i]['ResourceRecord']['Name'])")
  VALUE=$(echo "$VALIDATION_OPTIONS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[$i]['ResourceRecord']['Value'])")
  DOMAIN=$(echo "$VALIDATION_OPTIONS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[$i]['DomainName'])")
  echo "  Adding CNAME for $DOMAIN: $NAME → $VALUE"

  aws route53 change-resource-record-sets \
    --hosted-zone-id "$HOSTED_ZONE_ID" \
    --change-batch "{
      \"Changes\": [{
        \"Action\": \"UPSERT\",
        \"ResourceRecordSet\": {
          \"Name\": \"$NAME\",
          \"Type\": \"CNAME\",
          \"TTL\": 300,
          \"ResourceRecords\": [{\"Value\": \"$VALUE\"}]
        }
      }]
    }" > /dev/null
done

echo ""
echo "✅ All $NUM_DOMAINS CNAME record(s) added. Waiting for certificate validation (~2 min)..."
echo "   Check status: aws acm describe-certificate --certificate-arn $CERT_ARN --region us-east-1 --query Certificate.Status --output text"
