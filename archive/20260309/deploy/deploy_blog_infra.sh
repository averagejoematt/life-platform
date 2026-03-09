#!/bin/bash
# Deploy Blog Infrastructure — Phase 2
# Uploads prologue to S3, stores DDB record, creates CloudFront, configures DNS
#
# Prerequisites:
#   - ACM cert for blog.averagejoematt.com (already requested, validating)
#   - Route 53 hosted zone for averagejoematt.com (exists)
#   - S3 bucket matthew-life-platform with website hosting enabled (exists)
#
# Usage: bash deploy/deploy_blog_infra.sh

set -euo pipefail

REGION="us-west-2"
BUCKET="matthew-life-platform"
TABLE="life-platform"
HOSTED_ZONE_ID="Z063312432BPXQH9PVXAI"
CERT_ARN="arn:aws:acm:us-east-1:205930651321:certificate/952ddf18-d073-4d04-a0b7-42c7f5150dc2"
BLOG_DIR="blog"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo "========================================="
echo "  Deploying: Blog Infrastructure"
echo "  blog.averagejoematt.com"
echo "========================================="

# ── Step 1: Upload blog files to S3 ──────────────────────────────
echo ""
echo "[1/5] Uploading blog files to S3..."

aws s3 cp "$BLOG_DIR/style.css" "s3://$BUCKET/blog/style.css" \
    --content-type "text/css" \
    --cache-control "max-age=86400" \
    --region "$REGION"
echo "  ✓ style.css"

aws s3 cp "$BLOG_DIR/week-00.html" "s3://$BUCKET/blog/week-00.html" \
    --content-type "text/html" \
    --cache-control "max-age=3600" \
    --region "$REGION"
echo "  ✓ week-00.html"

aws s3 cp "$BLOG_DIR/index.html" "s3://$BUCKET/blog/index.html" \
    --content-type "text/html" \
    --cache-control "max-age=300" \
    --region "$REGION"
echo "  ✓ index.html"

aws s3 cp "$BLOG_DIR/about.html" "s3://$BUCKET/blog/about.html" \
    --content-type "text/html" \
    --cache-control "max-age=3600" \
    --region "$REGION"
echo "  ✓ about.html"

# Audio was already uploaded via Polly → S3 (blog/audio/elena-intro.mp3)
# Verify it exists:
aws s3 ls "s3://$BUCKET/blog/audio/elena-intro.mp3" --region "$REGION" && echo "  ✓ audio/elena-intro.mp3 (already exists)" || echo "  ⚠ Audio file missing — generate via Polly"

# Verify
echo "  Verifying..."
aws s3 ls "s3://$BUCKET/blog/" --region "$REGION"
echo "  ✓ All blog files uploaded"

# ── Step 2: Store prologue in DynamoDB ────────────────────────────
echo ""
echo "[2/5] Storing prologue in DynamoDB..."

CONTENT_MD=$(cat "$BLOG_DIR/week-00.html" | python3 -c "
import sys, json
# Just store a reference — full content is in S3
print(json.dumps(sys.stdin.read()))
" 2>/dev/null || echo '""')

aws dynamodb put-item \
    --table-name "$TABLE" \
    --item '{
        "pk": {"S": "USER#matthew#SOURCE#chronicle"},
        "sk": {"S": "DATE#2026-02-28"},
        "date": {"S": "2026-02-28"},
        "source": {"S": "chronicle"},
        "week_number": {"N": "0"},
        "title": {"S": "Before the Numbers"},
        "subtitle": {"S": "Prologue"},
        "stats_line": {"S": "Prologue | February 2026 | Seattle, WA"},
        "content_markdown": {"S": "See S3: blog/week-00.html"},
        "content_html": {"S": "See S3: blog/week-00.html"},
        "word_count": {"N": "1850"},
        "has_board_interview": {"BOOL": false},
        "series_title": {"S": "The Measured Life"},
        "author": {"S": "Elena Voss"},
        "generated_at": {"S": "2026-02-28T18:30:00Z"},
        "themes": {"L": [{"S": "introduction"}, {"S": "technology"}, {"S": "transformation"}, {"S": "quantified-self"}]},
        "is_prologue": {"BOOL": true}
    }' \
    --region "$REGION"

echo "  ✓ Prologue stored (PK=USER#matthew#SOURCE#chronicle, SK=DATE#2026-02-28)"

# ── Step 3: Wait for ACM certificate ─────────────────────────────
echo ""
echo "[3/5] Checking ACM certificate status..."

CERT_STATUS=$(aws acm describe-certificate \
    --certificate-arn "$CERT_ARN" \
    --region us-east-1 \
    --query 'Certificate.Status' \
    --output text)

if [ "$CERT_STATUS" != "ISSUED" ]; then
    echo "  Certificate status: $CERT_STATUS"
    echo "  Waiting for validation (this can take 5-30 minutes)..."
    aws acm wait certificate-validated \
        --certificate-arn "$CERT_ARN" \
        --region us-east-1
    echo "  ✓ Certificate validated!"
else
    echo "  ✓ Certificate already issued"
fi

# ── Step 4: Create CloudFront distribution ────────────────────────
echo ""
echo "[4/5] Creating CloudFront distribution..."

# Check if distribution already exists for blog.averagejoematt.com
EXISTING_DIST=$(aws cloudfront list-distributions \
    --query "DistributionList.Items[?Aliases.Items[0]=='blog.averagejoematt.com'].Id" \
    --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_DIST" ] && [ "$EXISTING_DIST" != "None" ]; then
    echo "  Distribution already exists: $EXISTING_DIST"
    CF_DOMAIN=$(aws cloudfront get-distribution \
        --id "$EXISTING_DIST" \
        --query 'Distribution.DomainName' \
        --output text)
else
    # Create distribution config
    cat > /tmp/cf-blog-config.json << CFEOF
{
    "CallerReference": "blog-measured-life-$(date +%s)",
    "Comment": "The Measured Life Blog — blog.averagejoematt.com",
    "Enabled": true,
    "Aliases": {
        "Quantity": 1,
        "Items": ["blog.averagejoematt.com"]
    },
    "Origins": {
        "Quantity": 1,
        "Items": [{
            "Id": "S3BlogOrigin",
            "DomainName": "$BUCKET.s3-website-$REGION.amazonaws.com",
            "OriginPath": "/blog",
            "CustomHeaders": {"Quantity": 0},
            "CustomOriginConfig": {
                "HTTPPort": 80,
                "HTTPSPort": 443,
                "OriginProtocolPolicy": "http-only",
                "OriginSslProtocols": {"Quantity": 1, "Items": ["TLSv1.2"]},
                "OriginReadTimeout": 30,
                "OriginKeepaliveTimeout": 5
            },
            "ConnectionAttempts": 3,
            "ConnectionTimeout": 10
        }]
    },
    "DefaultCacheBehavior": {
        "TargetOriginId": "S3BlogOrigin",
        "ViewerProtocolPolicy": "redirect-to-https",
        "AllowedMethods": {
            "Quantity": 2,
            "Items": ["HEAD", "GET"],
            "CachedMethods": {"Quantity": 2, "Items": ["HEAD", "GET"]}
        },
        "Compress": true,
        "ForwardedValues": {
            "QueryString": false,
            "Cookies": {"Forward": "none"},
            "Headers": {"Quantity": 0},
            "QueryStringCacheKeys": {"Quantity": 0}
        },
        "MinTTL": 0,
        "DefaultTTL": 300,
        "MaxTTL": 3600
    },
    "DefaultRootObject": "index.html",
    "PriceClass": "PriceClass_100",
    "ViewerCertificate": {
        "ACMCertificateArn": "$CERT_ARN",
        "SSLSupportMethod": "sni-only",
        "MinimumProtocolVersion": "TLSv1.2_2021"
    },
    "HttpVersion": "http2and3",
    "IsIPV6Enabled": true
}
CFEOF

    RESULT=$(aws cloudfront create-distribution \
        --distribution-config file:///tmp/cf-blog-config.json \
        --output json)

    DIST_ID=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['Distribution']['Id'])")
    CF_DOMAIN=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['Distribution']['DomainName'])")

    echo "  ✓ Distribution created: $DIST_ID"
    rm -f /tmp/cf-blog-config.json
fi

echo "  CloudFront domain: $CF_DOMAIN"

# ── Step 5: Configure DNS ─────────────────────────────────────────
echo ""
echo "[5/5] Configuring DNS..."

aws route53 change-resource-record-sets \
    --hosted-zone-id "$HOSTED_ZONE_ID" \
    --change-batch "{
        \"Changes\": [{
            \"Action\": \"UPSERT\",
            \"ResourceRecordSet\": {
                \"Name\": \"blog.averagejoematt.com\",
                \"Type\": \"A\",
                \"AliasTarget\": {
                    \"HostedZoneId\": \"Z2FDTNDATAQYW2\",
                    \"DNSName\": \"$CF_DOMAIN\",
                    \"EvaluateTargetHealth\": false
                }
            }
        }]
    }" \
    --no-cli-pager

echo "  ✓ DNS A record: blog.averagejoematt.com → $CF_DOMAIN"

# ── Summary ───────────────────────────────────────────────────────
echo ""
echo "========================================="
echo "  ✓ Blog infrastructure deployed!"
echo "========================================="
echo ""
echo "  S3:          s3://$BUCKET/blog/"
echo "  CloudFront:  $CF_DOMAIN"
echo "  URL:         https://blog.averagejoematt.com"
echo "  DynamoDB:    chronicle partition (Week 0 prologue stored)"
echo ""
echo "  NOTE: CloudFront takes 5-15 minutes to deploy fully."
echo "  The blog will be available at https://blog.averagejoematt.com"
echo "  once propagation completes."
echo ""
echo "  Key difference from dash.averagejoematt.com:"
echo "  - No authentication (blog is PUBLIC)"
echo "  - No Lambda@Edge viewer-request function"
echo "  - Clean editorial design optimized for reading"
echo ""
echo "  Files uploaded:"
echo "    blog/index.html   — Landing page with series intro"
echo "    blog/week-00.html — Prologue: \"Before the Numbers\""  
echo "    blog/style.css    — Editorial stylesheet"
echo ""
