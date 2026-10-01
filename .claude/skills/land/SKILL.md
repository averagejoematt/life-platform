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
approving it deploys a tree missing every later merge. The auto-filed wedge alert advises
*approve* with no ancestry check; do not follow it blindly. There is no machine half any
more: the #3021 lease janitor was retired by #4256 (ADR-158 left only the additive-IAM
deploy at the gate). The deploy dead-man (`scripts/check_deploy_deadman.py`) alarms on a
green run on main that never deployed; its alarm names the one recovery command.

## 4. Verify by CONTENT, not by sha

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
