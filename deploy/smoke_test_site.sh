#!/usr/bin/env bash
# smoke_test_site.sh — Verify averagejoematt.com is live and healthy
#
# Run after deploy_web_stack.sh + point_route53_to_cloudfront.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

BASE="https://averagejoematt.com"
PASS=0
FAIL=0

check() {
  local label="$1"
  local url="$2"
  local expected_status="${3:-200}"

  status=$(curl -s -o /dev/null -w "%{http_code}" "$url")
  if [[ "$status" == "$expected_status" ]]; then
    echo "  ✅ $label ($status)"
    ((PASS++))
  else
    echo "  ❌ $label — expected $expected_status, got $status ($url)"
    ((FAIL++))
  fi
}

echo "=== averagejoematt.com smoke tests ==="
echo ""

echo "Static pages:"
check "Homepage"       "$BASE/"
check "Platform"       "$BASE/platform/"
check "Character"      "$BASE/character/"
check "Journal"        "$BASE/journal/"
check "www redirect"   "https://www.averagejoematt.com/" 200

echo ""
echo "API endpoints:"
check "/api/status"    "$BASE/api/status"
check "/api/vitals"    "$BASE/api/vitals"
check "/api/journey"   "$BASE/api/journey"
check "/api/character" "$BASE/api/character"

echo ""
echo "API response quality:"
VITALS=$(curl -s "$BASE/api/vitals")
if echo "$VITALS" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('vitals',{}).get('weight_lbs') is not None" 2>/dev/null; then
  echo "  ✅ /api/vitals returns weight_lbs"
  ((PASS++))
else
  echo "  ❌ /api/vitals missing weight_lbs — check site_api_lambda DynamoDB query"
  ((FAIL++))
fi

echo ""
echo "Headers:"
CF_HEADER=$(curl -s -I "$BASE/" | grep -i "x-cache" | head -1 || echo "none")
echo "  CloudFront: $CF_HEADER"

echo ""
echo "──────────────────────────────────"
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]] && echo "✅ All checks passed — site is live." || echo "❌ $FAIL check(s) failed."
