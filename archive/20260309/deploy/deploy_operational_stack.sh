#!/usr/bin/env bash
# deploy_operational_stack.sh — Import + deploy LifePlatformOperational CDK stack
#
# Step 1: cdk synth (verify no errors)
# Step 2: cdk import (import existing AWS resources into CloudFormation)
# Step 3: cdk deploy (create missing alarms + Lambda permissions)
#
# Resources being imported:
#   8 Lambdas: freshness-checker, dlq-consumer, canary, pip-audit,
#              qa-smoke, key-rotator, data-export, data-reconciliation
#   6 EventBridge rules (key-rotator and data-export have no schedule)
#   7 CloudWatch alarms (3 Lambda error alarms + 4 canary custom alarms)
#   1 SQS-based DLQ depth alarm
#
# Alarms that will be CREATED (don't exist in AWS yet): none — all exist
# Lambda::Permissions that will be CREATED: SecretsManager invoke on key-rotator
#
# Usage: bash deploy/deploy_operational_stack.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CDK_DIR="$SCRIPT_DIR/../cdk"

echo "=== LifePlatformOperational — Import + Deploy ==="
echo ""

cd "$CDK_DIR"
source .venv/bin/activate

# ── Step 1: Synth ──
echo "--- Step 1: cdk synth (checking for errors) ---"
npx cdk synth LifePlatformOperational --quiet
echo "Synth OK"
echo ""

# ── Step 2: Import ──
echo "--- Step 2: cdk import (importing existing AWS resources) ---"
echo "Using import map: operational-import-map.json"
echo ""
echo "⚠️  CDK will prompt for physical resource IDs."
echo "    The import map covers most resources automatically with --resource-mapping."
echo "    If prompted manually, use the values from operational-import-map.json."
echo ""
npx cdk import LifePlatformOperational \
  --resource-mapping operational-import-map.json \
  --force

echo ""
echo "Import complete. Verifying stack status..."
aws cloudformation describe-stacks \
  --stack-name LifePlatformOperational \
  --query "Stacks[0].{Status:StackStatus,Reason:StackStatusReason}" \
  --region us-west-2

# ── Step 3: Deploy ──
echo ""
read -p "Proceed with cdk deploy? (creates SM invoke permission) (y/N) " confirm
[[ "$confirm" =~ ^[Yy]$ ]] || { echo "Import done, deploy skipped."; exit 0; }

echo "--- Step 3: cdk deploy ---"
npx cdk deploy LifePlatformOperational --require-approval never

echo ""
echo "=== Deploy complete ==="
echo ""
echo "Stack summary:"
aws cloudformation describe-stack-resources \
  --stack-name LifePlatformOperational \
  --query "StackResources[].{Type:ResourceType,LogicalId:LogicalResourceId,Status:ResourceStatus}" \
  --output table \
  --region us-west-2
