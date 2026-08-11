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
#      touched* — docs/, CLAUDE.md, .claude/README.md, lambdas/web/site_api_common.py.
#
# Step 2 is correct for the driver merging on main and wrong for an implementer on
# a branch: it sweeps a global literal (e.g. `test_count`) into a feature PR, where
# it becomes a guaranteed conflict against every other concurrent PR that added a
# test. Agents then hand-fight the loop — strip the literal, hook re-stages it,
# strip again — which is where the 2026-08-08 session lost five PRs.
#
# This script keeps the gate and drops the sweep: it runs black + ruff itself,
# restores any doc-literal file the agent did not explicitly name, stages ONLY the
# named paths, and commits with --no-verify. The driver reconciles the literals
# once per merge on main, which is the only place that arithmetic is stable.
#
# Usage:
#   bash deploy/agent_commit.sh "<commit message>" <path> [<path> ...]
#
# Refuses to commit if: no paths given, an unresolved merge conflict (UU) exists,
# a named path is a doc-sync literal file, or black/ruff reject the staged Python.
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
    docs/*|CLAUDE.md|.claude/README.md|lambdas/web/site_api_common.py) return 0 ;;
    *) return 1 ;;
  esac
}

for p in "${PATHS[@]}"; do
  # docs/ and site_api_common.py are only *usually* literal-bearing. Allow an
  # explicit override for the rare real edit, but make it deliberate.
  if is_literal_file "${p}" && [ "${ALLOW_DOC_LITERALS:-0}" != "1" ]; then
    echo "[agent-commit] ❌ '${p}' is a doc-sync literal file — the driver reconciles these on main." >&2
    echo "[agent-commit]    If this is a genuine content edit, re-run with ALLOW_DOC_LITERALS=1." >&2
    refuse 1
  fi
done

# ── Undo the hook's prior sweep ────────────────────────────────────────────────
# If an earlier commit attempt let the hook run, these files carry regenerated
# literals. Restore every literal-bearing file the agent did NOT name.
named=" ${PATHS[*]} "
restored=""
while IFS= read -r f; do
  [ -n "${f}" ] || continue
  case "${named}" in *" ${f} "*) continue ;; esac
  git checkout HEAD -- "${f}" 2>/dev/null && restored="${restored} ${f}"
done < <(git diff --name-only -- docs/ CLAUDE.md .claude/README.md lambdas/web/site_api_common.py)

if [ -n "${restored}" ]; then
  echo "[agent-commit] ↩ restored doc-literal files to HEAD:${restored}"
fi

# ── Stage exactly what was asked for ──────────────────────────────────────────
git reset -q
for p in "${PATHS[@]}"; do
  if [ ! -e "${p}" ]; then
    echo "[agent-commit] ❌ path does not exist: ${p}" >&2
    refuse 1
  fi
  git add -- "${p}" || refuse 1
done

STAGED="$(git diff --cached --name-only)"
if [ -z "${STAGED}" ]; then
  echo "[agent-commit] ❌ nothing staged — the named paths have no changes vs HEAD." >&2
  refuse 1
fi

# ── The format gate, kept (this is the half CI actually enforces) ─────────────
STAGED_PY="$(printf '%s\n' "${STAGED}" | grep -E '^(lambdas|mcp|cdk|tests|scripts|deploy)/.*\.py$' || true)"

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
