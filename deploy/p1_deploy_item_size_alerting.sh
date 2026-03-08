#!/bin/bash
# p1_deploy_item_size_alerting.sh — P1.10: DynamoDB item size CloudWatch metrics
#
# Adds cloudwatch:PutMetricData to the ingestion role, deploys strava + macrofactor
# Lambdas, and creates a CloudWatch alarm that fires when any item exceeds 300KB.
#
# Usage: cd ~/Documents/Claude/life-platform && bash deploy/p1_deploy_item_size_alerting.sh

set -euo pipefail
REGION="us-west-2"
ACCOUNT="205930651321"
SNS_ARN="arn:aws:sns:$REGION:$ACCOUNT:life-platform-alerts"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  P1.10: DynamoDB item size alerting                         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Add cloudwatch:PutMetricData to the ingestion role ──────────────
echo "── Step 1: Adding CloudWatch permission to ingestion roles ──"

for role in "life-platform-strava-role" "life-platform-macrofactor-role" "life-platform-ingestion-role"; do
    # Check if role exists
    aws iam get-role --role-name "$role" --no-cli-pager > /dev/null 2>&1 || { echo "  $role not found, skipping"; continue; }

    POLICY_NAME="${role/life-platform-/}-access"

    CURRENT=$(aws iam get-role-policy \
        --role-name "$role" \
        --policy-name "$POLICY_NAME" \
        --query "PolicyDocument" --output json --no-cli-pager 2>/dev/null || echo "")

    echo -n "  $role ... "

    NEW_POLICY=$(python3 - <<PYEOF
import json

existing = """$CURRENT"""
if existing.strip():
    doc = json.loads(existing)
else:
    doc = {"Version": "2012-10-17", "Statement": []}

doc["Statement"] = [s for s in doc["Statement"] if s.get("Sid") != "CloudWatchIngestionMetrics"]
doc["Statement"].append({
    "Sid": "CloudWatchIngestionMetrics",
    "Effect": "Allow",
    "Action": "cloudwatch:PutMetricData",
    "Resource": "*",
    "Condition": {
        "StringEquals": {"cloudwatch:namespace": "LifePlatform/Ingestion"}
    }
})
print(json.dumps(doc))
PYEOF
)
    aws iam put-role-policy \
        --role-name "$role" \
        --policy-name "$POLICY_NAME" \
        --policy-document "$NEW_POLICY" \
        --no-cli-pager
    echo "✅"
done

# Also add to the general Lambda execution roles that run strava/macrofactor
# (they may use the shared lambda-execution-role — handle gracefully)
echo ""

# ── Step 2: Check which roles strava + macrofactor actually use ──────────────
echo "── Step 2: Adding CW permission to actual Lambda execution roles ──"
for fn in "strava-data-ingestion" "macrofactor-data-ingestion"; do
    ROLE_ARN=$(aws lambda get-function-configuration \
        --function-name "$fn" --region "$REGION" \
        --query "Role" --output text --no-cli-pager 2>/dev/null || echo "")
    [ -z "$ROLE_ARN" ] && { echo "  $fn not found, skipping"; continue; }

    ROLE_NAME=$(basename "$ROLE_ARN")
    echo -n "  $fn uses role $ROLE_NAME ... "

    POLICY_NAME="ingestion-access"
    CURRENT=$(aws iam get-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-name "$POLICY_NAME" \
        --query "PolicyDocument" --output json --no-cli-pager 2>/dev/null || echo "")

    NEW_POLICY=$(python3 - <<PYEOF
import json
existing = """$CURRENT"""
if existing.strip():
    doc = json.loads(existing)
else:
    doc = {"Version": "2012-10-17", "Statement": []}
doc["Statement"] = [s for s in doc["Statement"] if s.get("Sid") != "CloudWatchIngestionMetrics"]
doc["Statement"].append({
    "Sid": "CloudWatchIngestionMetrics",
    "Effect": "Allow",
    "Action": "cloudwatch:PutMetricData",
    "Resource": "*",
    "Condition": {"StringEquals": {"cloudwatch:namespace": "LifePlatform/Ingestion"}}
})
print(json.dumps(doc))
PYEOF
)
    aws iam put-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-name "$POLICY_NAME" \
        --policy-document "$NEW_POLICY" \
        --no-cli-pager && echo "✅" || echo "⚠️  (may need manual review)"
done
echo ""

# ── Step 3: Deploy Lambdas ────────────────────────────────────────────────────
echo "── Step 3: Deploying Strava Lambda ──"
bash deploy/deploy_lambda.sh strava-data-ingestion lambdas/strava_lambda.py
sleep 10

echo "── Step 4: Deploying MacroFactor Lambda ──"
bash deploy/deploy_lambda.sh macrofactor-data-ingestion lambdas/macrofactor_lambda.py
sleep 5

# ── Step 5: Create CloudWatch alarm ──────────────────────────────────────────
echo ""
echo "── Step 5: Creating DynamoDB item size alarm (threshold: 300KB) ──"

aws cloudwatch put-metric-alarm \
    --alarm-name "life-platform-ddb-item-size-warning" \
    --alarm-description "DynamoDB item approaching 400KB limit — ingestion item exceeded 300KB. Check Strava or MacroFactor data volume." \
    --namespace "LifePlatform/Ingestion" \
    --metric-name "DynamoDBItemSizeKB" \
    --statistic "Maximum" \
    --period 86400 \
    --evaluation-periods 1 \
    --datapoints-to-alarm 1 \
    --threshold 300 \
    --comparison-operator "GreaterThanOrEqualToThreshold" \
    --treat-missing-data "notBreaching" \
    --alarm-actions "$SNS_ARN" \
    --region "$REGION" \
    --no-cli-pager

echo "  ✅ life-platform-ddb-item-size-warning created (>=300KB → alarm)"
echo ""

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✅ P1.10 Item Size Alerting Complete                       ║"
echo "║                                                              ║"
echo "║  Strava + MacroFactor now emit DynamoDBItemSizeKB metric    ║"
echo "║  Alarm fires when any item >= 300KB (DDB limit is 400KB)    ║"
echo "║  Namespace: LifePlatform/Ingestion > Source dimension       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
