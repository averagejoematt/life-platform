# Handover — 2026-08-27/28 (Opus 5): Session I — the cliff was real, its date was wrong by twenty days

**Session:** Opus 5, AUTONOMOUS with merge+deploy authority, ALL-OPUS. Drove
`~/.claude/plans/twinkling-noodling-treehouse.md`, then two owner-directed extensions: a rituals
run and a bug-bash sweep. Twelve agent lanes. Previous handover archived on `session-archive`.

**The second session holding `skills-corpus-governable-phase1` had ENDED** — established by evidence,
not assumption (zero files touched in the primary clone in 6h, no Claude Code process on the repo,
clean tree, PR gone `CONFLICTING` with nobody rebasing). Session H's never-touch order was
discharged and #3245 was picked up and landed.

## The score

- **19 PRs merged**: #3267 #3268 #3269 #3270 #3271 #3272 #3273 #3274 #3245 #3276 #3280 #3275
  — then, post-wrap under a second owner grant: #3290 #3291 #3292 plus four driver commits.
- **10 issues CLOSED with verdicts**: #3264, #3255, #3258, #3260, #3261, #3257, #3282, #3285,
  #3286, #3287.
- **14 issues FILED**, every one adversarially verified or ground-truthed: #3277 #3278 #3279
  #3282 #3283 #3284 #3285 #3286 #3287 #3288 #3289 #3293 #3294. Plus 6 §10 folds
  (#2799 ×1, #2578 ×4, #1367 ×1).
- **Open 51 → 55. Net +4 — the correct outcome, stated rather than suppressed.**
  The drain phase took it 51 → 45; the owner then asked mid-session for a bug bash, and the sweep
  found eleven real defects that survived adversarial verification. Suppressing verified
  reader-facing defects to protect a net-open metric is the disease this repo documents.
- **Three issues deliberately NOT closed** despite their PRs merging — #3252, #3250, #2801 each
  got a box-by-box verdict and `Fixes` was downgraded to `Refs` on two PRs. A merge is not a closure.
- **Seven deploys, every one verified by CONTENT.** **Twelve deploy leases disposed** — nine
  approved after a content decode, three **rejected**.

## The through-line: the stated mechanism and the actual mechanism had diverged

Session F found instruments reporting success without doing their job. H found written claims
measurement contradicts. I found the layer under both: **things that ARE working, but not by the
mechanism their own documentation names** — so the explanation anyone would act on is wrong even
while the number looks fine.

1. **The cliff's date.** "Doing nothing selects tier 3 on 09-01" — in the #2801 epic, in Session H's
   owner batch, and in this session's own plan — is **false**, structurally. It priced September
   against August's *month-end projection* ($176.34), a terminal value for a 90%-elapsed month.
   `_project_month_end` is month-scoped; `_decide_tier` caps at `actual_mtd_tier + 1`. Simulated
   through the real function, $150 reaches **tier 1 Sep 8 · tier 2 Sep 18 · tier 3 Sep 21**. The
   cliff is real; its date was wrong by twenty days.
2. **`prediction-gradable-share-low` clears by dilution, not retirement.** Its CDK comment credits
   `_retire_ungradeable`; measured, `GradableShare` rises 0.3951 → 0.4556 over four days while
   `UngradeablePendingCount` is **flat at 49 every day**.
3. **`ai-tokens-platform-daily-total` cited a window that had already expired** while the alarm
   stayed lit — a genuine sustained breach (195,560 / 167,974 against a 150,000 threshold).
4. **Five reader-truth rulings asserted an outcome the pipeline could not deliver** — all five say
   "visible as advisory, never gating" and all five express it as `severity = low`, which gates.
5. **Two `KNOWN_SECRETS` registries had drifted for months by exactly four ids**, invisible because
   the gate that would have reported it could not see the references.
6. **`main` has no branch protection and zero required checks** (#3288). `CONVENTIONS.md` describes
   a merge gate that does not exist; the honest record two files away is machine-pinned, the false
   one is not. Eleven PRs merged tonight gated **solely** by `wait_pr_green.sh` and an unpiped exit
   code. The discipline held — but it was the only belt, not a second one.
7. **The gating render sweep runs axe only at the desktop viewport** (#3277). The finder called the
   a11y defects WebKit-specific; the verifier ran both engines at both viewports and got
   byte-identical results. 100% viewport-driven, 0% engine-driven — and in 6 runs the WebKit
   workflow has found **zero** genuinely engine-specific bugs, a live ADR-103 datum.
8. **The chronicle's canonical permalink 301s to the wrong hub** (#3284). A one-way ratchet:
   `register_permalink_redirect()` only appends, while `untombstone_and_redate()` resurrects the
   record without un-registering. **And the existing gate asserts the blackhole is correct** —
   `tests/test_redirect_spotcheck.py` checks the 301 returns its declared Location.

## Lane 1 — the September ceiling, re-derived rather than raised

`$150/$176` → **`$215/$252`**, permanent, not a fourth dated window.

**Measured steady state, explicitly not a projection:** Cost Explorer unblended **$5.74/day, sd
$4.32, n=25** (08-01..08-25) → ~$172/mo, 95% CI $121–223. 08-26/27 excluded as **incomplete, not
outliers** — CE's Bedrock line lags 24–48h, and treating a lagging partial as a low day is the error
that produced the $4.12/day figure behind $150. Month actuals **May $48.19 · Jun $79.80 ·
Jul $98.35 · Aug ~$165** — roughly +$30/month, four months running.

**$215 chosen by executing `_decide_tier`** over a simulated September at three burn rates: the
lowest base that **never reaches tier 2 in any scenario** while still engaging the tier-1 ladder in
two — ADR-133's accepted posture without making tier 0 the cosmetic norm that same ADR rejects. The
plan's $205 hits tier 2 on Sep 28. All 15 published table rows were re-verified against the real
functions before the ADR shipped. Positive control: the sim reproduces the live governor exactly
(176.35 vs 176.34; tier 2 vs 2).

**The invisible deploy step worked and was verified:** `cdk deploy LifePlatformCore` with **zero CDK
file changes** moved the AWS Budget `150.0 → 215.0`, because `BUDGET_AMOUNT_USD` resolves at *synth*
time by parsing the governor source.

**Tier after deploy is 2 — correct, and predicted before it was observed.** The August window holds
until 09-01. Writing the prediction down first mattered: "still tier 2 after a ceiling raise"
otherwise reads as a failed deploy.

## Rituals — both NEVER-RUN entries actually run

- **`craft-review` (#3280)** now reads OK on main. Graded **B overall** across 10 lenses, 23
  findings, magnitudes derived from `review_anchors.py`. Its verdict in one line: *a repo whose
  machinery is consistently stronger than its self-description.* It refuted one of its own lenses'
  claims rather than banking it. #3288 is its sharpest finding, filed.
- **`proportionality-reread` (#3275)** — 73 rows walked, ~60 verified unchanged, **11 corrected**,
  and **two demote triggers found already fired unnoticed** (fresh-eyes 2026-07-26; reader-truth
  2026-08-26). The privacy-tier row's rent was understated ~10x (31 fields/42 pairs vs "3 fields,
  4 pairs"). **Landed.** The calendar now reports `no ritual outside its window, and every ritual
  has run at least once` — the daily red #3273 armed is resolved by running the rituals, not by
  stamping them.

## Post-wrap: a second grant, and the finding that justified refusing a green

The owner approved three more things after the wrap: clear main, reap the worktrees, drain the
reader-facing queue. All three landed, and the third produced the session's sharpest result.

**Main's red was cleared the wrong way first, deliberately, and I said so.** I dispatched a CI/CD
run to prove the board artifact had regenerated. No code had changed, so `Plan deployments` found
nothing and the run **skipped Deploy, Smoke, post-deploy integration and the Visual QA** — then
concluded `success`. `check_main_green` flipped to ✅ on a run that never executed the job that made
main red. `latest_main_conclusion` reads the conclusion and inspects nothing about which jobs ran, so
**a red main is clearable in one command, with no code, no deploy and no QA.** I predicted the skip
before dispatching, refused to bank it, left the `Main:` decode in place, and folded it onto #2578.

**That refusal was load-bearing.** The next run that actually deployed ran the QA for real, and the
`/method/board/` HIGH **reproduced** — surviving #3102's confirm step, while a second finding in the
same run was correctly marked NON-REPRODUCED and ungated. The untruncated text asserts *"has not
logged any food, training, habits, or journal entries since"* the cycle start. Ground truth:

| asserted absent | source | records | |
|---|---|---|---|
| food | macrofactor | 0 | ✅ |
| **training** | **strava** | **2** | ❌ |
| **habits** | **habitify** | **12** | ❌ |
| journal | notion | 0 | ✅ |

**Two of four asserted absences are false, one by twelve records.** And the timing is what makes it
conclusive: #3276's absence-sourcing fix deployed at ~06:00Z; the board regenerated at **15:09Z**,
after it, and still produced this. So the check exists, is deployed, and **is not reaching that
surface** — a different defect from "the check does not exist", which is what #3252 box 2 was. Filed
as **#3294** on `Now`. Had the hollow green been accepted, this would have been recorded as cleared.

**A second near-miss: the worktree reaper would have deleted three live lanes.** Its first real use.
"Clean, and every commit already in `origin/main`" cannot distinguish *finished* from *started ninety
seconds ago* — dirtiness is a lagging signal of liveness and the tool has no leading one. It is a
**race**: reap ten minutes later and all three read dirty, so the tool looks safe. Filed as **#3289**
with `git worktree lock` as the fix. Reaped safely after the lanes finished: **13 of 14 removed**,
the one failure being the primary clone, which git refuses and which the loop reports and skips.

**The verification lesson.** Two adversarial passes confirmed the findings, corrected several numbers
and refuted three sub-claims — but both stayed scoped to *what the finders reported*. Lane L traced
the #3287 **shape** instead and found it in two more consumers: `/api/pulse` had its own `Limit=1`
over the same widened range, handing the **water** and weight reads the partial next-UTC-day record
for the same ~7h, under a comment claiming it fetched "the PT-date record specifically". **A verifier
that only re-derives the claim can confirm a true finding and leave most of its blast radius
unfound.**

## Incidents & gotchas

- **A lease would have shipped a tree without the ceiling.** `b4f849f4` was *strictly newer than
  live* — ancestry alone waves it through — but carried `MONTHLY_CEILING = "150"`, older than main
  on the one number the session existed to change. Rejected with the decode. **"Newer than live" is
  not "carries the change you are deploying for."**
- **The census told me 562 and it was lying, because of my own mistake.** A scripted merge
  resolution dropped a `#`, so `test_gate_census_lane_3000.py` stopped parsing;
  `discover_registry_gates` swallows `SyntaxError`, so the file silently contributed **zero** gates
  and the count went **down** — the reassuring direction. Caught only because 562 disagreed with
  arithmetic done first. Folded to #2578.
- **`wait_pr_green` correctly REFUSED to classify a drift red** on #3271 because a
  non-`platform_counts.py` file was in it. Exit 1, not 4. The classifier was right; I was one file short.
- **I hit the piped-exit-code trap myself** — `check_backlog_hygiene.py | tail` printed `EXIT=0`
  while the gate exits **1**. Third recorded instance, and it was in my own brief.
- **My own docstring edit contained a literal `"""` and broke the module.**
- **A broader regression than the PR's own selection caught a real red** —
  `test_status_cost_honesty` asserted `base_aug > base_sep`, an encoded "a dated window is always a
  raise" that inverts now that $215 > $200.
- **Two issue-filers ran concurrently and both edited epic bodies.** A clobber risk I should have
  staggered; verified afterwards that all five roster additions survived.
- **A subagent incidentally read two plaintext secrets** while verifying source provisioning and
  flagged it itself. Scope contained: only secret *names* are in tracked files; the values sit in a
  local temp transcript outside the repo, uncommitted. Rotation is an owner judgment call.
- **Zero event swallows.** Every push swallow-checked at ~90s at the full 40-char sha.

## Gate lines

**Build beat:** 2026-08-28-the-stated-mechanism — #3261's fabricated share-card numbers and #3257's
Pacific freshness frame are merged AND deployed, verified by unzipping the shipped bundles and
regenerating the cards (14/14).
**Docs:** `docs/DECISIONS.md` (ADR-133 amendment 2026-08-28; ADR-104 amendment for the absence
ruling) · `docs/OPERATING_DISCIPLINE.md` (new §5 production authority) · `docs/CONVENTIONS.md` ·
`docs/ONBOARDING.md` · `docs/COST_TRACKER.md` · `docs/OPERATOR_GUIDE.md` · `docs/ARCHITECTURE.md` ·
`docs/RUNBOOK.md` · `docs/PROPORTIONALITY.md` · `docs/OPERATING_CALENDAR.md` ·
`docs/alarm_citations.json` · `docs/reviews/craft_grades_2026-08-27.json` · `CLAUDE.md` · ~29
ceiling prose sites
**Decisions:** ADR-133 amendment (the September base) · ADR-104 amendment (auto-synced counts as
"logging", owner ruling 2026-08-28)
**Main:** red — and this time for a **proven, live, reader-facing defect**, not an unexplained one.
The gating Visual QA on the last deploying run (`93e08039`) reproduced the `/method/board/` HIGH,
surviving #3102's confirm step. Ground-truthed: the read asserts four absences and **two are false**
(strava 2 training records, habitify 12 habit records). #3276's fix deployed ~06:00Z and the board
regenerated at 15:09Z *after* it, so the check is deployed and not reaching that surface. Filed as
**#3294** (`Now`). Nothing rolled back, correctly — the rollback reverts `site/` and this is
DynamoDB-served, #3252's unmet box 5 demonstrated a second time. **Do not clear this with a no-op
`workflow_dispatch`**: that turns `check_main_green` ✅ while skipping the very QA job that fails
(folded onto #2578). **doc-sync clean.**
**Deploy:** 4, all verified by content — AWS Budget `150.0 → 215.0` · governor `"215"/"252"` ·
site-api · qa-smoke · og-image-generator (cards regenerated and read back)
**Incidents:** 5 worth recording — the pre-ceiling lease; the census swallowing a syntax error; the
drift red `wait_pr_green` refused to misclassify; the piped exit code; the concurrent epic-body edits
**Closures:** #3264 #3255 #3258 #3260 #3261 #3257 — all with contract-shape verdicts. #3252, #3250,
#2801 deliberately NOT closed
**Backlog:** promoted **#3265** (both edits). **`now_liveness` stays RED at 2 of 3, recorded not
suppressed** — the planner prints `NO REMEDY IN THE CORPUS` for the opus lane; the only sanctioned
promotion (#2849) is `model:fable`, which three consecutive sessions have declined. The queue is
short *because this session drained it*. Two filers independently reached the same conclusion.
**Alarms:** all cited, gate exit 0
**CI warnings:** 1 — the unit suite at 2298s/1950s, the class's **eighth** instance. Triage: **no new
filing, no raise** — owned by **#3265**, promoted to `Now` this wrap. #3224's instruction stands:
attribute before touching the number. `--decoded` after naming it.
**Ledger:** the `proportionality-reread` in #3275 *is* this session's ledger work — 11 rows corrected
**Stash/hooks:** clean

## The session ended on a spend limit, not a stopping point

The lane implementing **#3294** — the P1 that is blocking every site deploy — was terminated
mid-implementation by a **monthly spend-limit API error**. It had written 442 lines across six files
and was starting the coverage enumeration when it stopped.

That work is **committed and pushed to `issue-3294-absence-sourcing-coverage`**, with no PR, marked
`WIP … DO NOT MERGE AS-IS`. It has no must-fail proof, no finished enumeration, and no regression
test. It is a starting point, not a fix — verify it against the acceptance boxes rather than
trusting it.

**Nothing else was in flight**: 0 open PRs, 0 waiting leases, working tree clean, doc-sync clean.

## Residual / next picks

- **#3284 — needs the owner's hands.** The current cycle's chronicle article (24 KB, real, in the
  live catalog) is unreachable to **every** reader. A repo-side fix does not deploy: the
  v4-redirects CloudFront Function body is a separately published artifact only Matthew republishes.
  Week 2 and Week 3 are pre-blackholed on the same three lines. `gate:owner`, so it will **not**
  self-select into `/uplevel`'s seed query.
- ~~**#3282**~~ **CLOSED** — the selector reads the stored record; pagination 84 → **93 genes**; a
  fourth defect found in the same file (multi-row genes kept whichever row DynamoDB returned last).
- ~~**#3285**~~ **CLOSED and verified live** — the card now reads 0 GREEN / 1350 AMBER in the delta
  tile, re-sampled from the deployed PNG.
- **#3283 #3277 #3278 #3279 #3288** — filed, verified, on `Later`. #3286/#3287 are CLOSED.
- **#3294 — P1, START HERE. It blocks every `site/**` deploy.** The board asserts four absences and
  two are false (strava 2, habitify 12); #3276's check is deployed but does not reach that surface.
  The visual QA gates every site deploy and auto-rolls-back on red, so the site is frozen and
  **#3286/#3287's front-ends are already sitting reverted** because of it. WIP on
  `issue-3294-absence-sourcing-coverage` (unverified). **This is why main is red.**
- **#3293** — two more surfaces state a direction from a signed value; `site_api_pulse.py:301`
  asserts `"up"` on absent/zero data while `:412` in the same file already does it correctly.
- **#3289** — the worktree reaper cannot tell a live lane from a finished one.
- **not-work — `/api/pulse`'s `mind` glyph has no `as_of` at all**, so #3287's disclosure cannot
  reach it; and `water`'s date is honest but not frame-labelled. Lane L named both, out of scope.
- **#3252** — box 2 is now UNBLOCKED by the owner's ADR-104 ruling and shipped in #3276; box 5 (the
  rollback-scope ruling) still needs a live gated run.
- **#3250** — open at 3 of 5: the `/review <lens>` spine, the ADR-099 dedup, the exemption orphans.
- **#2801** — open at 2 of 4: the CloudWatch EMF estate inventory and the secrets-manager floor.
- **#2578** — carries three new §10 folds this session.
- **#3083** — **decided hold** (owner, 2026-08-28), not a fourth silent parking. Do not re-surface
  as undecided; re-raise only at a materially larger n than 42.
- **#2883** — owner ruled **re-measure at n=30**. New datum recorded on the issue: only ~36% of real
  Bedrock spend carries a `CallerClass` dimension, which may be the reachable bar.
- **not-work — `operating-calendar.yml` is GREEN again**: both NEVER-RUN entries ran and landed.
- **not-work — rotate `life-platform/bluesky` and `life-platform/youtube`** if the owner judges it
  warranted: a subagent read them incidentally; values are in a local temp transcript only.
- **not-work — the #3260 alarm is unproven in production** until a dimensionless
  `AnthropicAPIFailure` datapoint appears after a real failure. A green suite is not evidence.
- **not-work — `mcp/` (~21k lines) is essentially unswept** by the bug bash; the finder said so.
- **not-work — worktrees reaped**: 13 of 14 removed, 25 kept. #3289 records the near-miss.
- **Dated:** **2026-08-31** — #3178 sentinel proof, #3191 TTL sweep · **2026-09-01** — the ceiling
  window reverts (now a RAISE, no action) · **2026-09-06** — #3245's calendar hold expires ·
  **2026-09-09** — `prediction-gradable-share-low` must carry a `#N` · **2026-09-16** —
  `fullreview-delta` hard date · **~2026-09-24** — #2978's re-measure.
