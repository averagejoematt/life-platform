#!/bin/bash
# deploy_strava_dedup.sh — Strava Ingestion Dedup (Package 1 of 3)
# Version: v2.34.0
#
# What this does:
#   1. Patches strava_lambda.py with dedup_activities()
#   2. Deploys updated Strava Lambda
#   3. Does NOT touch MCP server (no MCP deploy needed)
#
# Pre-flight: Run from ~/Documents/Claude/life-platform/

set -euo pipefail
cd ~/Documents/Claude/life-platform

echo "═══════════════════════════════════════════════════"
echo "  Package 1/3: Strava Ingestion Dedup"
echo "  Version: v2.34.0"
echo "═══════════════════════════════════════════════════"

# ── Step 1: Patch Strava Lambda ──────────────────────────────────────────
echo ""
echo "── Step 1: Patching Strava Lambda ──"
python3 patches/patch_strava_dedup.py

# ── Step 2: Verify patch ─────────────────────────────────────────────────
echo ""
echo "── Step 2: Verifying patch ──"

for check in "def dedup_activities" "Global dedup"; do
    if grep -q "$check" lambdas/strava_lambda.py; then
        echo "  ✅ Found: $check"
    else
        echo "  ❌ MISSING: $check — aborting"
        exit 1
    fi
done

python3 -c "import py_compile; py_compile.compile('lambdas/strava_lambda.py', doraise=True)" && echo "  ✅ Python syntax valid" || { echo "  ❌ Syntax error"; exit 1; }

# ── Step 3: Package and deploy ───────────────────────────────────────────
echo ""
echo "── Step 3: Packaging Strava Lambda ──"
cd lambdas
rm -f strava_lambda.zip
zip strava_lambda.zip strava_lambda.py
cd ..

echo "── Step 4: Deploying Strava Lambda ──"
aws lambda update-function-code \
    --function-name life-platform-strava \
    --zip-file fileb://lambdas/strava_lambda.zip \
    --region us-west-2 \
    --no-cli-pager

echo "  ✅ Strava Lambda deployed"

# ── Step 5: Wait and verify ──────────────────────────────────────────────
echo ""
echo "── Step 5: Waiting for Lambda to stabilize ──"
sleep 5

aws lambda get-function-configuration \
    --function-name life-platform-strava \
    --query "[LastModified, CodeSize, Handler]" \
    --region us-west-2 \
    --no-cli-pager

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅ Package 1/3 DEPLOYED — Strava Ingestion Dedup"
echo ""
echo "  What changed:"
echo "    - Strava Lambda now deduplicates multi-device"
echo "      recordings at ingestion time"
echo "    - Same logic used in daily brief (sport_type +"
echo "      15min overlap → keep richer record)"
echo ""
echo "  Test: Trigger a Strava ingest for a day with"
echo "  known duplicates and check CloudWatch logs for"
echo "  [DEDUP] messages."
echo ""
echo "  Next: Run deploy_n1_experiments.sh (Package 2/3)"
echo "═══════════════════════════════════════════════════"
