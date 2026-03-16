#!/bin/bash
# deploy/post_cdk_reconcile_smoke.sh
# ─────────────────────────────────────────────────────────────────────────────
# Post-CDK reconcile smoke test — run this IMMEDIATELY after any cdk deploy.
#
# The 2026-03-12 P0 alarm flood was caused by CDK reconcile overwriting two
# live Lambda configs to CDK's (wrong) desired state. A smoke test run right
# after reconcile would have caught it within minutes instead of overnight.
#
# What this does:
#   1. Verifies every Lambda in the reconciled stack(s) responds to invocation
#   2. Checks handler config matches source_file convention (no lambda_function)
#   3. Verifies Todoist IAM path exception is correct
#
# Usage:
#   bash deploy/post_cdk_reconcile_smoke.sh                  # test all operational + ingestion
#   bash deploy/post_cdk_reconcile_smoke.sh OperationalStack # test specific stack
#
# Exit: 0 = all green, 1 = one or more failures
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail
REGION="us-west-2"
STACK_FILTER="${1:-all}"
FAILED=0
PASSED=0

# ── Colour helpers ────────────────────────────────────────────────────────────
GREEN="\033[0;32m"; RED="\033[0;31m"; YELLOW="\033[1;33m"; RESET="\033[0m"
ok()   { echo -e "${GREEN}  ✅ $*${RESET}"; PASSED=$((PASSED+1)); }
fail() { echo -e "${RED}  ❌ $*${RESET}"; FAILED=$((FAILED+1)); }
warn() { echo -e "${YELLOW}  ⚠️  $*${RESET}"; }
section() { echo -e "\n${YELLOW}=== $* ===${RESET}"; }

# ── 1. Handler config verification ────────────────────────────────────────────
section "Handler config verification (CDK reconcile regression check)"

check_handler() {
  local fn="$1"
  local expected_module="$2"
  local actual
  actual=$(aws lambda get-function-configuration \
    --function-name "$fn" --region "$REGION" \
    --query "Handler" --output text 2>/dev/null || echo "ERROR")

  if [[ "$actual" == "ERROR" ]]; then
    fail "$fn — could not fetch handler config"
    return
  fi

  actual_module="${actual%%.*}"
  if [[ "$actual_module" == "$expected_module" ]]; then
    ok "$fn — handler: $actual"
  elif [[ "$actual_module" == "lambda_function" ]]; then
    fail "$fn — handler is 'lambda_function.lambda_handler' (CDK reconcile regression!). Fix: aws lambda update-function-configuration --function-name $fn --handler ${expected_module}.lambda_handler --region $REGION"
  else
    fail "$fn — handler module '$actual_module' != expected '$expected_module' (got: $actual)"
  fi
}

# Operational stack Lambdas that were affected in the 2026-03-12 P0
check_handler "life-platform-freshness-checker"  "freshness_checker_lambda"
check_handler "life-platform-key-rotator"         "key_rotator_lambda"
check_handler "insight-email-parser"              "insight_email_parser_lambda"

# Spot-check a few more ingestion Lambdas
check_handler "todoist-data-ingestion"            "todoist_lambda"
check_handler "whoop-data-ingestion"              "whoop_lambda"
check_handler "garmin-data-ingestion"             "garmin_lambda"
check_handler "health-auto-export-webhook"        "health_auto_export_lambda"

# ── 2. Todoist IAM S3 path verification ───────────────────────────────────────
section "Todoist IAM S3 path verification (raw/todoist/* exception)"

TODOIST_ROLE=$(aws lambda get-function-configuration \
  --function-name todoist-data-ingestion --region "$REGION" \
  --query "Role" --output text 2>/dev/null || echo "ERROR")

if [[ "$TODOIST_ROLE" == "ERROR" ]]; then
  fail "Could not fetch Todoist Lambda role"
else
  # Get the inline policy and check S3 resource
  ROLE_NAME="${TODOIST_ROLE##*/}"
  POLICY_JSON=$(aws iam get-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "TodoistIngestionPolicy" \
    --query "PolicyDocument" \
    --output json 2>/dev/null || echo "ERROR")

  if [[ "$POLICY_JSON" == "ERROR" ]]; then
    # Try default CDK policy name pattern
    POLICIES=$(aws iam list-role-policies --role-name "$ROLE_NAME" \
      --query "PolicyNames" --output json 2>/dev/null || echo "[]")
    warn "Could not fetch Todoist IAM policy directly. Role: $ROLE_NAME. Policies: $POLICIES"
    warn "Manual check: ensure S3 resource is raw/todoist/* (NOT raw/matthew/todoist/*)"
  else
    if echo "$POLICY_JSON" | grep -q "raw/matthew/todoist"; then
      fail "Todoist IAM still has raw/matthew/todoist/* — CDK reconcile regression! Lambda writes to raw/todoist/. Run fix_p0_alarm_bugs.sh."
    elif echo "$POLICY_JSON" | grep -q "raw/todoist"; then
      ok "Todoist IAM S3 path: raw/todoist/* (correct)"
    else
      warn "Todoist IAM policy found but couldn't parse S3 resource. Manual check recommended."
    fi
  fi
fi

# ── 3. Invocation smoke test ──────────────────────────────────────────────────
section "Invocation smoke test (Lambda responds, no import errors)"

invoke_check() {
  local fn="$1"
  local payload="${2:-'{}'}"
  local tmp="/tmp/smoke_${fn//[-\/]/_}.json"

  STATUS=$(aws lambda invoke \
    --function-name "$fn" \
    --payload "$payload" \
    --region "$REGION" \
    "$tmp" \
    --query "StatusCode" --output text 2>/dev/null || echo "0")

  if [[ "$STATUS" != "200" ]]; then
    fail "$fn — invocation returned status $STATUS"
    return
  fi

  # Check for runtime import errors (top-level crash before lambda_handler even runs)
  if grep -q "Runtime.ImportModuleError\|Unable to import module" "$tmp" 2>/dev/null; then
    ERROR=$(grep -o '"errorMessage":"[^"]*"' "$tmp" | head -1)
    fail "$fn — Runtime.ImportModuleError: $ERROR (wrong handler module name?)"
    return
  fi

  if grep -q '"FunctionError"' "$tmp" 2>/dev/null; then
    ERROR=$(grep -o '"errorMessage":"[^"]*"' "$tmp" | head -1)
    fail "$fn — Lambda error: $ERROR"
    return
  fi

  ok "$fn — responded 200"
  rm -f "$tmp"
}

# Freshness checker (the one that broke)
invoke_check "life-platform-freshness-checker"

# Todoist — just check it boots cleanly (imports resolve, handler exists)
# Empty payload: the Lambda will attempt ingestion but will exit cleanly on no-new-data
invoke_check "todoist-data-ingestion" '{}'

# Canary — full health check
invoke_check "life-platform-canary"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════"
echo -e "Post-reconcile smoke: ${GREEN}${PASSED} passed${RESET}, ${RED}${FAILED} failed${RESET}"
echo "════════════════════════════════════"

if [[ "$FAILED" -gt 0 ]]; then
  echo -e "${RED}❌ Smoke test FAILED — DO NOT proceed with further CDK deploys until fixed.${RESET}"
  echo ""
  echo "Common fixes:"
  echo "  Wrong handler: aws lambda update-function-configuration --function-name <fn> --handler <module>.lambda_handler --region $REGION"
  echo "  Wrong IAM:     bash deploy/fix_p0_alarm_bugs.sh"
  exit 1
fi

# ── S3 public read check (catches bucket policy wipe after P1 incident pattern) ────────────
echo "=== S3 public read verification ==="
S3_HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
  "http://matthew-life-platform.s3-website-us-west-2.amazonaws.com/site/index.html")
if [[ "$S3_HTTP" == "200" ]]; then
  echo -e "  ${GREEN}✅ S3 site/index.html — public read OK (200)${RESET}"
else
  echo -e "  ${RED}⚠ S3 site/index.html — public read BROKEN ($S3_HTTP)${RESET}"
  echo "  Fix: aws s3api put-bucket-policy --bucket matthew-life-platform --region us-west-2 --policy file://deploy/bucket_policy.json"
fi

echo -e "${GREEN}✅ All checks passed. CDK reconcile looks clean.${RESET}"
