#!/usr/bin/env bash
# TB7-3 + TB7-10: CDK reconcile + reserved concurrency for 13 ingestion Lambdas
# Run from: ~/Documents/Claude/life-platform/cdk/
set -euo pipefail

echo "=== CDK Reconcile: LifePlatformIngestion + LifePlatformOperational ==="
echo "Changes in this deploy:"
echo "  - TB7-3: Sync CDK state for both stacks (drift from ingestion_stack.py + role_policies.py changes)"
echo "  - TB7-10: reserved_concurrent_executions=1 on all 13 scheduled ingestion Lambdas"
echo "  - NOTE: Apple Health + HAE webhook intentionally excluded (event-driven, need concurrency)"
echo ""

cd "$(dirname "$0")"

# Activate venv
source .venv/bin/activate

# Diff first so you can review what changes
echo "=== CDK Diff ==="
npx cdk diff LifePlatformIngestion LifePlatformOperational

echo ""
echo "=== Proceeding with deploy in 5s (Ctrl-C to abort) ==="
sleep 5

npx cdk deploy LifePlatformIngestion LifePlatformOperational \
    --require-approval never \
    --outputs-file /tmp/cdk-reconcile-outputs.json

echo ""
echo "=== Verifying reserved concurrency on spot-check Lambdas ==="
for fn in whoop-data-ingestion strava-data-ingestion dropbox-poll weather-data-ingestion; do
    rc=$(aws lambda get-function-concurrency --function-name "$fn" \
         --query 'ReservedConcurrentExecutions' --output text 2>/dev/null || echo "N/A")
    echo "  $fn → reserved_concurrency=$rc"
done

echo ""
echo "=== Done. Check /tmp/cdk-reconcile-outputs.json for stack outputs ==="
