#!/bin/bash
# deploy_cdk_iam_roles.sh — Migrate all Lambda IAM roles to CDK-managed
# Deploy ONE stack at a time. Wait for each to succeed before proceeding.
set -euo pipefail
cd ~/Documents/Claude/life-platform/cdk

echo "═══════════════════════════════════════════════════════════════"
echo " CDK IAM Role Migration — v3.4.0"
echo "═══════════════════════════════════════════════════════════════"

echo "▸ Step 1: CDK diff (preview changes)..."
for stack in LifePlatformMcp LifePlatformOperational LifePlatformCompute LifePlatformIngestion LifePlatformEmail; do
    echo "--- $stack ---"
    npx cdk diff "$stack" 2>&1 || true
    echo ""
done

echo "Review the diff above. Press Enter to deploy, or Ctrl+C to abort."
read -r

STACKS=(LifePlatformMcp LifePlatformOperational LifePlatformCompute LifePlatformIngestion LifePlatformEmail)
for stack in "${STACKS[@]}"; do
    echo "▸ Deploying $stack..."
    npx cdk deploy "$stack" --require-approval never 2>&1
    echo "  ✅ $stack deployed. Waiting 15s..."
    sleep 15
done

echo ""
echo "All 5 stacks deployed. Next:"
echo "  1. bash deploy/verify_iam_migration.sh"
echo "  2. Monitor CloudWatch 24h"
echo "  3. bash deploy/cleanup_old_roles.sh"
