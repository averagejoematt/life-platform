#!/usr/bin/env bash
# resilient_curl.sh — timeout-resilient curl for the post-deploy site smoke (#1911)
#
# THE INCIDENT CLASS (twice in two days, 2026-07-29 and 2026-07-30):
# smoke_test_site.sh runs under `set -euo pipefail`. A bare command substitution
#
#     status=$(curl -s --max-time 10 "$url")
#
# is a trap under that setting: when curl exits non-zero (28 = timeout), the
# substitution fails, `set -e` aborts the WHOLE script immediately, and the run
# ends with a bare `##[error] exit code 28` — no ❌ row, no failing URL, and no
# chance for the check's own error handling to run. The post-deploy gate reads
# that as a bad deploy and auto-rolls-back. It did, twice, each time reverting a
# correct, fully-gated, merged fix (#1891, then #1895's front-end) — once putting
# a real clinician's name back on a live public page for ~15 minutes.
#
# Root cause of the timeouts themselves was origin latency on ONE endpoint
# (/api/inference_receipt — see #1911 and the GetMetricData batching fix). But
# the deeper defect is structural and outlives any single slow endpoint: ONE
# timed-out request out of ~40 is weak evidence of a bad deploy, yet it was
# sufficient to auto-revert merged work — and it did so anonymously.
#
# WHAT THIS PROVIDES
#   smoke_curl <curl args...>
#     Runs curl WITHOUT tripping `set -e`, retrying once (configurable) on the
#     transient connection-class exit codes only. Echoes curl's stdout. Publishes
#     curl's exit code via a file (see below), so callers inside a command
#     substitution can still read it.
#
#   smoke_curl_rc
#     The exit code of the most recent smoke_curl. Works across the command-
#     substitution subshell boundary (a plain global would be lost there), which
#     is why the code round-trips through a file rather than a variable.
#
# WHAT IT DELIBERATELY DOES NOT DO
#   It never retries an HTTP error. A 404/500 comes back as curl exit 0 with a
#   status code in the body/-w output, so it is untouched here and still fails
#   its check immediately. Only transport failures (timeout, connect, TLS, reset)
#   are retried — the class where a retry is evidence, not indulgence.
#
# Sourced by deploy/smoke_test_site.sh; unit-tested in tests/test_smoke_resilient_curl.py
# under real bash with `curl` and `sleep` stubbed as shell functions — no network,
# no wall-clock sleeps.
# ─────────────────────────────────────────────────────────────────────────────

# Total attempts per request (1 = no retry). The default of 2 is the issue's
# "retry once on curl timeout before failing" acceptance criterion.
SMOKE_CURL_ATTEMPTS="${SMOKE_CURL_ATTEMPTS:-2}"

# Seconds between attempts. A variable, never a literal — smoke_test_site.sh is
# asserted to carry no unconditional `sleep <digit>` (#1526's no-fixed-sleep rule).
SMOKE_CURL_RETRY_INTERVAL="${SMOKE_CURL_RETRY_INTERVAL:-2}"

# curl exit codes worth a second attempt — transport failures only:
#   7  couldn't connect      28 operation timed out    35 TLS handshake
#   52 empty reply           55 send error             56 recv error
# Anything else (including every HTTP status) fails on the first attempt.
SMOKE_CURL_RETRY_CODES="${SMOKE_CURL_RETRY_CODES:-7 28 35 52 55 56}"

# Where the exit code is published. Command substitution runs in a subshell, so a
# global assigned inside smoke_curl would vanish before the caller could read it.
SMOKE_CURL_RC_FILE="${SMOKE_CURL_RC_FILE:-${TMPDIR:-/tmp}/smoke_curl_rc.$$}"

# Count of retried requests over the run — reported in the smoke summary so a
# recovered timeout stays VISIBLE rather than being silently swallowed.
SMOKE_CURL_RETRIES=0
SMOKE_CURL_RETRY_LOG="${SMOKE_CURL_RETRY_LOG:-${TMPDIR:-/tmp}/smoke_curl_retries.$$}"
: >"$SMOKE_CURL_RETRY_LOG" 2>/dev/null || true

smoke_curl() {
  local out rc attempt=1
  while :; do
    # `if cmd; then` is exempt from set -e, so a failing curl lands in the else
    # branch instead of killing the script. This is the whole point of the lib.
    # NB: plain `curl`, not `command curl` — the unit tests stub curl as a shell
    # function, and `command` would bypass the stub and hit the real network.
    if out=$(curl "$@"); then
      rc=0
    else
      rc=$?
    fi
    [[ "$rc" -eq 0 ]] && break
    [[ "$attempt" -ge "$SMOKE_CURL_ATTEMPTS" ]] && break
    # Retry only the transport-failure class; anything else fails immediately.
    case " $SMOKE_CURL_RETRY_CODES " in
      *" $rc "*) ;;
      *) break ;;
    esac
    # stderr, never stdout — stdout is being captured by the caller.
    echo "  ⟳ curl exit $rc (transient class) — retrying once" >&2
    echo "retry rc=$rc" >>"$SMOKE_CURL_RETRY_LOG" 2>/dev/null || true
    attempt=$((attempt + 1))
    sleep "$SMOKE_CURL_RETRY_INTERVAL"
  done
  echo "$rc" >"$SMOKE_CURL_RC_FILE" 2>/dev/null || true
  printf '%s' "$out"
}

# Exit code of the most recent smoke_curl (0 when unknown).
smoke_curl_rc() {
  cat "$SMOKE_CURL_RC_FILE" 2>/dev/null || echo 0
}

# How many requests needed a retry this run (for the summary line).
smoke_curl_retry_count() {
  if [[ -f "$SMOKE_CURL_RETRY_LOG" ]]; then
    wc -l <"$SMOKE_CURL_RETRY_LOG" | tr -d ' '
  else
    echo 0
  fi
}

# ── #2978: confirm-before-fail for HTTP-level check failures ──────────────────
# Transport retries above cover curl-exit failures; this covers the OTHER half
# of the deploy-race class: the probe SUCCEEDS at the transport layer but reads
# a transient wrong answer (stale edge mid-invalidation, a cold Lambda's first
# hit, an empty first readout). A failed check re-runs its probe ONCE after a
# bounded delay; only a REPRODUCED failure reds the smoke. Every confirmed
# transient is counted (ADR-104) so the race rate stays measurable for #2978's
# 30-day re-measure even though it no longer auto-rolls-back green deploys.
#
#   smoke_confirm <probe-fn> [args…]
#     Sleeps SMOKE_CONFIRM_DELAY, re-runs the probe. Returns 0 (and increments
#     the confirmed-transient counter) iff the re-probe passes. Returns 1 when
#     confirmation is disabled (SMOKE_CONFIRM_ATTEMPTS < 1) or the failure
#     reproduces — the caller records its normal ❌ in that case.
SMOKE_CONFIRM_ATTEMPTS="${SMOKE_CONFIRM_ATTEMPTS:-1}"
SMOKE_CONFIRM_DELAY="${SMOKE_CONFIRM_DELAY:-15}"
SMOKE_CONFIRM_LOG="${SMOKE_CONFIRM_LOG:-$(mktemp "${TMPDIR:-/tmp}/smoke_confirm.XXXXXX")}"

smoke_confirm() {
  [[ "${SMOKE_CONFIRM_ATTEMPTS}" -lt 1 ]] && return 1
  echo "  ⟳ probe failed — confirming once after ${SMOKE_CONFIRM_DELAY}s before it can red (#2978)" >&2
  sleep "${SMOKE_CONFIRM_DELAY}"
  if "$@"; then
    echo "confirmed-transient: $*" >>"$SMOKE_CONFIRM_LOG" 2>/dev/null || true
    return 0
  fi
  return 1
}

# How many checks failed a first probe but passed the confirm (for the summary).
smoke_confirm_transient_count() {
  if [[ -f "$SMOKE_CONFIRM_LOG" ]]; then
    wc -l <"$SMOKE_CONFIRM_LOG" | tr -d ' '
  else
    echo 0
  fi
}
