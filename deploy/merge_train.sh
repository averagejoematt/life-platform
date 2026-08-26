#!/usr/bin/env bash
# merge_train.sh — merge-train mode for the reconcile ritual (#3104).
#
# ─────────────────────────────────────────────────────────────────────────────
# WHY THIS EXISTS — the measured cost, honestly scoped.
#
# #3104 was filed when SIX doc-sync counters lived in hand-merged files and every
# concurrent PR conflicted with every other one. #3101 (merged 2026-08-24, PR
# #3131) killed that class: the counters moved into the generated single-writer
# module `lambdas/web/platform_counts.py`, which `deploy/agent_commit.sh` refuses
# to stage at all. Session A therefore DEPRIORITIZED this issue with a dated
# comment — correctly, because most of the motivation had just evaporated.
#
# The residual is real and was measured on the following session's 9-PR train:
# the ONE remaining single-writer literal (`test_count`, in the generated module)
# still invalidates every other green PR's counter on every merge, because a
# branch that lands a test moves the derived count for all the others. That train
# paid ~8 serial rebase + regenerate + full-recheck cycles at ~20 min each. The
# class is NARROWER than when filed — one file, one writer, no hand-merged
# literals — but it is not gone, and the tax is serial by construction.
#
# The train's actual saving is structural, not clever: N PRs are verified green
# ONCE, reconciled onto a single accumulating tip, validated ONCE as a stack, and
# then merged back-to-back. Only a PR that genuinely conflicts pays a re-check.
# In the common post-#3101 case (no branch carries the counter file) NOTHING is
# force-pushed and NOTHING is re-checked — the train is a green-gate + a stacked
# offline validation + N merges.
#
# ─────────────────────────────────────────────────────────────────────────────
# WHAT IT DOES
#
#   Phase 1  GREEN GATE. For every PR, `deploy/wait_pr_green.sh` (the ONE
#            sanctioned watcher, #3103) is invoked as a subprocess. Its
#            derive/assert-by-name machinery is REUSED, never reimplemented —
#            there is no `gh pr checks` call and no `actions/runs?head_sha=`
#            query anywhere in this file. A non-green PR drops out of the train
#            with a named reason; the rest continue.
#
#   Phase 2  RECONCILE. A throwaway detached worktree is created (the caller's
#            checkout is NEVER touched). The train tip starts at
#            origin/<base>. Each surviving PR's head is rebased onto the current
#            tip in order:
#              • no conflict            → replayed as-is, tip advances
#              • conflict ONLY on a regenerable counter path → resolved by taking
#                the tip's copy and re-deriving with `sync_doc_metadata.py
#                --apply`, then the rebase continues
#              • ANY other conflicted file → the rebase is ABORTED, the PR drops
#                out of the train, and the offending paths are named. This
#                refusal is loud and total: a mixed conflict (counter + anything
#                else) refuses too. Auto-resolving a file with authored content
#                is how work gets silently destroyed (#2897); this script will
#                not do it.
#
#   Phase 3  STACKED VALIDATION. The final tip IS main + all N reconciled
#            branches (sequential rebase produces the stack for free). On that
#            tip, OFFLINE only:
#              1. `sync_doc_metadata.py --apply`, then `--check`. NOTE: `--check`
#                 is EXPECTED to fail on the stack BEFORE the apply — main's
#                 committed counter is stale relative to main+N-PRs' worth of new
#                 tests by construction. What is being proven is that the
#                 counters are cleanly DERIVABLE over the union, and the printed
#                 delta is exactly what the reconcile bot will write post-merge.
#                 The apply is discarded; the validation branch is never pushed.
#              2. the deploy-critical offline test subset (override with
#                 `--gate-cmd`; `--full-gate` selects the `premerge` lane).
#            A gate failure aborts the train before ANY merge, and the worktree
#            is left in place so the driver can inspect it.
#
#   Phase 4  MERGE. Each surviving PR is squash-merged in train order. Per the
#            #3103 discipline the verdict-read and the merge are SEPARATE
#            commands — never chained with `&&`, never in one compound command
#            (the exact shape that redded main twice on 2026-08-23/24). The first
#            merge failure ABORTS the whole train; every PR after it is reported
#            NOT-ATTEMPTED, never quietly skipped.
#
#   Phase 5  REPORT. One table: per-PR disposition (merged sha / dropped + why /
#            not-attempted + why).
#
# ─────────────────────────────────────────────────────────────────────────────
# SAFETY RAILS
#
#   • Never force-pushes a branch this run did not have to change. A branch is
#     pushed ONLY when a counter conflict was actually resolved on it, and then
#     only with `--force-with-lease=<branch>:<the exact sha gh reported>` — so a
#     concurrent push by the PR's own agent aborts the push instead of
#     overwriting it.
#   • Never pushes to a fork. A PR whose head lives in another repo drops out of
#     the train rather than being reconciled (we cannot own that branch).
#   • Never touches the caller's working tree — all git work happens in a
#     temporary `git worktree`, removed on success.
#   • Never merges `main` into anything, never pushes `main`, never deploys.
#   • `--dry-run` stops before EVERY mutation: no push, no merge. It still runs
#     the green gate, the reconcile, and the full stacked validation, so a
#     dry-run is a complete rehearsal.
#   • Abort-all on the first merge failure.
#
# ─────────────────────────────────────────────────────────────────────────────
# USAGE
#   deploy/merge_train.sh [options] <pr> [<pr> ...]
#
#     --dry-run            rehearse: everything except push and merge.
#     --base BRANCH        train base (default: main).
#     --repo OWNER/REPO    default averagejoematt/life-platform.
#     --remote NAME        git remote (default: origin).
#     --green-timeout SEC  per-PR budget handed to wait_pr_green.sh (default 1800).
#     --gate-cmd 'CMD'     replace the offline test gate command.
#     --full-gate          use the `premerge` lane instead of `deploy_critical`.
#     --skip-gate          skip the offline test gate (sync --check still runs).
#     --keep-worktree      keep the scratch worktree even on success.
#
# EXIT CODES
#   0  every PR in the train reached its intended terminal state (merged, or
#      dry-run-rehearsed) with no drops.
#   1  the train aborted (gate failure, merge failure) or at least one PR
#      dropped out. The report names every disposition either way.
#   2  bad arguments / unusable environment.
#
# SOURCEABLE for tests: `source deploy/merge_train.sh --source-only` exposes
# `classify_conflicts`, `reconcile_branch_onto`, `push_reconciled` and `merge_pr`
# without running main — see tests/test_merge_train_3104.py, which drives them
# against synthetic `git init` repos with no network and no `gh`.
#
# KNOWN REPO GOTCHA: `.claude/commands/reconcile-branch.md` §4 documents a
# `rebase --continue` phantom wedge. This script does not try to unwedge it — if
# `--continue` refuses, the PR is aborted out of the train and named, and the
# driver works that one PR by hand with the documented recipe.

set -uo pipefail

REPO="${MERGE_TRAIN_REPO:-averagejoematt/life-platform}"
REMOTE="${MERGE_TRAIN_REMOTE:-origin}"
BASE_BRANCH="${MERGE_TRAIN_BASE:-main}"
DRY_RUN="${MERGE_TRAIN_DRY_RUN:-0}"
GREEN_TIMEOUT="${MERGE_TRAIN_GREEN_TIMEOUT:-1800}"
KEEP_WORKTREE="${MERGE_TRAIN_KEEP_WORKTREE:-0}"
SKIP_GATE="${MERGE_TRAIN_SKIP_GATE:-0}"

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WAIT_PR_GREEN="${MERGE_TRAIN_WAIT_SCRIPT:-${_SCRIPT_DIR}/wait_pr_green.sh}"

# The regenerator is injectable ONLY so the offline tests can drive the conflict
# machinery in a synthetic repo that has no deploy/ tree. In every real run this
# is the single sanctioned writer of the counter module (#3101).
REGEN_CMD="${MERGE_TRAIN_REGEN_CMD:-python3 deploy/sync_doc_metadata.py --apply}"
CHECK_CMD="${MERGE_TRAIN_CHECK_CMD:-python3 deploy/sync_doc_metadata.py --check}"
GATE_CMD="${MERGE_TRAIN_GATE_CMD:-}"

# ── the ONLY paths a conflict may be auto-resolved on ────────────────────────
#
# Exactly one entry, deliberately. `lambdas/web/platform_counts.py` is GENERATED
# in full — every byte is re-derivable from the repo — so taking the tip's copy
# and re-deriving cannot destroy authored work. `docs/ARCHITECTURE.md` and
# `docs/INFRASTRUCTURE.md` mirror the same literals but ALSO carry authored
# prose, so they are deliberately NOT on this list: a conflict there is a human's
# problem, not a regeneration.
REGENERABLE_PATHS=("lambdas/web/platform_counts.py")

is_regenerable_path() {
  local candidate="$1" p
  for p in "${REGENERABLE_PATHS[@]}"; do
    [[ "${candidate}" == "${p}" ]] && return 0
  done
  return 1
}

# classify_conflicts <newline-separated conflicted paths>
#   Prints exactly one classification line and returns:
#     0  CLASSIFY CLEAN                       — no conflicted paths at all
#     3  CLASSIFY REGENERABLE <paths...>      — every conflict is a generated
#                                               counter path, safe to re-derive
#     1  CLASSIFY REFUSE <offending paths...> — at least one conflict is on a
#                                               file with authored content
#
#   A MIXED conflict set (counter + something else) returns REFUSE. That is the
#   load-bearing case: "one of the conflicts is the counter" must never be enough
#   to trigger an automatic resolution of the others.
classify_conflicts() {
  local raw="${1:-}"
  local line
  local -a offending=()
  local -a regenerable=()

  while IFS= read -r line; do
    [[ -n "${line}" ]] || continue
    if is_regenerable_path "${line}"; then
      regenerable+=("${line}")
    else
      offending+=("${line}")
    fi
  done <<<"${raw}"

  if [[ ${#offending[@]} -gt 0 ]]; then
    echo "CLASSIFY REFUSE ${offending[*]}"
    return 1
  fi
  if [[ ${#regenerable[@]} -gt 0 ]]; then
    echo "CLASSIFY REGENERABLE ${regenerable[*]}"
    return 3
  fi
  echo "CLASSIFY CLEAN"
  return 0
}

_conflicted_paths() {
  git diff --name-only --diff-filter=U 2>/dev/null | sort -u
}

# reconcile_branch_onto <train_tip> <src_ref> <out_branch>
#   Runs in the CURRENT git worktree. Creates <out_branch> at <src_ref> and
#   rebases it onto <train_tip>, resolving counter-file conflicts by
#   regeneration and refusing everything else.
#
#   Prints, as its LAST line, one of:
#     RECONCILED <sha> resolved=0     — replayed cleanly, branch unchanged in
#                                       content; the PR needs no force-push
#     RECONCILED <sha> resolved=1     — a counter conflict was resolved; this
#                                       branch differs from what the PR's agent
#                                       pushed, so it must be pushed + re-checked
#     DROPPED <reason>
#   Returns 0 on RECONCILED, 1 on DROPPED.
reconcile_branch_onto() {
  local train_tip="$1" src_ref="$2" out_branch="$3"
  local resolved=0 guard=0 classification rc path

  if ! git checkout -q -B "${out_branch}" "${src_ref}" 2>/dev/null; then
    echo "DROPPED could-not-check-out ${src_ref}"
    return 1
  fi

  if git rebase --quiet "${train_tip}" >/dev/null 2>&1; then
    echo "RECONCILED $(git rev-parse HEAD) resolved=0"
    return 0
  fi

  # The rebase stopped. Either it conflicted (the interesting case) or it failed
  # for a reason we do not attempt to interpret — both are handled below, and any
  # rebase still in progress is always aborted before we return.
  while true; do
    guard=$((guard + 1))
    if [[ "${guard}" -gt 50 ]]; then
      git rebase --abort >/dev/null 2>&1
      echo "DROPPED rebase-did-not-converge-after-50-resolutions"
      return 1
    fi

    if [[ ! -d "$(git rev-parse --git-path rebase-merge)" && ! -d "$(git rev-parse --git-path rebase-apply)" ]]; then
      # No rebase in progress and we got here from a nonzero rebase — the rebase
      # failed outright rather than stopping on a conflict.
      echo "DROPPED rebase-failed-without-a-conflict-to-resolve"
      return 1
    fi

    local conflicted
    conflicted="$(_conflicted_paths)"
    classification="$(classify_conflicts "${conflicted}")"
    rc=$?

    if [[ "${rc}" -eq 1 ]]; then
      git rebase --abort >/dev/null 2>&1
      echo "DROPPED conflict-on-non-regenerable-path: ${classification#CLASSIFY REFUSE }"
      return 1
    fi
    if [[ "${rc}" -eq 0 ]]; then
      # Stopped with nothing unmerged — not a conflict this script can act on.
      git rebase --abort >/dev/null 2>&1
      echo "DROPPED rebase-stopped-with-no-unmerged-paths"
      return 1
    fi

    # ── REGENERABLE: take the tip's copy, then re-derive over the merged tree ──
    while IFS= read -r path; do
      [[ -n "${path}" ]] || continue
      if git cat-file -e "${train_tip}:${path}" 2>/dev/null; then
        git checkout "${train_tip}" -- "${path}" || {
          git rebase --abort >/dev/null 2>&1
          echo "DROPPED could-not-restore-${path}-from-train-tip"
          return 1
        }
      else
        git rm -q -f -- "${path}" 2>/dev/null || true
      fi
    done <<<"${conflicted}"

    if ! (eval "${REGEN_CMD}") >/dev/null 2>&1; then
      git rebase --abort >/dev/null 2>&1
      echo "DROPPED regeneration-command-failed"
      return 1
    fi

    while IFS= read -r path; do
      [[ -n "${path}" ]] || continue
      [[ -e "${path}" ]] && git add -- "${path}"
    done <<<"${conflicted}"

    # Discard the regenerator's COLLATERAL edits (it also rewrites doc mirrors).
    # `git checkout -- .` restores the worktree from the INDEX, which already
    # holds this commit's own replayed content — so the PR's substance survives
    # and only the sweep is dropped. Nothing on the branch carries a counter, by
    # construction (#3101), so there is nothing else to lose here.
    git checkout -- . >/dev/null 2>&1

    resolved=1

    if git diff --cached --quiet; then
      # The replayed commit is now empty (its whole content was the counter).
      if ! GIT_EDITOR=true git rebase --skip >/dev/null 2>&1; then
        if [[ -d "$(git rev-parse --git-path rebase-merge)" || -d "$(git rev-parse --git-path rebase-apply)" ]]; then
          continue
        fi
        echo "DROPPED rebase-skip-failed"
        return 1
      fi
    else
      if ! GIT_EDITOR=true git rebase --continue >/dev/null 2>&1; then
        if [[ -d "$(git rev-parse --git-path rebase-merge)" || -d "$(git rev-parse --git-path rebase-apply)" ]]; then
          continue # stopped again on the next commit's conflict — classify it too
        fi
        echo "DROPPED rebase-continue-refused (see reconcile-branch.md §4, the phantom wedge)"
        return 1
      fi
    fi

    if [[ ! -d "$(git rev-parse --git-path rebase-merge)" && ! -d "$(git rev-parse --git-path rebase-apply)" ]]; then
      echo "RECONCILED $(git rev-parse HEAD) resolved=${resolved}"
      return 0
    fi
  done
}

# push_reconciled <local_branch> <remote_branch> <expected_remote_sha>
#   The ONLY mutating git call in this script, and it is leased: if the remote
#   branch is not exactly <expected_remote_sha> (i.e. the PR's own agent pushed
#   while the train was running), the push is REFUSED rather than clobbering it.
push_reconciled() {
  local local_branch="$1" remote_branch="$2" expected_sha="$3"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "DRY-RUN would force-push (leased on ${expected_sha}): ${local_branch} -> ${REMOTE}/${remote_branch}"
    return 0
  fi
  git push --force-with-lease="${remote_branch}:${expected_sha}" \
    "${REMOTE}" "${local_branch}:refs/heads/${remote_branch}"
}

# merge_pr <pr>
#   Deliberately a function of ONE line of gh, containing no verdict logic at
#   all. The caller reads wait_pr_green.sh's verdict in its own command and only
#   then calls this — the two are never chained (#3103).
merge_pr() {
  local pr="$1"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "DRY-RUN would merge PR #${pr} (squash) — stopping before the mutation"
    return 0
  fi
  gh pr merge "${pr}" --repo "${REPO}" --squash --delete-branch
}

# _watch_pr_green <pr>
#   The ONE call site both Phase 1 and Phase 4's post-rebase re-check use to
#   invoke deploy/wait_pr_green.sh — folded here (#3200) so the two identical
#   blocks that used to exist independently never drift from each other.
#   Streams the watcher's own output live, indented, exactly as before (`tee`
#   into a scratch file while piping through `sed` for the live view), then ALSO
#   reads that captured output back to classify wait_pr_green.sh's exit code:
#
#     rc 0            plain GREEN — proceed. _WATCH_RECONCILE_RED is cleared.
#     rc 4 (#3200)    GREEN-WITH-RECONCILE-OWNED-RED — also proceed, but
#                     _WATCH_RECONCILE_RED is set to the comma-joined path list
#                     off the watcher's own "RECONCILE-OWNED-RED <name>: <paths>"
#                     line, so the caller can name it in the train report
#                     instead of reporting a bare, unqualified "green".
#     anything else   passed straight through UNCHANGED (1=FAIL, 2=WAITING) —
#                     this function does not remap or reinterpret a real
#                     failure, it only adds a second "proceed" outcome next to
#                     the existing one. The #3103 discipline is unchanged: this
#                     reads wait_pr_green.sh's verdict and returns; the merge
#                     itself is always the caller's own, later, separate call.
_WATCH_RECONCILE_RED=""
_watch_pr_green() {
  local pr="$1" tmp rc out
  tmp="$(mktemp "${TMPDIR:-/tmp}/merge-train-watch.XXXXXX")"
  bash "${WAIT_PR_GREEN}" "${pr}" --repo "${REPO}" --timeout "${GREEN_TIMEOUT}" 2>&1 | tee "${tmp}" | sed 's/^/    /'
  rc="${PIPESTATUS[0]}"
  out="$(cat "${tmp}")"
  rm -f "${tmp}"
  _WATCH_RECONCILE_RED=""
  if [[ "${rc}" -eq 4 ]]; then
    _WATCH_RECONCILE_RED="$(printf '%s\n' "${out}" | sed -n 's/^RECONCILE-OWNED-RED [^:]*: //p' | paste -sd '; ' -)"
  fi
  return "${rc}"
}

# ── the offline stacked validation ───────────────────────────────────────────
run_offline_gate() {
  local rc=0
  echo ""
  echo "── stacked validation: counter derivation ───────────────────────────"
  # See the header: --check is EXPECTED to be red here before the apply, because
  # main's committed counter is stale relative to main + N PRs' new tests. What
  # matters is that the apply resolves it and --check then passes.
  if ! (eval "${REGEN_CMD}"); then
    echo "GATE FAIL: the regenerator (${REGEN_CMD}) failed on the stacked tree"
    return 1
  fi
  echo ""
  echo "counter delta the reconcile bot will write post-merge:"
  git --no-pager diff --stat -- "${REGENERABLE_PATHS[@]}" || true
  git --no-pager diff -- "${REGENERABLE_PATHS[@]}" | grep -E '^[+-][A-Za-z_" ]' || true
  if ! (eval "${CHECK_CMD}") >/dev/null 2>&1; then
    echo "GATE FAIL: ${CHECK_CMD} still reports drift AFTER a full regeneration —"
    echo "           the counters are not cleanly derivable over the stacked tree."
    rc=1
  else
    echo "counters re-derive cleanly over the stack (${CHECK_CMD} passes after --apply)."
  fi
  # The validation branch is local-only and never pushed; drop the apply so the
  # tip keeps exactly the union of the PRs' own content.
  git checkout -- . >/dev/null 2>&1
  [[ "${rc}" -ne 0 ]] && return 1

  if [[ "${SKIP_GATE}" -eq 1 ]]; then
    echo "offline test gate SKIPPED (--skip-gate)"
    return 0
  fi
  echo ""
  echo "── stacked validation: offline test gate ────────────────────────────"
  echo "\$ ${GATE_CMD}"
  if ! (eval "${GATE_CMD}"); then
    echo "GATE FAIL: the offline test gate failed on the stacked tree."
    return 1
  fi
  return 0
}

_usage() {
  cat <<'USAGE'
usage: deploy/merge_train.sh [options] <pr> [<pr> ...]

  --dry-run            rehearse everything; stop before any push or merge
  --base BRANCH        train base (default main)
  --repo OWNER/REPO    default averagejoematt/life-platform
  --remote NAME        git remote (default origin)
  --green-timeout SEC  per-PR budget for deploy/wait_pr_green.sh (default 1800)
  --gate-cmd 'CMD'     replace the offline test gate command
  --full-gate          use the `premerge` lane instead of `deploy_critical`
  --skip-gate          skip the offline test gate (counter derivation still runs)
  --keep-worktree      keep the scratch worktree even on success

Merges N green-but-counter-conflicting PRs as one train. See this file's header
for the full discipline (and #3104 for the measured churn that motivated it).
USAGE
}

main() {
  local -a prs=()
  local full_gate=0

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      --base)
        BASE_BRANCH="$2"
        shift 2
        ;;
      --repo)
        REPO="$2"
        shift 2
        ;;
      --remote)
        REMOTE="$2"
        shift 2
        ;;
      --green-timeout)
        GREEN_TIMEOUT="$2"
        shift 2
        ;;
      --gate-cmd)
        GATE_CMD="$2"
        shift 2
        ;;
      --full-gate)
        full_gate=1
        shift
        ;;
      --skip-gate)
        SKIP_GATE=1
        shift
        ;;
      --keep-worktree)
        KEEP_WORKTREE=1
        shift
        ;;
      -h | --help)
        _usage
        return 0
        ;;
      -*)
        echo "unrecognized option: $1" >&2
        _usage >&2
        return 2
        ;;
      *)
        if [[ ! "$1" =~ ^#?[0-9]+$ ]]; then
          echo "not a PR number: $1" >&2
          _usage >&2
          return 2
        fi
        prs+=("${1#\#}")
        shift
        ;;
    esac
  done

  if [[ ${#prs[@]} -eq 0 ]]; then
    _usage >&2
    return 2
  fi
  if [[ -z "${GATE_CMD}" ]]; then
    if [[ "${full_gate}" -eq 1 ]]; then
      GATE_CMD="python3 -m pytest tests/ -m 'premerge and not integration' -q --tb=short"
    else
      GATE_CMD="python3 -m pytest tests/ -m 'deploy_critical and not integration' -q --tb=short"
    fi
  fi
  for _bin in gh git jq python3; do
    command -v "${_bin}" >/dev/null 2>&1 || {
      echo "ERROR: required binary not found: ${_bin}" >&2
      return 2
    }
  done

  local root
  root="$(git rev-parse --show-toplevel)" || return 2

  # Parallel arrays (bash 3.2 — macOS ships no associative arrays).
  local -a dispo=() detail=() head_ref=() head_sha=() needs_push=() local_branch=() reconcile_red=()
  local i n
  n=${#prs[@]}
  for ((i = 0; i < n; i++)); do
    dispo+=("PENDING")
    detail+=("")
    head_ref+=("")
    head_sha+=("")
    needs_push+=("0")
    local_branch+=("")
    reconcile_red+=("")
  done

  echo "═══ MERGE TRAIN (#3104) ═════════════════════════════════════════════"
  echo "repo ${REPO} · base ${BASE_BRANCH} · ${n} PR(s): ${prs[*]}"
  [[ "${DRY_RUN}" -eq 1 ]] && echo "MODE: DRY RUN — no push, no merge, full rehearsal otherwise"
  echo ""

  # ── Phase 1: the green gate (wait_pr_green.sh, never reimplemented) ────────
  echo "── phase 1: green gate ───────────────────────────────────────────────"
  for ((i = 0; i < n; i++)); do
    local pr="${prs[$i]}"
    local meta
    meta="$(gh pr view "${pr}" --repo "${REPO}" --json headRefName,headRefOid,headRepositoryOwner,isCrossRepository,state 2>/dev/null)"
    if [[ -z "${meta}" ]]; then
      dispo[$i]="DROPPED"
      detail[$i]="could not read PR metadata via gh pr view"
      echo "  #${pr}: DROPPED — ${detail[$i]}"
      continue
    fi
    local state cross
    state="$(jq -r '.state // ""' <<<"${meta}")"
    cross="$(jq -r '.isCrossRepository // false' <<<"${meta}")"
    head_ref[$i]="$(jq -r '.headRefName // ""' <<<"${meta}")"
    head_sha[$i]="$(jq -r '.headRefOid // ""' <<<"${meta}")"
    if [[ "${state}" != "OPEN" ]]; then
      dispo[$i]="DROPPED"
      detail[$i]="PR state is ${state}, not OPEN"
      echo "  #${pr}: DROPPED — ${detail[$i]}"
      continue
    fi
    if [[ "${cross}" == "true" ]]; then
      dispo[$i]="DROPPED"
      detail[$i]="head branch lives in a fork — this train never pushes a branch it does not own"
      echo "  #${pr}: DROPPED — ${detail[$i]}"
      continue
    fi

    echo "  #${pr}: watching checks (deploy/wait_pr_green.sh)…"
    _watch_pr_green "${pr}"
    _grc=$?
    # rc 0 = plain green; rc 4 (#3200) = green except a CLASSIFIED
    # reconcile-owned red — both proceed, only the second is named. Anything
    # else (1=FAIL, 2=WAITING, …) drops the PR exactly as before this existed.
    if [[ "${_grc}" -ne 0 && "${_grc}" -ne 4 ]]; then
      dispo[$i]="DROPPED"
      detail[$i]="not green — wait_pr_green.sh exited ${_grc} (2 = WAITING gated-deployment lease, a human disposes it)"
      echo "  #${pr}: DROPPED — ${detail[$i]}"
      continue
    fi
    if [[ "${_grc}" -eq 4 ]]; then
      reconcile_red[$i]="${_WATCH_RECONCILE_RED}"
      echo "  #${pr}: GREEN (reconcile-owned red classified, #3200: ${reconcile_red[$i]})"
    else
      echo "  #${pr}: GREEN"
    fi
  done
  echo ""

  # ── Phase 2: reconcile onto an accumulating tip, in a scratch worktree ─────
  echo "── phase 2: reconcile ────────────────────────────────────────────────"
  git -C "${root}" fetch --quiet "${REMOTE}" "${BASE_BRANCH}" || {
    echo "ERROR: could not fetch ${REMOTE}/${BASE_BRANCH}" >&2
    return 2
  }
  local base_sha
  base_sha="$(git -C "${root}" rev-parse "${REMOTE}/${BASE_BRANCH}")"

  local wt
  wt="$(mktemp -d "${TMPDIR:-/tmp}/merge-train.XXXXXX")"
  rmdir "${wt}"
  if ! git -C "${root}" worktree add --quiet --detach "${wt}" "${base_sha}" >/dev/null 2>&1; then
    echo "ERROR: could not create the scratch worktree at ${wt}" >&2
    return 2
  fi
  echo "scratch worktree: ${wt} (the caller's checkout is never touched)"
  echo "train tip starts at ${REMOTE}/${BASE_BRANCH} = ${base_sha}"

  local train_tip="${base_sha}"
  local any_reconciled=0
  local saved_pwd="${PWD}"
  cd "${wt}" || return 2

  for ((i = 0; i < n; i++)); do
    [[ "${dispo[$i]}" == "PENDING" ]] || continue
    local pr="${prs[$i]}"
    local lb="merge-train/pr-${pr}"
    if ! git fetch --quiet "${REMOTE}" "+refs/pull/${pr}/head:refs/merge-train/head-${pr}" 2>/dev/null; then
      dispo[$i]="DROPPED"
      detail[$i]="could not fetch refs/pull/${pr}/head"
      echo "  #${pr}: DROPPED — ${detail[$i]}"
      continue
    fi
    local fetched
    fetched="$(git rev-parse "refs/merge-train/head-${pr}")"
    if [[ -n "${head_sha[$i]}" && "${fetched}" != "${head_sha[$i]}" ]]; then
      dispo[$i]="DROPPED"
      detail[$i]="head moved mid-train (gh said ${head_sha[$i]}, pull ref is ${fetched})"
      echo "  #${pr}: DROPPED — ${detail[$i]}"
      continue
    fi

    local out
    out="$(reconcile_branch_onto "${train_tip}" "refs/merge-train/head-${pr}" "${lb}" | tail -1)"
    if [[ "${out}" == DROPPED* ]]; then
      dispo[$i]="DROPPED"
      detail[$i]="rebase refused: ${out#DROPPED }"
      echo "  #${pr}: DROPPED — ${detail[$i]}"
      git checkout -q --detach "${train_tip}" 2>/dev/null
      continue
    fi
    train_tip="$(awk '{print $2}' <<<"${out}")"
    local_branch[$i]="${lb}"
    any_reconciled=1
    if [[ "${out}" == *"resolved=1" ]]; then
      needs_push[$i]="1"
      echo "  #${pr}: reconciled (counter conflict RESOLVED by regeneration) → ${train_tip:0:12}"
    else
      echo "  #${pr}: reconciled clean (no push needed) → ${train_tip:0:12}"
    fi
  done
  echo ""

  if [[ "${any_reconciled}" -eq 0 ]]; then
    echo "no PR survived reconciliation — nothing to validate, nothing to merge."
    cd "${saved_pwd}" || true
    _emit_report prs dispo detail reconcile_red
    _cleanup_worktree "${root}" "${wt}" 1
    return 1
  fi

  # ── Phase 3: ONE stacked validation over main + every reconciled branch ────
  echo "── phase 3: stacked validation (offline) ─────────────────────────────"
  git checkout -q --detach "${train_tip}"
  echo "validation tip ${train_tip} = ${BASE_BRANCH} + $(git rev-list --count "${base_sha}..${train_tip}") reconciled commit(s)"
  if ! run_offline_gate; then
    echo ""
    echo "TRAIN ABORTED before any merge — the stack does not validate."
    echo "the scratch worktree is LEFT IN PLACE for inspection: ${wt}"
    for ((i = 0; i < n; i++)); do
      if [[ "${dispo[$i]}" == "PENDING" ]]; then
        dispo[$i]="NOT-ATTEMPTED"
        detail[$i]="stacked offline gate failed — no PR was merged"
      fi
    done
    cd "${saved_pwd}" || true
    _emit_report prs dispo detail reconcile_red
    return 1
  fi
  echo ""
  echo "stacked validation PASSED."
  echo ""

  # ── Phase 4: push what we had to change, then merge in train order ────────
  echo "── phase 4: merge ────────────────────────────────────────────────────"
  local aborted=0
  for ((i = 0; i < n; i++)); do
    [[ "${dispo[$i]}" == "PENDING" ]] || continue
    local pr="${prs[$i]}"

    if [[ "${aborted}" -eq 1 ]]; then
      dispo[$i]="NOT-ATTEMPTED"
      detail[$i]="train aborted on an earlier merge failure"
      continue
    fi

    if [[ "${needs_push[$i]}" == "1" ]]; then
      echo "  #${pr}: pushing the reconciled branch (leased on ${head_sha[$i]})"
      if ! push_reconciled "${local_branch[$i]}" "${head_ref[$i]}" "${head_sha[$i]}"; then
        dispo[$i]="DROPPED"
        detail[$i]="leased force-push refused — the branch moved under the train; reconcile #${pr} by hand"
        echo "  #${pr}: DROPPED — ${detail[$i]}"
        continue
      fi
      if [[ "${DRY_RUN}" -eq 0 ]]; then
        # The branch content CHANGED, so the PR's earlier green verdict is stale.
        # Re-watch. This is the only re-check the train pays, and only the PRs
        # that actually conflicted pay it.
        echo "  #${pr}: branch changed — re-watching checks before merging"
        _watch_pr_green "${pr}"
        _rrc=$?
        # VERDICT READ ABOVE, IN ITS OWN COMMAND. The merge below is a separate
        # statement guarded by that verdict — never chained to it (#3103). rc 0
        # or rc 4 (#3200's classified reconcile-owned red) both proceed; the
        # re-classified paths (if any) overwrite the phase-1 note so the final
        # report reflects the post-rebase state, not a stale pre-rebase one.
        if [[ "${_rrc}" -ne 0 && "${_rrc}" -ne 4 ]]; then
          dispo[$i]="DROPPED"
          detail[$i]="post-rebase checks not green (wait_pr_green.sh exited ${_rrc})"
          echo "  #${pr}: DROPPED — ${detail[$i]}"
          continue
        fi
        if [[ "${_rrc}" -eq 4 ]]; then
          reconcile_red[$i]="${_WATCH_RECONCILE_RED}"
          echo "  #${pr}: GREEN (reconcile-owned red classified, #3200: ${reconcile_red[$i]})"
        fi
      fi
    fi

    if [[ "${DRY_RUN}" -eq 1 ]]; then
      merge_pr "${pr}"
      dispo[$i]="DRY-RUN"
      detail[$i]="would squash-merge (push needed: ${needs_push[$i]})"
      continue
    fi

    echo "  #${pr}: squash-merging"
    if ! merge_pr "${pr}"; then
      dispo[$i]="FAILED"
      detail[$i]="gh pr merge failed — TRAIN ABORTED here"
      aborted=1
      echo "  #${pr}: MERGE FAILED — aborting the whole train (nothing after this is attempted)"
      continue
    fi
    local merged_sha
    merged_sha="$(gh pr view "${pr}" --repo "${REPO}" --json mergeCommit --jq '.mergeCommit.oid // ""' 2>/dev/null)"
    dispo[$i]="MERGED"
    detail[$i]="squash sha ${merged_sha:-unknown}"
    echo "  #${pr}: MERGED ${merged_sha:0:12}"
  done

  cd "${saved_pwd}" || true
  echo ""
  _emit_report prs dispo detail reconcile_red
  local exit_rc=0
  for ((i = 0; i < n; i++)); do
    case "${dispo[$i]}" in
      MERGED | DRY-RUN) ;;
      *) exit_rc=1 ;;
    esac
  done
  _cleanup_worktree "${root}" "${wt}" "${exit_rc}"
  return "${exit_rc}"
}

_cleanup_worktree() {
  local root="$1" wt="$2" rc="$3"
  if [[ "${KEEP_WORKTREE}" -eq 1 || "${rc}" -ne 0 ]]; then
    echo "scratch worktree kept: ${wt}"
    return 0
  fi
  git -C "${root}" worktree remove --force "${wt}" >/dev/null 2>&1 &&
    echo "scratch worktree removed."
}

# _emit_report <prs-array-name> <dispo-array-name> <detail-array-name> [<reconcile-red-array-name>]
#   bash 3.2 has no nameref, so this reads the arrays via indirect expansion of
#   the caller's array names. The 4th argument (#3200) is OPTIONAL for backward
#   compatibility with the offline test harness, which sources this file and
#   calls _emit_report directly with only 3 arrays; when a PR's classified
#   reconcile-owned red survived to report time, its DETAIL column names it
#   explicitly instead of leaving the classification invisible in the one place
#   an operator actually reads — "merge_train phase 1 consumes the classified
#   verdict; its report names the reconcile-owned red per PR" (#3200 acceptance).
_emit_report() {
  local pa="$1" da="$2" ta="$3" ra="${4:-}"
  eval "local -a _p=(\"\${${pa}[@]}\")"
  eval "local -a _d=(\"\${${da}[@]}\")"
  eval "local -a _t=(\"\${${ta}[@]}\")"
  local -a _r=()
  if [[ -n "${ra}" ]]; then
    eval "_r=(\"\${${ra}[@]}\")"
  fi
  local i
  echo "═══ TRAIN REPORT ════════════════════════════════════════════════════"
  printf '%-8s %-14s %s\n' "PR" "DISPOSITION" "DETAIL"
  for ((i = 0; i < ${#_p[@]}; i++)); do
    if [[ -n "${_r[$i]:-}" ]]; then
      _t[$i]="${_t[$i]} [reconcile-owned red, #3200: ${_r[$i]}]"
    fi
  done
  for ((i = 0; i < ${#_p[@]}; i++)); do
    printf '#%-7s %-14s %s\n' "${_p[$i]}" "${_d[$i]}" "${_t[$i]}"
  done
  echo "═════════════════════════════════════════════════════════════════════"
}

# Sourceable for tests (`source deploy/merge_train.sh --source-only`) without
# running main — mirrors deploy/wait_pr_green.sh.
if [[ "${1:-}" != "--source-only" && "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
  exit $?
fi
