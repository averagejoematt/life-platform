# FULLREVIEW — 2026-07-28 (PARTIAL / BANKED)

> **Status: INCOMPLETE BY DESIGN — banked mid-flight, awaiting a Fable delta review.**
> This is the second `/fullreview` panel run (baseline: [FULLREVIEW_2026-07-16.md](FULLREVIEW_2026-07-16.md)).
> It was launched on Fable 5 and **ran out of Fable usage credits mid-panel**. Matthew's explicit direction
> was to bank Fable's work verbatim and NOT let another model finish or re-judge it — the point of the ritual
> is that Fable grades work that Opus/Sonnet produced, so an Opus completion would defeat the review's
> independence. **Nothing in this document was authored, graded, adjusted, or verified by any model other
> than the Fable panel agents.** The orchestrator (Opus 5) only transcribed the workflow journal.
>
> **Resume date: on or after 2026-08-02** (Fable weekly window reset, ~5 days from 07-28).

## What ran, what did not

| | Count | Detail |
|---|---|---|
| Lenses graded | **14 / 17** | missing: security, data-architect, growth |
| Lenses adversarially verified | **12 / 17** | cto + observability graded but UNVERIFIED; 3 ungraded |
| Raw findings | **72** | 13 high-sev |
| Verdicts returned | **63** | 46 CONFIRMED · 17 ADJUSTED · **0 REFUTED** |
| Findings still unverified | **9** | cto (4) + observability (5) |

**The 0-REFUTED result is itself notable and should be scrutinised by the delta run.** The 2026-07-16 run
refuted 17 of 89 (81% survival); this run refuted 0 of 63 (100% survival, with 17 root-cause ADJUSTMENTS
instead). Either the graders' evidence discipline improved materially, or this run's verifiers were less
adversarial than the baseline's. **Treat every finding below as provisional until the delta run re-tests a
sample** — the standing repo lesson is that ~50% of unverified subagent findings are false positives, and a
verifier that never refutes has not demonstrated it was trying to.

## Ground truth at review time

- **Day 1 of cycle 11** — genesis `2026-07-27` (`lambdas/constants.py`), SSM `experiment-cycle` = 11. Baseline weigh-in 321.09 lb (real).
- Live site build `6acd301` == main HEAD (deployed 2026-07-28T03:21Z). Main GREEN. Repo PUBLIC since 2026-07-20.
- **Budget tier 2**, standing by design until 08-01 (July temp ceiling $115/$135 per the ADR-133 amendment).
  Tier 2 pauses internal/dev AI *and* reader narratives — every grader was briefed that an honestly-"paused"
  surface is correct behavior, and that only a *stale or wrong* surface is a defect.
- Remediation agent = `shadow` (deliberate, ADR-129).
- Every grader carried the Day-1 **intentional-emptiness manifest** from `lambdas/phase_taxonomy.py` and the
  60-issue **do-not-refile list**, plus its own **2026-07-16 rubric anchors verbatim** so grades diff mechanically.

## Scorecard (14 of 17 lenses)

`†` = grader-proposed but **never adversarially verified** — do not act on these two grades without the delta run.

| Lens | Area | Grade | vs 2026-07-16 | Findings | C / A / R |
|---|---|---|---|---|---|
| cto | Architecture & ops | **B+**† | = held at B+ | 4 | **unverified** |
| principal | Code health | **A-** | = held at A- | 4 | 2 / 2 / 0 |
| aiq | AI content integrity — grounded generation (ADR-104), rigor  | **B** | ▼ **down from B+** | 6 | 3 / 3 / 0 |
| cpo | Product & narrative arc (CPO lens) | **B+** | = held at B+ | 5 | 3 / 2 / 0 |
| designer | Design system | **A-** | = held at A- | 3 | 3 / 0 / 0 |
| dataviz | Charts & instruments | **B+** | ▼ **down from A-** | 3 | 3 / 0 / 0 |
| qs | Scientific credibility | **C+** | ▼ **down from B+** | 9 | 6 / 3 / 0 |
| narrative | Voice & immersion (Narrative editor) | **B-** | ▼ **down from B** | 8 | 7 / 1 / 0 |
| security | Security & privacy lead | **NOT GRADED** | (was A-) | — | — |
| a11y | Accessibility | **A-** | = held at A- | 4 | 2 / 2 / 0 |
| reader | First-contact comprehension (cold Reddit reader, live site,  | **B** | ▼ **down from B+** | 7 | 6 / 1 / 0 |
| observability | observability — Telemetry & alerting | **B+**† | ▲ up from B | 5 | **unverified** |
| cost | Cost engineering | **B+** | = held at B+ | 5 | 5 / 0 / 0 |
| data | Data architect | **NOT GRADED** | (was B+) | — | — |
| integrations | Ingestion health | **B+** | = held at B+ | 4 | 3 / 1 / 0 |
| devex | Build & ship ergonomics (AI-agent development) — DevEx/SDLC  | **A-** | = held at A- | 5 | 3 / 2 / 0 |
| growth | Growth PM | **NOT GRADED** | (was B+) | — | — |

### Grade movement vs the 2026-07-16 baseline

**Regressions:**
- **aiq** B+ → **B**
- **dataviz** A- → **B+**
- **qs** B+ → **C+**
- **narrative** B → **B-**
- **reader** B+ → **B**

**Improvements:**
- **observability** B → **B+**

**Held:** cto, principal, cpo, designer, a11y, cost, integrations, devex.

## High-severity findings (13)

Ordered by lens. Verdict shown where a verifier ran.

- **[cto]** **UNVERIFIED** — The public-AI liveness canary's deterministic grounded-digits check fires false ALARMs on TRUE numbers — 4 of the last 9 runs flagged the real weigh-ins (317.61 on 07-22, 321.09 baseline on 07-27) as 'fabricated', because its fact universe (build_canonical_facts over the latest computed_metrics — only 3 keys on Day 1 post-wipe) is narrower than the grounding context the ask pipeline actually serves. The fabrication detector for the honesty moat is now the boy who cried wolf; its own docstring names this exact failure mode ('a permanently-red AI-judged alarm gets ignored').
- **[aiq]** **ADJUSTED** — Live Day-1 public surface serves phase-wrong experiment-age framing: /api/ai_analysis?expert=nutrition states 'Zero food logs in seven days of an experiment' when the cycle is 1 day old — and no gate class can catch it (spelled-out 'seven' is invisible to the digit-only number regex, 7 is in _BENIGN_NUMBERS anyway, and the stale_phase gate matches only 'Day N' tokens).
  - *Verifier correction:* The 'seven days' entered via (a) build_prompt's week framing ('This is Week {1} of the experiment... now day {1}', ai_expert_analyzer_lambda.py:863) inviting week≈seven-days extrapolation, and — more concretely — (b) the tombstone-blind prior-analysis get_item at :1077 (finding 4): restart_intelligence_wipe.py:133 tombstones ai_analysis in 'all' mode IN PLACE (UpdateItem, content preserved), so the cycle-10 EXPERT#nutrition record — whose closing state was literally a week of zero food logs (all July cycle-10 predictions are 'once food logs start coming in') — was present tombstone=true at 14:00:53Z and its first 300 chars were injected as _prior_analysis_summary into the Day-1 prompt. The gate-gap analysis (word-numbers invisible, 7 benign, day-N-only phase regex, no cycle params passed) is confirmed as why nothing caught it. Sev high stands: this is the #1194 hunt-order class live on a public surface.
- **[cpo]** **ADJUSTED** — The coaching door and cockpit board read serve numerically wrong Day-1 data as the current read: Dr. Victor Reyes' live position_summary opens 'Day 1 weight is 317.61 lbs' (the superseded genesis override), Dr. Kai's weekly call says 'a 7.5-hour sleep' and Dr. Brandt cites 60%/40.8ms/64bpm — while the platform's own truth is 321.09 lb (real weigh-in), 8.9h sleep, 56%/37.8/62 on /api/vitals and Home ('321 lb now'). With coach-narrative regeneration paused at budget tier 2 until 08-01, these contradictions stand on the door's first screen for days.
  - *Verifier correction:* The narratives were generated ~48 min AFTER the f06b8221 supersede, yet still baked 317.61 because the supersede's propagation surface (PROFILE#v1, S3 configs, baked pages, repo constants) did not cover the narrative pipeline's actual weight input at generation time: the withings DATE#2026-07-27 row still carried the override until the real reading was ingested 2026-07-28T03:05:42Z, and the regenerated constants.py only reached the fleet with the 03:21Z 07-28 CDK deploy. The needed process fix is supersede propagation to the wearable row / narrative inputs PLUS a dependent-narrative regen (sanctioned as honesty spend under the tier pause) — an invalidation hook alone, fired at supersede time, would have regenerated from the same stale source. Severity high stands; the contradiction is live now on the coaching door's first screen.
- **[dataviz]** **CONFIRMED** — Tombstoned prior-cycle intelligence serves live on the home page: /api/what_changed returns a record tombstoned at the 2026-07-13 reset (computed 2026-07-04, phase=pilot, cycle=5) and the home returnability strip renders it as 'newly unlocked this month: habit pct ↔ day grade (r=0.88, n=20…)' on Day 1 of cycle 11 — the exact #1194 hunt-order defect class, on the front page.
- **[qs]** **CONFIRMED** — At least 21 PubMed citations on the two live public evidence registries resolve to completely unrelated papers — fabricated PMID→claim mappings, several carrying invented quantitative summaries.
- **[qs]** **CONFIRMED** — The public 'Career · every cycle' calibration denominator (n=50) silently excludes 273 pre-registered bets that were voided at resets — the void ledger is write-only and no surface ever reports it.
- **[narrative]** **CONFIRMED** — Webb's live Day-1 coaching-door analysis fabricates graded outcomes from zero data: it declares 'That's a prediction miss, and I'm logging it as one' and 'protein adherence looks better than my baseline predicted' while the SAME text admits 'I have zero food logs. No calories, no macros... Nothing' — and the false verdict is now persisted as THREAD#2026-07-27#lunch_protein_prediction_miss, feeding future generations, and baked into the committed noscript ('The nutrition coach corrected a missed prediction', site/coaching/index.html:55). Recurrence of the #946/#1194 continuity-leak class via a write-time path: STANCE#latest (as_of 2026-07-26, phase=experiment, NOT tombstoned) carries the wiped pilot cycle's adherence continuity ('hitting protein and calorie targets more consistently than I initially predicted') and per coach_narrative_orchestrator.py step-10 comment 'leads the generation framing'.
- **[narrative]** **CONFIRMED** — The public game-rules page /method/game/ presents the dead pilot cast as current pillar owners — 'owner Dr. Peter Attia' (a REAL public clinician presented as platform staff) for metabolic and 'owner Coach Maya Rodriguez' for mind — contradicting the live roster (Dr. Amara Patel, Dr. Nathan Reeves) one door away; kill-on-sight adjacent (real person's name as staff on a public surface).
- **[narrative]** **CONFIRMED** — The wiped pilot cycle's 190g protein target survives in maintained prompt-feeding and page-generating configs and surfaces live as current: /method/game/ nutrition pillar shows 'protein total … target grams 190' and Webb's live analysis closes 'The 190g target and the current meal structure stay in place' — while the sealed cycle-11 canon is a 170g floor at 1,500 kcal (his own cross_domain_note, the sealed prereg, and user_goals.json all say 170).
- **[a11y]** **CONFIRMED** — The cockpit's Month/Journey scope buttons — functional, enabled controls on the flagship tier-1 door — fail WCAG AA in BOTH themes: opacity 0.6 de-emphasis blends the already-faint ink-faint label down to 2.84:1 (dark) and 2.34:1 (light) at 15.3px normal-size text (needs 4.5:1; fails even the 3:1 large-text bar). The failure has been absorbed into the axe baseline since 2026-07-19 so it never gates.
- **[reader]** **CONFIRMED** — REGRESSION of closed #787/#1226: the coaching door's coach card asserts "Day 1 weight is 317.61 lbs" — that is the pre-genesis 2026-07-22 weigh-in, not Day 1's real 321.09 — so a cold reader crossing home (321.1) → coaching (317.61) hits a 3.5 lb contradiction on the experiment's single most important number, on a site whose moat is 'the numbers are real'. Brandt's card similarly cites Whoop 60%/40.8ms/64bpm (Jul 26's values) as current instrumentation while the cockpit shows 56%/37.8ms/62bpm. This is also the #1194 hunt-order class: prior-cycle data presented as current on Day 1 of a fresh cycle.
- **[reader]** **ADJUSTED** — Hunt-order leak (#1194 class): home's ribbon announces "NEWLY UNLOCKED THIS MONTH: HABIT PCT ↔ DAY GRADE (R=0.88, N=20…)" on Day 1 of cycle 11, but the artifact is prior-cycle intelligence — computed_at 2026-07-04, window 2026-06-05→07-04, week 2026-W27, first_seen 2026-06-30 — served as current 24 days later; the genesis wipe of experiment-scoped intelligence did not cover it and the front-end gate only suppresses it pre-start.
  - *Verifier correction:* The leak is the READ path, not the wipe: lambdas/web/site_api_ledger.py:117 (what_changed()) reads SNAPSHOT#current and serves it with no tombstone/phase filter, so a tombstoned prior-cycle artifact ('tombstoned, never deleted... phase-filtered' per phase_taxonomy.py's own contract, line 23) is served as current; the preStart()-only front-end gate is the failed second belt. Fix: honest-empty (honest_null) when item.tombstone is true or computed_at < genesis, plus the computed_at >= genesis gate in story.js. (Secondary observation: weekly-correlation-compute has not overwritten the snapshot since 07-04 despite weekly Sunday runs — worth a look in the same fix.)
- **[observability]** **UNVERIFIED** — The AI-quality canary — the watchdog for reader-facing AI content — failed every scheduled run for a full week (OverallAlarm=1 on 07-20, 07-22, 07-24, 07-27, its entire Mon/Wed/Fri cadence) because the IAM fix (PR #1599, merged 2026-07-20: secretsmanager:GetSecretValue on life-platform/site-api-origin-secret) sat merged-but-undeployed until the owner CDK deploy 07-27 ~22Z; ai-canary-overall is still red now and structurally cannot clear before the next run Wed 07-29 — so the platform entered Day 1/2 of cycle 11, the highest-risk window for stale-AI-content leaks, with its AI watchdog blind.

## Per-lens detail

### cto — Architecture & ops — **B+** †UNVERIFIED

*Trend: = held at B+.*

**No verifier ran for this lens.** Findings below are first-pass only — the historical false-positive
rate for unverified findings in this repo is ~50%. Verify before filing.

#### cto-1 · UNVERIFIED · sev **high** · effort M · class A

**Finding.** The public-AI liveness canary's deterministic grounded-digits check fires false ALARMs on TRUE numbers — 4 of the last 9 runs flagged the real weigh-ins (317.61 on 07-22, 321.09 baseline on 07-27) as 'fabricated', because its fact universe (build_canonical_facts over the latest computed_metrics — only 3 keys on Day 1 post-wipe) is narrower than the grounding context the ask pipeline actually serves. The fabrication detector for the honesty moat is now the boy who cried wolf; its own docstring names this exact failure mode ('a permanently-red AI-judged alarm gets ignored').

**Evidence.** s3://matthew-life-platform/ai-canary-log/latest.json (status ALARM, 'ungrounded numbers {answer: [56.0, 321.09]}; facts={protein_g_target, protein_g_floor, weekly_rate_lbs}') + 2026-07-22.json (317.61 flagged); lambdas/operational/ai_quality_canary_lambda.py:262-279 (_canonical_facts); CW metric LifePlatform/AICanary OverallAlarm=1 on 07-19/20/21/23/26

**Root cause.** lambdas/operational/ai_quality_canary_lambda.py — evaluate_probe's grounded-digits check compares answer digits against _canonical_facts() (latest computed_metrics only), while site-api-ai grounds its answers on a richer context including current weight/vitals; any true number outside the 3-15-key snapshot is scored as fabrication. The 07-22 firing predates the reset, so this is a standing precision defect, not reset churn (the Day-1 thinning merely worsened it).

**Regression guard.** A precision fixture in tests/: feed the canary a probe answer containing ONLY numbers present in the live ask grounding payload and assert zero grounded-check alarms; plus a canary false-positive-rate line in the nightly qa layer (the sensor that watches sensors). Owner: the tests/ suite + qa-smoke layer (ADR-076 layer 2).

**Path-to-A step.** Ground the check against the same payload site-api-ai serves (or extend canonical_facts to the full vitals set) — a correction to an existing load-bearing sensor, zero new standing machinery.

#### cto-2 · UNVERIFIED · sev **medium** · effort M · class B

**Finding.** REGRESSION of the fixed R18-F01/R19-F02/FULLREVIEW-07-16 class: ARCHITECTURE.md (canonical, 'Last updated 2026-07-28') again carries materially false operational claims — worst, the budget tier mapping '1=coaches, 2=website AI' is the PRE-ADR-125 order that budget_guard.py explicitly inverted (live: 1=internal AI, 2=coach/reader narratives, 3=website_ai), so an incident responder during the current STANDING tier-2 window would misdiagnose which surfaces are legitimately paused. Also: the S3-trigger table lists deleted apple-health-ingestion as live; 'No role has dynamodb:Scan' is false (3 deliberate grants); secrets table says 21 (live: 25, with 'notion' listed SOFT-DELETED while live); the prose email-cadence table is an hour off both guarded tables (daily-brief '11:00 AM' vs live cron 17:00Z=10:00 PDT); cost section says 'tier 1, ~$80' vs live tier 2 / $88.32 MTD / July $115 window; '~50 alarms' vs 79 live.

**Evidence.** docs/ARCHITECTURE.md:89,191,283,350,356,383 vs lambdas/budget_guard.py:17-24,115,166; aws lambda get-function apple-health-ingestion → ResourceNotFoundException; cdk/stacks/role_policies.py:2204,2219,2257 (Scan grants: data-export, delete-user-data, reconciliation); aws secretsmanager list-secrets = 25 incl. life-platform/notion; aws events list-rules: daily-brief cron(0 17), anomaly cron(5 15); aws ce get-cost-and-usage Jul = $88.32; SSM budget-tier = 2; describe-alarms count = 79

**Root cause.** The 07-16 accuracy pass fixed the six named instances but the guard was only partially built: scripts/check_doc_facts.py's #1205 cron-diff covers ONLY lines quoting a literal cron(...) (the prose cadence table quotes none, so it drifted free), and covers no tier-mapping, no doc-named-lambda-exists check, no secret inventory; deploy/sync_doc_metadata.py:1254 keeps secret_count as a hand literal ('live-verified 2026-07-10, not auto-discovered') that the auto-sync stamps with a fresh 'Last updated' date — manufactured freshness on a 17-day-stale fact.

**Regression guard.** Extend check_doc_facts.py (the existing CI gate that already owns this class): (a) parse budget_guard.FEATURES and diff against any doc line stating tier semantics; (b) assert every function name in an ARCHITECTURE.md table exists in the CDK AST; (c) auto-discover secret_count via list-secrets at sync time or drop it from the stamped line. Process fix per fix-class B: the gate extension IS the change; editing the doc alone repeats 07-16.

**Path-to-A step.** One PR: fix the six drifted claims + land the three check_doc_facts.py extensions above (CI-rent only, an existing gate — ADR-103 frame: deploy-guardrail class, earned by three recurrences).

#### cto-3 · UNVERIFIED · sev **medium** · effort S · class A

**Finding.** qa-smoke-warnings alarm is structurally permanently red: WarnCount has been 4-11 every single day for 9+ days (chronic 'optional / no record today' timing warns for withings/strava/notion/supplements plus the standing cache-warm warn) against a >=1 threshold, so the alarm can never clear — red has stopped meaning anything on the alarm board.

**Evidence.** CW LifePlatform/QaSmoke WarnCount daily Maximum 07-19→07-27: 11,8,8,4,6,6,7,11,7; alarm qa-smoke-warnings in ALARM since 2026-07-18T21:38 PT (threshold 1.0, 86400s Maximum); /aws/lambda/life-platform-qa-smoke logs: '[QA] WARN Data Freshness / DDB:withings … no record (optional)' recurring every run

**Root cause.** lambdas/operational/qa_smoke_lambda.py classifies known-recurring timing/optional conditions as WARN and emits them into the same WarnCount metric the monitoring_stack alarms at >=1 — the classification and the threshold are wrong for a metric whose honest daily baseline is 4-11, regardless of phase or incident.

**Regression guard.** Per ADR-105 (thresholds from personal variance): derive the WarnCount threshold from the metric's own trailing baseline, or split 'expected-recurring' warns into a non-alarmed metric; keep the load-bearing 24h Maximum window untouched (memory: qa-smoke alarm window is load-bearing). A unit test asserting the chronic-warn set does not increment the alarmed metric. Owner: qa-smoke layer (ADR-076 layer 2) + monitoring_stack.

**Path-to-A step.** Reclassify chronic optional/timing warns out of the alarmed WarnCount (or set the threshold above the measured baseline) so a red qa-smoke-warnings alarm regains meaning — no new machinery, a threshold/classification correction.

#### cto-4 · UNVERIFIED · sev **medium** · effort S · class B

**Finding.** No reconcile loop maps standing ALARM states to explanations: 6 alarms were simultaneously red on Day 1, three of them past the 72h bar (qa-smoke-warnings 9d, qa-paused-by-budget 9d, ai-canary recurrent since 07-19), yet the session ledger records exactly one incident row (budget tier 1→2) — only qa-paused-by-budget is genuinely self-explaining by name. Nothing owns 'an alarm red >72h must cite an incident row or issue #', which is how the canary's false positives and the unclearable warn alarm sat unactioned.

**Evidence.** aws cloudwatch describe-alarms --state-value ALARM → 6 alarms (StateUpdated 07-18 ×2, 07-24 ×2, 07-27 ×2); CLAUDE.md session block 'Incidents: 1 row (budget tier 1→2, by-design)'; gh issue list searches for canary/qa-smoke/alarm → no open issue covering any of the three standing reds

**Root cause.** Process gap, not code: the wrap ritual and /platform-review check main-green and fleet-currency but no step enumerates describe-alarms --state-value ALARM and demands each red map to an explanation. The two real fixes above remove today's noise, but without the loop the next chronic red accumulates identically (this is the rubric's own C-anchor clause, observed live).

**Regression guard.** A one-line wrap/review gate (the existing (e)-series wrap gates are the precedent, #1863): list alarms in ALARM; each either cites an incident/issue # or the wrap fails honest. Owned by the /wrap skill + /platform-review checklist — zero standing infra, attention-rent only.

**Path-to-A step.** Add the 72h-alarm reconcile line to the wrap gates — process only, no AWS resources, no cost.

**Path to A (grader's ranked actions):**

1. Fix the canary's grounding universe: the grounded-digits check must compare against the same grounding payload site-api-ai serves (or a full-vitals canonical_facts), with a precision fixture in tests/ asserting true-number answers never alarm — corrects an existing load-bearing sensor, no new machinery.
2. One PR that fixes the six verified ARCHITECTURE.md drift instances AND extends scripts/check_doc_facts.py with: budget-tier-semantics diff against budget_guard.FEATURES, doc-named-lambda-exists-in-CDK check, and auto-discovered (or unstamped) secret_count — completing the guard the 07-16 path-to-A asked for (ADR-103 frame: deploy-guardrail class, earned by three recurrences of this exact class).
3. Reclassify chronic optional/timing qa warns out of the alarmed WarnCount metric (or derive the threshold from the metric's measured baseline per ADR-105); leave the 24h Maximum window untouched — makes qa-smoke-warnings red mean something again.
4. Add a 72h-alarm reconcile line to the /wrap gates: every alarm in ALARM must cite an incident row or issue #, or the wrap reports the shortfall honestly — attention-rent only, zero standing infra.
5. At the 08-01 ceiling auto-revert, verify tier recomputes against $85 and the qa-paused-by-budget + tier-2 pauses lift cleanly (one-time check, calendar-anchored — the dated-trigger discipline the PROPORTIONALITY ledger already models).

**Coverage (what this lens did NOT examine).** NOT examined: per-lambda DLQ wiring across all 105 live functions (verified the shared DLQ empty + digest drain only); us-east-1 alarm set (web stack) beyond stack existence; IAM policy simulation of any role (read role_policies.py source + trusted the drift-guarded deploys, stacks last updated 07-26/27); the #1859 us-east-1 rollback machinery and the 2026-03-30 PITR drill were not exercised; EventBridge cron-by-cron doc diff limited to daily-brief/anomaly (the two internal contradictions) — I did not re-verify the full compute/email cron table; CloudTrail data-event delivery; the exact cause of qa-smoke FailCount=2 on 07-24..26 (inferred to be the Notion schema drift fixed by PR #1888, not log-verified); the 99-doc vs 105-live Lambda count delta was not enumerated function-by-function; cost lens dollars beyond the single MTD figure ($88.32) used to sanity-check the governor.

**Lens notes.** DEDUP: no findings overlap the do-not-refile list or any open issue (searched canary/qa-smoke/ARCHITECTURE/alarm/secrets/grounded — zero hits on these defects); the qa-smoke FailCount 07-24..26 run traces to the Notion template-schema drift closed by PR #1888/#1840 — a worked detect→fix loop, credited not filed. PHASE-AWARE: budget tier 2 standing red (qa-paused-by-budget) is by-design until 08-01 and treated as correct; compute-pipeline-stale (fired on 07-26 pre-genesis data) and ingest-auth-unhealthy-24h (metric recovered to 1.0 by 07-27 11:00 PT after ~60h unhealthy) are reset-churn/self-recovered and clear within their 24h windows — noted, not filed; qa-smoke's Day-1 copy ('Character sheet absent — wiped at reset… pre-start/Day-1 grace') shows genuinely phase-aware sensor design. DATA-MATURITY caveat on finding 1: the Day-1 wipe thinned canonical_facts to 3 keys, worsening the canary's precision — but the 07-22 firing predates the reset, so the defect is standing (dissent-worthy: a lifecycle-only reading would misclassify it as class B). CREDITS toward the grade: all live-state protections reproduce (DDB deletion-protection+PITR, S3 delete-deny, 9 stacks incl. Web in us-east-1, digest drain 7/7 days 0 errors, DLQ 0); the PROPORTIONALITY ledger matches live on every row checked (remediation shadow in SSM, chronicle-podcast zombie exists unscheduled with its dated trigger, dated podcast re-check 2026-10-27) — the ledger discipline is A-caliber; the budget governor is doing exactly its job at tier 2 under the July $115 window with the $85 Budgets backstop intact. Minor unfiled: PROPORTIONALITY says '75 tools' vs ARCH/CLAUDE.md 76 (one-off count skew); ARCH line 7 '143 ADRs (ADR-001 → ADR-145)' reads oddly but is plausibly two retired numbers. Prior CTO lens 07-16: B+ — the six named doc claims WERE fixed and the #1205 cron guard WAS built; the regression finding here is the guard's coverage boundary, not a null response to the last review.

### principal — Code health — **A-**

*Trend: = held at A-.*

**Verifier on the grade:** All four findings survive in substance (2 confirmed, 2 adjusted on root-cause/framing only), and since they are uniformly low/medium-severity tooling-hygiene gaps with existing partial guards rather than production defects, they still support the proposed A- grade.

#### principal-1 · ADJUSTED · sev **medium** · effort S · class A

**Finding.** The CI quality-gate toolchain has drifted from requirements-dev.txt: the ENFORCED mypy gate installs mypy==2.1.0 (ci-lint.yml:75) while requirements-dev.txt:29 pins 2.3.0, hypothesis is 6.161.2 in CI (ci-test.yml:42) vs 6.161.5 (requirements-dev.txt:11), and pytest/pytest-cov/boto3/botocore are entirely UNPINNED in ci-test.yml:42 while pinned in requirements-dev — so the blocking type gate and the test runner can behave differently in CI than for a dev running the documented local commands. This is a REGRESSION of the pin parity explicitly verified at the 2026-07-16 baseline ('tool pins black/ruff/mypy match requirements-dev.txt exactly'); the CQ-01 comment discipline (requirements-dev.txt:22) covers only black+ruff and still points at 'ci-cd.yml' though the pins moved to ci-lint.yml in the #1655 split.

**Evidence.** .github/workflows/ci-lint.yml:75 ('pip install mypy==2.1.0') + ci-test.yml:42 ('pip install pytest pytest-cov boto3 botocore hypothesis==6.161.2') vs requirements-dev.txt:6-33 (pytest==9.1.1, pytest-cov==7.1.0, hypothesis==6.161.5, mypy==2.3.0, boto3==1.43.56); divergence introduced by Dependabot commit 39f77423 (2026-07-18, 'Updates mypy from 2.1.0 to 2.3.0' in requirements-dev only) and carried into ci-lint.yml by 203d6d1f (2026-07-24)

**Root cause.** Workflow files duplicate tool pins as inline literals that Dependabot cannot see or bump — Dependabot PR #1315 (39f77423) updated requirements-dev.txt's dev-tooling group while ci-cd.yml's (now ci-lint.yml/ci-test.yml's) hand-maintained copies stayed frozen; no guard asserts the two pin surfaces agree (CQ-01 is a comment, not a test, and names black/ruff only)

**Regression guard.** A pin-parity guard test in the test_coverage_floor_ratchet.py family: parse pip-install lines in .github/workflows/ci-*.yml and assert every pinned tool equals requirements-dev.txt's pin (and that pytest/pytest-cov are pinned at all) — owned by the unit-test QA layer, which already hosts the identical three-way-literal-agreement pattern for the coverage floor

**Path-to-A step.** Make requirements-dev.txt the single pin source: workflows install via `pip install -r requirements-dev.txt` (or a constraints file), or land the pin-parity guard test so the next Dependabot bump reds CI instead of silently forking the gate toolchain — ADR-103 cost: one offline test, zero runtime/standing machinery

**Verifier (ADJUSTED).** The drift itself reproduces exactly: ci-lint.yml:75 installs mypy==2.1.0 vs requirements-dev.txt mypy==2.3.0 (Dependabot 39f77423 on 2026-07-18 bumped requirements-dev only, confirmed via git show); ci-test.yml installs pytest/pytest-cov/boto3/botocore unpinned + hypothesis==6.161.2 vs 6.161.5. No duplicate issue found. But the finding's root cause misstates the guard state — CQ-01 is NOT merely a comment.

**Corrected cause/evidence.** A pin-parity guard test ALREADY exists — tests/test_ci_pin_consistency.py (self-labeled 'CQ-01: ... This test is the single-source guard'), and it is already #1655-aware (it reads ci-cd.yml + ci-lint.yml + ci-test.yml). The drift escaped because its _GATED_TOOLS tuple is scoped to ('black', 'ruff', 'playwright') only — mypy, hypothesis, pytest, pytest-cov, boto3/botocore are outside the guard's scope. The fix is extending _GATED_TOOLS (plus a pinned-at-all assertion for the test runner), not creating a new guard family; the proposed test_coverage_floor_ratchet.py-family guard would duplicate existing machinery.

#### principal-2 · CONFIRMED · sev **low** · effort M · class A

**Finding.** Invariant-helper canonicalization stopped at 1 of the rubric's 3 invariants: float-to-Decimal got the full treatment (#1207 + D5 guard) but (a) Pacific-'today' is still re-derived inline in 7+ modules despite pacific_time.py declaring 'This is the single source of truth — do not re-derive', and (b) ISO-parse is forked as the .replace('Z','+00:00') idiom at 27 inline sites plus 2 private defs with DIVERGENT naive-timestamp semantics — site_api_freshness._parse_iso_ts backfills tzinfo=UTC while whoop_lambda._parse_iso leaves a naive datetime naive, so _utc_day's astimezone() would interpret a tz-less timestamp as runner-LOCAL time (latent: Whoop payloads currently always carry Z/+00:00). No D5-style guard prevents the next Pacific fork from hardcoding UTC-8, the exact past defect three of these call sites' own comments memorialize.

**Evidence.** lambdas/pacific_time.py:17-18 (single-source declaration) vs inline ZoneInfo('America/Los_Angeles') today-derivations at lambdas/vacation_fund.py:94, reader_truth_qa.py:114, operational/qa_smoke_lambda.py:71, compute/dashboard_refresh_lambda.py:641, ingestion/notion_lambda.py:802, mcp/core.py:358, output_writers.py:1305; lambdas/ingestion/whoop_lambda.py:485-500 (_parse_iso no tzinfo backfill, _utc_day astimezone) vs lambdas/web/site_api_freshness.py:376-382 (backfills UTC); grep count 27 inline Z-replace sites

**Root cause.** Phase-4.2/#1207 consolidation scoped its structural guard (tests/test_ddb_patterns.py:371 D5) to floats_to_decimal only; pacific_time.py and the ISO idiom rely on docstring convention with no enforcement, so forks accreted after the module shipped (mcp/core.py and qa_smoke both post-date it, and the mcp bundle DOES include pacific_time via the #781 tree so no import barrier justifies them)

**Regression guard.** Extend the existing D5 structural-test pattern in tests/test_ddb_patterns.py: no inline ZoneInfo('America/Los_Angeles') today-derivation outside lambdas/pacific_time.py, and no private def matching _parse_iso* outside the canonical helper — same AST/regex guard shape already proven for the Decimal invariant

**Path-to-A step.** Add parse_iso_utc() to pacific_time.py (adopting the tzinfo-backfill semantics), repoint the 2 private defs and the today-derivation sites at the canonical helpers, and extend the D5 guard to both invariants — zero standing cost since pacific_time.py already ships in every bundle (#781)

**Verifier (CONFIRMED).** Independently reproduced every evidence point: all 7 cited inline ZoneInfo('America/Los_Angeles') today-derivations exist at the exact cited lines (vacation_fund.py:94, reader_truth_qa.py:114, qa_smoke_lambda.py:71, dashboard_refresh_lambda.py:641, notion_lambda.py:802 (+495), mcp/core.py:358, output_writers.py:1305) despite pacific_time.py:17-18's explicit 'single source of truth — do not re-derive'; my grep counts exactly 27 Z-replace sites; read both private parsers and confirmed the divergent naive-timestamp semantics — whoop_lambda._parse_iso returns naive datetimes as-is and _utc_day's astimezone() would interpret them as runner-local, while site_api_freshness._parse_iso_ts backfills tzinfo=UTC; the D5 guard in tests/test_ddb_patterns.py:371 covers only the float-to-Decimal walker. No open/closed issue duplicates this; no ADR sanctions the forks.

#### principal-3 · CONFIRMED · sev **low** · effort S · class A

**Finding.** The engine-doc --strict gate runs blocking in CI but only advisory locally, and it red-walled main TWICE in one day (2026-07-27) on ordinary engine-source merges — a gate-parity gap where the documented local workflow cannot reproduce the CI verdict, currently mitigated only by an operator memory reflex, not a structural check.

**Evidence.** gh run 30308481573 and 30305989798 (both main pushes 2026-07-27, lint/Lint+Syntax Check failed): log shows 'engine-doc source drift (--strict): docs/engines/READINESS.md verified 2026-07-26 but lambdas/compute/daily_metrics_compute_lambda.py committed 2026-07-27' then exit 1; both fixed same-day (green ea4a57f5); memory file reference_doc_index_strict_ci_only.md records the lesson as reflex-only; gh issue searches 'engine-doc'/'check_doc_index' return no open issue for parity

**Root cause.** scripts' check_doc_index --strict flag is passed only by the ci-lint.yml invocation; the local/pre-merge invocation path omits it, so an engine-source merge whose author forgets the manual reflex discovers the drift only post-merge on main

**Regression guard.** Run the --strict form in the pre-push/pre-merge local path (or a deploy-critical-lane structural test asserting engine-doc verified-dates are not older than their source files at HEAD), so the red fires before the merge — owned by the lint QA layer where the gate already lives

**Path-to-A step.** One-line parity: make the local check_doc_index invocation default to --strict (or add it to the pre-push hook), converting the encoded memory lesson into a structural gate — no new machinery, same script, earlier in the lifecycle

**Verifier (CONFIRMED).** Reproduced both cited failures myself: gh run 30305989798 and 30308481573 (both main pushes 2026-07-27, lint job) show the verbatim log line 'engine-doc source drift (--strict): docs/engines/READINESS.md verified 2026-07-26 but lambdas/compute/daily_metrics_compute_lambda.py committed 2026-07-27' (plus HYPOTHESIS.md/SCORING.md siblings); next main run ea4a57f5 green same day. Verified --strict is passed only by ci-lint.yml:282 and docs-ci.yml:87 while scripts/check_doc_index.py's default invocation leaves gate 4 print-only ('--strict # gate 4 drift also FAILS'), and no pre-commit hook or local path runs it. gh issue search for 'check_doc_index strict'/'engine-doc' returns only closed #1590/#973 (different scope: creating the gate, not local/CI parity) — not filed, not on the do-not-refile list, mitigation is memory-reflex only per the handover.

#### principal-4 · ADJUSTED · sev **low** · effort S · class B

**Finding.** The unit-test suite is past its own wall-clock budget and the self-reminding ratchet is firing unactioned: the green main run's Unit Tests job took 520s against the 480s budget (advisory ::warning:: emitted), after the suite grew 5108 to 8059 tests in the 12 days since baseline — the #1349 reminder achieved detection but no one has made the deliberate optimize-or-raise decision, so a standing warning is normalizing on every push (the exact decorative-gate erosion the coverage-floor lesson was about).

**Evidence.** gh run view --job 90162430202 (green main run 30322818528, 2026-07-28): '##[warning]Unit Tests job took 520s, over the 480s budget (40s over). Suite wall-clock has been climbing (157s -> 294s over 6 days, #1349)'; suite counts 8011 CI / 8059 local vs 5108 at the 07-16 baseline; local full run 139.6s uninstrumented, CI coverage-instrumented pass 293s; gh issue searches 'suite duration'/'slow tests' return no open issue

**Root cause.** Organic test growth (~2900 new tests in 12 days across the diary-360/backlog-PM/social-membrane waves) pushed the coverage-instrumented job past the 480s budget set by #1349; the warner (scripts/coverage_gap_warn.py --duration-budget-seconds 480) is detection-only and its output has no consumer obligated to act

**Regression guard.** The guard exists (the #1349 duration warner) — the missing piece is the PROCESS: a wrap-gate/backlog rule that a standing CI ::warning:: on green main gets triaged into an issue or a deliberate budget raise within a session, so advisory signals cannot silently normalize

**Path-to-A step.** Spend one session slot on `pytest --durations=25`, either trim/parallelize the outliers or raise the budget to a deliberate new number with rationale in the workflow comment — and add the standing-warning triage rule to the wrap checklist so the next breach self-escalates (pure process, zero standing cost)

**Verifier (ADJUSTED).** The core facts reproduce: job 90162430202 on green main run 30322818528 (d89686a0, 2026-07-28T02:20Z) carries the verbatim annotation 'Unit Tests job took 520s, over the 480s budget (40s over)...'; #1349 (the warner) and #1847 (the earlier runtime blowup) are both CLOSED and no open issue tracks the current breach. But the 'standing warning normalizing on every push' framing is wrong.

**Corrected cause/evidence.** This is the breach's FIRST occurrence, not a normalized standing warning: the immediately prior green main run (30308988990, job 90120494450, ~21:58Z 2026-07-27) emitted NO duration-budget warning — the suite crossed 480s only on the latest completed run, hours before this verification, at the tail of the 17-PR day. The substantive point survives in weakened form: a fresh over-budget signal exists with no triage decision yet (the session wrapped without filing it), so the optimize-or-raise decision is genuinely pending — but there is no evidence of the multi-run erosion/normalization pattern the finding alleges, which lowers the urgency of the process-rule half of the fix.

**Path to A (grader's ranked actions):**

1. Single-source the CI gate toolchain pins: install from requirements-dev.txt (or a constraints file) in ci-lint.yml/ci-test.yml, or add a pin-parity guard test in the test_coverage_floor_ratchet.py family asserting workflow pip-install literals equal requirements-dev pins (and that pytest/pytest-cov are pinned at all); fix the stale CQ-01 pointer ('ci-cd.yml' -> ci-lint.yml) and pyproject's 'ruff 0.14.0' header comment in the same PR — ADR-103: one offline test, zero runtime cost
2. Finish invariant canonicalization for the remaining 2 of 3 rubric invariants: parse_iso_utc() in pacific_time.py with tzinfo-backfill semantics, repoint whoop_lambda._parse_iso + site_api_freshness._parse_iso_ts and the 7 inline Pacific-today derivations, and extend the proven D5 structural-guard pattern (tests/test_ddb_patterns.py) to cover both — pacific_time.py already ships in every bundle (#781), so this is pure consolidation
3. Make the engine-doc --strict gate reproducible pre-merge: default the local check_doc_index invocation to --strict (or pre-push hook), converting the memory-reflex mitigation into structure so the 07-27 double main-red class cannot recur
4. Act on the standing suite-duration warning: pytest --durations=25, trim or parallelize the outliers or deliberately raise the 480s budget with rationale, and add a wrap-gate rule that any standing ::warning:: on green main gets triaged within a session
5. When the next test wave lands, ratchet the coverage floor 47->~50 through the existing three-literal + RATCHET_FLOOR mechanism (measured 54.62% leaves headroom; the gap-warn threshold is 10pts so the system will self-remind at ~57%) — keep the ratchet cadence alive rather than waiting for the #1658 70% end-state

**Coverage (what this lens did NOT examine).** NOT examined: mypy itself was not executed (not installed locally; I would not mutate the environment) — I verified the clean-set single-sourcing structurally (ci-lint.yml:82 reads tests/mypy_clean_set.py, so list drift is impossible) but did not reproduce the type-check verdict, and the 2.1.0-vs-2.3.0 behavioral delta is asserted from version divergence, not a differential run. Coverage was measured from the green main CI run log (54.62%), not locally (pytest-cov absent). Of the 262 test files touched since 07-16, only a heuristic wall-clock scan (hardcoded-2026-date + unmocked now() co-occurrence) was run, not a full read; mutation-level assertion strength and flake detection (single local run) were not assessed. The 77 local skip reasons were not individually re-audited this run (counts consistent with the baseline's audited creds/playwright classes). cdk/ stack-code health, tests/js/ (site JS tests), the creds-gated integration suite (by design), deployed-bundle byte content vs repo, and the MCP tool-count drift check were not covered. The baseline's unverified suspicion of Python 3.14-local vs 3.12-CI masked discrepancies remains unhunted (suite green on both). Prior-cycle leak hunting (the #1194 class) has no direct surface in this lens; nothing suspicious appeared in test/gate land.

**Lens notes.** DEDUP: god-modules (site_api_intelligence 2560 / site_api_coach 2538 / daily_brief_lambda 2481 / mcp registry 2409 lines) -> open #1654, reported as context only, and its decomposition is demonstrably in progress (site_api_data.py 4184->338 since baseline, mypy.ini records slice 3); coverage 70% end-state -> #1658 (my measured 54.62% is input to it); lambdas/ packaging -> #1653 (reserved session); mypy-strict expansion -> #1656; branch protection -> #1662 gate:owner; the duration warner itself was #1349 (shipped — my finding 4 is about the unactioned breach, not the mechanism); Dependabot PRs #1778-#1780 are owner-gated but are NOT the pin-drift finding (that drift is CI-literal vs requirements-dev, invisible to Dependabot by construction). REGRESSION VERDICT ON THE 07-16 BASELINE: all 5 prior findings remediated WITH guards (floor ratchet test, D5 decimal guard, test_no_dead_intelligence_functions, mypy.ini comment fix, site_api_data decomposition) — the remediation-with-regression-guard discipline is genuinely working; the one regressed surface is tool-pin parity (finding 1), which had no guard, proving the pattern: everything guarded held, the one unguarded verified-state drifted within 2 days (Dependabot 07-18). Main-red events 07-27 were the CI-only --strict gate (finding 3), fixed same-day — not 'red main tolerated'. Run 30324990970 sits 'waiting' on the production approval environment — normal, not stuck. test_iam_secrets_consistency's dropbox INFO warning is pre-existing and self-describing. DATA-MATURITY: this lens is cycle-independent; nothing graded here penalizes Day-1 emptiness. DISSENT-WORTHY: the full `test` job being non-gating for deploy (ADR-117, deploy gates on the 1429-test deploy_critical lane) remains a documented, reasonable tradeoff I did not file — but the lane's inclusion criteria deserve a re-look as the suite doubles, since the gap between 'reds main later' and 'blocks this deploy' widens with every test wave.

### aiq — AI content integrity — grounded generation (ADR-104), rigor bar (ADR-105), phase/day-awareness, hallucination surface, tombstone read semantics, coach quality gate (ADR-108), tier-2 pause honesty — **B**

*Trend: ▼ **down from B+**.*

**Verifier on the grade:** All six findings survive (four confirmed outright, two with corrected root causes, and finding 4 upgraded from latent to an active Day-1 prior-cycle leak feeding finding 0), so the surviving set fully supports the proposed B — arguably with more force than the original write-up, since the dominant historical defect class (#1194 tombstone leak-through) recurred live on Day 1.

#### aiq-1 · ADJUSTED · sev **high** · effort M · class A

**Finding.** Live Day-1 public surface serves phase-wrong experiment-age framing: /api/ai_analysis?expert=nutrition states 'Zero food logs in seven days of an experiment' when the cycle is 1 day old — and no gate class can catch it (spelled-out 'seven' is invisible to the digit-only number regex, 7 is in _BENIGN_NUMBERS anyway, and the stale_phase gate matches only 'Day N' tokens).

**Evidence.** curl https://averagejoematt.com/api/ai_analysis?expert=nutrition returned generated_at 2026-07-27T14:00:53Z with the quoted text; lambdas/intelligence/ai_expert_analyzer_lambda.py:265 computes days_in_experiment=1 and :293 stamps 'experiment days 1-1' into the same prompt; lambdas/grounded_generation.py:70 (_NUM_RE=\d+), :78 (_BENIGN_NUMBERS incl. 0-12), :490 (_DAY_N_RE 'day N' only)

**Root cause.** ai_expert_analyzer_lambda feeds a 7-day nutrition-log window alongside Day-1 experiment framing and its grounding closure (lines 1297-1300) omits generation_date_iso/start_date_iso entirely; grounded_generation has no day-span finding class and normalizes neither word-numbers nor 'N days of/into the experiment' framings

**Regression guard.** Extend tests/test_baseline_freshness_gate.py + test_prop_grounded_generation.py with day-span/word-number cases; the ai-quality-canary (deterministic leg) should probe experiment-age framing on /api/ai_analysis — owning layer: unit tests + the #385 canary

**Path-to-A step.** Add a day-span class to baseline_freshness_findings (normalize spelled-out numbers, match 'N days/weeks of/into the experiment' against expected_day) and pass the cycle params in the analyzer's findings_fn — extends the existing ledgered pure harness, no new subsystem (ADR-103 clean)

**Verifier (ADJUSTED).** Symptom fully reproduces: my curl of /api/ai_analysis?expert=nutrition returns 'Zero food logs in seven days of an experiment' plus elena_quote 'hasn't recorded a single meal in seven days' with days_in_experiment=1 (generated_at 2026-07-27T14:00:53Z). Gate-blindness verified in current code: _NUM_RE=\d+ (grounded_generation.py:70) misses spelled-out 'seven', 7 is in _BENIGN_NUMBERS (range 0-13, :77-79), _DAY_N_RE matches only digit 'day N' (:490), and the analyzer's grounding closure (:1295-1300) passes only facts+allowed — no generation_date_iso/start_date_iso. But the stated root cause is wrong: on Day 1 gather_data_for_expert clamps d30 = max(today-30, EXPERIMENT_START) (:264), so the nutrition packet was the empty 'No nutrition data available' branch (:310-317) — NO 7-day nutrition-log window exists in the Day-1 input.

**Corrected cause/evidence.** The 'seven days' entered via (a) build_prompt's week framing ('This is Week {1} of the experiment... now day {1}', ai_expert_analyzer_lambda.py:863) inviting week≈seven-days extrapolation, and — more concretely — (b) the tombstone-blind prior-analysis get_item at :1077 (finding 4): restart_intelligence_wipe.py:133 tombstones ai_analysis in 'all' mode IN PLACE (UpdateItem, content preserved), so the cycle-10 EXPERT#nutrition record — whose closing state was literally a week of zero food logs (all July cycle-10 predictions are 'once food logs start coming in') — was present tombstone=true at 14:00:53Z and its first 300 chars were injected as _prior_analysis_summary into the Day-1 prompt. The gate-gap analysis (word-numbers invisible, 7 benign, day-N-only phase regex, no cycle params passed) is confirmed as why nothing caught it. Sev high stands: this is the #1194 hunt-order class live on a public surface.

#### aiq-2 · CONFIRMED · sev **medium** · effort M · class A

**Finding.** A coach publicly self-grades a prediction verdict with no evaluated record behind it: /api/coach_analysis?domain=nutrition declares 'I called lunch wrong… That's a prediction miss, and I'm logging it as one' while every stored PREDICTION# is status=pending, the same payload reports prediction_count: 0, and the narrative itself admits 'I have zero food logs' — an LLM verdict with no deterministic computation before it (ADR-105 inversion), actively invited by the thread-prompt rules.

**Evidence.** curl /api/coach_analysis?domain=nutrition (generated_at 2026-07-27T17:01:15Z, quoted text + prediction_count 0); aws dynamodb query COACH#nutrition_coach PREDICTION# → 8 records all status=pending; lambdas/intelligence_common.py:1341 prompt rule 'If a prediction resolved: explicitly call it out. "I predicted [X]. I was [right/wrong]."'

**Root cause.** build_thread_prompt_block (lambdas/intelligence_common.py:1338-1345) instructs coaches to narrate prediction outcomes, but no gate class ties outcome-framed self-claims ('prediction miss/hit', 'I was right/wrong') to an evaluated (non-pending) prediction record supplied in the generation brief — the digit gates have nothing to check and ungrounded_behavioral only covers Matthew's behavior, not the coach's own track-record claims

**Regression guard.** New finding class + unit test (pattern of tests/test_ungrounded_behavioral_gate.py): outcome-framed claim with only-pending predictions must flag; owning layer: coach-quality-gate / grounded_generation composed into the coach V2 findings_fn

**Path-to-A step.** Ship a prediction-outcome-claim gate: deterministic regex for outcome framings, allow-listed against evaluated predictions in the brief, wired through regen_once on coach V2 and the expert analyzer

**Verifier (CONFIRMED).** My reproduction: curl /api/coach_analysis?domain=nutrition serves 'I called lunch wrong... That's a prediction miss, and I'm logging it as one' (generated_at 2026-07-27T17:01:15Z, regeneration_paused=true). My DDB query on COACH#nutrition_coach PREDICTION# (362 rows): ALL 18 current-cycle non-tombstoned records are status=pending (incl. the three written in the same 17:01:15Z invocation); the only confirmed/refuted records are June cycle-10 tombstones (phase=pilot, tombstone=true). The prompt rule reproduces verbatim at intelligence_common.py:1341: 'If a prediction resolved: explicitly call it out. "I predicted [X]. I was [right/wrong]."'. No deterministic evaluation preceded the self-graded 'miss' — ADR-105 inversion confirmed. Two evidence corrections that don't change the verdict: the payload contains NO prediction_count field (I enumerated every key), and the current-cycle pending count is 18, not 8 — the core claim re-derives independently either way. No duplicate open issue found.

#### aiq-3 · CONFIRMED · sev **medium** · effort M · class A

**Finding.** Cycle-freshness (#1691) and ungrounded-behavioral (#1699) gate coverage is convention, not structure: the optional params are passed by only 3 callers (coach V2, review-pack x2); the expert analyzer, chronicle, state_of_matthew, memoir, field-notes and debrief surfaces run grounding without them, and no test enforces which reader-facing surface must pass which gate class — finding 1 is the live consequence.

**Evidence.** grep generation_date_iso/available_logs across lambdas/: only ai_calls.py:2036-2071, review_pack_ranker.py:172, emails/ai_review_pack_lambda.py:228; ai_expert_analyzer_lambda.py:1297-1300 calls grounding_findings(facts, allowed) with no cycle params; eval_retention.py:66 SURFACES names 6 surfaces but no coverage test binds gate params to surfaces

**Root cause.** grounded_generation.grounding_findings' opt-in optional-param design (deliberate for backward compat, lines 786-859) with no registry/wiring test asserting per-surface gate coverage — each new gate class must be hand-wired into each caller and nothing fails when one is missed

**Regression guard.** A wiring-coverage-style test (pattern: tests/test_wiring_coverage.py) enumerating reader-facing AI surface modules and asserting each passes the applicable optional gate params; owning layer: unit-test CI gate

**Path-to-A step.** Make gate coverage structural with the registry test so a new AI surface cannot ship half-gated

**Verifier (CONFIRMED).** My grep across lambdas/ reproduces the coverage map exactly: only ai_calls.py (:2038, :2068-2071), review_pack_ranker.py:172, and emails/ai_review_pack_lambda.py:228 pass generation_date_iso/available_logs, while grounding_findings/regen_once callers also include ai_expert_analyzer_lambda (closure at :1295-1300 passes only facts+allowed), state_of_matthew_lambda, wednesday_chronicle_lambda, chronicle_prompt, daily_debrief_lambda, coach_history_summarizer, site_api_ai_lambda — none passing cycle/behavioral params. grounding_findings' signature is all-optional keywords (grounded_generation.py:786-797), confirming the opt-in design. eval_retention.py:66 SURFACES tuple reproduces verbatim (6 surfaces), and the tests/ directory contains no registry/coverage test binding gate params to surfaces (test_wiring_coverage.py covers MCP tools only; the gate tests test the gates, not the wiring). Finding 0 is indeed the live consequence. Not on the do-not-refile list.

#### aiq-4 · ADJUSTED · sev **low** · effort S · class A

**Finding.** Two public surfaces state contradictory Day-1 sleep durations: the integrator's weekly_priority narrates 'a 7.5-hour sleep' while /api/pulse_history and /api/observatory_week report 8.9h for the same night — the number gate proves 7.5 was in the model's input, meaning two prompt packets carry different sleep-duration definitions with no disclosure.

**Evidence.** curl /api/weekly_priority ('a 7.5-hour sleep', generated 2026-07-27T14:02:36Z) vs curl /api/pulse_history (2026-07-27 sleep_hours 8.9) and /api/observatory_week (8.9 hrs)

**Root cause.** the integrator-synthesis data packet in ai_expert_analyzer_lambda uses a different sleep field than the platform's canonical duration ((in_bed - awake), the 8.9h served by pulse/observatory) — cross-surface numeric consistency is unowned by any gate

**Regression guard.** Cross-surface consistency probe in ai_quality_canary_lambda: the sleep-hours value in the synthesis input packet must equal the canonical daily metric for the same date; owning layer: the #385 canary

**Path-to-A step.** Canonicalize the sleep-duration field in every AI prompt packet (one field, one definition, sourced from daily-metrics-compute)

**Verifier (ADJUSTED).** The surface contradiction reproduces: /api/coach_analysis weekly_priority says 'a 7.5-hour sleep' (generated 2026-07-27T14:02:36Z) while /api/pulse_history serves sleep_hours 8.9 for 2026-07-27. But the root cause is not a different sleep-duration definition: the whoop DDB row's sleep_end is 2026-07-27T14:22:57Z — the night's record FINALIZED 20 minutes AFTER the generation — and the narrative's companion numbers (quality 86, deep 17.6%, REM 30.3%) ALL mismatch the final row (quality 83, deep 24.2%, REM 22.0%). If only the duration field differed, the stage percentages would match; they don't, proving the packet was an earlier partial-night revision of the SAME whoop record, not a divergent field.

**Corrected cause/evidence.** The integrator cron (Monday 14:00 UTC = 6am PT) generated while the sleep record was still partial (~7.5h asleep of an in-progress night; final sleep_duration_hours=8.93); the whoop hourly ingestion later revised the row upward and the narrative was never regenerated (now frozen by the tier-2 regeneration_paused state, correct per ADR-133). The defect is generation-before-data-final on a source that revises intra-day, plus no re-generation on revision — the proposed canary check (packet value == canonical at generation time) would have PASSED here and caught nothing. Sev low stands.

#### aiq-5 · ADJUSTED · sev **low** · effort S · class A

**Finding.** The expert analyzer's prior-analysis read is tombstone-blind: a raw table.get_item on EXPERT#{key} with no singleton_visible guard feeds 'Your PREVIOUS analysis said…' into Day-1 prompts — the one remaining #946-class get_item bypass in the generation path (currently benign only because the reset left those singletons absent, not tombstoned-in-place).

**Evidence.** lambdas/intelligence/ai_expert_analyzer_lambda.py:1077 (raw get_item, no visibility check) vs the fixed pattern at lambdas/coach/coach_narrative_orchestrator.py:272-289 and lambdas/web/site_api_coach.py:1567-1571; aws dynamodb get-item EXPERT#integrator_month/experiment_arc → absent (null), while COACH#nutrition_coach BRIEF# rows show the wipe's archive-in-place mode (phase=pilot, tombstone=true)

**Root cause.** ai_expert_analyzer_lambda.py:1073-1088 predates the #946 hardening and was never retrofitted with the singleton_visible predicate that closed this class in the orchestrator and site-api

**Regression guard.** Replay-#946 unit test: a tombstoned EXPERT# record must yield an empty prior_summary; owning layer: unit tests (pattern of the existing #946 regression tests)

**Path-to-A step.** One-line singleton_visible guard on the prior-analysis read (bundled with the finding-5 sweep)

**Verifier (ADJUSTED).** Code claims verified: raw table.get_item on EXPERT#{key} with no visibility check at ai_expert_analyzer_lambda.py:1077 vs the guarded patterns (coach_narrative_orchestrator._get_item :272-289 and site_api_coach.py:1567-1571, both applying singleton_visible per #946). But the 'currently benign because the singletons are absent, not tombstoned-in-place' characterization is wrong and understates the defect.

**Corrected cause/evidence.** restart_intelligence_wipe.py tombstones the ai_analysis partition in 'all' mode IN PLACE via UpdateItem (content preserved, never deleted — Interpretation B, and ai_analysis is EXPERIMENT_SCOPED per phase_taxonomy.py:280), so the cycle-10 EXPERT#nutrition record was present with tombstone=true at the Day-1 14:00:53Z generation; the unguarded read fed its wiped cycle-10 text into the live Day-1 prompt as _prior_analysis_summary (then the fresh put_item overwrote the record, which is why it now shows no tombstone attrs). The finder's EXPERT#integrator_month/experiment_arc 'absent' probes are a red herring — I reproduced their absence, but those sks simply never existed on the partition; EXPERT#nutrition is the key that mattered and it was NOT absent. This bypass was ACTIVE on Day 1 (probable vector for finding 0's 'seven days'), so severity is understated at low — it is a live #1194-class prior-cycle leak in the generation path, and the one-line singleton_visible fix plus a #946 replay test is correct.

#### aiq-6 · CONFIRMED · sev **low** · effort S · class B

**Finding.** A current-cycle PREDICTION# record on the tagger-blind COACH# partition carries no phase/cycle stamp (siblings written the same day are stamped phase=experiment) — since phase_filter admits attribute-absent rows forever, an unstamped row on a write-time-stamped partition is a seeded prior-cycle leak for the next reset, caught only by the wipe's backstop pass.

**Evidence.** aws dynamodb query COACH#nutrition_coach PREDICTION#: pred_20260727_logged_daily_protein_intake_will_meet_or created 2026-07-26T16:41:47Z has NO phase attr while 01:46Z/17:01Z siblings carry phase=experiment; lambdas/phase_filter.py:21 PHASE_FILTER_EXPRESSION admits attribute_not_exists(phase); lambdas/phase_taxonomy.py:39-45 declares COACH#* tagger-blind/write-time-stamped (#1233)

**Root cause.** one prediction writer code path (the 2026-07-26T16:41Z writer — distinct from the 01:46Z path that stamps correctly) bypasses phase_taxonomy.experiment_stamp(); the PROCESS gap is that nothing audits tagger-blind partitions for stamp-less rows between resets

**Regression guard.** Nightly qa_smoke_lambda assertion: zero rows on COACH#*/ENSEMBLE#* partitions lacking a phase attribute; owning layer: qa-smoke (layer 2 of ADR-076)

**Path-to-A step.** Fix the missing experiment_stamp() call site and add the qa-smoke stamp-completeness sweep so the class stays closed

**Verifier (CONFIRMED).** My DDB query reproduces the evidence exactly: pred_20260727_daily_calorie_intake_will_remain_at_or_b and pred_20260727_logged_daily_protein_intake_will_meet_or (both created 2026-07-26T16:41:47Z) have NO phase attribute while same-day siblings (16:13:18Z, 17:02:02Z) and 07-27 rows carry phase=experiment. PHASE_FILTER_EXPRESSION admits attribute_not_exists(#phase) (phase_filter.py:21) and phase_taxonomy declares COACH#* tagger-blind/write-time-stamped (#1233). The root-cause claim ('one writer code path bypasses experiment_stamp()') is correct, and I identified the writer: deploy/seed_genesis_preregistration.py build_predictions (~lines 470-497) constructs PREDICTION# items with pre_registered=true / pre_registered_at=2026-07-26T16:41:21Z (both unstamped rows carry exactly these attrs, matching the frozen-file seeding run) and never applies experiment_stamp(), unlike coach_state_updater._put_item (stamps at :370, phase unconditionally) and dispute_docket._stamped (:273-275) — so a fail-soft SSM hiccup is ruled out as the cause (those paths always write phase). Not documented as intentional (the seeder's WIPE_REMINDER shows scoping awareness but no stamping). Fix target is the seeder, plus the proposed qa-smoke stamp-completeness sweep.

**Path to A (grader's ranked actions):**

1. Extend baseline_freshness_findings with a day-span class (normalize spelled-out numbers; match 'N days/weeks of/into the experiment' against expected_day) and wire generation_date_iso/start_date_iso into the expert analyzer's grounding closure — pure-harness extension, no new standing machinery (ADR-103 clean)
2. Add a deterministic prediction-outcome-claim gate: outcome-framed self-references ('prediction miss', 'I was right/wrong') must resolve to an evaluated (non-pending) prediction supplied in the generation brief; wire through regen_once on coach V2 and the analyzer
3. Promote the #1691/#1699 advisory gates to regenerate-or-hold on the reader-facing coach path — the promotion hook is already documented in code (ai_calls.py:2027-2030) and the ADR-108 hold shape is already built
4. Make gate coverage structural: a wiring-coverage-style registry test binding each reader-facing AI surface to its required gate classes (freshness, behavioral, dates), so a new surface cannot ship half-gated
5. Close the residual tombstone-blind seeds: singleton_visible on the analyzer's prior-analysis get_item + a nightly qa-smoke sweep for stamp-less rows on tagger-blind COACH#/ENSEMBLE# partitions

**Coverage (what this lens did NOT examine).** Examined: grounded_generation.py in full + its property tests, ai_calls coach V2 pipeline (grounding, quality gate, freshness/behavioral advisory gates, qa_archive), coach_quality_gate enforcement path, ai_expert_analyzer context assembly, coach_narrative_orchestrator reads, phase_filter/phase_taxonomy/tombstone semantics, and live endpoints (state_of_matthew, coaches, coach_analysis, coaching-dashboard, weekly_priority, ai_analysis, pulse_history, observatory_week, receipts) plus direct DDB queries of COACH#/ai_analysis partitions. NOT examined: actual email-send content (daily brief/debrief/wednesday chronicle), the podcast/panelcast QA gates, live POST behavior of /api/ask and /api/board_ask (read-only contract — no POSTs made), memoir/field-notes/horizons live pages, the /story/ chronicle static pages in depth, OG-image text, MCP tool outputs, inter-coach dialogue and diary-reaction surfaces, state_of_matthew generation code, and CloudWatch gate-fire telemetry. No Lambda was invoked and no writes performed.

**Lens notes.** Dedup: no finding overlaps an open issue — #1687/#1691/#1699 are CLOSED (shipped deliberately as advisory with a documented promotion hook, so promotion is a path-to-A step, not a refile); #1194 is the closed historical epic; #1374 (judge error-bars) and #1383 (coach line) are adjacent but distinct. The HUNT ORDER came back clean: zero prior-cycle/tombstoned narrative found reachable on any live endpoint — every public singleton read is #946-guarded (singleton_visible + day-count staleness withhold, verified at site_api_coach.py:1567/2509/591 and live via honest-null month_rollup/experiment_synthesis) — the platform's dominant historical defect class did NOT recur on its highest-risk day. Tier-2 pause honesty is exemplary and live-verified on five surfaces (state_of_matthew available:false; receipts tier=2 with accurate semantics and the real $115 July ceiling; regeneration_paused:true disclosed on coach_analysis; 'track record accruing' on the Day-1 roster; the correlative-never-causal AI disclosure). Data-maturity caveats: the finding-1 and finding-2 INSTANCES will be overwritten by tomorrow's runs — the findings are the permanent gate blind spots, not the transient texts; coach analyses timestamped 17:01Z predate the evening tier-1→2 flip, so their existence is not a tier violation. Dr. Kai Nakamura on public bylines resolves to the_integrator in config/personas.json (not persona drift — verified). prediction_count:0 alongside 8 stored pending predictions is two prediction stores (SOURCE#coach_thread vs COACH#/PREDICTION#) disagreeing publicly — folded into finding 2's evidence. For the data-lens (not AI): /api/observatory_week says 'Avg sleep declined 0.0h vs last week' with trend 'down' on a 0.0 delta, and its Day-1 'vs last week' comparison spans the genesis boundary. Dissent-worthy: grade calibration hinged on rubric anchor C matching finding 1 exactly ('mischaracterized AI content no gate would catch') against otherwise A-grade tombstone discipline and pause honesty — B is the honest midpoint; a panel crediting the zero-leak hunt result more heavily could defend B+.

### cpo — Product & narrative arc (CPO lens) — **B+**

*Trend: = held at B+.*

**Verifier on the grade:** All five findings survive on symptoms (3 confirmed, 2 adjusted on root cause), including the high-severity superseded-baseline contradiction live on the coaching door plus the dark flagship hook and missing paused disclosure — a set fully consistent with the proposed B+ (sound machinery, real Day-1 honesty/framing gaps).

#### cpo-1 · ADJUSTED · sev **high** · effort M · class B

**Finding.** The coaching door and cockpit board read serve numerically wrong Day-1 data as the current read: Dr. Victor Reyes' live position_summary opens 'Day 1 weight is 317.61 lbs' (the superseded genesis override), Dr. Kai's weekly call says 'a 7.5-hour sleep' and Dr. Brandt cites 60%/40.8ms/64bpm — while the platform's own truth is 321.09 lb (real weigh-in), 8.9h sleep, 56%/37.8/62 on /api/vitals and Home ('321 lb now'). With coach-narrative regeneration paused at budget tier 2 until 08-01, these contradictions stand on the door's first screen for days.

**Evidence.** curl /api/coaching-dashboard → coaches[Victor Reyes].position_summary 'Day 1 weight is 317.61 lbs', analysis_generated_at 2026-07-27T17:03:12Z; aws dynamodb query withings DATE#2026-07-27 → weight_lbs 321.09, ingested_at 2026-07-28T03:05:42Z; git log -S 317.61 → commit f06b8221 'real weigh-in supersedes the genesis override — baseline 317.61 → 321.09'; curl /api/vitals → weight 321, sleep 8.9, recovery 56, hrv 37.8, rhr 62

**Root cause.** coach_narrative_orchestrator generated the Day-1 OUTPUT# records 17:00–17:05Z 2026-07-27 against the restart --override-weight-lbs baseline and pre-final wearable sync; commit f06b8221 later superseded the baseline (321.09) without any invalidation/regeneration of dependent same-day narratives, and site_api_coach.py's #802 pause (tier>=2) now blocks the refresh that would have self-healed it. PROCESS fix required: the baseline-supersede step (a sanctioned, expected restart flow) must invalidate or regenerate narratives citing the superseded figure — a correction-regen should be explicitly sanctioned as honesty spend under the tier pause (ADR-104), not just fixing this instance.

**Regression guard.** qa_smoke_lambda assertion: any served coach narrative containing a Day-1/baseline weight figure must match the live baseline within 0.5 lb (deterministic regex + compare, no LLM); restart_verify step: after an override supersede, grep all served narrative surfaces for the superseded literal. Owner: qa-smoke layer (layer 2 of ADR-076).

**Path-to-A step.** Add a narrative-invalidation hook to the override-supersede flow (deploy/restart_pipeline.py path) + the qa_smoke baseline-figure check; sanction one-shot correction regens under budget_guard tier pause for known-wrong content. ADR-103: extends existing restart + qa_smoke machinery, no new standing infra.

**Verifier (ADJUSTED).** Symptom fully reproduced live: /api/coaching-dashboard serves Reyes 'Day 1 weight is 317.61 lbs' (analysis_generated_at 2026-07-27T17:03:12Z) and Kai's '7.5-hour sleep' while DDB withings DATE#2026-07-27 = 321.09 (my query), /api/vitals = 321/8.9h/56/37.8/62, Brandt cites 60%/40.8/64, SSM budget-tier = 2 so the refresh is paused until 08-01. But the root cause's sequencing is wrong: commit f06b8221 landed 2026-07-27 16:12Z — BEFORE the 17:00–17:05Z narrative generation — and its message states DDB PROFILE#v1 + S3 configs were updated live at that time, so the narratives were not 'generated then later superseded'.

**Corrected cause/evidence.** The narratives were generated ~48 min AFTER the f06b8221 supersede, yet still baked 317.61 because the supersede's propagation surface (PROFILE#v1, S3 configs, baked pages, repo constants) did not cover the narrative pipeline's actual weight input at generation time: the withings DATE#2026-07-27 row still carried the override until the real reading was ingested 2026-07-28T03:05:42Z, and the regenerated constants.py only reached the fleet with the 03:21Z 07-28 CDK deploy. The needed process fix is supersede propagation to the wearable row / narrative inputs PLUS a dependent-narrative regen (sanctioned as honesty spend under the tier pause) — an invalidation hook alone, fired at supersede time, would have regenerated from the same stale source. Severity high stands; the contradiction is live now on the coaching door's first screen.

#### cpo-2 · CONFIRMED · sev **medium** · effort S · class A

**Finding.** The coaching door's first screen presents the tier-2 HELD read without the #802 'refresh paused (budget guard)' disclosure that the deeper by-coach page correctly shows: /api/coaching-dashboard omits regeneration_paused entirely and coaching.js hardcodes paused=false for the roster render, so a premiere-day reader sees 'as of 2026-07-27' presented as merely dated, not paused-and-frozen.

**Evidence.** /api/coaching-dashboard payload keys verified live (weekly_priority: text/coach_name/generated_at only; coaches[i]: no regeneration_paused field); site/assets/js/coaching.js:500 'coachAsOf(c.analysis_generated_at, false)' vs :685 which passes '!!analysis.regeneration_paused'; lambdas/web/site_api_coach.py:1815 adds the flag only to /api/coach_analysis

**Root cause.** site_api_coach.py's coaching-dashboard handler never calls _regeneration_paused('coach_narrative') (the #802 disclosure was wired only into the per-coach /api/coach_analysis response at line 1815), and site/assets/js/coaching.js:500 hardcodes the paused arg to false.

**Regression guard.** Unit test: with SSM budget-tier mocked >=2, the coaching-dashboard payload must carry regeneration_paused=true (pattern already exists for coach_analysis); visual_ai_qa prompt line: a held board read must show the paused note. Owner: unit tests + visual-qa layer 3.

**Path-to-A step.** Plumb _regeneration_paused into the coaching-dashboard response and pass it through at coaching.js:500 — pure completion of #802's own stated intent, S effort, zero new machinery.

**Verifier (CONFIRMED).** My reproduction: live /api/coaching-dashboard coach objects and weekly_priority carry no regeneration_paused key, while /api/coach_analysis?coach=physical returns regeneration_paused: true right now (tier 2). coaching.js roster render hardcodes coachAsOf(c.analysis_generated_at, false) (~line 500) vs the by-coach path passing !!analysis.regeneration_paused (~line 685); lambdas/web/site_api_coach.py wires _regeneration_paused('coach_narrative') only into the coach_analysis response (line 1815; chronicle at 1553). Issue #802 is CLOSED, so this is an uncovered surface of a closed fix, not a duplicate; no open issue covers it.

#### cpo-3 · ADJUSTED · sev **medium** · effort M · class A

**Finding.** Predict-the-week — the cockpit's flagship returnability hook — is dark for the entire season-premiere week: /api/predict_week returns active:false and the section self-hides. The 07-16 high finding's fail-closed+clear-at-reset half shipped (verified: no dead-cycle content — NOT a regression), but the promised re-seed half never did, so the premiere ships with zero interactive hook exactly when audience attention peaks.

**Evidence.** curl /api/predict_week → {"active": false}; site/cockpit/index.html:289-290 (section hidden without an active challenge with predict_metrics); curl /api/challenges → challenges all status 'available', none active; docs/reviews/FULLREVIEW_2026-07-16.md:43 + :761 cpo item 1 ('cleared by restart_pipeline.py and re-seeded weekly'); gh issue search 'predict'/'challenge' → no open issue covers seeding

**Root cause.** No writer exists for the weekly challenge lifecycle's seed half: restart_pipeline/reset clears site/config/current_challenge.json (the 07-16 fix) but no restart step or weekly job seeds a genesis-week challenge — the code gap is permanent, not a reset artifact.

**Regression guard.** restart_verify assertion: after a reset, /api/predict_week is either active for the genesis ISO week or a dated skip decision is recorded; weekly qa_smoke check that an active cycle has an active-or-honestly-skipped challenge. Owner: restart_verify + qa-smoke layer.

**Path-to-A step.** Finish the challenge lifecycle: restart_pipeline seeds a genesis-week predict-the-week challenge (e.g. 'Day 1 says 321.09 — where does week one land?') + the restart_verify assertion. ADR-103: completes an already-sanctioned load-bearing reader-engagement loop, no new infra.

**Verifier (ADJUSTED).** Symptom reproduced (/api/predict_week → active:false, all /api/challenges 'available', cockpit section self-hides per site/cockpit/index.html:290-296) and it is NOT on the do-not-refile list — but the stated root cause ('no writer exists for the seed half; the code gap is permanent') is false: the seeder exists and ran.

**Corrected cause/evidence.** deploy/build_genesis_predict_week.py (#1378, shipped in commit 801fa011/PR #1531, wired into restart_pipeline.py's step list at lines 75/1171) DID write s3://matthew-life-platform/site/config/current_challenge.json at 2026-07-26T16:50Z with real genesis content ('The opening week — the board is on the record', prereg-SHA-stamped predict_metrics). It stamps week_id = current_iso_week(run time); the Sunday 07-26 run fell in ISO 2026-W30 while genesis Monday 07-27 is 2026-W31, so site_api_social._predict_subject's #1198 fail-closed week-mismatch guard hides it (the script's own output warns 'upload during the genesis week'). Corrected fix: re-run the seeder during the genesis week and derive week_id from the genesis date instead of upload time (+ the restart_verify assertion). Severity/effort drop to S — the '07-16 re-seed half never shipped' claim is also wrong.

#### cpo-4 · CONFIRMED · sev **medium** · effort S · class A

**Finding.** No surface tells a returning reader WHEN the next installment lands: chronicle and podcast lists say 'or come back / follow by email for the next entry' with no date, the podcast fallback ('drops here once the chronicle's been running a week') is honest but undated, and at tier 2 the first weekly chronicle cannot generate before 08-01 — returnability leans entirely on subscribe/RSS during the premiere week. This was the 07-16 cpo remediation item 4, never shipped and not filed as an issue.

**Evidence.** Static text of /story/ and /story/panel/ (fetched live — no cadence/date line); site/assets/js/dispatches.js:165-168 (pending marker + 'No episodes yet' fallback, no cron-derived date); grep 'next installment|cadence' across site JS → none; docs/reviews/FULLREVIEW_2026-07-16.md:761 cpo item 4; gh issue search → no open issue

**Root cause.** dispatches.js/story list templates have no next-date element and no API exposes the chronicle/panel cron-derived next-scheduled date (or the tier-pause-adjusted honest-pending variant) — the cadence promise was designed (07-16 remediation list) but never implemented.

**Regression guard.** smoke_test_site.sh/content check: chronicle and podcast list pages must carry either a next-date line or an explicit honest-pending line; visual_ai_qa prompt addition. Owner: smoke layer 1.

**Path-to-A step.** Ship the deterministic cadence line derived from the actual crons ('the next chronicle lands Sunday' / 'paused by the budget guard until Aug 1'), honest-pending when withheld — S effort, reuses the existing pending-marker pattern in dispatches.js.

**Verifier (CONFIRMED).** My reproduction: live /story/ and /story/panel/ text carries only undated 'come back' / 'next entry' / 'follow by email' lines; dispatches.js:163-168 pending marker + 'No episodes yet — the first weekly review drops here once the chronicle's been running a week' fallback with no cron-derived date; grep across site/assets/js/ finds no next-installment/cadence line; FULLREVIEW_2026-07-16.md cpo remediation item 4 verbatim ('Add a deterministic cadence line to the Chronicle and Podcast lists'); git log since 07-16 shows no cadence-line commit and gh issue search finds no open issue. Tier 2 (verified in SSM) pauses the chronicle until 08-01, so premiere-week returnability does lean on subscribe/RSS.

#### cpo-5 · CONFIRMED · sev **low** · effort S · class A

**Finding.** Premiere-day coach narratives speak in unframed mid-cycle voice: Dr. Webb's live read opens 'I called lunch wrong. I predicted it would be your structural weak point… That hasn't materialized' — a prior-cycle prediction reference served on Day 1 while the scorecard shows 0 decided predictions this cycle; a newcomer landing on the premiere reads it as self-contradiction. Cross-cycle coach memory is deliberate design; the missing piece is Day-1/cycle-boundary framing in the narrative prompt.

**Evidence.** /api/coaching-dashboard → coaches[Marcus Webb].position_summary (generated 2026-07-27T17:01:15Z); curl /api/predictions → current cycle confirmed 0/refuted 0/decided 0; contrast: the integrator (Dr. Kai) DOES frame 'You showed up on Day 1', so the capability exists but isn't enforced per-coach

**Root cause.** The per-coach narrative prompt in the coach_narrative_orchestrator path injects cross-cycle thread memory without a cycle-boundary instruction for early-cycle days (day<=3), so coaches reference last cycle's graded calls in the present tense with no 'last cycle' framing.

**Regression guard.** board_quality_gate (web/board_quality_gate.py) early-cycle check: a narrative generated on day<=3 that references a graded/prior prediction must carry explicit prior-cycle framing — the quality gate is already the sanctioned regenerate-or-hold chokepoint (ADR-108). Owner: the coach quality gate.

**Path-to-A step.** Add the Day-N + cycle-boundary context line to the per-coach prompt and the corresponding board_quality_gate early-cycle rule — prompt+gate change only, no new infra.

**Verifier (CONFIRMED).** My reproduction: Webb's live position_summary opens 'I called lunch wrong. I predicted it would be your structural weak point… That hasn't materialized' (generated 2026-07-27T17:01:15Z) while /api/predictions shows current-cycle decided=0 (102 pending); Kai's weekly_priority does frame 'You showed up on Day 1', so the framing capability exists but is not enforced per-coach. coach_narrative_orchestrator.py has cycle-aware arc/thread machinery (#946 tombstone+cycle guards) but no day<=3 cycle-boundary prompt instruction, and web/board_quality_gate.py has no early-cycle prior-prediction rule. Not a duplicate: #1383 on the do-not-refile list is a WhatsApp/Telegram channel, unrelated. Cross-cycle memory itself is deliberate design — the finding correctly scopes to missing framing only. Low severity is right.

**Path to A (grader's ranked actions):**

1. Wire narrative invalidation into the baseline-supersede flow + qa_smoke deterministic baseline-figure check, and sanction one-shot correction regens under the tier pause (ADR-104 honesty spend; extends existing restart+qa_smoke machinery — finding 1)
2. Plumb regeneration_paused into /api/coaching-dashboard and stop hardcoding false at coaching.js:500, with a tier-mocked unit test (finding 2, S)
3. Seed a genesis-week predict-the-week challenge from restart_pipeline + restart_verify assertion, completing the lifecycle the 07-16 review specified (finding 3)
4. Ship the cron-derived cadence line on chronicle/podcast lists, honest-pending when the budget guard pauses generation (finding 4, S)
5. Add Day-N/cycle-boundary framing to the per-coach narrative prompt enforced by board_quality_gate's early-cycle rule (finding 5, S)

**Coverage (what this lens did NOT examine).** Not examined: ask-the-board POST path (exercising it invokes Bedrock — read-only contract; verified only that coaching.js:1007/1101 wires /api/board_ask and rate limiting exists), actual browser-rendered JS states (no Playwright run — all JS-rendered conclusions inferred from code + live API payloads), the subscribe/email funnel and digest content, /data subpages beyond the door, by-coach deep pages as rendered, mobile/responsive behavior, off-site channels (Bluesky/X/YouTube links untested), the semantics of /api/predictions 'current' showing 102 pending on Day 1 (observed, not verified — flagged in lens notes), and the OG share-card images. Market comparison was a single WebSearch, not a systematic competitive scan.

**Lens notes.** DEDUP: finding 3 is the unshipped half of the 07-16 cpo finding 1 (the shipped half verified working — active:false + hidden, NOT a regression); finding 4 is 07-16 remediation item 4, unfiled; #1243 prologue read-aloud orphan confirmed still relevant, not refiled (owner-gated); #1383 coach-line and #1475 wayfinding are adjacent to findings 2/5 but distinct — not refiled; podcast epic #1737 untouched by finding 4 (cadence copy, not TTS). PRIOR-REMEDIATION SCORE: 3 of 5 07-16 cpo path-to-A items verified landed (predict fail-closed; bare door URLs now 301 — /data,/cockpit,/coaching,/protocols,/story,/method all verified; cycle-compare beat on Home live with /api/cycle_compare current_cycle 11). DATA-MATURITY CAVEATS (not penalized): static-fallback pillar zeros pre-date the first Day-2 character-sheet compute; state_of_matthew available:false renders an honest family fallback pointing at the cockpit; podcast's single week-0 prologue episode (2026-07-25) and chronicle's 3 prologue posts are deliberate season-premiere lead-ins — genuinely good premiere craft, as are /method/survival/ (the model handicaps its own human), /method/cycles/, and the consent-gated diary shelf copy. HUNT-ORDER (#1194): no tombstoned prior-cycle content found leaking on the surfaces probed — the one staleness defect found (finding 1) is a NEW class: same-day override-superseded content, not dead-cycle leakage. UNVERIFIED OBSERVATION for another lens: /api/predictions 'current' block reports 102 pending predictions on Day 1 (sleep coach alone 14) — plausible if the Day-1 ensemble batch-writes, but worth a data-lens confirm. DISSENT-WORTHY: I graded B+ not A- because finding 1 sits on the coaching door's first screen and is the platform's own C-anchor ('hooks silently serve stale content') during the highest-traffic week; against a market of institutional AI-coaching apps (Lark-class platforms, NHS AI Health Coach pilot, Allurion Coach Iris — no comparable public N=1 documentary found), credibility IS the entire moat, so a published number contradiction outranks any missing feature. Sources: link.springer.com/article/10.1007/s11695-024-07209-1, digitalhealth.blog.gov.uk/2025/10/29/exploring-the-potential-of-an-ai-health-coach, stocktitan.net (Allurion Coach Iris).

### designer — Design system — **A-**

*Trend: = held at A-.*

**Verifier on the grade:** All three findings survive intact (two medium, one low — a real gate blind spot with live drift plus untracked grandfathered off-grammar colors, all cleanly fixable), which is consistent with the proposed A-: a strong, mostly-policed design system with one structural coverage gap and a sanction-hygiene debt.

#### designer-1 · CONFIRMED · sev **medium** · effort M · class A

**Finding.** Builder-emitted inline CSS is a structural blind spot in the token gate: six v4_build_*.py generators ship rogue breakpoints (min-width 560/620/640/720/900 — none of §10.1's nine sanctioned numbers) plus a raw 64px font-size, live on real pages including /method/grade-your-coach/ shipped 2026-07-27 — the exact drift class the #1212 gate was built to stop, migrated to the unpoliced surface and actively growing.

**Evidence.** scripts/v4_build_grade_your_coach.py (min-width: 620px, 900px x2), v4_build_gear.py:322 + v4_build_eyeball.py (720px), v4_build_methods.py (640px), v4_build_theme_river.py (560px, 900px), v4_build_tone.py (900px), v4_build_journal.py:76 (font-size:64px); live-confirmed: curl https://averagejoematt.com/method/grade-your-coach/ returns (min-width: 620px) + 2x (min-width: 900px), site/gear/index.html:39 has 720px; scripts/check_css_tokens.py:64 SWEPT = 7 site/assets/css sheets only — no generator or built-HTML inline <style> is ever scanned

**Root cause.** The STYLE string constants inside scripts/v4_build_{gear,eyeball,methods,tone,theme_river,grade_your_coach,journal}.py emit page-scoped <style> blocks; scripts/check_css_tokens.py:64 scopes the sweep to site/assets/css/*.css so this CSS never meets the breakpoint/font-size/hex checks — DESIGN_SYSTEM_V5.md §10.1's own verification grep is likewise scoped to site/assets/css

**Regression guard.** Extend check_css_tokens.py to also extract and sweep <style> blocks from the v4_build_*.py sources (or from built non-legacy site/**/index.html), with a planted-violation test per the existing non-vacuous-check pattern in tests/test_css_tokens.py; owner: the existing CI unit-test job — zero new infra (ADR-103: extends a load-bearing offline gate)

**Path-to-A step.** One PR: retarget the five rogue values to their by-job sanctioned neighbors (620/640→601, 720→761, 560→480 or 601, 900→901), swap the journal drop cap to the story.css:401 relative-em pattern, then extend the gate so the fix can't rot

**Verifier (CONFIRMED).** Reproduced end-to-end: grep of the six v4_build_*.py files shows every cited rogue breakpoint (620/900 grade_your_coach, 720 gear.py:322 + eyeball.py:82, 640 methods.py:102, 560/900 theme_river, 900 tone.py:76) and font-size:64px at v4_build_journal.py:76; live curl of /method/grade-your-coach/ returns (min-width: 620px) + 2x (min-width: 900px) and site/gear/index.html:39 has 720px; check_css_tokens.py SWEPT = the 7 site/assets/css sheets only and SANCTIONED_BREAKPOINTS = {360,480,600,760,820,601,761,821,901} contains none of the five values; §10.1's rule text is itself scoped to site/assets/css/** exactly as the root cause states. No open or closed issue covers builder-inline CSS (#1006/#1212/#998 all CLOSED, stylesheet-scoped).

#### designer-2 · CONFIRMED · sev **medium** · effort S · class A

**Finding.** Five off-palette status-color families were grandfathered by hex-ok sanctions whose text promises 'its own tokenization is a separate finding' — no such issue exists — and the worst of them, red-for-lost (.pl-lost #dc2626) and green-for-won/confirmed, are live-wired today; the first decided prediction of cycle 11 ships a red/green semaphore contrary to §4's single-ember grammar, currently masked only because 0 of 102 calls are decided.

**Evidence.** story.css:731-733 (.pl-won #16a34a / .pl-lost #dc2626 / .pl-open #b45309), story.css:618 (.cr-confirmed #22c55e — while .cr-refuted at story.css:619 is already correctly var(--ember), so the same component mixes both grammars), story.css:958-959 (.sc-confirmed #5a8f6b), evidence.css:286-287 (.hb7-good #16a34a / .hb7-mid #d97706); live-wired: dispatches.js:218 builds pl-${esc(b.outcome)}, coaching.js:178 builds cr-${esc(r.status)}; curl /api/predictions → 102 pending, 0 decided (the mask); gh issue searches for tokenize/color/hex/ledger-red return no open issue; #1211 is CLOSED

**Root cause.** The #1211 remediation (post-2026-07-16 review) retokenized the two named accents (lead-sky, vice-hold) but silenced the remaining families with '/* hex-ok: ... out of #1211 scope — its own tokenization is a separate finding */' comments in story.css/evidence.css and never filed the finding — the sanction escape hatch in scripts/check_css_tokens.py accepts any free text, so the gate now permanently blesses the exact colors it was written to catch

**Regression guard.** The raw-hex gate already fires on these literals — deleting the sanction comments makes tests/test_css_tokens.py red until each family is tokenized; interim guard: a one-line test asserting no hex-ok sanction text contains 'separate finding' without a #NNNN issue ref

**Path-to-A step.** Decide the outcome grammar once (per §4: confirmed/won → ember, refuted/lost → muted ink — .cr-refuted and .vice-broke already model it), apply across .pl-*/.cr-*/.sc-*/.hb7-*, delete the five hex-ok sanctions

**Verifier (CONFIRMED).** All 8 hex-ok sanctions reproduced at the cited lines in story.css/evidence.css, five promising 'its own tokenization is a separate finding' — gh issue searches find no such issue; #1211 is CLOSED and its fix (ea335a57) retokenized only lead-sky/vice-hold. Live wiring verified: dispatches.js:218 emits pl-${outcome}, coaching.js:178 emits cr-${status}; /api/predictions overall = {total:102, pending:102, decided:0} so the red/green semaphore is currently masked exactly as claimed. §4 ('one ember accent… down/flat = muted ink, never red') plus the in-component contrast (.cr-refuted and .hb7-miss already ride var(--ember)) confirms the mixed-grammar defect.

#### designer-3 · CONFIRMED · sev **low** · effort S · class B

**Finding.** The gate's sanction grammar (hex-ok:/fs-ok:) accepts arbitrary free text with no issue-ref or expiry requirement, which is precisely how finding 2's untracked grandfathering happened — deferral-by-comment is invisible to the backlog (violates the ADR-099 principle that forward work lives in Issues).

**Evidence.** scripts/check_css_tokens.py sanction check is a substring test ('hex-ok:' / 'fs-ok:' in line — proven by tests/test_css_tokens.py:35,56); the 8 hex-ok comments in story.css/evidence.css defer to 'a separate finding' that gh issue list cannot find; contrast: the fs-ok SVG sanctions post-#1210 cite verifiable floor math (evidence.css:623) because the measured visual_qa gate arbitrates them

**Root cause.** scripts/check_css_tokens.py's sanction parser — a bare substring match with no schema; the process gap is that a sanction expressing deferred work carries no machine-checkable link to the backlog

**Regression guard.** Extend the sanction parser: a sanction whose reason implies deferral (or any hex-ok at all) must carry a #NNNN ref to an OPEN issue (offline check via a committed allowlist or the reason grammar); planted-violation test alongside the existing non-vacuous tests

**Path-to-A step.** Fold into finding 2's PR: after tokenizing, the remaining sanction population is small enough to require an issue ref or a self-contained verifiable reason on each

**Verifier (CONFIRMED).** check_css_tokens.py:114 is a bare substring test (`if "hex-ok:" in line`) with no issue-ref or expiry schema, proven permissive by tests/test_css_tokens.py:35 (free-text '/* hex-ok: status colour */' passes); the 8 sanctions defer to a 'separate finding' that was never filed, which is untracked forward work contrary to the ADR-099 backlog principle. The finding correctly notes the fs-ok viewBox-floor sub-check (#1210) as the contrasting arbitrated case, so no overstatement. Not a duplicate of #1872 (backlog hygiene linter, different surface).

**Path to A (grader's ranked actions):**

1. Extend scripts/check_css_tokens.py to sweep builder-emitted <style> CSS (the 10 v4_build_*.py STYLE blocks or built non-legacy HTML), fixing the five rogue breakpoints (560/620/640/720/900 → sanctioned by-job neighbors) and the 64px journal drop cap in the same PR — ADR-103-clean: extends the existing offline gate, zero standing cost
2. Tokenize the five grandfathered status-color families to one §4-compliant outcome grammar (confirmed/won → ember; refuted/lost → muted ink, as .cr-refuted and .vice-broke already do) and delete their hex-ok sanctions so the existing gate owns them
3. Require deferral-style sanctions to carry an open-issue ref, enforced by the sanction parser with a planted-violation test
4. File the tokenization issue the hex-ok comments promised (or land the fix directly) so nothing in the design system defers work outside the ADR-099 backlog

**Coverage (what this lens did NOT examine).** Examined: DESIGN_SYSTEM_V5.md in full; all 8 site/assets/css sheets via targeted greps (hex, fs-ok/hex-ok, glow/box-shadow additions since 07-16 via git diff); scripts/check_css_tokens.py + tests/test_css_tokens.py (ran: 5 passed) + tests/test_paper_ramp_contrast.py (ran: 3 passed); all 10 CSS-emitting builder scripts scanned for hex/font-size/breakpoints; live renders via Playwright (read-only) of /, /cockpit/, /coaching/, /data/character/, /story/diary/, /protocols/, /data/ at 390x844 AND 1280x900 with measured getScreenCTM SVG-text effective sizes (zero sub-floor at both widths — prior finding 1 verified fixed live) and horizontal-overflow checks (none); live curls of /version.json (6acd301 == main), /api/journey, /api/predictions, /method/grade-your-coach/, /story/diary/, /data/character/; inline <style> audit of the 4 non-legacy hand/build-authored pages (404, gear, privacy, journal essay). Day-1 empty states verified designed and honest on 5 surfaces; hunt-order probe clean (attempt #11, 11 season beads, DAY 1 consistent, character priors labeled 'AUTHORED PRIOR — NOT YET CONFIRMED'). NOT examined: /mind/, /subscribe/, /story/ subpages beyond the diary shelf, chronicle post bodies, /gear/ rendered, OG share cards, email templates; no light-vs-dark visual pass (relied on the passing paper-ramp contrast test + prior run's 19 measured ratios); no tap-target audit rerun (gating in CI); no VoiceOver/keyboard session; the design_sync_bundle.py hexes were not audited (export tool, not a live page).

**Lens notes.** Regression check against FULLREVIEW_2026-07-16 (designer, A-, 4 findings): ALL FOUR FIXED WITH REAL GUARDS — (1) SVG type floor is now a gating measured audit (tests/visual_qa.py:398-433, #1210) and measured clean live today at both widths; (2) lead-sky #0ea5e9 and vice-hold #16a34a retokenized to ember (story.css:707/719, evidence.css:262); (3) gate extended to all 7 consumer sheets + raw-hex + the §10.1 nine-number assertion (#1211/#1212), story.css 520px fixed; (4) fs-ok 'SVG viewBox units' sanctions now cite verifiable floor math with the measured gate as arbiter. The a11y lens's light-mode --alert also fixed (#1222, tokens.css:332/360). Finding 1 here is NOT a regression of a fixed instance — the sheets stay clean — but it IS the same drift class re-emerging on the one surface the extended gate doesn't reach, seeded by the newest page (grade-your-coach, 07-27). Dedup: no open issue matches any finding (searched design/color/hex/breakpoint/ledger); epic #1461 (visual identity v5.1) is adjacent context for finding 2 but does not name status-color tokenization; #1653 packaging and #1654 god-modules are unrelated. Data-maturity: finding 2 renders nothing today (0 of 102 calls decided) — it fires on the first graded prediction, likely within days as windows close. Kill-on-sight scan: clean — no decorative glow (all new box-shadows since 07-16 are :target focus rings or annotated elevation), no red-for-direction rendering live, no emoji marks (renderers resolve via domainIcon per §8.6), day-counter/attempt/bead surfaces all honestly Day-1/cycle-11. Dissent-worthy observation: .cr-refuted=ember while .cr-confirmed=green within the same list (story.css:618-619) means the outcome grammar was half-migrated — whoever fixes finding 2 should decide deliberately whether ember marks 'confirmed' (ember=alive) or 'refuted' (ember=attention), then apply it uniformly; today the site ships both readings.

### dataviz — Charts & instruments — **B+**

*Trend: ▼ **down from A-**.*

**Verifier on the grade:** All three findings survive adversarial verification with independent live+code reproduction — a high-severity front-page prior-cycle leak (the exact #1194 recurrence class) plus two medium honesty defects fully support the proposed B+ and would make anything higher indefensible.

#### dataviz-1 · CONFIRMED · sev **high** · effort S · class A

**Finding.** Tombstoned prior-cycle intelligence serves live on the home page: /api/what_changed returns a record tombstoned at the 2026-07-13 reset (computed 2026-07-04, phase=pilot, cycle=5) and the home returnability strip renders it as 'newly unlocked this month: habit pct ↔ day grade (r=0.88, n=20…)' on Day 1 of cycle 11 — the exact #1194 hunt-order defect class, on the front page.

**Evidence.** aws dynamodb get-item pk=USER#matthew#SOURCE#what_changed sk=SNAPSHOT#current → {tombstone:true, tombstoned_at:'2026-07-13T01:27:49Z', phase:'pilot', cycle:5, computed_at:'2026-07-04'}; curl https://averagejoematt.com/api/what_changed → newly_unlocked[0]={r:0.8777, first_seen:'2026-06-30', window 06-05→07-04}; lambdas/web/site_api_ledger.py:117 get_item with NO tombstone check; site/assets/js/story.js:885-897 renders it when !preStart() (false on Day 1); live home HTML has the [data-home-unlocked] mount and shipped story.js carries the copy (verified by curl)

**Root cause.** lambdas/web/site_api_ledger.py:what_changed() reads SNAPSHOT#current unconditionally — the intelligence wipe deliberately tombstones rather than deletes (deploy/restart_intelligence_wipe.py line 144: ('what_changed','all')), and the read-path tombstone-honoring convention (present in site_api_coach.py:563, site_api_ai_lambda.py:829, site_api_intelligence.py:2464) was never applied to the ledger split module. Secondary: the 'this month' copy is also stale-unsafe — the record was last written 07-04, 24 days before serve.

**Regression guard.** A sweep pytest that stubs a tombstoned record into EVERY experiment-scoped partition read by lambdas/web/* and asserts no handler returns tombstoned content (the per-module convention keeps missing modules — tests/test_honest_read_guards_1084.py has zero tombstone assertions today); nightly qa_smoke_lambda should own a post-reset 'no tombstoned payload serves' probe in the first cycle week.

**Path-to-A step.** In what_changed(): if item.get('tombstone') → return the existing shaped-empty honest_null response (the empty branch is already written 3 lines above); also gate the front-end copy on computed_at recency so 'this month' can never describe a 3-week-old record.

**Verifier (CONFIRMED).** Independently reproduced end-to-end: DDB get-item on what_changed/SNAPSHOT#current returns tombstone:true, tombstoned_at 2026-07-13, phase:pilot, cycle:5; curl /api/what_changed serves that exact record live (r=0.8777, window 06-05→07-04, honest_null:false). site_api_ledger.py:117 has no tombstone check while the convention exists in site_api_coach.py:571, site_api_ai_lambda.py:829, site_api_intelligence.py:2464; restart_intelligence_wipe.py:144 tombstones ('what_changed','all'). preStart() (coach_popover.js:45) returns null at dayN>=1, so story.js:885's only gate is open on Day 1; shipped story.33030b59.js carries the render and live home has the data-home-unlocked mount. Not fixed (git log site_api_ledger.py shows no fix), no open duplicate issue (#949 is closed and only covered pre-start). Exact #1194 hunt-order class on the front page.

#### dataviz-2 · CONFIRMED · sev **medium** · effort M · class A

**Finding.** The home constellation's edges — the page's strongest visual claim — are computed live from TOMBSTONED prior-cycle character_sheet records with no phase filter: on Day 1 all 14 edges (n=45–60, window 2026-05-28→07-26, ending the day before genesis) describe last cycle's co-movement while the adjacent nodes/caption say 'a young experiment starts low'.

**Evidence.** curl /api/pillar_coupling → window_start 2026-05-28, window_end 2026-07-26, 14 edges n=15–60; aws dynamodb query character_sheet DATE#2026-07-2* → records carry tombstone:true, phase:'pilot'; lambdas/phase_taxonomy.py:217 classes character_sheet EXPERIMENT_SCOPED ('wiped all + rebuilt'); lambdas/web/site_api_intelligence.py:1678-1684 queries begins_with(sk,'DATE#') with NO with_phase_filter (the helper exists and is used for insights in site_api_ledger.py:195); caption binding story.js:859-860 appends only 'over the last 60 days'

**Root cause.** handle_pillar_coupling (lambdas/web/site_api_intelligence.py:1670) deliberately reads trailing-60 character_sheet records but ignores the platform's own tombstone/phase contract on EXPERIMENT_SCOPED derived scores — either the read must honor tombstones (honest_null on Day 1, edges accrue with the cycle) or the cross-reset read must be explicitly sanctioned (ADR-077 carve-out) AND the figcaption must say the window predates the current cycle; today it is neither, and the 07-16 review's unfiled 'spans the reset' suspicion is now a 100%-prior-cycle figure.

**Regression guard.** Same sweep test as finding 1 (pillar_coupling is exactly the module the per-handler convention missed); plus a caption assertion in tests/visual_qa.py or a unit test: when window_start < EXPERIMENT_START_DATE the served payload must carry a cross-cycle flag the front-end renders.

**Path-to-A step.** Decide the semantic under ADR-077 and encode it: EITHER add the tombstone/phase filter so edges rebuild from genesis (constellation caption already handles few-days honesty), OR keep the trailing window as a sanctioned cross_phase read and ship a served boolean (spans_reset:true) that the figcaption renders as 'measured before this cycle began'.

**Verifier (CONFIRMED).** Reproduced: curl /api/pillar_coupling returns window 2026-05-28→2026-07-26 (ends day before genesis), 14 edges, honest_null:false — 100% prior-cycle data. handle_pillar_coupling (site_api_intelligence.py:1679) queries character_sheet DATE# with no with_phase_filter (the helper IS used at site_api_ledger.py:195); phase_taxonomy.py:217 classes character_sheet EXPERIMENT_SCOPED; caption binding (story.js:860) appends only 'over the last N days' with no cross-cycle disclosure. No fix in git log, no duplicate issue. One evidence nuance: my DDB query shows 07-20→24 with tombstone:true+phase:pilot but 07-25/26 carry phase:pilot WITHOUT tombstone:true — so the phase filter (not a tombstone-only check) is the necessary mechanism; this strengthens the finding's proposed fix rather than weakening the defect claim.

#### dataviz-3 · CONFIRMED · sev **medium** · effort S · class A

**Finding.** observatory_week's ADR-104 week-over-week guard is defeated by its own genesis clamp: prev window max(anchor-14/-8, EXPERIMENT_START) collapses 'last week' onto the current cycle's first days, so live today sleep serves delta 0.0 + trend 'down' + 'Avg sleep declined 0.0h vs last week' (today compared to itself), and on Days 2–8 of every cycle all six cockpit week-view rows will render ▲/▼ deltas 'vs last week' against days inside the same week; a tie also maps to trend 'down'.

**Evidence.** curl /api/observatory_week → {delta:0.0, delta_label:'vs 8.9 last week', trend:'down', notable:'Avg sleep declined 0.0h vs last week', sparkline:[8.9]} on Day 1; lambdas/web/site_api_rollups.py:277-279 (prev_start/prev_end clamped up to EXPERIMENT_START → prev window == [genesis,genesis] == the current window's own day, so _has_wow at line ~304 is True and the honest 'no completed prior week in this cycle' branch never fires); trend ternary ('up' if avg>prev else 'down') maps equality to 'down'; renderer cockpit.js:1222-1229 (masks Day 1 only via sparkline>=2 and delta!==0 filters); the same prev window feeds all six domain branches and the AI explain surface (site_api_ai_lambda.py:1333-1341 forwards delta/trend/delta_label to the model)

**Root cause.** lambdas/web/site_api_rollups.py:277-279 — the clamp assumed 'the prior window clamps to genesis and stays empty' (comment at the _has_wow guard), which was false the moment genesis day had data: max() maps a fully-pre-genesis window onto [genesis,genesis] instead of leaving it empty, silently overlapping the current week.

**Regression guard.** Unit test on the rollup with a stubbed table where anchor == genesis and anchor == genesis+2d: assert delta is null, trend 'flat', and prev window does not intersect [start_date, end_date]; the existing tests/test_pre_start_contract_sweep.py covers pre-start but not week-1-of-cycle — this is the adjacent lifecycle case it should own.

**Path-to-A step.** Replace the clamp with emptiness: if (anchor-8d) < EXPERIMENT_START → prev_items = [] (the existing _has_wow branch then serves the honest 'no completed prior week in this cycle' copy); independently map delta==0 to trend 'flat' in all six domain branches.

**Verifier (CONFIRMED).** Reproduced exactly: curl /api/observatory_week serves delta 0.0, trend 'down', notable 'Avg sleep declined 0.0h vs last week', sparkline [8.9] on Day 1. site_api_rollups.py:277-278: max(anchor-14/-8, EXPERIMENT_START) maps the fully-pre-genesis prev window onto [genesis,genesis] — inside the current window — so _has_wow (line 303) is true and the honest no-prior-week branch (line 337) never fires; the false assumption is written in the comment at lines 300-302. Tie→'down' confirmed at line 311 ('up' if avg>prev else 'down'). cockpit.js:1222-1226 masks Day 1 only via sparkline>=2 and delta!==0 — Days 2-8 pass both with overlapping windows across all domain branches (same prev_start/prev_end feeds each _query_source). AI explain (site_api_ai_lambda.py:1340) forwards delta/trend via an 'is not None' filter, so delta 0.0 + trend 'down' reach the model today. Closed #948 built the guard this clamp defeats; no open issue covers the post-genesis case.

**Path to A (grader's ranked actions):**

1. Honor the tombstone in site_api_ledger.what_changed(): serve the already-written honest_null shape when tombstone=true, and gate the home 'this month' copy on computed_at recency (S, no new infra).
2. Resolve pillar_coupling's semantic under ADR-077 and encode it: either phase-filter the character_sheet read so constellation edges rebuild from genesis, or sanction the cross-reset window explicitly with a served spans_reset flag the figcaption renders as 'measured before this cycle began' (S–M).
3. Fix the observatory_week prev-window clamp to yield an EMPTY prior week when it predates genesis (engaging the existing ADR-104 branch) and map delta==0 to trend 'flat' across all six domains (S).
4. Add ONE tombstone sweep pytest for lambdas/web/*: stub a tombstoned record into every EXPERIMENT_SCOPED partition each handler reads and assert nothing tombstoned is returned — converts the per-module convention (which missed the ledger module twice) into a structural gate; offline, zero standing cost, ADR-103-clean.
5. Add a first-week-of-cycle lifecycle case to tests/test_pre_start_contract_sweep.py (anchor==genesis and genesis+2d) so reset-boundary honesty is tested at BOTH lifecycle edges, not just pre-start.

**Coverage (what this lens did NOT examine).** Verified this run: live payloads for /api/journey_waveform, /api/journey, /api/pulse, /api/pillar_coupling, /api/correlations, /api/observatory_week (sleep), /api/vitals, /api/what_changed, /api/cycle_compare, /api/discoveries, /api/sleep_correlations; DDB ground truth for what_changed and character_sheet tombstones; full reads of story.js waveform/constellation/homePulse/cycleBeat, cockpit.js week view, site_api_rollups.py sleep branch, site_api_ledger.py, site_api_intelligence.py coupling handler, restart_intelligence_wipe.py registry+main loop, svgtype.js floors, tests/test_wave_render_guard.py header; confirmed the shipped story.js on CDN carries the unlocked-line renderer and the live home HTML has its mount. NOT examined this run: no browser render pass or screenshots (code+payload verification only — rendered-px SVG floors delegated to the visual_qa arbiter); charts.js primitives not re-audited line-by-line (relied on the 07-16 full 905-line pass plus spot checks of consumers); the 5 non-sleep observatory_week domain branches read only at the shared-clamp level; OG image cards, /data/ topic pages beyond the endpoints above, evidence_* modules, cockpit daily view internals, and calibration surfaces not re-inspected; AI explain behavior under budget tier 2 not exercised live; the weekly-correlation-compute writer itself (why nothing wrote after 07-04) not traced.

**Lens notes.** DEDUP: gh open-issue searches for what_changed/tombstone/pillar_coupling/constellation/observatory returned no matches; findings 1–2 are a RECURRENCE of the epic #1194 defect class (closed) — the guard that failed is the module-by-module tombstone-honoring convention (site_api_coach/ai_lambda/intelligence have it; the #1654-era ledger split module does not), with no sweep test; finding 2 upgrades the 07-16 dataviz lens's deliberately-unfiled 'spans the reset' suspicion with new tombstone evidence, not a refile. PRIOR-FINDING VERIFICATION: all three 07-16 findings are FIXED with non-vacuous guards — #1213/#1214 waveform (barTier 'mid' + WAVE_FLAT_HEIGHT, marker-block extracted and run under node by tests/test_wave_render_guard.py), #1215 constellation edges on the shared data-cpts readout, and the SVG type floor generalized into svgtype.js SVG_TYPE_FLOORS (#1210) with visual_qa as arbiter — no regressions of previously-fixed items. DATA-MATURITY: Day-1 emptiness is handled superbly almost everywhere (correlations gates {min_n:10, current_n:1} refuse; sleep_correlations serves coefficient:null/direction:'insufficient'; vitals hrv_trend:'insufficient_data' with hrv_30d_n:1; journey CI null + rate_provisional → projection refusal; cockpit week view renders its honest empty state today; cycle_compare's cycleBeat is payload-derived and reset-aware) — the three findings are all server-side reset-boundary payload honesty, not renderer encoding defects. DISSENT-WORTHY: what_changed's computed_at is 2026-07-04 — the weekly writer stopped ~3.5 weeks ago, BEFORE the 07-13 reset; that pipeline-health question belongs to the data-pipeline lens. Pulse serves status_color '#f5a623' raw hex in the API contract (renderer maps states to tokens; design-lens territory). KILL-ON-SIGHT: clean — no decorative glow, every correlation surface carries n and correlative framing, no causal claims, no age/vice/genome leakage on any chart surface I touched. GRADE RATIONALE: primitive library + uncertainty grammar remain the platform's best-in-class asset and the 07-16 fixes landed with real guards (would be A/A-), but Day 1 — the exact day the rubric exists for — has the front page serving tombstoned prior-cycle intelligence on two surfaces plus a fabricated week-over-week family armed for Days 2–8, all violating the platform's own tombstone/ADR-104 contracts: B+.

### qs — Scientific credibility — **C+**

*Trend: ▼ **down from B+**.*

**Verifier on the grade:** Yes — the surviving set still supports C+ and arguably no better: two high-severity credibility defects fully reproduce (18 fabricated PMID→claim mappings live on /api/supplements plus a fabricated citation with an invented effect-size summary on the active tongkat-ali protocol, and a public 'Career · every cycle' denominator that hides 273 voided pre-registered bets), backed by three medium findings (39 orphaned ungraded hypotheses, 3-of-6 cycles with no sealed prereg, the seal unlinked from every page), with only the hedging finding and the zone-2 dedupe claim materially downgraded.

#### qs-1 · CONFIRMED · sev **high** · effort L · class A

**Finding.** At least 21 PubMed citations on the two live public evidence registries resolve to completely unrelated papers — fabricated PMID→claim mappings, several carrying invented quantitative summaries.

**Evidence.** curl https://averagejoematt.com/api/supplements + /api/experiments (fetched 2026-07-28 04Z), then resolved every PMID via NCBI eutils esummary. Mismatches include: NAC — ALL THREE sources wrong (17284826 → 'Expression of a functional sphingomyelinase of Pseudomonas sp. TK4'; 24629205 → 'Effects of gum chewing on postoperative bowel motility after caesarean section'; 25974857 → 'Reduction of Working Time: Does It Lead to a Healthy Lifestyle?'); Myo-Inositol — ALL THREE wrong (27510537, 26905542, 28954909 → 'whale falls as chemosynthetic stepping-stones'); Glycine 17693028 → near-infrared stroke therapy; 27253365 → 'Zika Virus, Microcephaly, and Ocular Findings-Reply'; Apigenin 10802676 → GFP dilated cardiomyopathy; Electrolytes 25920354 → 'Five critical elements to ensure the precision medicine'; Collagen 27053525 → mTORC1/leucine; L-Glutamine 28426424 → 'cDNA library construction of two human Demodex species'; Reishi 26462366 → 'Celery Seed and Related Extracts'; Zinc 23647674 → intranasal curcumin; Multivitamin 36129998 labelled 'COSMOS trial' → 'Trial of Antisense Oligonucleotide Tofersen for SOD1 ALS'; 17921406 → skin-aging appearance; B-Complex 29495902 ('excess B6 neuropathy') → postpartum depression prophylaxis; Green Tea 22747440 → medullary thyroid carcinoma miRNA. Worst case, config/experiment_library.json:954 — the ACTIVE tongkat-ali-recovery protocol's evidence_for cites PMID 23615780 with the summary 'Reduced cortisol 16% and increased testosterone 37% in moderately stressed adults over 4 weeks'; 23615780 is 'Oral health, oral pain, and visits to the dentist: neighborhood influences'. config/experiment_library.json:1144 — berberine AMPK mechanism cites 22198837 = 'Two surfaces on the histone chaperone Rtt106…'.

**Root cause.** config/supplement_registry.json (served verbatim by lambdas/web/site_api_data.py::handle_supplements) and config/experiment_library.json (served by lambdas/web/site_api_ledger.py:152-160 and the experiments handler). The PMIDs were authored alongside the claim text and never resolved. The guard shipped for the previous review's citation finding — tests/test_supplement_registry.py:71-92 — validates only that a URL MATCHES AN ARTICLE URL SHAPE (`?term=` rejected, /\d+/ accepted); it never checks the article exists or matches the claim, so replacing search-URLs with plausible-looking digits passed the gate cleanly.

**Regression guard.** An offline pytest that resolves every citation PMID against a checked-in id→title fixture (refreshed by a small script that hits NCBI eutils; no runtime dependency, no standing cost) and asserts non-trivial token overlap between the real title and the registry's claimed title/summary. Owner: the offline unit-test layer that already hosts tests/test_supplement_registry.py — this is the same gate, correctly specified.

**Path-to-A step.** Re-verify every citation in both registries against the resolved title; replace or relabel each mismatch ('open question — no direct study found' is already the sanctioned honest form, used correctly for Magnesium L-Threonate), then land the resolution test so the class cannot recur.

**Verifier (CONFIRMED).** My own batch resolution of all 58 supplement PMIDs via NCBI eutils (esummary, fetched 2026-07-28) reproduces 18 hard mismatches on the live /api/supplements payload: NAC 17284826→'Expression of a functional sphingomyelinase of Pseudomonas sp. TK4', 24629205→'gum chewing after caesarean section', 25974857→'Reduction of Working Time'; Myo-Inositol 27510537→'Comparing metabolite profiles of habitual diet', 26905542→'Obesity and Sentinel Lymph Node Mapping', 28954909→'whale falls as chemosynthetic stepping-stones'; Glycine 17693028→near-infrared stroke therapy, 27253365→'Zika Virus, Microcephaly-Reply'; Apigenin 10802676→GFP dilated cardiomyopathy; Electrolytes 25920354→'Five critical elements... precision medicine'; Collagen 27053525→mTORC1/leucine; L-Glutamine 28426424→'cDNA library of two human Demodex species'; Reishi 26462366→'Celery Seed and Related Extracts'; Zinc 23647674→intranasal curcumin; Multivitamin 36129998→'Tofersen for SOD1 ALS' (labelled COSMOS), 17921406→skin-aging; B-Complex 29495902→postpartum depression prophylaxis; Green Tea 22747440→medullary thyroid carcinoma miRNA. Independently: 23615780='Oral health, oral pain, and visits to the dentist' (cited by the tongkat-ali-recovery protocol WITH the invented 'cortisol -16%/testosterone +37%' summary, and that evidence_for block is live in /api/discoveries), 22198837='Two surfaces on the histone chaperone Rtt106'. Root cause verified: handle_supplements (lambdas/web/site_api_data.py:271) serves the registry verbatim, and the #1216 guard at tests/test_supplement_registry.py:80 only rejects '?term=' / non-article URL shapes — it never resolves the id. No open issue covers this (gh issue list --search citation/PMID returns none); #1216 is CLOSED and its fix is confirmed still holding for the URL-shape class only.

#### qs-2 · CONFIRMED · sev **high** · effort S · class A

**Finding.** The public 'Career · every cycle' calibration denominator (n=50) silently excludes 273 pre-registered bets that were voided at resets — the void ledger is write-only and no surface ever reports it.

**Evidence.** curl https://averagejoematt.com/api/calibration → platform.lifetime.n=50 (23 confirmed / 27 refuted), rendered as 'Career · every cycle' at site/assets/js/evidence_intelligence.js:340. DDB query pk=USER#matthew#SOURCE#calibration → 296 rows: 23 forecast_resolution, 6 hypothesis_void, 267 prediction_void (voided_at_reset, by genesis: 07-18=84, 07-19=10, 07-20=110, 07-22=31, 07-27=38). grep for voided_at_reset / hypothesis_void / prediction_void across lambdas/ returns ZERO hits outside deploy/restart_pipeline.py, and zero across site/. So ~85% of every pre-registered coach call the platform ever made is invisible on the page whose subtitle is 'Every forecast graded against what actually happened — the honesty moat, made public.'

**Root cause.** lambdas/calibration_core.py outcome_to_binary returns None for outcome='voided_at_reset' (correct — they must not distort Brier), but handle_calibration never counts them separately, and the served `disclosure` string names only self-grading and Brier semantics. The #1199 fix wrote the rows and stopped there.

**Regression guard.** Unit test on handle_calibration: whenever the ledger holds voided_at_reset rows, the payload must carry a non-zero voided count and the disclosure must name it — plus a visual-AI-QA prompt for /method/calibration that flags 'page claims a complete career record while the ledger holds voided rows'. Owner: offline pytest + the existing tests/visual_ai_qa.py semantic layer.

**Path-to-A step.** Add `voided: {n, by_cycle}` to the /api/calibration payload and one rendered line on the Career card ('N bets voided at resets — never graded, shown so the denominator is honest'). One field, one line, zero standing cost (ADR-103 clean).

**Verifier (CONFIRMED).** Reproduced end-to-end. curl /api/calibration (2026-07-28) → platform.lifetime {n:50, confirmed:23, refuted:27}; my own DDB query of pk=USER#matthew#SOURCE#calibration returns 296 rows = 267 prediction_void + 6 hypothesis_void + 23 forecast_resolution, i.e. 273 outcome='voided_at_reset' rows keyed by reset_genesis (07-18:84, 07-19:10, 07-20:110, 07-22:31, 07-27:38). calibration_core.outcome_to_binary (line 56-63) returns None for that outcome so they are correctly excluded from Brier, and handle_calibration (site_api_coach.py:1968-2050) never counts or discloses them — I read the served disclosure string in full: it names self-grading, Brier semantics and calibrated-vs-skilled only, no void concept. grep for 'voided_at_reset' across lambdas/ and site/ returns zero hits outside deploy/restart_pipeline.py and its test; the only 'void' strings in site/assets/js are an unrelated coaching.js comment and JS `void` operator uses. evidence_intelligence.js:343 does render the block as 'Career · every cycle'. 273/(273+50)=84.5% matches the finder's ~85%. No open issue tracks it.

#### qs-3 · CONFIRMED · sev **medium** · effort M · class B

**Finding.** 39 open pre-registered hypotheses sit tombstoned, never graded AND never voided — the #1199 grade-or-void fix is forward-only and its skip rule permanently orphans everything tombstoned before it shipped.

**Evidence.** DDB scan sk begins_with HYPOTHESIS# → 46 rows: 39 status=pending/phase=pilot (all tombstone=true), formed 2026-05-10 through 2026-07-20; only 2 pending/experiment (cycle-11's genesis_prereg_h1/h2, live at /api/hypotheses). All 6 hypothesis_void rows in the ledger are genesis_prereg_h1/h2 at genesis 07-18/07-20/07-22 — so 4 engine-formed hypotheses dated 2026-07-20 were also tombstoned without a void row. deploy/restart_pipeline.py:470-480 `_is_open_untombstoned` returns False for any tombstoned row on the stated assumption that it 'already carries (or got) its own void row' — false for every bet tombstoned before #1199 and for any bet tombstoned by a re-run wipe. Today's 07-27 reset wrote 38 prediction_void rows and 0 hypothesis_void rows.

**Root cause.** deploy/restart_pipeline.py::_is_open_untombstoned (line ~470) — the idempotency guard doubles as a correctness assumption that was never reconciled for the pre-#1199 backlog; nothing in the pipeline asserts the invariant afterwards.

**Regression guard.** A post-void assertion inside restart_pipeline: after void_open_bets_at_reset, count(HYPOTHESIS#/PREDICTION# rows with status in OPEN_BET_STATUSES and tombstone=true and no matching CALIB#…#void row) must be 0, printed in the dry-run preview and failing the apply run. This is the process change; a one-time backfill of the 39 alone is not the fix. Owner: the restart-pipeline dry-run test that already sits beside the phase_taxonomy coverage assertion.

**Path-to-A step.** Run a one-time reconcile writing a cycle-stamped voided_at_reset row for each of the 39 orphans (stamped with the cycle that actually closed them), then land the post-void invariant assertion so no future reset can leave an open bet unrecorded.

**Verifier (CONFIRMED).** My own DDB scan on sk begins_with HYPOTHESIS# returns 46 rows: 39 status=pending/phase=pilot/tombstone=true (created 2026-05-10 through 2026-07-20, cycle stamps 1,2,4,6,8,9), 3 refuted/pilot, 2 archived/pilot, and exactly 2 open pending/phase=experiment (hypothesis_id genesis_prereg_h1/h2, created 2026-07-26). My query of the calibration partition shows all 6 hypothesis_void rows are genesis_prereg_h1/h2 at genesis 07-18/07-20/07-22, and the 07-27 reset wrote 38 prediction_void + 0 hypothesis_void — so all 39 are orphaned. deploy/restart_pipeline.py:472-482 `_is_open_untombstoned` returns False on any tombstoned row on the documented assumption that it 'already carries (or got) its own void row', which cannot be true for the 35 rows tombstoned before #1199 landed (82bb2dc4, 2026-07-17). Note my reproduction is slightly WORSE than the finder's: 4 rows created 2026-07-20 (post-#1199, cycle 9) were also tombstoned with no void row despite the void step running before the wipe (restart_pipeline.py:959-969), so the gap is not purely a historical backlog. Nothing asserts the post-void invariant.

#### qs-4 · ADJUSTED · sev **medium** · effort S · class B

**Finding.** Pre-registration — the platform's central credibility claim — is an attended, optional pipeline step, and 2 of the last 6 cycles started with no sealed prereg artifact at all.

**Evidence.** aws s3 ls s3://matthew-life-platform/generated/experiments/prereg/ → genesis-2026-07-19, genesis-2026-07-20, genesis-2026-07-27 only. Void-row genesis dates prove cycles also began 2026-07-18 (cycle 7) and 2026-07-22 (cycle 10); curl https://averagejoematt.com/experiments/prereg/genesis-2026-07-22.json → 404, genesis-2026-07-13.json → 404. deploy/restart_pipeline.py:790-791 seeds the prereg only under the opt-in `--with-preregistration` flag, and :1163-1167 prints the publish/stamp/lock steps as manual follow-ups. (Cycle 11's seal is intact and verifiable: local SHA adece752… == live artifact SHA == the published stamp; same for the channel-divergence prereg 57639f71… — the machinery is right, the trigger is optional.)

**Root cause.** deploy/restart_pipeline.py::build_post_verify_hooks (line 776-794) — with_preregistration defaults to False, so a reset that runs the whole 13-step pipeline still produces a cycle with no pre-registered bets unless the operator remembers the flag.

**Regression guard.** Flip the default to ON with an explicit `--no-preregistration` escape, and add the seal to deploy/restart_verify.py's checked surface (it already verifies the 95-URL v4 set): assert /experiments/prereg/genesis-<genesis>.json returns 200 and its SHA matches the published stamp. Owner: restart_verify, the layer that already gates a reset as complete.

**Path-to-A step.** Default the prereg seed ON in restart_pipeline and add the artifact+stamp fetch to restart_verify's pass criteria, so a cycle cannot be declared verified without a sealed pre-registration.

**Verifier (ADJUSTED).** Symptom reproduces but the count and the cause are both off. My aws s3 ls of generated/experiments/prereg/ shows genesis artifacts for 07-19, 07-20 and 07-27 only; the canonical cycle registry (CYCLE_GENESES, lambdas/web/site_api_data.py:100-112) lists cycles 6-11 as 07-13, 07-18, 07-19, 07-20, 07-22, 07-27 — so THREE of the last six cycles have no sealed artifact (07-13, 07-18, 07-22, all 404 live), not two. And the pipeline's own docstring block (restart_pipeline.py 'DELIBERATELY NOT FOLDED', ~lines 70-80) records publish_genesis_preregistration.py and genesis_prereg_stamp.py --apply as deliberately attended under the prereg/frozen-artifact dry-run-review posture (matching the reference_prereg_dry_run_review memory), so flipping --with-preregistration ON does NOT by itself produce a sealed public artifact.

**Corrected cause/evidence.** Corrected cause: two separate gaps, only one of which is a default-flag bug. (a) build_post_verify_hooks(with_preregistration=False) at restart_pipeline.py:776-791 makes SEEDING opt-in; (b) publish + SHA-stamp are intentionally excluded from the pipeline (documented attended posture) with no completion gate anywhere. The correct fix is therefore the verification half only: add the artifact+stamp fetch (200 + SHA match) to deploy/restart_verify.py's pass criteria so a cycle cannot be declared verified without a published seal; flipping the seed default is optional and does not close the gap on its own. Corrected numbers: 3 of the last 6 cycles unsealed.

#### qs-5 · CONFIRMED · sev **medium** · effort S · class A

**Finding.** The sealed, SHA-stamped pre-registration artifacts are reachable only by guessing the URL — no page on the live site links to /experiments/prereg/* .

**Evidence.** grep -rn 'experiments/prereg' across the repo returns only cdk/stacks/*.py (the CloudFront behavior), deploy/genesis_prereg_stamp.py and deploy/channel_divergence_prereg_stamp.py — zero hits in site/. site/assets/js/evidence_discovery.js:367 renders a 'frozen artifact ↗' link only from a per-experiment `pre_registration_url`, and curl /api/experiments shows 0 of 67 entries carry that field. /method/calibration's only outbound credibility link (evidence_intelligence.js:318-321, _OPEN_ARTIFACT_LINE) points at /method/grade-your-coach/, not at the seal. The strongest artifact the platform owns — a timestamped, hash-verifiable set of predictions made before the data existed — is invisible to the skeptic it was built for.

**Root cause.** deploy/genesis_prereg_stamp.py publishes to S3 and prints the verify command to the operator's terminal; no site surface or API field consumes public_artifact_url / public_stamp_url.

**Regression guard.** Extend the existing orphan/registry checks (the 'new page = FOUR registries' family) with a link test: every published /experiments/prereg/* object for the CURRENT genesis must be referenced by at least one page in the qa_manifest. Owner: deploy/smoke_test_site.sh content-smoke layer, which already asserts page/URL contracts.

**Path-to-A step.** Surface the current cycle's seal on /method/calibration and /method/predictions — one line with the artifact link, the SHA-256, and the copy-pasteable verify command already generated in the .sha256.json stamp.

**Verifier (CONFIRMED).** Reproduced: grep -rn 'experiments/prereg' across the repo (worktrees excluded) hits only cdk/stacks/role_policies.py:2816, cdk/stacks/web_stack.py:814-820, deploy/genesis_prereg_stamp.py, deploy/channel_divergence_prereg_stamp.py and the deploy/generated/*.sha256.json stamps — zero hits in site/. `grep -rno 'href="[^"]*prereg[^"]*"' site/` returns nothing. The only consumer of the artifact field is site/assets/js/evidence_discovery.js:367 (`x.pre_registration_url` → 'frozen artifact ↗'), and that field is produced only by lambdas/web/site_api_protocols.py:161 from a per-experiment `prereg_url`; my parse of the live /api/experiments payload shows 0 of 67 entries carry it. evidence_intelligence.js:318-321 _OPEN_ARTIFACT_LINE indeed points at /method/grade-your-coach/, not the seal. The genesis-2026-07-27 artifact is live (HTTP 200) but reachable only by guessing. Overlap context only, not a duplicate: open #1391 (Replication Kit, frontier cluster, do-not-refile) is a different scope.

#### qs-6 · ADJUSTED · sev **medium** · effort M · class A

**Finding.** Supplement 'science' bullets still state population efficacy claims as flat fact, including one that contradicts the item's own cited review.

**Evidence.** curl /api/supplements, scanning science[] for effect verbs with no hedge token: Apigenin — 'Reduces sleep onset latency and anxiety without grogginess' while its own challenges source (PMID 30875872, 'The Therapeutic Potential of Apigenin') is labelled in the same entry as 'evidence is predominantly preclinical'; L-Theanine — 'Promotes alpha brain waves, reduces anxiety without sedation'; Omega-3 — 'Reduces systemic inflammation, improves TG/HDL ratio'; NAC — 'Supports liver detoxification, reduces oxidative stress'; Collagen — '15g + vitamin C 30-60 min before exercise increases collagen synthesis'; Glycine — '2-3g before bed lowers core body temperature'. The #1217 guard covers only 'X% of Americans/people' prevalence claims, so unhedged efficacy statements pass untouched (the magnesium bullets it did cover are now correctly hedged).

**Root cause.** config/supplement_registry.json science[] arrays, rendered under 'the work — science, sources' by site/assets/js/evidence_body.js; tests/test_supplement_registry.py's _POP_PERCENT_RE only matches prevalence percentages, not efficacy verbs.

**Regression guard.** Widen the same offline guard: flag any science bullet containing an unhedged effect verb (reduces/increases/improves/lowers/prevents) unless the entry carries a `supports` source whose resolved title matches the claimed outcome. Owner: tests/test_supplement_registry.py — the guard already exists, it is scoped too narrowly.

**Path-to-A step.** Sweep the science bullets with a hedge-or-cite rule (the Magnesium entry is the model: 'Marketed as … but the direct evidence is a rodent study'), prioritising items whose own challenges source undercuts the bullet.

**Verifier (ADJUSTED).** The bullets exist verbatim in the live payload (I dumped all 66 science bullets), but the 'stated as flat fact' framing misreads the rendered surface. evidence_body.js:46-57 splits every item's sources into a displayed dissent list ('challenges it', shown FIRST, with the summary line reading 'incl. the dissent'), and my check confirms every item the finding cites carries a rendered challenges source — Apigenin's is precisely the 'evidence is predominantly preclinical' review the finding treats as a hidden contradiction; that pairing is the design, not a leak. Most items also carry an explicit limitation bullet ('Not yet confirmed in large RCTs', 'evidence promising but limited', 'Limited clinical evidence', 'Evidence in well-nourished populations is weak', 'Modest effect on fat loss'). Closed #1217 was scoped to factually WRONG quantitative prevalence claims (the 80%-of-Americans and BBB-exclusivity magnesium bullets), which are confirmed fixed, not to hedging style.

**Corrected cause/evidence.** What actually survives is much narrower and mostly finding 0 in disguise: for L-Theanine ('alpha brain waves') and Glycine ('lowers core body temperature') the supporting PMIDs (18296328, 22293292) resolve correctly and do support the bullet, so those are not unsupported claims at all. The genuinely unsupported bullets are unsupported because their citations are fabricated (NAC 'supports liver detoxification' → all three PMIDs wrong; Collagen '15g + vitamin C' → 27053525 is an mTORC1 paper). Fix the citations (finding 0) and this finding largely evaporates; the residue — Omega-3's 'Reduces systemic inflammation, improves TG/HDL ratio' backed only by two CVD-outcome trials — is a low-severity wording nit, not a medium-severity credibility defect.

#### qs-7 · CONFIRMED · sev **low** · effort S · class A

**Finding.** ADR-105 threshold provenance is computed and served but never rendered — the reader cannot tell a personal-variance band from an authored commitment.

**Evidence.** curl /api/character_config → 4 targets carry target_provenance {source: personal, method: percentile_band_p75, window_days: 365, n: 341-342} (sleep duration 8.47h, deep-sleep 25% with clamped bounds disclosed, REM 29.53%); the other 7 numeric targets (zone-2 150 min, protein 190 g, 5 sessions/wk, 3 strength days, 4 movement types, 4 protein meals, 4 reading days) carry behavioral:true and no provenance, which is correct classification. But grep -rn 'target_provenance' site/ returns NOTHING — no page renders the field, so the n=342-backed personal bands and the authored commitments render identically on the public character sheet. Served via lambdas/web/site_api_vitals.py:653-660.

**Root cause.** site/assets/js/evidence_character.js consumes the config for weights and mechanics copy but never reads target_provenance; the #1412 work stopped at the API boundary.

**Regression guard.** A rendering assertion in tests/visual_qa.py (or the AI-QA prompt for /method/character): when the payload carries target_provenance, the page must display the method and n. Owner: the visual-QA layer, which already gates rendered content.

**Path-to-A step.** Render the provenance chip next to each target — 'from your own 365-day distribution, p75, n=342' vs 'chosen commitment' — turning an already-paid-for credibility asset into visible proof.

**Verifier (CONFIRMED).** Reproduced: live /api/character_config contains 4 target_provenance objects (served by lambdas/web/site_api_vitals.py:668-669, gated on the dict shape), and `grep -rn target_provenance site/` returns zero hits. I also fetched the rendered /method/character/ page and grepped for percentile|p75|provenance|n=34x — no matches, confirming nothing renders it under any alternate wording. #1412 ('Baselines everywhere: character targets from personal variance') is CLOSED and delivered the API side; the render side is genuinely unshipped. Low severity is the right call — this is an unrealized asset, not a false statement.

#### qs-8 · CONFIRMED · sev **low** · effort M · class A

**Finding.** 63 of 67 experiment-library entries cite an author/journal/year string with no URL, so the public catalog's evidence is unclickable and unverifiable.

**Evidence.** curl /api/experiments → 67 entries; source_url is empty on 63 of them while evidence_citation carries strings like 'Wilkinson et al., Cell Metabolism 2020', 'Laukkanen et al., JAMA Internal Medicine …' (attached to id=active-recovery-protocol, a sauna trial cited for an active-recovery lever), 'Holt-Lunstad et al., PLOS Medicine 2010'. Only 4 entries carry a PMID — and 2 of those 4 are the fabricated mappings in finding 1 (23615780 tongkat-ali, 36482258 attributed to 'Yoshino et al., Science 2021' but resolving to a 2023 Chinese NMN RCT).

**Root cause.** config/experiment_library.json — evidence_citation was authored as prose with source_url left null for all but four entries; no schema rule requires a resolvable link.

**Regression guard.** Extend the citation-resolution test of finding 1 to experiment_library.json and require either a resolvable source_url or an explicit 'no direct study' label — the same rule, applied to the second registry. Owner: offline pytest.

**Path-to-A step.** Backfill source_url (or the honest no-study label) for the library, ordered by which entries are publicly promoted first (the 4 status=active ones are already rendered as ongoing protocols).

**Verifier (CONFIRMED).** My own parse of the live /api/experiments payload: 67 entries, 63 with a non-empty evidence_citation prose string and an empty source_url, 4 with a PMID URL (berberine-glucose 18442638 = correct 'Efficacy of berberine in patients with type 2 diabetes mellitus'; creatine-strength 28615996 = correct ISSN position stand; nmn-nad-precursor 36482258 = a real 2023 NMN RCT but attributed to 'Yoshino et al., Science 2021', a different paper; tongkat-ali-recovery 23615780 = the dentist-visits paper). So 2 of the 4 linked citations are wrong or mis-attributed, exactly as claimed. Root cause verified in config/experiment_library.json — no schema rule requires a resolvable link. Correctly rated low severity and it is the same fix family as finding 0.

#### qs-9 · ADJUSTED · sev **low** · effort S · class A

**Finding.** A near-duplicate pair survives the experiment-library dedupe, and the four 'ongoing protocols' shown publicly name three compounds absent from the actual supplement stack.

**Evidence.** curl /api/experiments → 67 entries (down from 71, so the prior dedupe landed) but zone2-150-min-week and zone-2-minimum both remain. Separately, /api/discoveries active_hypotheses = Tongkat Ali, NMN, Creatine, Berberine, rendered by site/assets/js/evidence_discovery.js:117-127 as 'Standing supplement protocols … long-horizon levers under continuous measurement' — while /api/supplements' 21-item stack contains only Creatine of the four. A reader comparing /protocols/discoveries with /protocols/supplements sees three levers claimed as continuously measured that the stack page does not list.

**Root cause.** config/experiment_library.json status=='active' (four entries, lambdas/web/site_api_ledger.py:157) is a second, unreconciled source of truth for 'what Matthew is taking', independent of config/supplement_registry.json.

**Regression guard.** A cross-registry consistency test: any experiment_library entry with pillar=='supplements' and status=='active' must have a matching non-paused supplement_registry key, or be relabelled. Owner: offline pytest alongside the registry guards.

**Path-to-A step.** Reconcile the two registries to one source of truth for the active stack, and merge the surviving zone-2 duplicate.

**Verifier (ADJUSTED).** Two claims, one dies. The dedupe claim is REFUTED: zone2-150-min-week (150 min/wk, 56 days, endpoint = pace-at-HR >5%) and zone-2-minimum (3 sessions/wk, 60 days, endpoints = RHR -3 bpm and HRV +8%) are distinct dose/endpoint designs, and that is exactly the standard the #1247 verifier applied when it kept the sauna 30d-vs-42d pair as legitimately distinct; #1247 is CLOSED and its named four pairs are gone (71→67 in 7c02b4b1). The cross-registry claim reproduces cleanly.

**Corrected cause/evidence.** Surviving defect: config/experiment_library.json holds 4 status=active entries (tongkat-ali-recovery, nmn-nad-precursor, creatine-strength, berberine-glucose, all pillar=supplements) which lambdas/web/site_api_ledger.py:152-170 serves as /api/discoveries active_hypotheses, rendered by evidence_discovery.js:117-127 as 'Standing supplement protocols … under continuous measurement' with an 'ongoing protocol' badge and 'active since 2026-02-09'. My parse of live /api/supplements shows a 21-item stack containing only Creatine — Tongkat Ali, NMN and Berberine appear nowhere in config/supplement_registry.json. Note also that /api/experiments maps status 'active'→'available', so the two public surfaces disagree about the same four rows. Drop the dedupe half; the finding is the two-sources-of-truth inconsistency alone (low severity).

**Path to A (grader's ranked actions):**

1. Citation-resolution gate + full sweep: land an offline pytest that resolves every PMID in config/supplement_registry.json and config/experiment_library.json against a checked-in id→title fixture and asserts token overlap with the claimed title/summary, then fix all 21 verified mismatches (relabel as 'open question — no direct study found' where no real paper exists). Zero standing cost, no new infra — ADR-103 clean; this is the single highest-leverage repair because 'click the citation' is the cheapest test a skeptic runs.
2. Publish the void denominator: add `voided:{n, by_cycle}` to /api/calibration and one rendered line on the Career card naming the 273 bets voided at resets. One payload field + one line of JS; it converts the platform's biggest survivorship hole into its most convincing honesty artifact.
3. Close the grade-or-void loop permanently: one-time reconcile of the 39 orphaned open hypotheses into cycle-stamped voided_at_reset rows, plus a post-void invariant assertion in restart_pipeline (open + tombstoned + unvoided == 0) that fails the apply run — the process fix, not the instance fix.
4. Make pre-registration structural, not attended: default seed_genesis_preregistration ON in restart_pipeline (with an explicit --no-preregistration escape) and add the sealed artifact + SHA-stamp fetch to restart_verify's pass criteria; then link the current seal from /method/calibration and /method/predictions so the strongest artifact stops being URL-guess-only.
5. Hedge-or-cite sweep of the supplement science bullets (widen the #1217 guard from prevalence percentages to unhedged efficacy verbs) and render target_provenance on the character sheet, so the personal-variance bands (n=342) are visibly distinguished from authored commitments.

**Coverage (what this lens did NOT examine).** Examined: live /api/supplements, /api/experiments, /api/calibration, /api/hypotheses, /api/discoveries, /api/correlations, /api/forecast, /api/vitals, /api/character_config, /api/cycle_compare, /api/benchmark_trends; all 58 unique supplement PMIDs + 6 active-experiment PMIDs resolved against NCBI eutils; DDB partitions SOURCE#calibration (296 rows), SOURCE#hypotheses (46 rows), PREDICTION# scan (2330 rows, 68 cycle-11 pending); the cycle-11 and channel-divergence prereg seals verified byte-for-byte (local SHA == live artifact SHA == published stamp); s3 ls of generated/experiments/prereg/; deploy/restart_pipeline.py void path; tests/test_supplement_registry.py; site/assets/js/evidence_intelligence.js, evidence_discovery.js, evidence_character.js; grading-stalled alarm + coach-prediction-evaluator log streams. NOT examined: the daily brief / email copy (17:00 UTC brief has not fired for Day 1), chronicle and Elena narrative text, coach dossier prompts and the ai_calls quality gate, MCP tool output text, /method/grade-your-coach's claimed Python↔JS bit-parity (I did not run the test vectors), the labs/PhenoAge/biology surfaces, statistical internals (FDR correction, EWMA forecast model, Brier binning code) beyond their served outputs, the ~40 PMIDs whose titles were topically plausible (checked at title level only — I did not read abstracts to confirm the specific quantitative claims), /api/protocols (empty on Day 1, not evaluable), the diary claims-ledger grading path (#1841, first compute pending), and any rendered-page visual verification (I read the JS renderers, not screenshots).

**Lens notes.** Dedup: nothing here maps to the do-not-refile list; gh issue searches for 'citation', 'PMID', 'supplement registry evidence' returned no open issue. #1216/#1217 are CLOSED (PR #1291, commit cc363a27) — finding 1 is REGRESSION-ADJACENT rather than a clean recurrence: the fix landed and the search-URLs really are gone, but the guard it shipped (tests/test_supplement_registry.py:71-92) validates URL SHAPE only, so a hallucinated but well-formed PMID passes; the guard that failed is the one the last review specified. Prior-run findings 4 (/method/benchmarks), 5 (calibration forecast fold-in) and 6 (experiment duplicates) are genuinely FIXED — benchmarks now says 'isn't wired to a live source yet … rather than inventing numbers' (evidence_intelligence.js:393) and the chronicle hook was retired (chronicle_render.py:633); calibration now serves interval_forecasts + career blocks; the library is 71→67 with one pair left. Prior finding 1 (bets vanish at reset) is HALF fixed — forward path implemented, historic backlog orphaned (finding 3). The cross-lens high finding on coach-prediction-evaluator IAM is RESOLVED: grading-stalled is OK since 2026-07-17 and the evaluator has log streams through 2026-07-27. Data-maturity caveats (Day 1, do not penalise): /api/correlations count=0 with gates{min_n:10,current_n:1}, /api/protocols empty, hrv_30d_n=1 with trend 'insufficient_data', platform season n=0 against career n=50, 2 pending prereg hypotheses and 68 pending coach predictions — all correct honest-empty machinery, and the 'Fresh slate — career: n=…' copy is verifiably true (68 PREDICTION# rows dated 2026-07-27 exist). No prior-cycle leakage found on any surface in this lens; cycle stamps on void rows correctly carry the CLOSING cycle. Dissent-worthy: I let a config-data defect (fabricated citations) dominate the grade over machinery that is otherwise A-grade — threshold provenance with n and window, a hash-verifiable prereg seal, a Brier/skill separation the disclosure explains honestly, an honestly-retired benchmarks board. A reviewer weighting engine quality over content quality would grade this B; I weight it C+ because the rubric's own F anchor is 'invented citations presented as studies', and a reader who clicks two links on /protocols/supplements has a coin-flip chance of landing on a paper about dentistry or whale falls.

### narrative — Voice & immersion (Narrative editor) — **B-**

*Trend: ▼ **down from B**.*

**Verifier on the grade:** All eight findings survive (seven confirmed, one adjusted-but-alive), including three high-severity Day-1 continuity/cast leaks on public surfaces plus a live fabricated-verdict pipeline — the surviving set fully supports the proposed B-, and arguably makes B- generous rather than harsh.

#### narrative-1 · CONFIRMED · sev **high** · effort M · class A

**Finding.** Webb's live Day-1 coaching-door analysis fabricates graded outcomes from zero data: it declares 'That's a prediction miss, and I'm logging it as one' and 'protein adherence looks better than my baseline predicted' while the SAME text admits 'I have zero food logs. No calories, no macros... Nothing' — and the false verdict is now persisted as THREAD#2026-07-27#lunch_protein_prediction_miss, feeding future generations, and baked into the committed noscript ('The nutrition coach corrected a missed prediction', site/coaching/index.html:55). Recurrence of the #946/#1194 continuity-leak class via a write-time path: STANCE#latest (as_of 2026-07-26, phase=experiment, NOT tombstoned) carries the wiped pilot cycle's adherence continuity ('hitting protein and calorie targets more consistently than I initially predicted') and per coach_narrative_orchestrator.py step-10 comment 'leads the generation framing'.

**Evidence.** curl /api/coach_analysis?domain=nutrition (full analysis text reproduced); aws dynamodb get-item COACH#nutrition_coach/STANCE#latest (phase=experiment, tombstone=null, generated_at 2026-07-26T17:01Z, pre-genesis); THREAD#2026-07-27#lunch_protein_prediction_miss in query output; site/coaching/index.html:55 noscript; lambdas/coach/coach_narrative_orchestrator.py:489-492 (stance leads framing)

**Root cause.** ai_calls._enforce_quality_gate (ADR-108, blocking) has no deterministic zero-data check — it approved a narrative asserting graded outcomes ('prediction miss', adherence 'better than predicted') for a domain whose current-cycle data count is 0; upstream, the pre-genesis STANCE#latest singleton written 07-26T17:01Z escaped the EXPERIMENT_SCOPED tombstone (phase_taxonomy.py:347 says COACH#* is scoped) because it was regenerated during the countdown window after the tagger ran

**Regression guard.** A deterministic pre-gate rule in the coach quality gate: when the domain's current-cycle observation count is 0, block verdict/outcome vocabulary (miss/hit/adherence-looks) and regenerate-or-hold — the existing ADR-108 blocking machinery owns this; plus a restart_verify assertion that no COACH#* singleton with pre-genesis generated_at survives untombstoned

**Path-to-A step.** Add the zero-data verdict check to _enforce_quality_gate (reuses the live blocking gate, no new standing cost — ADR-103: extension of existing machinery); tombstone-or-regenerate STANCE#latest/OUTPUT#2026-07-26 for all coaches and delete the false lunch_protein_prediction_miss thread so the fabricated verdict stops feeding forward

**Verifier (CONFIRMED).** Independently reproduced every link in the chain: live /api/coach_analysis?domain=nutrition simultaneously asserts 'That's a prediction miss, and I'm logging it as one' and 'protein adherence looks better than my baseline predicted' while admitting 'I have zero food logs... Nothing'; aws dynamodb get-item shows COACH#nutrition_coach/STANCE#latest with phase=experiment, no tombstone attribute, generated_at 2026-07-26T17:01:14Z (pre-genesis, exactly one 17:01Z cron-tick before the Day-1 generation at 2026-07-27T17:01:15Z) and evidence_basis carrying fabricated adherence claims ('Protein intake hitting floor on reported days', 'Logging fidelity appears high'); THREAD#2026-07-27#lunch_protein_prediction_miss exists in the query output alongside 13 sibling threads; site/coaching/index.html noscript carries 'The nutrition coach corrected a missed prediction'; phase_taxonomy.py:347 classes COACH#* EXPERIMENT_SCOPED; coach_narrative_orchestrator.py step 10 says STANCE#latest 'leads the generation framing'; ai_calls._enforce_quality_gate (line 1356) is a regenerate-or-hold loop over an LLM gate with no deterministic zero-data verdict check. Not a duplicate: prior leak-class issues #946/#1085/#1200 are all CLOSED — this is a live recurrence via the countdown-window regeneration path, exactly the hunt-order class.

#### narrative-2 · CONFIRMED · sev **high** · effort S · class A

**Finding.** The public game-rules page /method/game/ presents the dead pilot cast as current pillar owners — 'owner Dr. Peter Attia' (a REAL public clinician presented as platform staff) for metabolic and 'owner Coach Maya Rodriguez' for mind — contradicting the live roster (Dr. Amara Patel, Dr. Nathan Reeves) one door away; kill-on-sight adjacent (real person's name as staff on a public surface).

**Evidence.** curl https://averagejoematt.com/method/game/ → 'owner Dr. Peter Attia' (metabolic pillar card), 'owner Coach Maya Rodriguez' (mind pillar card) vs curl /api/coaches → glucose/metabolic = Dr. Amara Patel, mind = Dr. Nathan Reeves; source config/character_sheet.json:114,137

**Root cause.** config/character_sheet.json:114 ('Dr. Peter Attia') and :137 ('Coach Maya Rodriguez') never received the pilot-era cast rename (same rename that mapped andrew_huberman → Kai Nakamura in chronicle_email_sender_lambda.py:153); /method/game/ is generated from this config (known: character_sheet.json feeds the generated game page)

**Regression guard.** A cast-consistency unit test: every human name in owner/coach/byline fields across configs (character_sheet.json, board_of_directors.json, integrator hardcodes) must resolve to the persona registry — would also have caught finding 5; Unit Tests layer owns it

**Path-to-A step.** Rename the two owners to the canonical roster (Patel, Reeves), regenerate /method/game/, and land the cast-consistency test

**Verifier (CONFIRMED).** Reproduced live: /method/game/ metabolic pillar card reads 'owner Dr. Peter Attia' and mind pillar 'owner Coach Maya Rodriguez'; /api/coaches roster has 9 personas with metabolic_health = Dr. Amara Patel and behavioral_psychology = Dr. Nathan Reeves, no Attia/Rodriguez; config/character_sheet.json:114 and :137 carry the stale names and the game page is generated from that config (established memory reference); the pilot-era rename precedent (andrew_huberman → Dr. Kai Nakamura) verified at lambdas/emails/chronicle_email_sender_lambda.py:153 — the finder's path said lambdas/email/, a trivial typo. Aggravating: the coaching page publicly states 'no real people are depicted' while a real clinician's name sits as pillar owner one door away. No open duplicate issue (gh search Attia/Nakamura: empty).

#### narrative-3 · CONFIRMED · sev **high** · effort S · class A

**Finding.** The wiped pilot cycle's 190g protein target survives in maintained prompt-feeding and page-generating configs and surfaces live as current: /method/game/ nutrition pillar shows 'protein total … target grams 190' and Webb's live analysis closes 'The 190g target and the current meal structure stay in place' — while the sealed cycle-11 canon is a 170g floor at 1,500 kcal (his own cross_domain_note, the sealed prereg, and user_goals.json all say 170).

**Evidence.** curl /method/game/ → 'target grams 190'; curl /api/coach_analysis?domain=nutrition → 'The 190g target … stay in place' + cross_domain_note '170g protein'; curl /experiments/prereg/genesis-2026-07-27.json → four '170', zero '190'; config/character_sheet.json:93 (target_grams: 190), config/board_of_directors.json:408 ('protein is protected (190g target)') fed to prompts via lambdas/board_loader.py:153; config/user_goals.json:100-101 (daily_protein_min_g: 170)

**Root cause.** Stale maintained literals: config/character_sheet.json:93 and config/board_of_directors.json:408 still carry the pilot plan; restart_pipeline's doc/config sync does not sweep plan-number literals against user_goals.json (the known maintained-literal-drift class), so the dead target both renders publicly and enters coach prompt context

**Regression guard.** A restart_verify / qa_smoke rule: plan literals (protein, kcal, steps) in configs and generated pages must match user_goals.json + the sealed prereg — deterministic grep-class check, zero AI cost; the character-engine's own config validation should own it

**Path-to-A step.** Update both configs to 170g, regenerate /method/game/, and add the plan-literal reconciliation step to the restart pipeline's sync

**Verifier (CONFIRMED).** All literals reproduced: live /method/game/ nutrition pillar shows 'target grams 190'; live Webb analysis closes 'The 190g target and the current meal structure stay in place' while its own cross_domain_note says '1500-calorie target with 170g protein requirement'; sealed prereg genesis-2026-07-27.json contains '170' four times and '190' zero times; config/character_sheet.json:93 target_grams=190, config/board_of_directors.json:408 '(190g target)' fed into prompts via board_loader's relationship_to_matthew field, config/user_goals.json:100-101 daily_protein_min_g=170 with a note explicitly calling 170 the realistic floor. The maintained-literal-drift root cause matches the known class. No open duplicate (gh search: empty).

#### narrative-4 · CONFIRMED · sev **medium** · effort S · class B

**Finding.** Prologue Part III 'The Plan, On the Record' — the chain-of-authority terminus that Part I's editor's note points readers to — asserts '317.61 pounds on the morning of Day 1' (and stats_line '317.61 lbs at the start') with NO reconciliation note, while the real Day-1 weigh-in was 321.09 (live vitals 321, home hero 'From 321 lb'); a binge reader crossing from the story door to the cockpit hits a 3.5 lb contradiction on the experiment's most important number, in a document whose whole point is 'nothing here can be quietly revised'.

**Evidence.** curl /journal/posts/week-03/ → 'The destination. 317.61 pounds on the morning of Day 1.' and grep for 321/Editor/Calloway → all ABSENT; /journal/posts.json Part III stats_line; curl /api/vitals → weight_lbs 321, weight_as_of 2026-07-27; Part I excerpt shows the editor's-note reconciliation pattern already exists ('the figures that actually govern the experiment are the ones he put on the record')

**Root cause.** The restart pipeline's baseline-supersede step (override 317.61 → real weigh-in 321.09, recorded in project memory as 'override superseded') updates constants and live surfaces but has no step that sweeps frozen prologue artifacts with an appended editor's note — Part I got the note manually, Part III did not

**Regression guard.** restart_pipeline: when the genesis weigh-in supersedes an override, emit the dated editor's-note block onto any frozen prologue artifact quoting the working number (deterministic string scan for the superseded literal); smoke_test_site content check that the superseded weight literal never appears un-annotated

**Path-to-A step.** Append a Margaret Calloway editor's note to Part III (matching Part I's pattern): the real Day-1 scale read 321.09, the 317.61 working number and its waypoints re-anchor from it — the frozen text stays verbatim, the note reconciles it; wire the supersede-sweep into the restart pipeline

**Verifier (CONFIRMED).** Verbatim reproduction: /journal/posts/week-03/ contains '<strong>The destination.</strong> 317.61 pounds on the morning of Day 1.' (my first grep missed it only because a <strong> tag splits the sentence) plus the stats_line '317.61 lbs at the start' in posts.json, with ZERO occurrences of 321, Calloway, or any editor's note on the page — while /api/vitals serves weight_lbs 321, weight_as_of 2026-07-27, and the page's own frame is 'nothing here can be quietly revised later'. Part I ('Before the Numbers') does contain the Calloway editor's-note pattern, confirming the asymmetry. git log on the supersede commit (f06b8221, 317.61 → 321.09) shows constants/site regen but no prologue sweep — root cause verified. Distinct from open #1243 (Part II read-aloud carrying the superseded genesis DATE, a different artifact and number) — overlap-adjacent context only, not a duplicate.

#### narrative-5 · CONFIRMED · sev **medium** · effort M · class A

**Finding.** Two different characters occupy the board-lead role on the same door: the live coaching page signs 'the week's call · Dr. Kai Nakamura' (also the month/arc byline), while the roster one tab away ('The Team', /api/coaches) has no Nakamura and bills Dr. Eli Marsh (lead tier, added by closed #1112) as the one who 'turns eight specialists' reads into one coherent plan, and Matthew's single point of contact' — a reader cannot reconcile who runs the board, and Nakamura has no dossier, portrait, or team entry anywhere.

**Evidence.** site/coaching/index.html:55 noscript ('The week's call · Dr. Kai Nakamura', live-served); curl /api/coaches → 9 personas, no Nakamura, eli_marsh tier=lead; curl /api/coach/eli_marsh → full PI dossier; lambdas/web/site_api_coach.py:2484,2530 (hardcoded 'Dr. Kai Nakamura'); lambdas/intelligence/integrator_prompts.py:43 ('You are Dr. Kai Nakamura, Integrative Health Director'); gh issue #1112 (closed — added Marsh, never reconciled the integrator byline)

**Root cause.** #1112 introduced eli_marsh as the roster lead without retiring or registering the pre-existing integrator persona: integrator_prompts.py + two site_api_coach.py hardcodes still attribute the weekly/monthly/arc synthesis to Nakamura, who was never added to the persona registry the roster serves

**Regression guard.** The same cast-consistency test as the Attia finding: every byline/coach_name literal must resolve to the persona registry — Nakamura fails it today

**Path-to-A step.** Pick one canon (simplest: rename the integrator outputs and hardcodes to Dr. Eli Marsh, whose bio already claims the synthesis role) — one prompt file + two hardcodes + noscript regeneration; no new machinery

**Verifier (CONFIRMED).** Reproduced in full: site/coaching/index.html noscript live-serves 'The week's call · Dr. Kai Nakamura'; /api/coaches returns 9 personas with no Nakamura and eli_marsh at tier=lead; hardcoded 'Dr. Kai Nakamura' at lambdas/web/site_api_coach.py:2484 and :2530 (plus a THIRD instance the finder missed at lambdas/web/site_api_lambda.py:849, strengthening the finding); integrator_prompts.py:43/89/116 all open 'You are Dr. Kai Nakamura, Integrative Health Director'; gh issue #1112 is CLOSED (2026-07-12, added Marsh as lead on the by-coach surface) and never touched the integrator byline. No open duplicate.

#### narrative-6 · CONFIRMED · sev **medium** · effort S · class A

**Finding.** Coach voice register breaks within the same card list: Dr. Nathan Reeves' entire live analysis is third-person meta-voice ('The coach pivots from data to ownership… the coach refuses to interpret it… The coach isn't asking you…') and the baked board-read also renders Park and Webb in third person ('the sleep coach encountered a data paradox', 'The nutrition coach corrected a missed prediction') while Chen and live-Webb speak first person — the summarizer's register leaks into the coach's mouth, eroding the personas' blind distinguishability.

**Evidence.** curl /api/coach_analysis?domain=mind → full third-person text reproduced; site/coaching/index.html:55 noscript (mixed registers in one list); prompt at lambdas/coach/coach_state_updater.py:488-493 ('Preserve the coach's distinctive voice' — no structural first-person requirement)

**Root cause.** coach_state_updater.py's observatory_summary extraction (item 8 of the extraction prompt) relies on a prose instruction with no deterministic check — the documented prompt-rules-can't-guarantee-structure failure: the extractor drifts into summary-of-the-coach register and nothing rejects it

**Regression guard.** Deterministic post-check on observatory_summary: reject/regenerate any summary whose subject is 'The coach' / 'the {domain} coach' (regex, zero AI cost on pass) — the extraction pipeline itself should own it, same reflex as the anti-pattern check it already runs (item 7)

**Path-to-A step.** Add an explicit 'write in the coach's first person; never refer to the coach in third person' instruction PLUS the deterministic regex reject in the extraction pipeline

**Verifier (CONFIRMED).** Reproduced: live /api/coach_analysis?domain=mind attributed to Dr. Nathan Reeves is entirely third-person meta-voice ('The coach pivots from data to ownership… the coach refuses to interpret it… The coach isn't asking you…'), while live Webb speaks first person; the coaching noscript mixes registers in one list ('the sleep coach encountered a data paradox', 'The nutrition coach corrected a missed prediction' vs Chen's first-person entry). Root cause verified in code: site_api_coach.py:1682 prefers observatory_summary as the served analysis text, and the extraction prompt (coach_state_updater.py, item 8) has only the prose instruction 'Preserve the coach's distinctive voice' with no structural first-person requirement or deterministic post-check — the documented prompt-rules-can't-guarantee-structure failure class.

#### narrative-7 · ADJUSTED · sev **low** · effort M · class A

**Finding.** Same-day sleep numbers contradict across adjacent surfaces with no night scoping: the weekly priority credits 'a 7.5-hour sleep', the sleep coach card says 'duration at 6.58 hours / efficiency 93.81%', a nutrition thread says 'Sleep efficiency at 79.55%', and /api/vitals shows 8.9 h for the night of 07-26 — four numbers a Day-1 reader takes as the same night, none labeled with which night it describes.

**Evidence.** curl /api/weekly_priority ('a 7.5-hour sleep'); curl /api/coach_analysis?domain=sleep ('efficiency came in at 93.81%, duration at 6.58 hours', no night label); THREAD#2026-07-27#sleep_efficiency_nutritional_driver ('79.55%'); curl /api/vitals (sleep_hours 8.9, night_of 2026-07-26)

**Root cause.** Coach/integrator narrative generation quotes sleep metrics without an as-of/night qualifier and no reader-truth check compares narrative numbers against the vitals of a stated night — the same gap the 2026-07-16 ai-quality lens proposed a reader_truth_qa rule for (proposal only; no open issue found via gh search, so the guard was never landed)

**Regression guard.** The reader_truth_qa (nightly ADR-104 surface) rule proposed on 07-16: any narrative sleep/recovery/HRV figure must carry a night/as-of label, and labeled values must match that night's stored vitals within tolerance

**Path-to-A step.** Land the reader_truth_qa as-of rule and add 'always name the night a sleep figure describes' to the coach generation contract

**Verifier (ADJUSTED).** The four contradictory numbers all reproduce exactly (weekly_priority 'a 7.5-hour sleep'; sleep card 'efficiency came in at 93.81%, duration at 6.58'; THREAD#2026-07-27#sleep_efficiency_nutritional_driver '79.55%'; /api/vitals sleep_hours 8.9 night_of 2026-07-26), but the claim that NONE is labeled with its night is wrong: the sleep coach analysis explicitly anchors 'sleep-onset timestamp shows 07:00:14 UTC on July 26th' and repeatedly says 'last night', and it labels 79.55% as 'the single prior night I was working from'.

**Corrected cause/evidence.** The real defect is narrower and partly worse: (a) the LABELED surfaces contradict each other for the same night — the sleep card's 6.58 h/93.81% vs vitals' 8.9 h for night-of 07-26 is irreconcilable under any efficiency arithmetic; (b) the integrator's unlabeled '7.5-hour sleep' exactly equals the 7.5 h sleep-duration TARGET on /method/game/, suggesting a target-anchored fabricated actual; (c) the nutrition thread quotes the prior night's 79.55% with no night label adjacent to the current night's 93.81%. The proposed reader_truth_qa as-of/tolerance guard remains the right fix; severity low stands.

#### narrative-8 · CONFIRMED · sev **low** · effort S · class A

**Finding.** The story hub's 'newest first' chronicle list scrambles the prologue reading order within the shared 2026-07-26 date: Part II renders above Part III, so a reader descending the list encounters II → III → I and infers Part II is the later installment when Part III (the plan, the seal) is the finale.

**Evidence.** curl https://averagejoematt.com/story/ → 'newest first … 2026-07-26 — The Night Before Everything · Prologue · Part II / 2026-07-26 — The Plan, On the Record · Prologue · Part III'; /journal/posts.json order II, III, I

**Root cause.** The posts feed (built by the chronicle build path that writes journal/posts.json) tie-breaks same-date posts by an ordering (likely slug/insertion) that ignores the Part sequence — week fields are themselves inconsistent (Part II week:1, Parts I/III week:0)

**Regression guard.** A feed-order unit test on the chronicle builder: same-date posts sort by explicit part/sequence number; qa_smoke content check that Prologue parts list in ascending part order within a date

**Path-to-A step.** Add a sequence field to the post records and use it as the same-date tie-break in the builder and story.js

**Verifier (CONFIRMED).** Reproduced live: /story/ carries the literal 'newest first' label and lists 2026-07-26 'The Night Before Everything · Prologue · Part II' ABOVE 2026-07-26 'The Plan, On the Record · Prologue · Part III', then Part I (2026-07-21) — a descending reader meets II → III → I. posts.json order is II, III, I with the inconsistent week fields exactly as claimed (Part II week=1, Parts I/III week=0), which is consistent with a (date, week)-style tie-break ignoring part sequence. No open duplicate issue.

**Path to A (grader's ranked actions):**

1. Add the deterministic zero-data verdict check to the existing ADR-108 blocking quality gate (ai_calls._enforce_quality_gate): no graded-outcome vocabulary when the domain's current-cycle observation count is 0 — regenerate-or-hold; tombstone the surviving pre-genesis coach singletons (STANCE#latest, OUTPUT#2026-07-26) and the false lunch_protein_prediction_miss thread (ADR-103: extends live machinery, no new standing cost)
2. One cast, one canon: a persona-registry consistency unit test over every owner/byline/coach_name literal in configs and hardcodes; fix the three violations it finds today (Attia→Patel and Rodriguez→Reeves in character_sheet.json, Nakamura→Marsh in integrator_prompts.py + site_api_coach.py) and regenerate /method/game/ + the coaching noscript
3. Plan-literal reconciliation in the restart pipeline's sync step: sweep protein/kcal/step literals in maintained configs (board_of_directors.json, character_sheet.json) against user_goals.json + the sealed prereg at every reset — kills the 190g-vs-170g contradiction at the root, deterministic and free
4. Append the editor's-note reconciliation to Prologue Part III (the Part I pattern): the real Day-1 scale read 321.09 superseding the 317.61 working number, waypoints re-anchored — and make the baseline-supersede step of restart_pipeline emit this note automatically on any frozen artifact quoting the superseded literal
5. Land the reader_truth_qa as-of/night-scope rule (proposed 07-16, never shipped): narrative sleep/recovery figures must name their night and match that night's stored vitals — extends an existing nightly deterministic QA layer, zero AI cost

**Coverage (what this lens did NOT examine).** NOT examined: email narrative surfaces (daily brief, digests, Monday compass — no live email inspected); podcast script/audio content (epic #1737 territory); Elena's pending chronicle drafts for the coming Wednesday (chronicle generation tier-2 paused); the /data/ topic-page editorial and /story/timeline//attempts//about in depth (skimmed hub level only); by-coach detail pages for 6 of 9 coaches (sampled nutrition, mind, sleep in full); OG share-card copy; MCP tool prose; board_ask live generation (write endpoint — skipped under read-only + cost discipline); voice-fidelity scoreboard evidence (n=0 post-reset by design); the legacy tree (excluded by design). AWS reads were limited to the nutrition coach's COACH# partition — other coaches' STANCE/THREAD partitions likely carry the same pre-genesis-singleton pattern (mechanism verified for nutrition only; the sleep coach thread 'Recovery score improved from 29% to 60%' also narrates cross-seam continuity I did not fully trace).

**Lens notes.** Dedup/overlaps: #1243 (Prologue Part II READ-ALOUD orphaned with superseded genesis date) is known/owner-gated — my finding 4 is the distinct Part III weight-number gap, not refiled audio; podcast surfaces left to epic #1737; nothing here overlaps #1872/#1863/#1668/#1619/#1563/#1461. Verified FIXED from the 2026-07-16 baseline (no regression): /api/state_of_matthew now honest available:false; predict-the-week current (W30, prereg-anchored, sha-verified); dashboard excerpt truncation now carries ellipsis. Finding 1 is a RECURRENCE of the #946/#1194 class via a path the fix didn't cover — read-side guards (with_phase_filter) are correctly in place in both the orchestrator and the summarizer; the leak happened at WRITE time during the countdown window, when the 07-26 coach run re-distilled pilot continuity into fresh experiment-stamped singletons. Tier-2 posture: pause behavior is correctly disclosed everywhere I looked — coachAsOf 'as of {date} — refresh paused (budget guard)' + receipts link (#802/#1397), board-ask 'paused for the rest of the month… back on the 1st', SOM 'honest-absent until the first Sunday run' — pause copy quality is a genuine strength, not filed. Data-maturity caveats (not penalized): coach track records 'accruing', scorecard/calibration honest-empty, first SOM Sunday 08-02, month rollup honest-absent. Genuine voice strengths: home-page loop copy, the diary-shelf consent prose, Part II's verbatim-numbers disclosure, and Webb/Chen's distinct first-person registers are excellent. Unverified suspicions (not filed): Webb's analysis refers to Dr. Amara Patel as 'he' ('any glucose signal he's collecting') — I could not verify Patel's canonical gender from the served bio, worth a canon check; sleep coach's 'Recovery score improved from 29% to 60%' thread may narrate a cross-seam comparison (29 is the 07-26 pre-genesis reading) — same class as finding 1, mechanism unconfirmed for sleep. Dissent-worthy: the 07-26 intake threads (energy-crash mapping, constraint inventory) read as a deliberate, well-executed lead-in — the countdown-window coach engagement is good product; the defect is only that its regenerated singletons launder pilot continuity past the phase filter.

### security — Security & privacy lead — **NOT GRADED**

This lens never ran (credits exhausted). Prior grade 2026-07-16: **A-**. The delta run must
grade it from scratch against its persisted 2026-07-16 rubric anchors.

### a11y — Accessibility — **A-**

*Trend: = held at A-.*

**Verifier on the grade:** All four findings survive in substance (two confirmed verbatim, two adjusted on root-cause/magnitude details only), so the surviving set — one real high-severity flagship-page AA failure absorbed by the baseline, plus three narrow guard-coverage gaps in otherwise strong #1433/token/landmark machinery — still supports the proposed A-.

#### a11y-1 · CONFIRMED · sev **high** · effort S · class A

**Finding.** The cockpit's Month/Journey scope buttons — functional, enabled controls on the flagship tier-1 door — fail WCAG AA in BOTH themes: opacity 0.6 de-emphasis blends the already-faint ink-faint label down to 2.84:1 (dark) and 2.34:1 (light) at 15.3px normal-size text (needs 4.5:1; fails even the 3:1 large-text bar). The failure has been absorbed into the axe baseline since 2026-07-19 so it never gates.

**Evidence.** Live axe run 2026-07-28 (dark, 1440x900): color-contrast serious, 2 nodes, targets button[data-scope="month"]/[data-scope="journey"] on https://averagejoematt.com/cockpit/; computed styles read live in both themes (dark ink-faint rgb(152,141,120) op 0.6 over page rgb(14,12,8) = 2.84:1; light rgb(111,103,87) op 0.6 over rgb(244,239,228) = 2.34:1 — WCAG math in transcript); buttons have disabled=false, aria-disabled=null (announced as fully operable). tests/a11y_baseline.json '/cockpit/' color-contrast 2 nodes baselined.

**Root cause.** site/assets/css/cockpit.css:94 — `.scope-btn.scope-deep { opacity: 0.6; font-size: 0.9em; /* fs-ok: deliberate de-emphasis below the label size */ }` (P2.2 'quieter deeper scopes'): de-emphasis implemented as whole-element opacity on top of --ink-faint text, which only clears AA at full opacity (5.97:1 dark / 4.88:1 light).

**Regression guard.** The #1433 axe gate in tests/visual_qa.py already owns this class — it is disabled here only by the baselined (/cockpit/, color-contrast) ledger entry. After the fix, remove that entry via --update-baseline so the existing gate reds any recurrence; tests/test_token_contrast.py cannot see it (opacity composites are out of its token-pair scope), so the axe layer is the correct owner.

**Path-to-A step.** Drop the opacity from .scope-deep and keep the 0.9em size (full-opacity --ink-faint already reads quieter than the active .is-active ink and passes AA in both themes) — a one-line CSS change, then unbaseline /cockpit/ color-contrast. No new machinery; ADR-103-neutral.

**Verifier (CONFIRMED).** Independently reproduced everything: my own live axe run (2026-07-28, chromium 1440x900) returns color-contrast serious, 2 nodes, targets button[data-scope="month"]/[data-scope="journey"] on /cockpit/ in BOTH dark and light schemes; my live computed-style read shows opacity 0.6, 15.3px, disabled=false, aria-disabled=null, colors/backgrounds matching the tokens (site/assets/css/tokens.css: dark --ink-faint #988D78 on --page #0E0C08, light #6F6757 on #F4EFE4); my own WCAG math gives 2.84:1 dark / 2.34:1 light composited (5.97/4.88 at full opacity — the proposed one-line fix is sound). Root cause verified verbatim at site/assets/css/cockpit.css:94 (.scope-btn.scope-deep { opacity: 0.6; ... }). The /cockpit/ color-contrast entry sits in tests/a11y_baseline.json (2 nodes, captured 2026-07-19) so the #1433 gate never reds on it. No open or do-not-refile issue covers it (gh issue searches for a11y/contrast/axe returned zero).

#### a11y-2 · ADJUSTED · sev **medium** · effort S · class B

**Finding.** The committed a11y debt ledger is stale in the good direction and that staleness is a live hole in the guard: ~64 pages still carry baselined 'serious color-contrast' entries whose violations no longer exist on the live site, so a NEW serious contrast regression on any of those pages would be classified 'baselined' and pass the gate; the harness has printed 'a11y fixed vs baseline — shrink the ledger' warnings on every sweep for ~9 days with no shrink and no open issue tracking the burn-down.

**Evidence.** tests/a11y_baseline.json (captured 2026-07-19, untouched since — git log: only commit 1ebbb905) vs live axe reruns 2026-07-28: /gear/ 86 baselined nodes → 0, /method/registry/ 85 → 0, /data/character/ 60 → 0, /method/game/ 60 → 0, /data/badges/ 41 → 0, plus 8 more pages clean (transcript); gate key is (page, rule-id) per tests/a11y_audit.py:96-114 so baselined ids never gate; the fixed-vs-baseline warning path is tests/visual_qa.py:689-692; gh issue searches for a11y/contrast/axe/ledger return zero open issues.

**Root cause.** Process, not code: #1433 shipped the ledger with an explicit deliberate-shrink path (`python3 tests/visual_qa.py --update-baseline`, a11y_audit.py:117-160) but no ritual or owner ever runs it — the bulk of the debt was fixed as a side effect of 898e566f (fix(wall): staged-card contrast — dim the viz, never the text) AFTER the 07-19 capture, and the resulting per-run 'shrink the ledger' warnings are advisory output nobody triages.

**Regression guard.** The signal already exists (the per-page 'a11y fixed vs baseline' warning); the missing piece is a consumer: add ledger-shrink triage to the weekly full-surface visual-qa run's report handling (or the /wrap warning check) so unactioned 'fixed' warnings become a visible action item instead of scrolling by.

**Path-to-A step.** One reviewed PR running --update-baseline over the full surface now — restores real gating on ~64 pages at zero standing cost. Data-maturity caveat: keep (or re-verify after the cycle fills) the /data/character/ and /data/badges/ entries, since their current cleanliness partly reflects Day-1 wiped content whose tier-colored text returns as the cycle progresses.

**Verifier (ADJUSTED).** The structural masking hole is real and I reproduced it, but two evidence claims fail: (a) /method/game/ still shows 60 LIVE serious color-contrast nodes in my 2026-07-28 axe run — the finder's '/method/game/ 60 → 0' does not reproduce, so that entry is NOT stale and must survive any --update-baseline PR; (b) the '~9 days of warnings with no shrink' claim contradicts the finder's own root cause — the bulk fix 898e566f landed 2026-07-26 16:26 PT (~1.5 days before this review) and /data/character/ + /data/badges/ only went clean at the 07-27 cycle-11 reset wipe, so at most one or two sweeps have printed the shrink warnings.

**Corrected cause/evidence.** Confirmed core: tests/a11y_audit.py:106-114 keys the gate on (page, rule-id) only, so any page with a now-stale baselined color-contrast entry would classify a NEW serious contrast regression as 'baselined' and pass; my spot checks confirm staleness on /gear/ (86→0), /method/registry/ (85→0), /data/character/ (60→0), /data/badges/ (41→0), /data/, /story/, /coaching/team/, /data/vitals/ (9 of 10 checked pages clean of live color-contrast); tests/a11y_baseline.json is untouched on main since 1ebbb905 (2026-07-19) and gh shows zero open tracking issues. Corrections: the staleness window is ~1.5 days (post-898e566f 2026-07-26 + the 07-27 reset), not ~9 days, and /method/game/ (60 live serious nodes) must be excluded from the shrink — the finder's own /data/character//badges/ Day-1 caveat applies even more strongly there since /method/game/ is regenerated from character_sheet.json.

#### a11y-3 · CONFIRMED · sev **medium** · effort S · class A

**Finding.** The browser a11y audit never runs in light theme: both Playwright contexts hardcode color_scheme="dark", so axe's rendered-contrast check — the only layer that can see the opacity/color-mix composite failure class actually observed on this site — has zero light-theme coverage; the token pytest covers only the 10 token hex pairs.

**Evidence.** tests/visual_qa.py:921-928 (both mobile and desktop contexts pass color_scheme="dark"; no light context anywhere in the file); CI invocations at .github/workflows/site-deploy.yml:194, ci-cd.yml:875, visual-qa.yml:151, webkit-mobile-qa.yml:119 all use those defaults; finding 1 measures 2.34:1 in light — a light-theme AA failure no automated layer can currently observe (my manual light-theme axe run of 7 pages was otherwise clean, transcript).

**Root cause.** tests/visual_qa.py context construction (lines 921-928) — dark-only by original design of the screenshot sweep; when the #1433 axe audit was bolted onto capture_page it inherited that single-scheme context without a theme dimension.

**Regression guard.** This IS the guard gap: once a light context exists, the same #1433 gate + baseline machinery covers light with no new moving parts. tests/test_token_contrast.py stays the fast both-themes token layer; axe-in-light becomes the rendered layer.

**Path-to-A step.** Alternate the weekly full-surface visual-qa run between dark and light (one-line scheme parameter driven by week parity), or add a light-scheme pass over just the 6 tier-1 doors to the deploy sweep — same runner, same minutes envelope, ADR-103-clean (no new standing system, one parameter on an existing run).

**Verifier (CONFIRMED).** Reproduced every element: tests/visual_qa.py lines 925 and 928 hardcode color_scheme="dark" in both (mobile and desktop) contexts with no light context anywhere in the file — and the sibling harnesses tests/pr_render_gate.py (358, 371) and tests/site_review.py (100) are dark-only too; all four CI invocations (site-deploy.yml:194, ci-cd.yml:875, visual-qa.yml:151, webkit-mobile-qa.yml:119) call visual_qa.py with no theme flag; tests/test_token_contrast.py computes AA only for token hex pairs in both themes with zero opacity-compositing logic (no 'opacity' occurrence in the file), so it cannot see the observed composite failure class. I verified the concrete consequence live: my own light-scheme axe run on /cockpit/ shows the same serious color-contrast violation (2.34:1 by my math) that no automated layer currently observes.

#### a11y-4 · ADJUSTED · sev **low** · effort S · class A

**Finding.** The cockpit's baselined 'region' landmark violation quietly grew from 3 to 4 nodes (.hero-instruments now sits outside any landmark) — intra-rule growth is invisible to the gate because the key is (page, rule-id) with node counts deliberately excluded, so baselined rules can accrete new instances without any signal.

**Evidence.** tests/a11y_baseline.json '/cockpit/' region: 3 nodes (2026-07-19) vs live axe 2026-07-28: region moderate 4 nodes, targets .ph-kicker, .cockpit-fingerprint, .ph-attempt, .hero-instruments (transcript); gate-key design and its rationale at tests/a11y_audit.py:22-25 (#1428 anti-flake lesson — a documented tradeoff, correctly made; the growth itself is still a real live defect).

**Root cause.** Cockpit hero markup added after the 07-19 baseline capture places .hero-instruments (and .ph-attempt) outside the <main>/header landmark structure in site/cockpit/index.html — content unreachable by landmark navigation for screen-reader users.

**Regression guard.** Moderate impact never gates under #1433's serious/critical scope even when new, so the guard here is the ledger-shrink ritual of finding 2 plus the existing per-run advisory warning; alternatively tests/test_site_a11y_landmarks.py (static landmark pytest, currently green) could assert the cockpit hero children live inside a landmark.

**Path-to-A step.** Wrap the four flagged hero nodes in the existing header/main landmark when next touching cockpit HTML — fold into the finding-1 PR since both touch the same page.

**Verifier (ADJUSTED).** Symptom fully reproduced — my live axe runs (both themes) show region moderate 4 nodes (.ph-kicker, .cockpit-fingerprint, .ph-attempt, .hero-instruments) vs the baselined 3, and tests/a11y_audit.py's (page, rule-id) key indeed makes intra-rule node growth invisible to the gate (documented #1428 tradeoff at a11y_audit.py:22-25). But the stated root cause is wrong: the markup was NOT added after the 07-19 baseline capture.

**Corrected cause/evidence.** .hero-instruments landed in commit 80a27ad0 (feat(cockpit): instrument strip in the hero, #1147) on 2026-07-12 — a week BEFORE the 2026-07-19 baseline capture. The element ships statically `hidden` (site/cockpit/index.html:96) and is unhidden at runtime by cockpit.js's renderHeroInstruments (it also re-hides in time-travel mode), so the 3→4 growth reflects a runtime-visibility change since capture, not new markup. The underlying structural defect is that the entire .page-hero.cockpit-hero block (lines ~80-97, containing all four flagged nodes) sits between </header> (line 63) and <main> (line 99), outside any landmark. The proposed fix (wrap the hero in a landmark, fold into the finding-0 PR) remains correct.

**Path to A (grader's ranked actions):**

1. Fix cockpit.css:94 — replace the .scope-deep opacity:0.6 de-emphasis with full-opacity --ink-faint (already quieter than active ink, AA in both themes: 5.97:1 dark / 4.88:1 light), and fold the four cockpit landmark orphans (.hero-instruments etc.) into the same PR. One page, one PR, S effort.
2. Shrink the a11y debt ledger in one reviewed PR (`python3 tests/visual_qa.py --update-baseline` over the full surface) — restores real serious/critical gating on ~64 pages that are currently exempt; keep or defer the /data/character/ and /data/badges/ entries until the cycle fills (their cleanliness is partly Day-1 emptiness). Zero standing cost.
3. Give the axe audit a light-theme dimension: alternate the weekly full-surface run's color_scheme by week parity (or add a light pass over the 6 tier-1 doors at deploy). Same runner, one parameter — ADR-103 justification: no new system, an existing gate gains the missing half of its domain.
4. Add a consumer for the per-run 'a11y fixed vs baseline — shrink the ledger' warnings (weekly visual-qa report triage or the /wrap warning check) so ledger drift in either direction becomes an action item within a week instead of sitting unactioned for 9+ days.
5. After steps 1-2, re-run the full-surface sweep in both themes and confirm zero serious/critical entries remain in the ledger for non-reset-scoped pages — at that point the rubric's A bar (AA on every live page in both themes, gated) is met with the machinery already built.

**Coverage (what this lens did NOT examine).** NOT examined: no assistive-technology session (VoiceOver/NVDA) and no full manual keyboard walkthrough — keyboard/focus claims rest on code inspection (:focus-visible rules, wireTabList, popover focus traps verified in source, not driven live). Axe was run live on 15 of ~88 pages (7 in both themes, 8 more dark-only, chosen to cover the heaviest baseline entries plus the two pages shipped 07-27); the remaining ~73 pages are covered only by the CI sweep's own history. The interactive write flows (subscribe, votes, ask-the-board, predict-the-week) were not keyboard-tested this run. WebKit/iOS a11y behavior not exercised (the weekly webkit-mobile-qa workflow exists but was not re-verified). The diary shelf's card renderer was code-reviewed only — the live shelf is honestly empty on Day 1 (0 published entries, 1 withheld), so prosody/quote cards could not be observed rendered. Email templates and OG share cards were not audited. Reduced-motion was verified by grep + code read (motion.js/portraits.js early-exits, 30 CSS gates), not by a forced-preference browser pass.

**Lens notes.** DEDUP: gh searches (a11y, contrast, color-contrast, accessibility, axe, tap target, ledger) return zero open issues — all four findings are unfiled; the relevant history (#579, #1010/#1249, #1222, #1223, #1275, #1433) is closed and shipped. Nothing in the do-not-refile list is a11y-shaped. OVERLAP: finding 1's root pattern (dim-by-opacity over faint ink) is the same defect shape 898e566f just fixed on the Third Wall — the designer/dataviz lenses may want 'de-emphasis = color, never opacity, on text' written into DESIGN_SYSTEM_V5. REGRESSION CHECK vs FULLREVIEW_2026-07-16: all 4 baseline findings are verified FIXED WITH GUARDS — light --alert overridden in both light blocks (tokens.css:332/360) + test_light_alert_contrast_1222.py; palette-wide token-contrast pytest #1223 live and non-vacuous (asserts the historical 3.37:1 miss still fails); .wave a.bar added to TAP_TARGET_SEL and the 44px audit promoted to GATING (#1249, visual_qa.py:296/744-750); theme toggle sets aria-pressed + name swap (theme.js:54-55) + test_theme_toggle_aria.py. All 34 a11y-guard pytests pass locally (0.37s). No recurrences. DATA-MATURITY: /data/character/ and /data/badges/ axe-cleanliness partly reflects Day-1 wiped content — do not delete their ledger entries until re-verified mid-cycle. HUNT-ORDER PROBE: no prior-cycle leakage found on a11y surfaces; diary_shelf.js:52 explicitly refuses to fabricate a Day/cycle stamp for pre-genesis dates (the #1824 lesson, held). KILL-ON-SIGHT: clean — day-mark SVG glow is earned-score-driven (fingerprint.py:186), diary API launders themes to the 8-way public vocabulary, no vice/age/genome content in anything fetched. GRADE RATIONALE: the guard machinery went from 'none' (07-16) to a layered gating system (token pytest both themes, gating tap floor, per-page axe in every deploy + weekly run) in 12 days — genuinely rubric-A-shaped machinery; the grade stays A- rather than rising to A because the rubric's central criterion (AA on every live page in both themes) is concretely violated on the flagship cockpit in both themes, and the ledger staleness means the built gate is not actually protecting ~64 pages today. DISSENT-WORTHY: the (page, rule-id) gate granularity trades intra-rule growth blindness for anti-flake stability — I judge that tradeoff correct (#1428 lesson) as long as the ledger-shrink ritual of finding 2 exists; without it the ledger decays toward an excuse file, which is exactly what its own _meta note says it must never be.

### reader — First-contact comprehension (cold Reddit reader, live site, desktop 1280 + mobile 390) — **B**

*Trend: ▼ **down from B+**.*

**Verifier on the grade:** Six of seven findings survive intact (five confirmed, one adjusted but still a genuine high-sev tombstone-leak) including two high-severity honest-numbers defects on public doors on Day 1, so the proposed B remains well supported.

#### reader-1 · CONFIRMED · sev **high** · effort M · class A

**Finding.** REGRESSION of closed #787/#1226: the coaching door's coach card asserts "Day 1 weight is 317.61 lbs" — that is the pre-genesis 2026-07-22 weigh-in, not Day 1's real 321.09 — so a cold reader crossing home (321.1) → coaching (317.61) hits a 3.5 lb contradiction on the experiment's single most important number, on a site whose moat is 'the numbers are real'. Brandt's card similarly cites Whoop 60%/40.8ms/64bpm (Jul 26's values) as current instrumentation while the cockpit shows 56%/37.8ms/62bpm. This is also the #1194 hunt-order class: prior-cycle data presented as current on Day 1 of a fresh cycle.

**Evidence.** Live /coaching/ text dump (scratchpad/coaching-d1280.txt lines 104, 116) + /api/coaching-dashboard coaches[4].position_summary (curl output) vs /api/vitals weight_lbs=321 recovery=56 hrv=37.8 rhr=62; DDB query USER#matthew#SOURCE#withings: DATE#2026-07-22 = 317.61, DATE#2026-07-27 = 321.09 (ingested 2026-07-28T03:05Z, AFTER the coach analysis ran); whoop DATE#2026-07-26 recovery=60 vs DATE#2026-07-27 recovery=56

**Root cause.** lambdas/intelligence/ai_expert_analyzer_lambda.py:446-448 — current_weight = weights[-1] over a 30-day window with no date on the reading and no is-it-today check; the analyzer ran on Jul 27 before the Day-1 weigh-in ingested (03:05Z Jul 28), so the coach was handed the Jul-22 pre-genesis value and narrated it as 'Day 1 weight'. The Phase-3 grounding backstop (same file, line 1267+) grounds against the SAME stale fact set, so it structurally cannot catch staleness.

**Regression guard.** qa_smoke_lambda (layer 2, nightly) should cross-check any lb figure appearing in served coach position_summary against /api/vitals weight ±0.5 lb or require an explicit date qualifier; the #1226 fix (AS-OF chips) was a labeling guard that cannot catch a false in-text assertion — the missing guard is content-vs-canonical-vitals reconciliation.

**Path-to-A step.** Pass each reading's own date into the analyzer's fact block and require date-scoped phrasing ('last weigh-in Jul 22') whenever the reading is not from the data-day; add the qa-smoke reconciliation check.

**Verifier (CONFIRMED).** Reproduced end-to-end: /api/coaching-dashboard coaches[4] says 'Day 1 weight is 317.61 lbs' and coaches[7] cites 60%/40.8ms/64bpm while /api/vitals serves 321 (as_of 2026-07-27) / 56 / 37.8 / 62. DDB withings: DATE#2026-07-22=317.61; DATE#2026-07-27=321.09 ingested 2026-07-28T03:05Z — after every coach analysis_generated_at (17:00-17:05Z Jul 27). Root cause verified in lambdas/intelligence/ai_expert_analyzer_lambda.py (~448): current_weight = weights[-1] over a 30-day window with no reading date. Additional context strengthening the regression framing: the #1691 baseline-freshness gate (lambdas/ai_calls.py ~2020) is explicitly ADVISORY ('generation is NOT held') even though its framing regex includes 'day 1 weight' — so the shipped guard class structurally cannot block this. #787/#1226 closed, no open duplicate.

#### reader-2 · ADJUSTED · sev **high** · effort S · class B

**Finding.** Hunt-order leak (#1194 class): home's ribbon announces "NEWLY UNLOCKED THIS MONTH: HABIT PCT ↔ DAY GRADE (R=0.88, N=20…)" on Day 1 of cycle 11, but the artifact is prior-cycle intelligence — computed_at 2026-07-04, window 2026-06-05→07-04, week 2026-W27, first_seen 2026-06-30 — served as current 24 days later; the genesis wipe of experiment-scoped intelligence did not cover it and the front-end gate only suppresses it pre-start.

**Evidence.** curl /api/what_changed → newly_unlocked[0] {r:0.8777, first_seen:2026-06-30, n:20, interpretation:'weak'}, computed_at 2026-07-04T20:45Z, week 2026-W27; rendered on live home (scratchpad/home-d1280.txt line 117); site/assets/js/story.js:882-898 — the #949 comment documents this exact trap but gates only on preStart()

**Root cause.** The what_changed/newly-unlocked correlation artifact survived the ADR-077 genesis wipe — it is not classified experiment_scoped in lambdas/phase_taxonomy.py's registry (the coverage assertion never sees it), and site/assets/js/story.js:885 gates the announcement only on preStart(), not on computed_at >= genesis.

**Regression guard.** phase_taxonomy.py's coverage assertion (the registry that exists precisely so no scoped partition silently survives a reset) should own this; secondarily deploy/restart_pipeline verify step should assert /api/what_changed.computed_at >= genesis after a reset.

**Path-to-A step.** PROCESS: add the what_changed artifact to the experiment_scoped class in lambdas/phase_taxonomy.py so every future reset wipes it, AND gate the home ribbon on computed_at >= genesis (belt for the API's stale-artifact fallback). Fixing this one instance without the taxonomy row is a failing fix.

**Verifier (ADJUSTED).** Symptom fully reproduced and high-sev (#1194 class): /api/what_changed serves newly_unlocked r=0.8777/n=20, computed_at 2026-07-04, week 2026-W27 on Day 1 of cycle 11, and site/assets/js/story.js (~886) gates the home ribbon only on preStart(). But the claimed root cause is factually wrong: what_changed IS classified EXPERIMENT_SCOPED in lambdas/phase_taxonomy.py:238, and the live SNAPSHOT#current item carries tombstone=True / tombstoned_at=2026-07-13 / tombstoned_reason='experiment_restart_2026-07-13' — the reset machinery DID process it. The proposed fix (add the taxonomy row) is a no-op.

**Corrected cause/evidence.** The leak is the READ path, not the wipe: lambdas/web/site_api_ledger.py:117 (what_changed()) reads SNAPSHOT#current and serves it with no tombstone/phase filter, so a tombstoned prior-cycle artifact ('tombstoned, never deleted... phase-filtered' per phase_taxonomy.py's own contract, line 23) is served as current; the preStart()-only front-end gate is the failed second belt. Fix: honest-empty (honest_null) when item.tombstone is true or computed_at < genesis, plus the computed_at >= genesis gate in story.js. (Secondary observation: weekly-correlation-compute has not overwritten the snapshot since 07-04 despite weekly Sunday runs — worth a look in the same fix.)

#### reader-3 · CONFIRMED · sev **medium** · effort S · class A

**Finding.** The coaching door publicly declares a false data-integrity scandal: Dr. Okafor's card says "The April 3, 2026 lab draw is logged in the system with zero results — flagged markers: zero, total draws: zero" while /data/ advertises '153 biomarkers over time' and /api/labs serves 8 draws, 153 biomarkers, 26 out-of-range from that same date — a cold reader reading two doors is told the labs both exist and don't exist.

**Evidence.** curl /api/coaching-dashboard coaches[6].position_summary vs curl /api/labs → {latest_draw_date:'2026-04-03', total_draws:8, biomarkers:[153 items]}; DDB labs DATE#2026-04-03 record: total_biomarkers=153, out_of_range_count=26, biomarkers map present; extraction code read at lambdas/intelligence/ai_expert_analyzer_lambda.py:526-545

**Root cause.** lambdas/intelligence/ai_expert_analyzer_lambda.py:532-537 — the labs fact extractor hunts for top-level '*_flag' keys valued H/L, but the labs record schema stores a nested biomarkers map + out_of_range list (26 items), so flagged=[] / flagged_count=0 regardless of the data, and the coach prompt narrates the empty extraction as a data-integrity failure (ADR-104 grounded-generation breach: the ground itself is mis-extracted).

**Regression guard.** A unit test fixing the analyzer's labs extraction against a real labs-record fixture (SCHEMA.md is authoritative); qa_smoke could additionally red-flag any served coach text containing 'zero draws'/'zero results' while /api/labs.total_draws > 0.

**Path-to-A step.** Rewrite the labs fact block to read out_of_range/out_of_range_count/total_biomarkers per the actual schema, with the fixture test.

**Verifier (CONFIRMED).** Reproduced: live Okafor card declares the data-integrity problem while /api/labs.labs serves latest_draw_date 2026-04-03, total_draws=8, 152 biomarkers, flagged_count=26. DDB labs DATE#2026-04-03 has a nested biomarkers map + out_of_range_count=26 and ZERO top-level *_flag keys; the extractor at ai_expert_analyzer_lambda.py (~531-537) hunts only key.endswith('_flag') in ('H','L'), so flagged=[]/flagged_count=0 is guaranteed against the real schema — root cause verified in code. One nuance that does not change the verdict: the extractor does return total_draws=len(lab_items)=8, so the coach's 'total draws: zero' phrasing is prompt-side over-narration on top of the mis-extraction; the fix (read out_of_range_count/total_biomarkers per schema + fixture test) is right.

#### reader-4 · CONFIRMED · sev **medium** · effort S · class A

**Finding.** The home hero's second data line — the 4th thing every visitor reads, both viewports — is a broken English sentence: "even since the start — one weigh-in so far, Jul 27. The shape of it, every day, just below." The bare opener 'even' (the zero-delta branch) reads as a truncated fragment, exactly the 'looks broken' impression the hero cannot afford, and it fires on every Day 1 and every zero-delta day.

**Evidence.** Live render screenshots scratchpad/home-hero.png and home-m390-hero.png (orange-highlighted hero line); producing code site/assets/js/story.js:354 (dir = 'even') and :380 (dir opens the sentence)

**Root cause.** site/assets/js/story.js:354 — the three-way delta word ('down X lb' / 'up X lb' / 'even') is composed for mid-sentence use but line 380 places it sentence-initial; with a single weigh-in the delta is definitionally 0 so the 'even' branch is guaranteed on Day 1 of every cycle.

**Regression guard.** tests/visual_ai_qa.py (Haiku semantic pass) should flag an ungrammatical hero sentence; a unit test over the even-branch template string would have caught it deterministically. Neither owned it — the branch was never rendered until a zero-delta day.

**Path-to-A step.** Copy fix: 'holding even since the start' (or 'no change yet'), plus a template unit test covering all three delta branches.

**Verifier (CONFIRMED).** Reproduced deterministically without needing the screenshots: site/assets/js/story.js ~354 composes dir as 'down X lb'/'up X lb'/'even' for mid-sentence use, and the single-weigh-in branch (~380) opens the sentence with it; live /api/journey returns lost_lbs=0.0, weighin_count=1, last_weighin_date=2026-07-27, so the hero renders exactly 'even since the start — one weigh-in so far, Jul 27. The shape of it, every day, just below.' — the bare sentence-initial 'even' fragment, guaranteed on every Day 1 and any zero-delta day.

#### reader-5 · CONFIRMED · sev **medium** · effort S · class A

**Finding.** Day-1 temporal contradiction: coaching labels the brief line "TODAY'S LINE · FROM THE MORNING BRIEF" — and home shows it unlabeled — while the line itself says '…tomorrow's experiment start deserves one real win today', so the site simultaneously tells a cold reader 'DAY 1 · running now' and 'the experiment starts tomorrow'. Only the cockpit relabels it honestly as 'yesterday's read'.

**Evidence.** Live /coaching/ (scratchpad/coaching-d1280.txt lines 52-54), live home (home-d1280.txt line 74) vs 'DAY 1' banners on the same pages; renderer site/assets/js/coaching.js:484-488 (elena_hero_line from /public_stats.json, hardcoded 'today's line' kicker); cockpit's correct label at now-d1280.txt line 92

**Root cause.** The morning-brief generator writes elena_hero_line with deictics ('today'/'tomorrow') anchored to the data-day (Jul 26), and two of three consumers (coaching.js:486 kicker, story.js home surfacing) re-anchor it to the render-day as 'today', inverting its meaning on Day 1.

**Regression guard.** The cockpit already carries the correct pattern ('yesterday's read · written 10:05 AM') — a shared-label rule in the page kit plus a qa-smoke check that elena_hero_line containing 'tomorrow' never renders under a 'today' kicker.

**Path-to-A step.** Either strip deictics at generation (date-scope: 'Jul 26: sleep held…') or copy the cockpit's 'yesterday's read' kicker to coaching and home.

**Verifier (CONFIRMED).** Reproduced: public_stats.json elena_hero_line = '...tomorrow's experiment start deserves one real win today' (data-day Jul 26 deictics), coaching.js:486 hardcodes the kicker 'today's line · from the morning brief', story.js:771 renders the same line unlabeled on home, both under DAY 1 banners — while cockpit.js:247 carries the honest 'the daily line · yesterday's read · from the morning brief' label. Root cause (deictics anchored to data-day, two of three consumers re-anchor to render-day) verified in all three renderers.

#### reader-6 · CONFIRMED · sev **low** · effort S · class A

**Finding.** Self-contradicting statistic on home: 'R=0.88, N=20, POSITIVE · WEAK' — an r of 0.88 labeled weak reads as either a stats error or nonsense to exactly the skeptical Reddit reader the page courts; the codebase already contains the fix for this defect (_corr_strength, written after 'r=0.843 labeled weak') but the /api/what_changed path bypasses it and serves the stored n-gated label with no gloss.

**Evidence.** curl /api/what_changed → {r:0.8777, interpretation:'weak'}; rendered home-d1280.txt line 117; lambdas/web/site_api_intelligence.py:1751-1766 (the reconcile helper whose own docstring cites this exact defect class, not applied on the what_changed path); site/assets/js/story.js:892-894 deliberately displays the engine's stored call verbatim

**Root cause.** The what_changed endpoint serves weekly_correlation_compute_lambda.py's stored n-downgraded interpretation (lines 189-204: strong at r≥0.6 is demoted to 'weak' when n<required) without either applying site_api_intelligence.py's _corr_strength reconcile or glossing the n-gate — so a deliberate evidence-confidence downgrade reads as a strength mislabel.

**Regression guard.** The unit test that presumably covers _corr_strength should be extended to every endpoint serving an interpretation next to an r value (a served-label-matches-served-r invariant), owning the class rather than one endpoint.

**Path-to-A step.** Serve the label via _corr_strength on what_changed too, or change display copy to 'r=0.88 · n=20 — evidence still thin' so the n-gate is legible instead of self-contradicting.

**Verifier (CONFIRMED).** Reproduced: /api/what_changed serves r=0.8777, interpretation 'weak', rendered verbatim on home; the n-gate is real (weekly_correlation_compute_lambda: strong requires n>=50, moderate n>=30, so n=20 demotes to 'weak') and _corr_strength in site_api_intelligence.py (~1751) exists precisely because 'r=0.843 labeled weak' was previously treated as a defect. Two corrections that shape the fix, not the verdict: (a) the compute lambda lives at lambdas/compute/, not lambdas/intelligence/; (b) the verbatim display is a DOCUMENTED deliberate choice (story.js comment: 'the strength label stays the engine's own n-gated call, never re-derived here'), so the ADR-105-compatible fix is the second path_to_A option (gloss the n-gate, e.g. 'evidence still thin') — applying _corr_strength to relabel it 'strong' would contradict the deliberate n-gating. The cold-reader self-contradiction is real; sev low is right. (Also moot in practice once finding 1's fix lands, since this stale artifact should be honest-empty on Day 1.)

#### reader-7 · CONFIRMED · sev **low** · effort S · class A

**Finding.** Coach digest voice drift: two of the eight 'EACH COACH'S READ' cards narrate the coach in third person ('The coach pivots from data to ownership…', 'The glucose coach is in calibration mode…') while the other six speak first-person, and the Reeves card renders literal markdown asterisks ('do your targets feel like *your* future') — small but visible seams in AI-generated text on the friends/family-facing door.

**Evidence.** Live /coaching/ text dump scratchpad/coaching-d1280.txt lines 100 (Reeves, third person + raw *your*) and 108 (Patel, third person) vs first-person cards at lines 88, 96, 104, 116; same text in /api/coaching-dashboard position_summary fields

**Root cause.** The position_summary summarizer in the intelligence pipeline (lambdas/intelligence_common.py / ai_expert_analyzer_lambda.py write path) emits mixed-voice summaries with markdown emphasis, and coaching.js renders the string verbatim with no markdown handling.

**Regression guard.** Prompt-side voice constraint plus a cheap render-side strip/convert of *emphasis*; tests/visual_ai_qa.py semantic pass could flag third-person narration inside a first-person card frame.

**Path-to-A step.** Constrain the summarizer to first-person coach voice and strip markdown emphasis at render.

**Verifier (CONFIRMED).** Reproduced live from /api/coaching-dashboard: coaches[3] Reeves ('The coach pivots from data to ownership... do your targets feel like *your* future' — third person + literal markdown asterisks) and coaches[5] Patel ('The glucose coach is in calibration mode...' — third person) vs first-person voice on the other six cards. Renderer verified: coaching.js outputs esc(c.position_summary) verbatim with no markdown handling; write path is the Haiku position_summary parser (intelligence_common.py ~1461), consistent with the stated root cause. No open duplicate issue.

**Path to A (grader's ranked actions):**

1. Date-scope every number a coach cites: pass each reading's own date into ai_expert_analyzer_lambda's fact block, require 'last weigh-in <date>' phrasing when the reading is not from the data-day, and add a qa_smoke reconciliation check (coach-cited weight vs /api/vitals ±0.5 lb or date-qualified) — permanently closes the #787/#1226/#1194 coach-vitals class using the existing nightly QA layer, no new standing machinery (ADR-103: extends qa_smoke, rent already paid).
2. Register the what_changed/newly-unlocked artifact as experiment_scoped in lambdas/phase_taxonomy.py (so the existing coverage assertion owns it at every future reset) and gate the home ribbon on computed_at >= genesis in story.js — reuses ADR-077 machinery, zero new cost.
3. Fix the analyzer's labs fact extraction to read the record's real schema (out_of_range list / total_biomarkers) with a fixture unit test — kills the public 'zero results' false alarm at the source.
4. Fix the hero zero-delta copy branch in story.js:354/380 ('holding even since the start') with a three-branch template unit test — removes the one 'site looks broken' moment in the first screen.
5. Unify the brief-line label: carry the cockpit's honest 'yesterday's read' kicker to coaching and home (or strip deictics at generation) so 'Day 1' and 'tomorrow's experiment start' can never co-occur.

**Coverage (what this lens did NOT examine).** Rendered the LIVE site (build 6acd301 verified via /version.json == main HEAD) with Playwright, service workers blocked, real JS executed, full scroll-through before capture, at 1280x900 and 390x844 — all six target pages (/, /now/, /data/, /coaching/, /protocols/, /story/). Checked: console errors (zero on all 12 renders), page errors (zero), horizontal overflow (zero px at 390), raw mustache/undefined/NaN (none), empty data-binds (home: 3, all hidden or non-text; /now/: 25, verified all inactive-tab/hidden empty-states except benign tick elements). Cross-checked live APIs (vitals, labs, what_changed, coaching-dashboard, coach_team) and DDB ground truth (withings Jul 20-27, whoop Jul 25-27, labs 2026-04-03). NOT examined: story-door sub-tabs beyond Chronicle (Podcast/In-my-own-words/Timeline/Broadcast/About), /data/ topics beyond the default weight view, /coaching/ By-Coach/Scorecard/Team/lab-notes tab contents, /protocols/ Experiments/Challenges/Discoveries tabs, deep pages (/method/, /story/diary/, full chronicle pieces), the subscribe flow, ask-the-data and board_ask POST paths, OG share cards, dark mode, tablet widths, and the coaching-cards viewport crop (the region was verified via text dump + API + noscript HTML instead).

**Lens notes.** DEDUP: finding 1 is a named REGRESSION of CLOSED #787 (R22-CONTENT-02) and CLOSED #1226 (closed 2026-07-18) — the earlier fix added AS-OF chips, which cannot catch a false in-text assertion; reported as regression per method rule 2, not refiled as new. gh searches for what_changed/stale-prior-cycle/coach-vitals/hero/unlocked returned no open issues; #1383 ('Coach Line') is an unrelated WhatsApp-channel story; #1475 wayfinding not overlapped. DATA-MATURITY: Day-1 emptiness itself is handled exceptionally well and was NOT penalized — 'ATTEMPT #11 — PREVIOUS BEST: 13 DAYS', 'a young experiment starts low, not broken', chronicle PROLOGUE framing, the /data/ ranked honest-capture-backlog, 'one weigh-in so far — trend line draws in at 4+', and both NEW HERE explainers are A-grade phase-aware copy; every finding is a wrongness, not a thinness. Tier-2 budget: no surface served stale content labeled as paused AI; honest states observed. KILL-ON-SIGHT scan: no vice/substance names, no chronological age (PhenoAge copy explicitly withholds it), no decorative glow, correlative framing consistent ('correlation, not cause; announced once'); borderline: the integrator's call converts 5,000 steps ≈ '2.5 miles' (AI arithmetic in a rule statement — noted, below finding threshold); coach chips 'HELD SINCE JUL 26' are pre-genesis by one day but honest. '102 falsifiable calls · none decided yet' on Day 1 may briefly puzzle a reader (how does Day 1 have 102 calls?) but is coherent with prep-week filing — sub-finding. Mobile full-page captures show the fixed bottom nav painted mid-page — a Playwright full_page capture artifact, not a live defect (verified clean in viewport crops). DISSENT-WORTHY: the truncation-mid-word defect from the 07-16 baseline is FIXED (all coach cards now end with ellipses) — worth recording as a realized fix. Grade movement B+ → B is driven by the coaching door's three factually false AI claims (one a regression) and the Day-1 prior-cycle unlock leak — the exact hunt-order class this run existed to catch — against otherwise flawless rendering and best-in-class deliberately-young framing.

### observability — observability — Telemetry & alerting — **B+** †UNVERIFIED

*Trend: ▲ up from B.*

**No verifier ran for this lens.** Findings below are first-pass only — the historical false-positive
rate for unverified findings in this repo is ~50%. Verify before filing.

#### observability-1 · UNVERIFIED · sev **high** · effort S · class B

**Finding.** The AI-quality canary — the watchdog for reader-facing AI content — failed every scheduled run for a full week (OverallAlarm=1 on 07-20, 07-22, 07-24, 07-27, its entire Mon/Wed/Fri cadence) because the IAM fix (PR #1599, merged 2026-07-20: secretsmanager:GetSecretValue on life-platform/site-api-origin-secret) sat merged-but-undeployed until the owner CDK deploy 07-27 ~22Z; ai-canary-overall is still red now and structurally cannot clear before the next run Wed 07-29 — so the platform entered Day 1/2 of cycle 11, the highest-risk window for stale-AI-content leaks, with its AI watchdog blind.

**Evidence.** get-metric-statistics LifePlatform/AICanary OverallAlarm: 1.0 at every datapoint 07-20→07-27; EventBridge rule LifePlatformOperational-AiQualityCanarySchedule cron(20 16 ? * MON,WED,FRI *); s3://matthew-life-platform/remediation-log/ack_ledger.json ai-canary-blind conclusion: 'Run cdk deploy LifePlatformOperational to apply staged canary IAM grant (PR #1599 merged 2026-07-20)… expected ALARM until the deploy completes' (acked_at 2026-07-21, re-acked through 07-27)

**Root cause.** cdk/stacks/role_policies.py canary secret grant merged 07-20 but LifePlatformOperational not deployed until 07-27 — the deploy step of an IAM fix has no clock; the remediation agent re-acked 'pending CDK deploy' as bucket=stale for 6+ days without escalating the growing age. Same family as the 07-16 baseline's #727 dead-watchdog-via-IAM finding (that instance was repo-missing grant; this is repo-correct/live-wrong — the 'IAM parity codified broken state' class), so this is a recurrence of the class with a different mechanism; the new test_put_metric_data_grant_lockstep.py guard passed because the repo WAS correct.

**Regression guard.** The remediation agent's ack loop should own this: an ack whose conclusion names a pending deploy must carry a deploy-verified check (compare merged role_policies.py SHA vs deployed stack) and escalate needs-human with age after 48h instead of silently renewing bucket=stale. The existing R8-ST6 IAM-review gate reds ci-cd Plan on undeployed IAM merges — it signaled, but nothing converts that standing signal into an aging page.

**Path-to-A step.** 1

#### observability-2 · UNVERIFIED · sev **medium** · effort S · class A

**Finding.** qa-smoke-warnings is a permanently-red alarm carrying zero marginal signal: WarnCount has been ≥4 every single night for 8+ consecutive nights (4,6,6,7,11,7 over the last week — chronic 'optional: no record' items like withings/strava/notion/supplements plus hydration-null and cache-warmer), against a threshold of ≥1, so the alarm has sat ALARM since at least 07-18 and can only clear on a warning-free night that never occurs — the exact 'nothing permanently red or structurally unclearable' clause of the A bar.

**Evidence.** get-metric-statistics LifePlatform/QaSmoke WarnCount 07-20→07-27: 8,8,4,6,6,7,11,7 (never 0); cdk/stacks/monitoring_stack.py:436-438 (WarnCount Max >= 1, 86400s, digest); last-night run log /aws/lambda/life-platform-qa-smoke 2026-07-28: 7 WARN lines, 4 of them 'no record (optional)', footer 'warnings not emailed standalone'

**Root cause.** cdk/stacks/monitoring_stack.py:436 — threshold ≥1 on a metric whose empirical floor is 4: the alarm semantics ('a warnings-only run happened') don't match the metric's real distribution, violating the ADR-105 thresholds-from-personal-variance standard; the chronic warnings themselves are partly phase-honest (Day-boundary 'no record' on optional sources) and partly real untriaged debt (hydration null, todoist empty, warmer at 5 entries).

**Regression guard.** An alarm-inventory hygiene check in the remediation agent or qa-smoke itself: any alarm red >7 consecutive days is auto-escalated as 'structurally unclearable — recalibrate or triage'; the fresh-eyes/stale ack bucket sees these but renews rather than escalates.

**Path-to-A step.** 2

#### observability-3 · UNVERIFIED · sev **medium** · effort M · class A

**Finding.** Standing-red normalization: 6 of 79 alarms are simultaneously in ALARM (4 for >72h) and the remediation agent's ack ledger renews the same acks run after run — including one factually wrong ack: ingest-auth-unhealthy-24h (URGENT topic) is acked 'duplicate, covered by Whoop/Withings source-specific alarms', but per-source consecutive-failures alarms exist for only 5 sources (whoop, withings, strava, hevy, eightsleep) — a garmin/todoist/notion auth death would fire ONLY this 'duplicate' alarm, and the dimensionless IngestAuthHealthy metric means the page can't name which source broke.

**Evidence.** describe-alarms: 6 ALARM states (qa-paused-by-budget red since 07-18, qa-smoke-warnings 07-18, ingest-auth-unhealthy 07-24, qa-smoke-failures 07-24, ai-canary-overall + compute-pipeline-stale 07-27); ack_ledger.json ingest-auth-unhealthy-24h conclusion 'duplicate, covered by Whoop/Withings source-specific alarms'; alarm list shows exactly 5 ingest-consecutive-failures-* alarms; list-metrics LifePlatform/OAuth → IngestAuthHealthy has NO dimensions (lambdas/auth_breaker.py:61)

**Root cause.** Two joints: (a) the ack loop (remediation agent 'stale' bucket) has no escalation ratchet, so acks renew indefinitely and a red board becomes normal — a new red on Day 1 hides among six; (b) lambdas/auth_breaker.py emits IngestAuthHealthy without a Source dimension, forcing the aggregate alarm to be both undiagnosable and mislabeled 'duplicate' by the agent.

**Regression guard.** Ack-age ratchet in the remediation agent (3rd consecutive renewal → needs-human with age); a unit test on auth_breaker.py asserting the Source dimension is present; the existing alarm-inventory test should pin that every OAuth-capable source has either a per-source alarm or is explicitly covered by the aggregate.

**Path-to-A step.** 3

#### observability-4 · UNVERIFIED · sev **low** · effort S · class B

**Finding.** The urgent (paging) topic fired on expected conditions during genesis week, eroding the pager contract: ai-tokens-platform-daily-total routes to life-platform-alerts (urgent email) and breached on 07-25/07-26 purely from the post-genesis full-cycle rebuild — the agent itself acked both token alarms as 'transient post-genesis elevated token usage, expected during full-cycle rebuilds' — i.e., the operator was paged for a condition the system knew was expected.

**Evidence.** cdk/stacks/monitoring_stack.py:659 (ai-tokens-platform-daily-total → urgent, Sum 86400 ≥150000); remediation-log/2026/07/27/165627.json: ai-tokens-platform-daily-total 156061 vs 150000, acked 'expected during full-cycle rebuilds'; describe-alarms shows AlarmActions=life-platform-alerts (urgent) for this alarm vs digest for its per-feature sibling

**Root cause.** Fixed absolute token threshold with no genesis-window awareness: restart_pipeline (deploy/restart_pipeline.py) predictably triggers a rebuild token spike every cycle, and the alarm has no reset-window suppression or temporarily raised band — the same class as the July budget-ceiling dated window (ADR-133) already solved for spend.

**Regression guard.** A restart-runbook step (or restart_pipeline itself) that stamps a dated genesis window (like _TEMP_CEILING_WINDOW) consulted by the token alarms / dispatcher dedupe, so expected-rebuild breaches go digest-only; the restart_verify checklist should assert no urgent page fired for a predicted condition.

**Path-to-A step.** 4

#### observability-5 · UNVERIFIED · sev **low** · effort S · class B

**Finding.** compute-pipeline-stale fired red on both 07-26 and 07-27 mornings around the genesis cutover even though the compute did run (computed_metrics DATE#2026-07-27 exists in DDB) — a predictable per-reset staleness red, honest at fire-time but foreseeable, acked as 'transient scheduling delay during genesis cutover'; every future reset will reproduce this red unless the restart process accounts for it.

**Evidence.** get-metric-statistics ComputePipelineStaleness Source=computed_metrics: 1.0 at 07-26T05 PT and 07-27T05 PT, 0.0 between; dynamodb query USER#matthew#SOURCE#computed_metrics returns DATE#2026-07-27; rem.json ack 'transient scheduling delay during genesis cutover'

**Root cause.** The genesis cutover sequence (deploy/restart_pipeline.py phase-tag/wipe + redeploy) creates a window where the staleness emitter in lambdas/emails/daily_brief_lambda.py sees no fresh computed_metrics before the first post-reset compute lands — process artifact, not a wrong alarm; the process change needed is a restart-pipeline step that either pre-warms compute or opens a dated suppression window, mirroring the known genesis-week present-None class already in memory.

**Regression guard.** restart_verify (the 13/13 Day-2 check) should include 'no reset-predictable alarm fired red' or explicitly list the expected reds with their auto-clear date; the PHASE_TAXONOMY docs should name alarms as a reset-aware surface.

**Path-to-A step.** 4

**Path to A (grader's ranked actions):**

1. Close the merged-but-undeployed IAM gap: teach the remediation agent's ack loop that an ack whose conclusion names a pending CDK deploy must verify deployed-vs-merged state each run and escalate needs-human with an age counter after 48h (it already reads cfn drift and writes the ack ledger — this is a classifier rule, no new infra; ADR-103: modifies existing agent, zero standing cost) [S]
2. Recalibrate qa-smoke-warnings to its real distribution per ADR-105: alarm on FailCount>0 plus WarnCount above a rolling personal baseline (or a warn-streak of NEW warning keys), and triage the 4 chronic 'optional no record' warnings into phase-aware suppression so a warning-free night is actually achievable [S]
3. Add an ack-age ratchet + by-design suppression: 3rd consecutive ack renewal auto-escalates to needs-human; dated by-design reds (qa-paused-by-budget until 08-01) get a suppression window keyed to the SSM budget tier instead of standing red — target: the alarm board is all-green on a healthy day so one new red is unmissable [M]
4. Make genesis a first-class alarm event: restart_pipeline stamps a dated genesis window consulted by the token alarms and the staleness emitter (digest-only during the window), and restart_verify asserts no urgent page fired for a predicted condition [S]
5. Add a Source dimension to auth_breaker.py's IngestAuthHealthy emission and extend per-source auth alarm coverage to the OAuth sources currently covered only by the aggregate (garmin, todoist, notion), so the urgent page names the culprit and the 'duplicate' classification becomes true [S]

**Coverage (what this lens did NOT examine).** NOT examined this run: SES delivery of the digest/urgent emails to the actual inbox (verified the digest lambda runs daily and both digest-death alarms route to urgent, not that mail lands); us-east-1 alarm SNS routing (enumerated the 6 alarms — all OK — but did not verify their actions have live subscriptions); post-deploy verification that the 07-27 CDK run actually cleared the canary IAM gap and the 6-stack cfn drift (next canary run is Wed 07-29 and running drift detection is a mutation — both are asserted-pending, not proven-fixed); MCP EMF telemetry depth and the coherence sentinel's current warning content; cost_governor tier math (took tier=2 as given per shared context); the fresh-eyes workflow's downstream consumption; per-threshold ADR-105 calibration of the duration/latency alarms beyond the two token alarms and qa-smoke-warnings.

**Lens notes.** BASELINE DELTA (07-16 grade B): all 5 ledger-to-A items verifiably landed — grading-stalled is OK and clearable (state OK since 07-17), tests/test_put_metric_data_grant_lockstep.py exists, the remediation triage loop now completes every run (latest 3 runs classify every signal into buckets with an ack ledger + dispatch-dedupe markers + a curated email '0 fixed, 1 PRs, 6 need you'), the cfn_drift check returns real per-stack results instead of AccessDenied, and life-platform-alert-digest-errors/queue-age both route to the URGENT topic. Also healthy: 79 alarms with 0 INSUFFICIENT_DATA, DLQ depth 0, all 116 log groups retention-bounded (109×30d), both SNS topics have live subscriptions, digest queue drains daily (63 intra-day messages is normal accumulation; queue-age alarm OK). Finding #1 is a RECURRENCE OF THE CLASS of the baseline's #727 dead-watchdog-via-IAM high finding with a different mechanism (repo-correct/live-undeployed vs repo-missing) — the new lockstep test was the named guard and it structurally cannot catch deploy lag. IN-FLIGHT, NOT REFILED: the 07-27 remediation run already emailed needs-human items for the 6-stack cfn drift and the alarm_count doc-literal drift (77 vs live 79) — the loop is doing its job on those; the owner CDK deploy later that evening likely cleared the stack drift (unverified). The Whoop refresh-token death (07-24→07-27, urgent page → needs_human ack naming setup_whoop_browser_auth → recovered) is the loop working end-to-end, ~2.5-day human latency. DATA-MATURITY: qa-paused-by-budget red is the dated by-design tier-2 window (until 08-01) — counted only as red-normalization context, not a defect of itself; Day-1 'no record' qa-smoke warnings and the compute-stale genesis reds were graded as process artifacts, not emptiness penalties. DEDUP: gh issue searches for canary/qa-smoke/alarm/drift found no open issues covering any filed finding; nothing in the do-not-refile list overlaps. GRADE RATIONALE: B+ (up from B) — the loop machinery went from '1 of 4 runs completes triage' to demonstrably closing/handing off every signal, and all five prior ledger items landed; held below A- because the platform again entered a critical window (reset week) with a dead watchdog for 7 days via the same IAM family, and because 6 standing reds with auto-renewing acks (one factually wrong, one structurally unclearable) violate the 'red = actionable, nothing permanently red' core of the A bar.

### cost — Cost engineering — **B+**

*Trend: = held at B+.*

**Verifier on the grade:** All five findings survive with independent reproduction (one medium public-API fabricated-budget defect plus four low honesty/labeling drifts around an otherwise sound governor), which is consistent with the proposed B+ — real but small-effort transparency defects, nothing severe enough to drop below it and too many public-surface inaccuracies to go higher.

#### cost-1 · CONFIRMED · sev **medium** · effort S · class A

**Finding.** Public /api/status serves a fabricated budget claim — hardcoded budget=15.0 yields '613% of budget, status red' live, contradicting the ADR-063/133 ceiling ($115 July / $85 base) and the governor's own numbers on the same platform.

**Evidence.** lambdas/web/site_api_intelligence.py:824-830 (budget = 15.0, own duplicate CE call, days_in_month=30 hardcoded); live: curl https://averagejoematt.com/api/status -> cost: {mtd: 85.84, projected: 91.98, budget: 15.0, status: red, pct_of_budget: 613}. Only consumer is site/legacy/status/index.html, but the API endpoint is public.

**Root cause.** handle_status() in lambdas/web/site_api_intelligence.py predates ADR-063/133; its cost block hardcodes a $15 budget and recomputes MTD via its own Cost Explorer call instead of reading the governor's /life-platform/budget-breakdown SSM param. The literal was never migrated when the ceiling moved $15-era -> $75 -> $85 -> $115.

**Regression guard.** A price/ceiling-literal parity test (extend tests/test_receipts_endpoint.py or test_inference_receipt_ceiling.py) asserting no dollar-ceiling literal exists in lambdas/web/ outside _ADR133_BASE_CEILING_USD; qa_smoke (layer 2, ADR-076) should own a nightly check that every cost-bearing endpoint's ceiling matches the breakdown param. check_doc_facts covers docstrings but nothing covers endpoint literals.

**Path-to-A step.** Replace the cost block with a read of the budget-breakdown SSM param (tier/mtd/projected/ceiling) — also deletes the duplicate daily CE call; or drop the cost block from /api/status and point the legacy page at /api/receipts.

**Verifier (CONFIRMED).** Reproduced live: /api/status returns cost {mtd: 85.84, budget: 15.0, status: red, pct_of_budget: 613} (curl 2026-07-28T03:53Z). Code verified: lambdas/web/site_api_intelligence.py:824 budget=15.0, :822 days_in_month=30, :811-820 duplicate Cost Explorer call. Root cause independently verified: git log -S traces the $15 literal to 7e387ce0 (2026-03-29), pre-ADR-063, carried through the P1.1 extraction refactor unchanged. Consumers confirmed as site/legacy/status/index.html + legacy components.js only. No fix in git log, no duplicate issue.

#### cost-2 · CONFIRMED · sev **low** · effort S · class A

**Finding.** The public inference receipt claims 'the same math the budget governor enforces' but omits cache read/write token pricing AND the 1.15x safety buffer, and prices amazon.titan-embed-text-v2 at Sonnet rates via the dict fallback — three ways the shown number ($36.00 MTD) differs from the governor's enforced estimate (~$41.5).

**Evidence.** lambdas/web/site_api_intelligence.py:2070-2083 (_BEDROCK_PRICES has no cache_read/cache_write keys; _price_for_model falls through to sonnet for titan) vs cost_governor_lambda.py:132-139,264-277 (cache prices + _AI_SAFETY_BUFFER=1.15, unknown-model default = fable). Live /api/inference_receipt: ai_month_to_date_usd 36.0; titan row 42,637 tokens priced at $3/1M (~$0.128 shown vs ~$0.001 real). CW MTD sonnet cache tokens verified: 10,695 read / 24,614 write (~$0.10 omitted today — small now, unbounded as caching use grows).

**Root cause.** _BEDROCK_PRICES in site_api_intelligence.py is a hand-maintained partial copy of cost_governor_lambda._PRICES ('keep in sync' comment, no test enforcing it), missing the cache keys; _price_for_model's fallback is sonnet rather than an embeddings-aware branch; the note copy overstates parity.

**Regression guard.** A unit test importing both price tables and asserting key-for-key equality including cache_read/cache_write (natural home: tests/test_inference_receipt_ceiling.py, which already pins receipt<->governor ceiling lockstep); plus a fixture asserting a titan/unknown model is either priced from a real entry or excluded with a note.

**Path-to-A step.** Add CacheReadInputTokenCount/CacheWriteInputTokenCount to the receipt's per-model sums with the governor's cache prices, add a titan/embeddings price entry (or exclude embeddings with an honest note), and either apply the 1.15x buffer or amend the note to say 'pre-buffer estimate; the governor enforces this x1.15'.

**Verifier (CONFIRMED).** Reproduced all three deltas: _BEDROCK_PRICES (site_api_intelligence.py:2069-2074) lacks cache_read/cache_write keys and _price_for_model falls back to sonnet (:2082), vs cost_governor_lambda._PRICES (cache keys present), _DEFAULT_PRICE=fable, and _AI_SAFETY_BUFFER=1.15 applied in _ai_cost. Live receipt shows ai_month_to_date_usd 36.0 with amazon.titan-embed-text-v2:0 at 42,637 month tokens priced via the sonnet fallback, and the note at :2166-2170 claims governor-parity. Re-measured cache tokens myself via read-only CloudWatch: sonnet MTD CacheRead=10,695 / CacheWrite=24,614 — exactly the finder's figures.

#### cost-3 · CONFIRMED · sev **low** · effort S · class A

**Finding.** Surge-mode alert copy reads module constants MONTHLY_CEILING/SURGE_CEILING_USD ($85/$100) instead of the active-ceiling pair, so a surge engagement during the July window (uniques are at 803 of 900 — plausibly imminent) would email 'ceiling $85 -> $100' while the guard actually moves $115 -> $135.

**Evidence.** lambdas/operational/cost_governor_lambda.py:531,535,540,544,548 (_alert_surge f-strings use MONTHLY_CEILING and SURGE_CEILING_USD directly) vs :344-356 (_active_ceilings returns the July $115/$135 pair) and :504-523 (_alert correctly takes effective_ceiling as a parameter — only the surge alert has the gap).

**Root cause.** _alert_surge was written before _TEMP_CEILING_WINDOW existed and was never parameterized on the ceiling pair the way _alert was; it formats from the module-level env defaults that the calendar window deliberately bypasses.

**Regression guard.** Unit test in tests/test_cost_governor.py freezing the date inside _TEMP_CEILING_WINDOW and asserting the surge-alert subject/body carry the active pair; the existing test_budget_guard_ladder.py lockstep pattern (labels must mirror _FEATURE_CUTOFF) is the template — the same discipline was never applied to the surge alert's dollar figures.

**Path-to-A step.** Pass base/surge from _active_ceilings() (or the already-computed effective ceiling) into _alert_surge and format from those.

**Verifier (CONFIRMED).** _alert_surge (cost_governor_lambda.py:526+) formats from module constants MONTHLY_CEILING/SURGE_CEILING_USD in every f-string, while the handler (:664, :722) uses _effective_ceiling -> _active_ceilings() which returns the July $115/$135 pair; _alert (:504) is correctly parameterized on ceiling, only the surge alert is not. Deployed governor env sets only OBSERVE_MODE (operational_stack.py), so no MONTHLY_CEILING_USD override defeats the window. Live /api/receipts confirms recent_uniques 803 vs threshold 900 — surge engagement during the window is plausibly imminent as claimed.

#### cost-4 · CONFIRMED · sev **low** · effort M · class A

**Finding.** The 'base ceiling' label on both public receipts is stale during any temp-ceiling window: /api/receipts reports base_ceiling_usd 85.0 and /api/inference_receipt says 'The $85 base ceiling ($115 in effect)' with surge_active false — the in-effect number is honest but the $85->$115 delta is unexplained by any mechanism the payload names, since the breakdown param carries only the effective ceiling.

**Evidence.** lambdas/web/site_api_intelligence.py:2089 (_ADR133_BASE_CEILING_USD = 85.0, hardcoded) and :2166-2171 (note copy); live /api/receipts payload base_ceiling_usd:85.0 + ceiling_usd:115.0 + surge_active:false; governor _write_breakdown (cost_governor_lambda.py:446-489) writes no base/window field for consumers to read.

**Root cause.** The breakdown SSM payload schema omits the active base/surge ceiling pair and any window annotation, so every consumer hardcodes the ADR-133 base literal; the July window (a ceiling-shaped mechanism distinct from surge) is invisible to the public surfaces. Structural — any future temp window repeats it.

**Regression guard.** Extend tests/test_receipts_endpoint.py with a temp-window-dated case asserting base_ceiling_usd equals _active_ceilings()[0]; the receipt<->governor lockstep tests are the owning QA layer.

**Path-to-A step.** Have _write_breakdown persist the active (base, surge) pair (one JSON field, ADR-103 rent ~zero); consumers read it instead of _ADR133_BASE_CEILING_USD, which becomes fail-closed fallback only. Auto-reverts 08-01 either way, so this is about the next window, not this one.

**Verifier (CONFIRMED).** Reproduced live: /api/receipts returns base_ceiling_usd 85.0 + ceiling_usd 115.0 + surge_active False, and the inference-receipt note renders 'The $85 base ceiling ($115 in effect)' from hardcoded _ADR133_BASE_CEILING_USD (site_api_intelligence.py:2089, :2169) — whose own comment says it should be fail-closed-fallback only. Verified _write_breakdown's payload in source: tier/mtd/projected/ceiling/ai_daily/non_ai_daily/computed_at/surge_active/recent_uniques/surge_threshold — no base or window field, so the structural root cause (schema omission forcing consumer hardcoding) holds. Not sanctioned by ADR-133, which only keeps the AWS Budgets backstop at $85.

#### cost-5 · CONFIRMED · sev **low** · effort S · class A

**Finding.** Stale cost-machinery comments contradict live configuration: the CDK cost-governor block says 'Cadence: every 4h' and '6x/day' two lines above the actual cron(0 0/8) = 3x/day, and coach_memoir_lambda's docstring calls coach_narrative a 'tier-1 pause' when ADR-125 raised its cutoff to 2.

**Evidence.** cdk/stacks/operational_stack.py:~248-252 ('every 4h (was hourly)... 6x/day') vs :261 schedule='cron(0 0/8 * * ? *)' + its own inline '3x/day' comment; lambdas/compute/coach_memoir_lambda.py:13 ('tier-1 pause') vs budget_guard.py:115 (coach_narrative: 2).

**Root cause.** Comments not updated when the cadence moved 4h->8h and when ADR-125 moved coach_narrative band 1->2; violates the repo's own docs-current-truth-only reflex.

**Regression guard.** No automated guard fits prose comments; the /wrap doc-sync literal reconciliation habit is the owning process — add these two files to the next literal sweep. The memoir case could be caught by extending test_budget_guard_ladder.py to grep docstrings that name a feature+tier pair.

**Path-to-A step.** Two one-line comment edits in the next housekeeping PR.

**Verifier (CONFIRMED).** Both halves reproduced: cdk/stacks/operational_stack.py ~:248-252 says 'Cadence: every 4h (was hourly)... 6x/day' directly above schedule cron(0 0/8 * * ? *) whose inline comment says 'every 8h (3x/day)' — commit 082260a3 (#1254) corrected the cadence elsewhere but missed this block. lambdas/compute/coach_memoir_lambda.py:13 says 'coach_narrative — tier-1 pause' vs budget_guard.py coach_narrative: 2 (ADR-125 raise documented in the cutoff table itself). No open issue covers either comment.

**Path to A (grader's ranked actions):**

1. Migrate /api/status's cost block to the budget-breakdown SSM param (kills the $15 fabrication AND the duplicate daily Cost Explorer call — negative ADR-103 rent), or delete the block and point legacy at /api/receipts.
2. Enforce receipt<->governor price-table parity by test (including cache_read/cache_write keys), price cache tokens and Titan honestly on /api/inference_receipt, and make the 'same math' note true or amend it.
3. Parameterize _alert_surge on the active ceiling pair and pin it with a temp-window-dated unit test in test_cost_governor.py.
4. Persist the active (base, surge) ceiling pair in the governor's breakdown payload so no consumer ever hardcodes a base-ceiling dollar again; _ADR133_BASE_CEILING_USD demotes to fail-closed fallback.
5. Sweep the two stale cost comments (CDK cadence, memoir tier band) in the next literal-reconciliation pass.

**Coverage (what this lens did NOT examine).** Examined: cost_governor_lambda.py end-to-end (projection math, tier bands, temp window, surge, alerts, breakdown), budget_guard.py (full ladder + headroom), bedrock_client tier-3 chokepoint (grep-verified BudgetExceeded at both invoke paths), CDK env wiring (OBSERVE_MODE=false, no MONTHLY_CEILING_USD override), live SSM tier/breakdown/surge params, AWS Budgets actuals ($85 limit, $85.844 actual — the deliberate overrun-signals design confirmed live), live /api/receipts + /api/inference_receipt + /api/status + /api/state_of_matthew payloads, CloudWatch MTD cache-token counts for sonnet, Bedrock/first-party price verification via the claude-api skill, and test-file inventory (10 budget/cost test files exist). NOT examined: the daily brief email's rendered headroom line; the coaching page's tier-2 paused copy beyond state_of_matthew (my /api/coach_commentary and /api/chronicle probes 404'd — likely wrong endpoint names, so tier-2 degradation quality on those two surfaces is verified only in code (allow('coach_narrative') present at 4+ call sites), not live; Day-1 wipe also confounds paused-vs-empty there); the /method/cost/ and /method/receipts front-end JS rendering (API payloads only); the Friday Panel SKIP_TIER=2 lockstep; monitoring_stack budget alarms; contents (not just names) of the 10 test files; per-service non-AI CE breakdown.

**Lens notes.** Dedup: no open issue covers any finding (searched 'budget', 'receipt cost', 'api/status'); #1631 (X syndication gated because per-post billing is invisible to cost_governor) is adjacent context confirming the team already thinks about governor blind spots — cite it if finding 2's fix expands metering. Phase/data-maturity caveats: tier 2 standing is BY DESIGN (shared context; live math verified — projected $103.25 = 89.8% of $115 lands tier 2 via the min(projected, actual+1) rule, arithmetically consistent, not a governor bug even though the July raise was sized to land tier 1 at $96 projected — spend grew past the sizing assumption, which the incident row already records); state_of_matthew {available:false} is the honest Day-1 empty state working as intended (#1197 guard). Dissent-worthy observations for other lenses: (a) /api/receipts is the best ADR-104 artifact I've seen in this codebase — breakdown-as-sole-source, stale-flag-over-frozen-numbers, tokens-not-dollars with the reason published in the payload — worth citing as the pattern the /api/status block should have copied; (b) the projection machinery has both historical failure modes (double-count 2026-06-17, no-de-escalation N-08) documented in-code with their fixes and the actual-mtd cap — genuinely strong; (c) surge is 97 uniques away from tripping (803/900) which is why finding 3's alert-copy bug is time-sensitive despite low severity; (d) AWS Budgets actual has crossed $85 — the operator should expect (or has received) the deliberate backstop signal email; that is correct behavior, no action. Grade rationale: hard-stop chokepoint, ADR-125 ladder, projection math, and the flagship receipts all meet the A bar; the grade is held at B+ solely by the rubric's 'every public and operator-facing cost number matches the live governor state' clause, which /api/status violates outright and the inference-receipt note bends.

### data — Data architect — **NOT GRADED**

This lens never ran (credits exhausted). Prior grade 2026-07-16: **B+**. The delta run must
grade it from scratch against its persisted 2026-07-16 rubric anchors.

### integrations — Ingestion health — **B+**

*Trend: = held at B+.*

**Verifier on the grade:** All four findings survive (three fully confirmed with independent reproductions, one adjusted only on its count-evidence framing while its core doc defect stands), so the surviving set — two real medium ingestion-surface defects plus two low doc/process gaps — comfortably supports the proposed B+ grade.

#### integrations-1 · CONFIRMED · sev **medium** · effort S · class A

**Finding.** Public board renders a real months-long HAE lapse as 'dark' with NO duration: Blood pressure (last logged 2026-04-10, 109 days dark) and State of Mind (2026-04-02, 117 days) show days_dark:null because the liveness scan is capped at ~48 records, so any datatype dark longer than ~45 days loses its 'dark N days' number — exactly when the lapse is longest.

**Evidence.** Live: curl https://averagejoematt.com/api/source_freshness -> dark_datatypes [{'label':'Blood pressure','days_dark':null},{'label':'State of Mind','days_dark':null}]; DDB probe (query apple_health, 514 items to 2025-06-24): BP last blood_pressure_systolic on DATE#2026-04-10, SoM last som_check_in_count on DATE#2026-04-02; cause: lambdas/emails/freshness_checker_lambda.py:332 Limit=HAE_LIVENESS_WINDOW_DAYS+3 (45+3) and compute_datatype_liveness lines 300-304 (nothing in window -> age=None, dark=True)

**Root cause.** lambdas/emails/freshness_checker_lambda.py check_apple_health_datatypes bounds the last-seen query to the newest 48 apple_health DATE# items; compute_datatype_liveness then returns age_days=None for anything older, and site_api_freshness.py:190-192 forwards that null to the public dark_datatypes stamp. The window truncates the very signal the surface exists to report (D-4/#468's 'dark N days').

**Regression guard.** Unit test on compute_datatype_liveness with a fixture whose only BP record predates the window, asserting a numeric age (would fail today); plus a qa_smoke assertion that any dark:true datatype whose partition holds ANY historical record for its fields carries numeric days_dark. Owner: the nightly qa_smoke data-health layer (ADR-104 behavioral-absence semantics).

**Path-to-A step.** Paginate the last-seen query per still-unresolved datatype until found or a ~400-day cap (the daily checker already reads this partition; a few extra pages 1x/day is ADR-103-free), or write an O(1) per-datatype last-seen high-water mark at HAE ingest and read that.

**Verifier (CONFIRMED).** Independently reproduced end-to-end: live /api/source_freshness returns days_dark:null for Blood pressure and State of Mind (numeric 33d/37d for the in-window datatypes); DDB newest-48 apple_health DATE# window bottoms out at DATE#2026-06-11 while filtered newest-first queries confirm the true last BP record at DATE#2026-04-10 (blood_pressure_systolic=141) and last SoM at DATE#2026-04-02 (som_check_in_count=1) — real records the 48-item cap (freshness_checker_lambda.py:332, Limit=HAE_LIVENESS_WINDOW_DAYS+3) makes invisible, so compute_datatype_liveness lines 300-304 emits age_days=None and site_api_freshness.py:190-192 forwards the null. evidence_meta.js only renders 'dark Nd' when days_dark != null, so the longest lapses lose exactly the number the surface exists for. Not a duplicate: closed #1203 fixed a different cause (phase filter), and no open issue covers the window cap.

#### integrations-2 · CONFIRMED · sev **medium** · effort S · class A

**Finding.** The #1371 numbered cross-cycle provenance is structurally dead: all six carried sources on the Day-1 board return carried_from_cycle:null because no writer ever stamps `cycle` on RAW_TIMESERIES records (the phase tagger stamps phase only; the wipe stamps cycle only on tombstoned experiment-scoped rows), and sub-record sources (hevy) have no plain DATE# item at the key the reader get_items — the chip can only ever render the fallback 'carried from a previous attempt', never 'attempt N'.

**Evidence.** Live: /api/source_freshness -> strava/todoist/macrofactor/hevy/measurements/food_delivery all carried:true, carried_from_cycle:null; DDB: strava DATE#2026-07-22, todoist DATE#2026-07-26, macrofactor DATE#2026-06-24 each have phase=pilot and NO cycle attr; hevy has no plain DATE#2026-06-25 item (only DATE#2026-06-25#WORKOUT#259c2691...); writers: deploy/restart_phase_tag.py (UpdateExpression sets/REMOVEs #p=phase only) vs deploy/restart_intelligence_wipe.py:312-342 (cycle stamped only via build_update on wiped intelligence); reader: lambdas/web/site_api_freshness.py:71-91; fallback copy: site/assets/js/evidence_meta.js:287

**Root cause.** Cross-module contract gap: site_api_freshness._carried_from_cycle expects an ADR-077 `cycle` attribute on raw source DATE# records that no component of the reset pipeline writes to raw_timeseries partitions (restart_phase_tag.py deliberately writes only `phase`). The 'fail-soft' docstring masked that the soft path is the ONLY path.

**Regression guard.** A restart_verify (deploy/restart_verify.py) post-reset step asserting at least one carried source on the live board returns a numeric carried_from_cycle; unit test constructing the real stored shape (phase=pilot, no cycle attr) that fails while the number is unreachable. Owner: the reset pipeline's verify layer — this is a #1194-adjacent surface it should own.

**Path-to-A step.** Drop the DDB stamp dependency entirely: derive the cycle from the record's DATE vs the CYCLE_GENESES ledger already maintained in lambdas/web/site_api_data.py (date -> which cycle's window it fell in) — a pure function, no extra read, and it fixes hevy's sub-record shape for free.

**Verifier (CONFIRMED).** Independently reproduced every leg: live API shows all six carried sources (strava/todoist/macrofactor/hevy/measurements/food_delivery) with carried:true, carried_from_cycle:null; DDB get-items confirm strava DATE#2026-07-22 and todoist DATE#2026-07-26 hold phase=pilot with NO cycle attribute; hevy's partition has only DATE#2026-06-25#WORKOUT#259c2691... — no plain DATE#2026-06-25 item at the key _carried_from_cycle get_items (site_api_freshness.py:81-87). Writers verified: deploy/restart_phase_tag.py writes only phase (SET/REMOVE #p, lines 182/216); a repo-wide grep finds no component stamping ADR-077 cycle onto raw_timeseries partitions (whoop_lambda's 'cycle' is the Whoop API endpoint; the wipe stamps cycle only on tombstoned intelligence). #1371 is CLOSED as shipped yet its numbered chip is unreachable — the fail-soft path is the only path. CYCLE_GENESES exists at site_api_data.py:100, so the proposed date-derived fix is real. No duplicate open issue.

#### integrations-3 · ADJUSTED · sev **low** · effort S · class A

**Finding.** CLAUDE.md's ingestion bullet presents Garmin as a live '4x daily' pull while the live EventBridge fleet has NO garmin ingestion rule at all (paused ADR-074, rule removed) — the registry, board, and catalog are honest ('paused'), but the most-read agent doc states superseded cadence as current fact ('docs: current truth only' reflex), and its '15 scheduled ingestion Lambda functions' count doesn't match the 17 live ingestion-stack schedules.

**Evidence.** CLAUDE.md Architecture Overview item 1 ('except Garmin at 4x daily due to OAuth rate limits'); aws events list-rules us-west-2: 91 rules, zero matching garmin (all LifePlatformIngestion-* rules enumerated — Whoop/Withings/Strava/Eightsleep/Habitify/Notion/Youtube hourly 0-5+12-23 UTC, Todoist cron(0 14), Weather cron(0 14,2), Hevy cron(0 12-23), plus enrichment/reconciliation = 17); lambdas/source_registry.py:427 is honest ('OAuth API pull, 4x daily — paused (ADR-074)')

**Root cause.** Hand-maintained prose in CLAUDE.md's architecture bullet was not updated when the Garmin schedule was removed from ingestion_stack; the auto-sync machinery (deploy/sync_doc_metadata.py) covers counts elsewhere but has no rule tying this bullet's cadence claims to source_registry/the CDK schedules.

**Regression guard.** A check_doc_facts.py / sync_doc_metadata rule deriving the ingestion-cadence sentence (or at least the paused-source set and scheduled-lambda count) from source_registry.py + ingestion_stack, with a planted-violation test — the same gate class that already owns lambda/tool counts.

**Path-to-A step.** Pointerize the bullet: replace the hand-rolled per-source cadence prose with 'cadence + paused state per source live in lambdas/source_registry.py (method facet)' and let the count be sync-derived.

**Verifier (ADJUSTED).** The core claim is real but the count evidence is wrong-modeled. Confirmed half: aws events list-rules (us-west-2) returns 91 rules with ZERO matching garmin, while CLAUDE.md's Architecture item 1 states 'except Garmin at 4x daily due to OAuth rate limits' as current live cadence — Garmin has been paused since ADR-074 (2026-06-03) and the registry/board are honest ('paused'). Refuted half: '15 doesn't match the 17 live ingestion-stack schedules' compares functions to RULES — of the 17 LifePlatformIngestion rules, Whoop alone owns three (ingestion/recovery/reconciliation) and five more are enrichment/reconciliation/backfill/poll schedules, none of which are 'ingestion Lambda functions pulling from APIs'.

**Corrected cause/evidence.** The doc defect stands on the Garmin cadence prose alone ('docs: current truth only'). The count discrepancy, if kept, must be stated against the right comparator: cdk/stacks/ingestion_stack.py:9's own docstring says '16 Lambdas (13 scheduled + 1 S3-triggered + 1 API Gateway-triggered)' — so CLAUDE.md's '15 scheduled ingestion Lambda functions' vs 13 scheduled functions, not vs 17 EventBridge rules.

#### integrations-4 · CONFIRMED · sev **low** · effort S · class B

**Finding.** ingest-auth-unhealthy-24h stays red for up to 24h after auth recovers (Minimum over one 86400s period): at review time it was still in ALARM ~15h after Whoop's last 0-emission (07-27 13:00 UTC) with every AUTH_FAILURE marker verified clean — a standing red on a healthy fleet is the exact alarm-fatigue pattern the registry docstring names as the historical failure mode, and nothing in RUNBOOK/alarm description says the lag is expected.

**Evidence.** aws cloudwatch describe-alarms: ingest-auth-unhealthy-24h ALARM since 2026-07-24T21:01 PT, Minimum/86400x1/notBreaching; get-metric-statistics LifePlatform/OAuth IngestAuthHealthy: last Minimum=0 hour 2026-07-27T06:00 PT, all healthy since; DDB AUTH_FAILURE markers absent for all 11 sources (get-item sweep); lambdas/auth_breaker.py:73-74 documents the dimensionless design but not the clear-lag

**Root cause.** Alarm construction in cdk/stacks/monitoring_stack.py (1 evaluation period of 24h on Minimum) trades clear-latency for the deliberate 24h detection window; the process gap is that the recovery-lag semantics are undocumented, so an operator (or Day-1 reviewer) reads a healthy fleet as still-broken. Process fix: document the semantics where the alarm is triaged (RUNBOOK + AlarmDescription), don't just wait out this instance.

**Regression guard.** AlarmDescription text stating 'clears up to 24h after last unhealthy emission — confirm via AUTH_FAILURE markers, not alarm state' + a RUNBOOK triage entry; optionally re-shape to 4 eval periods x 6h Minimum (same 24h coverage, ~6h clear) — but respect the load-bearing-window precedent before shortening anything.

**Path-to-A step.** One monitoring_stack PR: add the description + RUNBOOK line (and the 4x6h eval split if the operator wants faster clears) — zero standing cost, kills the red-on-healthy ambiguity.

**Verifier (CONFIRMED).** Independently re-measured the live state: describe-alarms shows ingest-auth-unhealthy-24h in ALARM since 2026-07-24T21:01 PT with Minimum / 1 evaluation period x 86400s / LT 1 / notBreaching and AlarmDescription null; get-metric-statistics (hourly Minimum, 07-25 through 07-28 04:4xZ) shows the last zero-hour at 2026-07-27T06:00 PT with all 15 subsequent hourly Minimums >= 1 — i.e., the alarm was still red ~16h into a fully-recovered fleet at my check, and by construction stays red up to 24h after the last 0. Whoop's AUTH_FAILURE marker is absent (clean), RUNBOOK.md has zero entries for this alarm, and the monitoring_stack comment (lines 563-576) documents the detection design but never the clear-lag. The finding correctly frames this as an undocumented-semantics/process gap (sev low, fix_class B) rather than demanding the load-bearing window be shortened, so it is not refutable as 'working as designed' — the design is fine, the missing triage documentation is the defect. No duplicate issue found.

**Path to A (grader's ranked actions):**

1. Make HAE per-datatype darkness duration unbounded: paginate check_apple_health_datatypes until each datatype resolves a true last-seen (cap ~400d) or maintain an O(1) last-seen mark at ingest — BP then reads 'dark 109 days' instead of a null. ADR-103: extends an existing 1x-daily checker, no new machinery.
2. Derive carried_from_cycle as a pure function of the record's date against the CYCLE_GENESES ledger already in site_api_data.py (delete the doomed DDB `cycle` read); add a restart_verify assertion that the Day-1 board shows a numbered chip on >=1 carried source — closes both root causes including hevy's sub-record shape.
3. Pointerize CLAUDE.md's ingestion-cadence bullet to source_registry's method/paused facets and sync-derive the scheduled-lambda count (extend the existing check_doc_facts/sync_doc_metadata gate with a planted-violation test).
4. Document ingest-auth-unhealthy-24h's <=24h clear lag in its AlarmDescription + RUNBOOK triage entry (optionally 4x6h eval periods for faster clears at zero cost) so a red alarm on a verified-clean fleet is legible rather than fatigue-training.
5. Tie the youtube freshness-facet flip (freshness/monitored/active_api in source_registry.py:492-525) to the first-video landing as an explicit checklist line under epic #1668, so an actually-live source can't run invisible to every freshness/liveness surface — the flip is currently an unforced manual memory.

**Coverage (what this lens did NOT examine).** NOT examined: qa_smoke's actual Day-1 nightly output and required-tier verdicts (code paths read, run output not pulled); data_reconciliation's Monday gap sweep; dropbox poller / MacroFactor CSV transport live health (macrofactor dark 34d is disclosed behavioral, transport unprobed); notion/eightsleep/habitify/withings lambda internals; the strava/whoop provider-reconcile diff logic itself (alarms OK, algorithm unread); MCP tool_get_freshness_status live output (read-only contract bars invoking the MCP lambda — verified only that it derives from the same registry, source_registry.py:9); HAE webhook auth + end-to-end dedup behavior (water/caffeine reading-level dedup map read at health_auto_export_lambda.py:651-820, not exercised); interior-gap detector correctness (alarm OK, algorithm skimmed); whether Whoop's 07-27 recovery was a manual re-auth or vendor-side transient; the freshness checker's WARNING_HOURS tier and sick-day suppression behavior under real sick records; alert-digest email rendering of the incident.

**Lens notes.** REGRESSION HUNT (#1194/#1203) CAME BACK CLEAN — the 07-16 baseline's headline finding (phase filter blanking last_update for pre-genesis records exactly post-reset) is FIXED and HELD on the maximum-risk day: _latest_date_str and last_sync carry include_pilot=True (site_api_freshness.py:42-50,409-421) and the live Day-1 board reports real last_update + honest behavioral-stale ages for all carried sources (macrofactor 819.7h, hevy 795.7h, measurements 2907.7h). LIVE-FIRE POSITIVE: Whoop OAuth died 2026-07-25T04:00Z (401, auth_breaker_marked in /aws/lambda/whoop-data-ingestion logs), slo-source-freshness paged 07-25 17:39 PT (within ~14h — inside the rubric's one-cadence bar for a 48h-threshold source), IngestAuthHealthy alarm fired independently, checker email hints name the source with a re-auth command (freshness_checker_lambda.py:583-587), and after recovery the gap-aware backfill restored 07-25/07-26 at 07-28T03:00Z with CORRECT phase stamps across the genesis boundary (07-26=pilot, 07-27=experiment) — the machinery worked end-to-end. #471 Todoist standard verified live: cron(0 14 * * ? *) matches the registry's derivation comment, board shows 51.7h age vs 72h threshold = fresh. DEDUP/overlaps: youtube facets deliberately dark until provisioning = epic #1668 (context, not refiled; path-to-A #5 is the process guard, DDB partition confirmed empty, lambda running clean); compute-pipeline-stale ALARM (Source=computed_metrics, since 07-27 09:36 PT) is the compute lens's territory — flagging for them: likely a Day-1 wipe artifact and worth a reset-aware grace or genesis-seeded marker, same class as the 07-16 architecture lens's evaluator-sentinel note. gh searches (freshness / carried cycle / datatype dark / auth alarm) returned no overlapping open issues. DATA-MATURITY: none of the findings depend on cycle-11 thinness — BP/SoM darkness and the null provenance are pre-genesis-rooted structural issues; Day-1 emptiness elsewhere rendered honestly. GRADE RATIONALE: registry-as-single-source with a drift-linter test, live-fire incident success, and the held #1203 fix are A-grade; the grade caps at B+ because the rubric's C anchor — 'a real lapse rendered as no-data with no duration' — is literally instantiated on the public board for two hand-captured health streams (BP 109d, SoM 117d), and the promised numbered provenance never renders.

### devex — Build & ship ergonomics (AI-agent development) — DevEx/SDLC lens — **A-**

*Trend: = held at A-.*

**Verifier on the grade:** All five findings survive (3 CONFIRMED, 2 ADJUSTED on secondary details only — the core defects stand), and the mix of three medium/two low all-effort-S doc/gate-drift issues with no live-pipeline breakage is consistent with the proposed A- grade.

#### devex-1 · CONFIRMED · sev **medium** · effort S · class A

**Finding.** The /deploy skill's hand-maintained function→source mapping table has drifted from ground truth: it lists apple-health-ingestion (function does not exist — live AWS GetFunction returns ResourceNotFoundException, and no apple_health_lambda.py exists in the repo), maps weather-data-ingestion to weather_handler.py (file does not exist; ci/lambda_map.json says lambdas/ingestion/weather_lambda.py), and omits 43 live mapped functions (the entire coach fleet, forecast-engine, state-of-matthew, reading-*, etc.) — so the skill's own fuzzy-match instruction operates over wrong/incomplete data and a fresh agent deploying a coach lambda finds nothing.

**Evidence.** .claude/commands/deploy.md:84 ('weather-data-ingestion → weather_handler.py') and :89 ('apple-health-ingestion → apple_health_lambda.py'); ran a cross-check script vs ci/lambda_map.json → 2 mismatches + 43 functions in map absent from doc; `ls lambdas/**/weather_handler.py` → No such file; `aws lambda get-function --function-name apple-health-ingestion` → ResourceNotFoundException

**Root cause.** .claude/commands/deploy.md lines 70-137 — a hand-typed table duplicating ci/lambda_map.json, violating the repo's own meta-rule (CONVENTIONS 'Facts that drift: run the command, never quote a number'); no gate compares the doc table to the map (test_lambda_map_imports.py validates the map only)

**Regression guard.** A parity test (doc-facts style, planted-violation proven per the #1189 lesson) asserting every deploy.md table row's function+source exists in ci/lambda_map.json and flagging map functions absent from the doc — owned by the CI Lint job's doc-drift gates; better, regenerate the table from the map via sync_doc_metadata so the pre-commit hook keeps it current

**Path-to-A step.** Replace the hand table with generator output from ci/lambda_map.json (or a one-line 'resolve via ci/lambda_map.json' instruction) + the parity test. ADR-103: extends existing sync/gate machinery, zero new standing infra.

**Verifier (CONFIRMED).** Independently reproduced every leg: deploy.md:84 maps weather-data-ingestion to weather_handler.py (file exists nowhere in the tree; ci/lambda_map.json maps lambdas/ingestion/weather_lambda.py); deploy.md:86 lists apple-health-ingestion, which returns ResourceNotFoundException from live `aws lambda get-function` and is absent from lambda_map.json; my own cross-check script counted exactly 43 map functions missing from the doc table (coach-* fleet, forecast-engine, state-of-matthew, reading-*, etc.); deploy.md:38 explicitly instructs fuzzy matching against this table. No fix in `git log -- .claude/commands/deploy.md` since e787f48d, no duplicate open issue. Only trivial correction: the apple-health row is line 86, not 89.

#### devex-2 · ADJUSTED · sev **medium** · effort S · class A

**Finding.** CONVENTIONS §4's canonical pin-discovery commands still grep .github/workflows/ci-cd.yml, but #1655 (merged 2026-07-25) extracted the Lint job — and its black/ruff/mypy pins — to .github/workflows/ci-lint.yml; the documented command now returns only requirements-dev.txt values, and the one live disagreement (CI runs mypy==2.1.0, requirements-dev.txt pins mypy==2.3.0 via Dependabot #1315) is exactly the case the doc says to resolve by 'reading the CI pin' — which the command can no longer surface. The page's Verified: 2026-07-27 stamp post-dates the extraction by two days.

**Evidence.** docs/CONVENTIONS.md:118-119 (grep targets ci-cd.yml + requirements-dev.txt); ran that exact grep → zero black/ruff/mypy hits in ci-cd.yml; .github/workflows/ci-lint.yml:62 (black==25.9.0 ruff==0.14.14) and :75 (pip install mypy==2.1.0) vs requirements-dev.txt:29 (mypy==2.3.0); ci-cd.yml:258-259 ('extracted verbatim to ... ci-lint.yml'); git log -S 'mypy==2.3.0' → Dependabot bump 39f77423

**Root cause.** #1655's extraction PR moved the pins without updating the two discovery commands in docs/CONVENTIONS.md §4 (lines 118-119 and 127-128 for the CDK pins), and the CONVENTIONS re-verification pass on 07-27 didn't re-run the commands it quotes

**Regression guard.** The existing 'pinned-both-directions' check pattern (§4/#814): extend it (or check_doc_facts) with a pin-parity assertion that the tool versions in ci-lint.yml match requirements-dev.txt (or are documented as deliberately split), and point the doc's grep at .github/workflows/*.yml so the extraction class can't blind it again

**Path-to-A step.** Fix both grep commands to cover .github/workflows/*.yml, then resolve the mypy split deliberately (bump CI to 2.3.0 or pin dev back) with the parity assertion folded into the existing Lint job — no new standing machinery.

**Verifier (ADJUSTED).** Core claim reproduced: the documented grep at docs/CONVENTIONS.md:118-119 targets ci-cd.yml + requirements-dev.txt, and ci-cd.yml now has ZERO black/ruff/mypy pins (grep confirmed) — they moved to ci-lint.yml:62 (black==25.9.0 ruff==0.14.14) and :75 (mypy==2.1.0) via #1655's verbatim extraction (ci-cd.yml:258 comment). The live disagreement is real: CI mypy==2.1.0 vs requirements-dev.txt:29 mypy==2.3.0, exactly the case the doc says to resolve by reading the CI pin the command can no longer see. Verified: 2026-07-27 stamp confirmed. But the root cause overreaches on the CDK half.

**Corrected cause/evidence.** Only the black/ruff/mypy discovery command (lines 118-119) is blinded. The §4 CDK-pin grep (lines 127-128) still works — `npm install -g aws-cdk@2.1129.0` remains in ci-cd.yml:377 (the CDK setup was NOT part of the #1655 lint extraction), and aws-cdk-lib==2.262.1/constructs==10.7.1 still resolve from cdk/requirements.txt and requirements-dev.txt. The fix scope is one grep target, not two.

#### devex-3 · CONFIRMED · sev **medium** · effort S · class A

**Finding.** check_doc_index runs advisory by default locally but CI runs it --strict (both ci-lint.yml and docs-ci.yml), so a locally-green push can red CI on engine-doc source drift — this actually fired on 2026-07-27 (deploy_all-2 take-1 caught by CI's --strict gate per the handover), and the lesson was encoded in a memory topic (reference_doc_index_strict_ci_only) rather than in a gate, which is the exact anti-pattern this lens's rubric names (incident classes must live in gates, not agent memory).

**Evidence.** scripts/check_doc_index.py:200 ('strict = "--strict" in sys.argv') + :242-246 (gate 5 advisory unless strict); .github/workflows/ci-lint.yml:282 and docs-ci.yml:87 both run '--strict'; CONVENTIONS §8 quotes the command with no flag; CLAUDE.md session block: 'take-1 caught by CI's --strict engine-doc gate — local runs advisory, → memory'; gh issue search 'check_doc_index strict' → no open issue

**Root cause.** scripts/check_doc_index.py's default mode diverges from every CI invocation; the 07-27 incident's remediation stopped at a memory note instead of aligning the defaults or the documented command

**Regression guard.** Pre-commit hook (scripts/install_hooks.sh) or the wrap skill's doc step runs check_doc_index --strict so local == CI; minimally, the advisory-mode output should print a loud 'NB: CI runs --strict — N advisory items would RED CI' banner (self-documenting parity)

**Path-to-A step.** Make --strict the default (advisory opt-in via --advisory) and update the two doc references — one-line behavior flip on an existing script, converts a memory-only lesson into a structural guarantee.

**Verifier (CONFIRMED).** Reproduced end-to-end: scripts/check_doc_index.py:200 (`strict = "--strict" in sys.argv`) with gate 5 (engine-doc source drift, #973) advisory unless strict; both CI invocations pass --strict (ci-lint.yml:282, docs-ci.yml:87); the local/agent-facing invocation in .claude/commands/wrap.md:170 runs WITHOUT the flag, so local-green/CI-red divergence is structural. The 07-27 incident is recorded in the CLAUDE.md session block ('take-1 caught by CI's --strict engine-doc gate — local runs advisory, → memory') and the remediation stopped at the memory topic reference_doc_index_strict_ci_only.md (file exists) — no gate/default change landed since (git log on the script tops out at e1bcf766), no open issue covers it.

#### devex-4 · ADJUSTED · sev **low** · effort S · class A

**Finding.** The tombstone gate's scan set (docs, *.md in deploy/ and .claude/commands/, and lambdas/+mcp/ .py) has blind spots where the retired shared layer is still asserted as CURRENT: deploy/deploy_reading_mcp.sh tells the agent 'numeric/retry_utils that reading depends on already come from the shared layer, so there is NO shared-layer bump' plus two 'no layer version change' claims, and ci-cd.yml's live comments say the test-critical lane guards 'shared-layer module presence' and 'shared-layer rollback surfaced as a runbook' — the broad tombstone rule exists and would fire, but *.sh and workflow *.yml are never scanned, repeating the pre-2026-07-13 shape that motivated the source scan.

**Evidence.** deploy/deploy_reading_mcp.sh:9-10 (affirmative 'come from the shared layer'); .github/workflows/ci-cd.yml:13 and :271 (current-tense shared-layer claims); scripts/check_doc_tombstones.py:108-117 (SOURCE_DIRS = lambdas,mcp; candidates = deploy/*.md + .claude/commands/*.md + docs/**.md — no .sh, no .github); docs/_lint/tombstones.txt:14-21 (the broad 'ANY shared layer claim' rule that would catch these if scanned)

**Root cause.** The #781 generalized source scan (added 2026-07-13 to check_doc_tombstones.py) stopped at .py files; deploy shell scripts and workflow comments were never added to the candidate set, so retirements can't propagate there

**Regression guard.** Extend check_doc_tombstones.py candidates to deploy/*.sh and .github/workflows/*.yml (with the existing HISTORICAL/changelog exemption grammar), prove it RED on the pre-fix tree per the §8a ritual, then fix the flagged prose — owned by the docs-ci/lint tombstone gate

**Path-to-A step.** One PR: extend the scan set + correct the ~5 flagged lines (deploy_reading_mcp.sh, deploy_reading_data.sh, ci-cd.yml comments). Zero new machinery — widens an existing gate exactly as §8a prescribes.

**Verifier (ADJUSTED).** The blind spot and the stale prose both reproduce: check_doc_tombstones.py:108-117 scans only README/CLAUDE.md/Makefile + deploy/*.md + .claude/commands/*.md + docs/**.md + lambdas,mcp *.py — no *.sh, no .github/workflows. deploy_reading_mcp.sh:9-10 affirmatively claims numeric/retry_utils 'come from the shared layer' (retired by #781/ADR-131), and ci-cd.yml:13 ('shared-layer rollback surfaced as a runbook') and :271-272 ('shared-layer module presence') assert the retired layer as current pipeline behavior. However the finding's claim that 'the broad tombstone rule exists and would fire' on these lines is only half true.

**Corrected cause/evidence.** The `shared[- ](?:Lambda[- ])?layer` rule would fire on the ci-cd.yml lines if scanned — but NOT on deploy_reading_mcp.sh:10, because that line also contains 'NO shared-layer bump', which matches the scanner's RETIREMENT_LINE_RE exemption (`no shared[- ]layer`, check_doc_tombstones.py ~lines 70-75). Extending the scan set to .sh/.yml alone would leave the headline shell-script instance unflagged; the fix must also manually correct those lines (or tighten the exemption), and the §8a prove-RED ritual will only go red on the ci-cd.yml lines.

#### devex-5 · CONFIRMED · sev **low** · effort S · class A

**Finding.** MEMORY.md's AWS Configuration section hand-types the raw S3 path as 'raw/{source}/{datatype}/{YYYY}/{MM}/{DD}.json', contradicting CLAUDE.md's #1256/X-9 ground truth (three-generation fractured layout: most sources raw/matthew/{source}/{YYYY}/{MM}/YYYY-MM-DD.json, legacy no-user-segment, hevy flat UUID; 'read the raw_layout facet, don't construct keys') — a fresh agent's first-five-minutes reading contains two incompatible layouts and the memory copy is the wrong one to follow.

**Evidence.** MEMORY.md AWS Configuration bullet ('S3 raw path raw/{source}/{datatype}/{YYYY}/{MM}/{DD}.json') vs CLAUDE.md Store section (#1256 three-generation layout + 'read it, don't construct keys' pointing at lambdas/source_registry.py raw_layout facet)

**Root cause.** A hand-typed drifting fact in the memory index (outside repo CI reach), predating the #1256 raw_layout registry — violates the CONVENTIONS meta-rule the memory header itself endorses ('the rule lives in CONVENTIONS.md — never in two places')

**Regression guard.** The wrap-time body-follows-index gate (scripts/check_memory_body_facts.py) is the only machinery that can own memory-dir facts — add a rule for constructed raw-path literals, or simply make the line a pointer so there is no literal to drift

**Path-to-A step.** Replace the literal with 'raw layout: per-source, read lambdas/source_registry.py raw_layout (#1256) — never construct keys' in MEMORY.md.

**Verifier (CONFIRMED).** Reproduced: MEMORY.md:13 hand-types `raw/{source}/{datatype}/{YYYY}/{MM}/{DD}.json`, which matches none of the three real layout generations — lambdas/source_registry.py's raw_layout facets (e.g. line 160: prefix raw/matthew/whoop, filename YYYY-MM-DD.json; hevy flat UUID) and CLAUDE.md's #1256/X-9 'read it, don't construct keys' rule. The memory literal is outside repo CI reach, scripts/check_memory_body_facts.py exists as the only plausible owner, and no do-not-refile issue covers it. A fresh agent's first-read context genuinely contains two incompatible layouts with the memory copy wrong.

**Path to A (grader's ranked actions):**

1. Regenerate (or retire) the /deploy skill's function→source table from ci/lambda_map.json via the existing sync_doc_metadata/pre-commit machinery, with a parity test proven RED on today's tree (it would flag the dead apple-health row and the wrong weather row) — kills the hand-table drift class at its root (ADR-103: extends existing sync gates, no new standing infra).
2. Fix CONVENTIONS §4's two pin-discovery greps to cover .github/workflows/*.yml (the #1655 reusable workflows), then deliberately resolve the mypy 2.1.0/2.3.0 CI-vs-dev split and fold a lint-pin parity assertion into the existing pinned-both-directions check.
3. Align check_doc_index local default with CI: make --strict the default (advisory opt-in), update the §8 quoted command and the pre-commit/wrap references — converts the 2026-07-27 deploy_all-2 take-1 incident from a memory note into a structural local==CI guarantee.
4. Extend check_doc_tombstones.py's candidate set to deploy/*.sh and .github/workflows/*.yml (broad shared-layer rule already exists), prove RED pre-fix per the §8a ritual, and fix the ~5 flagged retired-layer claims in the same PR.
5. Replace MEMORY.md's hand-typed raw-S3-path literal with a pointer to lambdas/source_registry.py's raw_layout facet (#1256), honoring the memory index's own no-duplicated-rule header.

**Coverage (what this lens did NOT examine).** INSPECTED with reproduced evidence: docs/CONVENTIONS.md in full; ci-cd.yml structure + ci-lint.yml gates/pins/if-always ordering (matches §4's documented order); one-bundle integrity across all four paths (deploy_lambda.sh:100, deploy_fleet.sh:35-36, deploy_site_api.sh:21, deploy_mcp_split.sh:33, cdk lambda_helpers.py:66-75) + tests/test_deploy_bundle_paths.py run (6 passed); deploy-critical lane run offline with FAKE creds (1376 passed, 43 skipped in 6.8s); all three doc gates run locally (sync_doc_metadata --check PASS, check_doc_facts PASS with 113 docs+298 source files scanned, check_doc_index PASS); backlog_next.py run (Now=#1653 only, matches handover) + check_backlog_hygiene.py run (advisory mode, 1 violation + 2 advisories — consistent with #1868/#1872 state); every deploy.md mapping row cross-checked against ci/lambda_map.json programmatically + one live AWS read (apple-health-ingestion ResourceNotFound); prior-run findings 1-4 re-verified as FIXED with gates (genesis in check_doc_facts #1235, deploy.md site mode/stack owner corrected, CLAUDE.md command signatures corrected); MCP tool count re-discovered (76, matches CLAUDE.md); pre-commit hook installed in this clone. NOT EXAMINED: smoke_test_site.sh internals; site-deploy.yml full text; the remediation-agent workflow; the reconcile job's generator whitelist correctness; docs-ci.yml beyond the --strict grep; the full 8k-test suite (critical lane only); .claude/agents contracts (verified exemplary last run, unre-checked); skills other than /deploy (wrap/uplevel/qa taken on faith); live fleet config drift (no lambda config listing beyond the one GetFunction); the session-archive branch integrity; restart_pipeline's doc-sync step internals.

**Lens notes.** DEDUP: gh issue searches for all five candidates (check_doc_index strict, mypy pin, ci-lint pins, shared-layer deploy scripts, reading_mcp) returned no open issues — none refiled from the do-not-refile list; #1872's advisory-mode hygiene linter and #1653 (lambdas/ packaging, reserved session) are working-as-designed context, not findings; the coach-fleet deploy gap in deploy.md partially overlaps eng-excellence epic #1648's doc-craft territory but no specific open issue covers the table, so it stands as a finding. REGRESSION CHECK vs FULLREVIEW_2026-07-16: all 4 prior devex findings were remediated WITH regression gates (best-practice outcome — the genesis date is now a check_doc_facts scan, not just a fixed line); no recurrence found; the mapping-table defect was flagged as an 'unverified suspicion' last run and is now CONFIRMED — the suspicion-to-finding pipeline worked. HUNT ORDER (prior-cycle leakage, DevEx form): doc surfaces are genesis-current everywhere (cycle 11 / 2026-07-27 consistent across CLAUDE.md, constants.py, and the gated scan); the one 'tombstoned content presented as current' instance found is the dead apple-health-ingestion row in the deploy skill (finding 1). DATA-MATURITY: not applicable to this lens — nothing graded depends on cycle-11 data thinness; budget tier 2 does not affect any gate I ran (all offline). DISSENT-WORTHY: this platform's DevEx is exceptional for a solo operator — a 6.8s offline deploy-contract lane, four byte-identical deploy paths by construction, and an incident→gate conversion culture that actually closed last cycle's findings; the grade stays A- (not A) only because a fresh agent's first-five-minutes reading still contains provably wrong facts (dead deploy row, a pin-discovery command that returns the wrong mypy version) and a locally-green push actually redded CI this week via the --strict divergence — the A bar's 'provably current + local==CI' clauses are each violated once.

### growth — Growth PM — **NOT GRADED**

This lens never ran (credits exhausted). Prior grade 2026-07-16: **B+**. The delta run must
grade it from scratch against its persisted 2026-07-16 rubric anchors.

---

## Relaunch kit — the delta review (on or after 2026-08-02, Fable only)

**1. Refresh ground truth first.** Every number in the "Ground truth" block above will have moved:
experiment day (was Day 1 — a delta run lands ~Day 7+), the budget tier and ceiling (**the July $115/$135
window auto-reverts to $85/$100 on 2026-08-01 — a tier recomputation is guaranteed**), live build vs HEAD,
remediation mode, and the open-issue do-not-refile list. A stale shared-context block is what makes graders
mis-grade Day-N states.

**2. The banked script and its cache.**

```
script:  ~/.claude/projects/-Users-matthewwalker-Documents-Claude-life-platform/
           d35f0f02-d4dc-4078-a6c0-b9353edce3c2/workflows/scripts/
           fullreview-panel-2026-07-27-wf_7a5a8333-cdd.js
run id:  wf_7a5a8333-cdd
journal: .../subagents/workflows/wf_7a5a8333-cdd/journal.jsonl  (26 result rows)
```

**Workflow resume is same-session-only** (the 2026-07-17 lesson) — that session is closed, so the cache is
unreachable. The delta run must re-launch fresh. That is *fine and preferred*: this document IS the durable
artifact, and re-grading the 14 completed lenses against it produces exactly the delta Matthew asked for.

**3. What the delta run owes, in priority order.**

1. **Grade the 3 missing lenses** — security, data-architect, growth — from scratch against their persisted
   2026-07-16 anchors. Security matters most: the repo went PUBLIC on 2026-07-20 and has never been graded
   post-flip by this panel.
2. **Verify the 9 orphaned findings** — cto (4) and observability (5), which have first-pass evidence but no
   skeptic pass.
3. **Re-test a sample of the 63 "survived" findings.** 0 refusals across 12 verifiers is anomalous versus the
   baseline's 19% refutation rate. Sample ~10 across lenses with an explicitly lean-REFUTED brief; if the
   sample holds, the survival rate is real and the panel's evidence discipline has genuinely improved.
4. **Diff the grades mechanically** against the table above, and separate two causes for any movement:
   *(a)* the platform actually changed, *(b)* Day 1 vs Day N of the cycle changed what was observable. The qs
   lens (C+, a two-step drop) and narrative (B-) are the two that most need this disambiguation — both graded
   a site whose intelligence layer had been wiped hours earlier and whose narrative surfaces were tier-2 paused.
5. **Only then** file. Nothing from this run has been filed as issues; the read-only contract held throughout.

**4. What did NOT happen (so the delta run does not double-count):** no issues filed, no code changed, no
deploys, no AWS mutations, no gh writes. The panel was read-only end to end.

