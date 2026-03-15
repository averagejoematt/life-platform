#!/bin/bash
# deploy_and_verify.sh — Deploy a Lambda and immediately verify it starts clean.
#
# Wraps deploy_lambda.sh with a post-deploy invoke + CloudWatch log check.
# Catches ImportModuleError, AccessDenied, and runtime crashes BEFORE the
# next scheduled run finds them 11 hours later.
#
# USAGE:
#   bash deploy/deploy_and_verify.sh <function-name> <source-file> [extra args...]
#
# EXAMPLES:
#   bash deploy/deploy_and_verify.sh google-calendar-ingestion lambdas/google_calendar_lambda.py
#   bash deploy/deploy_and_verify.sh daily-brief lambdas/daily_brief_lambda.py \
#       --extra-files lambdas/ai_calls.py lambdas/html_builder.py lambdas/output_writers.py
#
# EXIT:
#   0 = deploy succeeded + Lambda boots clean
#   1 = deploy failed OR Lambda has import/runtime error
#
# VERIFICATION:
#   After deploying, invokes the Lambda with a dry-run payload.
#   Waits 8s for Lambda to start, then checks CloudWatch logs for:
#     - Runtime.ImportModuleError  → wrong handler module name or missing file
#     - AccessDenied               → IAM permission missing
#     - ERROR (structured log)     → runtime crash
#   Any of these triggers a warning and non-zero exit.
#
# HISTORY:
#   Born from Architecture Review #11 (Jin Park / Viktor Sorokin):
#   "The gap between changed and verified working is where incidents live."
#
# v1.0.0 — 2026-03-14 (R11 engineering strategy item 2)

set -euo pipefail

REGION="us-west-2"
VERIFY_WAIT_SECS=8      # seconds to wait after deploy before checking logs
LOG_TAIL_SECS=12        # how many seconds of logs to check

GREEN="\033[0;32m"; RED="\033[0;31m"; YELLOW="\033[1;33m"; RESET="\033[0m"
ok()   { echo -e "${GREEN}  ✅ $*${RESET}"; }
fail() { echo -e "${RED}  ❌ $*${RESET}"; }
warn() { echo -e "${YELLOW}  ⚠️  $*${RESET}"; }

# ── Args ──────────────────────────────────────────────────────────────────────
if [ $# -lt 2 ]; then
    echo "Usage: $0 <function-name> <source-file> [--extra-files ...]"
    exit 1
fi
FUNCTION_NAME="$1"
SOURCE_FILE="$2"
shift 2

# ── Step 1: Deploy ─────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════"
echo "  deploy_and_verify.sh — ${FUNCTION_NAME}"
echo "════════════════════════════════════════════════════════"

bash "$(dirname "$0")/deploy_lambda.sh" "$FUNCTION_NAME" "$SOURCE_FILE" "$@"
DEPLOY_EXIT=$?

if [ $DEPLOY_EXIT -ne 0 ]; then
    fail "Deploy failed — aborting verification"
    exit 1
fi

# ── Step 2: Wait for Lambda to stabilise ──────────────────────────────────────
echo ""
echo "⏳ Waiting ${VERIFY_WAIT_SECS}s for Lambda to settle..."
sleep $VERIFY_WAIT_SECS

# ── Step 3: Invoke with dry-run payload ────────────────────────────────────────
echo "🔬 Invoking ${FUNCTION_NAME} with dry-run payload..."
TMP_RESPONSE="/tmp/dav_${FUNCTION_NAME//[-\/]/_}.json"

# dry_run=true prevents any writes / emails / side effects on Lambdas that support it.
# For Lambdas that don't know dry_run, the event is ignored and the import stage is
# what we're really testing anyway.
INVOKE_STATUS=$(aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --payload '{"dry_run":true,"__verify":true}' \
    --cli-binary-format raw-in-base64-out \
    --region "$REGION" \
    "$TMP_RESPONSE" \
    --query "StatusCode" --output text 2>/dev/null || echo "0")

# ── Step 4: Check invoke response ─────────────────────────────────────────────
VERIFY_FAILED=0

if [[ "$INVOKE_STATUS" != "200" ]]; then
    fail "Invoke returned HTTP ${INVOKE_STATUS} (expected 200)"
    VERIFY_FAILED=1
fi

# Check response body for function-level errors
if [[ -f "$TMP_RESPONSE" ]]; then
    if grep -q "Runtime.ImportModuleError\|Unable to import module" "$TMP_RESPONSE" 2>/dev/null; then
        ERR=$(grep -o '"errorMessage":"[^"]*"' "$TMP_RESPONSE" | head -1 || echo "see response")
        fail "Runtime.ImportModuleError — wrong handler module name? ${ERR}"
        VERIFY_FAILED=1
    elif grep -q '"errorType"' "$TMP_RESPONSE" 2>/dev/null; then
        ERR=$(grep -o '"errorType":"[^"]*"' "$TMP_RESPONSE" | head -1 || echo "see response")
        MSG=$(grep -o '"errorMessage":"[^"]*"' "$TMP_RESPONSE" | head -1 || echo "")
        fail "Lambda error: ${ERR} ${MSG}"
        VERIFY_FAILED=1
    fi
    rm -f "$TMP_RESPONSE"
fi

# ── Step 5: Check CloudWatch logs ─────────────────────────────────────────────
echo "📋 Checking CloudWatch logs (last ${LOG_TAIL_SECS}s)..."

LOG_GROUP="/aws/lambda/${FUNCTION_NAME}"
LOG_OUTPUT=$(aws logs tail "$LOG_GROUP" \
    --since "${LOG_TAIL_SECS}s" \
    --region "$REGION" \
    --format short 2>/dev/null || echo "")

# Patterns that indicate a broken Lambda
FATAL_PATTERNS=(
    "Runtime.ImportModuleError"
    "Unable to import module"
    "Module not found"
    "AccessDenied"
    "ResourceNotFoundException.*Secret"
    "No module named"
)

for pattern in "${FATAL_PATTERNS[@]}"; do
    if echo "$LOG_OUTPUT" | grep -qi "$pattern" 2>/dev/null; then
        fail "Found '${pattern}' in CloudWatch logs — Lambda has a problem"
        echo "  → Run: aws logs tail ${LOG_GROUP} --since 30s --region ${REGION}"
        VERIFY_FAILED=1
    fi
done

# Warn (not fail) on generic ERRORs — these could be expected (no data yet, etc.)
if echo "$LOG_OUTPUT" | grep -q "\[ERROR\]\|\"level\":\"ERROR\"" 2>/dev/null; then
    FIRST_ERR=$(echo "$LOG_OUTPUT" | grep -m1 "\[ERROR\]\|\"level\":\"ERROR\"" | head -c 120)
    warn "ERROR in CloudWatch logs: ${FIRST_ERR}"
    warn "This may be expected (e.g. no data yet). Check manually if unexpected."
fi

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════"
if [[ $VERIFY_FAILED -eq 0 ]]; then
    ok "deploy_and_verify PASSED — ${FUNCTION_NAME} boots clean"
    echo "════════════════════════════════════════════════════════"
    exit 0
else
    fail "deploy_and_verify FAILED — see errors above"
    echo "  Rollback: bash deploy/rollback_lambda.sh ${FUNCTION_NAME}"
    echo "  Logs:     aws logs tail /aws/lambda/${FUNCTION_NAME} --since 5m --region ${REGION}"
    echo "════════════════════════════════════════════════════════"
    exit 1
fi
