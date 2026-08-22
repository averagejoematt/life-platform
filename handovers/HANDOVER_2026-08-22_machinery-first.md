# Handover — 2026-08-22 ~11:45 → ~16:45 PT: machinery first — the class #2753 vacated now has an owner, and the publish path took two rounds because the oracle moved under it

**Session:** Opus 5, autonomous, full merge + deploy authority. The driving instruction was
*"machinery first, then opus paydown"*, against the approved plan
`~/.claude/plans/golden-forging-hickey.md`, whose premise was measured rather than felt: of
120 post-July incident rows, **98 (82%) are self-inflicted delivery-machinery failures**,
and the largest class inside that had no owning epic since #2753 closed. Previous wrap
archived as `HANDOVER_2026-08-22_plan-then-execute.md`.

**Build beat:** none — nothing reader-visible shipped. Six merges: a QA ledger fix, a doc
generator's writer, a CI trigger change, a test-side registry, an alarm citation, and two
baselined oracle findings. `docs/content/BUILD_DISPATCH_CHECKLIST.md` wants reader-facing
work, and the one reader-facing thing touched (#2972) is still open by design.

**Docs:** `docs/INCIDENT_LOG.md` (+2 rows, Patterns section regenerated 155→157 — by the
writer this session shipped, not by hand), `docs/CONVENTIONS.md` §4a1 (what a test-adding
branch owes: nothing), `docs/PROPORTIONALITY.md` (derived-artifact registry row),
`docs/MCP_TOOL_CATALOG.md` (regenerated — it was a month stale), `docs/alarm_citations.json`
(the #2734 entry rewritten; it had rotted).

**Decisions:** none needed — #2982's option-A choice is recorded in CONVENTIONS §4a1 and on
the issue; #2986's registry is an implementation of ADR-103/144 and the charter, not a new
governance rule.

**Incidents:** 2 rows — post-deploy visual-QA red on two NEW reader-truth findings the
deploy did not cause (`/method/board/` was among the 91 passes); and a ~5 min Docs CI red
from a `test_count` stamp dropped during a rebase, healed unattended by the reconcile bot.

**Main:** green at `5f5069f6` — the latest completed CI/CD run succeeded. The gate still
exits 1, and its objection is fair rather than wrong: HEAD is the docs-only wrap commit
`f2628761`, which is outside `ci-cd.yml`'s path filter and so mints no CI/CD run **by
design** — not the swallowed-push shape (#2762) the gate flags it as, but genuinely
unwatched all the same. Docs CI is green on it. The earlier red (`32594947913` on
`564efa0c`) was its **visual-QA leg only** — Deploy, smoke and the I1/I2/I5 checks all
SUCCESS, auto-rollback SKIPPED — and both its findings are baselined in `#2990`.

**Alarms:** clean — every alarm red >72h cites an issue, no uncited flaps in the window.
The `budget-tier-sustained-7d` citation was rewritten (it stated a ceiling that no longer
exists).

**CI warnings:** 3, all triaged — two `Plan deployments` warnings claiming a "Lambda config
change (handler/runtime/memory/timeout/env/layer) CI cannot ship" on `LifePlatformOperational`
and `LifePlatformEmail`; I ran the diff they describe and **only `Code.S3Key` moved, on 7
functions** — an asset-hash change CI's code-deploy path does ship. Filed as **#2993**. The
third is the Unit Tests duration budget (1329s vs 1200s), the fifth crossing of a trend
`157 → 294 → 688 → 830 → 1247 → 1329`; recorded on the issue that already owns it (**#2692**)
rather than re-filed, noting this session added 63 tests to the suite.

**Stash/hooks:** clean — `git stash list` empty, hook freshness 🟢.

**Backlog:** Now live at 12 actionable; no stale `Later`. Fixed two hygiene violations —
epic #2799's `## Stories` missing #2989 and #2992, and the platform's own auto-filer
(#2991, the standalone visual-QA advisory) which is the same condition #2992 diagnoses in
full; closed to it.

**Closures:** #2981, #2975, #2982 and #2991 each carry the ADR-099 two-line verdict.

**Ledger:** omitted — from the wrap commit only. The derived-artifact registry row shipped
**with its subsystem** in `#2987` (`564efa0c9`), which is the better place for it, so
`docs/PROPORTIONALITY.md` has no diff in the wrap window. The row is live and carries
posture, rent (one build-time AST scan + `git ls-files`, one classification line per new
generator), and a demote trigger of a full quarter with no registry change.

---

## What shipped

| PR | what | state |
|---|---|---|
| **#2984** | #2975 — the incident-log derivation gets a writer, and its guard moves to the lane that stales it | merged `3997b0f10` |
| **#2985** | #2982 — a test-adding PR stops paying a round-trip to a literal it may not stamp | merged `97ae3aed9` |
| **#2983** | #2981 — the truth ledger records a pair at any severity, and the update path stops lying | merged `9d7a99e03` |
| **#2987** | #2986 — a registry for derived artifacts and the lanes their guards run in | merged `564efa0c9` |
| **#2988** | #2734 — re-measure the budget alarm; the projection half is resolved | merged `985dc935e` |
| **#2990** | #2959 — baseline the two `/story/` oracle findings holding the publish path | merged `5f5069f63` |

**Closed:** #2981, #2975, #2982, #2991. **Filed:** epic **#2986** (derived artifacts and
their lanes), **#2989** (the budget alarm's cut), **#2992** (the finding still holding the
publish path) and **#2993** (the Plan job's asset-hash-vs-config-change misread).
**Open: 78 → 79** — four closed, four filed, plus one the platform's own auto-filer opened
mid-session and I closed to #2992. The count went up; every issue filed names something
that was already broken and unmeasured.

**Deployed + verified:** `life-platform-site-api` 20:06:53Z and `life-platform-mcp`
20:09:49Z against a 19:51:19Z merge — both post-date it. Verified by **reading the deployed
artifact**, not the deploy status: live `/api/platform_stats` returns `test_count: 16136`,
matching `lambdas/web/site_api_common.py:220` exactly.

## The critical path, and where it actually ended

The plan's forced ordering was `#2981 → baseline #2972 → publish path unblocked`. The first
two links held exactly as designed. The third did not, and the reason is worth carrying.

`#2981` was real and cheap: the ledger's write path recorded only `high` findings while the
oracle grades the same finding non-deterministically, so a deliberate baselining pass on a
`med`-graded night recorded **nothing and printed "rewritten" anyway**. Fixed by making the
write path severity-free — the gate key already was (#2613) — with gating unchanged at read
time. `/method/board/`'s `audience_violation` baselined, ledger 26 → 27, and the re-run
reported `2 passed, 0 failed`.

Then the **full-surface** post-deploy sweep came back `91 passed, 2 failed across 93 pages`
— and `/method/board/` was among the **passes**. Two entirely different pages had picked up
high findings in the meantime. That is the oracle's non-stationary population doing exactly
what #2981's own issue body predicted, one level up: fixing the baselining mechanism does
not stop the target from moving while you aim at it.

Both new findings checked against the **live pages**, not the CI log line — which truncates
the note at ~96 chars and has produced a confident wrong root cause here before. Neither is
a defect: `/story/chronicle/` lists a 2026-08-18 post titled *Day One Actually Happened*,
which is ordinary Day-2 retrospective publishing, and `/story/build/agent-review/` states
its own span (`2026-05-29 → 2026-08-17`) and never claims to be current. Baselined under
#2959, 27 → 29.

And then it moved **again**. The local full-surface sweep after those merges returned
`92 passed, 1 failed` with a single high finding on `/method/` that the CI sweep 90 minutes
earlier had not seen — a third distinct high-finding population in one day. **The publish
path is therefore still held**, by #2992, and this time the finding may be a real render
defect rather than a sanctioned shape, so it is filed rather than baselined.

I nearly missed it. My first read of the sweep grepped a `tail -30` capture, found no 🔴,
and I wrote *zero high findings* — the exact truncation trap this repo already has a rule
for. `qa-screenshots/report.json` is the complete artifact and says `FAIL count: 1`. The
correction came from reading the whole record instead of the tail of it.

## The flagship: three broken triples, and one stale behind a fresh timestamp

Epic #2986 exists because a derived artifact needs four things — a generator, a writer that
can self-heal it, a guard, and that guard **placed in a lane the artifact's inputs trigger**
— and nothing declared which of the four each one had. Discovery finds 28 scripts writing a
git-tracked artifact.

The one worth reading twice is `docs/MCP_TOOL_CATALOG.md`. It was not merely stale — it was
**stale behind a fresh timestamp**. The reconcile bot touched the file *daily*, because
`sync_doc_metadata` owns its `Total tools:` literal; the generated body had not been re-run
since **2026-07-25**. The doc contradicted itself two lines apart:

```
**Version:** v8.6.0 | **Last updated:** 2026-08-22 | **Total tools:** 76
## All 72 Tools — by module
```

That is #2840's defect with a bot stamping it fresh every day, and no guard anywhere: its
`--check` was wired into no workflow step, no pytest, and no `run_generators()`. Both gaps
the registry found — this one and `generate_platform_model`'s post-merge-only guard — were
closed in the same change.

## Things that were not what they looked like

- **`GenerationSkippedUnchanged` has never been emitted** — zero metric *variants* in
  CloudWatch, not zero datapoints. The DDB cache writes fine (8 rows, all 8 coaches) but
  `reuse_count == 0` and `first_generated == last_generated` on every one: not a single hit
  since ADR-126 landed. Root cause: `canonicalize()` strips volatile *dict keys*, and the
  only call site passes two **rendered strings**, where a key-based strip cannot reach the
  embedded date. The whole `_VOLATILE_KEYS` list is inert in production. Recorded on #2889
  with the executed proof; not fixed, because normalizing volatile spans out of prose is
  the exact fragile path the module's own docstring warns against.
- **The guard meant to keep docs-ci's two path lists identical was comparing six-element
  prefixes.** Its regex terminated each block at the first entry carrying a trailing
  comment — the 7th of 15 — so it would have stayed green through #2982's change either
  way. Found only because I was deliberately making the tails diverge.
- **The `#2734` alarm citation had rotted.** It cited a `$135` ceiling reverting to
  `$85/$100`; #2836 superseded both on 08-18. A citation whose whole job is to explain a
  lit alarm, stating a ceiling that no longer exists, is worse than none.
- **#2734's trilemma had no live premise.** Measured by executing the shipped `_tier_for`:
  projected `$162.60` vs the `$200` August ceiling (81%), and `$121.50` vs the `$150`
  September base (81%). Neither month overruns. What remains is the alarm's *cut*, and it
  is derived rather than taste: **ADR-133 set the $150 base *from* a measured steady state
  of $4.12/day, which lands at 82.4% of it — inside band 1 by construction.** Filed as
  #2989 rather than re-cut as a tail-end edit to a paging surface.

## Two things I got wrong, and how

- **`git checkout tests/visual_qa.py` to clean up a mutation probe destroyed the fix I had
  just written there.** The edit was unstaged; checkout restored it from HEAD. Caught
  immediately by re-grepping, but the reflex is the lesson: never use `git checkout <path>`
  to revert a probe in a file you are also editing — copy to `/tmp` and copy back.
- **Discovery's first cut was useless in both directions.** A substring check for `open(`
  turned 9 real generators into **59** candidates, most of them `check_*.py` scripts that
  only READ a `site/` path. Tightening it to AST-resolved write targets then missed
  `deploy/sync_doc_metadata.py` — the largest generator in the repo — because it writes
  through a loop. The shipped version is strict on *whether a module writes* and wide on
  *which artifacts to attribute*, and it names its remaining blind spot (`DISCOVERY_BLIND`,
  5 generators writing through computed paths) rather than hiding it.

## Residual / next picks

- **#2992 — the publish path is NOT clear, and this is the one thing holding it.** I
  expected run `32597212151` to confirm it; it could not — its Deploy was **skipped** (the
  #2990 merge touched only `tests/truth_baseline.json`, nothing deployable), so visual-QA
  skipped with it. So I ran the full surface locally instead: `92 passed, 1 failed across
  93 pages`, and the single high finding is a NEW one on `/method/` that was absent from
  the CI sweep 90 minutes earlier. The API is right in every particular
  (`current_cycle = 14`, cycle 14 `is_current: True`), so it is either a wrong-row `· NOW`
  binding or an oracle misread — **do not baseline it until that is settled.**
- **#2889** — the generation cache has never hit once; root cause measured and posted. The
  fix is fingerprinting the structured brief before rendering, where `canonicalize` already
  works as designed. Do NOT start box 2 (extend to other surfaces) first — extending a gate
  that has never fired multiplies zero.
- **#2989** — the budget alarm's cut; three costed options on the issue, needs a monitoring
  CDK deploy and a rewrite of three hard assertions in `tests/test_budget_tier_alarms.py`.
- **#2986** — the registry's own folded findings: `test_platform_model_drift.py` is outside
  the `premerge` marker, and the 11 `v4_build_*` BUILDERs are classified but unaudited.
  Also worth noting: `/story/build/agent-review/`'s oracle finding lands on a BUILDER whose
  output ages with nobody responsible — the class the registry documented, showing up the
  same day.
- **#2974** — the visual-qa CI role still cannot `PutMetricData`; the failure log is wall-to-wall
  `AccessDenied` on every Bedrock call, confirming the bill-without-record class live.
- **#2972** — unchanged and still correctly open: no producer anywhere writes reader-facing
  coach prose, so it is new generation work. Now baselined as debt, which is the point.
- **#2893**, **#2832** — the remaining ranked opus paydown, untouched this session.
- **`training_coach`'s cache row last stored 2026-08-09**, 13 days behind its seven
  siblings. Flagged on #2889, *not diagnosed* — two partition-key guesses returned 0 rows,
  which measures nothing, so I recorded the observation rather than a conclusion.
  — *not-work — an observation attached to #2889, not a separate claim*
