# Handover — Session AF: the ~20h drain, and the second permission the first one was hiding (2026-09-15 ~01:30Z → ~22:10Z)

**Driver:** Opus 5 (1M). Owner brief: *"141 open issues, get it as low as it honestly goes."* Work order was
explicit — **Phase −1** a throughput spike, TIMEBOXED 90 min (`pytest-xdist`, counts must match the serial
baseline exactly, abandon at 90 min if it isn't working); **Phase 0** #3793 solo, *diagnose which of three
causes before fixing — if the coach is right and the cockpit moved, fix the check's framing, don't silence
the coach*; **Phase 1** build the pipeline (merge_train for every landing, lane-matched worktree
implementers, `wait_pr_green` for every verdict); **Phase 2** waves down the ranked Now queue, landing #3642
and #3682 early because they protect the session's own machinery; **Phase 3** a Later/Roadmap triage sweep,
then wrap.

Standing authority to merge and deploy each batch, CDK included, announced before running. Hard constraints:
**no `--deliver`**, the recap cron's `{"deliver": false}` hold STAYS, `~/Desktop/recap-cards/` untouched,
#3760 and the 13 `gate:owner` issues out of scope, **every deploy gate approved or REJECTED, never left
waiting**. And the one that shaped every closure below: *"a closure without the evidence its label demands
is worse than an open issue."*

---

## The number, and the honest split

**141 open → 122.** Nineteen net.

| | count | |
|---|---|---|
| Issues closed | **28** | 25 `completed`, 3 `not-planned` |
| — closed on live/measured evidence | 25 | each carries the evidence in its closing comment |
| — triage (not-planned / superseded) | 3 | #3798, #3778, #3403 |
| Issues filed | **9** | 2 of them closed in-session |
| PRs merged | **19** | every one through `merge_train.sh --dry-run` first |
| CDK stacks deployed | **6** | Email, Ingestion, Monitoring, Monitoring+Operational, Serve |
| IAM grants applied | **2** | `dynamodb:Query`, then `kms:Decrypt` scoped by `kms:ViaService` |
| Deploy leases disposed | **3 approved / 9 rejected** | every ancestor rejected BY NAME, none left waiting |

The count moved 19 and 25 of the 28 closures carry evidence. **Three are triage and are counted as triage,
not as fixes** — that split is the whole point of reporting it.

---

## The through-line: the first denial masked the second

**#3681 is the session in miniature.** Session AE's #3814 granted the deploy role `dynamodb:Query` because
the theme-river live build had never once succeeded in CI — it reported its `AccessDenied` as
`skipped (offline?)` and shipped a stale artifact behind a green deploy. That grant was **necessary and not
sufficient**. The `life-platform` table is encrypted with a customer-managed CMK, DynamoDB decrypts on the
*caller's* behalf, and `Query` without `kms:Decrypt` on that key is a second denial sitting directly behind
the first. The Query denial short-circuits before KMS is ever consulted, so **no amount of reading the code
could have found it — only the run after the first fix.**

What made that discoverable at all was #3814's own instrument, and its proof is the run that went red:

```
⛔ theme river build FAILED — CAUSE: denied (exit 1). site/data/theme_river.json was NOT regenerated.
   Step: theme river  ·  Command: python3 deploy/../scripts/v4_build_theme_river.py --live
… not authorized to perform: kms:Decrypt on resource:
arn:aws:kms:us-west-2:205930651321:key/444438d1-a5e0-43b8-9391-3cd2d70dde4d
```

The old idiom printed `skipped (offline?)` at exactly that line and shipped green. After the second grant,
`site/data/theme_river.json` at 19:21:29Z:

| | committed twin | LIVE |
|---|---|---|
| `state` | `empty` | **`warming_up`** |
| `n_days` | `0` | **`2`** |
| `n_themes` | — | **`8`** |
| `window` | `2026-09-06 → 2026-09-06` | **`2026-09-06 → 2026-09-15`** |

**First successful theme-river live build in CI, ever.**

---

## What shipped, merged AND verified live

**#3793 (Phase 0) — the coach was right.** The brief said diagnose which of three causes before fixing, and
the answer changed the fix. The coach cited recovery 73% against a cockpit serving 63%, and the cockpit had
moved between reads. The defect was the **checker's framing**: `_DATED_SENTENCE` did not recognise a prose
calendar date, so a citation that named its own date was tested against *current* state. Two things fell
out that patching the symptom would have missed — `may` had to be excluded from the unambiguous-month set
(it is a modal verb in ordinary coach prose), and `weights_cited_in`/`vitals_cited_in` were splitting
sentences separately so `Sept.` broke one and not the other. Live: `ContentTruthFailCount` 1.0 through
09-14 19:00 PT, **0.0 from 20:00 onward**; latest run `[QA] CAUSE fail none -`, PassCount 71, FailCount 0.

**#3714 — adherence found a real one on its first live session.** Deployed, then asked the live MCP server
for the real 2026-09-13 legs session: `tmpl:75A4F6C4` carried a ceiling of RPE 7.0 and all four working
sets came back at 8.0. The old calculator scored that movement **`pct: 100.0`** — and still does, correctly
labelled now as the set-count dimension. `as_prescribed` is an AND of two dimensions and never their
average; absent RPE is `unknown`, never `pass`.

**#3499 — the facet spans two stacks, and that mattered.** After deploying Monitoring the reader-audience
routing read **3/11**. The eight `site-api-*` alarms live in `serve_stack.py`, not `monitoring_stack.py` —
exactly the tagged-but-unrouted state the synth dead-man exists to prevent, visible only because the check
read AWS rather than the CDK tree. After `LifePlatformServe`: **11/11**, both actions on every member. The
remediation cron moved from 95 minutes *before* the canary it reads to **75 minutes after** (16:20Z →
17:35Z).

**#3563 — 46 metric filters armed, alarm live.** `swallowed-permission-denial` exists at
`INSUFFICIENT_DATA`, which is the correct state: no swallowed denial since arming. All three sampled Bedrock
roles verified carrying `PutMetricData` **against the deployed roles, not the CDK source**. Stays OPEN on
leg 1 — the bar is `coach-nudge` emitting `EstimatedCostUSD`, and that cron had already run today before the
deploy. I deliberately did **not** hand-invoke it: it is an email Lambda and a regen-invoke sends real mail.

**#3804 — the stash guard, mutation-proved on the real lane docs.** Six repository-level git operations
enumerated with a verdict each, including the *safe* rows — that is what makes it a set rather than a list
of grievances. **An honest limit I found by trying to break it and failing:** stripping `refs/stash` from
both lane docs left it green, because `reason_markers` are alternatives and `repository-level` still
matched. It enforces that *a* reason accompanies the prohibition, not that the reason is correct. That is
weaker than the title implies and it is written into the closing comment rather than left for discovery.

---

## What the guards caught in MY work, again

**The #3688 Set guard went red during its own rebase**, naming `lambdas/training/training_notes_llm.py:119`
— a truncation decision that landed on main from #3699 *after* that branch was cut. A fourth member of a
Set that was 3/3 when enumerated, found by the guard rather than by anyone reading the diff. Registered as a
**residual, not covered**, and the reason is the interesting part: #3688's remedy is to *retry*, correct for
the two covered judges because their truncation is nondeterministic. Here it is **deterministic** — fixed
cap, fixed note text — so N retries bill N times for N identical failures. The module's own registry facet
already named the right response (`re_derive_when: "… or TruncatedResponse is ever observed live"`).
Filed #3828.

**I measured the #3797 census at 644 and it was wrong.** The extra id was a #3315 registry-name **phantom**:
`PR_CHECKS`, a single path string, matched `gate_census._REGISTRY_NAME`'s `.*_CHECKS` arm and the census
minted a `registry::` gate for something that is not a registry. The lane test's own message names the
remedy — rename the constant, don't ledger a gate that does not exist. Re-measured: 643.

**The five-test arithmetic gap I posted as an open item on #3797 does not exist.** Settled by
`--collect-only` on all three selections, diffing **node ids** rather than totals: full 26,401 / `not serial`
26,353 / `serial` 48, with *in ALL and in neither pass*, *in a pass but not in ALL*, and *in BOTH passes* all
empty. The earlier discrepancy was two numbers from different runs on different trees with the suite five
tests larger by the second. That is now a **structural test** (the two `-m` expressions must be exact
complements over one registered marker), mutation-proved three ways, not an observation in a comment.

**My closure comment on #3793 carried the right evidence in an unparseable shape.** `**Live proof —**`
instead of `**Live proof:** <instant> — <where>`. For a machine-read contract that is the same as missing,
and the closure sweep said so.

---

## The find nobody was looking for

Chasing a stale alarm citation at wrap produced **#3829**, a live P1. Two DLQ alarms were cited as
*"not-work — a fired-and-cleared flap, recorded 2026-09-13"*. Both re-entered ALARM at 17:18Z today, and
those citations' own notes said a second transition stops being a flap. The queue was not empty:

```
{"cycle_date": "2026-09-15"}   SentTimestamp 1789492547367
```

Producer identified by timestamp — `coach-ensemble-digest`'s last log event is 120 ms earlier. It logs
**`Ensemble digest produced — 7 summaries, 6 disagreements, 5 unanimous flags`** and then dies at its 90 s
ceiling. `ENSEMBLE#digest` has **no `CYCLE#2026-09-15` row**. Duration has crept 57–62 s → the ceiling over
eight days; `SampleCount 3` on a once-daily cron is the async-retry signature, so a timeout bills **3 × 90 s**
and does the full Bedrock work each time. A success line for work that did not land — the third instance of
that shape this month. **Stated as unexplained:** 09-13 ran in 52.4 s with one invocation and *also* has no
row, so the timeout does not cleanly predict the gap and I did not invent a cause for it.

---

**Build beat:** none — the session's headline work (#3681's two-grant fix, #3499's routing) is merged and
deployed, but the reader-visible half is a `state: warming_up` artifact with 2 of 14 days of data; a beat
about it would be narrating machinery, not a shipped reader experience.
**Docs:** `infra/iam/README.md` (the new `KMSDecryptViaDynamoDB` statement and why it is separate from the
plain-`DescribeKey` Sid), `docs/alarm_citations.json` (three citations re-pointed), `docs/PROPORTIONALITY.md`
(642 → 643 declared gates, by `sync_doc_metadata.py --apply`).
**Decisions:** none needed — the one posture choice (scope CI's `kms:Decrypt` by `kms:ViaService` rather than
granting it outright) is recorded in the statement itself, the IAM README, and a mutation-proved guard; it
narrows an existing grant rather than setting new architecture policy.
**Main:** stranded — CI/CD run `35013357326` on `14e8aaa93` has `Deploy: success` and `Post-deploy
integration checks: success`, but `Smoke test: failure` on the **`Verify canary`** step (19:54:49→19:54:57Z,
8 s). The same canary invoked live at **20:02:41Z returns `all_pass: true, failures: 0,
failed_deploy_health: 0`** across DDB/S3/MCP/Bedrock — so the gating lane is healthy now and the failure is
the known smoke-vs-deploy race class, not a live defect. The `Auto-rollback (smoke failure)` job had **not
resolved** at wrap time (it queues behind Unit Tests and Visual QA); if it fires it will strip a
verified-correct fleet deploy, which is the #2051 incident shape. **Next session: read that job's outcome
first.** Separately, the R8-ST6 Plan-red strand that had blocked every deploy is **cleared** — `Plan
deployments: success` on this run, unstranded by the KMS grant and the CDK deploys.
**Incidents:** none — the canary smoke failure is recorded in the `**Main:**` line above and is not yet
incident-class: the gating lane is green live, no rollback has fired, and no data gap or >1h main-red
occurred. If the auto-rollback DOES fire, that firing is incident-class and gets its row the session that
sees it.
**Stash/hooks:** clean — the stack is empty and the hook is 🟢 fresh. One entry was found and dropped: the
FOREIGN `stash@{0}` the #3688 lane left contaminating the #3756 worktree on 2026-09-14. Before dropping I
verified its 236 payload lines are **byte-identical** to what `origin/issue-3688-judge-truncation-retry`
now carries, and archived the patch to the session scratchpad anyway.
**Closures:** #3793, #3714, #3681, #3804, #3499, #3563(commented, still open) commented — plus 22 earlier in
the session · DoD: `closure_sweep.py --session` scanned 28, hits 17, **blocking=none** (the one blocking
`no-live-proof` on #3793 was fixed by re-posting its proof in the parseable grammar); the residual warn-mode
hits are `no-outcome-verdict`/`unhomed-residual` on issues closed in the session's first half.
**Backlog:** Now live at 5 actionable in the opus lane (floor 3) — no promotion needed; 7 more `Now` stories
are `gate:owner`/`blocked:*` and correctly not counted. `later_staleness` sweep: **zero** stale issues —
`check_backlog_hygiene.py --rule later_staleness` returns OK over all 122 open. **Residual, stated not
hidden:** 5 `acceptance_count` violations (#3607, #3611, #3615, #3617, #3621 — 6–8 boxes against a 3–5
contract). I read #3607's seven: they are seven distinct substantive requirements, not padding. Trimming
them to hit a count would degrade real acceptance criteria to satisfy a number, which is the one thing this
session's brief ruled out. They need the issues' owner to split or re-scope them, not a wrap to shave them.
**Alarms:** 0 uncited — `check_alarm_citations.py` exits 0 across all four legs. Three citations were
re-pointed this session: `qa-smoke-failures` (had opened `#3793 —`, which became a violation the moment that
issue closed on the cure; rewritten with **no `#N` anywhere**, citing the fixing PR by squash sha, the
measured metric series, and a stated expiry of ~2026-09-16T00:00Z when the 24h Maximum bucket no longer
contains a pre-deploy datapoint), and both DLQ siblings re-pointed from the closed #2912 to #3829.
**CI warnings:** none to triage — `check_ci_warnings.py` reports the latest completed main run isn't green,
so there is no green-run annotation set to read; that is the `**Main:**` line's business, not this gate's.
**Ledger:** none — no standing machinery shipped. The census moved 641 → 643 across #3811 and #3807 and
`docs/PROPORTIONALITY.md` was stamped to match, but every entrant is a guard/test inside an existing
subsystem's posture, not a new subsystem with its own rent row.

---

## Residual / next picks

- **Read `Auto-rollback (smoke failure)` on run `35013357326` FIRST.** `not-work — a standing ops read, not
  a backlog item.` If it fired, it stripped a verified-correct fleet deploy (#2051 shape) and needs a
  re-deploy plus a `docs/INCIDENT_LOG.md` row that session.
- **#3797 is GREEN and deliberately held.** `#3797` — it and #3807 both stamp the census at 643 from a
  common base of 642; whichever lands second must read **644**. It needs a rebase, a re-measure on the
  rebased tree (never by arithmetic, confirmed by id-set diff against a `git archive` of the merge-base) and
  a re-stamp of two literals. The precise three-step recipe is on the PR.
- **#3807 was mid-merge-train at wrap and is still OPEN.** `#3807` — it was green on `57734c469`, but `main`
  moved under it (my two direct docs/chore commits), so the train reconciled it onto `b7e6bb598` and is
  **re-watching checks** before merging. Stacked validation PASSED. Verify its disposition at source
  (`gh pr view 3807 --json state,mergedAt`), **never from a monitor event** — Session AE reported a PR merged
  that had actually been dropped, off exactly that mistake. If it landed, main's census is 643 and #3797 must
  re-stamp to 644; if it did not, #3797 re-stamps to 643 and #3807 goes second.
- **#3563 stays open on leg 1.** `#3563` — the bar is the next scheduled `coach-nudge` run emitting
  `EstimatedCostUSD` where 30 days have none. That cron is 15:10Z daily. Do not hand-invoke it.
- **#3829 is a live P1 filed this session.** `#3829` — `coach-ensemble-digest` times out daily, bills 3×90 s,
  and drops rows. Its 09-13 gap is explicitly unexplained.
- **#3828** — `#3828` the training-notes truncation residual, P3/Later, zero live observations.
- **`Bash(bash deploy/cdk_deploy.sh:*)` is in the working tree and deliberately NOT committed.**
  `not-work — an owner decision.` It was approved to unblock one deploy this session; committing it would
  turn a one-time unblock into a durable repo-wide grant for an infrastructure mutation, which the standing
  operator rule says is ask-first *even where a permission rule would allow it*. The ten read-only checker
  entries beside it WERE committed (`78c8e71df`).
- **Two commits went straight to main past branch protection** — `78c8e71df` (permissions chore) and
  `76ec4d2bd` (alarm citations). `not-work — sanctioned by this session's brief ("wrap/docs commits go
  straight to main — that's settled"), recorded here so the audit trail is explicit rather than discovered.`
- **5 `acceptance_count` backlog violations** — `#3607`, `#3611`, `#3615`, `#3617`, `#3621`. Each needs its
  acceptance list split or re-scoped by someone holding the issue's intent.
