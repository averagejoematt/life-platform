#!/bin/bash
# ══════════════════════════════════════════════════════════════════════
# Deploy Buddy Accountability Page — buddy.averagejoematt.com
# v2.53.0
#
# Phase 1: Upload HTML + seed data.json to S3
# Phase 2: ACM certificate
# Phase 3: CloudFront distribution  
# Phase 4: Lambda@Edge auth (separate from dashboard)
# Phase 5: Associate auth with CloudFront + enable POST
# Phase 6: Route 53 DNS
# Phase 7: Update Daily Brief Lambda with write_buddy_json
#
# Usage:
#   chmod +x deploy/deploy_buddy_page.sh
#   deploy/deploy_buddy_page.sh
# ══════════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BUDDY_DIR="$PROJECT_DIR/lambdas/buddy"

DOMAIN="buddy.averagejoematt.com"
BUCKET="matthew-life-platform"
REGION="us-west-2"
CERT_REGION="us-east-1"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Auth config (separate from dashboard)
BUDDY_SECRET_ID="life-platform/buddy-auth"
BUDDY_FUNCTION_NAME="life-platform-buddy-auth"
BUDDY_ROLE_NAME="life-platform-cf-auth-edge"  # Reuse existing role

echo "╔═══════════════════════════════════════════════════════╗"
echo "║  Buddy Accountability Page Deploy                    ║"
echo "║  Domain: $DOMAIN                       ║"
echo "║  Version: v2.53.0                                    ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""

# ══════════════════════════════════════════════════════════════
# Phase 1: Upload HTML + Seed Data
# ══════════════════════════════════════════════════════════════
echo "═══ Phase 1: Upload buddy page to S3 ═══"

if [ -f "$BUDDY_DIR/index.html" ]; then
    echo "  Uploading index.html..."
    aws s3 cp "$BUDDY_DIR/index.html" "s3://$BUCKET/buddy/index.html" \
        --content-type "text/html" --cache-control "max-age=300"
    echo "  ✅ index.html uploaded"
else
    echo "  ❌ $BUDDY_DIR/index.html not found!"
    exit 1
fi

# Seed data.json if it doesn't exist
if ! aws s3 ls "s3://$BUCKET/buddy/data.json" >/dev/null 2>&1; then
    echo "  Seeding initial data.json..."
    cat > /tmp/buddy-seed.json << 'SEEDEOF'
{
  "generated_at": "2026-03-01T00:00:00Z",
  "date": "2026-02-28",
  "beacon": "green",
  "beacon_label": "Matt's doing his thing",
  "beacon_summary": "Page just went live. Real data will appear after tomorrow's morning brief.",
  "prompt_for_tom": "No action needed yet — this page just launched. Check back tomorrow for live data.",
  "status_lines": [
    {"area": "Food Logging", "status": "green", "text": "Tracking active"},
    {"area": "Exercise", "status": "green", "text": "Data loading..."},
    {"area": "Routine", "status": "green", "text": "Data loading..."},
    {"area": "Weight", "status": "green", "text": "Data loading..."}
  ],
  "activity_highlights": [],
  "food_snapshot": "Real nutrition data will appear after tomorrow's morning brief.",
  "journey": {"days": 0, "lost_lbs": 0, "pct_complete": 0, "goal_lbs": 185},
  "last_updated_friendly": "Just launched"
}
SEEDEOF
    aws s3 cp /tmp/buddy-seed.json "s3://$BUCKET/buddy/data.json" \
        --content-type "application/json" --cache-control "max-age=300"
    rm /tmp/buddy-seed.json
    echo "  ✅ Seed data.json uploaded"
else
    echo "  data.json already exists, skipping seed"
fi

echo ""

# ══════════════════════════════════════════════════════════════
# Phase 2: ACM Certificate
# ══════════════════════════════════════════════════════════════
echo "═══ Phase 2: ACM Certificate ═══"

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
    sleep 5
fi

# Get validation record
VALIDATION=$(aws acm describe-certificate \
    --certificate-arn "$CERT_ARN" \
    --region "$CERT_REGION" \
    --query 'Certificate.DomainValidationOptions[0].ResourceRecord')

VAL_NAME=$(echo "$VALIDATION" | python3 -c "import sys,json; print(json.load(sys.stdin)['Name'])")
VAL_VALUE=$(echo "$VALIDATION" | python3 -c "import sys,json; print(json.load(sys.stdin)['Value'])")
CERT_STATUS=$(aws acm describe-certificate \
    --certificate-arn "$CERT_ARN" \
    --region "$CERT_REGION" \
    --query 'Certificate.Status' --output text)

if [ "$CERT_STATUS" != "ISSUED" ]; then
    echo ""
    echo "  ┌───────────────────────────────────────────────────────┐"
    echo "  │  ADD THIS DNS RECORD (CNAME):                         │"
    echo "  │  Name:  $VAL_NAME"
    echo "  │  Value: $VAL_VALUE"
    echo "  └───────────────────────────────────────────────────────┘"
    echo ""
    read -p "  Press Enter when DNS record is added (or Ctrl+C to exit)..."

    echo "  Waiting for validation (up to 10 min)..."
    MAX_WAIT=40; COUNT=0
    while [ "$COUNT" -lt "$MAX_WAIT" ]; do
        CERT_STATUS=$(aws acm describe-certificate \
            --certificate-arn "$CERT_ARN" --region "$CERT_REGION" \
            --query 'Certificate.Status' --output text)
        if [ "$CERT_STATUS" = "ISSUED" ]; then echo "  ✅ Certificate validated!"; break; fi
        COUNT=$((COUNT + 1))
        echo "  ... status: $CERT_STATUS ($COUNT/$MAX_WAIT)"
        sleep 15
    done
    if [ "$CERT_STATUS" != "ISSUED" ]; then
        echo "  ❌ Certificate not validated. Add DNS record and re-run."; exit 1
    fi
fi
echo "  ✅ ACM Certificate: ISSUED"
echo ""

# ══════════════════════════════════════════════════════════════
# Phase 3: CloudFront Distribution
# ══════════════════════════════════════════════════════════════
echo "═══ Phase 3: CloudFront Distribution ═══"

EXISTING_DIST=$(aws cloudfront list-distributions \
    --query "DistributionList.Items[?Aliases.Items[0]=='$DOMAIN'].Id" \
    --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_DIST" ] && [ "$EXISTING_DIST" != "None" ]; then
    echo "  Distribution already exists: $EXISTING_DIST"
    CF_DOMAIN=$(aws cloudfront get-distribution --id "$EXISTING_DIST" \
        --query 'Distribution.DomainName' --output text)
else
    echo "  Creating CloudFront distribution..."
    ORIGIN="$BUCKET.s3-website-$REGION.amazonaws.com"
    
    cat > /tmp/buddy-cf-config.json << CFEOF
{
  "CallerReference": "life-platform-buddy-$(date +%s)",
  "Comment": "Buddy Accountability Page — buddy.averagejoematt.com",
  "Enabled": true,
  "DefaultRootObject": "index.html",
  "Aliases": { "Quantity": 1, "Items": ["$DOMAIN"] },
  "Origins": {
    "Quantity": 1,
    "Items": [{
      "Id": "S3BuddyOrigin",
      "DomainName": "$ORIGIN",
      "OriginPath": "/buddy",
      "CustomOriginConfig": {
        "HTTPPort": 80, "HTTPSPort": 443,
        "OriginProtocolPolicy": "http-only",
        "OriginSslProtocols": { "Quantity": 1, "Items": ["TLSv1.2"] }
      }
    }]
  },
  "DefaultCacheBehavior": {
    "TargetOriginId": "S3BuddyOrigin",
    "ViewerProtocolPolicy": "redirect-to-https",
    "AllowedMethods": {
      "Quantity": 7,
      "Items": ["GET","HEAD","OPTIONS","PUT","PATCH","POST","DELETE"],
      "CachedMethods": { "Quantity": 2, "Items": ["GET","HEAD"] }
    },
    "ForwardedValues": { "QueryString": false, "Cookies": { "Forward": "none" } },
    "MinTTL": 0, "DefaultTTL": 300, "MaxTTL": 3600, "Compress": true
  },
  "CustomErrorResponses": { "Quantity": 0 },
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
        --distribution-config file:///tmp/buddy-cf-config.json \
        --query 'Distribution.{Id:Id,Domain:DomainName,Status:Status}' \
        --output json)

    EXISTING_DIST=$(echo "$DIST_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['Id'])")
    CF_DOMAIN=$(echo "$DIST_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['Domain'])")
    echo "  Distribution ID: $EXISTING_DIST"
    echo "  CloudFront domain: $CF_DOMAIN"
    rm -f /tmp/buddy-cf-config.json
fi
echo "  ✅ CloudFront distribution ready"
echo ""

# ══════════════════════════════════════════════════════════════
# Phase 4: Lambda@Edge Auth (separate password)
# ══════════════════════════════════════════════════════════════
echo "═══ Phase 4: Lambda@Edge Auth ═══"

# Password prompt
echo -n "  Enter password for buddy page: "
read -s BUDDY_PASS1; echo ""
echo -n "  Confirm password: "
read -s BUDDY_PASS2; echo ""
if [ "$BUDDY_PASS1" != "$BUDDY_PASS2" ]; then echo "  ❌ Passwords don't match"; exit 1; fi
if [ ${#BUDDY_PASS1} -lt 6 ]; then echo "  ❌ Min 6 characters"; exit 1; fi

# Create/update secret
if aws secretsmanager describe-secret --secret-id "$BUDDY_SECRET_ID" --region "$CERT_REGION" >/dev/null 2>&1; then
    aws secretsmanager update-secret \
        --secret-id "$BUDDY_SECRET_ID" \
        --secret-string "{\"password\":\"$BUDDY_PASS1\"}" \
        --region "$CERT_REGION" --no-cli-pager
    echo "  ✅ Secret updated"
else
    aws secretsmanager create-secret \
        --name "$BUDDY_SECRET_ID" \
        --secret-string "{\"password\":\"$BUDDY_PASS1\"}" \
        --description "Buddy accountability page auth password" \
        --region "$CERT_REGION" --no-cli-pager
    echo "  ✅ Secret created"
fi

# Add buddy secret access to existing edge role
BUDDY_SM_POLICY="{
  \"Version\": \"2012-10-17\",
  \"Statement\": [{
    \"Effect\": \"Allow\",
    \"Action\": [\"secretsmanager:GetSecretValue\"],
    \"Resource\": [
      \"arn:aws:secretsmanager:${CERT_REGION}:${ACCOUNT_ID}:secret:life-platform/cf-auth-*\",
      \"arn:aws:secretsmanager:${CERT_REGION}:${ACCOUNT_ID}:secret:life-platform/buddy-auth-*\"
    ]
  }]
}"
aws iam put-role-policy \
    --role-name "$BUDDY_ROLE_NAME" \
    --policy-name "secrets-read" \
    --policy-document "$BUDDY_SM_POLICY" --no-cli-pager
echo "  ✅ IAM policy updated for buddy secret"

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${BUDDY_ROLE_NAME}"

# Create buddy auth Lambda
mkdir -p /tmp/buddy-auth
cat > /tmp/buddy-auth/index.mjs << 'AUTHEOF'
import { createHmac, timingSafeEqual } from 'crypto';
import { SecretsManagerClient, GetSecretValueCommand } from '@aws-sdk/client-secrets-manager';

const SECRET_ID = 'life-platform/buddy-auth';
const COOKIE_NAME = '__buddy_auth';
const COOKIE_MAX_AGE = 90 * 24 * 60 * 60;
const CACHE_TTL_MS = 5 * 60 * 1000;

let _cachedPassword = null;
let _cacheExpiry = 0;
const sm = new SecretsManagerClient({ region: 'us-east-1' });

async function getPassword() {
    if (_cachedPassword && Date.now() < _cacheExpiry) return _cachedPassword;
    const resp = await sm.send(new GetSecretValueCommand({ SecretId: SECRET_ID }));
    const secret = JSON.parse(resp.SecretString);
    _cachedPassword = secret.password;
    _cacheExpiry = Date.now() + CACHE_TTL_MS;
    return _cachedPassword;
}

function hmacSign(password, expiry) {
    return createHmac('sha256', password).update(String(expiry)).digest('hex');
}

function makeCookieHeader(password) {
    const expiry = Math.floor(Date.now() / 1000) + COOKIE_MAX_AGE;
    const sig = hmacSign(password, expiry);
    return `${COOKIE_NAME}=${expiry}|${sig}; Path=/; Max-Age=${COOKIE_MAX_AGE}; Secure; HttpOnly; SameSite=Lax`;
}

function validateCookie(cookieStr, password) {
    const re = new RegExp(`${COOKIE_NAME}=(\\d+)\\|([a-f0-9]+)`);
    const m = cookieStr.match(re);
    if (!m) return false;
    const [, expiryStr, sig] = m;
    if (parseInt(expiryStr, 10) < Math.floor(Date.now() / 1000)) return false;
    const expected = hmacSign(password, expiryStr);
    try {
        return timingSafeEqual(Buffer.from(sig, 'hex'), Buffer.from(expected, 'hex'));
    } catch { return false; }
}

function loginPage(redirectUri, error) {
    const errorHtml = error
        ? '<p style="color:#ef4444;text-align:center;margin:0 0 1rem;font-size:0.9rem">Incorrect password</p>' : '';
    const esc = (s) => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
    const html = `<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Matt's Check-In</title>
<style>
*{box-sizing:border-box}
body{font-family:'Outfit',-apple-system,sans-serif;background:#0d0f14;color:#e8e6e3;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}
.card{background:#161921;border-radius:16px;padding:2rem;width:90%;max-width:360px;box-shadow:0 4px 24px rgba(0,0,0,.4)}
h1{font-size:1.1rem;margin:0 0 .5rem;text-align:center;font-weight:600}
.sub{font-size:.8rem;color:#8a8997;text-align:center;margin-bottom:1.5rem}
input[type=password]{width:100%;padding:12px 14px;border:1px solid #232733;border-radius:10px;background:#0d0f14;color:#e8e6e3;font-size:1rem;margin-bottom:1rem;outline:none;transition:border .2s;font-family:inherit}
input[type=password]:focus{border-color:#4ade80}
button{width:100%;padding:12px;border:none;border-radius:10px;background:#4ade80;color:#0d0f14;font-size:1rem;font-weight:600;cursor:pointer;transition:background .2s;font-family:inherit}
button:hover{background:#22c55e}
</style>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600&display=swap" rel="stylesheet">
</head><body>
<div class="card">
<h1>Matt's Check-In</h1>
<div class="sub">Accountability partner access</div>
${errorHtml}
<form method="POST" action="/__auth">
<input type="password" name="password" placeholder="Password" autofocus required autocomplete="current-password">
<input type="hidden" name="redirect" value="${esc(redirectUri)}">
<button type="submit">Sign In</button>
</form></div></body></html>`;
    return { status: '200', statusDescription: 'OK',
        headers: { 'content-type': [{ value: 'text/html; charset=utf-8' }],
                   'cache-control': [{ value: 'no-store' }] },
        body: html };
}

export async function handler(event) {
    const request = event.Records[0].cf.request;
    const uri = request.uri;
    const method = request.method;
    const cookieStr = (request.headers.cookie || []).map(c => c.value).join('; ');

    let password;
    try { password = await getPassword(); } catch {
        return { status: '503', statusDescription: 'Service Unavailable',
                 headers: { 'content-type': [{ value: 'text/plain' }] },
                 body: 'Auth service temporarily unavailable.' };
    }

    if (validateCookie(cookieStr, password)) {
        if (uri === '/__auth') return { status: '302', statusDescription: 'Found',
            headers: { location: [{ value: '/' }], 'cache-control': [{ value: 'no-store' }] } };
        return request;
    }

    if (method === 'POST' && uri === '/__auth') {
        let body = '';
        if (request.body) {
            body = request.body.encoding === 'base64'
                ? Buffer.from(request.body.data, 'base64').toString('utf-8')
                : request.body.data;
        }
        const params = new URLSearchParams(body);
        const submitted = params.get('password') || '';
        const redirectTo = params.get('redirect') || '/';
        if (submitted === password) {
            return { status: '302', statusDescription: 'Found',
                headers: { location: [{ value: redirectTo }],
                           'set-cookie': [{ value: makeCookieHeader(password) }],
                           'cache-control': [{ value: 'no-store' }] } };
        }
        return loginPage(redirectTo, true);
    }

    return loginPage(uri, false);
}
AUTHEOF

cd /tmp/buddy-auth
zip -j /tmp/buddy-auth.zip index.mjs

if aws lambda get-function --function-name "$BUDDY_FUNCTION_NAME" --region "$CERT_REGION" >/dev/null 2>&1; then
    aws lambda update-function-code \
        --function-name "$BUDDY_FUNCTION_NAME" \
        --zip-file fileb:///tmp/buddy-auth.zip \
        --region "$CERT_REGION" --no-cli-pager
    echo "  ✅ Lambda code updated"
    aws lambda wait function-updated --function-name "$BUDDY_FUNCTION_NAME" --region "$CERT_REGION"
else
    echo "  Creating Lambda function (waiting 10s for IAM)..."
    sleep 10
    aws lambda create-function \
        --function-name "$BUDDY_FUNCTION_NAME" \
        --runtime "nodejs20.x" \
        --role "$ROLE_ARN" \
        --handler "index.handler" \
        --zip-file fileb:///tmp/buddy-auth.zip \
        --timeout 5 --memory-size 128 \
        --region "$CERT_REGION" --no-cli-pager
    echo "  ✅ Lambda created"
    aws lambda wait function-active --function-name "$BUDDY_FUNCTION_NAME" --region "$CERT_REGION"
fi

# Publish version
BUDDY_VERSION=$(aws lambda publish-version \
    --function-name "$BUDDY_FUNCTION_NAME" \
    --description "Buddy auth $(date +%Y-%m-%d)" \
    --region "$CERT_REGION" \
    --query 'Version' --output text)
BUDDY_LAMBDA_ARN="arn:aws:lambda:${CERT_REGION}:${ACCOUNT_ID}:function:${BUDDY_FUNCTION_NAME}:${BUDDY_VERSION}"
echo "  ✅ Version $BUDDY_VERSION published"
echo ""

# Clean up
rm -rf /tmp/buddy-auth /tmp/buddy-auth.zip

# ══════════════════════════════════════════════════════════════
# Phase 5: Associate Auth with CloudFront
# ══════════════════════════════════════════════════════════════
echo "═══ Phase 5: Associate Lambda@Edge with CloudFront ═══"

ETAG=$(aws cloudfront get-distribution-config --id "$EXISTING_DIST" --region us-east-1 \
    --query 'ETag' --output text)
aws cloudfront get-distribution-config --id "$EXISTING_DIST" --region us-east-1 \
    --query 'DistributionConfig' > /tmp/buddy-cf-update.json

if ! command -v jq &> /dev/null; then
    echo "  ❌ jq is required. Install with: brew install jq"
    echo "  Lambda ARN for manual association: $BUDDY_LAMBDA_ARN"
    exit 1
fi

jq --arg arn "$BUDDY_LAMBDA_ARN" '
  .DefaultCacheBehavior.LambdaFunctionAssociations = {
    "Quantity": 1,
    "Items": [{
      "LambdaFunctionARN": $arn,
      "EventType": "viewer-request",
      "IncludeBody": true
    }]
  }
' /tmp/buddy-cf-update.json > /tmp/buddy-cf-final.json

aws cloudfront update-distribution \
    --id "$EXISTING_DIST" \
    --if-match "$ETAG" \
    --distribution-config file:///tmp/buddy-cf-final.json \
    --region us-east-1 --no-cli-pager

rm -f /tmp/buddy-cf-update.json /tmp/buddy-cf-final.json
echo "  ✅ Lambda@Edge associated with CloudFront"
echo ""

# ══════════════════════════════════════════════════════════════
# Phase 6: Route 53 DNS
# ══════════════════════════════════════════════════════════════
echo "═══ Phase 6: Route 53 DNS ═══"
echo ""
echo "  ┌───────────────────────────────────────────────────────┐"
echo "  │  ADD THIS DNS RECORD AT YOUR REGISTRAR:               │"
echo "  │                                                       │"
echo "  │  Type:  CNAME                                         │"
echo "  │  Name:  buddy                                         │"
echo "  │  Value: $CF_DOMAIN"
echo "  │                                                       │"
echo "  │  (For averagejoematt.com)                             │"
echo "  └───────────────────────────────────────────────────────┘"
echo ""

# Try to add via Route 53 if hosted zone exists
HOSTED_ZONE=$(aws route53 list-hosted-zones-by-name \
    --dns-name "averagejoematt.com" \
    --query "HostedZones[?Name=='averagejoematt.com.'].Id" \
    --output text 2>/dev/null | head -1 || echo "")

if [ -n "$HOSTED_ZONE" ] && [ "$HOSTED_ZONE" != "None" ]; then
    ZONE_ID=$(echo "$HOSTED_ZONE" | sed 's|/hostedzone/||')
    echo "  Found Route 53 hosted zone: $ZONE_ID"
    echo "  Creating A record alias..."
    
    CF_HOSTED_ZONE_ID="Z2FDTNDATAQYW2"  # CloudFront always uses this zone ID
    
    aws route53 change-resource-record-sets \
        --hosted-zone-id "$ZONE_ID" \
        --change-batch "{
            \"Changes\": [{
                \"Action\": \"UPSERT\",
                \"ResourceRecordSet\": {
                    \"Name\": \"$DOMAIN\",
                    \"Type\": \"A\",
                    \"AliasTarget\": {
                        \"HostedZoneId\": \"$CF_HOSTED_ZONE_ID\",
                        \"DNSName\": \"$CF_DOMAIN\",
                        \"EvaluateTargetHealth\": false
                    }
                }
            }]
        }" --no-cli-pager
    echo "  ✅ Route 53 A record created"
else
    echo "  ⚠️  No Route 53 hosted zone found. Add the CNAME record manually above."
fi
echo ""

# ══════════════════════════════════════════════════════════════
# Phase 7: Update Daily Brief Lambda
# ══════════════════════════════════════════════════════════════
echo "═══ Phase 7: Update Daily Brief Lambda ═══"
echo ""
echo "  ⚠️  MANUAL STEP REQUIRED:"
echo ""
echo "  1. Open lambdas/daily_brief_lambda.py"
echo "  2. Paste the contents of lambdas/buddy/write_buddy_json.py"
echo "     BEFORE the '# HANDLER' section"
echo "  3. In lambda_handler, after the write_clinical_json call, add:"
echo "         write_buddy_json(data, profile, yesterday)"
echo "  4. Redeploy with:"
echo "     cd lambdas && cp daily_brief_lambda.py /tmp/lambda_function.py"
echo "     cd /tmp && zip -j daily-brief.zip lambda_function.py"
echo "     aws lambda update-function-code \\"
echo "       --function-name life-platform-daily-brief \\"
echo "       --zip-file fileb:///tmp/daily-brief.zip \\"
echo "       --region us-west-2"
echo ""

echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║  ✅ Buddy Accountability Page Deploy Complete!               ║"
echo "║                                                              ║"
echo "║  URL: https://buddy.averagejoematt.com                      ║"
echo "║  Auth: Separate password (life-platform/buddy-auth)          ║"
echo "║  Data: Updated daily at 10:00 AM PT with morning brief      ║"
echo "║                                                              ║"
echo "║  CloudFront takes 5-15 min to propagate globally.            ║"
echo "║  Singapore should resolve within 15-20 min.                  ║"
echo "║                                                              ║"
echo "║  To change password later:                                   ║"
echo "║    aws secretsmanager update-secret \\                        ║"
echo "║      --secret-id life-platform/buddy-auth \\                  ║"
echo "║      --secret-string '{"password":"NEW"}' \\                  ║"
echo "║      --region us-east-1                                      ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
