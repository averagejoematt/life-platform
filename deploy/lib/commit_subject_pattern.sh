#!/usr/bin/env bash
# deploy/lib/commit_subject_pattern.sh — the ONE Conventional-Commits subject
# pattern, shared by scripts/install_hooks.sh's generated commit-msg hook and
# deploy/agent_commit.sh (#3642).
#
# WHY THIS FILE EXISTS. Before it, the two copies disagreed in practice. The
# hook's inline `PATTERN` used a scope class of `[a-z0-9._-]+`, which REJECTS
# this repo's own multi-issue commit convention — subjects like
# `fix(#3535,#3537): …` — because `#` and `,` are outside that class. But
# `deploy/agent_commit.sh` commits with `git commit --no-verify` (deliberately,
# to skip the hook's OTHER job, the doc-sync sweep) and never checked the
# subject at all, so the exact subject a plain `git commit` would refuse still
# landed on main whenever it went through the script. Two lanes on 2026-09-06
# used the multi-issue form and only the bypass let it through.
#
# DECISION (#3642): WIDEN, not narrow. `git log --oneline` shows the
# multi-issue scope in real, heavy use on main (driver squash-merge titles
# double as the local commit subject on the merging branch) — it is a live
# convention, not a mistake to stamp out. The scope class below admits digits,
# `#`, `,` and a following space, in addition to the original
# lowercase-alnum-dot-dash set.
#
# Usage — both callers do exactly this:
#   . deploy/lib/commit_subject_pattern.sh
#   if commit_subject_is_exempt "$SUBJECT"; then
#     : # machine-generated (Merge/Revert/fixup!/squash!/amend!) — always OK
#   elif printf '%s' "$SUBJECT" | grep -qE "$COMMIT_SUBJECT_PATTERN"; then
#     : # OK
#   else
#     : # refuse
#   fi
#
# A single source of truth means the two paths cannot independently drift
# again: change the pattern here and both the human hook and the agent script
# move together in the same commit.

COMMIT_SUBJECT_PATTERN='^(feat|fix|chore|docs|refactor|test|ci|build|perf|style|revert)(\([a-zA-Z0-9#,._ -]+\))?!?: .+'

commit_subject_is_exempt() {
  case "$1" in
    "Merge "* | "Revert "* | "fixup! "* | "squash! "* | "amend! "*) return 0 ;;
    *) return 1 ;;
  esac
}
