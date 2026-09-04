# Handover — 2026-09-02 (Fable 5): Session T — the drain to the floor

**Session:** Claude Fable 5, executing the owner-approved Session T plan ("do the next
session plan" — maximal drain + the owner window). Phase 0 boot reads; Phase 1 the two
P1 pipe repairs driver-run in order (#3442 → #3443); Phase 2 three lane waves (9
worktree-implementer lanes, all landed); Phase 3 driver work (#3448, #3373 design, the
owner window — both gate:owner items cleared IN-SESSION); pre-wrap: the 5 stale
dependabot PRs folded in. **Target was 14–16 closes; landed 18** (plus 2 filed), with
every survivor's reason named. The owner was present throughout — approved the IAM
apply, picked (a) on #3424, and approved the Session U plan.

## What shipped — 24 PRs merged (19 session + 5 dependabot), 3 approved fleet deploys, 18 issues closed

**The P1 pipe repairs (driver-run, deployed, live-proven):**
- **#3442 / PR #3456** — the whoop `DATE#<d>#WORKOUT#<uuid>` clobber class: ONE shared
  day-row predicate (`digest_utils.DAY_SK_RE`/`is_day_row`/`filter_day_rows`),
  `query_range` day-rows-only as the paved road, all 8 member sites fixed, field_notes'
  prior-art regex converged, and the SET guard — an AST census registry pinning every
  literal-whoop query site (32 modules) by lane; a 9th member cannot silently re-join.
  The verifier's byte-exact reproductions are wire-fixture regressions through the REAL
  code paths (W35 hrv_vs_recovery 11/.9799→14/.9666; ACWR 08-31 0.945→1.040, 24/85 days).
- **#3443 / PR #3457** — ACWR survives the night: co-owned field registry
  (`compute/computed_metrics_contract.py`), read-before-put carry in BOTH from-scratch
  rebuilds (fail-loud), a derivation guard pinning the acwr writer's UpdateExpression to
  the registry, and the dead-man (`operational/acwr_liveness_qa`, >48h red — this
  incident pages on day 2). **The filed #3135 hypothesis was REFUTED**: the real trigger
  is the #2811 PT-clock correction re-aiming the evening re-put from UTC-yesterday (a
  wrong-record latent bug that accidentally protected the merge) onto PT-yesterday.
  **Backfill: all 8 dark days restored with clean values — 08-31 serves 1.040 live**, the
  exact number the #3442 verifier predicted; 09-01 corrected to 1.017; 09-02 seeded for
  tonight's 00:00Z survival observation.

**The lane waves (9 lanes, 9 PRs):** #3444/PR #3463 (phase-filter third wave + the
ratchet traced through digest_utils; 2 further sites recorded as debt) · #3445/PR #3460
(Evidence Bar MAP-shape + n_eff — a real level-flip found in live W35 data) · #3446/PR
#3459 (input_status-aware Day-1 guard; the live force-recompute proved it) · #3447/PR
#3461 (budget-ledger invariants; live check surfaced an unregistered billed secret) ·
#3449/PR #3465 (closure-aware registry fingerprints, 3 blind spots proven to trip) ·
#3450/PR #3467 (Wilson accuracy_ci95 everywhere + settled/open disjointness — the
DIL-039/040 8/37 [11.4%, 37.2%] number is now the served format) · #3451/PR #3466
(sleep n + device disclosure, Playwright DOM proof) · #3453/PR #3464 (structural
value-position sentinel — 5th phrase-matched family member retired) · **#3430/PR #3471
(opus root-cause: the compute-pipeline flap was a FALSE POSITIVE — operator pre-cron
dry-runs + Period-86400 evaluation arithmetic; 0-of-4 true positives in 60d; #1962's
premise falsified by the metric record; the authoritative-run gate ships with positive
controls).**

**Driver work:** #3448/PR #3462 (the 2% null stamped as a documented ADR-105 exception —
registry entry `directional_trend_verdict`, executable failure regimes, September n≥30
re-derive trigger) · the #3373 design comment (substrate, row schema, five primitives,
the #3447 interplay, the governor hold_until ruling — carry, implementation on the owner
call) · smalls #3437/PR #3470, #3438/PR #3468, #3455/PR #3469.

**The owner window (both gate:owner items CLOSED in-session):**
- **#3429 / PR #3458** — owner approved the IAM apply; three live sentinel dispatches
  enumerated the REAL read set beyond the filed four (ListTargetsByRule, backup-bucket
  reads, `s3:GetLifecycleConfiguration` — the action name lacks "Bucket", raw/* listing
  for the sampler). Final run 18:46Z: **3 clean + 1 honest drift, zero AccessDenied** —
  the DIL-027 chain exercised for the first time since the checks landed.
- **#3424** — owner picked **(a)**: the 30s fail-open ceiling accepted as a dated priced
  tolerance (decision-time re-measure **0/109, Wilson [0%, 3.4%]** — the filed 4% tail
  predates #3413 and has not recurred), recorded in the ADR-108 scope row (3c6aab5be)
  with quarterly/p90-25s/any-occurrence re-measure triggers and **(d) pre-named as the
  upgrade path** — never a silent widening.

**Also live-verified:** the Day-1 character force-recompute (#3390 leg — structurally
impossible pre-#3446); the #3414 day-2 counter (12 passed / 3 failed, n=15 — the first
failed voice verdicts this surface ever recorded); dependabot batch #3405–#3409 all
green after rebase (one stuck "merge in progress" cleared on retry).

## Gotchas hit

1. **A rejected code-lease superseded by a docs-only tip = an undeployed-merge window.**
   Stewarding rejected #3462/#3463/#3470's merge runs in favor of the then-tip — which
   was a docs-only commit whose Deploy the classifier SKIPPED. Caught by content-checking
   lambda timestamps, not by any green run; cured with a `deploy_all=true` dispatch +
   approval, content-verified. New reflex in the lease memory: before rejecting a
   code-bearing lease, confirm the superseding run will actually deploy.
2. **`gh` auth died mid-session** — `~/.config/gh/hosts.yml` truncated to 3 bytes,
   almost certainly a write race among the many concurrent gh pollers (Monitor + several
   wait_pr_green watchers + lanes). Git-remote auth survived; only the owner's
   `gh auth login` recovers. Memory: `reference_gh_hosts_yml_write_race`.
3. **The extraction-moves-the-anchors class fired on BOTH P1 PRs** (Session S's gotcha,
   reproduced): the census test tripped gate-census/premerge-registration/two size
   ceilings; the qa dead-man pushed qa_smoke over 1200 (extracted to the raw_archive_qa
   sibling pattern); daily_metrics paid for its carry via extraction into the contract
   module. Also learned: an EXTRACTED check leaves the gate census (the #3457 bump had
   to be reverted — found=590 on its branch while #3456's test added the +1).
4. **The swallow-recovery ladder's rung 1 failed live** (#3430 lane): close/reopen minted
   ZERO runs — only a new head sha recovered. Ladder memory extended.
5. **The census/ledger literals churned all queue long** — PROPORTIONALITY's gate count
   and BASELINE_TOTAL_GATES needed per-branch reconciliation at 3 points (590→591→592);
   the stack-census-PRs discipline held.

## Gate lines

**Build beat:** 2026-09-02-the-drain-to-the-floor
**Docs:** engine docs re-verified in-queue (READINESS + SCORING #3443, CHARACTER #3446, HYPOTHESIS #3444+#3450 folded), 4 PROPORTIONALITY rows in-PR, INCIDENT_LOG updated in-PR (#3430 row rewrite) + 2 wrap rows, `docs/alarm_citations.json` re-pointed, this wrap's sync_doc_metadata
**Decisions:** none needed — the #3424 tolerance landed as a dated ADR-108 scope-row amendment (3c6aab5be), not a new ADR; the #3448 exception rides ADR-105's documented-exception form
**Main:** green (a1d8623f)
**Incidents:** 2 rows added — the gh hosts.yml auth truncation (~30 min gh outage, owner re-auth); the undeployed-merge window from lease rejections superseded by a docs-only skipped-Deploy tip (caught by content check, cured by deploy_all)
**Stash/hooks:** clean
**Closures:** #3442, #3443, #3444, #3445, #3446, #3447, #3448, #3449, #3450, #3451, #3452, #3453, #3455, #3437, #3438, #3429, #3424, #3430 commented (18) · DoD: scanned=24 window=closed>=2026-09-02 hits=10 findings=10 dispositioned=0 mode=warn — all 10 are post-close-comment: the (e8) wrap-time verdicts themselves landing after `Fixes #N` auto-close, the contract's own designed flow, dispositioned as-designed; 0 unhomed residuals, 0 post-close assertions of continued work
**Backlog:** Now 3 actionable in-lane (#3436, #3422, #3390 — no promotions needed, floor met); Later sweep — none stale, no calls owed
**Alarms:** all cited (batch PASS) — `ai-tokens-platform-daily-total` re-pointed #2801→#3474 (its citation went stale when the owner-window closed #2801's parent; the #2996 closed-citation leg of the gate caught it)
**CI warnings:** 3 — 2× duplicate `LifePlatformMonitoring` Tags (the ONE real pending owner cdk deploy, standing owner ask: `bash deploy/cdk_deploy.sh LifePlatformMonitoring`); 1× Unit Tests 2038s > 1950s budget (the #3403 class — its acceptance waits on post-#3378 data, earliest ~09-08; this session added ~60 tests across 19 PRs; no raise on a single reading per the warning's own instruction); decoded
**Ledger:** rows added in-PR — #3443 (co-owned computed_metrics write contract + ACWR dead-man) and #3448 (the stamped ±2% exception, priced acceptance); none new at wrap

## Residuals / next picks (the floor: 9 working issues, every survivor's reason named)

- **The Session U plan is owner-approved** — `~/.claude/plans/lovely-snacking-panda.md`:
  one session on **2026-09-08** (Opus, September posture). Expected 9 → 5 working.
  (not-work — the plan itself; its items are cited below)
- **#3473** — compute-pipeline-stale heartbeat (the #3430 residual; Next, workable any
  session).
- **#3474** — ai-tokens daily-total re-threshold-or-tripwire (filed at wrap when the
  citation gate caught the orphaned alarm; Next).
- **#3422** — the janitor cadence leg: now DECIDABLE — Session T's 0-of-~10 (the hand
  steward beat the janitor to every rejection) + the 2–4.5h measured cadence point at a
  `workflow_run` event hook over the 15-min cron.
- **#3403** — not-work until ~09-08 — its acceptance requires the post-#3378 duration
  window.
- **#3436** — Engineering-leg design box after the 09-08 Architect first run; arming is
  gated on 4 clean Architect weeks by its own precondition.
- **#3390** — owner-only residue: the weigh-in → supersede reflex (the session-runnable
  legs are done, incl. the Day-1 force-recompute).
- **#2883** — not-work until the September n=30 clean-month read (~09-30), per its own
  thread ruling.
- **#2978** — check its `blocked:date` on 09-08; the warm-retry/origin-side fix is
  ordinary engineering once open.
- **#3042** — the A-Grade epic: moves on grades + the two owner acts (pentest and
  signed-artifacts commission-or-decline rows).
- **#3373** — design posted; implementation on the owner's park-or-build call (an 09-08
  Architect input).
- **Tonight's two observables:** the 00:00Z evening re-put must preserve 09-02's seeded
  ACWR (not-work — the acwr_liveness dead-man owns it from here); the ~23:42Z
  reader-truth sweep's `basis:"withdrawn"` count (not-work — a courtesy datapoint on the
  closed #3399, predicts exactly one).
- **Standing owner asks (unchanged set, renumbered):** pentest · signed artifacts · the
  #1781 cleanup script · the two drills · `bash deploy/cdk_deploy.sh
  LifePlatformMonitoring` (clears 2 of the 3 CI warnings) · the weigh-in (#3390/#2883) ·
  the 09-08 Architect inputs (#1407, Time-Affluence rent ruling — read Sunday's first
  cross-phase run first, the calc-proof corpus, the #3373 call). (not-work — owner-only)

**The through-line:** Session S proved the arithmetic and indicted the pipes; Session T
replaced the pipes and watched the true numbers flow through them — the erased 0.945
became a served 1.040, the never-scored meter got its first honest window, every served
accuracy grew its interval, and the two decisions only the owner could make were made
in the room, in the session, on fresh measurements. The floor that remains is not
unfinished work; it is dated windows and owner acts, named one by one.
