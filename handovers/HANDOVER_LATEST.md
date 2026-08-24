# Handover — 2026-08-24 (Fable 5, autonomous, ~19h incl. overnight watchers): Phase D2 of the A-Grade Program + the deploy plane healed + the biggest single-session drain yet (28 PRs, 17 closures)

## SESSION_STATE — Session A (shimmering-snacking-quokka), live block, replace at each phase boundary

**Updated:** 2026-08-24 ~19:45Z · **Phase:** A2+A3 agents in flight · **Driver:** Fable 5.
If resuming on Opus: *"Resume ~/.claude/plans/shimmering-snacking-quokka.md from SESSION_STATE"*.

- **A0 DONE.** Main green at `5fa985dd8` (wrap commit's Docs CI red fixed by `ceffdb2e1` —
  fact-scanner misread "#2989 alarm fix" as an alarm count + stale INCIDENT_LOG patterns;
  citations commit `5fa985dd8`). Fleet deploy confirmed complete (qa-smoke LastModified
  2026-08-24 18:51Z). No waiting leases. `gh secret list`: NO RECONCILE_PUSH_TOKEN, NO
  DEPLOY_GATE_JANITOR_TOKEN → D0.6 + #3021 skipped silently per plan.
- **Scheduled observations read:** first real nightly edge-429 = **GREEN** (PASS among 58;
  registered qa_smoke_lambda.py:1015, deployed pre-run; the 3 PAUSE + 1 WARN + 1 FAIL all
  enumerated and edge_429 not among them). Baselines: RegenDiscarded 0/24h ·
  TruncatedResponses 15 (D2's own burn window) · CallerClass dimension live (prod-cron/ci)
  · GenerationSkippedUnchanged no data yet (#3107 known). Recall corpus GREEN tonight.
- **qa-smoke-failures still lit, NEW cause:** nightly FAIL = cross_surface:weight — Webb
  (nutrition_coach) cites 321 lb (generated 08-23) vs cockpit 326 (weighed 08-24) because
  today's regen was HELD twice by the ADR-108 quality gate (score 62 both attempts).
  Evidence commented on #3083; alarm re-cited with expiry 2026-08-25T18:00Z. Also filed
  #3108 (coach-state-updater float('early') bug, glucose_coach RELATIONSHIP#state stalls).
  ai-tokens-daily + s3-bucket-size alarms decoded + cited (latter folded into DIL-026 lane).
- **Agents in flight (11, all worktree-implementer, PRs never self-merged):** #3103
  wait_pr_green (sonnet) · #3102 confirm-before-gate (sonnet) · #3101 literal-conflict
  (opus) · #3049 source-completeness (opus) · DIL-025 idempotency census (opus) · DIL-028
  raw-layout replay (sonnet) · DIL-026 lifecycle + bucket-size disposition (sonnet) ·
  DIL-027 cross-account/region raw/ backup (opus) · #2997 qa-smoke-warnings reconcile
  (sonnet) · #3000 census lane (sonnet) · #2578 CodeQL-sentinel can-it-fail (opus).
- **Next:** merge trains for foundation trio first (use #3103's tool once landed), then D3
  lanes + register flips; A4 drain wave (#2815, #2957 residuals, #3066, #2823, #3018,
  #2888, #2847, #2883 residuals, #3108) launches as slots free; epic acceptance passes
  #2986/#2798/#2799/#2801/#2578. Owner batch surfaced in-conversation (8 items, unanswered
  → wrap). Merge discipline: verdicts read in their OWN command, check sets by name.

**Session:** Fable 5. Drove: *"Boot Phase D2 of the A-Grade Program"*
(`~/.claude/plans/ticklish-soaring-teapot.md`), then owner-directed scope expansion:
*"clear as much of the open issues backlog as possible with sub-agents … non-fable
where possible"*, *"make sure all pull requests are done"*, *"pay down as many open
items as possible"*. AUTONOMOUS with merge+deploy authority. Previous handover archived
as `HANDOVER_2026-08-23_agrade-d1-control-boundaries.md` on `session-archive`.
**Next session:** Session A of `~/.claude/plans/shimmering-snacking-quokka.md`
(owner-approved: D3 + foundation + drain; Fable drives A, Opus drives B).

## What shipped (28 PRs merged AND deployed AND live-verified)

**D2 — the truth manifest (all three lanes done; DIL-010/035 flipped, #3097):**
- **Lane 1 (#2898 CLOSED, PR #3080)** — the ceiling family collapsed to ONE source
  (`cost_governor_lambda` constants): `site_api_budget` imports it, `core_stack`
  derives at synth (template proven byte-identical), `renderCost` reads live
  `/api/receipts` with ADR-104 omit-when-stale, derivation guard in the premerge lane
  (`scripts/budget_ceilings.py` = the one parser; a second parser is itself forbidden by
  test). Mutation-proved 5 ways. **Found live: /method/cost/ told readers $150 while the
  August window base is $200**, plus a "$~80" string-concat display bug — both dead.
  Live: receipts serves 200/235 + window flag; auto-reverts 09-01 with no deploy.
- **Lane 2 (PR #3072)** — public-claims registry: 4 behavioral claims (remediation mode,
  deploy lanes, deletion promise, auto-merge caps) with wire-real comparators both
  directions (comparator reds on drift; discovery reds an unregistered claim-bearing
  generator). Runtime-state claims use the permanence-terms recorded-value pattern.
  PROPORTIONALITY row. Scope-disciplined to exactly four.
- **Lane 3** — verified already-closed by intervening work (catalog current + `--check`
  in docs-ci; platform-model `--check` pre-merge in docs-ci); epic #2986 commented with
  per-box acceptance, ONE honest residual keeps it open (the generic re-stamp rule).

**The deploy plane, broken at boot, fully healed:** D1's wrap site-deploy had rolled
back; #3064's rerun failed with three NEW causes. All diagnosed and fixed at producers:
#3057 AA clamp on data-supplied coach colors (PR #3071, closes it); #3067 vision-judge
tall-page tiling — bound derived from the model's 1568px resize tier, NOT Bedrock's 8000
reject limit (PR #3078); #2957 got two new members (chronicle archival framing, the
verify-table), then **PR #3074 fixed six members at the producer** via the shared
`site_api_phase_frame` vocabulary and drained 6 baseline entries; #3066 hero as-of
framing (PR #3075); a REAL #2506-class front-end bug on /story/agents/ (UTC week seed —
PR #3095); and a main-level landmine from the CSP extraction (page_data.js broke the JS
unit lane for every site PR — PR #3077). Site-deploys green end-to-end since; #3064
auto-closed on a green standalone run.

**The drain (owner-directed):** every Now story + a Next wave, all via sonnet/opus
worktree agents (18 agents; ~0 Fable tokens in implementation): #2989 alarm banding
(cleared live same-session), #2893 waste audit ($1.66/mo eliminated; surfaced the
ADR-108 gate green-lighting 84/484 unevaluated drafts → #3083 owner call), #2889
gen-cache extension (measured skip-rate was ZERO; causes fixed/filed #3107), #2813
PT-day contract sweep, #2883 remediation-spend attribution (PR #3070 + IAM applied),
#2892 caller-class dimension at the bedrock chokepoint, #3082+#3084 transport extraction
(ai_calls 2396→2264, re-bill + budget-retry dead), #3086 regen-discard telemetry, #2824
grant-enumeration call-graph sweep (**found 12 live IAM gaps** incl. golden-eval running
Bedrock outside the budget ceiling — PR #3094 closed 12/13 + both out-of-band applies,
`verify_oidc_iam --strict` CLEAN), #2837 EMF ledger (**premise inverted: the bill tracks
~102 dense series ≈ $19/mo, not the 703-series inventory**), #3037 unparked (recall
publish-path grants + self-heal + silence-alarm extraction, monitoring ratchet TIGHTENED
1358→1331), plus both dependabot PRs and the CodeQL pair (#160 fixed + rescan-confirmed,
#159 dismissed with reason — **code scanning at 0 open**).

**Deploys (all postflight-verified):** fleet pass **105 lambdas / 0 failed** at HEAD
9331995b · 6 cdk stacks (Monitoring ×2, Email, Ingestion, Operational, Serve, Compute) ·
site-api ×2 + site auto-deploys ×4 (final green) · qa-smoke + chronicle-approve +
coach-quality-gate + coach-state-updater · IAM put-role-policy ×2 (remediation
AiCostTelemetry, golden-eval BudgetTierRead/EvalConfigRead) with strict parity CLEAN.

## Retrospective (owner-requested) + the foundation it produced

~Half the 12h+ wall-clock was process friction, now filed: **#3101** literal-conflict
surface removal (the serial merge tax — 15 PRs × 12–18 min check cycles + reconcile-bot
races), **#3102** confirm-before-gate for truth verdicts (3 rollbacks on single-run
judge flips), **#3103** `wait_pr_green.sh` (the blessed named-check-set watcher),
**#3104** merge-train mode. Fifth lesson to memory: combine finding→fix in ONE agent
brief (the #3092→#3094 and #3081→#3091 stacks each paid a doubled check cycle).

## Gate lines

**Build beat:** 2026-08-24-d2-truth-manifest
**Docs:** DILIGENCE register (DIL-010/035 flipped, #3097) · PROPORTIONALITY (+3 rows via
PRs: claims registry #3072, grant sweep #3092/#3094 with the 13-gap correction, EMF
ledger #3093) · INCIDENT_LOG (+3 rows + header) · alarm_citations (+4 entries) ·
SECRETS_MAP-adjacent: infra/iam README (both staged grants stamped APPLIED) ·
MONITORING (regenerated: derived ledger pointer, #3093) · COACH_STANCE (fail-open
posture documented, #3081) · engines/ADR-126 amendment (#3073) · sync_doc_metadata
--apply run at the wrap commit
**Decisions:** none needed — no governance-class choice beyond dispositions already
recorded in the register/PROPORTIONALITY rows (the fail-open gate call is deliberately
DEFERRED to the owner as #3083)
**Main:** green (9331995b)
**Incidents:** 3 rows added — two merge-train site auto-rollbacks (one #2957 member
baselined, one real UTC-week bug fixed #3095; single-run-verdict exposure filed #3102);
the deploy-critical PyYAML collection red ~1.5h (#3100/#3105); the ~15.5h
production-lease chain (2 leases rejected with decode; janitor token = owner batch)
**Stash/hooks:** clean
**Closures:** #3057, #3064, #3067, #2989, #2977, #2898, #2893, #2892, #2889, #2837,
#2824, #2813, #3082, #3084, #3086, #3096, #3098 all commented (ADR-099 two-line
verdicts; #2889/#2892/#2824/#3084 honestly `partial` with residuals named — #3107 filed
for the coach-brief cache gap, the chronicle-sender grant rides the _OPEN_GAPS ratchet)
**Backlog:** Now live at 3 actionable (promoted #3101, #3102, #3103 by stored rank —
also Session A's first work); Later sweep — no stale Later issues; hygiene OK across 67
open (14 violations found at the gate all fixed: 4 epics' Stories coverage, outcome
audiences, #3083 label, #3098 wedge tracker closed, score-line milestones)
**Alarms:** 0 red >72h uncited; 10 flap episodes in the 72h window all decoded in
alarm_citations (ai-daily-spend ×2 + site-api-invocation-spike ×7 + coherence ×1 — all
the session's own agent burn/QA traffic, each with an expiry clause);
qa-smoke-failures re-cited as a dated self-clearing window (stale corpus evidence;
expires 2026-08-25T19:00Z — if still lit after the first post-#3037 nightly, file fresh)
**CI warnings:** 1 — unit-suite 1507s vs 1500s budget (7s over; this session added ~230
tests); filed #3106 for the measure-first budget re-decision (--decoded)
**Ledger:** 3 rows added (public-claims registry · grant-enumeration sweep · EMF
namespace ledger — each in its shipping PR, ADR-103/144 shape)

## Owner batch (ONE ask — everything needing Matthew; front-loaded next session per plan A1)

1. **RECONCILE_PUSH_TOKEN PAT** (unblocks D0.6 required checks — also the structural fix
   for tonight's reconcile-bot races).
2. **DEPLOY_GATE_JANITOR_TOKEN** (#3021 — would have caught tonight's 15.5h lease chain).
3. **respiratory_rate + disturbance_count consent** (#3045 residual).
4. **notion secret deletion pre-check** (#2890 — LastAccessed 2026-07-25 reader).
5. **#2961 cdk-import approval** (D3 alarm lane) · **#2834 IAM posture**.
6. **NEW: #3083** — the ADR-108 quality gate fail-opens on its own fallback report
   (84/484 drafts green-lit unevaluated): pass-for-availability stays, or hold?
7. **NEW: schedule the DIL-027 timed restore drill** (a ~30–60 min owner appointment;
   Session A ships the cross-account raw/ backup + priced row without it).

## Residuals / next picks

- **Session A** = `~/.claude/plans/shimmering-snacking-quokka.md` (owner-approved):
  D3 lanes + foundation (#3101/#3102/#3103 now on Now) + drain toward zero. Boot prompt
  delivered in-conversation 2026-08-24.
- **Scheduled observations (not-work — dated):** first REAL nightly edge-429 2026-08-24
  18:30Z (RED is real) · qa-smoke-failures self-clear window expires 2026-08-25T19:00Z ·
  new metric baselines accruing (RegenDiscarded / CallerClass / TruncatedResponses /
  GenerationSkippedUnchanged — read at Session A boot, no alarms until baselined) ·
  first prod-class governor share after one 8h cycle · first real prediction grades
  ~2026-08-31 · WAF revisit 2026-10-15 · legacy unsubscribe sunset 2026-09-22.
- **#2883 stays open** (boxes 2/4: ratio re-measure post-telemetry + CE reconciliation)
  — Session A drain list.
- **#2824's last gap** (chronicle-sender personas.json) is now unblocked (#3037 merged)
  — rides the `_OPEN_GAPS` ratchet, which reds the day it's fixed and not deleted.
- **Honest lessons worth carrying:** (1) the absent-check class recurred TWICE as a
  compound-command slip (watcher output + merge in one command) — #3103 makes the fix
  structural; separate-command merges from now. (2) Two stranded leases accumulated
  because mid-train gate arrivals had no watcher — janitor token + #3103. (3) The
  yaml-less-lane collection break is the 2026-08-08 class recurring — module-scope work
  in test files must be import-guarded.
