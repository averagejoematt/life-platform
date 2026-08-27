#!/usr/bin/env bash
# agent_commit.sh — the one-command commit for implementer agents.
#
# WHY THIS EXISTS. The repo's pre-commit hook does two things, and the second one
# costs agents a lot of wall-clock:
#
#   1. a format gate (black + ruff on staged Python) — genuinely load-bearing, CI
#      fails the build without it;
#   2. `sync_doc_metadata.py --apply`, which rewrites the auto-maintained doc
#      literals (test counts, tool counts, …) and then `git add`s *whatever it
#      touched* — docs/, CLAUDE.md, .claude/README.md, lambdas/web/platform_counts.py.
#
# Step 2 is correct for the driver merging on main and wrong for an implementer on
# a branch: it sweeps a global literal (e.g. `test_count`) into a feature PR, where
# it becomes a guaranteed conflict against every other concurrent PR that added a
# test. Agents then hand-fight the loop — strip the literal, hook re-stages it,
# strip again — which is where the 2026-08-08 session lost five PRs.
#
# #3101 moved the discovered counters OUT of lambdas/web/site_api_common.py into
# the generated single-writer module lambdas/web/platform_counts.py, which exists
# for no other purpose. Two consequences for this script, both deliberate:
#   • platform_counts.py is refused outright — there is no "genuine content edit"
#     of a generated counter file, so it has no ALLOW_DOC_LITERALS escape hatch.
#   • site_api_common.py is NO LONGER on the refusal list. It carries no sync
#     literal any more, and it is a hot shared module (134 endpoints import it);
#     making every real edit to it need ALLOW_DOC_LITERALS=1 was the tax the old
#     placement charged.
#
# This script keeps the gate and drops the sweep: it runs black + ruff itself,
# stages ONLY the named paths, and commits with --no-verify. The driver reconciles
# the literals once per merge on main, which is the only place that arithmetic is
# stable.
#
# Usage:
#   bash deploy/agent_commit.sh "<commit message>" <path> [<path> ...]
#
# A DIRECTORY argument covers the files under it (#2897). If a changed doc-literal
# file is not covered by any argument, the script REFUSES and names it rather than
# reverting it — see the long note at the restore block for why that default
# flipped. `ALLOW_LITERAL_RESTORE=1` opts back into auto-restoring those files,
# writing a recovery patch first.
#
# DELETIONS AND RENAMES (#3221). A named path that is gone from disk but still
# tracked at HEAD is a DELETION and is staged as one — that is the half of a rename
# the old script could not express at all. Because it could not, the only route for
# a rename was a bare `git rm` + `git commit` outside this script, which is exactly
# the bypass that let the pre-commit hook sweep lambdas/web/platform_counts.py into
# a branch on #3202. A guard unavailable on the one operation whose hook behaviour
# is least predictable is a guard with a hole where implementers stand. See the
# staging block for the one shape still refused (a vanished DIRECTORY).
#
# Refuses to commit if: no paths given, an unresolved merge conflict (UU) exists,
# a named path is a doc-sync literal file (or the generated counter module, which
# has no override), a changed doc-literal file is unnamed, a named path is neither
# on disk nor tracked-and-deleted, or black/ruff reject the staged Python.
# EVERY refusal exits nonzero and prints a terminal "REFUSED" line (#2464) — a
# success is exit 0 plus the "✅ committed N path(s)" line, nothing else is.
set -uo pipefail

# ── The refusal funnel (#2464) ─────────────────────────────────────────────────
# EVERY path that discards the commit must exit through here, nonzero, so a
# caller's `&&` chain stops at the refusal instead of pushing nothing and then
# destroying the worktree. The terminal REFUSED line is the output-level tell for
# callers whose invocation eats the exit status (`... | tee`/`| tail` reports the
# pipe's last command, and separate tool calls don't chain at all) — if you see
# it, NOTHING was committed. Never add a refusal that bypasses this funnel.
refuse() {
  _code="${1:-1}"
  echo "[agent-commit] ✋ REFUSED — nothing was committed (exit ${_code})." >&2
  exit "${_code}"
}

ROOT="$(git rev-parse --show-toplevel)" || exit 1
cd "${ROOT}" || exit 1

if [ "$#" -lt 2 ]; then
  echo "[agent-commit] ❌ usage: bash deploy/agent_commit.sh \"<message>\" <path> [<path> ...]" >&2
  refuse 2
fi

MSG="$1"
shift
PATHS=("$@")

# ── Refuse on an unresolved conflict ──────────────────────────────────────────
# `git add`-ing a file that still carries <<<<<<< markers has shipped to main
# before. A `UU` anywhere means the tree is mid-merge and not commit-ready.
# Capture, don't `grep -q` (#2464): under pipefail, `-q` exits on first match and
# can SIGPIPE `git status`, turning a REAL conflict into a pipeline failure that
# reads as "no conflict" — the check would fail OPEN. Plain grep drains its input.
CONFLICTED="$(git status --porcelain | grep -E '^(UU|AA|DD|AU|UA|DU|UD) ' || true)"
if [ -n "${CONFLICTED}" ]; then
  echo "[agent-commit] ❌ unresolved merge conflict in the tree:" >&2
  printf '%s\n' "${CONFLICTED}" >&2
  echo "[agent-commit]    resolve every conflicted path, then re-run." >&2
  refuse 1
fi

# ── Refuse to let an agent commit a doc-sync literal ───────────────────────────
# These files are reconciled by the driver on main, once per merge. A branch that
# carries them conflicts with every sibling PR.
is_literal_file() {
  case "$1" in
    docs/*|CLAUDE.md|.claude/README.md|lambdas/web/platform_counts.py) return 0 ;;
    *) return 1 ;;
  esac
}

# #3101: the generated counter module is refused with NO override. Everything else
# on the list above is only *usually* literal-bearing (a real prose edit to docs/
# is a normal thing to want); a hand edit to a file whose entire contents are
# regenerated from the repo on every sync is not.
is_generated_only_file() {
  case "$1" in
    lambdas/web/platform_counts.py) return 0 ;;
    *) return 1 ;;
  esac
}

for p in "${PATHS[@]}"; do
  if is_generated_only_file "${p}"; then
    echo "[agent-commit] ❌ '${p}' is GENERATED (#3101) — deploy/sync_doc_metadata.py --apply is its only writer," >&2
    echo "[agent-commit]    run by the reconcile bot on main. A branch carrying it conflicts with every sibling PR." >&2
    echo "[agent-commit]    Drop it: git checkout HEAD -- ${p}" >&2
    refuse 1
  fi
  # docs/ is only *usually* literal-bearing. Allow an explicit override for the
  # rare real edit, but make it deliberate.
  if is_literal_file "${p}" && [ "${ALLOW_DOC_LITERALS:-0}" != "1" ]; then
    echo "[agent-commit] ❌ '${p}' is a doc-sync literal file — the driver reconciles these on main." >&2
    echo "[agent-commit]    If this is a genuine content edit, re-run with ALLOW_DOC_LITERALS=1." >&2
    refuse 1
  fi
done

# ── The restore SOURCE is the MERGE-BASE, never the moving tip (#3221) ────────
# The #3221 recovery had a second trap in it. The first restore of
# platform_counts.py was taken from `origin/main`, which had MOVED mid-session (a
# sibling merge bumped `test_count` 17436 -> 17452) — so restoring from it would
# have carried ANOTHER PR's literal onto this branch: silent, plausible-looking and
# wrong, which is the same cross-PR drift this whole script exists to prevent.
#
# The correct source is where this branch left main: `git merge-base HEAD
# origin/main`. HEAD is not it either — if an earlier bypass already COMMITTED a
# swept literal onto the branch (the exact #3221 shape), restoring from HEAD
# restores the swept value and reports success.
#
# Falls back to HEAD when there is no origin/main to compute a base against (a
# fresh clone, a scratch repo, a detached CI checkout) — a degraded source is still
# better than none, and the fallback is named in the output so it is never silent.
BASE_REF="${AGENT_COMMIT_BASE_REF:-origin/main}"
LITERAL_REF="$(git merge-base HEAD "${BASE_REF}" 2>/dev/null || true)"
if [ -n "${LITERAL_REF}" ]; then
  LITERAL_REF_DESC="the merge-base with ${BASE_REF} (${LITERAL_REF})"
else
  LITERAL_REF="HEAD"
  LITERAL_REF_DESC="HEAD (no ${BASE_REF} — could not compute a merge-base)"
fi

# ── The generated counter module is always safe to restore (#3101) ────────────
# If an earlier commit attempt let the pre-commit hook run, platform_counts.py
# carries a regenerated counter the agent never asked for. Unlike docs/, this file
# has NO authored content — every byte of it is re-derivable by
# `sync_doc_metadata.py --apply` — so the #2897 hazard (silently destroying prose)
# structurally cannot apply, and restoring it is strictly better than making the
# agent hand-fight the hook. Runs after the named-path loop above so that NAMING it
# is still an explicit refusal, not a silent no-op.
#
# #3221: diffed against ${LITERAL_REF}, NOT the index. The hook's sweep ends in
# `git add`, so the swept file is STAGED — a bare `git diff -- <path>` compares
# index-to-worktree, sees no difference, and this block did nothing on the one
# input it was written for. A ref-to-worktree diff sees staged and unstaged alike.
COUNTS_FILE="lambdas/web/platform_counts.py"
if ! git diff --quiet "${LITERAL_REF}" -- "${COUNTS_FILE}" 2>/dev/null; then
  if git checkout "${LITERAL_REF}" -- "${COUNTS_FILE}" 2>/dev/null; then
    echo "[agent-commit] ↩ restored ${COUNTS_FILE} to ${LITERAL_REF_DESC}"
    echo "[agent-commit]    (generated — the reconcile bot owns it, #3101)"
  else
    echo "[agent-commit] ❌ ${COUNTS_FILE} differs from ${LITERAL_REF_DESC} and could not be restored." >&2
    echo "[agent-commit]    A branch must not carry it (#3101). Drop it by hand, then re-run." >&2
    refuse 1
  fi
fi

# ── Undo the hook's prior sweep ────────────────────────────────────────────────
# If an earlier commit attempt let the hook run, these files carry regenerated
# literals. The agent did not ask for those, and carrying them conflicts with
# every sibling PR — so they have to come off the commit somehow.
#
# #2897: the way this USED to happen was `git checkout HEAD --` on every changed
# literal-bearing file the agent did not name, and the "did the agent name it?"
# test was a literal substring match on the joined argument list. Passing the
# DIRECTORY `docs/` therefore made every file under it "unnamed", and the script
# silently destroyed ~13 files of authored prose (including a finished ADR
# amendment) while printing "✅ committed" and exiting 0. `git diff` is the
# source, so the work was not recoverable from the index.
#
# Two changes close that. First, a directory argument now genuinely COVERS the
# files under it, which removes the footgun from the happy path. Second, anything
# still unnamed is a REFUSAL, not a discard: this script's job is to keep literals
# off a branch, and destroying authored content to achieve that has the
# cost/benefit backwards. The caller decides, and gets told how.

# Expand every named path to the concrete tracked files it covers. `git ls-files`
# echoes a plain file argument straight back, so this is a no-op for file args;
# the untracked-but-named case is covered because ${p} itself is kept too.
named=""
for p in "${PATHS[@]}"; do
  named="${named} ${p}"
  while IFS= read -r _f; do
    [ -n "${_f}" ] && named="${named} ${_f}"
  done < <(git ls-files -- "${p}" 2>/dev/null)
done
named=" ${named} "

unnamed=""
while IFS= read -r f; do
  [ -n "${f}" ] || continue
  case "${named}" in *" ${f} "*) continue ;; esac
  unnamed="${unnamed} ${f}"
done < <(git diff --name-only -- docs/ CLAUDE.md .claude/README.md lambdas/web/platform_counts.py)

if [ -n "${unnamed}" ]; then
  if [ "${ALLOW_LITERAL_RESTORE:-0}" = "1" ]; then
    # Deliberate, opt-in discard. Still save a recovery patch first — the thing
    # being thrown away may be authored prose no test can regenerate.
    _bak="$(git rev-parse --git-dir)/agent_commit_restored_$(date +%Y%m%dT%H%M%S).patch"
    git diff -- ${unnamed} > "${_bak}" 2>/dev/null || true
    git checkout HEAD -- ${unnamed} 2>/dev/null
    echo "[agent-commit] ↩ restored doc-literal files to HEAD:${unnamed}"
    echo "[agent-commit]    recovery patch: ${_bak}"
  else
    echo "[agent-commit] ❌ these changed doc-literal files were not named:" >&2
    for f in ${unnamed}; do echo "[agent-commit]      ${f}" >&2; done
    echo "[agent-commit]    Refusing to discard them (#2897 — silently reverting these destroyed 13 files of authored work)." >&2
    echo "[agent-commit]    Pick one:" >&2
    echo "[agent-commit]      • keep them:    add them to the argument list (a directory covers its files)" >&2
    echo "[agent-commit]      • discard them: git checkout HEAD -- <files>" >&2
    echo "[agent-commit]      • auto-restore: re-run with ALLOW_LITERAL_RESTORE=1 (writes a recovery patch first)" >&2
    refuse 1
  fi
fi

# ── Stage exactly what was asked for ──────────────────────────────────────────
#
# #3221: "absent from disk" is not one condition, it is three, and the old script
# collapsed all three into "path does not exist" and refused:
#
#   (a) a tracked file the caller DELETED (or the old half of a rename) — a normal
#       thing to commit. `git add -A -- <path>` stages the removal. Refusing here is
#       what forced the bare-`git rm` bypass that let the hook sweep a doc literal
#       onto a branch; supporting it is this issue.
#   (b) a DIRECTORY (or glob) that is gone from disk but still has tracked files
#       under it — REFUSED outright, and named. A vanished directory is the #2897
#       silhouette: one argument standing for an unbounded set of removals the
#       caller never enumerated, on the operation where a mistake is least
#       recoverable. Name the deleted files. A directory that still EXISTS is
#       unchanged — it covers its files exactly as #2897 made it (pinned by
#       tests/test_agent_commit_exit_codes.py).
#   (c) a typo / an unquoted multi-path argument — still the old refusal, still
#       through refuse(), still nonzero with the terminal REFUSED line (#2464).
git reset -q
for p in "${PATHS[@]}"; do
  if [ -e "${p}" ] || [ -L "${p}" ]; then
    git add -- "${p}" || refuse 1
    continue
  fi

  # `git ls-files` reads the INDEX, which `git reset -q` above has just restored to
  # HEAD — so it answers "did this path exist at HEAD?" and a deleted-on-disk file
  # is still listed. It also expands a directory/glob argument, which is how (b) is
  # told apart from (a): one entry equal to the argument itself is a single file.
  tracked="$(git ls-files -- "${p}" 2>/dev/null)"
  if [ -z "${tracked}" ]; then
    echo "[agent-commit] ❌ path does not exist and git does not track it: ${p}" >&2
    echo "[agent-commit]    (a deleted file IS accepted — but only if it was tracked at HEAD)" >&2
    refuse 1
  fi
  if [ "${tracked}" != "${p}" ]; then
    n_tracked="$(printf '%s\n' "${tracked}" | wc -l | tr -d ' ')"
    echo "[agent-commit] ❌ '${p}' is gone from disk and covers ${n_tracked} tracked file(s) — refusing (#3221/#2897)." >&2
    echo "[agent-commit]    A vanished DIRECTORY cannot stand in for an unenumerated set of deletions." >&2
    echo "[agent-commit]    Name each deleted file:" >&2
    printf '%s\n' "${tracked}" | sed 's/^/[agent-commit]      /' >&2
    refuse 1
  fi

  # (a) — stage the deletion. `-A` is explicit rather than relying on git >= 2.0's
  # "plain `git add <pathspec>` also records removals" behaviour.
  echo "[agent-commit] − staging deletion: ${p}"
  git add -A -- "${p}" || refuse 1
done

STAGED="$(git diff --cached --name-only)"
if [ -z "${STAGED}" ]; then
  echo "[agent-commit] ❌ nothing staged — the named paths have no changes vs HEAD." >&2
  refuse 1
fi

# ── The format gate, kept (this is the half CI actually enforces) ─────────────
# #3221: a DELETED .py is in ${STAGED} but not on disk, and `black --check` on a
# path that does not exist exits 2 — which would turn every rename into a
# format-gate refusal, i.e. re-close the hole this issue opened. Filter the staged
# list to what still exists before handing it to a formatter; there is nothing to
# format about a removal.
STAGED_PY=""
while IFS= read -r _sp; do
  [ -n "${_sp}" ] || continue
  case "${_sp}" in
    lambdas/*.py | mcp/*.py | cdk/*.py | tests/*.py | scripts/*.py | deploy/*.py) ;;
    *) continue ;;
  esac
  [ -f "${_sp}" ] || continue
  STAGED_PY="${STAGED_PY}${STAGED_PY:+
}${_sp}"
done <<EOF
${STAGED}
EOF

# USE THE PINNED BLACK AND RUFF, NEVER THE ONES ON PATH. CI runs an exact pair
# (requirements-dev.txt == ci-lint.yml, CQ-01); a typical local black is 25.9.0
# against CI's 26.3.1, and the two disagree in BOTH directions — a file the local
# one calls clean can be one CI reformats, and vice versa. Resolving from PATH is
# how an agent's green commit red-mained main's Lint job on 2026-08-08
# (lambdas/emails/anomaly_detector_lambda.py), and how the pre-commit hook spent
# 2026-08-11 refusing commits CI would have passed (#2570).
#
# The search, the version verification and the fail-closed message all live in
# deploy/lib/pinned_formatters.sh — ONE resolver shared with the pre-commit hook,
# reading the pin from requirements-dev.txt. It already looks in the PRIMARY
# clone as well as ${ROOT} (implementers run in worktrees and .venv-black is
# untracked, so a worktree-local lookup alone misses it), and it version-verifies
# every candidate including PATH, so a correct PATH install is accepted and a
# skewed one never is.
if [ -n "${STAGED_PY}" ]; then
  _PF_LIB="${ROOT}/deploy/lib/pinned_formatters.sh"
  if [ ! -f "${_PF_LIB}" ]; then
    echo "[agent-commit] ❌ ${_PF_LIB} is missing — cannot verify the formatter pin." >&2
    echo "[agent-commit]    Refusing to run an unpinned format gate (#2570)." >&2
    refuse 1
  fi
  # shellcheck source=lib/pinned_formatters.sh
  . "${_PF_LIB}"

  # Fail CLOSED: an unpinned format gate is worse than no gate, because it
  # refuses correct code and blesses code CI will reject.
  if ! BLACK="$(resolve_pinned_formatter black)"; then
    echo "[agent-commit] ❌ format gate FAILED CLOSED — no black at the pinned version (#2570)." >&2
    refuse 1
  fi
  if ! RUFF="$(resolve_pinned_formatter ruff)"; then
    echo "[agent-commit] ❌ format gate FAILED CLOSED — no ruff at the pinned version (#2570)." >&2
    refuse 1
  fi
  if ! "${BLACK}" --check ${STAGED_PY}; then
    echo "[agent-commit] ❌ black would reformat — run: ${BLACK} ${STAGED_PY}" >&2
    refuse 1
  fi
  if ! "${RUFF}" check ${STAGED_PY}; then
    echo "[agent-commit] ❌ ruff check failed — run: ${RUFF} check --fix ${STAGED_PY}" >&2
    refuse 1
  fi
  echo "[agent-commit] ✓ black $(pinned_formatter_version black) + ruff $(pinned_formatter_version ruff) clean"
fi

# --no-verify is deliberate: the gate above replaces the hook's useful half, and
# skipping the hook is the entire point (it would re-stage the doc literals).
git commit --no-verify -m "${MSG}" || refuse 1

echo "[agent-commit] ✅ committed $(printf '%s\n' "${STAGED}" | wc -l | tr -d ' ') path(s)"
echo "[agent-commit]    next: git push -u origin \$(git branch --show-current)"
exit 0
