#!/bin/bash
# Group D: Ingestion validation + size monitoring (F2.1, F2.2, F2.5)
# Items 15-19: Field presence validation (Whoop, Strava, Eight Sleep)
#              + Item size warnings (Strava, MacroFactor)
#
# Code changes already applied to local Lambda files.
# This script zips and deploys all 4 modified Lambdas.

set -euo pipefail
REGION="us-west-2"
cd ~/Documents/Claude/life-platform

echo "═══════════════════════════════════════════════════════"
echo "  Group D: Ingestion Validation + Size Monitoring"
echo "═══════════════════════════════════════════════════════"

# ── 1. Whoop Lambda (F2.5 field validation) ──
echo ""
echo "▸ [1/4] Deploying Whoop Lambda..."
cd lambdas
zip -j /tmp/whoop_lambda.zip whoop_lambda.py
aws lambda update-function-code \
  --function-name whoop-data-ingestion \
  --zip-file fileb:///tmp/whoop_lambda.zip \
  --region $REGION \
  --no-cli-pager
echo "  ✓ Whoop Lambda deployed with field presence validation"
sleep 10

# ── 2. Strava Lambda (F2.5 field validation + F2.1 size warning) ──
echo ""
echo "▸ [2/4] Deploying Strava Lambda..."
zip -j /tmp/strava_lambda.zip strava_lambda.py
aws lambda update-function-code \
  --function-name strava-data-ingestion \
  --zip-file fileb:///tmp/strava_lambda.zip \
  --region $REGION \
  --no-cli-pager
echo "  ✓ Strava Lambda deployed with field validation + size monitoring"
sleep 10

# ── 3. Eight Sleep Lambda (F2.5 field validation) ──
echo ""
echo "▸ [3/4] Deploying Eight Sleep Lambda..."
zip -j /tmp/eightsleep_lambda.zip eightsleep_lambda.py
aws lambda update-function-code \
  --function-name eightsleep-data-ingestion \
  --zip-file fileb:///tmp/eightsleep_lambda.zip \
  --region $REGION \
  --no-cli-pager
echo "  ✓ Eight Sleep Lambda deployed with field presence validation"
sleep 10

# ── 4. MacroFactor Lambda (F2.2 size warning) ──
echo ""
echo "▸ [4/4] Deploying MacroFactor Lambda..."
zip -j /tmp/macrofactor_lambda.zip macrofactor_lambda.py
aws lambda update-function-code \
  --function-name macrofactor-data-ingestion \
  --zip-file fileb:///tmp/macrofactor_lambda.zip \
  --region $REGION \
  --no-cli-pager
echo "  ✓ MacroFactor Lambda deployed with size monitoring"

cd ..

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Group D Complete!"
echo "  Deployed: whoop, strava, eightsleep, macrofactor"
echo ""
echo "  New log patterns to watch:"
echo "    [VALIDATION] ⚠️ CRITICAL fields missing"
echo "    [VALIDATION] Expected fields missing"
echo "    [SIZE-WARNING] ⚠️ ... approaching 400KB"
echo "    [SIZE-INFO] ... item is NNkB"
echo "═══════════════════════════════════════════════════════"
