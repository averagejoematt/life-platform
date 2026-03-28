#!/bin/bash
set -euo pipefail

# R18-F06: Add endpoint-specific WAF rate rules for AI endpoints
# Requires the existing WebACL from TB7-26 (setup_waf.sh)

REGION="us-east-1"
WEBACL_NAME="life-platform-amj-waf"
SCOPE="CLOUDFRONT"

echo "=== R18-F06: WAF endpoint-specific rate rules ==="

echo "[1/3] Fetching current WebACL..."
WEBACL_JSON=$(aws wafv2 get-web-acl \
  --name "$WEBACL_NAME" \
  --scope "$SCOPE" \
  --region "$REGION" \
  --no-cli-pager)

WEBACL_ID=$(echo "$WEBACL_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['WebACL']['Id'])")
LOCK_TOKEN=$(echo "$WEBACL_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['LockToken'])")
CURRENT_RULES=$(echo "$WEBACL_JSON" | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['WebACL']['Rules']))")

echo "  Current rules: $(echo "$CURRENT_RULES" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")"

if echo "$CURRENT_RULES" | grep -q "AskRateLimit"; then
  echo "  ✓ AskRateLimit rule already exists — skipping"
  exit 0
fi

echo "[2/3] Adding endpoint-specific rate rules..."

NEW_RULES=$(python3 -c "
import json
rules = json.loads('''$CURRENT_RULES''')

rules.append({
    'Name': 'AskRateLimit',
    'Priority': 3,
    'Statement': {
        'RateBasedStatement': {
            'Limit': 100,
            'EvaluationWindowSec': 300,
            'AggregateKeyType': 'IP',
            'ScopeDownStatement': {
                'ByteMatchStatement': {
                    'SearchString': '/api/ask',
                    'FieldToMatch': {'UriPath': {}},
                    'TextTransformations': [{'Priority': 0, 'Type': 'LOWERCASE'}],
                    'PositionalConstraint': 'STARTS_WITH'
                }
            }
        }
    },
    'Action': {'Block': {}},
    'VisibilityConfig': {
        'SampledRequestsEnabled': True,
        'CloudWatchMetricsEnabled': True,
        'MetricName': 'AskRateLimit'
    }
})

rules.append({
    'Name': 'BoardAskRateLimit',
    'Priority': 4,
    'Statement': {
        'RateBasedStatement': {
            'Limit': 100,
            'EvaluationWindowSec': 300,
            'AggregateKeyType': 'IP',
            'ScopeDownStatement': {
                'ByteMatchStatement': {
                    'SearchString': '/api/board_ask',
                    'FieldToMatch': {'UriPath': {}},
                    'TextTransformations': [{'Priority': 0, 'Type': 'LOWERCASE'}],
                    'PositionalConstraint': 'STARTS_WITH'
                }
            }
        }
    },
    'Action': {'Block': {}},
    'VisibilityConfig': {
        'SampledRequestsEnabled': True,
        'CloudWatchMetricsEnabled': True,
        'MetricName': 'BoardAskRateLimit'
    }
})

print(json.dumps(rules))
")

VISIBILITY_CONFIG=$(echo "$WEBACL_JSON" | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['WebACL']['VisibilityConfig']))")

aws wafv2 update-web-acl \
  --name "$WEBACL_NAME" \
  --scope "$SCOPE" \
  --region "$REGION" \
  --id "$WEBACL_ID" \
  --lock-token "$LOCK_TOKEN" \
  --default-action '{"Allow": {}}' \
  --visibility-config "$VISIBILITY_CONFIG" \
  --rules "$NEW_RULES" \
  --no-cli-pager > /dev/null

echo "  ✓ Added AskRateLimit (100/5min on /api/ask*)"
echo "  ✓ Added BoardAskRateLimit (100/5min on /api/board_ask*)"

echo ""
echo "[3/3] Verifying..."
VERIFY=$(aws wafv2 get-web-acl --name "$WEBACL_NAME" --scope "$SCOPE" --region "$REGION" --query 'WebACL.Rules[].Name' --output text --no-cli-pager)
echo "  Active rules: $VERIFY"
echo ""
echo "=== R18-F06 complete ==="
