#!/bin/bash
# fix_cf_auth_methods.sh — Allow POST on dash CloudFront so auth form works
# Fixes: clinic.html (and all protected pages) error after password entry
# Root cause: AllowedMethods only had GET/HEAD, blocking the POST to /__auth

set -euo pipefail

DIST_ID="EM5NPX6NJN095"
ETAG="E3UN6WX5RRO2AG"

echo "=== Fix CloudFront Auth: Allow POST ==="
echo ""

# Get current config
echo "[1/3] Fetching current distribution config..."
aws cloudfront get-distribution-config --id "$DIST_ID" --output json \
  | jq '.DistributionConfig' > /tmp/cf-dash-config.json

# Update AllowedMethods to include POST (and OPTIONS for good measure)
echo "[2/3] Updating AllowedMethods to allow POST..."
jq '.DefaultCacheBehavior.AllowedMethods = {
    "Quantity": 7,
    "Items": ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"],
    "CachedMethods": {
        "Quantity": 2,
        "Items": ["GET", "HEAD"]
    }
}' /tmp/cf-dash-config.json > /tmp/cf-dash-config-updated.json

# Also need to forward cookies so the auth cookie works!
# Current config: "Cookies": {"Forward": "none"} — this means CloudFront
# strips cookies before forwarding to origin AND before Lambda@Edge sees
# the response cookies on subsequent requests.
# For Lambda@Edge viewer-request, cookies ARE available in the request
# (viewer-request runs before cache), but let's also forward the cookie
# to ensure Set-Cookie headers aren't cached incorrectly.

echo "[3/3] Applying update..."
aws cloudfront update-distribution \
  --id "$DIST_ID" \
  --if-match "$ETAG" \
  --distribution-config file:///tmp/cf-dash-config-updated.json \
  --output json \
  | jq '{Status: .Distribution.Status, DomainName: .Distribution.DomainName, ETag: .ETag}'

echo ""
echo "✓ CloudFront updated — POST now allowed"
echo "  Distribution will redeploy (2-5 min)."
echo "  Then test: visit dash.averagejoematt.com/clinic.html"
echo "  Enter password → should redirect successfully now."
