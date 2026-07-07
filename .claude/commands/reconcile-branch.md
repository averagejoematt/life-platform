Merge a queue of concurrent PRs that each touch the doc-sync literals
(`test_count`/`alarms`/`lambda_count`/`adrs` in `lambdas/web/site_api_common.py`'s
`PLATFORM_STATS`, mirrored into `docs/ARCHITECTURE.md`/`docs/INFRASTRUCTURE.md`) without
red-main windows or a rejected squash-merge. Canonical source: `docs/CONVENTIONS.md` §3
(squash-merge drops unpushed commits) and the "Facts that drift" table (§ near the end)
— **where this file and CONVENTIONS.md disagree, CONVENTIONS.md wins.**

## Arguments: $ARGUMENTS

The PR numbers or branch names to reconcile, in merge order (e.g. `#836 #837 #838`). If
empty, ask which PRs are in scope, or find candidates with:
`gh pr list --state open --search "site_api_common.py in:files"`.

## Instructions

### 0. Confirm the drift is real

Doc-sync literals only conflict when two PRs branched off *different* points on `main`
and each baked its own snapshot of the auto-discovered counts. If all PRs in scope
branched off the same recent `main`, this ritual is unnecessary — just merge normally.
Otherwise, work the queue below **one PR at a time, in order** — never merge two before
reconciling each.

### 1. For each PR in the queue

```bash
git checkout <branch>
git merge origin/main            # conflicts land on the PLATFORM_STATS literal lines
                                  # and the generated doc files
```

- Resolve real content conflicts normally, keeping the **branch's actual changes** (its
  new tests/lambdas/alarms/ADRs) — never discard the PR's substance.
- For the **generated** literal/doc files specifically, take main's copy first, then let
  the discoverer recompute the truth over the merged tree:
  ```bash
  git checkout --theirs docs/ARCHITECTURE.md docs/INFRASTRUCTURE.md lambdas/web/site_api_common.py
  git add docs/ARCHITECTURE.md docs/INFRASTRUCTURE.md lambdas/web/site_api_common.py
  python3 deploy/sync_doc_metadata.py --apply     # authoritative — recomputes from the MERGED tree
  git add -A
  git commit --no-edit
  python3 deploy/sync_doc_metadata.py --check     # must print the CHECK PASSED line
  ```
- Re-run the tests the merge touched, plus the truth gate itself:
  ```bash
  python3 -m pytest tests/test_platform_stats_truth.py -v
  # + whichever subset the PR's own changes exercise
  ```

### 2. Linearize before squash-merging

GitHub's squash-merge flags a branch containing a `git merge origin/main` commit as
CONFLICTING even when `main` is a full ancestor of the branch. Don't try to squash-merge
straight off the merge commit — linearize first:

```bash
git reset --soft <main-sha>      # keeps the resolved working tree, drops the merge commit
git commit -m "<original PR intent, now rebased onto current main>"
git push -f                      # force-push YOUR OWN PR branch only, never main
```

Sanity-check the result before merging: `git diff --stat origin/main..<branch> --
lambdas/ cdk/` should show only the PR's intended changes (CONVENTIONS.md §3 — lambda/cdk
drift is the dangerous kind; site/docs drift here is expected, it's the literals you just
regenerated).

### 3. Squash-merge, then advance the queue

`gh pr merge <PR> --squash --delete-branch` (or the repo's normal merge flow). Move to
the next PR in the queue and repeat from step 1 — its `origin/main` merge will now
include the PR you just landed, which is the point: each subsequent PR reconciles against
the truth as of the *previous* merge, not a stale snapshot.

### 4. Repo-specific gotcha: the `rebase --continue` phantom wedge

If you rebase instead of merging (e.g. to avoid the merge-commit problem in step 2
entirely) and `git rebase --continue` refuses with "You must edit all merge conflicts and
then mark them as resolved" **even though `git ls-files -u` is empty and the index is
genuinely clean** — this is a known repo-specific wedge (root cause unconfirmed, suspected
pre-commit-hook interference during the rebase's internal commit; not yet promoted into
CONVENTIONS.md). Don't fight it:

```bash
git commit --no-verify -C "$(cat .git/rebase-merge/stopped-sha)"   # commit the resolved index as-is
git rebase --quit                                                    # discard the wedged rebase state
git checkout -B <branch> HEAD                                        # reattach the branch
```

Only safe when the rebase todo shows "No commands remaining" (a single-commit branch);
with more commits pending, re-rebase the remainder instead.

### 5. Before deploying anything from the merged queue

`cdk diff` — read it. An unexplained `[-]`/destroy on a resource nobody touched means
`main` is behind live (a squash-heavy session dropped something), not that it's safe to
deploy (CONVENTIONS.md §3, source: #216 and the 2026-06-29 recurrence).

## Guardrails

- One PR at a time — reconciling two branches' doc-sync drift simultaneously reintroduces
  the exact conflict this ritual exists to prevent.
- `sync_doc_metadata.py --apply` is the only source of truth for the literals — never
  hand-edit a count.
- Never force-push `main`; only your own PR branch, and only after `--reset --soft`
  produced the tree you intend.
