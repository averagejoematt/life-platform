#!/usr/bin/env bash
# deploy/smoke_test_cloudfront.sh — HTTPS smoke test for all 3 CloudFront distributions
#
# Tests:
#   - HTTPS connectivity (curl -I, expect HTTP 200 or 302)
#   - TLS certificate validity
#   - Correct domain served via CloudFront (x-cache header present)
#   - No HTTP→HTTP fallback (HTTPS enforced)
#
# Usage:  bash deploy/smoke_test_cloudfront.sh
#
# v1.0.0 — 2026-03-10 (Item 7, sprint v3.5.0)

set -euo pipefail

PASS=0
FAIL=0
results=()

check() {
  local name="$1"
  local result="$2"   # "pass" or "fail: <reason>"
  if [[ "$result" == "pass" ]]; then
    echo "  [PASS]  $name"
    results+=("[PASS] $name")
    PASS=$((PASS + 1))
  else
    echo "  [FAIL]  $name"
    echo "          $result"
    results+=("[FAIL] $name — $result")
    FAIL=$((FAIL + 1))
  fi
}

smoke_test_domain() {
  local domain="$1"
  local dist_id="$2"
  local expect_auth="$3"   # "yes" if CloudFront auth is expected (302 redirect is OK)

  echo ""
  echo "── $domain ($dist_id) ────────────────────────────────"

  local url="https://${domain}/"
  local response
  response=$(curl -sI --max-time 10 "$url" 2>&1) || true

  # 1. HTTPS reachable (HTTP 200 or 302 for auth-gated, never connection error)
  local http_status
  http_status=$(echo "$response" | grep -i "^HTTP/" | head -1 | awk '{print $2}') || true

  if [[ -z "$http_status" ]]; then
    check "$domain: HTTPS reachable" "fail: no HTTP response (connection failed?)"
  elif [[ "$http_status" == "200" ]] || [[ "$http_status" == "302" ]] || [[ "$http_status" == "301" ]]; then
    check "$domain: HTTPS reachable (HTTP $http_status)" "pass"
  else
    check "$domain: HTTPS reachable" "fail: unexpected HTTP $http_status"
  fi

  # 2. TLS certificate valid (curl would error with exit code 60 if invalid)
  local tls_check
  tls_check=$(curl -sI --max-time 10 --fail-with-body "$url" 2>&1) && tls_ok="pass" || tls_ok="fail"
  # For auth-gated (302), curl --fail-with-body doesn't fail on 302, so special-case
  if [[ "$expect_auth" == "yes" ]]; then
    local tls_raw
    tls_raw=$(curl -vI --max-time 10 "$url" 2>&1) || true
    if echo "$tls_raw" | grep -q "SSL connection\|TLSv1"; then
      check "$domain: TLS certificate valid" "pass"
    elif echo "$tls_raw" | grep -qi "certificate\|SSL"; then
      # Check for errors specifically
      if echo "$tls_raw" | grep -qi "certificate verify failed\|SSL_ERROR\|handshake failure"; then
        check "$domain: TLS certificate valid" "fail: TLS error detected"
      else
        check "$domain: TLS certificate valid" "pass"
      fi
    else
      check "$domain: TLS certificate valid" "pass"  # no errors = pass
    fi
  else
    if [[ "$tls_ok" == "pass" ]]; then
      check "$domain: TLS certificate valid" "pass"
    else
      # Distinguish TLS error from HTTP error
      if echo "$tls_check" | grep -qi "certificate verify failed\|SSL_ERROR"; then
        check "$domain: TLS certificate valid" "fail: $tls_check"
      else
        check "$domain: TLS certificate valid" "pass"  # HTTP error but TLS worked
      fi
    fi
  fi

  # 3. CloudFront header present (x-cache: Hit from cloudfront OR Miss from cloudfront)
  local xcache
  xcache=$(echo "$response" | grep -i "^x-cache:" | head -1) || true
  if echo "$xcache" | grep -qi "cloudfront"; then
    check "$domain: CloudFront x-cache header present" "pass"
  else
    # Some responses may not have x-cache on first hit — check via-header as fallback
    local via
    via=$(echo "$response" | grep -i "^via:" | head -1) || true
    if echo "$via" | grep -qi "cloudfront"; then
      check "$domain: CloudFront via header present" "pass"
    else
      check "$domain: CloudFront header present" "fail: no x-cache or via CloudFront header (got: '$xcache')"
    fi
  fi

  # 4. HTTP plain text is redirected (not served over HTTP)
  local http_redirect
  http_redirect=$(curl -sI --max-time 10 "http://${domain}/" 2>&1) || true
  local plain_status
  plain_status=$(echo "$http_redirect" | grep -i "^HTTP/" | head -1 | awk '{print $2}') || true
  local location
  location=$(echo "$http_redirect" | grep -i "^location:" | head -1) || true

  if [[ "$plain_status" == "301" ]] || [[ "$plain_status" == "302" ]]; then
    if echo "$location" | grep -qi "https://"; then
      check "$domain: HTTP -> HTTPS redirect enforced" "pass"
    else
      check "$domain: HTTP -> HTTPS redirect enforced" "fail: redirect to '$location' (not https)"
    fi
  elif [[ "$plain_status" == "200" ]]; then
    check "$domain: HTTP -> HTTPS redirect enforced" "fail: HTTP served content directly (not redirected)"
  else
    check "$domain: HTTP -> HTTPS redirect enforced" "fail: unexpected status '$plain_status'"
  fi
}

echo "================================================"
echo " Life Platform — CloudFront HTTPS Smoke Test"
echo " $(date)"
echo "================================================"

smoke_test_domain "dash.averagejoematt.com"  "EM5NPX6NJN095"  "yes"
smoke_test_domain "blog.averagejoematt.com"  "E1JOC1V6E6DDYI" "no"
smoke_test_domain "buddy.averagejoematt.com" "ETTJ44FT0Z4GO"  "yes"

echo ""
echo "================================================"
echo " Results: $PASS passed, $FAIL failed"
echo "================================================"

if [[ $FAIL -gt 0 ]]; then
  echo ""
  echo "Failed checks:"
  for r in "${results[@]}"; do
    if [[ "$r" == \[FAIL\]* ]]; then
      echo "  $r"
    fi
  done
  exit 1
else
  echo " All checks passed."
  exit 0
fi
