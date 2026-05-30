#!/bin/bash
# stage_reserved_concurrency.sh — B-01: Reserved concurrency for the 5 hottest Lambdas.
#
# WHY: protects the platform's most-trafficked Lambdas from co-tenant starvation
# when the account-level concurrency limit is hit. Each gets a reserved slot
# pool; the remainder of the account quota is shared across the other 80+ Lambdas.
#
# GATED: this script will REFUSE to run until the AWS account ConcurrentExecutions
# limit has been raised from 10 → 100 (case 177921309700709). The total reserved
# below is 80, and AWS requires UnreservedConcurrentExecutions >= 10, so the limit
# must be ≥ 90 (we target 100 for headroom) before this can apply.
#
# Reversal: `aws lambda delete-function-concurrency --function-name <name>` per Lambda.
# Idempotent: re-running re-applies the same reservations.

set -euo pipefail

REGION="us-west-2"
REQUIRED_LIMIT=90

# (function-name, reserved-concurrency)
ASSIGNMENTS=(
  "life-platform-mcp:30"           # chatty, supports concurrent Claude Desktop sessions
  "life-platform-site-api:20"      # high-volume read endpoint, fast (<300ms)
  "life-platform-site-api-ai:5"    # AI calls are slow (3–20s); intentional throttle
  "daily-brief:5"                  # singleton scheduled, bursty when sending
  "health-auto-export-webhook:20"  # bursty on each phone-sync upload
)
# Total reserved = 80. With limit=100, unreserved=20 (above the 10 minimum).

echo "[B-01] Pre-flight: verifying account ConcurrentExecutions limit >= $REQUIRED_LIMIT..."
LIMIT=$(aws lambda get-account-settings --region "$REGION" \
  --query 'AccountLimit.ConcurrentExecutions' --output text)
if [[ "$LIMIT" -lt "$REQUIRED_LIMIT" ]]; then
  echo "[B-01] BLOCKED: account ConcurrentExecutions limit is $LIMIT (need ≥ $REQUIRED_LIMIT)."
  echo "[B-01] Wait for AWS Support case 177921309700709 to be approved, then re-run."
  exit 2
fi
echo "[B-01] OK — limit is $LIMIT, proceeding."

for entry in "${ASSIGNMENTS[@]}"; do
  fn="${entry%:*}"
  rc="${entry##*:}"
  echo "[B-01] Setting reserved_concurrent_executions=$rc on $fn…"
  aws lambda put-function-concurrency \
    --function-name "$fn" \
    --reserved-concurrent-executions "$rc" \
    --region "$REGION" \
    --output text > /dev/null
  # Tiny pause to avoid throttling the control plane.
  sleep 1
done

echo "[B-01] Applied. Current state:"
for entry in "${ASSIGNMENTS[@]}"; do
  fn="${entry%:*}"
  rc=$(aws lambda get-function-concurrency --function-name "$fn" --region "$REGION" \
    --query 'ReservedConcurrentExecutions' --output text 2>/dev/null || echo "n/a")
  echo "  $fn  → $rc"
done
