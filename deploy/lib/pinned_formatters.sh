#!/usr/bin/env bash
# deploy/lib/pinned_formatters.sh — resolve black/ruff at the version CI pins.
#
# WHY THIS EXISTS (#2570). CI's format gate installs an exact pair of versions
# (`.github/workflows/ci-lint.yml`: `pip install black==… ruff==…`). The
# pre-commit hook and deploy/agent_commit.sh used to resolve those tools off bare
# `PATH`. On 2026-08-11 that PATH black was 25.9.0 while CI pinned 26.3.1, and the
# two DISAGREE on real files (lambdas/ai/ai_calls.py): the hook refused a commit
# CI would have passed, and applying the reformat the hook demanded produced a
# tree CI's gate then rejected. Both directions wrong; only the pin is
# authoritative.
#
# THE CONTRACT.
#   * The pin is declared in exactly ONE place for this library:
#     `requirements-dev.txt`. Nothing here hardcodes a version number.
#     tests/test_formatter_pin_consistency.py derives the SET of every place a
#     black/ruff pin is declared anywhere in the tracked tree and fails if any two
#     disagree — so ci-lint.yml, pr-checks.yml, the Makefile and this resolver can
#     never silently drift apart again.
#   * Resolution is VERSION-VERIFIED, not location-trusted. Each candidate binary
#     is executed with `--version` and accepted only if it reports exactly the
#     declared pin. A candidate that reports anything else is rejected and the
#     search continues.
#   * It FAILS CLOSED. If no candidate reports the pinned version, the resolver
#     prints what it looked at, what each one reported, and how to install the
#     pin — and exits non-zero. There is no silent fall back to whatever is on
#     PATH; that fallback is the entire bug this file closes.
#
# USAGE (bash):
#   source "${PROJ_ROOT}/deploy/lib/pinned_formatters.sh"
#   BLACK="$(resolve_pinned_formatter black)" || exit 1   # message already on stderr
#   "${BLACK}" --check some_file.py
#
# TEST HOOKS (both are still version-verified — neither can be used as a bypass):
#   PINNED_FORMATTER_REQUIREMENTS   override the requirements file to read the pin from
#   PINNED_FORMATTER_BIN_BLACK      colon-separated candidate list tried FIRST for black
#   PINNED_FORMATTER_BIN_RUFF       colon-separated candidate list tried FIRST for ruff

# ── Where the pin is declared ─────────────────────────────────────────────────
# Resolve the repo root from this file's own location so the library works from a
# worktree, a subdirectory, or a hook (whose cwd is the repo root but whose
# $0 is .git/hooks/pre-commit).
_pf_repo_root() {
  local _self
  _self="${BASH_SOURCE[0]}"
  ( cd "$(dirname "${_self}")/../.." >/dev/null 2>&1 && pwd )
}

_pf_requirements_file() {
  if [ -n "${PINNED_FORMATTER_REQUIREMENTS:-}" ]; then
    printf '%s\n' "${PINNED_FORMATTER_REQUIREMENTS}"
    return 0
  fi
  printf '%s/requirements-dev.txt\n' "$(_pf_repo_root)"
}

# pinned_formatter_version <tool> → echoes the declared pin, or exits 1 loudly.
pinned_formatter_version() {
  local tool="$1" req ver
  req="$(_pf_requirements_file)"
  if [ ! -f "${req}" ]; then
    echo "[pinned-formatters] ❌ cannot read the pin: ${req} does not exist." >&2
    return 1
  fi
  # Strip inline comments and whitespace, then match `<tool>==<version>` exactly.
  ver="$(sed -e 's/#.*//' -e 's/[[:space:]]//g' "${req}" \
        | grep -E "^${tool}==[0-9][0-9A-Za-z.+-]*$" \
        | head -n1 \
        | cut -d= -f3-)"
  if [ -z "${ver}" ]; then
    echo "[pinned-formatters] ❌ no '${tool}==<version>' pin found in ${req}." >&2
    return 1
  fi
  printf '%s\n' "${ver}"
}

# ── Candidate binaries, in preference order ───────────────────────────────────
# .venv-black is untracked and lives in the PRIMARY clone, not a worktree, so a
# worktree-local lookup alone silently misses it (observed the same day the
# agent_commit.sh version of this search was added). `git rev-parse
# --git-common-dir` resolves the primary clone's .git from any worktree.
_pf_candidates() {
  local tool="$1" root common main_root override
  root="$(_pf_repo_root)"

  case "${tool}" in
    black) override="${PINNED_FORMATTER_BIN_BLACK:-}" ;;
    ruff) override="${PINNED_FORMATTER_BIN_RUFF:-}" ;;
    *) override="" ;;
  esac
  if [ -n "${override}" ]; then
    printf '%s\n' "${override}" | tr ':' '\n'
  fi

  common="$(git -C "${root}" rev-parse --git-common-dir 2>/dev/null || true)"
  if [ -n "${common}" ]; then
    case "${common}" in
      /*) ;;
      *) common="${root}/${common}" ;;
    esac
    main_root="$(cd "${common}/.." 2>/dev/null && pwd || true)"
  fi

  local d
  for d in "${root}" "${main_root:-}"; do
    [ -n "${d}" ] || continue
    printf '%s/.venv-black/bin/%s\n' "${d}" "${tool}"
    printf '%s/.venv/bin/%s\n' "${d}" "${tool}"
  done

  command -v "${tool}" 2>/dev/null || true
}

# _pf_probe <binary> → echoes the dotted version it reports, or nothing.
# black prints "black, 26.3.1 (compiled: yes)"; ruff prints "ruff 0.14.14".
_pf_probe() {
  local bin="$1" out
  [ -x "${bin}" ] || command -v "${bin}" >/dev/null 2>&1 || return 1
  out="$("${bin}" --version 2>/dev/null | head -n1)" || return 1
  printf '%s\n' "${out}" | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?([0-9A-Za-z.+-]*)?' | head -n1
}

# resolve_pinned_formatter <tool>
#   stdout: the absolute path (or bare name) of a binary VERIFIED at the pin
#   exit 1: nothing matched — a full explanation is already on stderr
resolve_pinned_formatter() {
  local tool="$1" want cand got seen report=""
  want="$(pinned_formatter_version "${tool}")" || return 1

  while IFS= read -r cand; do
    [ -n "${cand}" ] || continue
    case " ${seen:-} " in *" ${cand} "*) continue ;; esac
    seen="${seen:-} ${cand}"
    got="$(_pf_probe "${cand}" || true)"
    [ -n "${got}" ] || continue
    if [ "${got}" = "${want}" ]; then
      printf '%s\n' "${cand}"
      return 0
    fi
    report="${report}
    ${cand} → ${got}"
  done < <(_pf_candidates "${tool}")

  {
    echo "[pinned-formatters] ❌ no ${tool} at the pinned version ${want} could be found."
    echo "[pinned-formatters]    The pin is declared in $(_pf_requirements_file) and must equal CI's"
    echo "[pinned-formatters]    (.github/workflows/ci-lint.yml). Using a different ${tool} is NOT safe:"
    echo "[pinned-formatters]    black 25.9.0 and 26.3.1 disagree on real files in this repo (#2570), so a"
    echo "[pinned-formatters]    local pass can red CI and a local 'fix' can red CI the other way."
    if [ -n "${report}" ]; then
      echo "[pinned-formatters]    Candidates probed:${report}"
    else
      echo "[pinned-formatters]    No ${tool} executable was found at all."
    fi
    echo "[pinned-formatters]    Install the pin (one-time, from the PRIMARY clone — not a worktree):"
    echo "[pinned-formatters]      python3 -m venv .venv-black"
    echo "[pinned-formatters]      .venv-black/bin/pip install -q \$(grep -E '^(black|ruff)==' requirements-dev.txt)"
    echo "[pinned-formatters]    Emergency bypass, knowing CI will still gate you: git commit --no-verify"
  } >&2
  return 1
}
