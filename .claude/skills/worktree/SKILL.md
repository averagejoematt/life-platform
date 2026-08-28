---
name: worktree
description: "Create a git worktree correctly, or inventory and safely retire stale ones. Use when starting isolated work on an issue, when worktrees have accumulated, or when a test passes locally and fails in CI (or vice versa) and stale checkouts are the suspect."
user-invocable: true
argument-hint: "[new <issue-N> | list | reap]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, TodoWrite
---

Create worktrees the way this repo has learned to, and retire them before they start
lying to you.

## Why this exists

Worktree sprawl is not untidiness here — it corrupts verdicts, and always in the worse
direction: **the polluted developer machine is the one that looks clean.** Two failures
in a single session (2026-08-27), from 93 worktrees across 12 parent directories:

- `tests/test_hevy_compiler_isolation.py` failed locally and passed in CI. A stale in-repo
  worktree is a full second checkout, and the repo-wide sweep walked it. #953 had already
  fixed this once — by name, for the .claude/worktrees directory only — so a second
  in-repo root (.worktrees) reproduced it exactly.
- `scripts/skill_lint.py` **passed** locally and failed in CI, because a skill pointed at
  that same gitignored directory — present only on a machine carrying stale worktrees.

## Mode: `new <issue-N>`

1. **Outside the repo.** One canonical parent, never a path inside the checkout. An
   in-repo worktree is walked by every repo-wide sweep.
2. **One canonical spelling.** `git worktree list` currently shows both
   `~/Documents/Claude/…` and `~/documents/claude/…`. On macOS those are the *same*
   directory, and edits through one leak into the tree the other names — which reads as
   the main checkout mutating itself.
3. **Lane-unique name**, `issue-<N>-<slug>`, off up-to-date `origin/main`.
4. **Lane-unique scratch filenames.** Concurrent agents share one scratchpad: two lanes
   both wrote `pr_body.md`, clobbered each other in both directions, and a stray `Fixes`
   falsely auto-closed #3222 while its work sat unmerged.
5. **Never deploy from a worktree branch** — the tell is a deceptive 0-diff. Deploy from
   `main`, after merge.

## Mode: `list`

```bash
python3 scripts/worktree_reaper.py
```

Reports every worktree grouped by parent, flags case-twin paths and any worktree **inside**
the repo, and classifies each as reapable or kept *with the reason*.

## Mode: `reap`

```bash
python3 scripts/worktree_reaper.py            # dry run — always read this first
python3 scripts/worktree_reaper.py --apply    # remove only the reapable ones
```

Every check fails closed. A worktree is a candidate only when it is not the main checkout
or the current tree, has **no** uncommitted changes, and every commit is either already in
`origin/main` or belongs to a PR GitHub reports as `MERGED`. A `CLOSED` PR is *not* merged
and is kept; an ambiguous or unknowable verdict is kept; a detached HEAD is kept.

Read the kept list before applying — the reasons are the point, and a row you disagree
with is a bug in the classifier, not a nuisance to override. There is no flag that skips
the checks.

## Not a CI gate, deliberately

`--check` is for a session pre-flight, not for CI. A CI runner has no worktrees, so a gate
there would be green forever without measuring anything — the vacuous-gate class this repo
has already paid for (#2578).
