# Handover — 2026-08-20 (morning, ~08:27 → ~09:5x PT): the fable floor moved, and I was wrong about a colour

**Session:** Opus, owner-directed (plan `playful-toasting-owl.md`, model ceiling Opus). Boot was
**charter + `blast_radius.py`**, not a prose re-read. **The rule changed this session:** `model:fable`
is no longer fully untouchable — Opus **may** relabel a fable issue with a written reason and **may**
close genuinely-dead ones, but **may not BUILD** any of them. #2846 stays Fable-sequenced regardless
(#2847 turned out to already be `model:opus`). Previous wrap archived as
`HANDOVER_2026-08-19_backlog-drain-round-1.md`.

**Build beat:** none — every merge this session is internal (guards, DLQs, MCP field-stripping, alarm
routing, a citation prune). Nothing reader-facing shipped, and per
`docs/content/BUILD_DISPATCH_CHECKLIST.md` a beat must be merged **and** deployed work a reader can
see. Nothing here qualifies, and nothing was deployed.

**Main:** **stranded, not red** — every code gate is green (lint, Deploy-critical tests, Unit Tests all
`success`); only `Plan deployments` failed, on the **R8-ST6 IAM-review gate**, because merging #2694
introduced `sqs:SendMessage` grants for 13 DLQs and CI structurally cannot ship IAM. `Deploy` was
SKIPPED, not failed. **I caused this by merging #2694, and it now blocks every ci-cd deploy** until
`bash deploy/cdk_deploy.sh LifePlatformOperational` runs from main (owner ask #1). This is #2834's
thesis happening live in the session that relabelled it. **Nothing was deployed** — three CI/CD
production gates were **rejected**, never left waiting (#1901 class).
**Closures:** #2741, #2670, #2782, #2647, #2646, #2804, #2755, #2694, #2708 (9). **Filed:** #2912 (1).
**Re-scoped, not closed:** #2734, #2883, #2815 (all retitled to what is now true), #2692 (confirmed
live, no re-scope needed).
**Relabelled off fable:** #2813, #2824, #2803, #2761, #2841, #2890, #2833, #2834, #2797, #2832 (10).
**Alarms:** 0 uncited. The registry itself was pruned 15 → 2 entries (PR #2917).
**Stash/hooks:** clean.

---

## The count, honestly

**95 → 87 open. 9 closed, 1 filed, 8 net.** And the number that actually matters this session:

**`model:fable` 36 → 25.** One closed (#2782, genuinely delivered), ten relabelled with a written
reason on each issue. The floor last session was ~39 with the fable set frozen; it is now ~25.

That is the whole point of the session and it is worth separating from the drain number. The drain
number is modest. **The floor moved by 11**, and 10 of those are issues that were never Fable work in
the first place — they were AST guards, registry facets, parametrized sweeps, and a Secrets Manager
consolidation, sitting behind a model queue they had no reason to be in.

Seven PRs opened; five merged at time of writing (#2909, #2910, #2911, #2915, plus the #2914/#2913/
#2916/#2917 queue in flight — see "left in flight").

---

## Phase 0 — both clocks, and one cron correctly dropped

Boot was **Thu 15:27:39Z / 08:27:39 PDT**. `daily-brief` (17:00Z daily) had **not yet fired** — 1h33m
out. `wednesday-chronicle` is **Wednesdays only** and today is **Thursday**; next run 2026-08-26. I
said so and dropped it rather than hunting a run that cannot exist.

**The namespace correction from the plan held:** `LifePlatform/QaSmoke`, not `LifePlatform/QA`.

### #2741 (P1) closed `realized` — the last box was earned overnight

Box 5 needed two halves that had never co-existed. Both were live:

```
life-platform-qa-smoke  LastModified 2026-08-19T22:37:49Z  (= 15:37:49 PDT)
FailCount 0.0 at 2026-08-19T15:40 PDT   <-- 2m11s AFTER that deploy
Alarm updated from ALARM to OK  2026-08-19T19:53:11.160-07:00
```

Four consecutive `FailCount: 0` runs, the last unambiguously post-deploy, and the transition banked in
`describe-alarm-history` rather than inferred from current state.

### #2670 closed `realized` — and the planted test cost nothing

All four **body** boxes (the later comment's numbering is off by one — I read the body, per the plan).
Box 3 wanted a *planted* failure driving a real OK→ALARM transition, only possible while both alarms
sat at OK.

```
$ put-metric-data --namespace LifePlatform/QaSmoke --metric-name WarnCount --value 1
Alarm updated from OK to ALARM  2026-08-20T08:34:27.517-07:00     (50 seconds later)
```

**I planted on `-warnings`, deliberately not `-failures`** — box 3 says "one of them", and
re-saturating the blocking alarm we had just spent #2741 getting green would have blinded tonight's
18:30Z run. Blast radius was checked *before* planting: the alarm action is SNS
`life-platform-alerts-digest`, which fans out to an **SQS queue** (no pager, no direct email), and
`repository_dispatch` fires the remediation agent only on a confirmed *deploy wedge*, not on qa-smoke.
Nothing was paged.

**Box 4 was satisfied by not needing it.** Both thresholds are still `>= 1.0`. The alarms were
desaturated by fixing the findings and classifying the accepted ones as chronic
(`[QA] 7 warning(s) (0 alarmed, 7 chronic), 0 failures`) — **not** by widening the line until the red
went away. That is the better outcome and the closure says so.

### I published a wrong prediction and corrected it on the issue

I wrote in the closure that the planted datapoint would hold the alarm red for ~24h on a trailing
window, inferred from two organic clearances that both landed at 24h+3min. **It self-cleared in 60
seconds.** The residual cost of the test was zero.

The metric shows exactly one datapoint and no zero (`Maximum 1.0 / SampleCount 1.0` at 08:33), yet the
recovery reason cites `[0.0 (…15:35:00)]` — that is `TreatMissingData: notBreaching` rendering an
**empty evaluation window** as zero.

**What I could not explain, and said so rather than inventing:** the same alarm held ALARM for ~2 days
organically but 60 seconds on a planted breach. Same alarm, same metric, same threshold. I filed that
as **#2912** rather than stretching the closure to cover it, because it has a real operational edge:

> the `/wrap` citation gate (#1959) keys on alarms in ALARM **>72h**. An alarm that flaps for 60
> seconds is invisible to it by construction.

That is #2670's own thesis with the sign flipped — *a saturated alarm hides its own findings*, and so
does a flapping one. Nothing currently detects the second case.

## Phase 0b — four premises re-verified, three were stale

The plan warned this bit twice last session. It bit again, three times out of four.

- **#2734 — the projection half is now FALSE.** Title said "171% of the ceiling". Live at
  `2026-08-20T08:00:15Z`: `projected=$160.90` vs `effective_ceiling=$200` = **80.5%, under**.
  Re-scoped and retitled. The alarm half is not just live but **structurally permanent**: under the
  new $150 base the run rate ($1.74 + $2.22 = $3.96/day → ~$118.80/mo) is **79.2%** of ceiling, which
  lands in band 1 — so `budget-tier-sustained-7d` is lit forever by design. That is the #2670 defect
  class freshly recreated, and it is now the issue's only open box.
- **#2883 — headline stale.** `CostMetricDriftRatio` fell **2.4673 → 1.3673** during 08-19 and is
  holding. But the bar is **< 1.15 sustained 7d**, so it does *not* close — closing at 1.37 would
  repeat #357 verbatim, one decimal further along. Retitled to the measured number.
- **#2815 — substantially already shipped by #2908.** Boxes 1–3 verified done on `main`; the two
  `utc-exempt(#2815)` annotations exist at `coach_quality_gate.py:305` and `ai_calls.py:2344` with the
  shared-frame rationale. Re-scoped to the real remainder (convert the `OUTPUT#` frame atomically),
  which is **blocked on extracting a sibling out of `ai_calls.py` — 2396/2396, zero headroom**. Also
  corrected: `coach_memoir_lambda.py` is at `lambdas/compute/`, not `lambdas/emails/`.
- **#2692 — live, and WORSE than filed.** Last green main run: `21:38:26Z → 22:00:26Z` = **1320s**
  against the 1200s budget. Trend now `157 → 294 → 688 → 830 → 1247 → 1320`. **I also recorded the
  retraction I owed:** my prior-session 937s "trend reversed" reading was wrong; 1323s then and 1320s
  today bracket the real number.

## Phase 1 — five workers, seven PRs, and one thing I got wrong

Verified **every** worker against its **branch**, never its report. That has now held six sessions.
All five branches were clean on the `aws_cdk`-import trap (the thing that red-mained main last
session), all module-size ratchets respected, all `Fixes` keywords single and un-negated.

Two workers over-reported line counts (220 vs 177 actual; 206 vs 163) — immaterial, but it is a
consistent direction and worth knowing.

**The correction that matters — #2757, and I was the one who was wrong.**

Worker 1's fix derived coach title/colour from the registry. I checked the branch and found a defect
its report missed: `#f59e0b` is shared by **`labs_coach` and `physical_coach`** in
`config/personas.json`, so deriving as-is would make two different coaches render identically — *a
fresh instance of the exact bug #2757 exists to fix.* Good catch, correctly sent back.

Then I over-reached. I also told it to revert the sleep/nutrition colours to the hand-typed values, on
a least-blast-radius argument: three surfaces show `#818cf8`, only one shows `#8b5cf6`, so change one
not three. The worker **pushed back in writing** rather than complying. I went and read #2757's body
myself, and it settles it against me:

> `#10b981` is layne_norton's registry color, **a pre-roster-v2 palette** … `config/personas.json`
> agrees with the registry

Three copies of an obsolete value is not majority evidence — it is the duplication the issue exists to
delete. I retracted. **The worker was right and my surface-count reasoning reached the wrong answer
from correct arithmetic.** Final state keeps registry values for sleep/nutrition, overrides only
`labs_coach` (whose registry value was a genuine collision bug), promotes the fuller public titles
*into* the registry, and adds an operational-set colour-uniqueness guard — which is the most valuable
thing in that PR.

**Worth preserving from the other workers:**

- Worker 3 found `test_daily_debrief.py`'s fixture had a **hand-typed `"zone"` key that was not the
  real wire shape** — the fixture was masking the very bug #2804 reports. *Fixture must be the wire*,
  found in the wild.
- Worker 5 **imported** the us-east-1 SNS topic rather than creating a second one (which would have
  fragmented live subscribers), and flagged a pre-existing `dash-total-errors` dimension mismatch
  instead of silently "fixing" it.
- Worker 2 mutation-tested its DLQ guard live (reverted one `dlq=`, confirmed two tests red, restored).

## Phase 2 — the fable triage pass (the session's real output)

**36 → 25.** The test applied to each: *does this need narrative or product-voice judgement, or is it
structural work any capable model can execute against its own acceptance criteria?*

| issue | → | why, in one line |
|---|---|---|
| #2813 | sonnet | parametrized tz sweep generalising a **named precedent file**; tight spec |
| #2824 | opus | fleet-wide AST grant-drift guard — "guard the SET, not the instance" |
| #2803 | opus | privacy tier as a registry column + AST read-discovery gate |
| #2761 | opus | the #2380 wrap gate that has **silently failed every session since it landed** |
| #2841 | opus | a posture decision + one convention line; the evidence is measurement |
| #2890 | opus | Secrets Manager consolidation; blast-radius analysis *is* the work |
| #2833 | opus | already `gate:owner`; the deliverable is an ADR amendment, not prose |
| #2834 | opus | already `gate:owner`; option (b) is an IAM **diff-gate design** |
| #2797 | opus | its own child #2803 is opus — an epic that cannot schedule coherently |
| #2832 | opus | explicitly "the `test_heartbeat_completeness` pattern applied to reviews" |

**A correction to the plan:** it suggested #2833/#2834 might be *reclassified* to `gate:owner`. They
already carry it. The convention pairs `gate:owner` **with** a model label (cf. #1738 `model:opus` +
`gate:owner`), so the right action was a model swap.

**Left as genuinely Fable**, unchanged: #748, #1380, #1388, #1389, #1391, #1398, #1407, #1414, #1415,
#1570, #1631 (its own body says "gated, do NOT build yet"), #1629, plus the narrative epics and
**#2846** (excluded by standing instruction) and **#2842** (the Kernel).

**#2782 closed `realized`** — the BodyScan 2 spike delivered: `MEAS_TYPES` **21 → 30**, SoT rulings
recorded by name at `SCHEMA.md:329`, ADR-104 absence semantics (`spo2_pct` zero is never stored), and
`docs/NEW_SIGNAL_PLAYBOOK.md` + ADR-154 now cited in the charter as *the* paved road for a signal.
**One of its findings was wrong and the closure says so:** `SCHEMA.md:327`'s "all current consumers are
field-selective (verified in #2782)" was false — #2809 is fixing exactly that.

## Phase 3 — structural hygiene

**Two epics closed, both fully delivered, neither noticed:**

- **#2647** — all 8 children (#2659–#2666) closed. Its last box ("the error-suggestion table
  references only tool names that exist in `mcp/registry.py`, **enforced by a test**") is live at
  `tests/test_mcp_suggestion_tool_names_2666.py`. A one-word edit became a derivation guard.
- **#2646** — all 6 children closed. **Its body checkboxes still showed #2686/#2688 unchecked while
  both issues were `CLOSED/COMPLETED`.** I closed on issue state, which is the authority, and said so
  — that checkbox drift is #2802's thesis in miniature.

**Nine milestone-less non-fable epics → zero.** #2798/#2799/#2801/#2802/#2753/#2645 → `Next`, #1737 →
`Later`. #2801 is **not** realized — only its first box (#2836) landed; 8 stories remain open.

## The alarm-citation registry was 13/15 stale (PR #2917)

Verified live: every removed entry's alarm is `OK` **and** its cited issue is `CLOSED` — including the
whole Whoop cluster (#1934; Whoop's newest row is `DATE#2026-08-20`, ingesting normally again). Kept
the two whose alarms have not cleared: `budget-tier-sustained-7d` (#2734) and
`token-alarm-genesis-window-active` (#2116 closed, but **the alarm is still lit**, which is exactly
what the header's "AND" requires).

This matters because that registry is what the **only gate that has ever obligated anyone to look at a
lit alarm** reads. 13 of 15 rows describing alarms that went quiet weeks ago makes it read like an
active incident board while describing history.

## An incident I caused

**`gh pr merge #2910 --squash --delete-branch` auto-closed the stacked PR #2914**, because #2914's base
*was* that branch. Recovered by pushing the branch sha back to origin, reopening #2914, retargeting to
`main`, and `git rebase --onto origin/main` to drop the already-squash-merged commits. No work lost.
**Lesson: never `--delete-branch` a PR that is the base of another.**

## The doc-sync literal treadmill, and how I broke it

Every PR that adds tests moves the `test_count` literal, so five concurrent PRs all went red on
`Wiki drift gates`, and each merge invalidated the next. Ran the `/reconcile-branch` ritual for the
first (it works exactly as written), then switched to a cheaper move for the rest: **replay only the
PR's substantive files onto current `main` and omit the literal edits entirely.** No conflict is
possible, and `main`'s post-merge reconcile automation regenerates the literal — verified: `main` at
`a223d8e02` passes `sync_doc_metadata.py --check` cleanly.

**Also confirmed:** `sync_doc_metadata.py --apply` stamps `Last updated:` dates into ~8 unrelated docs
that `--check` reports as `already in sync ✓`. Hand-patch the numbers; do not run `--apply` on a branch.

## A near-miss worth recording

`gh pr checks 2915` reported `{"notgreen":0,"total":7}` — and **"Collect + deploy-critical + format"
was simply absent from the list**, because its run had not registered yet. A shrinking check set reads
identical to a green one. Asserting the rollup is not enough; the *set* has to be right too. Caught it
by querying runs for the head sha directly.

## Left in flight

- **#2914** (#2809, Tier-2 privacy strip) — MERGEABLE, replayed clean, awaiting lane
- **#2913** (#2829, us-east-1 alarms) — replayed clean, 172 passed locally, awaiting lane
- **#2916** (#2757, coach identity) — reworked + rebased, awaiting lane
- **#2917** (citation prune) — awaiting lane

All four are substantively verified against their branches; only CI lanes remain.

## Owner asks (numbered)

1. **Deploy authorization — now URGENT, because the pipeline is stranded.** Nothing shipped this
   session; I **rejected** three CI/CD production gates rather than strand them (#1901 class). But
   merging #2694 tripped the **R8-ST6 IAM-review gate** (13 DLQs → `sqs:SendMessage` grants), so
   `Plan deployments` now fails and **every future ci-cd deploy strands until an owner-run
   `cdk deploy` lands from main.** Order matters:

   **(a) first** — `bash deploy/cdk_deploy.sh LifePlatformOperational` (ships #2694's DLQs *and*
   clears the IAM gate). Read the `cdk diff` before approving: expect S3Key rehashes plus 13 new
   `DeadLetterConfig` blocks and their `sqs:SendMessage` statements, and **nothing else**.
   **(b) then** — recover the stranded half with a `deploy_all=true` `workflow_dispatch` of
   `ci-cd.yml`, which ships the code-only fixes below.

   Three merges want the code deploy:
   - `#2804` + `#2755` + `#2708` → the shared `lambdas/` bundle (code-only, no CDK, no IAM).
     `daily-debrief` and `life-platform-mcp` both still read `LastModified 2026-08-19T22:3xZ`, which
     **predates every merge** — so all three closures are recorded `partial`, not `realized`.
   - `#2694` → **`bash deploy/cdk_deploy.sh LifePlatformOperational`**. CDK-owned; a code deploy
     cannot ship a `DeadLetterConfig`. This is the #2806 class, stated up front this time.
   - (after #2913 merges) → `LifePlatformWeb`, **region us-east-1**.
2. **A Withings weigh-in.** Newest row is still `DATE#2026-08-16` (321.01 lbs) — 4 days stale. This
   also unblocks #2797's folded `segmental-fields-unverified-live` check.
3. **One taste call, now a one-line edit:** #2757 makes coach colour a single registry value. Sleep is
   `#8b5cf6` and nutrition `#22c55e` (the roster-v2 palette). If you prefer the older `#818cf8` /
   `#10b981`, it is one line in `config/personas.json` — that reversibility is the point of the fix.
4. **Four `gate:owner` issues still need you:** #1738, #1571, #1677, plus #1631 (self-gated). #2833 and
   #2834 also carry `gate:owner` and are now `model:opus`, so they are startable *with* you.

## Next

- Land the four in-flight PRs, then deploy per ask #1.
- **#2912** (the flapping-alarm gap) is the freshest and cheapest — it has a planted-test method
  already proven in #2670.
- **#2734**'s remaining box: re-base or retire `budget-tier-sustained-7d` before band 1 becomes
  permanent noise.
- **#2761** — the wrap gate that has never fired, now startable.
- **#2692** — `pytest --durations=25` **on CI**, not locally; the 3.4x local/CI gap is still unexplained.
