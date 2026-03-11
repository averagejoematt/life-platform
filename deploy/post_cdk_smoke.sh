#!/usr/bin/env bash
# deploy/post_cdk_smoke.sh — Post-CDK deploy smoke test
#
# Runs after any `cdk deploy` to verify the platform is healthy.
# Catches env-var wipeouts, TLS bugs, and Lambda error state before
# they surface in production emails.
#
# Tests:
#   1. CloudFront HTTPS + TLS + redirect (delegates to smoke_test_cloudfront.sh)
#   2. Lambda error state — all email + compute Lambdas
#   3. MCP warm ping — invokes a cached tool to confirm the intelligence layer
#
# Usage:
#   bash deploy/post_cdk_smoke.sh                         # all checks
#   bash deploy/post_cdk_smoke.sh --skip-mcp              # skip MCP call (no API key needed)
#   bash deploy/post_cdk_smoke.sh --stack LifePlatformEmail  # Lambda checks scoped to stack
#
# Exit codes:  0 = all pass | 1 = one or more failures
#
# v1.0.0 — 2026-03-10 (Item 1, board review sprint v3.5.0)

set -euo pipefail

REGION="us-west-2"
SKIP_MCP=false
STACK_FILTER=""

# ── Parse args ────────────────────────────────────────────────────────────────
for arg in "$@"; do
  case "$arg" in
    --skip-mcp) SKIP_MCP=true ;;
    --stack) STACK_FILTER="${2:-}" ;;
  esac
done

PASS=0
FAIL=0
WARN=0
results=()

# ── Helpers ───────────────────────────────────────────────────────────────────
green() { echo -e "\033[32m$*\033[0m"; }
red()   { echo -e "\033[31m$*\033[0m"; }
yellow(){ echo -e "\033[33m$*\033[0m"; }

check() {
  local name="$1" result="$2"
  if [[ "$result" == "pass" ]]; then
    green "  [PASS]  $name"
    results+=("[PASS] $name")
    PASS=$((PASS + 1))
  elif [[ "$result" == warn:* ]]; then
    yellow "  [WARN]  $name"
    yellow "          ${result#warn:}"
    results+=("[WARN] $name — ${result#warn:}")
    WARN=$((WARN + 1))
  else
    red "  [FAIL]  $name"
    red "          $result"
    results+=("[FAIL] $name — $result")
    FAIL=$((FAIL + 1))
  fi
}

# ── Section 1: CloudFront ─────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════════════"
echo " Section 1/3 — CloudFront HTTPS smoke test"
echo "══════════════════════════════════════════════════════════════"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$SCRIPT_DIR/smoke_test_cloudfront.sh" ]]; then
  if bash "$SCRIPT_DIR/smoke_test_cloudfront.sh"; then
    check "CloudFront suite" "pass"
  else
    check "CloudFront suite" "fail: one or more CloudFront checks failed (see above)"
  fi
else
  check "CloudFront suite" "warn:smoke_test_cloudfront.sh not found — skipping"
fi

# ── Section 2: Lambda error state ─────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════════════"
echo " Section 2/3 — Lambda error state (last 5 min)"
echo "══════════════════════════════════════════════════════════════"

# All email + compute Lambdas — the ones CDK touches on EmailStack / ComputeStack
EMAIL_LAMBDAS=(
  "daily-brief"
  "weekly-digest"
  "monthly-digest"
  "nutrition-review"
  "wednesday-chronicle"
  "weekly-plate"
  "monday-compass"
  "brittany-weekly-email"
)
COMPUTE_LAMBDAS=(
  "anomaly-detector"
  "character-sheet-compute"
  "daily-metrics-compute"
  "daily-insight-compute"
  "adaptive-mode-compute"
  "hypothesis-engine"
  "failure-pattern-compute"
)

check_lambda_state() {
  local fn="$1"
  local state config last_update last_status

  # get-function-configuration: check State, LastUpdateStatus
  config=$(aws lambda get-function-configuration \
    --function-name "$fn" \
    --region "$REGION" \
    --output json 2>&1) || {
    check "$fn: reachable" "fail: aws lambda get-function-configuration failed: $config"
    return
  }

  state=$(echo "$config" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('State','Unknown'))")
  last_status=$(echo "$config" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('LastUpdateStatus','Unknown'))")

  if [[ "$state" != "Active" ]]; then
    check "$fn: State=$state" "fail: Lambda not Active (State=$state)"
    return
  fi
  if [[ "$last_status" == "Failed" ]]; then
    reason=$(echo "$config" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('LastUpdateStatusReasonCode','?'))" 2>/dev/null || echo "?")
    check "$fn: LastUpdateStatus" "fail: LastUpdateStatus=Failed (reason: $reason)"
    return
  fi

  # Check CloudWatch errors in last 5 minutes
  NOW=$(date -u +%s)
  START=$((NOW - 300))
  START_ISO=$(python3 -c "import datetime; print(datetime.datetime.utcfromtimestamp($START).strftime('%Y-%m-%dT%H:%M:%SZ'))")
  END_ISO=$(python3 -c "import datetime; print(datetime.datetime.utcfromtimestamp($NOW).strftime('%Y-%m-%dT%H:%M:%SZ'))")

  errors=$(aws cloudwatch get-metric-statistics \
    --region "$REGION" \
    --namespace "AWS/Lambda" \
    --metric-name "Errors" \
    --dimensions "Name=FunctionName,Value=$fn" \
    --start-time "$START_ISO" \
    --end-time "$END_ISO" \
    --period 300 \
    --statistics Sum \
    --output json 2>/dev/null | \
    python3 -c "import json,sys; d=json.load(sys.stdin); pts=d.get('Datapoints',[]); print(int(sum(p['Sum'] for p in pts)))" 2>/dev/null || echo "0")

  if [[ "$errors" -gt 0 ]]; then
    check "$fn" "fail: $errors error(s) in last 5 minutes"
  else
    check "$fn: State=Active, no recent errors" "pass"
  fi
}

echo "  Checking email Lambdas..."
for fn in "${EMAIL_LAMBDAS[@]}"; do
  check_lambda_state "$fn"
done

echo ""
echo "  Checking compute Lambdas..."
for fn in "${COMPUTE_LAMBDAS[@]}"; do
  check_lambda_state "$fn"
done

# ── Section 3: MCP intelligence layer warm ping ───────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════════════"
echo " Section 3/3 — MCP intelligence layer warm ping"
echo "══════════════════════════════════════════════════════════════"

if [[ "$SKIP_MCP" == "true" ]]; then
  echo "  Skipped (--skip-mcp flag set)"
  WARN=$((WARN + 1))
  results+=("[WARN] MCP ping — skipped by flag")
else
  MCP_FN="life-platform-mcp"
  # Invoke get_health_dashboard (cached tool) — minimal payload, confirms tool layer intact
  PAYLOAD='{"jsonrpc":"2.0","method":"tools/call","params":{"name":"get_health_dashboard","arguments":{}},"id":1}'
  ENCODED_PAYLOAD=$(echo -n "$PAYLOAD" | base64)

  MCP_RESPONSE=$(aws lambda invoke \
    --function-name "$MCP_FN" \
    --region "$REGION" \
    --payload "$ENCODED_PAYLOAD" \
    --cli-binary-format raw-in-base64-out \
    /tmp/mcp_smoke_response.json \
    --output json 2>&1) || {
    check "MCP Lambda invocable" "fail: aws lambda invoke failed: $MCP_RESPONSE"
    MCP_RESPONSE=""
  }

  if [[ -n "$MCP_RESPONSE" ]]; then
    STATUS_CODE=$(echo "$MCP_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('StatusCode',0))" 2>/dev/null || echo "0")
    FUNC_ERROR=$(echo "$MCP_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('FunctionError',''))" 2>/dev/null || echo "")

    if [[ "$STATUS_CODE" == "200" ]] && [[ -z "$FUNC_ERROR" ]]; then
      # Check response contains expected MCP structure
      RESP_CONTENT=$(cat /tmp/mcp_smoke_response.json 2>/dev/null || echo "")
      if echo "$RESP_CONTENT" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert 'result' in d or 'error' in d" 2>/dev/null; then
        check "MCP Lambda: invocable + returns valid JSON-RPC" "pass"
      else
        check "MCP Lambda" "warn:invoked but response structure unexpected — check MCP logs"
      fi
    else
      check "MCP Lambda" "fail: StatusCode=$STATUS_CODE FunctionError=$FUNC_ERROR"
    fi
    rm -f /tmp/mcp_smoke_response.json
  fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════════════"
echo " Post-CDK Smoke Test Results: ${PASS} pass | ${WARN} warn | ${FAIL} fail"
echo "══════════════════════════════════════════════════════════════"

if [[ $FAIL -gt 0 ]]; then
  echo ""
  red "FAILED checks:"
  for r in "${results[@]}"; do
    if [[ "$r" == \[FAIL\]* ]]; then
      red "  $r"
    fi
  done
  echo ""
  red "⛔  Deploy smoke test FAILED. Investigate before considering deploy complete."
  exit 1
elif [[ $WARN -gt 0 ]]; then
  echo ""
  yellow "WARNINGS (non-blocking):"
  for r in "${results[@]}"; do
    if [[ "$r" == \[WARN\]* ]]; then
      yellow "  $r"
    fi
  done
  echo ""
  yellow "⚠️   Deploy smoke test passed with warnings."
  exit 0
else
  echo ""
  green "✅  All checks passed. Deploy is healthy."
  exit 0
fi
