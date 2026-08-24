#!/usr/bin/env bash
# wait_pr_green.sh — the ONE blessed PR-check watcher (#3103).
#
# THE INCIDENT (2026-08-23/24 session): ~12 ad-hoc watchers were hand-rolled in one
# session and each one independently reinvented — and sometimes missed — the same
# discipline:
#
#   1. Short-sha `actions/runs?head_sha=<7 chars>` queries silently return EMPTY
#      (GitHub's Actions API wants the full 40-char sha). An empty result reads as
#      "no runs" rather than "wrong query" — indistinguishable from a swallowed push.
#   2. "No checks reported" got treated as DONE at least once. It is a FAILURE, never
#      a pass — the swallowed-push class (see docs/CONVENTIONS.md, the push-run
#      detector, `reference_swallowed_push_no_runs_at_all.md`).
#   3. An EXPECTED check that never attaches to the PR is invisible to a naive
#      "any red?" filter — everything that *did* report was green, so the watcher
#      declared victory while a whole check never ran
#      (`reference_absent_check_invisible_to_fail_filter.md`). The fix is to assert
#      the expected set BY NAME, not just scan whatever showed up.
#   4. Twice, "read the watcher's verdict" and "gh pr merge" were chained in one
#      compound command, so the merge fired past an unread NONGREEN line. This
#      script NEVER merges — it only prints a verdict and exits. The merge is always
#      a separate, deliberate command the caller reads before running.
#
# WHAT THIS DOES
#   - Resolves the PR's current head via the FULL 40-char sha (`gh pr view --json
#     headRefOid`), never a shell-truncated prefix.
#   - Reads checks via `gh pr checks <pr> --json name,state,bucket`, which gh itself
#     scopes to the PR's head — no hand-rolled `actions/runs?head_sha=` query exists
#     in this script at all, which structurally forecloses failure mode #1.
#   - Derives a default expected-check-by-NAME set from the PR's changed paths
#     (grounded in the real `.github/workflows/*.yml` `name:`/`paths:` fields — see
#     `derive_expected_checks` below — never invented), extendable with `--expect`.
#   - Polls until every expected check is present BY NAME and terminal, or the
#     timeout elapses. An absent expected check is reported by name, exactly like a
#     failed one — it is never silently dropped because everything *else* passed.
#   - Detects a WAITING check (a gated-deployment lease, e.g. an Environment
#     protection rule) and reports it distinctly — not green, not failed. A human
#     disposes leases (`deploy/approve_deployment.sh` / `deploy/reject_deployment.sh`);
#     this script does not wait one out.
#   - If the PR's head sha changes mid-poll (a new push landed), restarts the watch
#     against the new sha rather than silently grading stale checks.
#
# WHAT THIS NEVER DOES
#   - Never runs `gh pr merge` or any mutating call. Exit code is the verdict; the
#     merge is the caller's own, separate, next command.
#
# USAGE
#   deploy/wait_pr_green.sh <pr-number> [--expect "Check name"]... \
#       [--timeout SECONDS] [--interval SECONDS] [--no-derive] [--repo OWNER/REPO]
#
#   <pr-number>        the PR to watch.
#   --expect NAME      an additional check name to require (repeatable). Names are
#                       matched EXACTLY against what GitHub reports — copy the real
#                       string from `gh pr checks <a-recent-pr> --json name`, don't
#                       guess (a workflow job `name:` field can itself get silently
#                       truncated by a YAML `#`-comment gotcha — see the
#                       BASELINE_CHECKS comment below for a live example).
#   --timeout SECONDS  overall wait budget (default 1800 = 30 min).
#   --interval SECONDS poll interval (default 30).
#   --no-derive        skip path-based derivation; expect ONLY the baseline set
#                       (unconditional PR checks) plus any --expect names.
#   --repo OWNER/REPO  defaults to averagejoematt/life-platform.
#
# EXIT CODES
#   0  every expected check is present and green.
#   1  a terminal failure was observed, or the timeout elapsed with checks still
#      absent/pending — NONGREEN lines name every offending check.
#   2  a WAITING (gated-deployment) check was observed — WAITING lines name it; a
#      human must approve or reject the lease, this script does not wait it out.
#
# SELF-TEST (fixture mode, no network, no `gh` calls — see tests/test_wait_pr_green.py)
#   deploy/wait_pr_green.sh --fixture path/to/checks.json [--expect NAME]... [--no-derive]
#   Evaluates the fixture JSON (the same shape `gh pr checks --json name,state,bucket`
#   returns) exactly once — no polling, no PR number, no gh calls — and exits with the
#   same codes as the real run. This is also how the core logic is testable in CI's
#   offline unit suite: `deploy/wait_pr_green.sh --fixture` sourced or spawned as a
#   subprocess, fed a fixture, asserted on exit code + NONGREEN/WAITING output.
#
# This file is also SOURCEABLE (`source deploy/wait_pr_green.sh --source-only`) so a
# test harness can call `derive_expected_checks` / `evaluate_checks_json` directly —
# see tests/test_wait_pr_green.py's bash-harness tests.

set -uo pipefail

REPO="${WAIT_PR_GREEN_REPO:-averagejoematt/life-platform}"

# ── the baseline: checks that report on EVERY PR regardless of changed paths ──
#
# Grounded in the actual `on: pull_request:` triggers, read 2026-08-24 (#3103):
#   - pr-checks.yml carries NO `paths:` filter on its `pull_request` trigger BY
#     DESIGN (its own header: adding one would silently un-require the fast lane —
#     see deploy/github_posture.json's `main_required_checks_ruleset`). Its three
#     jobs (fast-lane, full-suite, api-before-frontend) all fire unconditionally.
#   - secret-scan.yml (gitleaks) likewise has no `paths:` filter.
#   - codeql.yml's `pull_request:` trigger ALSO carries no `paths:` filter (only
#     its `push:` trigger is path-scoped) — both CodeQL matrix legs fire on every PR.
#
# "Full unit suite (pre-merge," — yes, missing "#3025)" — is the REAL reported name,
# verified live via `gh api repos/.../commits/<full-sha>/check-runs`, not a typo in
# this file. The job's `name:` in pr-checks.yml literally is `Full unit suite
# (pre-merge, #3025)`, but YAML treats an unquoted `#` preceded by whitespace as a
# COMMENT START — so everything from " #3025)" onward is stripped before GitHub ever
# sees the string. `(#2831)` in the api-before-frontend job survives intact because
# its `#` is preceded by `(`, not whitespace, so it's not a comment. This script
# matches the name GitHub actually reports; it is not this script's job to fix the
# workflow file's YAML gotcha (flagged separately, out of scope for #3103).
BASELINE_CHECKS=(
  "Collect + deploy-critical + format"
  "Full unit suite (pre-merge,"
  "API-before-frontend sequencing check (#2831)"
  "gitleaks (PR commit range only, not full history)"
  "CodeQL analysis (python)"
  "CodeQL analysis (javascript-typescript)"
)

# derive_expected_checks <newline-separated changed files>
#   Prints the baseline set plus path-conditional additions, one name per line.
#   Grounded in the real `paths:` filters in .github/workflows/{v4-gate,docs-ci}.yml
#   — read those files if this drifts, never hand-guess a new name.
derive_expected_checks() {
  local files="$1"
  printf '%s\n' "${BASELINE_CHECKS[@]}"
  # v4-gate.yml pull_request paths: site/**, scripts/v4_*.py, tests/pr_render_gate.py,
  # tests/visual_qa.py, tests/accuracy_audit.py, tests/fixtures/render_gate/**, etc.
  if grep -qE '^site/|^scripts/v4_[^/]*\.py$|^tests/pr_render_gate\.py$|^tests/visual_qa\.py$|^tests/accuracy_audit\.py$|^tests/fixtures/render_gate/' <<<"${files}"; then
    printf '%s\n' \
      "Migration coverage + HTML well-formedness" \
      "Render + accuracy gate (local render)"
  fi
  # docs-ci.yml pull_request paths: docs/**, README.md, CLAUDE.md, .claude/commands/**,
  # deploy/sync_doc_metadata.py, scripts/check_doc_*.py, + the code half
  # (lambdas/**, mcp/**, config/**, cdk/**) + two named tests/ fact-source files.
  if grep -qE '^docs/|^README\.md$|^CLAUDE\.md$|^\.claude/commands/|^deploy/sync_doc_metadata\.py$|^scripts/check_doc_.*\.py$|^scripts/doc_facts_ops\.py$|^scripts/generate_adr_index\.py$|^scripts/generate_mcp_tool_catalog\.py$|^scripts/operating_calendar\.py$|^lambdas/|^mcp/|^config/|^cdk/|^tests/qa_manifest\.py$|^tests/leak_token_sweep\.py$|^tests/test_platform_stats_truth\.py$' <<<"${files}"; then
    echo "Wiki drift gates"
  fi
}

# ── the pure evaluator — no gh, no network, fully unit-testable ──────────────
#
# evaluate_checks_json <checks-json> <expected-name-1> [<expected-name-2> ...]
#   <checks-json> is a JSON array shaped like `gh pr checks --json name,state,bucket`
#   output: [{"name":..., "state":..., "bucket":...}, ...].
#   `bucket` is gh's own categorization (pass/fail/pending/skipping/cancel — see
#   `gh pr checks --help`); this function trusts it rather than re-deriving from raw
#   `state` strings, EXCEPT for WAITING, which gh buckets as "pending" but which this
#   script must surface distinctly (a gated-deployment lease, not ordinary in-flight
#   work — a human disposes it, waiting it out is never correct).
#
#   Prints one line per expected check:
#     GREEN <name>
#     PENDING <name> <state>
#     WAITING <name>
#     NONGREEN <name> <state-or-ABSENT>
#   then a final line:
#     VERDICT SUCCESS|PENDING|WAITING|FAIL
#   Returns 0=SUCCESS, 3=PENDING (keep polling), 2=WAITING, 1=FAIL.
evaluate_checks_json() {
  local checks_json="$1"
  shift
  local -a expected=("$@")
  local any_waiting=0 any_nongreen=0 any_pending=0
  local exp entry state bucket

  # bash 3.2 (macOS's shipped /bin/bash — this repo's scripts run there locally
  # and under bash 5 in CI) treats `"${expected[@]}"` as an unbound-variable error
  # under `set -u` when the array has zero elements, even though the array itself
  # was assigned. Guard explicitly rather than relying on `${expected[@]:-}`,
  # which would otherwise inject one spurious empty-string iteration.
  if [[ ${#expected[@]} -eq 0 ]]; then
    echo "VERDICT SUCCESS"
    return 0
  fi

  for exp in "${expected[@]}"; do
    entry=$(jq -c --arg n "${exp}" '[.[] | select(.name == $n)] | .[0] // empty' <<<"${checks_json}" 2>/dev/null)
    if [[ -z "${entry}" || "${entry}" == "null" ]]; then
      # Printed as NONGREEN (the literal contract: "assert the expected set BY
      # NAME" — an absent check must never be invisible), but bucketed as
      # `any_pending`, not `any_nongreen`: a check that hasn't attached to the
      # PR yet is not necessarily broken, it may just not have started. The
      # caller (main's poll loop) keeps polling on `any_pending` and only
      # treats a still-absent name as the FINAL failure reason once the
      # timeout elapses — never an instant fail, never silently dropped either.
      echo "NONGREEN ${exp} ABSENT"
      any_pending=1
      continue
    fi
    state=$(jq -r '.state // ""' <<<"${entry}")
    bucket=$(jq -r '.bucket // ""' <<<"${entry}")
    if [[ "${state}" == "WAITING" ]]; then
      echo "WAITING ${exp}"
      any_waiting=1
    elif [[ "${bucket}" == "pass" ]]; then
      echo "GREEN ${exp}"
    elif [[ "${bucket}" == "pending" ]]; then
      echo "PENDING ${exp} ${state}"
      any_pending=1
    else
      # fail / skipping / cancel / unrecognized bucket — treated as a hard, terminal
      # NONGREEN. A skipped-but-expected check never satisfies this watch (a skip on
      # a check we ourselves asserted as required almost always means a job-level
      # `if:` regressed, not that it's fine to proceed).
      echo "NONGREEN ${exp} ${state:-${bucket}}"
      any_nongreen=1
    fi
  done

  # "No checks reported at all" must NEVER read as done — with zero entries every
  # expected name is ABSENT above, which already routes to "keep polling" (not an
  # instant pass). This explicit check exists only to surface the diagnostic once
  # the caller decides to stop polling (timeout), never to short-circuit early.
  local total
  total=$(jq 'length' <<<"${checks_json}" 2>/dev/null || echo 0)
  if [[ "${total}" -eq 0 ]]; then
    echo "NOTE zero checks have been reported at all — possible swallowed push (verify with: gh run list --branch <branch> -R ${REPO})"
  fi

  if [[ "${any_nongreen}" -eq 1 ]]; then
    echo "VERDICT FAIL"
    return 1
  fi
  if [[ "${any_waiting}" -eq 1 ]]; then
    echo "VERDICT WAITING"
    return 2
  fi
  if [[ "${any_pending}" -eq 1 ]]; then
    echo "VERDICT PENDING"
    return 3
  fi
  echo "VERDICT SUCCESS"
  return 0
}

# ── CLI driver ─────────────────────────────────────────────────────────────

_usage() {
  cat <<'USAGE'
usage: deploy/wait_pr_green.sh <pr-number> [--expect "Check name"]...
                                [--timeout SECONDS] [--interval SECONDS]
                                [--no-derive] [--repo OWNER/REPO]
       deploy/wait_pr_green.sh --fixture FILE [--expect "Check name"]... [--no-derive]

Waits for a PR's checks to go green by NAME. Never merges — prints a verdict and
exits. See the header comment in this file for the full discipline this encodes.
USAGE
}

main() {
  local pr="" fixture="" timeout=1800 interval=30 no_derive=0
  local -a extra_expect=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --expect)
        extra_expect+=("$2")
        shift 2
        ;;
      --timeout)
        timeout="$2"
        shift 2
        ;;
      --interval)
        interval="$2"
        shift 2
        ;;
      --no-derive)
        no_derive=1
        shift
        ;;
      --repo)
        REPO="$2"
        shift 2
        ;;
      --fixture)
        fixture="$2"
        shift 2
        ;;
      -h | --help)
        _usage
        return 0
        ;;
      *)
        if [[ -z "${pr}" ]]; then
          pr="$1"
        else
          echo "unrecognized argument: $1" >&2
          _usage >&2
          return 2
        fi
        shift
        ;;
    esac
  done

  if [[ -z "${pr}" && -z "${fixture}" ]]; then
    _usage >&2
    return 2
  fi

  # ── fixture mode: no gh, no network, no polling — one evaluation, one verdict.
  if [[ -n "${fixture}" ]]; then
    local checks_json
    checks_json=$(cat "${fixture}")
    local -a expected=()
    if [[ "${no_derive}" -eq 0 ]]; then
      while IFS= read -r line; do
        [[ -n "${line}" ]] && expected+=("${line}")
      done < <(derive_expected_checks "")
    else
      expected+=("${BASELINE_CHECKS[@]}")
    fi
    [[ ${#extra_expect[@]} -gt 0 ]] && expected+=("${extra_expect[@]}")
    evaluate_checks_json "${checks_json}" "${expected[@]}"
    local rc=$?
    if [[ "${rc}" -eq 3 ]]; then
      rc=1 # a fixture is a single static snapshot — "still pending" has no next poll, treat as nonzero
    fi
    return "${rc}"
  fi

  # ── real mode: gh, full shas, polling ──────────────────────────────────────
  local head_sha changed_files
  head_sha=$(gh pr view "${pr}" --repo "${REPO}" --json headRefOid --jq '.headRefOid') || {
    echo "ERROR: could not resolve PR #${pr}'s head sha via gh pr view" >&2
    return 1
  }
  if [[ ${#head_sha} -ne 40 ]]; then
    echo "ERROR: resolved sha '${head_sha}' is not a full 40-char sha — refusing to proceed (#3103 discipline)" >&2
    return 1
  fi
  changed_files=$(gh pr view "${pr}" --repo "${REPO}" --json files --jq '.files[].path' 2>/dev/null || echo "")

  local -a expected=()
  if [[ "${no_derive}" -eq 0 ]]; then
    while IFS= read -r line; do
      [[ -n "${line}" ]] && expected+=("${line}")
    done < <(derive_expected_checks "${changed_files}")
  else
    expected+=("${BASELINE_CHECKS[@]}")
  fi
  [[ ${#extra_expect[@]} -gt 0 ]] && expected+=("${extra_expect[@]}")
  # dedupe, preserving order
  local -a dedup=()
  local e s seen
  for e in "${expected[@]}"; do
    seen=0
    for s in "${dedup[@]:-}"; do
      [[ "${s}" == "${e}" ]] && seen=1 && break
    done
    [[ "${seen}" -eq 0 ]] && dedup+=("${e}")
  done
  expected=("${dedup[@]}")

  echo "Watching PR #${pr} (${REPO}) at sha ${head_sha}"
  echo "Expected checks (${#expected[@]}):"
  printf '  - %s\n' "${expected[@]}"

  local start now elapsed checks_json out rc
  start=$(date +%s)
  while true; do
    now=$(date +%s)
    elapsed=$((now - start))
    if [[ "${elapsed}" -ge "${timeout}" ]]; then
      echo "TIMEOUT after ${elapsed}s (budget ${timeout}s) — last known state:"
      checks_json=$(gh pr checks "${pr}" --repo "${REPO}" --json name,state,bucket 2>/dev/null || echo '[]')
      evaluate_checks_json "${checks_json}" "${expected[@]}"
      return 1
    fi

    local cur_sha
    cur_sha=$(gh pr view "${pr}" --repo "${REPO}" --json headRefOid --jq '.headRefOid' 2>/dev/null || echo "")
    if [[ -n "${cur_sha}" && ${#cur_sha} -eq 40 && "${cur_sha}" != "${head_sha}" ]]; then
      echo "PR head moved ${head_sha} -> ${cur_sha} (a new push landed) — restarting the watch against the new sha"
      head_sha="${cur_sha}"
      start=$(date +%s)
      changed_files=$(gh pr view "${pr}" --repo "${REPO}" --json files --jq '.files[].path' 2>/dev/null || echo "")
      continue
    fi

    checks_json=$(gh pr checks "${pr}" --repo "${REPO}" --json name,state,bucket 2>/dev/null || echo '[]')
    out=$(evaluate_checks_json "${checks_json}" "${expected[@]}")
    rc=$?

    case "${rc}" in
      0)
        echo "${out}"
        echo "All ${#expected[@]} expected checks are GREEN (elapsed ${elapsed}s)."
        return 0
        ;;
      1)
        echo "${out}"
        echo "A check FAILED — stopping (elapsed ${elapsed}s). This script never merges; fix, re-push, and re-run."
        return 1
        ;;
      2)
        echo "${out}"
        echo "A WAITING (gated-deployment) check was observed — stopping (elapsed ${elapsed}s)."
        echo "A human disposes leases: deploy/approve_deployment.sh <run_id> or deploy/reject_deployment.sh <run_id>."
        return 2
        ;;
      3)
        local green_count
        green_count=$(grep -c '^GREEN ' <<<"${out}" || true)
        echo "  ... ${green_count}/${#expected[@]} green (elapsed ${elapsed}s/${timeout}s), polling again in ${interval}s"
        sleep "${interval}"
        ;;
    esac
  done
}

# Sourceable for tests (`source deploy/wait_pr_green.sh --source-only`) without
# running main — mirrors the pattern in deploy/lib/resilient_curl.sh.
if [[ "${1:-}" != "--source-only" && "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
  exit $?
fi
