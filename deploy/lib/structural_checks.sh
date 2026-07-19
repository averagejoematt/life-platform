#!/usr/bin/env bash
# structural_checks.sh — static-page structural assertions for the site smoke (#1429).
#
# The static long-tail (/404, /subscribe/confirm/, /privacy/, the essays, …) can
# silently break or leak placeholder content between reviews — no API dep, no
# visual gate at deploy time. These two predicates give every static/utility page
# a structural gate inside deploy/smoke_test_site.sh:
#
#   struct_marker_ok <file>   — the page body must contain the fixed-string marker
#                               in $STRUCT_MARKER (expected title/selector, declared
#                               per page in tests/qa_manifest.py — THE registry, #1426).
#                               Fixed-string (grep -F), never a regex: markers are
#                               literal HTML fragments like 'class="policy-title"'.
#   leak_tokens_absent <file> — the body must carry NO template-leak token. The token
#                               set is deliberately narrower than the home-page
#                               stale-copy scan: /gear/ legitimately says "coming
#                               soon" (affiliate links) and forms carry placeholder=
#                               attributes, so those words are NOT in this set.
#
# Both take the body file as $1, matching the check_fn contract of
# deploy/lib/cache_aware_fetch.sh's assert_body_until (#1526) — a failing check
# re-fetches within the shared bounded budget before it may fail the gate.
#
# Sourced by deploy/smoke_test_site.sh; unit-tested (fixture bodies, curl/sleep
# stubbed) by tests/test_smoke_structural.py.

# \b is honored by both GNU grep (CI) and macOS BSD grep (verified: matches
# ' TODO ' but not 'Todoist').
LEAK_TOKEN_PATTERN='lorem ipsum|launching april|\btodo\b|\btktk\b|\{\{[a-z0-9_.]+\}\}'

struct_marker_ok() {
  grep -qF -- "$STRUCT_MARKER" "$1"
}

leak_tokens_absent() {
  ! grep -qiE "$LEAK_TOKEN_PATTERN" "$1"
}
