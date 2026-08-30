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

```bash
python3 scripts/lane_worktree.py new <issue-N> <slug>     # creates, and LOCKS
```

This is the only sanctioned way to make a lane worktree, because it is the only one that
sets the liveness signal (#3289 — the reaper listed three *running* lanes as reapable, and
a lock each agent has to remember is a lock that is missing on exactly the lane that gets
deleted). It enforces rules 1–3 below rather than asking you to recall them.

1. **Outside the repo, in the ONE canonical parent** — `<repo>/../worktrees/<repo-name>`,
   i.e. `~/dev/worktrees/life-platform/<branch>` for this checkout. That path is defined
   once, in `scripts/worktree_paths.py`, and read by BOTH `lane_worktree.py` (which
   creates into it) and `worktree_reaper.py` (whose `--check` fails on anything outside
   it). Never a path inside the checkout — an in-repo worktree is walked by every
   repo-wide sweep and `lane_worktree.py` refuses to make one.

   > Why it is a registry and not a sentence: on 2026-08-30 the worktrees were
   > consolidated by hand from six parents into one, but `lane_worktree.py` still computed
   > a different parent — and within the hour five fresh lanes landed in a seventh
   > directory. The convention has to live where the tools read it, not where people
   > remember it.
2. **One canonical spelling.** On macOS `~/Documents/Claude/…` and `~/documents/claude/…`
   are the *same* directory, and edits through one leak into the tree the other names —
   which reads as the main checkout mutating itself. The parent is resolved to its true
   on-disk case, so invoking it through a twin spelling still lands in the canonical tree.
3. **Lane-unique name**, `issue-<N>-<slug>`, off up-to-date `origin/main`.
4. **Lane-unique scratch filenames.** Concurrent agents share one scratchpad: two lanes
   both wrote `pr_body.md`, clobbered each other in both directions, and a stray `Fixes`
   falsely auto-closed #3222 while its work sat unmerged.
5. **Never deploy from a worktree branch** — the tell is a deceptive 0-diff. Deploy from
   `main`, after merge.

**Release when the lane is done** (after the PR merges — not when the PR opens; a pushed
branch awaiting merge is still live work):

```bash
python3 scripts/lane_worktree.py release <path>    # == git worktree unlock <path>
```

Until it is released the reaper keeps the worktree, by design, and prints this command on
the kept row.

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

Every check fails closed. A worktree is a candidate only when it is not the main working
tree or the current tree, is **not locked**, has been **idle longer than the floor**
(`--min-idle-minutes`, default 120), has **no** uncommitted changes, and every commit is
either already in `origin/main` or belongs to a PR GitHub reports as `MERGED`. A `CLOSED`
PR is *not* merged and is kept; an ambiguous or unknowable verdict is kept; a detached HEAD
is kept.

**Why lock and idle, and not dirtiness (#3289).** Dirtiness *lags*: a lane is clean between
checkout and its first write, and again between its push and its merge, so a clean-and-merged
test cannot tell "finished" from "started ninety seconds ago". It is a race, and the run ten
minutes later that sees three dirty trees concludes the tool is safe. The lock *leads* — it
exists from creation — and git itself refuses to remove a locked worktree without force,
which this tool never passes. The main working tree is identified by inode, not by string,
so a case-twin spelling cannot smuggle the primary clone into the candidate list.

Read the kept list before applying — the reasons are the point, and a row you disagree
with is a bug in the classifier, not a nuisance to override. There is no flag that skips
the checks.

## Not a CI gate, deliberately

`--check` is for a session pre-flight, not for CI. A CI runner has no worktrees, so a gate
there would be green forever without measuring anything — the vacuous-gate class this repo
has already paid for (#2578).
