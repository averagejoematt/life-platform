#!/usr/bin/env bash
# post_hygiene_v344.sh — Run all 3 post-hygiene actions from v3.4.4 session
# 1. Delete dead Lambda files (weather_lambda.py.archived, freshness_checker.py)
# 2. Deploy failure-pattern-compute with TTL fix
# 3. Deploy CDK LifePlatformComputeStack with needs_kms updates
#
# Run from project root: bash deploy/post_hygiene_v344.sh

set -euo pipefail
cd /Users/matthewwalker/Documents/Claude/life-platform
ROOT="$(pwd)"
DEPLOY="$ROOT/deploy"

echo "======================================="
echo " Life Platform v3.4.4 — Post-Hygiene"
echo "======================================="
echo ""

# ── Step 1: Delete dead files ────────────────────────────────────────────────
echo "Step 1/3: Deleting dead Lambda files..."

if [ -f "$ROOT/lambdas/weather_lambda.py.archived" ]; then
    rm "$ROOT/lambdas/weather_lambda.py.archived"
    echo "  ✓ Deleted lambdas/weather_lambda.py.archived"
else
    echo "  ✓ Already gone: lambdas/weather_lambda.py.archived"
fi

if [ -f "$ROOT/lambdas/freshness_checker.py" ]; then
    rm "$ROOT/lambdas/freshness_checker.py"
    echo "  ✓ Deleted lambdas/freshness_checker.py"
else
    echo "  ✓ Already gone: lambdas/freshness_checker.py"
fi

echo ""

# ── Step 2: Deploy failure-pattern-compute (TTL field added) ─────────────────
echo "Step 2/3: Deploying failure-pattern-compute (TTL fix)..."
bash "$DEPLOY/deploy_lambda.sh" failure-pattern-compute lambdas/failure_pattern_compute_lambda.py
echo "  ✓ failure-pattern-compute deployed"

echo ""
echo "  Waiting 10s before CDK deploy..."
sleep 10

# ── Step 3: CDK deploy LifePlatformComputeStack (needs_kms on 6 compute fns) ─
echo "Step 3/3: Deploying LifePlatformComputeStack (needs_kms audit)..."
cd "$ROOT/cdk"
source .venv/bin/activate
npx cdk deploy LifePlatformCompute --require-approval never
echo "  ✓ LifePlatformComputeStack deployed"

echo ""
echo "======================================="
echo " All done! Verify in CloudWatch:"
echo "   /aws/lambda/failure-pattern-compute"
echo "   /aws/lambda/dashboard-refresh"
echo "   /aws/lambda/anomaly-detector"
echo "======================================="
echo ""
# ── Step 4: Git commit ──────────────────────────────────────────────────────
echo "Step 4/4: Git commit..."
cd "$ROOT"
git add -A
git commit -m "v3.4.4: Hygiene sweep — INCIDENT_LOG +5, ADRs 021-023, needs_kms audit, TTL failure_pattern, 19 scripts archived, ARCHITECTURE.md updated"
git push
echo "  ✓ Committed and pushed"

echo ""
echo "======================================="
echo " Next: create life-platform/habitify"
echo " secret before 2026-04-07."
echo " See handovers/2026-03-10_hygiene_sweep_v3.4.3.md"
echo "======================================="
