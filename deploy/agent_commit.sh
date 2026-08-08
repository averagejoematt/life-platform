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
set -uo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "${ROOT}" || exit 1

if [ "$#" -lt 2 ]; then
  echo "[agent-commit] ❌ usage: bash deploy/agent_commit.sh \"<message>\" <path> [<path> ...]" >&2
  exit 2
fi

MSG="$1"
shift
PATHS=("$@")

# ── Refuse on an unresolved conflict ──────────────────────────────────────────
# `git add`-ing a file that still carries <<<<<<< markers has shipped to main
# before. A `UU` anywhere means the tree is mid-merge and not commit-ready.
if git status --porcelain | grep -qE '^(UU|AA|DD|AU|UA|DU|UD) '; then
  echo "[agent-commit] ❌ unresolved merge conflict in the tree:" >&2
  git status --porcelain | grep -E '^(UU|AA|DD|AU|UA|DU|UD) ' >&2
  echo "[agent-commit]    resolve every conflicted path, then re-run." >&2
  exit 1
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
    exit 1
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
    exit 1
  fi
  git add -- "${p}" || exit 1
done

STAGED="$(git diff --cached --name-only)"
if [ -z "${STAGED}" ]; then
  echo "[agent-commit] ❌ nothing staged — the named paths have no changes vs HEAD." >&2
  exit 1
fi

# ── The format gate, kept (this is the half CI actually enforces) ─────────────
STAGED_PY="$(printf '%s\n' "${STAGED}" | grep -E '^(lambdas|mcp|cdk|tests|scripts|deploy)/.*\.py$' || true)"

# PREFER THE PINNED BLACK, NOT THE ONE ON PATH. CI runs black 26.3.1; a typical
# local install is 25.9.0, and the two disagree in BOTH directions — a file the
# local one calls clean can be one CI reformats, and vice versa. Resolving from
# PATH is how an agent's green commit red-mained main's Lint job on 2026-08-08
# (lambdas/emails/anomaly_detector_lambda.py). The repo keeps the pin in
# .venv-black; use it when present and say loudly when it is not.
#
# MUST ALSO LOOK IN THE MAIN CHECKOUT, NOT JUST ${ROOT}. Implementers run in git
# worktrees, and .venv-black is untracked — it exists only in the primary clone,
# so a worktree-local lookup silently falls back to PATH and reintroduces exactly
# the skew this guard exists to stop (observed the same day it was added).
# `git rev-parse --git-common-dir` resolves to the primary clone's .git from any
# worktree; its parent is that clone's root.
BLACK="black"
_COMMON_DIR="$(git rev-parse --git-common-dir 2>/dev/null)"
case "${_COMMON_DIR}" in
  /*) ;;
  *) _COMMON_DIR="${ROOT}/${_COMMON_DIR}" ;;
esac
_MAIN_ROOT="$(cd "${_COMMON_DIR}/.." 2>/dev/null && pwd)"

for _cand in "${ROOT}/.venv-black/bin/black" "${_MAIN_ROOT}/.venv-black/bin/black"; do
  if [ -x "${_cand}" ]; then
    BLACK="${_cand}"
    break
  fi
done

if [ "${BLACK}" = "black" ]; then
  echo "[agent-commit] ⚠ .venv-black not found (looked in ${ROOT} and ${_MAIN_ROOT:-?}) —" >&2
  echo "[agent-commit]   falling back to black on PATH ($(black --version 2>/dev/null | head -1))." >&2
  echo "[agent-commit]   CI pins 26.3.1; a version skew here can pass locally and red main's Lint job." >&2
fi

if [ -n "${STAGED_PY}" ]; then
  if command -v "${BLACK}" >/dev/null 2>&1 || [ -x "${BLACK}" ]; then
    if ! "${BLACK}" --check ${STAGED_PY}; then
      echo "[agent-commit] ❌ black would reformat — run: ${BLACK} ${STAGED_PY}" >&2
      exit 1
    fi
    if ! ruff check ${STAGED_PY}; then
      echo "[agent-commit] ❌ ruff check failed — run: ruff check --fix ${STAGED_PY}" >&2
      exit 1
    fi
    echo "[agent-commit] ✓ black + ruff clean"
  else
    echo "[agent-commit] ⚠ black/ruff not on PATH — format gate SKIPPED, CI will catch it" >&2
  fi
fi

# --no-verify is deliberate: the gate above replaces the hook's useful half, and
# skipping the hook is the entire point (it would re-stage the doc literals).
git commit --no-verify -m "${MSG}" || exit 1

echo "[agent-commit] ✅ committed $(printf '%s\n' "${STAGED}" | wc -l | tr -d ' ') path(s)"
echo "[agent-commit]    next: git push -u origin \$(git branch --show-current)"
