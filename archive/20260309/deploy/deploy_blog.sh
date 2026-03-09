#!/bin/bash
# Deploy blog infrastructure for The Measured Life
# Phase 2: S3 upload + CloudFront + Route 53
#
# Prerequisites:
#   - ACM cert for blog.averagejoematt.com (already requested)
#   - Route 53 hosted zone (already exists)
#   - S3 bucket with website hosting (already configured)
#
# Usage: bash deploy/deploy_blog.sh

set -euo pipefail

REGION="us-west-2"
BUCKET="matthew-life-platform"
CERT_ARN="arn:aws:acm:us-east-1:205930651321:certificate/952ddf18-d073-4d04-a0b7-42c7f5150dc2"
HOSTED_ZONE_ID="Z063312432BPXQH9PVXAI"
BLOG_DIR="blog"

echo "========================================="
echo "  Deploying: The Measured Life Blog"
echo "  blog.averagejoematt.com"
echo "========================================="

# ── Step 1: Upload blog files to S3 ──────────────────────────────
echo ""
echo "[1/4] Uploading blog files to S3..."
aws s3 cp "$BLOG_DIR/style.css" "s3://${BUCKET}/blog/style.css" \
    --content-type "text/css" \
    --cache-control "max-age=86400" \
    --region "$REGION"

aws s3 cp "$BLOG_DIR/index.html" "s3://${BUCKET}/blog/index.html" \
    --content-type "text/html" \
    --cache-control "max-age=300" \
    --region "$REGION"

aws s3 cp "$BLOG_DIR/week-00.html" "s3://${BUCKET}/blog/week-00.html" \
    --content-type "text/html" \
    --cache-control "max-age=3600" \
    --region "$REGION"

echo "  ✓ Files uploaded"
aws s3 ls "s3://${BUCKET}/blog/" --region "$REGION"

# ── Step 2: Wait for ACM cert ────────────────────────────────────
echo ""
echo "[2/4] Checking ACM certificate status..."
CERT_STATUS=$(aws acm describe-certificate \
    --certificate-arn "$CERT_ARN" \
    --region us-east-1 \
    --query "Certificate.Status" \
    --output text)

if [ "$CERT_STATUS" = "ISSUED" ]; then
    echo "  ✓ Certificate issued"
elif [ "$CERT_STATUS" = "PENDING_VALIDATION" ]; then
    echo "  ⏳ Certificate pending validation — waiting (up to 5 min)..."
    aws acm wait certificate-validated \
        --certificate-arn "$CERT_ARN" \
        --region us-east-1
    echo "  ✓ Certificate issued"
else
    echo "  ✗ Unexpected status: $CERT_STATUS"
    exit 1
fi

# ── Step 3: Create CloudFront distribution ────────────────────────
echo ""
echo "[3/4] Creating CloudFront distribution..."

# Check if distribution already exists for blog.averagejoematt.com
EXISTING_DIST=$(aws cloudfront list-distributions \
    --query "DistributionList.Items[?Aliases.Items[0]=='blog.averagejoematt.com'].Id" \
    --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_DIST" ] && [ "$EXISTING_DIST" != "None" ]; then
    echo "  Distribution already exists: $EXISTING_DIST"
    CF_DOMAIN=$(aws cloudfront get-distribution --id "$EXISTING_DIST" \
        --query "Distribution.DomainName" --output text)
else
    # Create distribution config
    cat > /tmp/blog-cf-config.json << 'CFEOF'
{
  "CallerReference": "blog-measured-life-2026-03-01",
  "Aliases": {
    "Quantity": 1,
    "Items": ["blog.averagejoematt.com"]
  },
  "DefaultRootObject": "index.html",
  "Origins": {
    "Quantity": 1,
    "Items": [
      {
        "Id": "S3BlogOrigin",
        "DomainName": "matthew-life-platform.s3-website-us-west-2.amazonaws.com",
        "OriginPath": "/blog",
        "CustomHeaders": { "Quantity": 0 },
        "CustomOriginConfig": {
          "HTTPPort": 80,
          "HTTPSPort": 443,
          "OriginProtocolPolicy": "http-only",
          "OriginSslProtocols": { "Quantity": 1, "Items": ["TLSv1.2"] },
          "OriginReadTimeout": 30,
          "OriginKeepaliveTimeout": 5
        },
        "ConnectionAttempts": 3,
        "ConnectionTimeout": 10,
        "OriginShield": { "Enabled": false }
      }
    ]
  },
  "DefaultCacheBehavior": {
    "TargetOriginId": "S3BlogOrigin",
    "ViewerProtocolPolicy": "redirect-to-https",
    "AllowedMethods": {
      "Quantity": 2,
      "Items": ["HEAD", "GET"],
      "CachedMethods": { "Quantity": 2, "Items": ["HEAD", "GET"] }
    },
    "Compress": true,
    "ForwardedValues": {
      "QueryString": false,
      "Cookies": { "Forward": "none" },
      "Headers": { "Quantity": 0 },
      "QueryStringCacheKeys": { "Quantity": 0 }
    },
    "MinTTL": 0,
    "DefaultTTL": 300,
    "MaxTTL": 3600,
    "SmoothStreaming": false,
    "LambdaFunctionAssociations": { "Quantity": 0 },
    "FunctionAssociations": { "Quantity": 0 },
    "FieldLevelEncryptionId": "",
    "TrustedSigners": { "Enabled": false, "Quantity": 0 },
    "TrustedKeyGroups": { "Enabled": false, "Quantity": 0 }
  },
  "CacheBehaviors": { "Quantity": 0 },
  "CustomErrorResponses": {
    "Quantity": 1,
    "Items": [
      {
        "ErrorCode": 404,
        "ResponsePagePath": "/index.html",
        "ResponseCode": "200",
        "ErrorCachingMinTTL": 60
      }
    ]
  },
  "Comment": "The Measured Life Blog — blog.averagejoematt.com",
  "Enabled": true,
  "ViewerCertificate": {
    "ACMCertificateArn": "arn:aws:acm:us-east-1:205930651321:certificate/952ddf18-d073-4d04-a0b7-42c7f5150dc2",
    "SSLSupportMethod": "sni-only",
    "MinimumProtocolVersion": "TLSv1.2_2021",
    "CertificateSource": "acm"
  },
  "Restrictions": {
    "GeoRestriction": { "RestrictionType": "none", "Quantity": 0 }
  },
  "PriceClass": "PriceClass_100",
  "HttpVersion": "http2and3",
  "IsIPV6Enabled": true
}
CFEOF

    DIST_RESULT=$(aws cloudfront create-distribution \
        --distribution-config file:///tmp/blog-cf-config.json \
        --query "Distribution.[Id,DomainName]" \
        --output text)

    DIST_ID=$(echo "$DIST_RESULT" | awk '{print $1}')
    CF_DOMAIN=$(echo "$DIST_RESULT" | awk '{print $2}')
    echo "  ✓ Distribution created: $DIST_ID"
fi

echo "  CloudFront domain: $CF_DOMAIN"

# ── Step 4: Create Route 53 DNS record ────────────────────────────
echo ""
echo "[4/4] Creating Route 53 DNS record..."

# Get the CloudFront hosted zone ID (always Z2FDTNDATAQYW2 for CloudFront)
aws route53 change-resource-record-sets \
    --hosted-zone-id "$HOSTED_ZONE_ID" \
    --change-batch "{
        \"Changes\": [{
            \"Action\": \"UPSERT\",
            \"ResourceRecordSet\": {
                \"Name\": \"blog.averagejoematt.com.\",
                \"Type\": \"A\",
                \"AliasTarget\": {
                    \"HostedZoneId\": \"Z2FDTNDATAQYW2\",
                    \"DNSName\": \"${CF_DOMAIN}\",
                    \"EvaluateTargetHealth\": false
                }
            }
        }]
    }"

echo "  ✓ DNS alias created: blog.averagejoematt.com → $CF_DOMAIN"

# ── Summary ───────────────────────────────────────────────────────
echo ""
echo "========================================="
echo "  ✓ Blog infrastructure deployed!"
echo "========================================="
echo ""
echo "  S3:          s3://${BUCKET}/blog/"
echo "  CloudFront:  $CF_DOMAIN"
echo "  URL:         https://blog.averagejoematt.com"
echo "  Prologue:    https://blog.averagejoematt.com/week-00.html"
echo ""
echo "  Note: CloudFront deployment takes ~5-10 min to propagate."
echo "  The blog is PUBLIC (no auth) — by design."
echo ""
echo "  The Lambda will publish new posts to the same S3 path"
echo "  every Wednesday at 7:00 AM PT."
echo ""
