#!/bin/bash
# p0_verify.sh — Verify all P0 items are complete
#
# Usage: cd ~/Documents/Claude/life-platform && bash deploy/p0_verify.sh

REGION="us-west-2"
PASS=0
FAIL=0

check() {
    local label="$1"
    local result="$2"
    local expected="$3"
    if echo "$result" | grep -q "$expected"; then
        echo "  ✅ $label"
        PASS=$((PASS + 1))
    else
        echo "  ❌ $label (got: $result)"
        FAIL=$((FAIL + 1))
    fi
}

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  P0 Verification                                            ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Check 1: ai-keys secret exists ────────────────────────────────────────────
echo "── Check 1: life-platform/ai-keys secret ──"
SECRET_STATUS=$(aws secretsmanager describe-secret \
    --secret-id "life-platform/ai-keys" \
    --region "$REGION" \
    --query "Name" --output text --no-cli-pager 2>/dev/null || echo "NOT_FOUND")
check "Secret life-platform/ai-keys exists" "$SECRET_STATUS" "ai-keys"
echo ""

# ── Check 2: ANTHROPIC_SECRET env var on AI Lambdas ───────────────────────────
echo "── Check 2: ANTHROPIC_SECRET env var on AI Lambdas ──"
for fn in "daily-brief" "weekly-digest" "hypothesis-engine" "anomaly-detector" "monday-compass"; do
    VAL=$(aws lambda get-function-configuration \
        --function-name "$fn" --region "$REGION" \
        --query "Environment.Variables.ANTHROPIC_SECRET" \
        --output text --no-cli-pager 2>/dev/null || echo "NOT_FOUND")
    check "$fn ANTHROPIC_SECRET=ai-keys" "$VAL" "ai-keys"
done
echo ""

# ── Check 3: 3 scoped IAM roles exist ─────────────────────────────────────────
echo "── Check 3: Scoped IAM roles exist ──"
for role in "life-platform-compute-role" "life-platform-email-role" "life-platform-digest-role"; do
    ROLE_STATUS=$(aws iam get-role --role-name "$role" \
        --query "Role.RoleName" --output text --no-cli-pager 2>/dev/null || echo "NOT_FOUND")
    check "Role $role exists" "$ROLE_STATUS" "$role"
done
echo ""

# ── Check 4: Lambda role assignments ──────────────────────────────────────────
echo "── Check 4: Lambda role assignments ──"
check_lambda_role() {
    local fn="$1"
    local expected="$2"
    local actual
    actual=$(aws lambda get-function-configuration \
        --function-name "$fn" --region "$REGION" \
        --query "Role" --output text --no-cli-pager 2>/dev/null | sed 's|.*role/||' || echo "NOT_FOUND")
    check "$fn uses $expected" "$actual" "$expected"
}
check_lambda_role "daily-brief"             "email-role"
check_lambda_role "weekly-digest"           "digest-role"
check_lambda_role "monthly-digest"          "digest-role"
check_lambda_role "hypothesis-engine"       "compute-role"
check_lambda_role "daily-insight-compute"   "compute-role"
check_lambda_role "character-sheet-compute" "compute-role"
echo ""

# ── Summary ────────────────────────────────────────────────────────────────────
TOTAL=$((PASS + FAIL))
echo "══════════════════════════════════════════════════════════════"
echo "  Results: $PASS/$TOTAL passed"
if [ "$FAIL" -eq 0 ]; then
    echo "  ✅ All P0 checks passed — platform hardened"
else
    echo "  ⚠️  $FAIL check(s) failed — review above"
fi
echo "══════════════════════════════════════════════════════════════"
