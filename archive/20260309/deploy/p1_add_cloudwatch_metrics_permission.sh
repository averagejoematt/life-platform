#!/bin/bash
# p1_add_cloudwatch_metrics_permission.sh
# Adds cloudwatch:PutMetricData to the 3 scoped roles so ai_calls.py
# can emit token usage and failure metrics (P1.8/P1.9).
#
# Usage: cd ~/Documents/Claude/life-platform && bash deploy/p1_add_cloudwatch_metrics_permission.sh

set -euo pipefail
REGION="us-west-2"
ACCOUNT="205930651321"

echo "── Adding cloudwatch:PutMetricData to 3 scoped roles ──"
echo ""

add_cw_permission() {
    local role="$1"
    local policy_name="${role/life-platform-/}-access"

    echo -n "  $role ... "

    # Try to read existing inline policy; fall back to empty doc if none
    CURRENT=$(aws iam get-role-policy \
        --role-name "$role" \
        --policy-name "$policy_name" \
        --query "PolicyDocument" --output json --no-cli-pager 2>/dev/null || echo "")

    # Build merged policy entirely in Python, print to stdout, capture in variable
    NEW_POLICY=$(python3 - <<PYEOF
import json, sys

existing = """$CURRENT"""

if existing.strip():
    doc = json.loads(existing)
else:
    doc = {"Version": "2012-10-17", "Statement": []}

# Remove existing CW statement (idempotency)
doc["Statement"] = [s for s in doc["Statement"] if s.get("Sid") != "CloudWatchMetrics"]

doc["Statement"].append({
    "Sid": "CloudWatchMetrics",
    "Effect": "Allow",
    "Action": "cloudwatch:PutMetricData",
    "Resource": "*",
    "Condition": {
        "StringEquals": {"cloudwatch:namespace": "LifePlatform/AI"}
    }
})
print(json.dumps(doc))
PYEOF
)

    aws iam put-role-policy \
        --role-name "$role" \
        --policy-name "$policy_name" \
        --policy-document "$NEW_POLICY" \
        --no-cli-pager

    echo "✅"
}

add_cw_permission "life-platform-compute-role"
add_cw_permission "life-platform-email-role"
add_cw_permission "life-platform-digest-role"

echo ""
echo "✅ CloudWatch PutMetricData added to all 3 roles (namespace-scoped to LifePlatform/AI)"
