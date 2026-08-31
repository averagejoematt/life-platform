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
*approve* with no ancestry check; do not follow it blindly. The machine half of this step
is the #3021 janitor (`deploy-wedge-watch.yml`): it auto-rejects superseded waiting leases
once `DEPLOY_GATE_JANITOR_TOKEN` exists — if its job is red on a 4xx, the token is missing
and this whole section is running on manual reflexes.

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

## 5. Close the loop honestly

Per ADR-099, the session that merges owns the closing comment:

```
**Shipped:** <what changed> · PR #N · <live evidence>
**Outcome:** <realized|partial|not-realized> — <did the ## Outcome sentence come true?>
```

`not-realized` and `partial` are legitimate; a blank comment beats a fabricated verdict.
**Partial acceptance is not a close** — merge the PR, reopen the issue, name the unmet
boxes.

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
