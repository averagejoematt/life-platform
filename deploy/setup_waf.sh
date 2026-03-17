#!/bin/bash
# setup_waf.sh — TB7-26: WAF rate limiting on AMJ CloudFront (E3S424OXQZ8NBE)
#
# Creates a WAF WebACL in us-east-1 (required for CloudFront) with:
#   Rule 1: Rate limit /api/subscribe* — 60 requests per 5min per IP (anti-spam)
#   Rule 2: Rate limit all requests    — 1000 requests per 5min per IP (DDoS floor)
#
# Attaches WebACL to the AMJ CloudFront distribution (E3S424OXQZ8NBE).
#
# WAF cannot attach directly to Lambda Function URLs. MCP endpoint
# (c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws) is
# protected by API key auth — not publicly advertised. TB7-26 satisfied.
#
# Cost: ~$6/month (1 WebACL + 2 rules + request volume negligible at current scale)
# Run: bash deploy/setup_waf.sh
# Idempotent: safe to re-run, checks for existing WebACL first.

set -euo pipefail
REGION="us-east-1"   # WAF for CloudFront must be us-east-1
DISTRIBUTION_ID="E3S424OXQZ8NBE"
WEBACL_NAME="life-platform-amj-waf"
SCOPE="CLOUDFRONT"

echo "=== TB7-26: WAF setup for averagejoematt.com ==="
echo ""

# ── 1. Check if WebACL already exists ──────────────────────────────────────
echo "[1/4] Checking for existing WebACL..."
EXISTING_ARN=$(aws wafv2 list-web-acls \
  --scope "$SCOPE" \
  --region "$REGION" \
  --query "WebACLs[?Name=='${WEBACL_NAME}'].ARN" \
  --output text --no-cli-pager 2>/dev/null || echo "")

if [ -n "$EXISTING_ARN" ] && [ "$EXISTING_ARN" != "None" ]; then
  echo "  ✓ WebACL already exists: $EXISTING_ARN"
  WEBACL_ARN="$EXISTING_ARN"
  WEBACL_ID=$(aws wafv2 list-web-acls \
    --scope "$SCOPE" \
    --region "$REGION" \
    --query "WebACLs[?Name=='${WEBACL_NAME}'].Id" \
    --output text --no-cli-pager)
  echo "  Skipping creation, using existing."
else
  # ── 2. Create WebACL ──────────────────────────────────────────────────────
  echo "[2/4] Creating WebACL with rate-limiting rules..."

  # Write rules to temp file — avoids zsh mangling inline JSON
  RULES_FILE=$(mktemp /tmp/waf_rules_XXXXXX)
  cat > "$RULES_FILE" << 'RULES_EOF'
[
  {
    "Name": "SubscribeRateLimit",
    "Priority": 1,
    "Statement": {
      "RateBasedStatement": {
        "Limit": 60,
        "EvaluationWindowSec": 300,
        "AggregateKeyType": "IP",
        "ScopeDownStatement": {
          "ByteMatchStatement": {
            "SearchString": "L2FwaS9zdWJzY3JpYmU=",
            "FieldToMatch": {"UriPath": {}},
            "TextTransformations": [{"Priority": 0, "Type": "LOWERCASE"}],
            "PositionalConstraint": "STARTS_WITH"
          }
        }
      }
    },
    "Action": {"Block": {}},
    "VisibilityConfig": {
      "SampledRequestsEnabled": true,
      "CloudWatchMetricsEnabled": true,
      "MetricName": "SubscribeRateLimit"
    }
  },
  {
    "Name": "GlobalRateLimit",
    "Priority": 2,
    "Statement": {
      "RateBasedStatement": {
        "Limit": 1000,
        "EvaluationWindowSec": 300,
        "AggregateKeyType": "IP"
      }
    },
    "Action": {"Block": {}},
    "VisibilityConfig": {
      "SampledRequestsEnabled": true,
      "CloudWatchMetricsEnabled": true,
      "MetricName": "GlobalRateLimit"
    }
  }
]
RULES_EOF

  WEBACL_JSON=$(aws wafv2 create-web-acl \
    --name "$WEBACL_NAME" \
    --scope "$SCOPE" \
    --region "$REGION" \
    --default-action '{"Allow": {}}' \
    --description "Rate limiting for averagejoematt.com CloudFront TB7-26" \
    --visibility-config '{"SampledRequestsEnabled":true,"CloudWatchMetricsEnabled":true,"MetricName":"LifePlatformAmjWaf"}' \
    --rules "file://${RULES_FILE}" \
    --no-cli-pager)
  rm -f "$RULES_FILE"

  WEBACL_ARN=$(echo "$WEBACL_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['Summary']['ARN'])")
  WEBACL_ID=$(echo "$WEBACL_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['Summary']['Id'])")
  echo "  ✓ WebACL created: $WEBACL_ARN"
fi

echo ""

# ── 3. Attach WebACL to CloudFront distribution via update-distribution ───
# Note: WAF CloudFront associations must be set in the distribution config,
# not via associate-web-acl (that API is for ALB/APIGW/AppSync only).
echo "[3/4] Attaching WebACL to CloudFront distribution $DISTRIBUTION_ID..."

# Get current distribution config + ETag
CONFIG_JSON=$(aws cloudfront get-distribution-config \
  --id "$DISTRIBUTION_ID" \
  --region "$REGION" \
  --no-cli-pager)

ETAG=$(echo "$CONFIG_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['ETag'])")

# Check if WebACL is already set
CURRENT_WAF=$(echo "$CONFIG_JSON" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(d['DistributionConfig'].get('WebACLId',''))")

if [ "$CURRENT_WAF" = "$WEBACL_ARN" ]; then
  echo "  ✓ WebACL already attached to distribution."
else
  # Write updated config to temp file with WebACLId set
  CONFIG_FILE=$(mktemp /tmp/cf_config_XXXXXX)
  echo "$CONFIG_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
cfg = d['DistributionConfig']
cfg['WebACLId'] = sys.argv[1]
print(json.dumps(cfg))
" "$WEBACL_ARN" > "$CONFIG_FILE"

  aws cloudfront update-distribution \
    --id "$DISTRIBUTION_ID" \
    --region "$REGION" \
    --if-match "$ETAG" \
    --distribution-config "file://${CONFIG_FILE}" \
    --no-cli-pager > /dev/null
  rm -f "$CONFIG_FILE"
  echo "  ✓ WebACL attached to $DISTRIBUTION_ID"
fi

echo ""

# ── 4. Verify ──────────────────────────────────────────────────────────────
echo "[4/4] Verifying attachment..."
VERIFY=$(aws cloudfront get-distribution-config \
  --id "$DISTRIBUTION_ID" \
  --region "$REGION" \
  --query "DistributionConfig.WebACLId" \
  --output text --no-cli-pager)

if [ "$VERIFY" = "$WEBACL_ARN" ]; then
  echo "  ✓ Verified: WAF WebACL is protecting $DISTRIBUTION_ID"
else
  echo "  ❌ Verification failed. WebACLId: $VERIFY"
  exit 1
fi

echo ""
echo "=== TB7-26 complete ==="
echo ""
echo "WAF Rules active on averagejoematt.com:"
echo "  Rule 1 — SubscribeRateLimit: /api/subscribe* blocked at >60 req/5min per IP"
echo "  Rule 2 — GlobalRateLimit:   all paths blocked at >1000 req/5min per IP"
echo ""
echo "MCP endpoint note:"
echo "  Lambda Function URLs cannot attach to WAF directly."
echo "  MCP endpoint (c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws)"
echo "  is protected by API key authentication. Not publicly advertised."
echo "  TB7-26 satisfied: public-facing API surface is now WAF-protected."
echo ""
echo "Cost: ~\$6/month (1 WebACL @ \$5 + 2 rules @ \$1 each, request charges negligible)"
echo ""
echo "CloudWatch metrics available in us-east-1:"
echo "  aws cloudwatch get-metric-statistics --namespace AWS/WAFV2 \\"
echo "    --metric-name BlockedRequests --dimensions Name=WebACL,Value=$WEBACL_NAME \\"
echo "    --region us-east-1 ..."
