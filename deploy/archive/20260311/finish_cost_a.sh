#!/usr/bin/env bash
# deploy/finish_cost_a.sh
# COST-A: Finalize CloudWatch alarm consolidation.
#
# Context: v3.4.5 wrote the CDK changes. v3.4.6 deployed LifePlatformEmail.
# This script completes the remaining two steps:
#   1. Delete pre-CDK orphan alarms (delete_orphan_alarms.sh already populated)
#   2. Deploy LifePlatformMonitoring (removes duplicate alarms from stack)
#   3. Deploy LifePlatformOperational (removes canary-any-failure dup)
#
# Expected result: ~87 -> ~41 alarms, saves ~$4.60/mo
#
# Usage: bash deploy/finish_cost_a.sh

set -euo pipefail
REGION="us-west-2"

echo "=== COST-A: Finalizing CloudWatch alarm consolidation ==="
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Step 1: Count current alarms ─────────────────────────────────────────────
BEFORE_COUNT=$(aws cloudwatch describe-alarms \
  --region "$REGION" --output json \
  | python3 -c "import json,sys; print(len(json.load(sys.stdin)['MetricAlarms']))")
echo "Current alarm count: $BEFORE_COUNT"
echo ""

# ── Step 2: Delete orphan alarms ─────────────────────────────────────────────
echo "Step 1: Deleting orphan alarms..."
bash "$SCRIPT_DIR/delete_orphan_alarms.sh"

echo ""
echo "Pausing 5 seconds before CDK..."
sleep 5

# ── Step 3: Deploy CDK Monitoring stack ─────────────────────────────────────
echo ""
echo "Step 2: Deploying LifePlatformMonitoring..."
cd "$SCRIPT_DIR/../cdk"
cdk deploy LifePlatformMonitoring --require-approval never

echo ""
echo "Pausing 10 seconds before next stack..."
sleep 10

# ── Step 4: Deploy CDK Operational stack ────────────────────────────────────
echo ""
echo "Step 3: Deploying LifePlatformOperational..."
cdk deploy LifePlatformOperational --require-approval never

# ── Step 5: Final count ──────────────────────────────────────────────────────
echo ""
echo "=== Final alarm count ==="
AFTER_COUNT=$(aws cloudwatch describe-alarms \
  --region "$REGION" --output json \
  | python3 -c "import json,sys; print(len(json.load(sys.stdin)['MetricAlarms']))")
echo "Before: $BEFORE_COUNT  ->  After: $AFTER_COUNT  (target: ~41)"
SAVED=$((BEFORE_COUNT - AFTER_COUNT))
echo "Alarms removed: $SAVED"

echo ""
echo "=== COST-A Complete ==="
echo "Savings: ~\$4.60/month (CloudWatch alarms consolidated)"
