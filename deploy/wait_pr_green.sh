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
#   - Reads checks via `gh pr checks <pr> --json name,state,bucket,link`, which gh
#     itself scopes to the PR's head — no hand-rolled `actions/runs?head_sha=` query
#     exists in this script at all, which structurally forecloses failure mode #1.
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
#                       guess (a workflow job `name:` field can silently truncate at
#                       an unquoted `#` — see the BASELINE_CHECKS comment below for
#                       the #3117 incident that motivated this warning).
#   --timeout SECONDS  overall wait budget (default 1800 = 30 min).
#   --interval SECONDS poll interval (default 30).
#   --zero-check-grace SECONDS
#                       how long ZERO attached checks is tolerated before the
#                       swallow diagnosis runs (default 120). Long enough that
#                       ordinary attach latency never trips it — #3219's whole
#                       point is a named diagnosis, not a faster failure. Once
#                       any check has attached the diagnosis never runs at all.
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
#   5  SWALLOWED PUSH (#3219) — after `--zero-check-grace` seconds with ZERO
#      checks attached, `scripts/check_main_green.py --classify-sha <full40>`
#      classified the head sha as `swallowed`: no workflow run of ANY kind
#      references it, so no check will ever attach and polling to the 1800s
#      timeout is dead time. Deliberately DISTINCT from 1 (a red or a timeout) —
#      the action is not "fix and re-push", it is the event-swallow recovery
#      ladder, which the script prints. The other zero-run states
#      (path-filter-skip, bot-push-no-dispatch, indeterminate) are NAMED and
#      polling CONTINUES — they are not swallows and must not be lumped in.
#   4  GREEN-WITH-RECONCILE-OWNED-RED (#3200) — every expected check is green
#      EXCEPT "Wiki drift gates", whose only red is `sync_doc_metadata.py
#      --check` naming exclusively reconcile-owned paths (docs/*, CLAUDE.md,
#      .claude/README.md, the generated lambdas/web/platform_counts.py — the
#      driver reconciles these once per merge on main, #3101; a branch cannot
#      carry them at all, `agent_commit.sh` refuses them outright). This is a
#      structural PASS for merge purposes — see `_is_reconcile_owned_path`
#      below — reported distinctly (an explicit RECONCILE-OWNED-RED line) so a
#      caller can name what it waved through instead of silently treating it
#      as an ordinary green. ANY other red, or a non-reconcile path in that
#      gate's own ❌ list, still exits 1 exactly like before this existed.
#
# SELF-TEST (fixture mode, no network, no `gh` calls — see tests/test_wait_pr_green.py)
#   deploy/wait_pr_green.sh --fixture path/to/checks.json [--expect NAME]... [--no-derive]
#   Evaluates the fixture JSON (the same shape `gh pr checks --json name,state,bucket`
#   returns) exactly once — no polling, no PR number, no gh calls — and exits with the
#   same codes as the real run. This is also how the core logic is testable in CI's
#   offline unit suite: `deploy/wait_pr_green.sh --fixture` sourced or spawned as a
#   subprocess, fed a fixture, asserted on exit code + NONGREEN/WAITING output. A
#   fixture entry named "Wiki drift gates" may additionally carry a `driftFiles`
#   array (the gate's own ❌ file list) to exercise the #3200 classifier — see
#   `_is_reconcile_owned_path` and `evaluate_checks_json` below.
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
# FIXED by #3117 (was open when #3103 landed this script): the job's `name:` in
# pr-checks.yml used to be `Full unit suite (pre-merge, #3025)` — YAML treats an
# unquoted `#` preceded by whitespace as a COMMENT START, so everything from
# " #3025)" onward was stripped before GitHub ever saw the string, and the WIRE
# name silently truncated to `Full unit suite (pre-merge,` (trailing comma).
# `(#2831)` in the api-before-frontend job below never had this problem — its `#`
# is preceded by `(`, not whitespace, so it was never a comment start. #3117
# renamed the job to `Full unit suite (pre-merge, issue 3025)` (no `#` at all) —
# the baseline below is that CURRENT wire name, not the old truncated one.
BASELINE_CHECKS=(
  "Collect + deploy-critical + format"
  "Full unit suite (pre-merge, issue 3025)"
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
  # docs-ci.yml pull_request paths: docs/**, README.md, CLAUDE.md, .claude/{skills,agents}/**,
  # deploy/sync_doc_metadata.py, scripts/check_doc_*.py, + the code half
  # (lambdas/**, mcp/**, config/**, cdk/**) + two named tests/ fact-source files.
  if grep -qE '^docs/|^README\.md$|^CLAUDE\.md$|^\.claude/(skills|agents)/|^\.claude/README\.md$|^deploy/sync_doc_metadata\.py$|^scripts/check_doc_.*\.py$|^scripts/doc_facts_ops\.py$|^scripts/generate_adr_index\.py$|^scripts/generate_mcp_tool_catalog\.py$|^scripts/operating_calendar\.py$|^lambdas/|^mcp/|^config/|^cdk/|^tests/qa_manifest\.py$|^tests/leak_token_sweep\.py$|^tests/test_platform_stats_truth\.py$' <<<"${files}"; then
    echo "Wiki drift gates"
  fi
}

# ── the sanctioned reconcile-owned path set (#3200) — DERIVED, never hand-listed ──
#
# The incident (#3200, live 2026-08-26): the ONLY red on PR #3201 was "Wiki drift
# gates", whose failing step (`sync_doc_metadata.py --check`) named exactly ONE
# stale literal: `lambdas/web/platform_counts.py`. That file is refused outright by
# `deploy/agent_commit.sh` — a branch structurally cannot carry it — so this was
# never a real defect, it was the exact shape of PR the merge train (#3104) exists
# to carry. The workaround that night was a human eyeballing the ❌ list and
# verifying every path was reconcile-owned before merging by hand. This section
# retires that step.
#
# `deploy/agent_commit.sh`'s `is_literal_file()` is already the ONE real
# enforcement point for "which paths are reconciled on main, never on a branch" —
# see its own header comment. The universe of paths `sync_doc_metadata.py --check`
# can print in its ❌ list is exactly that same set: `docs_to_process` in
# sync_doc_metadata.py's `main()` is every doc under `RULES` (all `docs/*`) plus
# `CLAUDE.md` / `.claude/README.md`, and the generated-counter drift
# (`lambdas/web/platform_counts.py`) and the MONITORING.md alarm-inventory drift
# (already a `docs/*` path) are reported the same way. Re-typing that pattern here
# would be a second source of truth that drifts the moment either list changes —
# the issue calls this out explicitly — so it is extracted from agent_commit.sh at
# runtime instead.
_AGENT_COMMIT_SH="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/agent_commit.sh"

# _derive_reconcile_owned_pattern
#   Prints the exact `|`-joined case-pattern list out of agent_commit.sh's
#   `is_literal_file()`, e.g. `docs/*|CLAUDE.md|.claude/README.md|lambdas/web/platform_counts.py`.
#   Prints NOTHING if agent_commit.sh is missing or its shape changed enough that
#   the extraction no longer matches (function renamed, case arm restructured) —
#   the caller (`_is_reconcile_owned_path`) treats an empty pattern as "derivation
#   failed" and fails CLOSED, never treats an unclassifiable path as sanctioned.
_derive_reconcile_owned_pattern() {
  [[ -r "${_AGENT_COMMIT_SH}" ]] || return 0
  awk '
    /^is_literal_file\(\)/ { infn = 1; next }
    infn && /return 0 ;;/ {
      line = $0
      sub(/^[[:space:]]*/, "", line)
      sub(/\)[[:space:]]*return 0 ;;.*/, "", line)
      print line
      exit
    }
    infn && /^}/ { exit }
  ' "${_AGENT_COMMIT_SH}" 2>/dev/null
}

# _is_reconcile_owned_path <repo-relative-path>
#   True iff <path> matches the pattern derived above. Deliberately NOT a bare
#   `case "$path" in $pattern)` — an unquoted `|`-joined variable used as a case
#   pattern does NOT act as an alternation list in bash (the `|` produced by an
#   expansion is a literal character, not a separator; a `case` needs it literally
#   in the script source to split alternatives) — verified empirically while
#   building this, it silently matched nothing at all. `@(pat1|pat2|...)` extglob
#   syntax fixes that, but `bash -n` (CI's shell-syntax-check job, ci-lint.yml
#   #2881) parses this file WITHOUT ever running a `shopt -s extglob` that lives
#   later in the same file, so extglob patterns fail bash -n outright. Splitting
#   the pattern into an array on `|` and matching each one individually against
#   plain `[[ == ]]` globbing sidesteps both problems — no extglob needed, no
#   alternation-list footgun. `read -ra` (not an unquoted `(${pattern})` array
#   assignment) is deliberate too: the latter also performs PATHNAME expansion on
#   each word, so `docs/*` would silently expand against whatever files happen to
#   exist in the CURRENT directory instead of staying a literal pattern — caught
#   live while building this (see tests/test_wait_pr_green.py's regression proof).
_is_reconcile_owned_path() {
  local path="$1"
  local pattern_str
  pattern_str="$(_derive_reconcile_owned_pattern)"
  [[ -n "${pattern_str}" ]] || return 1
  local -a patterns
  IFS='|' read -ra patterns <<<"${pattern_str}"
  local pat
  for pat in "${patterns[@]}"; do
    [[ "${path}" == ${pat} ]] && return 0
  done
  return 1
}

# _extract_wiki_drift_files <raw log text on stdin>
#   Pulls the file list out of sync_doc_metadata.py --check's own
#   "❌ CHECK FAILED — N stale literal(s) across M file(s):" block — one
#   "     - <path>" line per file, terminated by the "Fix:" line (see
#   deploy/sync_doc_metadata.py's `main()`). Ground-truthed against the real
#   bytes of run 32998950747 / job 98275389042 (#3200), which is tab-prefixed by
#   `gh run view --job --log` as `JOBNAME<TAB>STEPNAME<TAB>TIMESTAMPZ<content>` —
#   this takes awk's `$NF` (the last tab-separated field) so it works unprefixed
#   too (e.g. raw `gh api .../logs` text), not just the `gh run view` shape.
#   Pure text processing — no gh, no network — fully unit-testable on its own.
_extract_wiki_drift_files() {
  awk -F'\t' '
    {
      msg = $NF
      sub(/^[0-9TZ:.\-]+Z[[:space:]]?/, "", msg)
      if (msg ~ /CHECK FAILED/) { collecting = 1; next }
      if (collecting && msg ~ /^[[:space:]]*Fix:/) { collecting = 0; next }
      if (collecting) {
        line = msg
        gsub(/^[[:space:]]*-[[:space:]]*/, "", line)
        gsub(/[[:space:]]+$/, "", line)
        if (line != "") print line
      }
    }
  '
}

# ── #3219: the zero-checks-attached diagnosis ────────────────────────────────
#
# THE INCIDENT (Session E, 2026-08-26, twice in one session). PR #3215 at
# 5213b364 and PR #3214 at 769905bd each printed `0/7 green` every 30s until the
# operator went and checked by hand. Both were genuine event swallows —
# `actions/runs?head_sha=<full40>` returned `total_count=0` — and in both cases
# that discriminating fact was available on the FIRST poll. `0/7 green` at 30s and
# `0/7 green` at 300s render identically, so the script's own output never told
# anyone to go look. ~10 minutes of dead polling, twice.
#
# What is NOT claimed: that waiting is wrong. Checks legitimately take time to
# attach and a watcher that bailed on the first empty poll would be worse than
# this bug. What is added is a NAMED DIAGNOSIS after a bounded grace, not a faster
# failure — and only when ZERO checks have attached, never when some have.
#
# THE CLASSIFICATION IS NOT REIMPLEMENTED HERE. `scripts/check_main_green.py`
# already owns it (`classify_zero_run_head`, #2826/#3212 — swallowed vs
# path-filter-skip vs bot-push-no-dispatch vs indeterminate) together with the
# impure fetch that feeds it (`diagnose_uncovered_head`, which issues the
# FULL-40-char runs query and reads the commit's file list and committer). #3212
# exists precisely because that logic lived inside one consumer and a second
# consumer could not reach it; a second COPY would be the same bug with extra
# steps. This script shells out to that module and reads its JSON.
#
# The command is overridable for tests (`WAIT_PR_GREEN_CLASSIFY_CMD`) — the only
# way to exercise the diagnosis offline, since the real one needs the network.
_WAIT_PR_GREEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
CLASSIFY_CMD="${WAIT_PR_GREEN_CLASSIFY_CMD:-python3 ${_WAIT_PR_GREEN_DIR}/../scripts/check_main_green.py --classify-sha}"

# The states, named once. Keyed off check_main_green.py's own vocabulary — never
# off a phrase in the reason text (the #3199 lesson: every phrase-matched
# suppressor in this repo has failed in the field).
ZC_SWALLOWED="swallowed"

# ── #3318: the closing set, asserted at the moment before the merge ──────────
#
# THE CLASS. A `Fixes #N` closes N on merge whether or not N's work is in the PR:
# two lanes sharing one `pr_body.md` published each other's `Fixes` (#3222 via PR
# #3226), and a body that named a box "not satisfied" still carried `Fixes #2848`
# (PR #3253). Both were found by a human days later.
#
# WHY THIS SEAM. This script is the one sanctioned pre-merge watcher (#3103): every
# merge is preceded by its verdict, so this is the last read of the PR body before
# `gh pr merge`. pr-checks.yml cannot be the seam — it fires on push, not on a body
# edit (no `types: [edited]`), and the stray-Fixes class arrives via `gh pr edit`.
# The check is NOT reimplemented in bash: scripts/check_pr_closing_set.py owns the
# grammar and the verdict vocabulary (`CLOSING-SET VERDICT OK|NONGREEN|UNAVAILABLE`),
# derived from scripts/closure_contract.py; this function forwards its output and
# reads its exit code. Advisory (`warn`) today — exit 0 whatever it finds; the
# documented flip to `block` (CLOSURE_CONTRACT_MODE, or the registry's DEFAULT_MODE)
# turns a NONGREEN closing set into this watcher's exit 1. Runs ONLY on the
# merge-eligible verdicts (0 and 4) — a red or a timeout is not about to merge.
#
# ABSENCE IS LOUDER THAN FAILURE: if the script cannot run at all, a
# `CLOSING-SET VERDICT UNAVAILABLE` line is printed — the line is never silently
# missing. Overridable for tests (`WAIT_PR_GREEN_CLOSING_SET_CMD`); the PR number is
# appended as the last argument.
CLOSING_SET_CMD="${WAIT_PR_GREEN_CLOSING_SET_CMD:-python3 ${_WAIT_PR_GREEN_DIR}/../scripts/check_pr_closing_set.py --repo ${REPO} --pr}"

# _closing_set_check <pr>
#   Prints the script's CLOSING-SET lines verbatim. Returns 0 when the script exited 0
#   (OK, or any verdict under the advisory posture), 1 when it exited non-zero (block
#   posture: NONGREEN or UNAVAILABLE) or could not run at all — in which case the
#   UNAVAILABLE line is printed HERE, so the closing set is never silently unasserted.
_closing_set_check() {
  local pr="$1" out rc
  out=$(${CLOSING_SET_CMD} "${pr}" 2>&1)
  rc=$?
  if [[ "${out}" != *"CLOSING-SET"* ]]; then
    # The detector's contract is that it ALWAYS prints a CLOSING-SET line; anything else
    # (command not found = 127, an import error, an empty run) means it did not run.
    echo "CLOSING-SET VERDICT UNAVAILABLE — '${CLOSING_SET_CMD} ${pr}' exited ${rc} without a verdict line; the closing set was NOT asserted (#3318)"
    [[ -n "${out}" ]] && echo "  ${out}" | head -5
    return 1
  fi
  echo "${out}"
  if [[ "${rc}" -ne 0 ]]; then
    echo "CLOSING-SET blocked the verdict (closure-contract posture is block; script exit ${rc}) — fix the PR's closing set before merging."
    return 1
  fi
  return 0
}

# classify_zero_check_diagnosis <classifier-json>
#   Pure — takes the classifier's JSON, prints the operator-facing lines, and
#   returns 5 for a CONFIRMED swallow (stop, this will never attach) or 0 for
#   every other state (say what it is, keep polling). Unreadable or unparseable
#   JSON returns 0 with a NOTE: a diagnosis that cannot be made must degrade to
#   the pre-#3219 behaviour of waiting, never to a manufactured swallow — crying
#   swallow on ordinary attach latency is worse than the bug being fixed.
classify_zero_check_diagnosis() {
  local raw="$1"
  local state reason
  state=$(jq -r '.state // ""' <<<"${raw}" 2>/dev/null)
  reason=$(jq -r '.reason // ""' <<<"${raw}" 2>/dev/null)
  if [[ -z "${state}" ]]; then
    echo "NOTE zero-check diagnosis unavailable (classifier returned nothing usable) — continuing to poll."
    return 0
  fi
  if [[ "${state}" == "${ZC_SWALLOWED}" ]]; then
    echo "SWALLOWED-PUSH ${reason}"
    echo "  The push minted no workflow run of any kind at this head sha. No check will ever attach."
    echo "  Recovery ladder (docs/CONVENTIONS.md, reference_github_event_swallow_recovery.md):"
    echo "    1. close/reopen the PR   — gh pr close <pr> && gh pr reopen <pr>"
    echo "    2. supersede-PR          — new branch off the same tree, open a fresh PR"
    echo "    3. integration train     — fold the branch into the driver's train and let that PR earn the checks"
    return 5
  fi
  echo "DIAGNOSIS ${state} — ${reason}"
  echo "  Not a swallow. Continuing to poll (this state is expected to resolve or to stay empty by design)."
  return 0
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
#     RECONCILE-OWNED-RED <name>: <path>[, <path>...]   (#3200, "Wiki drift
#       gates" only — see below)
#   then a final line:
#     VERDICT SUCCESS|PENDING|WAITING|FAIL|GREEN-WITH-RECONCILE-OWNED-RED
#   Returns 0=SUCCESS, 3=PENDING (keep polling), 2=WAITING, 1=FAIL,
#   4=GREEN-WITH-RECONCILE-OWNED-RED.
#
#   #3200: when the expected check is literally "Wiki drift gates" and its
#   entry carries a `driftFiles` array (that gate's own ❌ file list — real
#   mode: `_enrich_wiki_drift_checks_json`; fixture mode: put it directly in
#   the fixture JSON), a bucket=fail/skipping/cancel state that would
#   otherwise be a plain NONGREEN is instead classified: if EVERY path in
#   `driftFiles` is reconcile-owned (`_is_reconcile_owned_path`, derived from
#   agent_commit.sh — never hand-listed), it's printed as RECONCILE-OWNED-RED
#   and rolled into `any_reconcile_owned_red`, not `any_nongreen`. An empty or
#   absent `driftFiles`, or ANY path that isn't reconcile-owned, falls straight
#   through to the plain NONGREEN path below — fail-closed by construction, and
#   a second red check (any other expected name failing) still fails the whole
#   set exactly as before (`any_nongreen` wins the verdict priority below).
evaluate_checks_json() {
  local checks_json="$1"
  shift
  local -a expected=("$@")
  local any_waiting=0 any_nongreen=0 any_pending=0 any_reconcile_owned_red=0
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
      #
      # #3200: ONE exception. "Wiki drift gates" failing because
      # sync_doc_metadata.py --check named ONLY reconcile-owned paths is not a
      # real red — see the header comment above and this function's docstring.
      local classified=0
      if [[ "${exp}" == "Wiki drift gates" ]]; then
        local drift_json drift_count all_owned dpath
        drift_json=$(jq -c '.driftFiles // empty' <<<"${entry}" 2>/dev/null)
        if [[ -n "${drift_json}" && "${drift_json}" != "null" ]]; then
          drift_count=$(jq 'length' <<<"${drift_json}" 2>/dev/null || echo 0)
          if [[ "${drift_count}" -gt 0 ]]; then
            all_owned=1
            while IFS= read -r dpath; do
              [[ -n "${dpath}" ]] || continue
              _is_reconcile_owned_path "${dpath}" || all_owned=0
            done < <(jq -r '.[]' <<<"${drift_json}")
            if [[ "${all_owned}" -eq 1 ]]; then
              echo "RECONCILE-OWNED-RED ${exp}: $(jq -r 'join(", ")' <<<"${drift_json}")"
              any_reconcile_owned_red=1
              classified=1
            fi
          fi
        fi
      fi
      if [[ "${classified}" -eq 0 ]]; then
        echo "NONGREEN ${exp} ${state:-${bucket}}"
        any_nongreen=1
      fi
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
  if [[ "${any_reconcile_owned_red}" -eq 1 ]]; then
    echo "VERDICT GREEN-WITH-RECONCILE-OWNED-RED"
    return 4
  fi
  echo "VERDICT SUCCESS"
  return 0
}

# ── real-mode-only enrichment (#3200) — the ONLY function here that shells out ──
#
# _enrich_wiki_drift_checks_json <checks-json>
#   When "Wiki drift gates" is present in <checks-json> and bucket=fail, fetches
#   that check's own job (via its `link` field, an `.../actions/runs/<run>/job/
#   <job>` URL — `gh pr checks` must be called with `--json ...,link` for this to
#   have anything to read) and, IFF the literal-drift-gate step is the ONLY
#   failing step in that job — every gate step there runs `if: always()` (#749:
#   one red never masks the rest), so a second, unrelated gate could fail
#   alongside it in the same job, and that must never be swept in — pulls its ❌
#   file list and stamps it onto the entry as `driftFiles` for
#   evaluate_checks_json to classify.
#
#   ANY failure along this path (no link, `gh api` error, empty file list,
#   another step also failed) leaves checks_json byte-for-byte UNTOUCHED —
#   fail-closed to the pre-#3200 plain-NONGREEN path, never guessed.
#   Not unit-tested directly (it is nothing but `gh`/`jq` plumbing); the logic it
#   feeds (`evaluate_checks_json` + `_is_reconcile_owned_path`) is the part that
#   is mutation-proved, via fixtures that supply `driftFiles` directly.
#
#   #3209: the job log is fetched via the raw REST endpoint
#   (`gh api repos/.../actions/jobs/<job>/logs`), NOT `gh run view --job --log`.
#   The latter was the #3200 original and is reliably wrong: for job 98291682348
#   it returned a log covering every OTHER step in the job (404-shaped lines)
#   while omitting the one step that actually failed — reproduced twice, and
#   inconsistent job-to-job (an earlier job on the same workflow/step DID
#   return it via `gh run view`). The raw endpoint returned the failing step's
#   own `CHECK FAILED` block reliably. `_extract_wiki_drift_files` already
#   parses this endpoint's unprefixed-text shape unmodified (it was written to
#   take awk's `$NF`, so a leading `TIMESTAMP<TAB>` prefix is optional) — only
#   the log SOURCE changed here, not the parser.
_enrich_wiki_drift_checks_json() {
  local checks_json="$1"
  local entry bucket link jobid steps_json other_fail raw_log drift_files drift_files_json

  entry=$(jq -c '[.[] | select(.name == "Wiki drift gates")] | .[0] // empty' <<<"${checks_json}" 2>/dev/null)
  if [[ -z "${entry}" || "${entry}" == "null" ]]; then
    printf '%s' "${checks_json}"
    return 0
  fi
  bucket=$(jq -r '.bucket // ""' <<<"${entry}")
  if [[ "${bucket}" != "fail" ]]; then
    printf '%s' "${checks_json}"
    return 0
  fi

  link=$(jq -r '.link // ""' <<<"${entry}")
  jobid="${link##*/job/}"
  if [[ -z "${link}" || "${jobid}" == "${link}" || -z "${jobid}" ]]; then
    printf '%s' "${checks_json}"
    return 0
  fi

  steps_json=$(gh api "repos/${REPO}/actions/jobs/${jobid}" --jq '.steps' 2>/dev/null) || {
    printf '%s' "${checks_json}"
    return 0
  }
  other_fail=$(jq -r '[.[] | select(.conclusion == "failure" and .name != "Literal-drift gate (sync_doc_metadata --check)")] | length' <<<"${steps_json}" 2>/dev/null)
  if [[ "${other_fail}" != "0" ]]; then
    printf '%s' "${checks_json}"
    return 0
  fi

  raw_log=$(gh api "repos/${REPO}/actions/jobs/${jobid}/logs" 2>/dev/null) || {
    printf '%s' "${checks_json}"
    return 0
  }
  drift_files=$(_extract_wiki_drift_files <<<"${raw_log}")
  if [[ -z "${drift_files}" ]]; then
    printf '%s' "${checks_json}"
    return 0
  fi

  drift_files_json=$(printf '%s\n' "${drift_files}" | jq -R . | jq -s .)
  jq --argjson df "${drift_files_json}" \
    'map(if .name == "Wiki drift gates" then . + {driftFiles: $df} else . end)' \
    <<<"${checks_json}" 2>/dev/null || printf '%s' "${checks_json}"
}

# ── CLI driver ─────────────────────────────────────────────────────────────

_usage() {
  cat <<'USAGE'
usage: deploy/wait_pr_green.sh <pr-number> [--expect "Check name"]...
                                [--timeout SECONDS] [--interval SECONDS]
                                [--zero-check-grace SECONDS]
                                [--no-derive] [--repo OWNER/REPO]
       deploy/wait_pr_green.sh --fixture FILE [--expect "Check name"]... [--no-derive]

Waits for a PR's checks to go green by NAME. Never merges — prints a verdict and
exits. See the header comment in this file for the full discipline this encodes.
USAGE
}

main() {
  local pr="" fixture="" timeout=1800 interval=30 no_derive=0
  local zero_check_grace="${WAIT_PR_GREEN_ZERO_CHECK_GRACE:-120}"
  local -a extra_expect=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --expect)
        extra_expect+=("$2")
        shift 2
        ;;
      --zero-check-grace)
        zero_check_grace="$2"
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

  echo "Zero-check grace: ${zero_check_grace}s (then the #3219 swallow diagnosis runs at the full 40-char sha)"

  local start now elapsed checks_json out rc
  # #3219 state. `saw_attach` latches on the first poll that sees ANY check: the
  # diagnosis is for "nothing ever attached", and a PR whose checks arrived and
  # then went quiet is a different animal that this must not misdiagnose.
  # `diagnosed` keeps a non-swallow verdict from reprinting every interval.
  local attached=0 saw_attach=0 diagnosed=0 diag_out diag_rc
  start=$(date +%s)
  while true; do
    now=$(date +%s)
    elapsed=$((now - start))
    if [[ "${elapsed}" -ge "${timeout}" ]]; then
      echo "TIMEOUT after ${elapsed}s (budget ${timeout}s) — last known state:"
      checks_json=$(gh pr checks "${pr}" --repo "${REPO}" --json name,state,bucket,link 2>/dev/null || echo '[]')
      checks_json=$(_enrich_wiki_drift_checks_json "${checks_json}")
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

    checks_json=$(gh pr checks "${pr}" --repo "${REPO}" --json name,state,bucket,link 2>/dev/null || echo '[]')
    checks_json=$(_enrich_wiki_drift_checks_json "${checks_json}")

    # #3219: how many checks have ATTACHED at all — the fact the old progress
    # line could not express. `0/7 green` was printed identically whether seven
    # checks were queued or none existed.
    attached=$(jq 'length' <<<"${checks_json}" 2>/dev/null || echo 0)
    [[ "${attached}" -gt 0 ]] && saw_attach=1

    if [[ "${attached}" -eq 0 && "${saw_attach}" -eq 0 && "${diagnosed}" -eq 0 && "${elapsed}" -ge "${zero_check_grace}" ]]; then
      diagnosed=1
      echo "No check has attached in ${elapsed}s (grace ${zero_check_grace}s) — classifying head sha ${head_sha} (#3219)."
      # The FULL 40-char sha, never a prefix: a short-sha `actions/runs?head_sha=`
      # query returns empty and would SELF-CONFIRM a swallow (failure mode #1 in
      # this file's header). `head_sha` was length-checked at 40 above.
      diag_out=$(${CLASSIFY_CMD} "${head_sha}" 2>/dev/null || true)
      classify_zero_check_diagnosis "${diag_out}"
      diag_rc=$?
      if [[ "${diag_rc}" -eq 5 ]]; then
        echo "Stopping at ${elapsed}s — a swallowed push will never go green. This script never merges and never re-pushes."
        return 5
      fi
    fi

    out=$(evaluate_checks_json "${checks_json}" "${expected[@]}")
    rc=$?

    case "${rc}" in
      0)
        echo "${out}"
        echo "All ${#expected[@]} expected checks are GREEN (elapsed ${elapsed}s)."
        # #3318: the merge-eligible verdict is the seam — assert the closing set NOW,
        # against the body as it stands at this moment, before the caller reads GREEN.
        _closing_set_check "${pr}" || return 1
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
        # #3219: the two states get two visually distinct lines. They used to
        # render identically (`0/7 green`), which is why ~10 minutes of dead
        # polling on a swallowed push looked exactly like a healthy early run.
        local green_count
        green_count=$(grep -c '^GREEN ' <<<"${out}" || true)
        if [[ "${attached}" -eq 0 ]]; then
          echo "  ... ⧗ NO CHECKS ATTACHED YET — 0 of ${#expected[@]} expected are present at ${head_sha:0:8} (elapsed ${elapsed}s/${timeout}s, grace ${zero_check_grace}s), polling again in ${interval}s"
        else
          echo "  ... ${green_count}/${#expected[@]} green — ${attached} check(s) attached (elapsed ${elapsed}s/${timeout}s), polling again in ${interval}s"
        fi
        sleep "${interval}"
        ;;
      4)
        echo "${out}"
        echo "GREEN except a classified reconcile-owned red (elapsed ${elapsed}s) — see the RECONCILE-OWNED-RED line(s) above (#3200). This still never merges; the exit code (4) is the caller's own signal to name it and proceed."
        _closing_set_check "${pr}" || return 1 # #3318: exit 4 is merge-eligible too
        return 4
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
