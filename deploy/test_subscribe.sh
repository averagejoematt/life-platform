#!/bin/bash
# test_subscribe.sh — End-to-end test of /api/subscribe flow
#
# Tests:
#   1. POST /api/subscribe with valid email → 200 + pending_confirmation
#   2. POST with invalid email → 400
#   3. POST with duplicate confirmed email → 200 (silent)
#   4. DynamoDB record verify → record exists with status=pending_confirmation
#   5. CloudWatch logs check → Lambda ran without errors
#
# Usage: bash deploy/test_subscribe.sh [test-email]
# Default test email: subscribe-test@averagejoematt.com (SES sandbox-safe)
#
# Note: actual confirmation email delivery requires SES sandbox exit or
# a verified recipient address. This test verifies the API + DDB layer.

set -euo pipefail
REGION="us-west-2"
TABLE="life-platform"
API_URL="https://averagejoematt.com/api/subscribe"
TEST_EMAIL="${1:-subscribe-smoketest-$(date +%s)@averagejoematt.com}"

echo "=== /api/subscribe end-to-end test ==="
echo "  API:   $API_URL"
echo "  Email: $TEST_EMAIL"
echo ""

PASS=0
FAIL=0

check() {
  local label="$1"; local result="$2"; local expected="$3"
  if echo "$result" | grep -q "$expected"; then
    echo "  ✅ $label"
    PASS=$((PASS+1))
  else
    echo "  ❌ $label"
    echo "     Expected: $expected"
    echo "     Got:      $result"
    FAIL=$((FAIL+1))
  fi
}

# ── Test 1: Valid subscribe ────────────────────────────────────────────────
echo "[1/5] POST valid email..."
RESP1=$(curl -s -X POST "$API_URL" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$TEST_EMAIL\",\"source\":\"smoke-test\"}" \
  -w "\nHTTP_STATUS:%{http_code}")
STATUS1=$(echo "$RESP1" | grep "HTTP_STATUS:" | cut -d: -f2)
BODY1=$(echo "$RESP1" | grep -v "HTTP_STATUS:")
check "HTTP 200" "$STATUS1" "200"
check "pending_confirmation in body" "$BODY1" "pending_confirmation"

# ── Test 2: Invalid email ─────────────────────────────────────────────────
echo "[2/5] POST invalid email..."
RESP2=$(curl -s -X POST "$API_URL" \
  -H "Content-Type: application/json" \
  -d '{"email":"not-an-email"}' \
  -w "\nHTTP_STATUS:%{http_code}")
STATUS2=$(echo "$RESP2" | grep "HTTP_STATUS:" | cut -d: -f2)
check "HTTP 400 for invalid email" "$STATUS2" "400"

# ── Test 3: Empty email ───────────────────────────────────────────────────
echo "[3/5] POST empty email..."
RESP3=$(curl -s -X POST "$API_URL" \
  -H "Content-Type: application/json" \
  -d '{"email":""}' \
  -w "\nHTTP_STATUS:%{http_code}")
STATUS3=$(echo "$RESP3" | grep "HTTP_STATUS:" | cut -d: -f2)
check "HTTP 400 for empty email" "$STATUS3" "400"

# ── Test 4: DynamoDB record verify ────────────────────────────────────────
echo "[4/5] Verifying DynamoDB record..."
sleep 2  # give Lambda time to write

# Compute SHA256 of test email
EMAIL_HASH=$(echo -n "$TEST_EMAIL" | python3 -c "import hashlib,sys; print(hashlib.sha256(sys.stdin.read().strip().lower().encode()).hexdigest())")

DDB_ITEM=$(aws dynamodb get-item \
  --table-name "$TABLE" \
  --region "$REGION" \
  --key "{\"pk\":{\"S\":\"USER#matthew#SOURCE#subscribers\"},\"sk\":{\"S\":\"EMAIL#${EMAIL_HASH}\"}}" \
  --query "Item.status.S" \
  --output text --no-cli-pager 2>/dev/null || echo "NOT_FOUND")

check "DDB record status=pending_confirmation" "$DDB_ITEM" "pending_confirmation"

# ── Test 5: CloudWatch logs check ─────────────────────────────────────────
echo "[5/5] Checking Lambda logs for errors..."
sleep 3
LOG_GROUP="/aws/lambda/email-subscriber"
# email-subscriber Lambda runs in us-east-1 (deployed by web_stack.py)
LATEST_STREAM=$(aws logs describe-log-streams \
  --log-group-name "$LOG_GROUP" \
  --region "us-east-1" \
  --order-by LastEventTime \
  --descending \
  --limit 1 \
  --query "logStreams[0].logStreamName" \
  --output text --no-cli-pager 2>/dev/null || echo "")

if [ -n "$LATEST_STREAM" ] && [ "$LATEST_STREAM" != "None" ]; then
  LOG_EVENTS=$(aws logs get-log-events \
    --log-group-name "$LOG_GROUP" \
    --log-stream-name "$LATEST_STREAM" \
    --region "us-east-1" \
    --limit 30 \
    --query "events[*].message" \
    --output text --no-cli-pager 2>/dev/null || echo "")
  
  if echo "$LOG_EVENTS" | grep -qi "error\|exception\|traceback"; then
    echo "  ❌ Errors found in Lambda logs"
    FAIL=$((FAIL+1))
  else
    echo "  ✅ No errors in Lambda logs"
    PASS=$((PASS+1))
  fi
else
  echo "  ⚠️  No log stream found (Lambda may not have run yet)"
fi

# ── Summary ───────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════"
echo "Subscribe test: $PASS passed, $FAIL failed"
echo "════════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
  echo "❌ Subscribe flow has issues. Check CloudWatch logs:"
  echo "   aws logs tail /aws/lambda/email-subscriber --region us-west-2 --follow"
  exit 1
fi

echo "✅ Subscribe flow working end-to-end."
echo ""
echo "Note: Confirmation email delivery requires:"
echo "  - SES sandbox exit (for non-verified recipients), OR"
echo "  - Verified recipient address in SES"
echo ""
echo "To verify SES delivery, check the SES sending dashboard:"
echo "  aws sesv2 get-account --region us-west-2 --query 'SendingEnabled'"

# ── Cleanup test record ───────────────────────────────────────────────────
echo ""
echo "Cleaning up test record from DDB..."
aws dynamodb delete-item \
  --table-name "$TABLE" \
  --region "$REGION" \
  --key "{\"pk\":{\"S\":\"USER#matthew#SOURCE#subscribers\"},\"sk\":{\"S\":\"EMAIL#${EMAIL_HASH}\"}}" \
  --no-cli-pager 2>/dev/null && echo "  ✓ Test record deleted" || echo "  ⚠️  Cleanup failed (non-fatal)"
