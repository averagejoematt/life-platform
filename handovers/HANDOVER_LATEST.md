# Handover — 2026-08-27 (Opus 5, Session G): five closed, net −4, and the cost epic I was sent to retire and did not

**Session:** Opus 5. Drove: *"Boot Session G of the self-sustaining push… THE SPINE IS EPIC #2801 (Cost)…
Honest target: 4–7 closures, net −3 to −6, PLUS epic #2801"*
(`~/.claude/plans/session-g-cost-cliff-and-class-fixes.md`). AUTONOMOUS with merge+deploy authority.
ALL-OPUS — driver and all seven implementation lanes. Fable untouched, so #3042 and #2849 were out of
scope by definition. Previous handover archived as
`HANDOVER_2026-08-27_session-f-green-instruments.md` on `session-archive`.

## The score

- **5 issues CLOSED with verdicts**: #3139, #3204, #2888, **#2798 (an EPIC)**, #3079.
- **8 PRs merged**: #3240, #3238, #3239, #3244, #3246, #3243, #3242, #3241.
- **ZERO standalone issues filed.** Findings folded as epic checkboxes per CONVENTIONS §10 — #2798 ×1,
  #2799 ×5, #2578 ×2 (both **closed**), #2801 ×1 (a keep-open verdict). One issue, **#3237**, was
  auto-filed by #3213's own watcher, not by me.
- **Open count 47 → 43. Net −4**, counting #3237 honestly against me. Inside the 4–7 / −3 to −6 target.
- **Three deploys, verified by content, not by sha**: `life-platform-site-api`, `site-stats-refresh` and
  `dashboard-refresh` at `e06d88dc` — each bundle unzipped and grepped: `health/sensor_absence.py`
  present at **8,759 bytes** with its caller wired in all three. Plus the CI/CD fleet deploy at
  `6a6ef3a1f`, approved rather than left stranded.

## The headline: I did not close epic #2801, and that is the session's most important result

Both of #2801's open children closed today (#2888, #3139), making **every child closed and every
`Done when` box owned by a closed story.** I verified the boxes rather than reading their owners'
states — the AWS Budgets backstop really is re-pointed to **$150** (live `describe-budgets`), the EMF
namespace ledger really exists (`tests/test_emf_namespace_ledger_2837.py`, 57 passed), #2986 really
closed the re-stamping class. **Judged by child count this was a closure.**

Then I priced the cliff, and the Outcome does not hold. Live from SSM `/life-platform/budget-breakdown`
at `2026-08-27T16:00:11Z`: MTD **$162.47**, projected **$175.18** (all-classes $189.05), ceiling $200,
tier 2. AI spend by caller class, the #2892 dimension:

```
ci            $6.78/day   64.5%     <-- CI is 1.92x production
prod-cron     $3.53/day   33.6%
dev-session   $0.20/day    1.9%
```

On **2026-09-01** the ADR-133 window auto-reverts $200 → **$150** with no deploy. Bands are fixed
fractions, so the thresholds become $109.50 / $130.50 / **$145.50**:

```
$175.18/mo -> 116.8% of $150 => TIER 3   (Sept matches Aug projection)
$189.05/mo -> 126.0% of $150 => TIER 3   (all-classes)
$183.90/mo -> 122.6% of $150 => TIER 3   (current run-rate x30)
$145.26/mo ->  96.8% of $150 => TIER 2   (ALL CI and dev AI removed — clears by 24 cents)
```

**Every realistic September scenario lands at tier 3** — the hard cutoff, where website AI pauses, the
daily brief skips AI, `bedrock_client.invoke()` raises, and both AI CI gates go dark. This epic exists
to stop the tier system describing the designed steady state; closing it while that is about to happen
would be the phantom its own Problem statement warns about. **KEEP OPEN**, posted with the arithmetic.

Uncertainty stated rather than skipped: the $6.78/day CI term is **session-driven, not structural**
(n=4 complete days, the dimension has only existed since 08-24, window overlaps three heavy sessions).
If September runs far fewer sessions the cliff softens; at August's pace tier 3 is arithmetic. I cannot
forecast the owner's session cadence, so both bounds are given rather than one number.

## The through-line: F found instruments that report success without doing their job. G found the next layer — instruments whose stated *reason* is false while their conclusion is right

1. **The D-01 caching note** (PR #3246). It told the next reader that cross-region inference makes a
   once/day brief "never get a cache HIT" and to re-enable only after "re-measuring CacheRead>0."
   Measured on the same function, same profile: cache reads **38,872** and **22,068** against writes of
   26,933/27,097 — reads exceed writes. **The mechanism is false and the re-entry condition is already
   satisfied**, so anyone diligent enough to obey the instruction would ship a no-op plus a write
   premium. The conclusion is still right, for a reason the note never gave: the block is ~784 tokens
   against Sonnet's 1,024 floor.
2. **The deploy-wedge cron declares a safety property it has never delivered** (posted to #3237).
   Measured every consecutive scheduled gap, **n = 99**: the declared `*/15` was delivered **0 times**,
   and the 17-minute blind window its own comment claims to bound held **1 of 99 (1.0%)**. Median 43
   min, p90 71 min, max 6.99h — and by session end the gap was **10 hours**.
3. **A site auto-rollback that cannot fix the class of failure that triggers it** (folded → #2799).
   Detailed below.
4. **My own vacuous control**, again — the exact rule I put in all seven lane briefs. Probing whether
   the #2811 fleet matcher was blind, my first control used a shape that is itself blind, got `[]`, and
   for a moment I read it as "the surface is clean." A six-shape probe replaced it. **4 of 6 fire; 2 do
   not.**

## The rollback that reverted a good build, reported success, and left the defect live

Site deploy `33079187092` on Session F's wrap commit, this morning at 07:12 PT. Deploy succeeded — the
commit touched exactly **one** file under `site/`: `site/story/build/beats.json`, +31 lines, **F's own
published build beat**. Visual+AI QA then failed on one reproduced high: `/coaching/by-coach/` had
Dr. Max Reyes saying *"Day 10 as of today"* on Day 11. Auto-rollback fired, reported success, and
reverted `site/`.

The narrative is served from **DynamoDB** via `/api/coach_analysis`. The rollback reverts **`site/`
objects in S3**. Disjoint. I re-pulled the endpoint after it completed: still `regeneration_paused:
True`, still `generated_at 2026-08-26T17:02:28Z`, still Day 10. So in one run it **could not** fix its
trigger, **deleted a wanted unrelated change**, **reported `success`**, and left the defect live.

Lane 6 made the finding stronger than I had it: the rollback is **asymmetric with the deploy** —
`deploy-site` also runs `config_twin_sync.py --apply --strict` against bucket-root `config/`, which the
site-api reads at runtime, and the rollback covers `site/` only, so **a bad `config/` twin survives a
"successful" rollback**. It also re-stamps `/version.json` backwards. And it caught a stale line:
`CLAUDE.md:124`'s "rollback's `needs` excludes it" describes `ci-cd.yml`, not `site-deploy.yml`, which
gained the `visual-qa` dependency when #750 moved it.

Root cause of the trigger: ADR-125 tier 2 pauses regeneration, and the frozen text carries an
**absolute day number** plus "as of today", so it goes stale by one more day every day. Fixed in #3243
by datelining the read in the frame its own prose uses — not by weakening the pause, not by
regenerating. F's build beat is confirmed back on the live site.

## Four lanes falsified the premise of the work they were sent to do

- **#2888** — the top row of its own ranking is not a feature. `unknown` is **46% / $33.19 per 30d**,
  larger than daily-brief and the whole coach pipeline combined, and it is **CI**. Its dominant token
  class is screenshot **image** input — uncacheable in principle, no stable prefix at any size. Closed
  on a falsified premise after the lane went looking for one last trim lever (the daily-brief shared
  block) and **measured it into the ground**: 784 tokens under a 1,024 floor, ~$0.8–1.1/mo even if it
  cleared. The lane had told me to keep the issue open; it tested its own claim and reversed itself.
- **#3139** — the caching inversion does not exist. `I > 14.29·O`; 10 of 12 features fail *impossibly*.
- **#2835** — the issue over-counts itself. `pip-audit` is first-Monday-guarded, so it is **six** emails
  on ~3 Mondays in 4 and the fold saves **two**, not three; the "or fold into ai-review-pack's Sunday
  send" option is **13.5h out of phase**; "zero alarm/infra changes" is unachievable alongside its own
  acceptance. Lane 5 refused to half-ship it and posted a working design instead.
- **#3079** — "the two `_image_block` implementations" are **three**.

## Incidents & gotchas

- **Main was NOT green at boot**, and F's handover said it was. Two Session-F residuals: `CLAUDE.md`'s
  wrap prose tripped `check_doc_facts` (its "12 tests" read as the suite count, truth 17,664), and the
  INCIDENT_LOG Patterns block was **stale** while F's gate line claimed it was regenerated. All **10**
  full-suite failures were that one root cause. Fixed at `25205ce5`.
- **I then hit #1908's trap myself** — the docs-only fix could not re-run CI/CD, because `docs/**` is
  not in its `paths:` filter, so the stale red persisted until I diagnosed it by hand. Hours later
  Lane 4's first attempt at Item B **reintroduced that exact trap**, and #1908's own guard caught it.
- **Two deploy leases rejected with decodes.** The first was 6 commits behind and would have shipped a
  tree without #3239; the second was at `69a35909`, **older than my manual deploys**, so approving it
  would have regressed live Lambdas. The third, at current main, was **approved** rather than stranded.
- **A concurrent session is working in the primary clone.** It appeared mid-session as an unpushed
  local commit and grew to **5 commits** (now PR #3245, the skills-corpus migration). I moved all
  driver git work into an isolated worktree at `origin/main` and touched none of it.
- **I fabricated a sha and then read my own bad input as a finding.** Swallow-checking a merge I typed
  a 40-character sha rather than reading one, got zero rows, and briefly concluded the push was
  swallowed. It was not. Corrected within the minute; recorded because it is the same class as the
  vacuous control.
- **The census is a serialization point and it bit a lane I had not warned.** I briefed Lanes 4 and 7
  about `BASELINE_TOTAL_GATES`; Lane 5's **QA** fix also added a gate, which I had not anticipated. The
  general rule, which Lane 5 articulated: **registering a file in `_PREMERGE_EXTRA_FILES` tends to move
  the census, so every lane that adds a repo-shape guard is a census-baseline lane whether it knows it
  or not.** Related trap Lane 4 flagged and Lane 5 then checked explicitly: `_tracked_files` derives
  from git, so a **present-but-untracked** new guard reads as absent — measure staged or set a ceiling
  that reds the commit introducing the file.
- **Closing #3204 orphaned an alarm citation**, and the wrap's own (e10) gate caught it the same
  session — `qa-smoke-failures` cited an issue that had closed hours earlier.

## Gate lines

**Build beat:** 2026-08-27-the-sensor-that-ended
**Docs:** `docs/alarm_citations.json` (qa-smoke-failures re-cited; the glucose leg resolved and the
weight leg restated) · `docs/DECISIONS.md` (ADR-049 amendment 2026-08-27, via #3238) ·
`lambdas/ai/ai_calls.py`'s D-01 note corrected (via #3246) · `deploy/sync_doc_metadata.py --apply`
**Decisions:** none needed — ADR-049's amendment was filed inside #3238 by its own lane; the two
governance-shaped calls this session (keep #2801 open against a completed box set; close #2888 on a
falsified premise) are recorded as verdicts on the issues themselves, where the evidence lives
**Main:** green (`6a6ef3a1`) — but it was **RED at boot while Session F's handover declared it green**, and
the stale red was unclearable by its own fix: all 10 full-suite failures traced to one wrap-prose line, and
because `docs/**` sits outside ci-cd's `paths:` filter the docs-only remedy at `25205ce5` could not re-run
CI/CD (**#1908's trap, live**). Cleared when `6a6ef3a1f` completed success during this wrap; all three
production leases actioned — two rejected as stale (the second *older* than code already deployed), one
approved, and a fourth at `3eff37e6` approved at 0.4h rather than left to strand
**Incidents:** 4 rows added — the site auto-rollback that reverted F's build beat for a DynamoDB-sourced
defect it could not fix · main red at boot on two Session-F doc residuals, invisible to re-run by the
#1908 trap · two production deploy leases rejected as stale, one of which would have regressed live
Lambdas · the deploy-wedge cron undelivered for 10h against a declared 15-minute cadence
**Stash/hooks:** clean — `git stash list` empty
**Closures:** #3139, #3204, #2888, #2798, #3079 — all five commented with contract-shape
Shipped/Outcome verdicts; **#3204 recorded `partial`** because its operator/alerting leg was
deliberately cut on my instruction and folded to #2799 rather than left implied
**Backlog:** `Now` refilled to 4 actionable — promoted **#2999** (0.60) and **#2848** (0.50) from
`Later` by stored rank, score lines corrected to `→ Now` in the same edit. `Next` held only #2849
(Fable, out of scope by the brief), so refilling from `Next` would have meant queueing work this
session type cannot do. **#3237 carried no milestone and was invisible to every ranked query** — set to
`Later`. Later sweep: no stale issues
**Alarms:** 1 lit >72h, cited — `qa-smoke-failures`, re-pointed at #3083 (open, `gate:owner`) after its
glucose leg resolved; no uncited fired-and-cleared flaps in the window
**CI warnings:** none to triage — `check_ci_warnings` reads the latest **green** completed run and
there was not one at wrap time (the queue was still draining behind the approved lease)
**Ledger:** omitted — the one new standing artifact (`deploy/verify_doc_facts_derivable.py`) landed
with its rent priced inside the work: a bounded probe that reads no doc and compares no literal, a
recorded ruling that it must **not** gate structural `None` fallbacks (with a test pinning that
choice), and a `+2` census adjudication in-file. A `PROPORTIONALITY.md` row would restate that
verbatim; deferring deliberately to the #2999 sweep that will re-price the census rows anyway

## Owner batch (18 items)

1. **THE SEPTEMBER 1 CLIFF — now priced, and it is the top item.** The ceiling auto-reverts $200 → $150
   in five days and every realistic run-rate lands at **tier 3**. Three options on #2801: raise the base
   to ~$190–200 (and re-point the backstop with it), cut AI CI cadence, or accept tier 3 and re-band
   honestly. **Doing nothing selects option 3 by default, with no deploy and no announcement.**
2. **The AI-CI cadence decision** (#2888's residue) — the only lever that moves the number, worth up to
   ~$6.78/day. It now has a price *and* a measured counter-argument: the `visual_ai_qa` gate caught a
   live reader-facing defect **this morning** that nothing else was looking for.
3. RECONCILE_PUSH_TOKEN PAT (D0.6) · 4. DEPLOY_GATE_JANITOR_TOKEN (#3021) — **two leases needed manual
   disposal again today** · 5. respiratory_rate/disturbance_count consent (#3045) · 6. #2834 IAM posture
7. **#3083 — still the standing `gate:owner` policy call**, and now the sole citation holding the
   `qa-smoke-failures` alarm; its evidence is cleaner than ever · 8. DIL-027 restore-drill appointment
9. S3 Batch Replication backfill click (~$0.49) · 10. **#3042 re-grade** (Fable) · 11. Whoop re-auth if
   pending · 12. #2883 box-4 call · 13. `aws cloudwatch delete-alarms --region us-east-1 --alarm-names
   life-platform-cf-auth-errors` · 14. the freshness-checker's `dynamodb:PutItem` AccessDenied on its
   notion alert-state write · 15. **`deploy-wedge-watch.yml` — now measured, n=99: the declared `*/15`
   has been delivered 0 times and its stated 17-minute safety property held 1%.** Decide: make the
   declaration honest, or move detection to an event-driven trigger that actually bounds the window.
16. **NEW — `CLAUDE.md:124` is provably stale**: "rollback's `needs` excludes it" describes `ci-cd.yml`,
   not `site-deploy.yml`, which gained the `visual-qa` dependency at #750. Left untouched under
   status-block discipline. 17. **NEW — a concurrent session holds PR #3245** (skills-corpus migration);
   it was unpushed local work in the shared clone for part of today. 18. **NEW — the site rollback's
   scope**: folded to #2799, but the `config/` asymmetry is arguably worse than the DynamoDB case
   because `config/` **is** repo-versioned and **was** shipped by that very workflow.

## Residuals / next picks

- **#2801** (P2 epic, Cost) — every child closed, Outcome unmet, five days to the cliff. **Start here.**
- **#2883** (#2883, P2, budget self-metric drift 2.44× → 1.37× against a <1.15 bar, nothing alarms on
  it) — the last untouched P2 on `Now`; pairs with #2801 because you cannot price a cut on attribution
  you do not trust.
- **#2978** (P2 UMBRELLA, deploy-race false positives) and **#2835** (chore; Lane 5 posted a concrete
  design and a corrected sizing at `issues/2835#issuecomment-5441892781`) — both on `Now`, unstarted.
- **#2999** (P2, gates slice 2 — the verdict fraction) and **#2848** (P3) — promoted to `Now` this wrap
  by stored rank. #2999 is the natural successor to this session's census work.
- **#2799**'s five new checkboxes — rollback-scope-must-match-failure-class, rollback-success-is-
  unasserted, sub-datatype liveness never emitted, series helpers dropping absent days, and the AI
  context map having no glucose entry.
- **#3237** — auto-filed advisory tracker for the cron-freshness red; auto-closes on the next green run
  of that workflow, which requires GitHub to actually deliver a scheduled `deploy-wedge-watch` run.
- **not-work — the two remaining `#2578` residuals are named in-file**: a discoverer returning `None`
  for a *structural* reason still falls back silently to `PLATFORM_FACTS` (deliberately not gated, with
  a test pinning that choice, because gating `_count_adrs` would rebuild the #1908 trap by hand), and
  the structural-test family still cannot see `test_pair_seam_conformance_2847.py`.
- **not-work — `#3202`'s last acceptance box stays unproven.** Budget tier was 2 all session, which
  pauses `coach_narrative`; the only effective override window is 16:00–17:00Z. Unchanged from F.
- **not-work — ~93 stale git worktrees.** The concurrent session appears to be building a reaper for
  exactly this; leave it to them.
- **Dated observations:** **2026-08-31 (Mon)** — #3178's sentinel cadence proof and #3191's TTL-parity
  sweep · **~08-29** — `ai-tokens-platform-daily-total` and `prediction-gradable-share-low` cross 72h ·
  **2026-09-01** — the ceiling revert · **~09-24** — #2978's 30-day re-measure · **2026-10-15** — WAF
  revisit · **2026-09-22** — legacy unsubscribe sunset.
