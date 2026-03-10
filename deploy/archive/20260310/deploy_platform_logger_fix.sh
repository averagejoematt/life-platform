#!/bin/bash
# deploy_platform_logger_fix.sh — Hotfix: redeploy Lambda Layer with PlatformLogger v1.0.1
#
# Fixes two bugs causing ~20 alarms across all ingestion + compute Lambdas:
#   Bug A: 'Logger' object has no attribute 'set_date'
#          Cause: platform_logger.py was missing from layer (ImportError fallback hit)
#   Bug B: PlatformLogger.info() takes 2 positional arguments but 3 were given
#          Cause: %s-style positional args not supported (now fixed in v1.0.1)
#
# Fix: rebuild layer with updated platform_logger.py, redeploy Core + all dependent stacks.
# Affected stacks: LifePlatformCore, LifePlatformIngestion, LifePlatformCompute,
#                  LifePlatformEmail, LifePlatformOperational, LifePlatformMcp
#
# 2026-03-10

set -euo pipefail
PROJ_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== PlatformLogger hotfix deploy ==="
echo ""

# Step 1: Rebuild the layer
echo "Step 1/3 — Rebuilding Lambda Layer..."
bash "$PROJ_ROOT/deploy/build_layer.sh"
echo ""

# Step 2: Deploy Core stack (publishes new layer version)
echo "Step 2/3 — Deploying LifePlatformCore (new layer version)..."
cd "$PROJ_ROOT/cdk"
source .venv/bin/activate
npx cdk deploy LifePlatformCore --require-approval never
echo ""

# Step 3: Deploy all stacks that consume the layer so Lambdas pick up new version
echo "Step 3/3 — Redeploying dependent stacks (Lambdas pick up new layer version)..."
echo "  Deploying LifePlatformIngestion..."
npx cdk deploy LifePlatformIngestion --require-approval never
sleep 10
echo "  Deploying LifePlatformCompute..."
npx cdk deploy LifePlatformCompute --require-approval never
sleep 10
echo "  Deploying LifePlatformEmail..."
npx cdk deploy LifePlatformEmail --require-approval never
sleep 10
echo "  Deploying LifePlatformOperational..."
npx cdk deploy LifePlatformOperational --require-approval never
sleep 10
echo "  Deploying LifePlatformMcp..."
npx cdk deploy LifePlatformMcp --require-approval never
echo ""

echo "=== Deploy complete ==="
echo ""
echo "Next steps:"
echo "  1. Wait ~5 min for alarms to auto-resolve (24h window resets)"
echo "  2. Manually invoke a few Lambdas to verify clean execution:"
echo "     aws lambda invoke --function-name whoop-data-ingestion --region us-west-2 /tmp/out.json && cat /tmp/out.json"
echo "     aws lambda invoke --function-name daily-metrics-compute --region us-west-2 /tmp/out.json && cat /tmp/out.json"
echo "  3. Clear the DLQ (11 dead messages from failed invocations):"
echo "     aws sqs purge-queue --queue-url https://sqs.us-west-2.amazonaws.com/205930651321/life-platform-ingestion-dlq --region us-west-2"
