#!/bin/bash
# Dashboard Phase 2 — Infrastructure Deploy
# ACM certificate + CloudFront distribution for dash.averagejoematt.com
# Run AFTER deploy_dashboard_phase2_code.sh
set -euo pipefail

DOMAIN="dash.averagejoematt.com"
BUCKET="matthew-life-platform"
REGION="us-west-2"
CERT_REGION="us-east-1"  # ACM certs for CloudFront MUST be us-east-1
ORIGIN="$BUCKET.s3-website-$REGION.amazonaws.com"

echo "╔═══════════════════════════════════════════════════════╗"
echo "║  Dashboard Phase 2 — Infrastructure (CloudFront)     ║"
echo "║  Domain: $DOMAIN                         ║"
echo "╚═══════════════════════════════════════════════════════╝"

# ── Phase 1: ACM Certificate ──
echo ""
echo "═══ Phase 1: Request ACM Certificate ═══"

# Check if cert already exists
EXISTING_CERT=$(aws acm list-certificates --region "$CERT_REGION" \
  --query "CertificateSummaryList[?DomainName=='$DOMAIN'].CertificateArn" \
  --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_CERT" ] && [ "$EXISTING_CERT" != "None" ]; then
  CERT_ARN="$EXISTING_CERT"
  echo "  Certificate already exists: $CERT_ARN"
else
  echo "  Requesting certificate for $DOMAIN..."
  CERT_ARN=$(aws acm request-certificate \
    --domain-name "$DOMAIN" \
    --validation-method DNS \
    --region "$CERT_REGION" \
    --query 'CertificateArn' \
    --output text)
  echo "  Certificate ARN: $CERT_ARN"
  echo "  Waiting 5s for DNS validation records..."
  sleep 5
fi

# Get validation CNAME
echo ""
echo "  Fetching DNS validation record..."
VALIDATION=$(aws acm describe-certificate \
  --certificate-arn "$CERT_ARN" \
  --region "$CERT_REGION" \
  --query 'Certificate.DomainValidationOptions[0].ResourceRecord')

VAL_NAME=$(echo "$VALIDATION" | python3 -c "import sys,json; print(json.load(sys.stdin)['Name'])")
VAL_VALUE=$(echo "$VALIDATION" | python3 -c "import sys,json; print(json.load(sys.stdin)['Value'])")
CERT_STATUS=$(aws acm describe-certificate \
  --certificate-arn "$CERT_ARN" \
  --region "$CERT_REGION" \
  --query 'Certificate.Status' \
  --output text)

echo ""
echo "  ┌─────────────────────────────────────────────────────┐"
echo "  │  ADD THIS DNS RECORD AT YOUR REGISTRAR:             │"
echo "  │                                                     │"
echo "  │  Type:  CNAME                                       │"
echo "  │  Name:  $VAL_NAME"
echo "  │  Value: $VAL_VALUE"
echo "  │                                                     │"
echo "  │  Current status: $CERT_STATUS"
echo "  └─────────────────────────────────────────────────────┘"

if [ "$CERT_STATUS" != "ISSUED" ]; then
  echo ""
  echo "  ⏳ Certificate is not yet validated."
  echo "  Add the CNAME record above, then re-run this script."
  echo "  (DNS propagation typically takes 1-30 minutes)"
  echo ""
  echo "  To check status:"
  echo "    aws acm describe-certificate --certificate-arn $CERT_ARN --region $CERT_REGION --query 'Certificate.Status' --output text"
  echo ""
  read -p "  Press Enter if you've added the DNS record and want to wait, or Ctrl+C to exit..."

  echo "  Waiting for certificate validation (checking every 15s, up to 10 min)..."
  MAX_WAIT=40
  COUNT=0
  while [ "$COUNT" -lt "$MAX_WAIT" ]; do
    CERT_STATUS=$(aws acm describe-certificate \
      --certificate-arn "$CERT_ARN" \
      --region "$CERT_REGION" \
      --query 'Certificate.Status' \
      --output text)
    if [ "$CERT_STATUS" = "ISSUED" ]; then
      echo "  ✅ Certificate validated!"
      break
    fi
    COUNT=$((COUNT + 1))
    echo "  ... status: $CERT_STATUS (attempt $COUNT/$MAX_WAIT)"
    sleep 15
  done

  if [ "$CERT_STATUS" != "ISSUED" ]; then
    echo "  ❌ Certificate not validated after 10 minutes."
    echo "  Verify the DNS record is correct and re-run this script."
    exit 1
  fi
fi

echo ""
echo "  ✅ ACM Certificate: ISSUED"

# ── Phase 2: CloudFront Distribution ──
echo ""
echo "═══ Phase 2: Create CloudFront Distribution ═══"

# Check if distribution already exists for this domain
EXISTING_DIST=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?Aliases.Items[0]=='$DOMAIN'].Id" \
  --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_DIST" ] && [ "$EXISTING_DIST" != "None" ]; then
  echo "  Distribution already exists: $EXISTING_DIST"
  CF_DOMAIN=$(aws cloudfront get-distribution --id "$EXISTING_DIST" \
    --query 'Distribution.DomainName' --output text)
else
  echo "  Creating CloudFront distribution..."

  # Write config to temp file
  cat > /tmp/cf-dist-config.json << CFEOF
{
  "CallerReference": "life-platform-dashboard-$(date +%s)",
  "Comment": "Life Platform Dashboard — dash.averagejoematt.com",
  "Enabled": true,
  "DefaultRootObject": "",
  "Aliases": {
    "Quantity": 1,
    "Items": ["$DOMAIN"]
  },
  "Origins": {
    "Quantity": 1,
    "Items": [
      {
        "Id": "S3WebsiteOrigin",
        "DomainName": "$ORIGIN",
        "OriginPath": "/dashboard",
        "CustomOriginConfig": {
          "HTTPPort": 80,
          "HTTPSPort": 443,
          "OriginProtocolPolicy": "http-only",
          "OriginSslProtocols": { "Quantity": 1, "Items": ["TLSv1.2"] }
        }
      }
    ]
  },
  "DefaultCacheBehavior": {
    "TargetOriginId": "S3WebsiteOrigin",
    "ViewerProtocolPolicy": "redirect-to-https",
    "AllowedMethods": { "Quantity": 2, "Items": ["GET", "HEAD"], "CachedMethods": { "Quantity": 2, "Items": ["GET", "HEAD"] } },
    "ForwardedValues": {
      "QueryString": false,
      "Cookies": { "Forward": "none" }
    },
    "MinTTL": 0,
    "DefaultTTL": 300,
    "MaxTTL": 3600,
    "Compress": true
  },
  "CustomErrorResponses": {
    "Quantity": 0
  },
  "ViewerCertificate": {
    "ACMCertificateArn": "$CERT_ARN",
    "SSLSupportMethod": "sni-only",
    "MinimumProtocolVersion": "TLSv1.2_2021",
    "CloudFrontDefaultCertificate": false
  },
  "PriceClass": "PriceClass_100",
  "HttpVersion": "http2and3"
}
CFEOF

  DIST_RESULT=$(aws cloudfront create-distribution \
    --distribution-config file:///tmp/cf-dist-config.json \
    --query 'Distribution.{Id:Id,Domain:DomainName,Status:Status}' \
    --output json)

  EXISTING_DIST=$(echo "$DIST_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['Id'])")
  CF_DOMAIN=$(echo "$DIST_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['Domain'])")
  CF_STATUS=$(echo "$DIST_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['Status'])")

  echo "  Distribution ID: $EXISTING_DIST"
  echo "  CloudFront domain: $CF_DOMAIN"
  echo "  Status: $CF_STATUS (takes 5-15 min to fully deploy)"
  rm /tmp/cf-dist-config.json
fi

echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║  ✅ Infrastructure deploy complete!                          ║"
echo "║                                                              ║"
echo "║  CloudFront: https://$CF_DOMAIN/dashboard/"
echo "║                                                              ║"
echo "║  ┌─────────────────────────────────────────────────────────┐ ║"
echo "║  │  ADD THIS DNS RECORD AT YOUR REGISTRAR:                 │ ║"
echo "║  │                                                         │ ║"
echo "║  │  Type:  CNAME                                           │ ║"
echo "║  │  Name:  dash                                            │ ║"
echo "║  │  Value: $CF_DOMAIN"
echo "║  │                                                         │ ║"
echo "║  │  (For averagejoematt.com)                               │ ║"
echo "║  └─────────────────────────────────────────────────────────┘ ║"
echo "║                                                              ║"
echo "║  After adding the CNAME:                                     ║"
echo "║    https://dash.averagejoematt.com/dashboard/                ║"
echo "║                                                              ║"
echo "║  Cost: ~\$0/mo (CloudFront free tier: 1TB/10M requests)      ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
