#!/usr/bin/env bash
# deploy_sleep_sot_redesign.sh — Deploy sleep source-of-truth migration
#
# Deploys 6 Lambdas with Whoop as sleep SOT (duration, stages, score)
# and Eight Sleep retained for bed environment data.
#
# Changed files:
#   1. mcp/config.py          — "sleep": "whoop", "sleep_environment": "eightsleep"
#   2. mcp/tools_sleep.py     — queries Whoop, returns "source": "whoop"
#   3. mcp/helpers.py         — normalize_whoop_sleep() added
#   4. mcp/tools_correlation.py — migrated to Whoop sleep
#   5. mcp/tools_lifestyle.py — migrated (intentional ES refs for bed metrics)
#   6. lambdas/anomaly_detector_lambda.py — METRICS → whoop sleep fields
#   7. lambdas/wednesday_chronicle_lambda.py — sleep section → Whoop + ES environment
#   8. lambdas/daily_brief_lambda.py — fully migrated to Whoop sleep
#   9. lambdas/monthly_digest_lambda.py — fully migrated (ex_whoop_sleep())
#  10. lambdas/weekly_digest_lambda.py — migrated
#
# Usage:
#   cd ~/Documents/Claude/life-platform
#   chmod +x deploy/deploy_sleep_sot_redesign.sh
#   ./deploy/deploy_sleep_sot_redesign.sh

set -euo pipefail

REGION="us-west-2"
DEPLOY_DIR="deploy"
LAMBDAS_DIR="lambdas"

info()  { echo "  [INFO]  $*"; }
ok()    { echo "  [✅]    $*"; }
fail()  { echo "  [❌]    $*" >&2; }
step()  { echo ""; echo "═══ $* ═══"; }

ERRORS=0

# ══════════════════════════════════════════════════════════════════════════════
# PRE-FLIGHT: Syntax check all changed files
# ══════════════════════════════════════════════════════════════════════════════
step "Step 0: Pre-flight syntax checks"

for f in mcp_server.py mcp/*.py; do
    if ! python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" 2>/dev/null; then
        fail "Syntax error: $f"
        ERRORS=$((ERRORS + 1))
    fi
done

for f in \
    "$LAMBDAS_DIR/anomaly_detector_lambda.py" \
    "$LAMBDAS_DIR/wednesday_chronicle_lambda.py" \
    "$LAMBDAS_DIR/daily_brief_lambda.py" \
    "$LAMBDAS_DIR/monthly_digest_lambda.py" \
    "$LAMBDAS_DIR/weekly_digest_lambda.py"; do
    if [ ! -f "$f" ]; then
        fail "Missing: $f"
        ERRORS=$((ERRORS + 1))
    elif ! python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" 2>/dev/null; then
        fail "Syntax error: $f"
        ERRORS=$((ERRORS + 1))
    fi
done

if [ "$ERRORS" -gt 0 ]; then
    echo ""
    fail "$ERRORS syntax errors found. Aborting."
    exit 1
fi
ok "All files pass syntax check"

# ══════════════════════════════════════════════════════════════════════════════
# 1. MCP Server (mcp_server.py + mcp/ package)
# ══════════════════════════════════════════════════════════════════════════════
step "Step 1/6: MCP Server (life-platform-mcp)"

rm -f mcp_server.zip
zip mcp_server.zip mcp_server.py
zip -r mcp_server.zip mcp/ -x "mcp/__pycache__/*"
info "Packaged mcp_server.zip ($(du -h mcp_server.zip | cut -f1))"

aws lambda update-function-code \
    --function-name "life-platform-mcp" \
    --zip-file "fileb://mcp_server.zip" \
    --region "$REGION" > /dev/null
aws lambda wait function-updated --function-name "life-platform-mcp" --region "$REGION"
ok "MCP server deployed"

sleep 5

# ══════════════════════════════════════════════════════════════════════════════
# 2. Anomaly Detector
# ══════════════════════════════════════════════════════════════════════════════
step "Step 2/6: Anomaly Detector (anomaly-detector)"

# Handler expects: anomaly_detector_lambda.lambda_handler
rm -f anomaly_detector.zip
cp "$LAMBDAS_DIR/anomaly_detector_lambda.py" anomaly_detector_lambda.py
zip -j anomaly_detector.zip anomaly_detector_lambda.py
rm anomaly_detector_lambda.py

aws lambda update-function-code \
    --function-name "anomaly-detector" \
    --zip-file "fileb://anomaly_detector.zip" \
    --region "$REGION" > /dev/null
aws lambda wait function-updated --function-name "anomaly-detector" --region "$REGION"
ok "Anomaly detector deployed"

sleep 5

# ══════════════════════════════════════════════════════════════════════════════
# 3. Daily Brief
# ══════════════════════════════════════════════════════════════════════════════
step "Step 3/6: Daily Brief (daily-brief)"

# Handler expects: lambda_function.lambda_handler
rm -f daily_brief.zip
cp "$LAMBDAS_DIR/daily_brief_lambda.py" lambda_function.py
zip -j daily_brief.zip lambda_function.py
rm lambda_function.py

aws lambda update-function-code \
    --function-name "daily-brief" \
    --zip-file "fileb://daily_brief.zip" \
    --region "$REGION" > /dev/null
aws lambda wait function-updated --function-name "daily-brief" --region "$REGION"
ok "Daily brief deployed"

sleep 5

# ══════════════════════════════════════════════════════════════════════════════
# 4. Weekly Digest
# ══════════════════════════════════════════════════════════════════════════════
step "Step 4/6: Weekly Digest (weekly-digest)"

# Handler expects: weekly_digest_lambda.lambda_handler
rm -f weekly_digest.zip
cp "$LAMBDAS_DIR/weekly_digest_lambda.py" weekly_digest_lambda.py
zip -j weekly_digest.zip weekly_digest_lambda.py
rm weekly_digest_lambda.py

aws lambda update-function-code \
    --function-name "weekly-digest" \
    --zip-file "fileb://weekly_digest.zip" \
    --region "$REGION" > /dev/null
aws lambda wait function-updated --function-name "weekly-digest" --region "$REGION"
ok "Weekly digest deployed"

sleep 5

# ══════════════════════════════════════════════════════════════════════════════
# 5. Monthly Digest
# ══════════════════════════════════════════════════════════════════════════════
step "Step 5/6: Monthly Digest (monthly-digest)"

# Handler expects: lambda_function.lambda_handler
rm -f monthly_digest.zip
cp "$LAMBDAS_DIR/monthly_digest_lambda.py" lambda_function.py
zip -j monthly_digest.zip lambda_function.py
rm lambda_function.py

aws lambda update-function-code \
    --function-name "monthly-digest" \
    --zip-file "fileb://monthly_digest.zip" \
    --region "$REGION" > /dev/null
aws lambda wait function-updated --function-name "monthly-digest" --region "$REGION"
ok "Monthly digest deployed"

sleep 5

# ══════════════════════════════════════════════════════════════════════════════
# 6. Wednesday Chronicle
# ══════════════════════════════════════════════════════════════════════════════
step "Step 6/6: Wednesday Chronicle (wednesday-chronicle)"

# Handler expects: lambda_function.lambda_handler
rm -f wednesday_chronicle.zip
cp "$LAMBDAS_DIR/wednesday_chronicle_lambda.py" lambda_function.py
zip -j wednesday_chronicle.zip lambda_function.py
rm lambda_function.py

aws lambda update-function-code \
    --function-name "wednesday-chronicle" \
    --zip-file "fileb://wednesday_chronicle.zip" \
    --region "$REGION" > /dev/null
aws lambda wait function-updated --function-name "wednesday-chronicle" --region "$REGION"
ok "Wednesday chronicle deployed"

# ══════════════════════════════════════════════════════════════════════════════
# 7. Update DynamoDB Profile — sleep SOT
# ══════════════════════════════════════════════════════════════════════════════
step "Step 7: Update DynamoDB profile source-of-truth"

# Update the profile's source_of_truth.sleep from "eightsleep" to "whoop"
# and add sleep_environment → eightsleep
aws dynamodb update-item \
    --table-name "life-platform" \
    --key '{"pk":{"S":"USER#matthew"},"sk":{"S":"PROFILE#v1"}}' \
    --update-expression "SET source_of_truth.sleep = :whoop, source_of_truth.sleep_environment = :es" \
    --expression-attribute-values '{":whoop":{"S":"whoop"},":es":{"S":"eightsleep"}}' \
    --region "$REGION" > /dev/null

ok "DynamoDB profile updated: sleep→whoop, sleep_environment→eightsleep"

# ══════════════════════════════════════════════════════════════════════════════
# CLEANUP
# ══════════════════════════════════════════════════════════════════════════════
step "Cleanup"
rm -f anomaly_detector.zip daily_brief.zip weekly_digest.zip monthly_digest.zip wednesday_chronicle.zip anomaly_detector_lambda.py weekly_digest_lambda.py
ok "Temp zips removed (mcp_server.zip kept for reference)"

# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Sleep SOT Redesign — Deployment Complete               ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  ✅ life-platform-mcp     (config + tools_sleep)        ║"
echo "║  ✅ anomaly-detector      (METRICS → whoop sleep)       ║"
echo "║  ✅ daily-brief           (sleep section → Whoop)       ║"
echo "║  ✅ weekly-digest         (sleep analysis → Whoop)      ║"
echo "║  ✅ monthly-digest        (ex_whoop_sleep added)        ║"
echo "║  ✅ wednesday-chronicle   (sleep + environment split)   ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Sleep Duration/Stages/Score  →  Whoop (SOT)            ║"
echo "║  Bed Environment/Temperature  →  Eight Sleep (SOT)      ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "Quick smoke test (MCP):"
echo "  Ask Claude: 'What was my sleep like last week?'"
echo ""
echo "Next daily brief will use Whoop sleep data automatically."
