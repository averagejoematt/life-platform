#!/usr/bin/env bash
# prod_write_guard.sh — a test run cannot reach real AWS through a deploy script (#6116).
#
# THE INCIDENT (docs/INCIDENT_LOG.md, 2026-11-16). A draft unit test ran
# `deploy/www_preview_sync.sh --target root --restore-previous` for real from a laptop: its subprocess env set
# AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY/AWS_PROFILE to "", the CLI treats an empty value as unset, and it fell
# back to the default (admin) profile in ~/.aws. 663 objects copied over site/ and a /* invalidation, from a test.
#
# THE GUARD, at the execution boundary. Source this near the top of every deploy script that reaches AWS:
#     source "$(dirname "${BASH_SOURCE[0]}")/lib/prod_write_guard.sh"      # a script in deploy/
#     source "$(dirname "${BASH_SOURCE[0]}")/prod_write_guard.sh"          # a script in deploy/lib/
# tests/test_prod_write_guard_6116.py derives the set of writing scripts from their text and fails on one that
# does not source it.
#
# Outside a test runner it does NOTHING: no function is defined, PATH is untouched, no variable is exported — a CI
# deploy job and an attended deploy from a shell run exactly as before. A test runner is detected three ways, any
# one of which is enough, so a test that rebuilds its subprocess env from scratch cannot shed all three by accident:
#   1. PYTEST_CURRENT_TEST is set (pytest exports it; a child inherits it unless the test strips it);
#   2. LP_TEST_SESSION is set (tests/conftest.py exports it for the whole session and its children);
#   3. an ancestor process is pytest (`ps`, walked to the root — survives `env -i`).
# Under a test runner, `aws` (every call — a read too, so a refused restore makes ZERO calls) and a mutating
# `cdk`/`npx cdk` (deploy, destroy, bootstrap, ...) are refused with exit 97 and one line on the script's original
# stderr, unless the executable they resolve to is named in LP_TEST_AWS_IS_STUB (a ","-separated list of absolute
# paths: "this aws is my stub"). The deploy/lib/prod_write_guard_bin/ shims go first on PATH as well, so a child
# that calls `aws` by name (xargs, a python helper) meets the same rule. The Python twin is
# deploy/lib/prod_write_guard.py.

[ -n "${_LP_PWG_LOADED:-}" ] && return 0
_LP_PWG_LOADED=1
LP_PWG_EXIT=97
_LP_PWG_LIB=$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)
_LP_PWG_SHIM_DIR="$_LP_PWG_LIB/prod_write_guard_bin"
LP_PWG_REASON=""

# Is this command line (one process's `ps -o args=`) a pytest process? The program must BE pytest or python: a
# `zsh -c "pytest … && bash deploy/x.sh"` parent names pytest in its args, and it is not a test runner.
_lp_pwg_is_pytest_cmd() {
  local args=" $1 " first=${1%% *}
  first=${first##*/}
  case "$first" in
    pytest | py.test) return 0 ;;
    [Pp]ython*) ;;
    *) return 1 ;;
  esac
  [[ "$args" =~ [[:space:]]-m[[:space:]]*(pytest|py\.test)[[:space:]] ]] && return 0
  [[ "$args" =~ [[:space:]][^[:space:]]*/(pytest|py\.test)[[:space:]] ]] && return 0
  return 1
}

_lp_pwg_ancestor_is_pytest() {
  command -v ps >/dev/null 2>&1 || return 1
  local pid=${PPID:-0} depth=0 line ppid args
  while [ "${pid:-0}" -gt 1 ] && [ "$depth" -lt 64 ]; do
    line=$(ps -o ppid= -o args= -p "$pid" 2>/dev/null) || return 1
    line="${line#"${line%%[![:space:]]*}"}"
    [ -n "$line" ] || return 1
    ppid=${line%%[[:space:]]*}
    args=${line#"$ppid"}
    args="${args#"${args%%[![:space:]]*}"}"
    if _lp_pwg_is_pytest_cmd "$args"; then
      LP_PWG_REASON="ancestor pid $pid is pytest"
      return 0
    fi
    pid=$ppid
    depth=$((depth + 1))
  done
  return 1
}

# 0 = running under a test runner (LP_PWG_REASON says which signal), 1 = not.
lp_pwg_test_context() {
  if [ -n "${PYTEST_CURRENT_TEST:-}" ]; then
    LP_PWG_REASON="PYTEST_CURRENT_TEST is set"
    return 0
  fi
  if [ -n "${LP_TEST_SESSION:-}" ]; then
    LP_PWG_REASON="LP_TEST_SESSION is set"
    return 0
  fi
  _lp_pwg_ancestor_is_pytest
}

# The first executable `$1` on PATH that is not one of this guard's own shims ("" when there is none).
lp_pwg_resolve() {
  local tool=$1 dir phys shim
  shim=$(cd -P "$_LP_PWG_SHIM_DIR" 2>/dev/null && pwd)
  local IFS=:
  for dir in $PATH; do
    [ -n "$dir" ] || dir=.
    [ -x "$dir/$tool" ] && [ ! -d "$dir/$tool" ] || continue
    phys=$(cd -P "$dir" 2>/dev/null && pwd) || continue
    [ "$phys" = "$shim" ] && continue
    printf '%s\n' "$phys/$tool"
    return 0
  done
  return 1
}

# 0 when `$1` (a resolved executable) is named in LP_TEST_AWS_IS_STUB.
_lp_pwg_is_declared_stub() {
  local want=$1 entry phys
  [ -n "${LP_TEST_AWS_IS_STUB:-}" ] || return 1
  local IFS=,
  for entry in $LP_TEST_AWS_IS_STUB; do
    [ -n "$entry" ] || continue
    phys="$(cd -P "$(dirname "$entry")" 2>/dev/null && pwd)/$(basename "$entry")" || continue
    [ "$phys" = "$want" ] && return 0
  done
  return 1
}

# Does this cdk/npx invocation change a stack? (`npx cdk synth`, `npx astro build`, `cdk diff` pass through.)
_lp_pwg_cdk_mutates() {
  local tool=$1 arg names_cdk=0
  shift
  [ "$tool" = cdk ] && names_cdk=1
  for arg in "$@"; do
    case "$arg" in cdk | aws-cdk | aws-cdk@* | */cdk) names_cdk=1 ;; esac
  done
  [ "$names_cdk" = 1 ] || return 1
  for arg in "$@"; do
    case "$arg" in deploy | destroy | bootstrap | import | rollback | watch | gc | refactor) return 0 ;; esac
  done
  return 1
}

lp_pwg_refuse() {
  # fd 2 may be inside `$(… 2>/dev/null)`; the guard saved the script's own stderr as fd 87 when it was sourced.
  local msg="prod_write_guard: REFUSED \`$1\` — running under a test runner ($LP_PWG_REASON) and that tool is not a declared stub, so real AWS is unreachable (a test with a stub sets LP_TEST_AWS_IS_STUB=<stub path>) — #6116"
  if { true >&87; } 2>/dev/null; then printf '%s\n' "$msg" >&87; else printf '%s\n' "$msg" >&2; fi
  # A refusal inside `$(aws … || true)` or a pipeline ends only that subshell, and the script would read the refusal
  # as an empty answer and carry on (the restore then says "nothing to restore" and exits 0). So a subshell also
  # signals the script's main shell, whose USR2 trap (set when the guard armed) exits it with the same code. `$$` is
  # the main shell's pid in every subshell; this shell's own pid is its child's PPID (bash 3.2 has no BASHPID).
  if [ -n "${_LP_PWG_MAIN_PID:-}" ] && [ "$(exec sh -c 'echo $PPID')" != "$_LP_PWG_MAIN_PID" ]; then
    kill -s USR2 "$_LP_PWG_MAIN_PID" 2>/dev/null || true
  fi
  exit "$LP_PWG_EXIT"
}

# The one entry every guarded call goes through (the functions below, and the PATH shims).
lp_pwg_run() {
  local tool=$1 real
  shift
  real=$(lp_pwg_resolve "$tool") || real=""
  if [ "$tool" != aws ] && ! _lp_pwg_cdk_mutates "$tool" "$@"; then
    [ -n "$real" ] || { echo "$tool: command not found" >&2; return 127; }
    "$real" "$@"
    return
  fi
  if [ -n "$real" ] && _lp_pwg_is_declared_stub "$real"; then
    "$real" "$@"
    return
  fi
  lp_pwg_refuse "$tool $(printf '%s ' "$@" | cut -c1-80)"
}

if lp_pwg_test_context; then
  exec 87>&2
  _LP_PWG_MAIN_PID=$$
  trap 'exit "$LP_PWG_EXIT"' USR2
  export LP_TEST_SESSION="${LP_TEST_SESSION:-1}"
  case ":$PATH:" in
    *":$_LP_PWG_SHIM_DIR:"*) ;;
    *) export PATH="$_LP_PWG_SHIM_DIR:$PATH" ;;
  esac
  aws() { lp_pwg_run aws "$@"; }
  cdk() { lp_pwg_run cdk "$@"; }
  npx() { lp_pwg_run npx "$@"; }
fi
