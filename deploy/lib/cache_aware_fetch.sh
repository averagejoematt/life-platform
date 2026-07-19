#!/usr/bin/env bash
# cache_aware_fetch.sh — bounded content-assertion retries for the site smoke (#1526).
#
# 2026-07-19 05:40 UTC (INCIDENT_LOG): a deploy shipped new content AND the smoke
# guard asserting it; smoke fetched /coaching/ from a CloudFront edge the
# invalidation hadn't reached yet, saw the cached pre-deploy page, failed the
# brand-new static-core check, and auto-rollback reverted a HEALTHY deploy.
#
# Mechanism: a failed body assertion may re-fetch + re-check on an interval until
# a SHARED budget is spent — sized to the CloudFront propagation window (~60-90s).
# The common case (fresh edge, assertion passes) is one fetch and ZERO sleeps; the
# worst case adds at most the budget once across the ENTIRE smoke run (shared, not
# per-assertion). There is deliberately no unconditional sleep in this path — the
# deterministic wait lives where the AWS credentials are (sync_site_to_s3.sh blocks
# on `aws cloudfront wait invalidation-completed` after creating the invalidation);
# this lib is the second net for propagation residue.
#
# Sourced by deploy/smoke_test_site.sh; unit-tested (curl/sleep stubbed as shell
# functions) by tests/test_smoke_cache_aware.py.

CONTENT_RETRY_BUDGET="${SMOKE_CONTENT_RETRY_BUDGET:-90}"     # seconds, SHARED across all retries in a run
CONTENT_RETRY_INTERVAL="${SMOKE_CONTENT_RETRY_INTERVAL:-15}" # seconds between re-fetches

# refetch_within_budget <url> <file> — one budgeted wait + re-fetch of url into
# file. Returns 1 (without sleeping) once the shared budget is spent.
refetch_within_budget() {
  local url="$1" file="$2"
  [[ "$CONTENT_RETRY_BUDGET" -ge "$CONTENT_RETRY_INTERVAL" ]] || return 1
  CONTENT_RETRY_BUDGET=$((CONTENT_RETRY_BUDGET - CONTENT_RETRY_INTERVAL))
  echo "  ⏳ stale-edge suspect: $url — re-fetching in ${CONTENT_RETRY_INTERVAL}s (${CONTENT_RETRY_BUDGET}s retry budget left)"
  sleep "$CONTENT_RETRY_INTERVAL"
  curl -s --max-time 15 "$url" > "$file" || true
  return 0
}

# assert_body_until <url> <file> <check_fn> — run `check_fn <file>`; while it
# fails, do budgeted re-fetches of url into file. Returns the FINAL verdict
# (0 pass / 1 fail); the last-fetched body stays in file for the caller's
# failure message.
assert_body_until() {
  local url="$1" file="$2" check_fn="$3"
  while ! "$check_fn" "$file"; do
    refetch_within_budget "$url" "$file" || return 1
  done
  return 0
}
