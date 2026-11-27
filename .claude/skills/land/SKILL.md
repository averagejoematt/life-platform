---
name: land
description: "Get a merged change actually running in production and prove it — assert the expected check set by name, swallow-check the push, dispose the deploy lease, then verify by shipped CONTENT rather than by sha. Use when merging a PR, after a merge, or whenever asked whether something is live."
user-invocable: true
argument-hint: "[PR number]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, TodoWrite
---

Four failure classes bite **every session**, and they are all in the gap between "the PR
is approved" and "the change is running". This is the one procedure that closes it.

## 1. Merge — assert the check SET by name

```bash
python3 scripts/assert_pr_green.py <PR>     # or: bash deploy/wait_pr_green.sh <PR>
```

**In its own command, unpiped, and read the verdict.** Not `gh pr checks | grep -c fail`.

- An **empty** rollup passes a naive fail-filter. That merged a PR with a red pre-merge lane.
- A lane that has not **attached** yet is invisible to a fail filter. That merged two PRs
  past a red full suite (29 incident rows are lane-subset/union-breach main reds).
- A **piped** step exits with `tail`'s status — a driver once read a gate's pre-fix output
  minutes after merging the fix.
- **Absent ≠ pass.** Compare the not-green set to the *expected* set; any extra member is
  a HOLD until its log is read. A pre-declared red is a hypothesis, not a reading.

`main` is branch-protected: one change, one branch, one PR, `Fixes #N`.

## 2. Swallow-check the push — every push, ~90s after

GitHub silently drops push events. Five in one night; one swallowed a **wrap commit** and
landed stale derived artifacts nothing saw for ~7h.

```bash
gh api "repos/averagejoematt/life-platform/actions/runs?head_sha=$(git rev-parse HEAD)" --jq '.total_count'
```

Use the **full 40-char sha** — a short sha misses `pull_request` runs (#3103). Zero runs
at a sha means **swallowed**, never "done". Recovery ladder: close/reopen the PR →
supersede-PR → integration train.

**Delay is not swallow.** Event minting has run ~10 minutes behind for a whole night: a
merge showed zero runs at its head sha for 6+ minutes and then the real run arrived. Wait
~10–15 min and re-query before invoking the ladder — escalating early mints a
`workflow_dispatch` twin, which is two runs at one sha and therefore two leases (§3).

*Discriminator:* a `GITHUB_TOKEN` reconcile push legitimately mints zero runs and touches
`lambdas/**`, so it looks identical. Without that distinction a detector pages after every
merge and gets ignored.

## 3. Dispose EVERY deploy lease — enumerate first, then approve or REJECT, never leave waiting

A gated run holds a **lease on the whole deploy group**; every later run queues behind it.
Found every session: 16.4h, 15.5h, 7.5h — and 2026-08-30's worst instance, **~9h**, was a
lease the session never enumerated: a merge train's squash pushes minted TWO runs 8 seconds
apart, the OLDER reached the gate first and held the lease `waiting`, and the session
watched the NEWER run's gate — which was `pending` behind it and structurally could never
open. A watch on the wrong member of the set is silence, and silence reads as patience.

So the step is a SET operation, immediately after every merge push (and again after every
train):

```bash
gh run list --workflow ci-cd.yml --limit 10 \
  --json databaseId,status,headSha -q '.[] | select(.status != "completed")'
```

**More than one non-completed run = multiple leases in flight.** Dispose each NOW: reject
every run whose head sha is an ancestor of the newest one (record the decode), approve
the union. Do not arm a watch until the set has exactly one live member — and any watch
you do arm must have a bounded timeout that ESCALATES (re-enumerate + report), never a
silent until-loop: 'blocked' must be distinguishable from 'still waiting'.

Decode before deciding: **reject any lease whose sha is already an ancestor of `main`** —
approving it deploys a tree missing every later merge.

**Except the reconcile child (2026-10-26, #5384).** When the newer run's head commit is the
bot's `chore(reconcile): … [skip-reconcile]` commit and its parent is the gated run's sha,
the PARENT run owns the deploy: the child's Plan logs `deploy-base: this push is a reconcile
commit and the run at its parent … ships this tree` and skips its own Deploy. **Approve the
parent; let the child finish without deploying.** Rejecting the parent strands the merge
(merged, green, nothing deployed — it happened on #5383 until a `gh run rerun` + approve).
The ancestor-reject rule still holds for two real merges in a train. The auto-filed wedge alert advises
*approve* with no ancestry check; do not follow it blindly. There is no machine half any
more: the #3021 lease janitor was retired by #4256 (ADR-158 left only the additive-IAM
deploy at the gate). The deploy dead-man (`scripts/check_deploy_deadman.py`) alarms on a
green run on main that never deployed; its alarm names the one recovery command.

## 4. Verify by CONTENT, not by sha

**For `site/**` or a `scripts/v4_build_*.py` generator, the content check is the live
page AND the newest `site-deploy.yml` run's conclusion** (`gh run list --workflow
site-deploy.yml --limit 1 --json conclusion,headSha`): the workflow publishes and then
rolls itself back on a red QA, or fails before publishing, and nothing pages either way
(#3878 3 d, #4703 23 h). A merge is not a publish; a `success` conclusion on the merged
sha is. A generator change is outside the workflow's `paths` — dispatch it
(`gh workflow run site-deploy.yml`) and read that run.

**Before merging anything that must go live — and again whenever a live check finds content
missing — read whether the plane's LAST deploy was rolled back.** A standing red gate rolls
back every later deploy whatever it carries (2026-11-15: one 5 px overflow reverted the v9
root ~9.5 h, a privacy fix with it; a smoke boundary reverted a healthy fleet). `success` on
the rollback job = reverted; `skipped` = not. Fix or land the red first — a green merge is
not a live change.

```bash
gh run view "$(gh run list --workflow web-preview-deploy.yml --branch main --status completed --limit 1 --json databaseId -q '.[0].databaseId')" --json headSha,jobs -q '.headSha[0:9] + "  " + ([.jobs[] | select(.name | startswith("Auto-rollback")) | .name + ": " + .conclusion] | join(", "))'   # v9 root
gh run view "$(gh run list --workflow ci-cd.yml --branch main --status completed --limit 1 --json databaseId -q '.[0].databaseId')" --json headSha,jobs -q '.headSha[0:9] + "  " + ([.jobs[] | select(.name | startswith("Auto-rollback")) | .name + ": " + .conclusion] | join(", "))'   # Lambda fleet
```

**A page assertion the root smoke makes is held before the merge (2026-11-27, #6320).** `deploy/smoke_test_site.sh`
asserts fixed strings on the live v9 pages and runs only after the sync; #6321 removed asserted markup, passed every
pre-merge gate and was rolled back in production. `scripts/check_www_build.py`'s scan now reads those rows
(`scripts/www_smoke_pins.py`) and fails the web gate on the PR. When a www change removes or renames page markup, change
the smoke row in the same PR; a `deploy/`- or `qa/`-only fix does not trigger the v9 deploy, so dispatch
`gh workflow run web-preview-deploy.yml --ref main -f target=root` and read that run.

**A privacy fix to the site has more than one copy (2026-11-15, #6083).** The root being right says nothing about
the preview `/next/v9/` (empty outside a rehearsal), the pages a build no longer writes (the sync never deletes), or
the nightly archive `/archive/latest.tar.gz`. One command reads every public copy against the live publication policy
and prints, in order, what a human runs — it runs none of it:

```bash
python3 scripts/check_public_copies.py --remediation   # exit 0 = every copy clean AND the archive is newer than the fix
```

Run it after the fix is live at the root, do what it prints (`deploy/quarantine_public_copy.sh` copies a public
object to `backups/` before it removes it; the archive is regenerated, never removed), and run it again until it
exits 0. The v9 deploy runs the same guard (`--check`) after every sync; a red there is a copy to repair, never a
reason to revert the root.

**The guard does not enumerate every copy yet (#6223), so a privacy removal also walks these by hand (2026-11-23/24):**
superseded link-preview images (`site/assets/og/**`), CI artifacts on this PUBLIC repo that hold rendered pages or
screenshots (`gh api repos/{owner}/{repo}/actions/artifacts` — preserve privately, then delete), every generated JSON
a writer copies the text into (`generated/*.json`, e.g. the brief's summary line in `public_stats.json`/`pulse.json`),
and every outbound channel that renders it (subscriber email). Then rebuild the archive. **Order matters:** merge the
repo-side stub or fix FIRST, then quarantine the stored copy — the reverse leaves a window in which the guard reads
the page as unreadable and reds every build (2026-11-25, ~32 min, #6266).

**A red root smoke also freezes the rollback baseline.** "Record this green root build as the previous build" is
skipped on every red run, so `www-previous/LATEST` keeps the last green build — 2026-11-22/23 it stayed ~8.7 h at a
build from before the editions, and a rollback in that window would have restored retired pages. When root smoke is
red, the rollback target is stale: fix the red before anything else ships to the root.

A CloudFront path is cached (`/archive/latest.tar.gz` for an hour, and a query string is not part of its key), so
"I re-fetched it" proves nothing until the invalidation completes.

**Merged is not deployed. Deployed is not verified.**

A `Fixes` auto-closure proves the merge and nothing else — if CI/CD died before the deploy
job, the issue reads closed while prod runs the old code. 116 incident rows are tagged
"deployment error". A deploy timestamp is not a commit. A deploy from a worktree branch
shows a deceptive **0-diff** and ships stale content; deploy from `main`, after merge.

A run **cancelled at its Deploy step** because a newer reconcile run superseded it is not a
missed deploy: the newer run's diff is *accumulated* and carries it. Do not re-dispatch on
run topology — verify by bundle content below, which is the only question that matters.

So: unzip the deployed bundle, grep for the shipped module, **and confirm its caller is
wired**. Presence of a file is not proof it is reached — a transform can be correct and
unreachable, and 15 documented fields sat dark for six days behind a green fixture test.

```bash
bash deploy/verify_deployed_symbol.sh <function-name> <symbol>
```

## 5. Release the lane — after the merge is verified, never before

A lane worktree is locked from creation (`lane_worktree.py new`) so the reaper cannot eat a
running agent. Nothing else ever unlocks it: on 2026-09-27 that was 348 worktrees, 97 still
locked, ~37 GB (#4259). So once §1 asserted the checks and the squash landed on `main`, the
**driver** (the session that ran the merge — never the lane itself) releases it:

```bash
python3 scripts/lane_worktree.py release <worktree-path | issue-number>
```

A bare issue number resolves the one `issue-<N>-*` lane (zero or several matches is an
error, never a guess). Releasing does not delete anything: the `worktree-reap` wrap gate
removes the released lane at the next `/wrap` if it is clean, idle and merged, and reports it
by name if it is dirty. A PR that is open, red or unmerged is still live work — do not
release it.

## 6. Close the loop honestly

Per ADR-099, the session that merges owns the closing comment:

```
**Shipped:** <what changed> · PR #N · <live evidence>
**Outcome:** <realized|partial|not-realized> — <did the ## Outcome sentence come true?>
```

`not-realized` and `partial` are legitimate; a blank comment beats a fabricated verdict.
**Partial acceptance is not a close** — merge the PR, reopen the issue, name the unmet
boxes.

**If the issue carries a `## Set` section (#3594),** read the PR body's own member list
before writing the verdict — "instance-only" (the PR names and fixes only the specimen the
issue happened to cite, with no count/member-list evidence the class was even considered)
is a `partial`, not a `realized`, whatever the PR's own claim says. A residual member the
PR didn't cover gets disposed exactly like any other residual above: a carrier `#N`, a fold
onto a named open issue, or `not-work — <reason>` — never silently dropped.

**An INSTRUMENT closes on its first live output, not on the merge (#3595).** If the work is
an alarm, gate, sweep, judge, ledger, scheduled job or fail-soft write, the PR carries `Refs
#N` (never `Fixes #N`), and the close waits for a comment carrying `**Live proof:** <UTC
instant> — <where>` — the first non-degraded output, pasted. `Fixes #N` is for a
product/config/doc fix a live curl proves after the deploy. Four instruments read CLOSED
while dead for 21–49 days because the merge was the close.

The full definition-of-done for a close is the registry `scripts/closure_contract.py`
(#3318; rendered in `docs/CONVENTIONS.md` §4a2). Two of its rules bite here: a `partial` /
`not-realized` verdict, or any residual the comment names, must be disposed to exactly one
home — a carrier `#N`, a fold onto a named open issue `#N`, or `not-work — <home>`; and the
PR's closing set is asserted before the merge — `deploy/wait_pr_green.sh` prints
`CLOSING-SET …` on its green verdict (advisory today; a `declared-target-mismatch` or a
`partial-acceptance-close` there is the stray-`Fixes` class that closed #3222 and #2848).

And note the case no test covers: **a green suite is necessary and not sufficient for a
timing or performance fix.** `#3231` shipped half-broken with all twelve of its own tests
green; the only symptom was one line in a durations block. Lambda CPU is memory-fractional
and boto3 sessions are GIL-bound, so a performance change validated on a laptop can invert
live — measure at origin, post-deploy.
