# Life Platform — Open Backlog

> **⚠️ FROZEN — historical archive (ADR-099, 2026-07-03).** The single source of truth for
> forward work is now the **GitHub issue backlog**: epics (`type:epic`) + ranked stories
> (`type:story`) on Now/Next/Later milestones — see
> https://github.com/averagejoematt/life-platform/issues and
> `docs/reviews/BACKLOG_MANIFEST_2026-07.json`. Do not add items here. Every open item below
> was reconciled on 2026-07-03 (41 open → migrated as issues · 29 already shipped · 26 gated ·
> 11 won't-do → the parked register). The shipped-history sections retain archival value.

**Last updated:** 2026-06-29 (Self-Management & Coherence Program Phases 1–4 + the content-bug fix + precision pass + asset-completeness guard ALL SHIPPED — see the section directly below. Prior: 2026-06-23 redesign marathon — Physical/Vitals/Mind pages + Doors IA + RQA-04/05 + WQA-06 all shipped; follow-ups added: PHY-01..06, VIT-01..06, DOORS-01, MIND-01..05 (Mind capture DEFERRED pending invitation-UX sign-off). Earlier: Nutrition/Training/Sleep/Habits shipped, EVR-01..06; 2026-06-09 ER-02 upstream-API contract tests DONE → CHANGELOG; ER external-review-lens rigor series ER-01..08; 2026-06-07 v8.4.0 PG product/growth summit, ADR-077 phase taxonomy + restart tooling)
**Source:** Synthesis of V1 audit (2026-05-17, ADR-057), V2 audit (2026-05-17, `docs/V2_AUDIT_PLAN.md`), V2 follow-up sessions (2026-05-18/19), the 2026-05-29 marathon (Bedrock cutover, budget guard, remediation agent, May-30 restart), the 2026-06-01/02 v4 website launch + QA sweep, and the 2026-06-03 operations/cost session (ADR-074/075). Data-blocked items D-01/D-03/D-04 + N-01/L-11 re-checked against live AWS on 2026-06-03.

> Single source of truth for everything **not done**. Items closed-with-rationale (ADR-057) and items shipped are not listed — see `docs/CHANGELOG.md` for what landed and `docs/DECISIONS.md` for what was formally closed.

### Recently shipped (2026-06-28/29 — Self-Management & Coherence Program + content-bug fix + precision pass)

The platform proved it was ALIVE but not RIGHT — silent-incoherence bugs (predictions inconclusive-for-weeks, recovery 30-vs-86, a coach serving RHR 53 vs the canonical 64) all passed every existing liveness check. The program closes that gap. **All four phases + follow-ups deployed; main green; 0 open PRs.**

- ✅ **Phase 1 — Coherence Sentinel** (#245): `life-platform-coherence-sentinel` (daily 10:45 AM PT, read-only) runs 5 pure invariants in `lambdas/coherence_invariants.py` (each unit-tested by replaying a past outage) → `LifePlatform/Coherence` metrics → the `coherence-overall` digest alarm + a budget-gated Haiku semantic pass.
- ✅ **Phase 2 — shared contracts** (#246/#247): `measurable_metrics.py` (the extractor allowlist DERIVED from `METRIC_SOURCES`, un-driftable) + `canonical_facts.py` (one facts schema + units; a producer-contract test asserts `daily_metrics_compute` writes every field).
- ✅ **Phase 3 — deploy hygiene** (#248): clobber guard in `sync_site_to_s3.sh` + `deploy/session_postflight.py` (layer uniformity + config drift).
- ✅ **Phase 4 — self-healing eyes on content** (#250/#251/#252): the Sentinel persists findings to `s3://…/coherence-log/` + grounds on `canonical_facts`; the remediation agent reads them; `REMEDIATION_TAXONOMY.md` routes every coherence finding to **Bucket B/C only, never auto-merge** (a test enforces no content path on the allowlist).
- ✅ **Content-bug self-correction** (#254): the Sentinel caught coaches serving a hallucinated RHR (53 vs 64). `ai_expert_analyzer` now self-corrects — `_hard_canonical_contradictions` (RHR/recovery/HRV) regenerates the narrative once on a hard canonical contradiction + a no-invent-trends prompt rule.
- ✅ **Precision pass + honest alarm** (#255/#256/#257): `facts_agreement` no longer false-fires on historical/trend mentions; the email-subscriber config drift is resolved; **`coherence-overall` now fires on the DETERMINISTIC invariants only** — the Haiku semantic read is advisory (too noisy to gate a daily alarm). Sentinel reports OVERALL OK.
- ✅ **Postflight asset-completeness guard** (#258): catches the reproducible CDK glitch that ships a Lambda zip missing root `lambdas/*.py` (the silent Sentinel break). `session_postflight.check_asset_completeness()` downloads each bundled-asset canary's zip and asserts its imported root modules are present.

**Open follow-ups (small):** coach physiological fabrication is a quality frontier (now bounded — egregious cases self-correct + trip a precise alarm; soft Haiku noise is advisory — pushing further is its own session); the `ai_calls.py` nutrition guardrail rides the next layer rebuild; optionally wire `session_postflight` into CI.

### Recently shipped (2026-06-28 — coaching commentary-first + Phase-C backends + nutrition 24h-lag, #237–248)

- ✅ **Coaching recut commentary-first** (#237–243): `/coaching/` = The Read · By Coach · Scorecard · Team · lab-notes · Reader Q&A; **C-1** cross-week experiment arc (`/api/experiment_synthesis`), **C-2** cardio-vs-lifts + per-muscle balance, **C-3** gradable predictions + a Scorecard (routed metric+direction claims to the directional/EWMA evaluator; `handle_predictions` reads real `PREDICTION#`).
- ✅ **Nutrition 24h-lag framing** (#244): MacroFactor is a manual end-of-day upload → always ~24h behind by design; every surface (cockpit/coaching/data + 7 MCP tools) now treats the latest COMPLETE day as live, never "not logged today".

### Recently shipped (2026-05-29 marathon — moved out of backlog)

- ✅ **Bedrock cutover** (ADR-062) — all Claude inference on AWS Bedrock + IAM auth.
- ✅ **$75 budget guardrails** (ADR-063) — `cost_governor_lambda` + `budget_guard.py` + tiered AI degradation (1=coaches, 2=website AI, 3=hard cutoff). Enforcement ENABLED.
- ✅ **Self-healing remediation agent** (ADR-064) — daily GitHub Actions workflow, Sonnet 4.6 via OIDC. Phase 1 shadow validated.
- ✅ **Auto-merge gate** (ADR-065) — `remediation/automerge.py` deterministic gate. Phase 2 ENABLED (mode=auto).
- ✅ **May-30 restart** — genesis re-anchored to 2026-05-30 via `restart_pipeline.py` (provisional baseline 304.62 lbs; re-run Saturday post-weigh-in to lock).
- ✅ **Ingestion alarm consolidation** — 12 redundant per-Lambda error alarms removed (~$1.20/mo saved).
- ✅ **Strava paused, freshness IAM fixed, coach seasonality crash fixed, CI verification holes closed, coach truncation fixed across siblings, secret pruning audit (none safely removable).**
- ✅ **PAT rotation** — `gho_` refreshed; classic `life-platform-development` PAT (god-mode, never-used) deleted.

### Recently shipped (2026-06-05 session — moved out of backlog)

- ✅ **L-01/L-02/L-05/L-06/L-10/L-11, D-03, B-03** closed (a few long-tail remain — see below).
- ✅ **S-01** Tier-3 graceful-empty site-api — deployed. **S-06** freshness infra-vs-behavioral split (zero new metrics/alarms) — deployed.
- ✅ **Pipeline status** Evidence dashboard — `GET /api/source_freshness` + `/evidence/pipeline/`.
- ✅ **Cockpit `/api/character` 503 fix** (it 503'd ~16h/day — now reads the latest available record) + **Day-Grade Replay** (per-pillar `score_delta` chip).
- ✅ **a11y:** `--ink-faint` contrast fixed in both themes; constellation `<svg>` `role="img"`→`role="group"`.
- ✅ **`deploy/smoke_test_site.sh` rewritten for v4** (was 58 false failures → 65/0).
- ✅ **Visual + AI-vision UI test harness** (`tests/visual_qa.py` + `tests/visual_ai_qa.py` + CI `visual-qa` job, **ADR-076**) — Playwright deterministic + Claude/Bedrock semantic. Found & fixed the **`/api/coach_analysis` 400** for 4 of 7 cockpit pillars.
- ⚠️ **KMS "cleanup" was a false premise** — the remaining `KMS_KEY_ARN` grants are the LIVE DynamoDB key; do NOT remove (see the restart-followups note further down).

**Operator follow-ups from this session (not auto-done):** `git push` the 17 commits; apply the staged `bedrock:InvokeModel` grant in `deploy/setup_github_oidc.sh` to enable AI-QA in CI; flip the `visual-qa` job advisory→gate after a tuning week. See `handovers/HANDOVER_LATEST.md`.

### Recently shipped (2026-06-05 continued session — moved out of backlog)

- ✅ **D-01** daily-brief prompt-cache waste fixed — `cache_system=False` on the 4 daily-brief calls (root cause: Bedrock cross-region inference defeats region-local cache at once/day volume). Needs layer rebuild + daily-brief deploy.
- ✅ **N-01** `slo-source-freshness` structural false-positive **resolved/closed** — verified live: paused sources already excluded, S-06 deployed; alarm now tracks real infra freshness (flagging a genuine eightsleep/todoist ~2-day gap).
- ✅ **S-02** Evidence depth **done** (premise was stale — no /legacy links remain): bespoke renderers added for intelligence/predictions/benchmarks. Needs site deploy.
- ✅ **visual-qa CI job flipped advisory→gate** (deterministic layer verified green on live prod, 17 pages/0 fails). AI-vision layer self-skips under tier-3 budget so it can't false-block; tune after a budget reset.
- 🔴 **Surfaced N-08** — June budget at **tier 3** (all AI paused) on a projection overshoot ($15 MTD actual). Needs a decision (see N-08).

### Recently shipped (2026-06-06 session — moved out of backlog)

- ✅ **N-08 RESOLVED** — root cause was deeper than "early-month overshoot": after a pause the projection structurally can't decay (`ai_daily = ai/active_days` freezes), so tier 3 would have held until ~Jun 22. Fix (PR #12, deployed): `_decide_tier()` caps projection-driven escalation at **actual-MTD tier + 1**. Tier went 3→**1** (brief + website AI back; orchestrator stays paused — correct, its ~$2.4/day run-rate is real per D-03). 15 unit tests. **Follow-up lever (open):** reduce coach-narrative-orchestrator tokens (D-03) — at current run-rate June will duty-cycle tier 0/1.
- ✅ **D-01 deployed** — layer **v72** published (`SHARED_LAYER_VERSION=72`, PR #13), daily-brief repointed; brief code shipped via PR #11 CI. Other Lambdas catch up on next cdk deploy. Verify next 11 AM brief: CacheWrite=0.
- ✅ **S-02 deployed** — Evidence bespoke renderers + `/feed.xml` alias (L-06) live, verified 200.
- ✅ **Bedrock OIDC grant** — verified ALREADY applied on `github-actions-deploy-role` (matches staged scope); AI-vision QA active in CI now that tier <3. First gated `visual-qa` run green (PR #11).
- ✅ **DLQ 16→2** — all `[AI_UNAVAILABLE]` coach outputs from the tier-3 outage; cause fixed, remainder ages out. (CI `test_i9_dlq_empty` red until then.)
- ℹ️ **Remediation branch open:** `remediation/freshness-date-sk-filter` (no PR) — legit `begins_with(sk, "DATE#")` fix for sentinel-record false-stales in `freshness_checker_lambda.py`. Review + merge.

---

### Training & coaching workstream — Stages 1–3 (2026-06-21, PRs #186/#187/#188)

**Shipped + deployed + live-verified:**
- ✅ **Stage 1 — data integrity** (#186): `get_muscle_volume` completeness signal (B2a), Pallof/carries→Core classifier fix (B2b), `get_freshness_status` MCP interior-gap scan (B3, closed the ADR-092 follow-up). B1 (Strava walk gap) was already fixed by DI-2 #180.
- ✅ **Stage 2 — recovery-adaptive authoring** (#186, ADR-093): freshness gate + tier-agnostic GREEN/YELLOW/RED branches (subtract-only) + `training_context` ceiling/floor modulation, in `manage_hevy_routine`. MCP-only deploy (no layer bump).
- ✅ **Stage 3 Phase 1 — training-notes feedback loop** (#187, ADR-094): derived note-signal projection + bounded Haiku tail + `get_exercise_notes` (#136) + pain elevation + freshness extractor-dark guard. Layer **v88** (#188), backfilled, live.

**Open follow-ups (TR-series):**
- [ ] **TR-01 — Stage 3 Phase 2** (the loop-back, GATED): feed `get_exercise_notes` into the pre-flight + description generator; cross-exercise pattern detection (n-floored ≥3, correlative). **Gate (Viktor):** Phase 1 must be eyeballed against real notes for ~1–2 weeks first — Phase 1 alone is instrumentation, Phase 2 is what justifies the build. Matthew confirms accuracy → build.
- [ ] **TR-02 — `deviation` ingest wiring**: the pure pushed-vs-performed diff (`compute_deviation`) is built + tested but not wired on-ingest — needs a `template_id`↔`movement_key` map (pushed IR keys internally, performed workout keys by Hevy `template_id`). ADR-094.
- [ ] **TR-03 — promote `branches` to a first-class IR field + compiler rendering** (Stage 2): so the autonomous Phase-3 cron authoring path and a future overnight re-stamp inherit the adaptive block. Requires a **layer bump** (routine_ir/hevy_compiler are layer-resident) — deferred from v1 which renders into exercise notes + inputs_snapshot. ADR-093.
- [ ] **TR-04 — overnight re-stamp Lambda** (Stage 2, §8 deferred): post-Whoop-sync, pre-highlight the matching branch. v1 is self-selection only (Matthew's lock); must fail-open to the always-present branches if built.
- [ ] **TR-05 — bring the cron authoring path onto the branch model** (`hevy_routine_cron_lambda` still emits the legacy ideal/floor pair). Pairs with TR-03.
- [ ] **TR-06 — rest as a coach lever (NOT auto)**: prescribed `rest_seconds` round-trips via `get_routine` and is tracked; changing it is a multi-factor coach judgment (bodyweight/goals/phase), never auto-set from recovery. No build — a coaching-discipline note (see memory `feedback_rest_and_params_multifactor`).
- [ ] **TR-07 — reconcile other activity sources** (ADR-092 out-of-scope): source-of-truth reconciliation for Whoop/Garmin (the pattern generalizes; each is a separate opt-in).

---

### Website QA + elite elevation (2026-06-21, PR #190 — plan `zazzy-yawning-quiche.md`)

**Shipped + live-verified (Matthew's 10-item QA pass):** all 8 data-correctness bugs (#1/#3 homepage chronicle feed + genesis labels, #2 lab-notes week_label, #4 `/now/` stale-synthesis hardening + re-run, #5/#6 Hevy cardio/stretching in cardio panel, #7 1RM via weight_kg+Epley, #8 Apple-Health-first steps) + #9 nutrition elevation (calorie-vs-TDEE / protein-vs-target trends, macro stacked bar, periodization/eating-window) + #10 habits elevation (keystone-correlation panel, adherence trend, per-group bars). New `charts.js` primitives `stackedBar`/`correlationChip`.

**Deep-dive elevation SHIPPED (2026-06-21, 4-persona audit → P0–P3, all on main + edge-verified):**
- ✅ **WQA-01 (done)** — audited all ~37 Evidence pages + 5 doors as 4 readers. P0 credibility-breakers (waveform relative tiers · projection suppressed · vices 5-of-6 · 1RM clamp/✓-met · sleep-score sanity gate · null-steps single-source · cost ~$60 · Strava/MF un-paused). P1 dead-panels/placeholders (kvtable nested-render · empty discovery cards dropped · "Check back soon" gone · {duration}→"30 days" · ledger cause-cards incl. snake-rescue · mind_pillar + honest empty). P2 (Day-N/Week-1 home anchor · vanity-count trim · distinct 26/19/11 source labels). P3 (survival/postmortems promoted into "How it holds up").

**Open follow-ups (WQA-series):**
- [ ] **WQA-02 — Nav legibility.** Shared `doors.js` active-door state + what-lives-where captions across the 5 doors.
- [ ] **WQA-03 — visual QA pass.** `tests/visual_qa.py --screenshot --ai-qa` + Matthew eyeballs the elevated pages.
- [ ] **WQA-04 — Third Wall reply (NEEDS MATT'S WORDS).** `matthew_agreement` empty on every field note → AI↔Matthew dialogue one-sided. The platform correctly refuses an AI-fabricated first-person reply (impersonation); Matthew pastes/approves his own to wire it.
- [ ] **WQA-05 — DEXA T-score +3.9 (NEEDS SOURCE VERIFICATION).** Implausible bone T-score on /physical — verify the scan value vs a parse error before touching; don't silently "correct" a real medical number.
- ✅ **WQA-06 — Surface coach disagreements (DONE, PR #204).** Fixed `_team_tensions` field mapping (the integrator digest stores `position_a`/`position_b`/`nakamura_call`, not the old names → positions were empty) + a "where the coaches disagree" head-to-head section on the board with the integrator's call. Live: Nutrition-vs-Labs (protein) + Training-vs-Mind (rest days). The argument surfaced, not averaged.
- [ ] **WQA-07 — Day-N anchor on Story + Coaching** (Home done) — extend the genesis stamp for full cross-site consistency. ✅ DONE (e3f8677b — shared stampGenesis on all 3 reader doors).

---

### Reverse-QA — data-coverage audit (2026-06-21, week-one of data; 2 agents mapped DDB reality vs site coverage)

**Premise:** not "is what we show correct" (the WQA forward pass) but "what's in the data that we're NOT showing, and what trends are now worth surfacing with ~7 days."

**Shipped + live (the cheap high-signal wins):**
- ✅ **RQA-01 — RHR + strain trends** — `pulse_history` now carries `rhr_bpm` + `strain`; charted in Evidence vitals. RHR falling 65→55 during the cut = "body responding," shown nowhere before.
- ✅ **RQA-02 — last-night sleep-stage bar** (Deep/REM/Light stackedBar) — was only single %s.
- ✅ **RQA-03 — MacroFactor micronutrient sufficiency + protein-timing score** — `/api/nutrition_overview` + a panel (sufficiency bars + score figures). Beyond-macros depth.

**Open (each = a new compute endpoint porting an MCP tool's logic + a panel — port carefully + verify vs the MCP output, don't rush):**
- ✅ **RQA-04 — Readiness components on the Cockpit (DONE, PR #202).** `_latest_readiness()` reads `computed_metrics.readiness_score` + `component_scores` into `/api/snapshot.readiness`; `/now/` renders the stored score + worded band (primed/moderate/go-easy, ember not red) + per-component bars (recovery/sleep/movement/habits) above the raw-vitals rows. Cheap read-only surface of a previously-hidden signal; live-verified (score 63 · moderate).
- ✅ **RQA-05 — Deficit-sustainability panel (DONE, PR #203).** Ported `get_deficit_sustainability` → `/api/deficit_sustainability` (phase-filtered) + a five-channel "is the cut costing you?" panel on the nutrition page (HRV/sleep/recovery/habits/training; strain=ember not red; MF TDEE; honest empty <7d). Port verified vs MCP output. Live: severity sustainable, 1/5 degraded.
- [ ] **RQA-06 — Autonomic balance** (`get_autonomic_balance`, FLOW/STRESS quadrant) + **RQA-07 — Zone-2 breakdown** (`get_zone2_breakdown`, Z2 vs 150-min). New compute endpoints.
- [ ] **RQA-08 — Recovery-vs-prior-day-deficit overlay** — dual-line (NO Pearson r at n=7; overlay + "too few points for a coefficient" caption).
- [ ] **RQA-09 — verify glucose/mood panels degrade honestly** (lineChart `<4-pt` rule likely already handles the empty axis) + **suppress `computed_metrics.tsb = −726.8`** garbage if it surfaces.

**Held as premature at week one** (per the audit): metabolic adaptation, ACWR (needs the chronic window), gait trends, HR-recovery, body-comp velocity (1 DEXA), and any Pearson-r correlation chip on the new pairings.

---

### Evidence-page redesign series (2026-06-22, PRs #193/#194 Nutrition · #195 Training · #196 Sleep · #197 Habits)

**Premise:** four turnkey design-review-panel specs (`docs/specs/CLAUDE_CODE_PROMPT_<PAGE>_v1.md` + `docs/SPEC_<PAGE>_REDESIGN_*.md`) → per-P-item implementation, honesty-gated, local-render QA (desktop / mobile-390px / light). All four pages **shipped + deployed + live-verified** (build fingerprint == HEAD each time). New `charts.js` primitives across the series: `intakeSpine`, `sufficiencyBars`, `stackedColumns`, `mealWindowRibbon`, `dualLineChart`, `targetSpine`, `heatStrip` (compact/cutDate), `stackedDayColumns`, `landmarkBars`, `dumbbell` + `lineChart` spine option.

**Habits (#197) — open follow-ups (EVR-series), all genuine needs-data (the honest empty states ARE the build; these wire the capture):**
- [ ] **EVR-01 — per-habit driver capture (trigger + reward).** P1.3 surfaces friction (real, = inverse adherence) but trigger/reward render "— not captured." Needs a per-habit capture step (a one-tap trigger/reward tag in Habitify or a side store) → fills the drivers table. Until then the honest-empty cells stand.
- [ ] **EVR-02 — "why missed" reason capture.** P1.4 shows real miss *counts* but "reason not captured." A one-tap why-on-a-missed-day (travel / illness / low day) turns counts into narrative. No fabricated causes until the capture exists.
- [ ] **EVR-03 — cross-page completion-feed.** P1.5 cross-links each habit group → its evidence page, but the *reverse* feed (a Nutrition/Sleep/Training day's own completion folding into the group score) needs each evidence page to expose a single daily-completion signal, then fold it in without double-counting Habitify. Honest-pending today.
- [ ] **EVR-04 — ship inferred taxonomy *groupings* public (DECISION).** P1.1 derives a logical group per habit (`taxonomy.group`) server-side but the public surface still groups by Habitify's stored group — only the time-of-day/type *context tags* ship (labeled auto-derived). Promoting the derived regrouping to the visible surface was held as a STOP-AND-ASK; revisit if the stored groups prove noisy.
- [ ] **EVR-05 — upgrade taxonomy classifier from name-only heuristic.** `_derive_habit_taxonomy` is deterministic keyword matching on the habit name. A richer pass (habit metadata, or a cheap classification call) would catch cases the keyword map misses. Low priority — the heuristic + "auto-derived, not fact" label is honest as-is.
- [ ] **EVR-06 — keystone coefficient auto-surfaces at ≥14d overlap** (NO build — a windowed watch). Genesis+8d as of ship, so the keystone renders *withheld* live; the P2.1 gate flips the noise-guarded coefficient on automatically at 2 weeks (~2026-06-28). Matthew authorized auto-surface; eyeball it once the window opens.

---

### Physical-page redesign series (2026-06-23, PR #201 — weight cockpit + composition arc + PhenoAge)

**Premise:** fifth turnkey design-review page. Reframed `/evidence/physical/` to "weight is the metronome; composition is the arc" — daily weight cockpit (Tier 1) over an episodic composition arc (Tier 2); replaced the DEXA black-box bio-age with a transparent, privacy-preserving Levine PhenoAge. All P0/P1/P2 shipped + deployed + live-verified. New `charts.js` primitives `weightTrendChart` + `projectionCone`; new `/api/phenoage` endpoint.

**Open follow-ups (PHY-series):**
- [ ] **PHY-01 — PhenoAge age-inversion residual (DECISION).** Option A removes the obvious leak (no chronological age, no gap returned — verified live). But the 9 Levine markers are public on the labs page, so a determined reader applying the formula could approximate chronological age from the precise published phenotypic number (the marker→pheno relationship is ~1:1 in age). Mitigation available if Matthew wants zero-deducibility: band the published PhenoAge (e.g., nearest 5) and/or show drivers as direction-only. Low urgency (sophisticated attack); flagged for owner call.
- [ ] **PHY-02 — schedule DEXA scan two (drives the countdown; unlocks velocity).** ~10 weeks post-genesis (~late Aug 2026). The single highest-value capture step — turns every composition figure from a dated snapshot into a real trajectory. The P1.1 countdown is waiting on it.
- [ ] **PHY-03 — tape measurements capture.** 0 sessions. Cheap, frequent between-DEXA proxy that feeds the silhouette + segmental; the P2.2 card is an honest empty state until the first session.
- [ ] **PHY-04 — progress-photo capture + privacy stance (STOP-AND-ASK before any public/blurred render).** Private-by-default; the faceless silhouette is the public-safe proxy. No public photo render without explicit opt-in.
- [ ] **PHY-05 — composition velocity (GATED).** Lean/fat/visceral change per week — build ONLY once a 2nd valid DEXA exists AND the delta clears the scan's least-significant-change. Placeholder until then (never off one scan).
- [ ] **PHY-06 — complementary ages (optional).** Vascular age (Withings PWV, type 91) + VO₂max fitness age as secondary lenses beside PhenoAge (the anchor). WHOOP Age is NOT in the official API — do not build on the unofficial password-auth scrape without explicit sign-off + a "fragile source" label.

---

### Vitals-page redesign follow-ups (2026-06-23, PR #205 — glance-first, three altitudes)

Front-end-only redesign shipped (status rings, autonomic hero, 2×2, small-multiples). Introduced the reserved `--alert` RED token (state-alerts only, never direction). Phase-3 cards are honest gated states; follow-ups (VIT-series):
- [ ] **VIT-01 — blood-pressure cuff capture** → a BP trend on the vitals page (highest-value missing daily vital).
- [ ] **VIT-02 — hourly habit-completion history** → upgrades the glyph row from "X of N today" to "vs your average by this hour" (no fabricated baseline until then).
- [ ] **VIT-03 — continuous/walking HR · VIT-04 VO₂max trend · VIT-05 subjective energy/mood 1–5** (needs capture).
- [ ] **VIT-06 — cross-metric vitals correlations** (WATCH): withheld until ≥2 weeks overlap; auto-opens reusing the Sleep correlation board. No coefficient drawn before the window.

### Doors / cross-site IA follow-up (2026-06-23, PR #206)

- [ ] **DOORS-01 — Third-Wall reply MECHANIC (STOP-AND-ASK, shared with MIND-04).** The empty reply slot is first-class held-space on Home/Coaching/Mind; the actual reply path (input → store → render Matthew's words) is intentionally unbuilt. Needs the invitation-not-obligation reply UX confirmed + a write path. The platform must never fabricate a first-person reply ([[feedback_sensitive_content]] / WQA-04). One mechanic serves all three surfaces.

### Mind-page redesign series (2026-06-23, PR #207 — Phase 0 shipped; capture DEFERRED)

**Premise:** the most sensitive page. Phase 0 shipped (unnamed restraint cumulative-first, inviting absence, Third Wall, decomposed pillar; ZERO red; fixed a live vice-name privacy leak). Phase 1 (the friction-killer capture) is DEFERRED pending Matthew's sign-off on the invitation-not-obligation UX (its explicit STOP-AND-ASK) + a write path. **No mood/temptation capture coercion, ever; no nags/guilt/gamified streaks on mood; relapse logging must feel safe or it won't happen.**
- [ ] **MIND-01 — 1-tap daily mood (the friction-killer).** ~5 faces/dots + optional note, logged instantly; NO streak counter on mood, no "you missed yesterday." Capturable from Mind / Cockpit / Vitals glyph row / email reply. Accrues into a quiet sparkline. **Confirm UX + build the write path first (site-api is near-read-only).** Highest leverage — likely the one to ship first.
- [ ] **MIND-02 — weekly reflection prompt** → one gentle rotating question as a journal seed; skippable, no guilt.
- [ ] **MIND-03 — temptation quick-log + private resist-rate ledger** (`log_temptation`/`get_temptation_trend` exist as MCP tools — needs a web write path); judgment-free both ways.
- [ ] **MIND-04 — Third-Wall reply mechanic** (= DOORS-01; the held slot is built, the mechanic is gated).
- [ ] **MIND-05 — mood-vs-recovery overlay** (needs ~2 weeks of mood logs): "did I feel as good as my body said?" Observation-only, no Pearson/chip under the window. Placeholder until then.

---

## 📋 By status

| Bucket | Count | Action mode |
|---|---|---|
| **🔴 User-action blocked** | 3 | Waiting on you / AWS Support |
| **⏰ Data-blocked / time-windowed** | 5 | D-03 ✅ closed, D-01/D-04 findings open, D-02/D-05 still windowed (checked 2026-06-03) |
| **🟡 Long-tail low-value** | 5 | L-01/L-02/L-05/L-06/L-10/L-11 ✅ closed 2026-06-03; remaining: L-03/L-04/L-07/L-08/L-09 |
| **🛑 Defer-with-rationale (won't do)** | 9 | Documented `won't-do` unless trigger fires |
| **📦 New work surfaced (post-V2)** | 7 | N-01 ✅ closed · N-08 ✅ resolved 2026-06-06 (tier 3→1) |
| **🌐 v4 website + ops follow-ups** | 5 | S-01 ✅ + S-02 ✅ + S-06 ✅ deployed · B-03 ✅ · S-03/S-04/S-05 open · S-07 deferred |
| **🚀 Product & Growth (PG)** | 7 | NEW 2026-06-07 summit. PG-00 ✅ · **PG-01/02/03/05/06 ✅ deployed; PG-04 ✅ native-SES (CI-deploy pending); PG-14 ✅ Tier-A productionized 2026-06-09 → CHANGELOG** · PG-04b/PG-13 remain · **PG-07 gate-blocked on D-05 (~2026-06-17)** |
| **🔬 External-Review rigor (ER)** | 3 | NEW 2026-06-09 external-lens review. **Done: ER-01 ✅ ER-02 ✅ ER-03 Layer 1 ✅ (objective-gap Tier 1) + ER-05 ✅ ER-06 ✅ (cheap-honesty Tier 2).** Remaining: ER-03 Layer 2 (LLM judge, deferred) + ER-04 / ER-07 / ER-08 (recorded-decision items). Full spec: `docs/specs/ER_EXTERNAL_REVIEW_RIGOR_2026-06-09.md` |
| **🛡️ Self-Sustainability (SS)** | 11 | NEW 2026-06-29 from the "hands-off 6-month" simulation. The engine self-sustains; the seam is failures that **go dark/decay silently**. Top leverage: SS-01 chronicle dark-out · SS-03 loud decay alarms · SS-04 dependabot auto-merge. Spec: plan `soft-baking-toast.md` |
| **TOTAL OPEN** | **~38** | 2026-06-09: ER-01 + ER-02 + PG-14 ✅ closed; +8 ER from external-review lens. 2026-06-07: +14 PG from summit; PG-00/01/02/03/04/05/06 + PG-14-spike closed same day; PG-04b logged |

---

## 🛡️ Self-Sustainability & 6-Month Foresight (SS-series) — 2026-06-29

**Source:** the "hands-off except data entry" 6-month simulation (plan `soft-baking-toast.md`;
3-agent ground-truth on the cron fleet, decay timers, and human-in-the-loop gates).
**Thesis:** the ~50-Lambda engine self-sustains and *gets richer* with data; the seam is that
several failures **go dark / decay silently** instead of **running and telling you loudly**. The
engineer/QS audience is best-served; **friends & family are worst-hit** (the public weekly story
stops). Ordered by leverage.

### A. Self-sustainability hardening (highest leverage)
- **SS-01 — Chronicle auto-publish fallback · ✅ DONE (2026-06-29, #265).** A daily bounded sweep on
  `chronicle-approve` auto-publishes a draft unapproved past the review window (via the same approve
  publish path), bounded `[HOURS=48, MAX_DAYS=10]` so it catches a forgot-to-click draft but never
  resurrects an abandoned one. Deployed + verified live.
- **SS-02 — Podcast HOLD-aging escape · ✅ DONE (2026-06-29).** Holds are now tagged
  `hold_class` (safety|quality); a Mon+Wed sweep (`{"sweep_holds": true}`) auto-**retries** a
  *quality* hold on the current week by RE-GENERATING it through every gate (publishes only if a
  fresh attempt clears the bar — never ships the flagged draft as-is). **Safety/sensitivity holds
  are NEVER auto-released** (deviation from the original note, which lumped sensitivity as soft — an
  acute-crisis week must stay human). Bounded: review window / max-days / retry-cap. Deploy:
  `LifePlatformEmail` (new EventBridge rule + lambda).
- **SS-03 — Loud source-specific decay alarms · 🟢 LARGELY DONE (2026-06-29).** On inspection most of
  the proposed monitors **already exist** — the one real gap was the budget kill-switch:
  - ✅ **budget-tier hard-stop alarm** (NEW, `monitoring_stack`): `budget-tier-hardstop` (BudgetTier
    ≥3 → **urgent**: all Bedrock off, the daily brief itself goes data-only). The ≥2-→-digest case
    (website AI paused) was *already* covered by `life-platform-budget-tier-escalation`, but it
    conflated tier 2 with the categorically-worse tier 3; the new alarm pages promptly on a hard-stop
    instead of waiting for the overnight digest. `cost_governor` already emits the `BudgetTier` metric.
  - ✔︎ **Garmin-staleness** → already covered by `ingest-liveness-unhealthy` (ER-01, "the signal the
    silent 44-day Garmin outage lacked") + Garmin's activity backstop (Strava) is freshness-monitored.
  - ✔︎ **podcast-HOLD-aging** → already surfaced by `panelcast-no-episode-7d` (a HELD episode doesn't
    emit `PanelcastPublished`, so 7 silent days fires). The *auto-release* of soft holds is SS-02.
  - ⏭ **token-expiry-7d** → DEFERRED. Freshness already alarms OAuth >60d / manual-rotation >120d;
    a 7-day early-warning tier maps poorly (we track "last changed", not an expiry timestamp) and
    would be noisy. Revisit only if a token actually expires inside an absence.
  - ⏭ **Dependabot-PR-age** → belongs to **SS-04** (a GitHub-API/workflow check, not a CW alarm).
- **SS-04 — Dependabot safe-auto-merge · ✅ DONE (2026-06-29).** Two workflows: `dependabot-validate`
  (`on: pull_request`, read-only) runs the enforced lint + offline tests against the *bumped* tool
  versions (the main CI/CD only runs on push-to-main, so PRs had no Python validation); and
  `dependabot-automerge` (`on: workflow_run` of a successful validate) approves + squash-merges the
  in-scope root **dev-tooling** group only. Safe-by-construction: self-gated on validate success (no
  branch-protection/`allow_auto_merge` dependency), no PR-code execution under a write token, never
  touches /cdk or runtime, and leaves the PR for a human if a review gate blocks it. **No deploy**
  (workflows activate on merge to main). *(Optional: enabling repo `allow_auto_merge` + required
  checks would make it even tighter, but that's a security-posture toggle left to Matthew.)*
- **SS-05 — Experiment continuity · ✅ DONE (2026-06-29).** **DECISION: runs continuously** — a reset
  is a deliberate manual `restart_pipeline.py` act, never automated; counters legitimately grow
  unbounded. Added a Sentinel `check_experiment_continuity` invariant that ALARMs only when a
  surfaced week DISAGREES with the genesis date (the ADR-077 stale-pre-reset leak) or genesis is
  misconfigured. Deploy: `LifePlatformOperational` (bundled-asset, no layer).
- **SS-06 — Enforce gradable predictions · ✅ DONE (2026-06-29).** The C-3 fix already eliminated the
  `machine`/`threshold=None` spec (routes metric+direction → gradable `directional`, else
  `qualitative`); the residual gap was *write-time visibility*. `coach_state_updater` now emits
  `LifePlatform/Predictions::PredictionGradableShare` per run — a leading indicator of an extraction
  regression (the Sentinel needs ≥8 *closed* preds to see it). Deploy: the coach stack (bundled asset).

### B. Novelty / engagement engine (sustain returnability)
- **SS-07 — "Predict the week" reader loop** — already **PG-07** (gated on D-05, now unblockable).
- **SS-08 — Monthly longitudinal "what changed" · 🟡.** Surfaces cumulative change + newly-unlocked
  correlations as windows open, so a flat day still shows motion. Reuses `longitudinal_summary` +
  the correlation engine. Builds on RQA-06/07.
- **SS-09 — Rotate the podcast/brief format · 🟡.** A format/question-rotation lever so the weekly
  show doesn't feel formulaic by episode 26.

### C. Correctness / credibility rigor
- **SS-10 — Coach-grounding frontier · 🟠.** Push fabrication from detect-and-email → block-and-regen
  at generation time. The known its-own-session item + the `ai_calls.py` nutrition guardrail (rides
  the next layer rebuild).
- **SS-11 — Editorial-image guardrail · 🟡.** Optional human-approve or a quality/denylist check
  before an auto-picked Pexels cover ships (counterweight to "fully automatic"; from the 2026-06-29
  visual-uplevel work).
- **PRE-13** (genome/lab publication granularity) — already deferred; revisit before publishing
  deeper raw data.

**Pending/known (don't re-invent):** B-01 concurrency 10→100 (AWS Support); N-02 subscriber-token
scaling; N-05 V2 audit drift (~2026-08-17).

---

## 🚀 Product & Growth (PG-series) — 2026-06-07 Summit

**Source:** Product + Personal Board joint summit, 2026-06-07 (full record: `docs/reviews/SUMMIT_2026-06-07_PRODUCT_GROWTH_REVIEW.md`).
**Governing test for every PG item:** *does this make Matthew more likely, or less likely, to reach 185?* Growth as a byproduct of real progress = yes. Growth that requires more building or more performance = no.
**Build cap (Reeves/Viktor dissent, accepted):** the platform is already ~2 years more mature than the transformation it documents (genesis re-anchored 2026-05-30, baseline 304.62 lb). PG work is weighted toward **front-door + audience (cheap, non-building)** and **Wedge B showcase (documents what exists)**. Net-new analytic engines are OUT — they violate the 30-day post-genesis data-maturity gate.

### How Claude Code should work a PG item (each session)
1. **Open:** read `handovers/HANDOVER_LATEST.md` then `CLAUDE.md`; confirm `main` is pushed/clean before starting (the 2026-06-05 17-commit backlog must be resolved first).
2. **Scope:** do ONE PG item per session unless they're trivially coupled. Confirm the item's *gate* is met before touching code.
3. **Deploy discipline (unchanged):** Matthew runs all deploys in terminal — never via MCP. Site: per-file `aws s3 cp` (NEVER `--delete` at bucket root) + CloudFront invalidation (`E3S424OXQZ8NBE`) always follows. Lambda: full `web/` package, never single-file (ADR-046); 10s between sequential Lambda deploys. MCP: run `test_mcp_registry.py` before deploy; tool functions go BEFORE the `TOOLS={}` dict. Layer modules (`ai_calls.py`, `html_builder.py`, etc.): require layer rebuild + `SHARED_LAYER_VERSION` bump.
4. **Public AI rule (Anika/Dana):** any reader-facing AI endpoint must (a) keep the LLM strictly interpretive — math in Python, LLM narrates only, correlative + confidence-labelled (Henning standard); (b) ship behind per-IP rate limits + the existing budget-tier degrade (**PG-10 is a hard prerequisite**). One traffic spike must not empty the $75 ceiling and dark-fire the site.
5. **Editorial guardrails (all public surfaces):** no employer/role/industry; partner never named; only alcohol + food-delivery vice categories named publicly; bereavement opt-in only; correlative framing; down-weeks always visible.
6. **Close:** update `CHANGELOG.md` + `PROJECT_PLAN.md` always (other docs per their triggers); `python3 deploy/sync_doc_metadata.py --apply` if counts changed; write handover + update `HANDOVER_LATEST.md`; `git add -A && git commit && git push`. Move the finished PG item out of this file into `CHANGELOG.md`.

---

### PG-00 — Wedge decision (DECISION, do before PG-06+)
- **Decision required from Matthew:** confirm the summit recommendation — **Wedge B now** (build-in-public; the only wedge true today; feeds the enterprise-AI mandate; *capped* to documenting what exists), **Wedge A accruing** (transformation story via chronicle + email list; monetise at ~30 lb + sustained list), **Wedge C shelved** (multi-tenant = existing W-02 trigger).
- **Claude Code action:** none until decided. Once decided, record as an ADR (`docs/DECISIONS.md`) and unblock PG-06.
- **Effort:** decision only. **Gate:** Matthew.

### PG-01 — Story-page honesty hook + 10-sec "what/who" ✅ DONE 2026-06-07 (deployed; everyman/Wedge-A line, PR #31)
- **Why:** the front door assumes you already know what the site is; the Midlife-Wake-up & Casual-Reader segments bounce. The shareable asset (honest *before*, biostatistician-checked) isn't stated anywhere.
- **Files:** `site/index.html` (hero copy / `.h-hero__title` area), relevant copy in `scripts/v4_build_*` if hero is templated; check `site/assets/js/components.js` for hero hydration.
- **Action:** add a one-line hook (honesty framing, no employer/partner per guardrails) + a 10-second "what this is / who it's for" line above the fold. Copy only — do not touch Direction-05 visual identity (Tyrell: it's already world-class).
- **Acceptance:** a first-time visitor can answer "what is this and who's it for" in <10s; `bash deploy/smoke_test_site.sh` stays 65/0; CLS budget (<0.1) unaffected.
- **Effort:** S (copy). **Gate:** none.

### PG-02 — Cockpit first-run reading layer ✅ DONE 2026-06-07 (deployed; dismissible first-run card, localStorage `ajm-cockpit-intro-v1`, visual_qa 20/0)
- **Why:** `/now` is glanceable for the pilot, unreadable for a new visitor (Mara: "can't use it without instructions"). Two-mode: pilot (dense default) vs visitor (narrated first-visit overlay).
- **Files:** `site/assets/js/` (cockpit hydration — locate the `/now` renderer), `site/assets/css/` for the overlay; client-side only, NO api change (James: cheap).
- **Action:** dismissible first-run "what am I looking at" overlay; default stays dense; preserve confidence labels (Henning: "preliminary pattern, n=9" is the credibility moment). Use a lightweight cookie/localStorage flag for "seen".
- **Acceptance:** overlay shows once, dismissible, never blocks the dense view; `tests/visual_qa.py` cockpit still PASS.
- **Effort:** S (client). **Gate:** none.

### PG-03 — Subscribe CTA on every chronicle dispatch + "read from #1" ✅ DONE 2026-06-07 (foot CTA → /subscribe/ + RSS + earliest-by-date back-catalogue link; `dispatches.js`)
- **Why:** the chronicle is the only organic-share engine; today it has no consistent capture or back-catalogue path.
- **Files:** chronicle templates (`site/chronicle/` + `scripts/v4_build_*` for chronicle render), `posts.json` ordering for the "#1" path.
- **Action:** subscribe CTA at the foot of every dispatch; a "start from the first dispatch" link; verify `/feed.xml` (L-06, live) is linked.
- **Acceptance:** CTA present on all dispatches post-rebuild; back-catalogue navigable; smoke test green.
- **Effort:** S (template). **Gate:** none.

### PG-04 — Start the email list + welcome sequence ✅ DONE 2026-06-07 (native SES; v4-corrected welcome + day-2 bridge)
- **Decision (Matthew):** native SES (not an external ESP) — the path already runs on SES.
- **Found:** the full subscribe→confirm→welcome **sequence already existed** on native SES — double opt-in, day-0 welcome, day-2 "bridge" (EventBridge daily), non-destructive unsub, rate-limit, canary skip. The gap was **v4-migration staleness**, not missing infra.
- **Fixed:** welcome email links repointed legacy `/character//mind/` → v4 doors (`/story/chronicle/` first, `/now/`, `/evidence/`, `/story/`); day-2 bridge `FALLBACK_PAGES` repointed (`/live/`→`/now/`, `/chronicle/`→`/story/chronicle/`). Welcome body factored into `_welcome_email_content()` + offline-verified. Pure Lambda code (no IAM/CDK) — deploys via CI on merge (production-approval gate), off the reset path.
- **PG-04b follow-up (deferred, post-reset):** the `subscriber-onboarding` role has **no `s3:GetObject` grant**, so the bridge's dynamic dispatch-card loading has always AccessDenied→fallback in prod. To surface real dispatch cards: add an S3 grant for `site/chronicle/posts.json` in `role_policies.subscriber_onboarding()`, point the key there, deep-link `/story/chronicle/#<week>`, then `cdk deploy` the email stack. Held off Monday so the IAM/CDK change doesn't ride the reset.
- **Acceptance:** confirmed-subscriber + welcome path intact on native SES; canary still skips send (no MAILER-DAEMON). ✓ offline-verified; live after CI deploy.

### PG-05 — Evidence empty-states say *why* ✅ DONE 2026-06-07 (deployed; genesis-aware copy on correlations/predictions/benchmarks, PR #31)
- **Why:** genesis-week Evidence pages (correlations/predictions/benchmarks) are honestly empty; a visitor must read *integrity*, not breakage.
- **Files:** `site/assets/js/evidence.js` (the bespoke `renderCorrelations`/`renderPredictions`/`renderBenchmarks` empty-states), rebuild via `scripts/v4_build_evidence.py`.
- **Action:** empty-state copy explains genesis reset + "fills in as data accrues" with confidence framing.
- **Acceptance:** all 3 topics show explanatory empty-states; `tests/visual_qa.py` 20/0.
- **Effort:** XS (copy). **Gate:** none.

### PG-06 — Wedge B build-log surface ✅ DONE 2026-06-07 (editorial topic `/evidence/build/`, 6 writeups citing real ADRs/modules; no new feature)
- **Why:** the platform/architecture is the only wedge true today (Builder/Engineer segment + enterprise-AI proof). Surfaces the build honestly.
- **Files:** new Evidence topic or dedicated page (`scripts/v4_build_evidence.py` topic registry + an `evidence.js` renderer), sourcing from existing ADRs/`docs/`.
- **Action:** a FINITE set of build-in-public writeups (board framework, AI-vision QA harness, budget governor, "keeping an AI honest about my own data"). **CAP: documents what exists; shipping a writeup must NOT spawn new platform features.**
- **Acceptance:** pages render + indexable; each writeup links to the real ADR/code; no new Lambdas created to support it.
- **Effort:** M. **Gate:** PG-00 = Wedge B confirmed.

### PG-07 — Reader "predict the week" loop (NEXT)
- **Why:** reader-side engagement that does NOT make Matthew perform (Maya's guardrail). Reuses the prediction-ledger machinery you're already validating (D-05).
- **Files:** `PREDICTION#`/`LEARNING#` partitions; a read-mostly public endpoint (hardened per PG-10); a small front-end widget.
- **Action:** "predict whether this week's intervention moves the needle"; aggregate reader predictions; reveal next dispatch. LLM (if any) interprets only.
- **Acceptance:** reader can submit a prediction; aggregate stored + revealed; endpoint passes PG-10 hardening.
- **Effort:** M. **Gate:** PG-10 done; D-05 prediction loop producing real verdicts (~2026-06-17).

### PG-08 — One sustainable social channel + repurposing rhythm (NEXT, ongoing)
- **Why:** organic distribution; Ava: pick ONE channel sustainable for a year, not three abandoned in a month.
- **Action:** each dispatch → one "transparency moment" repost (down-weeks/honesty, not highlights). Process, not code; Claude Code can scaffold a repurposing template/checklist in `docs/content/`.
- **Acceptance:** a repeatable per-dispatch checklist exists; first 4 weeks executed.
- **Effort:** ongoing. **Gate:** PG-03.

### PG-09 — Methodology / SEO / credibility pages (NEXT)
- **Why:** the Skeptic-Clinician segment cites methodology; these are unique, linkable, indexable assets ("the Henning standard", "how I keep an AI honest about my own data").
- **Files:** Evidence/Story page additions + build scripts; ensure indexable (robots/sitemap).
- **Acceptance:** pages live, indexable, internally linked; smoke test green.
- **Effort:** M. **Gate:** NEXT.

### PG-10 — Public AI endpoint hardening ✅ DONE 2026-06-08 (most pre-built; verified + pinned + correlative framing added)
- **Why:** Dana/Anika — a public AI endpoint has an unbounded request denominator; one spike empties the $75 ceiling and dark-fires the whole site (the budget guard already proved it can tier-3 the platform).
- **Found (mostly already shipped, Phase 2.1 2026-05-16):** per-IP **DDB-backed** rate limit on *both* `/api/ask` (5 anon/20 sub-hr) and `/api/board_ask` (5/IP/hr); `_ai_paused_response()` tier-≥2 graceful **HTTP-200** degrade checked **before inference on both handlers** (incl. the 6-call board_ask); `max_tokens` caps (600 ask / 300 per persona); **500-char** input cap; injection scrub + sensitive-category filter + output scrub; `reserved_concurrent_executions=2`.
- **Added (the last gap):** the `/api/ask` system prompt now enforces **correlative-only, never-causal + explicit confidence labels** (Henning standard) — meeting the "outputs carry confidence labels" acceptance. New `tests/test_ai_endpoint_hardening.py` (7 source-grep guards) pins every invariant so it can't silently regress.
- **Acceptance:** ✅ budget can't be breached (rate-limit + pause + token caps + reserved concurrency); ✅ tier-≥2 degrades cleanly (200, not 5xx); ✅ outputs correlative + confidence-labelled. Pure Lambda code (no IAM/CDK) → CI-deploy on merge (production gate); **held for post-reset.**
- **Note:** `board_ask` personas stay opinion/debate by design (clearly a named-experts panel, not the platform asserting data) — left as-is intentionally.

### PG-11 — Wedge A monetisation (LATER, gated)
- **Why:** the transformation story is the biggest-TAM wedge but needs a real result.
- **Action:** guide / cohort / paid narrative tier — design when triggered.
- **Effort:** L. **Gate (hard):** ~30 lb visible honest progress AND a sustained email list. NOT before.

### PG-12 — Light community (LATER, gated)
- **Why:** belonging loop; but an empty forum is worse than none.
- **Effort:** L. **Gate:** critical-mass list (community specialist's trigger).

---

### PG-13 — In-platform "agents" showcase (EXPLORATORY → Wedge B)
*Matthew's idea: "AI agents that do X/Y/Z for the platform — a way to show off my AI use and be creative."*

- **Key insight (cheapest, highest-integrity win):** you ALREADY run a rich agent roster — **surface it before spawning new ones.** Existing agents to name + expose: the 8-agent Coach Intelligence ensemble (`lambdas/coach_computation_engine.py:COACH_IDS`; ADR-047/055), the self-healing **Remediation Agent** (`remediation/` + daily GitHub Actions, Sonnet 4.6 via OIDC, ADR-064/065), the **Visual+AI QA Agent** (`tests/visual_ai_qa.py`, ADR-076), the **Budget Governor** (`cost_governor_lambda.py`, ADR-063), the **Anomaly Detector** (`lambdas/emails/anomaly_detector_lambda.py`), the **Freshness Sentinel** (`freshness_checker_lambda.py`), and **Elena Voss** (the chronicle journalist agent).
- **Phase 1 — Agent roster + activity feed (cheap, no new inference; do this first):**
  - **Files:** new Evidence topic / page via `scripts/v4_build_evidence.py` + `evidence.js` renderer; data sourced from existing agent outputs (remediation PR/commit logs, QA verdicts, anomaly flags, budget-tier transitions, coach ensemble summaries under `ENSEMBLE#`).
  - **Action:** a public "Meet the agents that run The Measured Life" page + a weekly **"Agent Activity"** readout ("the remediation agent fixed X, the QA agent caught Y, the sentinel flagged a 2-day eightsleep gap"). Genuinely novel build-in-public content and a Wedge-B engagement loop. Read-only — no new agent, no new cost.
  - **Acceptance:** page renders from real agent data; no new Lambda/inference; smoke + visual_qa green.
- **Phase 2 — 1–2 net-new creative agents (OPTIONAL, cost-gated, build-cap applies):** e.g. a **Scout** (surfaces studies relevant to the current protocol), an **Adversary** (argues against Matthew's choices — he values being challenged), a **Curator** (gym-playlist maintenance). Each new public agent MUST pass **PG-10** hardening and the interpret-only rule, and counts against the build cap — prefer Phase 1's showcase value first.
- **Gate:** PG-00 (Wedge B) for the public surface; Phase 2 additionally gated on PG-10 + a cost check (Dana). **Effort:** Phase 1 M; Phase 2 M–L each.
- **Adversarial note:** Reeves/Viktor flag new agents as build-itch. Phase 1 is sanctioned (surfacing, ~zero build). Phase 2 is the itch — keep it contained and Wedge-B-justified, not core-platform expansion.

### PG-14 — "AI me" weight-loss visualization — ✅ DONE + DEPLOYED 2026-06-09 (Tier-A → CHANGELOG; B/C deferred)
- **Shipped + live** (front-end only; site synced, CloudFront invalidated): the Tier-A "data figure" — a faceless, monochrome SVG silhouette whose girth is a direct function of the real `/api/journey` weight — renders as the `/evidence/results/` hero (`evidence.js` `dataFigure`/`renderResults`/`WIRE.results` + `evidence.css` `.df-*`). Data-driven, theme-adaptive (`var(--ink)`), `prefers-reduced-motion`-aware, "representative figure, not a photo" disclaimer baked in. Tier B (photoreal) + Tier C (video) remain deferred (honesty/privacy bar unchanged). Final browser visual QA pending CloudFront propagation. See CHANGELOG → "PG-14 — 2026-06-09" + `docs/specs/PG-14_ai_me_spike.md`.

*Matthew's idea: "an AI version of myself that drops weight, like those creative AI videos — how hard would it be?"*

- **✅ Spike complete:** `spikes/pg14_ai_me/` (self-contained prototype + 3 frames) + `docs/specs/PG-14_ai_me_spike.md` (go/no-go). **Finding:** the *honest* version is the *buildable* one — a faceless, monochrome SVG silhouette whose girth is a direct function of the real weight (304→185), morphs convincingly, hallucinates nothing, privacy-safe, on-brand. Torso morph strong; limbs stylised (2D-procedural ceiling). **Rec: GO Tier A** as ONE contained data-driven artifact (e.g. `/evidence/results/` hero or chronicle milestone); **NO-GO/defer Tier B** (photoreal = honesty+privacy bar) **& Tier C** (video = quality). Not deployed (lives in `spikes/`). **Productionization (≈S–M, no new backend) is the owner's call — hold until post-reset to anchor the new genesis weight.**

- **Honest feasibility read (three tiers, cheapest/most-defensible first):**
  - **Tier A — Data-driven parametric figure (RECOMMENDED, buildable, on-brand):** a morphable body figure driven by your REAL data (Withings body-comp, tape `measurements`, weight 304→current→projected 185). Tech: a parametric **SMPL/SMPL-X** mesh rendered headless (pyrender/Blender) → milestone time-lapse via `ffmpeg`; or a lighter **Three.js** figure in-browser. Honest (no hallucination), privacy-safe (generic body, not your face), ties to evidence/measurements you already hold. A "304 → 185" honest time-lapse is a strong Wedge-B/chronicle artifact.
  - **Tier B — Photoreal identity-preserving generation (R&D, privacy- and honesty-gated):** identity-preserving image edit / personalized model on your photos to render "you" at milestones. **Problems to flag, not hide:** (1) a generated "you at 185" is a *guess*, not a projection — presenting it as fact violates the Henning/Lena correlative-honesty standard; must be labelled motivational fiction. (2) Feeding your face/body to third-party generative APIs is a real privacy decision and cuts against the site's pseudonymous-ish posture (no employer, partner unnamed). (3) Identity consistency is still unreliable.
  - **Tier C — Generative AI *video* (DEFER):** image-to-video (Runway/Kling/Veo/Sora-class). Consistent identity + accurate body-change over a journey is beyond reliable quality today; expect artifacts. Revisit as models improve.
- **Spike first (Claude Code, time-boxed ~1 session):** prototype **Tier A** with current data — map weight/measurements → body params, render 3–5 milestone frames, assess fidelity vs. your real measurements. Output a short writeup (`docs/specs/`) + sample frames; decide go/no-go before any Tier B/C work.
- **Gate:** PG-00 (Wedge B framing). Tier B blocked on an explicit Matthew privacy decision + a label-as-fiction commitment. Tier C deferred. **Effort:** Tier A spike S–M; Tier A full M; Tier B L + privacy review; Tier C deferred.
- **Adversarial note:** a creative artifact, not an analytic engine — fine *as* a contained Wedge-B showcase, not a reason to expand the core platform. The most motivating *and* honest version is Tier A driven by real numbers (it moves with actual progress — reinforcing the §1 "185" test).

---

## 🔬 External-Review rigor (ER-series) — 2026-06-09

**Source:** External technical-review lens (2026-06-09 session) — "how would ~10 senior engineers who don't share the platform's own rubric react?" Distinct from the internal Technical Board (R1–R20), which is self-assessment against a self-authored rubric. **Full spec with per-item approach/files/acceptance:** `docs/specs/ER_EXTERNAL_REVIEW_RIGOR_2026-06-09.md`.

**Governing distinction:** ER-01/02/03 close an *objective* gap no external reviewer would sign off without (the silent-outage class, thin upstream-seam coverage, untested AI-output truthfulness). ER-04..08 convert *arguable* critiques (over-provisioning, self-grading, the DB choice) into explicit recorded decisions. None of these are feature expansion — rigor that de-risks what already ships is exempt from the PG build-cap.

**How Claude Code works an ER item:** one item per session; ER-01/02/03 first; new tests must run **offline** so CI can gate; held to the standard they enforce (correlative-only, math-in-Python, Henning confidence bands). Deploy discipline unchanged (Matthew runs deploys in terminal; layer changes need a rebuild + `SHARED_LAYER_VERSION` bump). On close: CHANGELOG + PROJECT_PLAN, ADR where called for, move the item to CHANGELOG.

### ER-01 — Infra-liveness heartbeat (the 44-day-outage class) · Tier 1 · ✅ DONE + DEPLOYED 2026-06-09 (ADR-085)
- **Shipped + live** (layer v77 published via Core; Ingestion/Operational/Monitoring deployed): new layer module `lambdas/ingest_health.py` (pure decision core); `ingestion_framework` records a `USER#system / INGEST_HEALTH#{source}` sentinel + EMF at every terminal path; `pipeline_health_check` `check_ingest_liveness` mode (daily 17:10 UTC) emits `UnhealthySourceCount` + a distinct-subject digest alert; new `ingest-liveness-unhealthy` alarm (16→17); freshness left behavioral-only. 31 offline tests + live smoke (garmin 2/3 throttle streak correctly stayed silent). See CHANGELOG → "ER-01 — 2026-06-09" + ADR-085.

### ER-02 — Upstream-API contract tests (recorded fixtures) · Tier 1 · ✅ DONE 2026-06-09
- **Shipped** (tests only, no deploy): `tests/test_upstream_contracts.py` + 9 scrubbed fixtures `tests/fixtures/upstream/**` (whoop/withings/hae priority + strava/garmin) + `deploy/refresh_upstream_fixtures.py` (live re-pull/scrub/diff) + a CI gating step. Offline suite 1630 green; injection-tested (rename fails shape+roundtrip; planted token fails the scrub guard). See CHANGELOG → "ER-02 — 2026-06-09".

### ER-03 — AI-output eval harness (the "is the advice correct" gap) · Tier 1 · Layer 1 ✅ DONE 2026-06-14 · Layer 2 deferred
- **Why:** `visual_ai_qa.py` checks pages *render*; nothing checks the coach/insight *content* is correlative-only, confidence-labelled, fabricates no numbers, does no LLM math. The board can't see this — it's the same kind of AI grading itself. **Truthfulness gate, not a new engine — build-cap does not apply.**
- **Layer 1 — SHIPPED (tests only, no deploy):** `tests/test_ai_output_faithfulness.py` (offline, **gating**) drives `er03_gate.er03_check` over a labelled corpus `tests/fixtures/ai_inputs/faithfulness_cases.json` (11 cases: good must PASS; planted-bad must FAIL across all four classes — fabricated number / causal connective / unhedged small-N / "Matthew" opener) + a wiring-coverage guard that the reader-facing paths (`coach_daily_reflection_lambda`, `coach_panel_podcast_lambda`) still route through `er03_gate`. 14 tests green; load-bearing (seeded fabrication caught); documented in `docs/TESTING.md` §11. See CHANGELOG → "ER-03 Layer 1 — 2026-06-14".
- **Layer 2 (deferred):** Haiku judge vs an in-repo rubric, self-skips at budget tier ≥2, never blocks on 5xx. Do on a tier-0 window + cost check when appetite allows.

### ER-04 — MCP tool utilisation audit + prune (the 8% problem) · Tier 3 · Effort M
- **Why:** 133 tools, ~11 used in 30d (EMF `LifePlatform/MCP ToolInvocations`). Sharpens **B-02** from time-gated (re-eval 2026-07-17) to decision-driven now.
- **Action:** classify every tool used / justified-long-tail (annotate the cadence) / dead-weight; prune dead-weight in 10–20 batches via the existing `AUDITED_AT` ratchet; ADR records the keep/justify/prune rule + 90d trigger. First candidates (B-02): `tools_lifestyle.py` orphans (~3,400 LOC), `tools_correlation.py` (~1,553 LOC), `compare_*_periods` variants.
- **Acceptance:** every tool classified; `test_wiring_coverage.py` + registry tests green; catalog/registry reconcile via `sync_doc_metadata.py`; ADR recorded.
- **Gate:** supersedes B-02's date gate; don't ride a reset.

### ER-05 — De-weight the self-grade + external-review readiness · Tier 2 · ✅ DONE 2026-06-14
- **Shipped (docs only):** prominent **"What these grades are — and are not"** caveat atop `REVIEW_METHODOLOGY.md` (internal self-assessment vs a self-authored rubric, grades only ratchet up, only a cold external senior-engineer review is a trusted A); recorded that `generate_review_bundle.py` is the single self-contained cold-read bundle (verified: 2,924-line / 212KB single file, runs offline) and is the intended input to that one external review. Caveat to be reproduced atop each review. See CHANGELOG → "ER-05/06 — 2026-06-14".

### ER-06 — PII-to-public-surface guarantee (tested) · Tier 2 · ✅ DONE 2026-06-14
- **Shipped:** `deploy/pii_surface_guard.py` (offline scanner) + `tests/test_public_surface_pii_guard.py` (**gating**) over the committed `site/` tree, three arms — blocked-vice keywords (`seeds/content_filter.json`), structural PII (SSN / 16-digit / non-allowlisted email), and a literal personal denylist loaded from a **non-committed** source (`config/pii_denylist.local.json` gitignored, or env `PII_DENYLIST_JSON`; repo is PUBLIC). Same scanner runs **fail-closed in `sync_site_to_s3.sh` before the S3 sync**. **First run caught a real leak:** the public `challenges_catalog.json` shipped two `public:false` blocked-category templates (stripped, 84→82) + fixed the read-path `_is_blocked_vice(name **or** id)` bug that missed id-only keywords. `config/pii_denylist.example.json` template committed. See CHANGELOG → "ER-05/06 — 2026-06-14".

### ER-07 — Complexity posture ledger (load-bearing vs scaffolding) · Tier 3 · Effort M
- **Why:** the "over-provisioned for N=1" verdict splits entirely on *purpose*; today that's implicit, so complexity accretes undecided. **Scope: a technical posture decision, NOT a build-vs-health referendum.**
- **Action:** classify each major subsystem (remediation agent + auto-merge, us-east-1 edge, budget tiers, per-Lambda DLQs vs consolidated, X-Ray-everywhere, the 3 boards) as (a) load-bearing / (b) justified-as-portfolio / (c) retire-candidate; one ADR ("complexity posture, 2026-06"); act on (c); record the standing rule that new enterprise-pattern infra must name which frame justifies it.
- **Acceptance:** every listed subsystem has an explicit verdict + rationale; (c) scheduled/removed; standing rule in the ADR.
- **Gate:** none — decision-only, no deploy risk.

### ER-08 — DynamoDB-vs-analytical-store decision ADR · Tier 4 (defer-leaning) · Effort S + optional spike
- **Why:** single-table DDB (no GSIs) is an awkward fit for analytical/time-series/cross-source data and the big MCP query layer partly compensates; the choice may be right but is implicit. **Do NOT migrate.**
- **Action:** ADR stating why DDB, what it costs in query expressiveness, and the revisit trigger (e.g. DuckDB-over-Parquet-in-S3 as a read-side layer *alongside* DDB if ad-hoc analytics are needed); optional `spikes/er08_duckdb_readside/` re-implementing one correlation query to size the alternative.
- **Acceptance:** ADR makes the implicit explicit with an honest cost statement + concrete trigger; any spike stays in `spikes/`, ships nothing.
- **Gate:** low priority; defer behind Tiers 1–3.

---

## 🔴 User-action blocked

### B-01 — AWS Lambda concurrency quota raise
- **Filed:** AWS Support case 177921309700709 on 2026-05-19
- **Ask:** Account concurrent-execution limit 10 → 100
- **Cost:** Free
- **Unblocks:** Reserved concurrency rollout (pre-staged in CDK, commented out)
- **Action when approved:** Uncomment `reserved_concurrent_executions=` in `cdk/stacks/operational_stack.py` for 5 Lambdas (mcp, site-api, site-api-ai, daily-brief, hae-webhook); deploy via `cdk deploy LifePlatformOperational`.
- **ETA:** ~24h from filing

### B-02 — MCP tool bulk-delete decision window
- **V2 plan:** Recommended 60-day grace before bulk-pruning 124 unused MCP tools
- **Re-evaluate:** 2026-07-17 (60 days from V2 audit)
- **Data:** Per `LifePlatform/MCP ToolInvocations` metric, only 11 of 135 tools called in last 30d
- **First-pass candidates (already removable):** `tools_calendar.py` ✅ done, ~70 orphan `tool_*` functions in `mcp/tools_lifestyle.py` (3,400 LOC), `mcp/tools_correlation.py` (1,553 LOC), various `compare_*_periods` variants
- **Action:** When ready, run orphan-tool ratchet down from `AUDITED_AT=64` toward 0 in batches of 10-20

### B-03 — show_and_tell/screenshots/ local cleanup — ✅ DONE 2026-06-03
- The 169MB had already been cleared in a prior pass; only an empty `screenshots/` dir remained (0B, untracked). Removed it. Closed.

---

## ⏰ Data-blocked / time-windowed

### D-01 — Cache hit-rate quantification (V2 P1.5) — ✅ DONE 2026-06-05
- **daily-brief (14d):** CacheRead **0** vs CacheWrite 10K → cache delivered no savings and the writes were pure 25%-premium cost.
- **Deeper root cause (2026-06-05):** all 4 daily-brief Claude calls use the *same* model (`AI_MODEL`=sonnet-4-6) and the *same* `shared_system` preamble, so intra-invocation reuse *should* have hit — yet 0 reads. The cause is **Bedrock cross-region inference**: `us.anthropic.claude-sonnet-4-6` routes each call to whichever region has capacity, and prompt cache is region-local. A once/day, 4-call brief writes a fresh cache each call and never reads one back. Not fixable at the app layer for low-volume callers.
- **Fix shipped:** `cache_system=False` on all 4 daily-brief call sites in `lambdas/ai_calls.py` (`call_training_nutrition_coach`/`call_journal_coach`/`call_board_of_directors`/`call_tldr_and_guidance`) + corrected the stale "Phase 3.8" comment in `daily_brief_lambda.py`. `coach-narrative-orchestrator` caching left untouched — it's high-frequency, keeps a region warm, and hits (382K reads/14d).
- **Deploy + verify:** ✅ deployed 2026-06-06 — layer v72 published, daily-brief repointed. After the next 11 AM brief, `daily-brief` CacheWrite should drop to 0 with unchanged output.

### D-02 — Coach hit_rate threshold tuning (V2 P3.6)
- **Wait until:** ~2026-07-17 (60 days for confirmed/refuted verdicts to accumulate)
- **What changed:** V2 P1.1 (already-shipped) enforces `_normalize_metric_hint` whitelist; predictions with invalid hints become qualitative-only (correctly skipped by evaluator). New predictions from 2026-05-17+ should have measurable verdicts.
- **Action when data exists:** Read `coach_quality_gate.PASS_SCORE_THRESHOLD = 60`; tune based on actual hit_rate_pct distribution; promote advisory → blocking on score < 40

### D-03 — Per-Lambda AI spend ranking (V2 P1.4 followup) — ✅ checked 2026-06-03
- **Data now exists.** 7 Lambdas emit input/output tokens via `LifePlatform/AI` (`LambdaFunction` dim): coach-narrative-orchestrator, daily-brief, coach-history-summarizer, coach-ensemble-digest, coach-state-updater, coach-quality-gate, api_ask. (Fewer than the "9 of 22" BACKLOG estimated — site_api/site_api_ai/partner dimensions not observed in the 14d window.)
- **Ranking (input tokens, 14d ending 2026-06-03):**
  1. **coach-narrative-orchestrator — 8.03M in / 539K out** ← dominant spender, ~8× the next. Sonnet narrative path. Caching already engaged (D-01).
  2. daily-brief — 1.02M in / 163K out (cache wasted — see D-01)
  3. coach-history-summarizer — 557K in / 27K out
  4. coach-ensemble-digest — 434K in / 83K out
  5. coach-state-updater — 416K in / 257K out
  6. coach-quality-gate — 275K in / 74K out
  7. api_ask — 0 in window (website AI quiet or budget-gated)
- **Reduction levers:** coach-narrative-orchestrator is the only real target — everything else is rounding error. Levers: tighten its system prompt / context window, confirm Haiku isn't viable for sub-sections, verify cache hit-rate stays high. Re-run this query monthly.

### D-04 — SES open-rate baseline (V2 P1.6 followup) — ⚠️ root cause found 2026-06-03
- **Checked:** Send=175, Delivery=110 over 14d, but **no `Open`/`Click` metric is published at all** (not zero — absent).
- **Root cause (not Apple-Mail masking):** `aws sesv2 get-configuration-set --configuration-set-name life-platform-emails` returns `TrackingOptions: null` and `VdmOptions: null`. Open-tracking is **not enabled**, so SES never injects the tracking pixel and never emits the Open metric. The V2 assumption that the config set auto-tracks opens was wrong.
- **Decision needed (not just "wait for data"):** To get open-rate you must `aws sesv2 put-configuration-set-tracking-options` with a CNAME-validated `CustomRedirectDomain` (open pixel + click redirect rewrite). That's a privacy tradeoff for a personal/low-volume list — may be a deliberate "won't do." Until configured, open-rate is permanently unobservable.

### D-05 — Coach prediction loop validation (V2 ADR-055)
- **Wait until:** ~2026-06-17 (30 days post-loop closure)
- **What it tests:** Daily coach predictions get auto-evaluated against measured outcomes. Pre-V2 = 100% inconclusive (theatrical). Post-V2 should produce real confirmed/refuted verdicts.
- **Action when data exists:** Run `aws dynamodb query --table-name life-platform --key-condition-expression "begins_with(sk, 'PREDICTION#')" ...` and count by `verdict` field. Expect mix of confirmed/refuted (not 100% inconclusive).

---

## 🟡 Long-tail low-value (chip away when bored)

### L-01 — multi-line prints in `anomaly_detector_lambda.py` — ✅ DONE 2026-06-03 (`0e41f11`)
- 5 `print()` → `logger.info()` (file at `lambdas/emails/anomaly_detector_lambda.py`; logger already present). Needs anomaly-detector deploy to take effect in logs.

### L-02 — redundant explicit imports in `mcp/registry.py` — ✅ DONE 2026-06-03 (`0e41f11`)
- Dropped 5 redundant single-name re-imports (`tool_get_autonomic_balance`, `tool_get_sleep_environment_analysis`, `tool_get_deficit_sustainability`, `tool_get_metabolic_adaptation`, `tool_get_journal_sentiment_trajectory`) — all already in the bulk imports above them. Registry flake8 violations 131→126; wiring-coverage test green. Needs MCP deploy to take effect.

### L-03 — Site_api AI-handler extraction — ✅ CLOSED 2026-06-06 (already done; premise stale)
- The V2-era 7,879-line monolith no longer exists: `site_api_lambda.py` is ~738 lines, the package is multi-module (`site_api_coach/data/intelligence/observatory/social/vitals/common`), and `/api/ask` + `/api/board_ask` live in the dedicated `lambdas/web/site_api_ai_lambda.py` (own Lambda). Nothing to extract.

### L-04 — Shared module adoption in exempt ingestion Lambdas — ✅ DONE 2026-06-06 (PR #19, deployed)
- `dropbox_poll`: all 6 raw `urlopen` sites → `http_retry.urlopen_with_retry` (it was the one with raw HTTP — the backlog had it inverted).
- The rest was stale: macrofactor + food_delivery have **no raw HTTP left** (Tier-1 teardown); dropbox has no DDB float writes; food_delivery's Decimals are money formatting, not converter duplication; HAE's `floats_to_decimal` is **deliberately divergent** (NaN/Inf→None — DDB rejects `Decimal('NaN')` — and 4dp sensor rounding) and is now documented in-code as do-not-"clean-up".

### L-05 — `print()` in `garmin_lambda.py` — ✅ DONE 2026-06-03 (`0e41f11`)
- Last `print()` → `logger.info()` at `lambdas/ingestion/garmin_lambda.py`. Moot in practice (Garmin retired, ADR-074) — done for consistency if ever revived.

### L-06 — RSS feed `/feed.xml` alt-path 404 — ✅ DONE 2026-06-03 (`0e41f11`)
- `scripts/v4_build_rss.py` now writes `site/feed.xml` as a byte-identical alias of `rss.xml` (duplicate-file approach — `redirects.map` is auto-generated by `v4_migration_inventory.py` so a manual 301 there would be overwritten). Live after next `bash deploy/sync_site_to_s3.sh`.

### L-07 — DEPENDENCY_GRAPH.md SPOF/partition estimates — ✅ DONE 2026-06-06
- SPOF table re-derived: whoop/macrofactor reader counts refreshed (string-level, dated), MacroFactor row notes the ingestion pause (ADR-061/074), "Anthropic API" row corrected to **AWS Bedrock** (ADR-062/063 failure semantics), quota row marked still-pending (verified live: limit still 10).

### L-08 — SCHEMA.md per-source field tables — ✅ DONE 2026-06-06 (full line-by-line cross-check)
- Every per-source table verified against `lambdas/ingestion/*`. Highlights fixed: 3 query-breaking wrong Withings field names (`fat_ratio_pct`/`hydration_kg`/`heart_pulse`); apple_health XML table was 6-of-7 wrong; `total_kilojoules` marked legacy-only (⚠️ still read by hypothesis_engine/tools_nutrition — code follow-up candidate); state_of_mind clarified (lives in the apple_health partition; `som_top_*` are strings); MacroFactor `daily_summary` v2 format documented; **hevy got a field table + SK patterns** (it had none despite being the primary strength source); Garmin v1.5.0 fields; ~10 smaller missing-field groups.

### L-09 — MCP_TOOL_CATALOG.md per-section tool tables — ✅ DONE 2026-06-06 (full line-by-line cross-check)
- Verdict: zero stale entries, zero misplacements, but **17 of 133 registry tools were missing** — added (Coach Intelligence ×6, Coach Actions/Quality ×3, Unified Workouts ×3, Field Notes/Ledger ×3, Vacation Fund ×1, Meta ×1) with param signatures AST-extracted from the registry. Stale "127" counts fixed in 4 places (the banned grep method removed); warmer table corrected (14 steps, `centenarian_benchmarks` was missing); phase-filter section de-staled (retired SIMP-1 tool names).

### L-10 — `webhook-key` reference in `cdk/stacks/role_policies.py` — ✅ NOT AN ISSUE (verified 2026-06-03)
- The only `webhook-key` mention (lines 405-406) is a deliberate *historical note* explaining the secret was deleted 2026-03-14 and `ingestion-keys` replaced it. There is **no stale IAM grant** — no resource ARN references a dead secret. The comment is useful context; leaving it. Closed, no change needed.

### L-11 — DLQ depth — ✅ DONE (verified 2026-06-03)
- `life-platform-ingestion-dlq` now holds **0 messages** (ApproximateNumberOfMessages=0, NotVisible=0). The 66 stuck pre-Garmin messages aged out at 14d retention. No action needed; ingestion gaps self-heal via gap-detection backfill regardless.

---

## 🛑 Defer-with-rationale (won't do unless trigger fires)

These items are documented in ADR-057 or surfaced in V2 plan as won't-do. Do not re-open without new evidence.

### W-01 — Split `intelligence_common.py` (1,556 LOC)
- **Why won't-do:** Only 1 importer (`ai_expert_analyzer`); splitting multiplies imports without benefit
- **Reopen if:** A second major importer emerges

### W-02 — Multi-user / Cognito (V1 Phase 6, ~4 FTE-weeks)
- **Why won't-do:** No second user on horizon
- **Reopen if:** Real subscriber begins onboarding to their own dashboard

### W-03 — Cross-region DR (V1 P8.13)
- **Why won't-do:** Overkill for personal platform
- **Reopen if:** SLA pressure or regulatory requirement

### W-04 — Site_api full router split (V2 P6.6, 7,879 LOC monolith)
- **Why won't-do:** Touches public surface, risk > benefit
- **Reopen if:** A new endpoint requires touching the file substantially

### W-05 — HAE handler registry refactor (V1 P4.6)
- **Why won't-do:** Cleanup-only; current per-data-type code works
- **Reopen if:** 6th+ data type added

### W-06 — Lambda Power Tuning campaign (V1 P8.6)
- **Why won't-do:** Most Lambdas already at 256MB minimum; daily-brief unsafe to tune (sends real emails per invoke); realistic savings $1-3/mo
- **Reopen if:** Memory-related throttling becomes an issue

### W-07 — Batch API (V1 P5.9)
- **Why deferred:** Original plan said reconsider July 2026
- **Reopen on:** 2026-07-15 with 3 months of post-caching AI cost data

### W-08 — Inline JS extraction from `site/index.html` (V2 P6.2)
- **Why won't-do:** 22 KB across 15 inline scripts; touches many DOM IDs; risk of breaking dashboard hydration; cosmetic benefit
- **Reopen if:** CSP hardening (drop `'unsafe-inline'`) becomes priority

### W-09 — DLQ on 16 "async" Lambdas (V2 P6.5)
- **Why won't-do:** Operations stack explicitly sets `dlq=None` for scheduled health-check Lambdas; self-healing on next cron tick
- **Reopen if:** A specific Lambda's failure mode would benefit from manual replay

---

## 📦 New work surfaced (post-V2)

Items that came up during V2 follow-up sessions and aren't yet scheduled.

### N-01 — long-standing alarms — ✅ 4 of 5 cleared (checked 2026-06-03), 1 structural remains
- **Cleared:** `life-platform-dlq-depth-warning` (OK since 2026-05-28), `life-platform-garmin-data-ingestion-errors` (OK since 2026-05-29), `life-platform-ingestion-dlq-messages` (OK since 2026-05-28). `ingestion-error-whoop` no longer exists (the `ingestion-error-*` alarm family is now per-compute/email-Lambda and all 34 are OK).
- **`slo-source-freshness` structural false-positive — ✅ RESOLVED (verified live 2026-06-05).** The "count=3 forever from paused sources" premise was already false: paused sources (Garmin/Strava/MacroFactor) are **commented out of `SOURCES` entirely** in `freshness_checker_lambda.py`, so they're never counted, and S-06 (`3bde46d`, deployed 2026-06-03 21:27 UTC) excludes behavioral sources (measurements/food_delivery) from `StaleSourceCount`. Live count has dropped from a permanent 3 to a fluctuating 1–2.
- **The alarm now behaves as designed** — it fires only when a genuine infra source exceeds its per-source threshold. At verification time it flagged `eightsleep` (51h) and `todoist` (51h), i.e. a real ~2-day gap — exactly the signal it's meant to surface (digest-routed, non-paging). No code change: lowering those thresholds would blunt a working signal.
- **Operational note (not a code item):** eightsleep + todoist showed a live ~2-day data gap on 2026-06-05/06 — worth a glance to confirm it's behavioral (didn't use device / no tasks closed) vs an ingestion issue.

### N-02 — Subscriber `confirm-token` lookup uses DDB scan
- Per V2 audit web/DX agent
- Currently fine (subscriber volume low)
- Re-evaluate when >2000 subscribers; switch to GSI-less pattern (item-per-token)
- Effort: 1h refactor + test
- Trigger: subscriber count

### N-03 — Email dark-mode CSS
- V2 plan: 30% of recipients use dark mode; emails currently assume light
- Add `@media (prefers-color-scheme: dark)` block in `html_builder.py`
- Effort: 3h design + test in real clients

### N-04 — Site `h1` semantic vs visual review
- V2 closed: hidden h1 is valid SEO pattern; left alone
- Possible follow-up: convert `.h-hero__title` from `div` to `h1` and remove the hidden one
- Skipped because of CSS cascade risk
- Effort: 2h careful refactor

### N-05 — V2 audit drift checks: re-verify all v1-shipped items are still working in 90 days
- Schedule a 2026-08-17 audit (per V2_AUDIT_PROMPT.md cadence)
- Use `docs/V2_AUDIT_PROMPT.md` for the v3 round
- Cost: ~1 session of focused agent work

### N-06 — Coach `quality_gate` threshold promotion
- Currently advisory (logs score, doesn't block); V2 wired it but kept it observational
- After 30 days of scores accumulating, decide: promote to retry-with-stricter-prompt on score <60? block on score <40?
- Re-evaluate: 2026-06-19

### N-07 — `compute_metadata` adoption gap-filling
- V2 P2.6 expanded to 5 more compute Lambdas; `acwr_compute` skipped (uses update_item)
- Future: if `acwr_compute` ever switches to put_item, add tag_record there
- No ETA — only if pattern changes

### N-08 — June budget tier 3 — ✅ RESOLVED 2026-06-06 (PR #12, deployed; tier now 1)

- **Resolution:** `_decide_tier()` in `cost_governor_lambda.py` caps projection-driven escalation at actual-MTD tier +1 (and ignores the projection entirely inside the early-month window). Found a second, worse failure mode while fixing: post-pause the projection structurally can't decay (`ai_daily = ai/active_days` freezes), so the old code would have held tier 3 until ~Jun 22 with AI off the whole time.
- **Decisions (a)/(b)/(c) answered:** (a) the ~$2.4/day AI run-rate is REAL (orchestrator-dominated, matches D-03) — not transient; (b) yes, projection was too trigger-happy — fixed via the actual-spend cap rather than a one-off floor; (c) no manual reset needed — redeployed governor re-computed tier 1 on invoke.
- **Open follow-up:** the real spend lever remains coach-narrative-orchestrator token reduction (see D-03). At current run-rate June will duty-cycle between tiers 0/1 — acceptable, but trimming the orchestrator unlocks full tier-0 months.
- Original report follows for context:
- **Observed:** SSM `/life-platform/budget-tier` = **3** (set 2026-06-05 17:00 PT). At tier 3 the budget guard hard-cuts ALL AI: daily brief skips AI, website `/api/ask`+`/api/board_ask` return "paused", and `bedrock_client.invoke()` raises `BudgetExceeded` (confirmed live — the AI-vision QA layer self-skipped with "monthly $75 ceiling reached").
- **But actual MTD spend is only $15.38** (Cost Explorer, Jun 1–5). The tier is **projection-driven**: ~$3/day run-rate × 30 ≈ ~$90/mo projected → ≥95% of $75 → tier 3. So it's an early-month linear-extrapolation overshoot, not a real $75 breach — yet it's currently degrading the product (no AI brief, no website AI).
- **Decisions needed:** (a) is the ~$3/day June run-rate real and worth reducing (prime suspect: `coach-narrative-orchestrator`, the dominant AI spender per D-03 — 8M in-tokens/14d), or a transient (restart aftermath)? (b) Is the cost_governor's linear projection too trigger-happy this early in the month — should it weight actual-vs-projected or add an absolute-spend floor before tiering to 3? (c) Short-term: manually reset to tier 0 for testing (`aws ssm put-parameter --name /life-platform/budget-tier --value 0 --type String --overwrite`) if the projection is judged a false alarm.
- **Relation to D-01:** the daily-brief cache fix trims waste but is rounding error vs this; the real lever is the projection logic + coach-narrative-orchestrator token budget.

---

## 🌐 v4 website + ops follow-ups (2026-06-01/02/03 sessions)

Surfaced during the v4 "The Measured Life" launch, QA sweep, and operations/cost session. Documented in `handovers/HANDOVER_LATEST.md`; folded here for single-source-of-truth.

### S-01 — Tier 3 graceful-empty site-api deploy (committed, NOT deployed)
- **Status:** Code committed (`ee88b6b`); awaiting CI/CD production approval or manual `/deploy site-api`.
- **What it does:** Converts 503s on `/api/nutrition_overview` + `/api/correlations` to shaped-empty 200s (restart-safe); 4 more endpoints audited to match. Files: `lambdas/web/site_api_observatory.py` (+ siblings).
- **Action:** Deploy full `web/` package (never single-file — ADR-046/deploy.md), then verify the two endpoints return shaped-empty 200 not 503.

### S-02 — Evidence depth — ✅ DONE 2026-06-05 (premise was stale)
- The "14 archive topics link to /legacy" framing was **obsolete**: v4 `site/assets/js/evidence.js:153` already zeroes all `/legacy` link-outs ("everything lives inline in v4 now"), and the registry has no `archive`-mode topics. The real remaining gap was *depth*: 3 data-mode topics still rendered via the generic auto-table fallback (`renderGeneric`).
- **Fixed:** added bespoke renderers `renderCorrelations` (intelligence), `renderPredictions` (predictions), `renderBenchmarks` (benchmarks) in `evidence.js` + registered them in `RENDERERS`; rebuilt via `scripts/v4_build_evidence.py`. All 3 endpoints are empty this genesis week (restart wiped intelligence) so they show honest bespoke empty-states now and rich readouts as data accrues.
- **Deploy:** ✅ synced 2026-06-06 — all 3 topics + `/feed.xml` verified 200 live.

### S-03 — Cockpit Week scope — ✅ DONE 2026-06-06 (PR #20, deployed + browser-verified)
- Week scope renders real `/api/observatory_week` reads for 6 domains: sparkline of actual daily values, week's primary number, delta vs prior week. Sparse domains are omitted with an honest count ("2 of 6 instruments reporting" in genesis week — fills in as data accrues). **Month stays honestly gated** (the record is days old; a month view would re-run the week — false affordance; revisit ~30 days post-genesis). Also fixed a latent scope→Today restore bug (`.voice.human` stayed hidden).

### S-04 — RSS real-time refresh — ✅ CLOSED 2026-06-06 (won't-do-as-specified)
- The chronicle index (`site/chronicle/posts.json`) is repo-static and deploy-bound — instant-RSS-only would announce posts the chronicle page doesn't list yet (feed/index desync). The coherent unit is a larger "instant chronicle publish" feature (approve lambda updates posts.json + page data + RSS together); the current weekly flow already couples them at deploy. Reopen only as that full feature.

### S-05 — visual_qa coverage — ✅ DONE 2026-06-06 (PR #17)
- The 3 bespoke Evidence pages (intelligence/predictions/benchmarks) added to the gate (20 pages, verified 20/0 live). Legacy repointing moot — no UI links to /legacy remain.

### S-06 — slo-source-freshness alarm still firing — ⚠️ needs a decision (re-diagnosed 2026-06-03)
- **Correction:** paused sources are ALREADY excluded — Garmin/Strava/MacroFactor are commented out of `SOURCES` in `freshness_checker_lambda.py`. So the alarm (StaleSourceCount=2-3) is firing on **genuinely stale ACTIVE behavioral sources** (e.g. `measurements` now >60d, others lapsing), not paused ones. The alarm is arguably working as designed.
- **The real question (your call):** the SLO alarm trips at `StaleSourceCount ≥ 1`, so ANY behavioral source lapsing pages it — structurally noisy for a personal platform where infrequent logging is normal. Options: (a) accept it (routed to digest, not paging) and just keep behavioral `SOURCE_STALE_HOURS` overrides current; (b) split the metric into infra-stale (OAuth broken — alarm) vs behavioral-stale (you haven't logged — informational, no alarm); (c) raise the threshold. Not a mechanical fix — needs a product decision before coding.

### S-07 — daily-brief cache-write waste — 🔬 DIAGNOSED 2026-06-03, deferred (not worth changing)
- **What was investigated:** daily-brief builds one `shared_system` preamble (`ai_calls.daily_brief_shared_system`) and passes it to 4 calls (`call_board_of_directors`, `call_training_nutrition_coach`, `call_journal_coach`, `call_tldr_and_guidance`) — all same model (Sonnet, no `model=` override), identical system block, `cache_system=True`, seconds apart. By design (Phase 3.8) calls 2-4 should hit the cache. They don't: CacheRead=0, CacheWrite≈740/day over 14d.
- **Why it's NOT a global Bedrock/cross-region issue:** `coach-narrative-orchestrator` caches fine (382K reads / 67K writes, same Bedrock path + cross-region profiles). So the 0-reads is **daily-brief-specific**.
- **Ruled out (from CloudWatch logs, 2026-06-02/03 runs):** TTL expiry (BoD→Training/Nutrition are ~12s apart, far inside the 5-min TTL), model mismatch (all 4 default to Sonnet), and the `shared_system=None` fallback (no "shared_system build failed" warning logged). The block is built once and shared — yet calls 2-4 still don't read it.
- **Root cause still unconfirmed:** needs per-call `cache_read_input_tokens`/`cache_creation_input_tokens` logging (only the aggregate metric exists today; the text logs don't break it down). Leading suspect: `shared_system` sits near/under the ~1024-token Sonnet cache-engagement floor, so Bedrock silently skips the read. Confirming requires instrumenting daily-brief — itself a deploy not worth 2¢.
- **Why deferred:** the *waste* is the 25% write premium on ~740 tokens/day = **~$0.02/month** (negligible). The 4 functions live in `ai_calls.py` (a SHARED LAYER module) and are daily-brief-only, but changing them still needs a layer rebuild + redeploy. Speculatively disabling caching (might be the wrong fix — the orchestrator proves it *can* work) on a shared module, via a ~20-Lambda layer deploy, to save 2¢/mo is upside-down. **Do NOT disable blindly.**
- **If ever picked up:** first pull daily-brief's per-call Bedrock cache token logs to confirm root cause; if the 4 calls genuinely share a cacheable ≥1024-token prefix, make caching *work* (recover the intended $1.50-2/mo); only if it's structurally impossible, set `cache_system=False` and bundle into the next layer rebuild. Not a standalone deploy.

---

## How to add to this backlog

When you discover a new tech debt item:

1. Pick a category (User-action, Data-blocked, Long-tail, Won't-do, New-work-surfaced)
2. Assign an ID (next number in sequence within category)
3. Add a section like the ones above with: title, source/why-found, action, trigger/timing, effort estimate
4. Commit with `docs(backlog): add B-NN ...`

If you do an item, move it to `docs/CHANGELOG.md` and remove from here. If you decide an item won't ever be done, move it to `docs/DECISIONS.md` as an ADR with rationale.

---

**Verified:** 2026-05-19 — synthesized from V1 audit + V2 audit + V2 follow-ups


### Restart 2026-05-18 follow-ups

- [x] **2026-05-27: Wrapped 20 of the original 21 clear-cut USER#-data sites** across 3 batches (commits 0bcb771 + 3796a5f + 5f4d969). Covers web (site-api family), MCP tools, ingestion (apple_health), and email Lambdas (chronicle, weekly_digest, monthly_digest, anomaly_detector). Skipped 1 intentionally (subscriber count — SUBSCRIBER records deliberately untagged per ADR-058).
- [x] ~~**Deferred — remaining ~46 phase-relevant sites + 145 truly-unclear sites.**~~ — **✅ DONE 2026-06-07 (PR #23).** Full AST inventory of all 268 query sites (the "~46" was an undercount): 112 wrapped (incl. structural helper wraps), 68 verified exempt, 22 explicit `include_pilot=True` cross-phase annotations (clinical labs/DEXA, ACWR/circadian/training continuity, longitudinal MCP research tools), 65 already covered. The inventory found public endpoints serving 100% pilot data (discoveries/experiments/hypotheses/correlations) — now filtered. Layer v74. Owner retention rule recorded: clinical = date-independent; progress = resets on website at restart; everything stays in DB. **Follow-on: the phase-taxonomy registry (expert panel review in progress) makes this coherent permanently.**
- [ ] Re-evaluate phase filter at 30/60/90 days post-restart (ADR-058 §13).
- [x] ~~Remove orphan IAM references to `S3_KMS_KEY_ARN` in `cdk/stacks/role_policies.py`~~ — **DONE 2026-05-24** (grants removed). Only `S3_KMS_KEY_ID` (`5c50ca02…`, PendingDeletion) remains as an unused constant in `constants.py:28` + two explanatory comments; keep until the key fully deletes 2026-06-16, then drop the constant.
  - ⚠️ **2026-06-05 — do NOT remove the remaining `KMS_KEY_ARN` grants.** Verified against live AWS: `KMS_KEY_ARN` references `444438d1…` (alias `life-platform-dynamodb`, **State: Enabled**), which is the **DynamoDB table's SSE-KMS key** (`life-platform` table `SSEType: KMS` → this ARN). The ~32 `kms:Decrypt`/`GenerateDataKey` grants are LOAD-BEARING — every Lambda needs them to read/write DDB. An audit/roadmap pass flagged these as "orphan grants" by conflating them with the deleted S3 CMK (`5c50ca02`); removing them would lock the platform out of all its data. The bucket itself is AES256 (no S3 CMK).
- [x] ~~DLQ has 62 stale messages — drain via `life-platform-dlq-consumer`.~~ — drained 2026-05-24 (down to 0).
- [x] ~~`life-platform/notion` secret is `MARKED FOR DELETION` — confirm intentional or re-create.~~ — verified 2026-05-24: secret is healthy (`DeletedDate: null`, last changed today), actively referenced by `notion_lambda.py`, `freshness_checker_lambda.py`, `pipeline_health_check_lambda.py`. Was likely restored before this BACKLOG note got written. No action needed.
- [ ] Decide whether to resurrect 1-2 specific chronicle entries via `restart_chronicle_handler.py --resurrect-sk`, or leave the chronicle blank until the next Wednesday cycle generates the first fresh entry.

### 2026-05-24 P3.4 site-api work follow-ups

- [x] ~~Site-api Lambda is missing the shared layer attachment.~~ — **Code staged 2026-05-24.** `shared_layer=shared_utils_layer` added to `SiteApiLambda`, `SiteApiAiLambda`, and `SiteStatsRefresh` in `cdk/stacks/operational_stack.py`. Awaits next `cdk deploy --all` (deferred to post-launch to avoid hot-fix-overwrite risk).
- [x] ~~CloudWatch dashboard for `LifePlatform/SiteAPI` EMF metrics.~~ — **verified DONE 2026-06-06**: `life-platform-site-api-dashboard` exists live (`monitoring_stack.py` — p50/p95 per top-6 routes + cold-start rate).
- [x] ~~Subscribe-page CLS 0.151 (over the 0.1 budget).~~ — **Fixed 2026-05-24.** Root cause: empty `#amj-nav` / `#amj-hierarchy-nav` / `#amj-subscribe` mount points shifted content when components.js populated them. Added `min-height` reservations in `site/assets/css/base.css`. CLS now 0.091 (under budget).

### 2026-05-24 post-launch CDK deploy follow-ups

- [ ] **Batched `cdk deploy --all` post-launch.** Pending changes staged in CDK code:
    1. Remove orphan S3 CMK grants from all IAM role policies (`cdk/stacks/role_policies.py` — `S3_KMS_KEY_ARN` deleted from 26 PolicyStatement resources). Bucket is AES256, key in PendingDeletion until 2026-06-16. Code-complete; deploy deferred to avoid the CDK reconcile hot-fix-overwrite risk on launch eve.
    2. Reattach shared layer to `site-api`, `site-api-ai`, `site-stats-refresh` (see above).
    3. Run after Monday's launch settles. Use `cdk deploy --all --hotswap-fallback` and verify against `restart_verify_rendered.py` (27/27) immediately after.

### 2026-05-25 launch-eve bug sweep — fixed + open follow-ups

**Fixed and deployed 2026-05-25 01:30–02:30 UTC:**
- [x] `site_writer.py` — `JOURNEY_START_WEIGHT` referenced at module-load before its import. Caused `(non-fatal)` warning on every daily-brief run. Moved the `from constants import ...` block above the `HERO_WHY_PARAGRAPH` f-string. Deployed via daily-brief bundle.
- [x] `coach-quality-gate` IAM gap — daily-brief role granted `lambda:InvokeFunction` on coach-computation-engine etc. but not coach-quality-gate. Every coach call logged `AccessDeniedException (non-blocking)`. Added the ARN to the `CoachIntelligenceInvoke` policy statement. Deployed via `cdk deploy LifePlatformEmail`.
- [x] Canary subscribe bouncing — `/api/subscribe` synthetic subscriber `canary+<ts>@mattsusername.com` resulted in SES sending a confirmation email that then bounced (MAILER-DAEMON spam). `email_subscriber_lambda.py` now reads `source` from POST body and skips the confirmation send when `source == "canary"`. Deployed to both us-west-2 and us-east-1.
- [x] Canary alert-on-any-failure — every transient blip emailed `🔴 canary: 1 failure(s)`. Added a 2-consecutive-fail buffer using DDB state at `USER#system / CANARY#last_state`. Only alerts when the SAME check has failed in both the previous AND current run. Deployed.
- [x] 43 CloudWatch alarms still publishing to immediate-email SNS topic `life-platform-alerts` — root cause of "AWS Notification Message" + alarm-flap spam. Batch-rerouted to digest topic via `aws cloudwatch put-metric-alarm` script. CDK source updated (mcp_stack + operational_stack `add_alarm_action`/`add_ok_action` lines now point at `local_digest_topic`).
- [x] `pipeline-health-check` Lambda had no `SNS_ARN` env var, falling back to hardcoded `life-platform-alerts` topic. Set env var to digest topic via CLI.

**Open follow-ups:**
- [x] ~~**Garmin OAuth rate-limited (HTTP 429)** — needs manual re-auth.~~ — **Superseded by ADR-074 (2026-06-03): Garmin direct-API ingestion RETIRED/paused.** Garmin's 2026 anti-automation crackdown 429-blocks server-side OAuth2 refresh from datacenter IPs (374 throttles vs 2 successes / 14 days — unwinnable headless). Garmin is commented out of `freshness_checker_lambda.py` SOURCES + OAUTH_SECRETS. **Revive options (open decision):** Terra wearable aggregator (free, official, webhook — 3rd-party privacy tradeoff) · official Garmin Health API (B2B, approval-gated) · residential proxy (paid, fragile). See ADR-074.
- [x] **The 5 duplicate Morning Brief emails** were caused by `aws lambda invoke daily-brief` during my P3.4 / phase-filter test cycles. Lesson: never invoke an email-shipping Lambda unless explicitly intended. **The DRY_RUN gate EXISTS (added 2026-05-26):** invoke with `{"dry_run": true}` or set env `DRY_RUN=1` — both SES sends are gated; `{"force_send": true}` overrides. Verified 2026-06-06.
- [ ] **`compute-pipeline-stale` alarm** will fire tomorrow (genesis = first day) because compute hasn't run yet. Now routes to digest, so it'll batch into one email. Once compute runs at 11 AM PT Monday, alarm self-clears.
- [ ] **JOURNAL_COACH validator BLOCKED empty output** in daily-brief logs (currently every run). Cause: pre-genesis there are no journal entries, so the coach returns empty, the validator blocks it as low-quality. **Expected pre-launch behavior** — once you start journaling (via Notion), the coach will produce output and the validator will accept it. Self-resolves; no code change needed.
- [ ] **Training coach prompt drift** — `[ai_validator] WARNING: Output starts with 'Matthew' — prompt instruction may have been ignored`. Quality issue, not blocking. The Sonnet prompt for the training coach tells the model not to start with "Matthew" — Sonnet is ignoring that instruction. Worth a prompt-engineering pass post-launch.
- [ ] **76 untagged DDB records discovered + retro-tagged** via `restart_phase_tag.py --apply` 2026-05-25 02:24 UTC. Root cause: per-Lambda write paths (`character_engine.store_character_sheet`, daily-brief insight writes, ingestion writes between phase-tag runs) didn't add phase tags. Fixed `store_character_sheet` to tag pre-genesis writes as `pilot`; **other write paths still don't tag**. Acceptable for now (untagged passes the filter as "experiment"), but a future hardening pass should add a `compute_metadata.tag_record(item, phase=...)` helper used by every writer.

**Source freshness inventory captured 2026-05-25 02:25 UTC** — 3 fresh (whoop, apple_health, habitify), 9 stale. Of the 9: only Garmin is a code bug (above). The rest are behavioral (macrofactor=44d, food_delivery=58d, measurements=57d, notion=23d, etc.) and resolve when you log data.

### 2026-05-25 MacroFactor Tier 1 — TORN DOWN (was blocked by Firebase App Check)

- [x] **MF unofficial-API path removed.** Closed same day it was deployed. Firebase App Check blocked the auth endpoint; 5 workarounds all failed. Code, Lambda, IAM role, EventBridge rule, secret, and DDB state record all removed. ADR-061 "Update 2026-05-25 (same day, later)" documents the attempt and tear-down rationale for institutional memory.
- [x] **Tier 2 (manual MacroFactor Dropbox export) is the only food-level + MF-workout path.** Unchanged.
- [x] WS-3 schema migration of historical MF Dropbox workout records — no longer needed since there's no Tier 1 to dedupe against. Existing `_expand_legacy_aggregate` bridge in `mcp/tools_hevy.py` continues to surface them via `source="macrofactor_export"`.

### 2026-05-24 phase-filter sweep — deferred-with-reason

- [x] ~~**~254 raw `table.query()` callsites still bypass the phase-filter chokepoint.**~~ — **✅ DONE 2026-06-07 (PR #23).** See the restart-followups entry above: 268 sites inventoried, 112 wrapped, 68 exempt, 22 annotated cross-phase. Known restart-coverage gap surfaced for the taxonomy work: `ENSEMBLE#digest` is neither tagged nor wiped.
