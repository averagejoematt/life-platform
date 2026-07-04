# Data-Source Health Review — 2026-07

> **Self-grade caveat (ER-05):** every judgment in this review is internal AI self-assessment against the platform's own code, stored data, and live surfaces — not external validation. Findings were adversarially verified (each citation re-opened, each live probe re-run by an independent verifier), but the grader and the graded share a brain.

**Date:** 2026-07-04 · **Repo state:** `origin/main` @ `40cbbc4a` (post #453/#454/#455 — `source_registry.py` #392 live, layer v97) · **Probes:** live AWS (us-west-2) + averagejoematt.com, captured 2026-07-04 ~06:20–08:30 UTC.

## Scope

Owner-requested (brief of 2026-07-04): a full health review of **every data-source integration** — what we pull, how we pull it, why we pull it, how it's stored, what custom calculations sit on it, and how honestly the site presents it — plus a forward-looking roadmap for extracting structured signal from free-text journal entries.

**15 sources reviewed** across 8 dimensions each (API/auth · storage · timing · CRUD/idempotency · best-practice deltas · custom calculations · site honesty · value/posture):

- **SIMP-2 framework (8):** Whoop, Withings, Strava, Eight Sleep, Habitify, Todoist, Weather, Garmin (paused, ADR-074)
- **Pattern-exempt standalone (7 paths):** Notion journal, MacroFactor (+ dropbox_poll chain), Apple Health / HAE webhook (CGM · water · BP · State of Mind) + the dormant XML export path, food delivery, measurements, Hevy (cursor backfill + parked webhook)
- **Cross-source merges:** unified sleep, device agreement, training load/TSB, weight resolution
- **Cross-cutting lenses:** integration architecture (framework vs standalone), merge honesty under degraded inputs, journal free-text extraction (as-is + roadmap)

**Purpose:** feed an outcome-ranked backlog batch (ADR-099 pipeline: findings JSON → scored stories → GitHub issues, gated on owner green-light).

## How this review was run

Stage 0 reconciled the open-issue ledger (13 open `area:data` stories/epics + prior reviews: PLATFORM_PRODUCT_REVIEW_2026-07 §8, HAE_PATH_REVIEW_2026-06-19, ADR-074/061/056/057/060) and captured a live evidence baseline (freshness API, CloudWatch alarm states + metric history, per-partition latest-SK probes, INGEST_HEALTH sentinels, EventBridge rule states, MCP EMF telemetry) so lanes could not re-find shipped work. Five per-source lane agents + three cross-cutting lens agents then filled the 8-dimension rubric, each required to cite `file:line` + literal quote or a live probe command + literal output for every claim. Every finding then faced an independent adversarial verifier instructed to refute it by re-opening the citations and re-running the probes (house FP rate for review agents is ~50%).

**Funnel:** 71 raw findings → 5 merged as cross-lane duplicates → **66 distinct, all 66 confirmed by adversarial verification** (7 adjusted in severity or mechanism) → 0 dropped outright; 4 sub-claims refuted during verification and recorded in §Dropped. The clean sweep against a ~50% house FP expectation reflects the probe-required finding format — every lane had to carry live evidence before the verifier ever saw it — plus independent re-probing of every live number (which reproduced, in several cases to the decimal).

## State of the sources (measured, 2026-07-04)

| source | pipe (sentinel) | data recency | freshness board | notes |
|---|---|---|---|---|
| whoop | healthy (fails=0) | 2026-07-04 | fresh | recovery refresh 9:30 PT; rotating-token race handled |
| eightsleep | healthy | 2026-07-03 | fresh | but re-logins with password grant every run; temp pipeline dead since ~Mar |
| apple_health (HAE) | no sentinel | 2026-07-04 (steps/basal only) | fresh | CGM dark since 05-23, BP 04-10, SoM 04-02, workouts 06-25 — invisible per-datatype |
| habitify | healthy | 2026-07-04 | fresh | past-day records freeze with unresolved "pending" |
| todoist | healthy | 2026-07-02 (by design) | **stale (infra)** | deterministic 14h/day false-stale window; snapshot fields poisoned since ≥05-10 |
| weather | healthy | 2026-07-04 | **absent from board** | not in source_registry at all |
| withings | healthy | 2026-06-26 | behavioral-stale | weigh-in lapse; site labels the 8-day-old weight "today" |
| strava | healthy | 2026-06-25 | behavioral-stale | live reconciliation ALARM = reconciler UTC/local misfire, store is complete |
| garmin | **73 consecutive throttles** | 2026-06-15 | paused | cron still ENABLED 4×/day into the throttle |
| hevy | no sentinel | 2026-06-25 | behavioral-stale | failure invisible end-to-end; liveness alarm watches a metric hevy never emits |
| macrofactor | no sentinel | 2026-06-24 | behavioral-stale | TDEE/deficit chain dead end-to-end; workouts partition dead since 03-07 |
| notion (journal) | no sentinel | 2026-05-25 | MCP-only (monitored:False) | **all enrichment output wiped by re-ingestion clobber**; no raw archive |
| food_delivery | n/a (manual CSV) | 2026-03-28 | behavioral-stale | dormant by design; re-import semantics unsafe for the planned Monarch feed |
| measurements | n/a (manual CSV) | 2026-03-29 | behavioral-stale | **ingestion orphaned — no S3 trigger, no invoker; next upload does nothing** |
| sleep_unified (derived) | n/a | 2026-07-02 | — | merge rules reference nonexistent fields; effectively relabeled Whoop |

**Live alarms at review time:** `slo-source-freshness` (ALARM since 06-27 — driver was pre-#392 misclassification, now fixed; residual = the Todoist false-stale window) · `ingest-reconciliation-strava` (ALARM since 07-03 — reconciler window-edge false positive; store verified complete).

## Executive synthesis

Seven themes across the 66 findings:

**1 · Failure detection is calibrated to the framework 8 — the seven standalone paths are dark.** The ER-01 sentinel, auth breaker, DATA-2 validation, and phase tagging all live in `ingestion_framework.py`; none of the standalone paths carry all of them, and the gap is not theoretical: Hevy failure is invisible on every layer at once (X-1, P1 — errors return a 500 *body* from a successful invocation, and the liveness alarm watches a metric Hevy never emits), notion/dropbox can never leave "unknown" in the health check (X-2), an unknown-format MacroFactor CSV is a silent 200-skip after the file has already been marked processed (B-5), and two S3-triggered ingesters turn out to have **no S3 trigger at all** (measurements B-4; the apple_health XML path D-5). Meanwhile HAE reads "fresh" while ~90% of its datatypes have been dark for weeks to months (D-4).

**2 · Writer and reader field names have drifted into a dozen dead couplings.** Extraction writes what nobody reads, and readers read what nobody writes: the TDEE/deficit chain is dead end-to-end across three generations of field names (B-1), the daily brief's strength section has been silently omitted for ~4 months because it still reads the dead `macrofactor_workouts` partition (B-2), the character sheet's body-fat component reads fields that have never existed (B-3), the unified-sleep staging merge references `*_percentage` fields Whoop never wrote (A-2), the hypothesis engine reads two nonexistent fields (A-5), the CGM TIR branch reads an unprefixed name (D-2), and the journal trajectory tool + chronicle read `enriched_*` variants the enricher never writes (J-3). Nothing enforces the writer→reader contract; each coupling died silently.

**3 · The journal pipeline — the platform's only free-text extraction — has been wiped by its own ingester.** 0 of 50 journal records carry any `enriched_*` field: Notion re-ingestion does a full-item `put_item` that clobbers all 23 enrichment attributes, and the 2-day enrichment window never heals history (J-1, P1). Downstream, every consumer reads None — and two consumers were *additionally* dead from field-name drift (J-3) and unwired data keys (J-4). The journal is simultaneously the least-observed source (no sentinel, `monitored: False`), the least-recoverable (no raw S3 archive — DDB is the only copy of irreplaceable text, X-7), and the input to the owner's requested extraction roadmap (§Roadmap).

**4 · Honesty is recorded but not surfaced.** The engine computes provenance and staleness stamps that no public surface consumes: `tsb_load_basis` says `confidence: hevy_fallback` while TSB is 100% duration-proxy and a coach prompt states "Training fatigue (TSB −87)" unqualified (M-3); `weight_as_of: 2026-06-26` is served while the site labels the same number "today" and "yesterday" (M-5); the sleep page's "night of" header takes its date from a record that is structurally 1–2 nights behind the figures beneath it (A-3); readiness is displayed beside components that are not its inputs (M-4); TSB's form bands assume TSS scale on kJ inputs, so 8 rest days publicly read as maximal fatigue (C-5) while walking — "the primary engine" — contributes zero load (C-6).

**5 · Paused/behavioral semantics are half-adopted.** #392's registry fixed the freshness checker (verified live: StaleSourceCount dropped 4→1 within hours of the deploy), but the same class of hand-rolled source metadata survives in 8+ other files (X-10), two of them already factually wrong (qa_smoke still declares Strava "paused (API 402)"; `DECLARED_PAUSED_SOURCES` suppresses real-outage detection for a live-cron source and feeds a false "NOT live ingest paths" line to the training coach — C-3). Garmin's cron fires 4×/day into a throttle it has lost to for 18 days, against the ADR-074 pause (C-2).

**6 · CRUD beyond append-only is unhandled: edits, deletes, late finalization.** Hevy delete tombstones have no consumer and a start-time edit orphans the old record (C-7); Notion edits older than 2 days never re-sync and deletions never reconcile (E-6); Habitify's last write of a day freezes unresolved "pending" — a 48% day is stored as 100% forever (E-2); Todoist's snapshot fields have been the entire unfiltered task list since ≥May (E-1); CSV re-imports corrupt aggregates (B-6, X-12).

**7 · Both live alarms at review time were instrument misfires, not data problems.** `ingest-reconciliation-strava` is a UTC/local window-edge false positive — the store is complete (C-1); `slo-source-freshness`'s residual driver is the Todoist freshness arithmetic (max healthy age 62h vs a 48h threshold, E-3). The reconciler *did* earn its keep in June catching a real late-sync gap; the casualty here is alarm credibility — the exact failure mode #392 was built to end.

## Stage-0 ledger reconciliation

Open items seeded to every lane (related-to, never re-found): #422 habit causality · #421 vitals depth · #419 coverage floor/mypy · #417 overnight re-stamp · **#415 source-of-truth reconciliation generalization** · #414 autonomic quadrant · **#412 pushed-vs-performed loop** · #400 email dark-mode · #390 coach quality gate · #388 recovery-vs-deficit overlay · #383 phase-filter re-eval · epics #347/#348 · #398 MCP prune (shipped as subscriber-note; prune remains ER-04) · prior findings observability-01 (behavioral/infra split — shipped via #392; residuals evidenced here), data-arch-01/02/04, HAE_PATH_REVIEW P1/P2 set, ADR-074 (Garmin pause), ADR-061 (MacroFactor Tier-1 teardown), ADR-057 (HAE refactor deferral), ADR-103 retire-candidates (hevy-webhook).

Pre-seeded baseline discrepancies adjudicated by the lanes: #1 Garmin cron → **confirmed, C-2**; #2 DECLARED_PAUSED_SOURCES → **confirmed and not cosmetic, C-3**; #3 Todoist stale → **evidenced + root-caused, E-3/X-5**; #4 hevy-webhook → reconciled to ADR-103 (not re-found); #5 journal ADR-062 deviation → **REFUTED — dead scaffolding, calls route through Bedrock (J-2)**; #6 sleep_unified lag → **by-design cadence, but powers a public mislabel (A-3)**; #7 journal_analysis 05-16 → **explained behavioral (J-5)**; #8 macrofactor_workouts → **root-caused: export stream stopped at Hevy go-live; email consumers never repointed (B-2)**; #9 sentinel coverage → **quantified (X-1/X-2)**; #10 HAE monolith → reconciled to ADR-057 (trigger not tripped; defect evidence D-1 reframes the case).

## Findings by lens

Format: `id · title` — `type` · severity P1/P2/P3 · effort S/M/L · confidence. Every finding carries openable evidence (`file:line` under `origin/main@40cbbc4a`, or a live probe) and survived an independent adversarial verifier who re-opened the citations and re-ran the probes. *Verifier:* notes quote what was re-checked. Severities shown are post-verification.

### §1 Sleep & recovery (Lane A: Whoop, Eight Sleep, sleep reconciler)

#### A-1 · Eight Sleep does a full email+password login on every single run — gap · P2 · S · high
The framework persists credentials *before* `fetch_day`, but `authenticate` only re-logins when the token is absent (`eightsleep_lambda.py:647`), so the stale token is written back unchanged; the real re-login happens in `fetch_day`'s 401 handler (`:665-669`) whose fresh token is never persisted — `save_secret()` (`:202`) has zero call sites. 18 password grants/day against an unofficial API is a lockout/abuse-flag risk.
**Evidence:** logs, 7d: 126 × `"Eight Sleep 401 — re-logging in"` (every scheduled run). *Verifier:* re-counted 126 relogins **and** 126 stale-token writebacks; confirmed the writeback precedes `fetch_day`.

#### A-2 · Unified-sleep staging merge is dead — the reconciler reads fields that don't exist (merges M-1) — bug · P2 · M · high
`sleep_reconciler_lambda.py:136-142` reads `rem_percentage`/`slow_wave_sleep_percentage`/`light_sleep_percentage`/`awake_percentage`; the whoop record's real fields are `rem_sleep_hours`/`slow_wave_sleep_hours`/`light_sleep_hours`/`time_awake_hours`. Ditto `toss_and_turns` vs `toss_turn_count`, `hrv_score` vs `hrv_avg` (`:178-182`); the "Apple = clock duration" rule reads sleep fields the apple record has never carried. The stored unified record is the whoop record plus one Eight Sleep score — despite the module header's promised ruleset.
**Evidence:** DDB probes of whoop/eightsleep/apple `DATE#2026-07-02` items; 0/25 unified records since genesis carry any staging field. *Verifier:* re-probed all three source items + the stored unified item; "blast-radius statement is verbatim true."

#### A-3 · Unified sleep is structurally 1–2 nights behind and the public sleep page's "night of" header takes its date from it (merges M-2) — bug · P2 · S · high
`DEFAULT_LOOKBACK=1` with `range(1, 2)` (`sleep_reconciler_lambda.py:253-254`) reconciles *yesterday only* — the reconciler never processes today's already-ingested wake date, and a failed or late day is never re-reconciled (verified: unified `2026-06-12` permanently missing whoop although whoop 06-12 now exists). `evidence.js:55` prefers `uni.night_of` for the "Last night — the evidence" header, captioning fresher figures with a stale night.
**Evidence:** live 07-04 06:47 UTC: `/api/sleep_reconciliation` → `night_of=2026-07-01` while `/api/sleep_detail` → `as_of 2026-07-03`. *Verifier:* ADJUSTED — lag confirmed (understated: two nights behind pre-14:00 UTC); mechanism corrected to lookback-excludes-today (Eight Sleep ingests hourly, so the original "cron ordering" clause was wrong).

#### A-4 · Eight Sleep temperature pipeline is dead — the intervals endpoint 404s on every run; no temp field in ≥4 months — bug · P2 · M · high
~125 lines of fetch (`eightsleep_lambda.py:400-525`, `/v2/users/{id}/intervals`) run hourly and silently swallow a 404. Consumers across MCP (`tools_sleep.py:380-497`), the site bed-temp charts (`site_api_data.py:1708,1889-1987`), and the evidence page's environment section render a permanently-empty state.
**Evidence:** logs, 7d: 135 × `"Intervals endpoint error: HTTP 404"`; DDB spot-checks Mar–Jun: no `bed_temp_*` anywhere; live `/api/sleep_detail`: `bed_temp_f: null`. *Verifier:* re-counted the 404s; "≥3.5 months" is conservative (≥4).

#### A-5 · hypothesis_engine reads two nonexistent fields — total-sleep and bed-temp hypotheses are impossible — bug · P3 · S · high
`hypothesis_engine_lambda.py:293` reads `total_in_bed_time_hrs` (real field: `sleep_duration_hours`); `:344` reads `avg_bed_temp_f` (writer emits `bed_temp_f` — and it's dead anyway per A-4). Rows drop None, so both columns silently never populate.
*Verifier:* verbatim confirmed.

#### A-6 · Whoop 7-day sleep-onset consistency window is diluted by workout sub-records — bug · P3 · S · high
`_compute_sleep_consistency` (`whoop_lambda.py:284-289`) pages 6 items descending over a partition that interleaves `DATE#{d}#WORKOUT#{id}` sub-records; on training-heavy weeks the "7-day" StdDev computes over as few as 2 nights.
*Verifier:* replayed the exact query — 5 of 6 returned items were workout sub-records.

#### A-7 · ingestion_validator field-name drift makes whoop/eightsleep checks no-ops and floods warnings on every workout — gap · P3 · S · high
Validator checks `sleep_score` (`ingestion_validator.py:113,120`) and `heart_rate_avg` (`:226`); stored fields are `sleep_quality_score` and `hr_avg` — those type/range/critical checks can never fire. Every whoop `#WORKOUT#` sub-record trips the `at_least_one_of` warning.
**Evidence:** 1,518 sub-record warnings in 14d (verifier's count). *Verifier:* confirmed + quantified.

#### A-8 · Whoop v2 webhooks exist and are unused — hourly polling re-fetches 3 days × 4 endpoints — opportunity · P3 · L · med
Polling is deliberate and working; webhooks would close the late-sync class and serve #415's reconciliation goal. *Verifier:* confirmed no webhook receiver exists in the repo; deliberate-choice framing correct.

#### A-9 · A failed Whoop secret writeback is logged "non-fatal" but actually strands the rotated refresh token — risk · P3 · S · high
Whoop rotates the single-use refresh token every run; `ingestion_framework.py:549` demotes writeback failure to a warning, but the sole persist path is that writeback — a lost write means next-run 400 → breaker → manual `setup_whoop_auth.py`.
*Verifier:* confirmed the retry loop only rescues the concurrent-rotation race, not a lost writeback.

### §2 Body & nutrition (Lane B: Withings, MacroFactor + Dropbox, food delivery, measurements)

#### B-1 · The MacroFactor TDEE/deficit chain is dead end-to-end — three generations of field names, zero live matches — bug · P2 · M · high
Writer emits `expenditure_kcal` (daily-summary format only — 4 records ever, 04-01..04); readers want `tdee`/`expenditure` (`site_api_observatory.py:269,712`), `tdee_kcal`/`maintenance_calories` (`daily_insight_compute_lambda.py:1099`), `tdee_kcal`/`estimated_tdee_kcal` (`ai_context.py:133`). The observatory silently falls back to a hardcoded formula (age 35 / height 182.88 / else 2400 — `:713-719`); the "MacroFactor TDEE preferred" plateau path has never fired. Bonus booby-trap: `hypothesis_engine_lambda.py:309` writes TDEE into a `weight_lbs` column.
**Evidence:** live `/api/nutrition_overview`: `tdee=None, avg_deficit=None`; DDB: 0/124 records carry any reader-side name. *Verifier:* confirmed all writers/readers; nit — the fallback formula is Mifflin-St Jeor mislabeled Harris-Benedict in its own comment.

#### B-2 · Daily brief + weekly digest strength detail still read the dead macrofactor_workouts partition — Hevy was never plumbed in — gap · P2 · M · high
`daily_brief_lambda.py:379` and `weekly_digest_lambda.py:839-880,1509` read a partition dead since 2026-03-07 (the workout CSV export stopped at Hevy go-live); zero `hevy` references in either file while `monthly_digest_lambda.py:215` shows the working pattern. Strength rows and exercise detail have been silently omitted from both emails for ~4 months.
*Verifier:* ADJUSTED wording — sections silently *omitted*, not rendered-empty (Training still shows Strava rows); substance confirmed.

#### B-3 · Character-sheet body-fat component reads fields that have never existed — the metabolic pillar is structurally blended toward 50 — bug · P3 (from P2) · S · high
`character_engine.py:488-491` reads `body_fat_pct`/`fat_mass_pct`; 0/1198 withings records carry them (or `fat_ratio_pct` — the scale has been weight-only since 2021, as `tools_health.py:777-780` already documents). `body_fat_trajectory` holds 0.25 of the metabolic pillar's weight → coverage caps at 0.75 → a permanent ≤~3-point pull toward 50 on the public character sheet.
*Verifier:* ADJUSTED — core confirmed; `_compute_body_comp_deltas` is dead *code* (early-returns before the query), and blend impact quantified at ≤~3 points → P3.

#### B-4 · Measurements ingestion is orphaned — no S3 trigger, no invoke permission, no invoker anywhere — gap · P2 · S · high
Bucket notifications cover macrofactor/insight-email/food-delivery only; `lambda get-policy` → ResourceNotFound; no MCP tool, script, or rule invokes it; `imports/measurements/` doesn't exist. ADR-044 (status Active) describes an S3 trigger that isn't there. The next tape-measure upload — already 97d overdue per the due-recall surface — will silently do nothing.
*Verifier:* independently reproduced all probes; nuance — the CDK comment "manual/MCP-triggered (no schedule)" shows the state is semi-intentional, which is exactly the ADR-vs-deployed drift.

#### B-5 · Unknown-format MacroFactor CSV is a silent 200-skip after the file is already marked processed — risk · P3 · S · high
`macrofactor_lambda.py:626-628` returns 200 on unknown headers with no archive/metric/error; `dropbox_poll_lambda.py:577-586` has already hash-marked and moved the file — no retry ever. The `MacroFactorFormatDrift` metric has no alarm and detects a different drift class; behavioral classification keeps the resulting staleness off every paging surface. This is the recurrence path of the 22-day 2026-05-03 incident.
*Verifier:* confirmed; refutation hunt failed.

#### B-6 · food_delivery re-import semantics corrupt aggregates on any partial or re-ordered CSV — risk · P3 (P2 when Monarch reuses it) · M · high
Positional `TXN#` keys orphan on re-import; `MONTH#`/`YEAR#`/`STREAK#current` are recomputed from only the uploaded file's rows; `clean_days = 365 − days` assumes full-year coverage (`food_delivery_lambda.py:77,96-201`). Fix belongs inside the planned Monarch-feed story.
*Verifier:* confirmed end-to-end.

#### B-7 · The MacroFactor daily cron is a no-op — 365 dead invocations/year masquerading as coverage — bug · P3 · S · high
`cron(0 16)` fires with no payload; the handler requires `Records`/`bucket`+`key` and returns a clean 400 in ~2ms — which also means the error alarm can never fire on it.
**Evidence:** live 2ms REPORT lines daily. *Verifier:* confirmed + the alarm nuance.

#### B-8 · *(merged into X-12)*

#### B-9 · Withings hourly posture re-fetches every missing day and rotates the OAuth token every run — opportunity · P3 · S · high
During a weigh-in gap: ~144 getmeas + ~18 token rotations/day for a ≤1×/day behavioral event; the per-day loop is a framework artifact (the API accepts a date range). Each rotation is a small chance to strand the token chain (see A-9 for the failure shape).
*Verifier:* confirmed, numbers calibrated (~180 calls/day, capped by lookback=7).

### §3 Training (Lane C: Strava, Garmin, Hevy, training-load math)

#### C-1 · The live ingest-reconciliation-strava ALARM is a reconciler false positive at the local/UTC day boundary — the store is complete — bug · P2 · S · high
The reconciler pulls API activities by UTC instant but fetches stored ones by local-date SK range (`strava_lambda.py:448-451` vs `:394,454`); an evening-PT walk at exactly the window start is inside the API set but outside the SK range. The alarmed activity (`18978915387`) is stored under `DATE#2026-06-18`. The 06-23/24 spikes were a *real* late-sync gap (since fixed) — the reconciler earned its keep; the current alarm is noise. Fix before generalizing per #415.
*Verifier:* mechanism re-derived end-to-end; all post-06-29 warnings are this class.

#### C-2 · Garmin: cron ENABLED 4×/day into a known throttle contradicts the declared ADR-074 pause — posture · P2 · S · high
Registry `paused:True`, alarms removed, freshness excludes it — but the EventBridge rule fires 4×/day; the sentinel shows ~73 consecutive throttle failures since the last success 06-16, and the code's own note says re-hitting "only prolongs the throttle." Coherent options: a documented 1×/day auto-recovery probe, or disable the rule (manual re-auth to revive).
*Verifier:* confirmed (71 fails at probe time — one day's drift); breaker TTL 3h < inter-run gap, so every run really hits the endpoint.

#### C-3 · DECLARED_PAUSED_SOURCES = {"strava"} suppresses real-outage detection for a live-cron source — bug · P2 · S · high
Three runtime consumers: pipeline health check excludes strava from `UnhealthySourceCount` + skips its boot probe (`pipeline_health_check_lambda.py:246-249,353-362`); MCP freshness resolves "paused" for a behavioral lapse; the training coach is told "These are NOT live ingest paths right now" (`ai_expert_analyzer_lambda.py:576-582`) — false since the 06-20 re-enable. Layer module: follow CONVENTIONS §1 to ship.
*Verifier:* confirmed; the defect is the stale declaration, and it would now mask a real Strava outage.

#### C-4 · Movement honesty guard can't distinguish behavioral rest from pipe breakage — the under-training verdict is suppressed exactly when warranted — gap · P3 · M · high/med
`assessable = strava_live` (`intelligence_common.py:1276-1281`); any non-live state withholds the verdict. The disambiguating signal exists unused: a healthy `INGEST_HEALTH#strava` sentinel + no records = behavioral rest.
*Verifier:* confirmed and live-manifest now — 8 rest days with "Do NOT call this under-training" in the coach prompt.

#### C-5 · TSB form bands assume TSS scale but the loads are kilojoules — the component is permanently saturated and reads full rest as maximal fatigue — bug · P2 · M · high
Live: `ctl=471, atl=558.4, tsb=−87.4`. Three consumers apply ±30-scale bands: readiness `clamp(60 + tsb·2)` → pinned 0 (`daily_metrics_compute_lambda.py:384-387`); `character_engine.py:356` `_in_range_score(−10, 25)` → floored 0 on the public sheet; `tools_health.py:355` same calibration. After 8 rest days the platform reads maximally fatigued — the opposite of reality.
*Verifier:* re-derived all three bands from the live record to the decimal.

#### C-6 · Walks contribute zero training load — "Strava kJ authoritative" is nominal; TSB models lifting only — gap · P3 · M · high
Strava populates `kilojoules` only for power-device activities; stored walks carry None, and the `s > 0` gate skips them. Live `tsb_load_basis.strava_days = 0` over 60 days while the site calls walking "the primary engine." Fold into the C-5 rescale.
*Verifier:* confirmed — even the WeightTraining activity carries `kilojoules: None`; site copy verbatim.

#### C-7 · Hevy delete/edit lifecycle is half-built: tombstones written but never consumed; a start-time edit orphans the old record (merges X-4) — bug · P3 · M · high
`DELETE#WORKOUT#{id}` markers (`hevy_backfill_lambda.py:87-104`) have zero readers — the promised "next audit pass" doesn't exist — and the deleted workout's record keeps counting in volume/strength forever; the date-embedded SK (`hevy_common.py:287`) duplicates on cross-date edits; the `MAX_PAGES_PER_RUN=30` cap advances the cursor silently when truncated.
*Verifier:* confirmed all three legs.

#### C-8 · Hevy records are keyed by UTC date, not local — evening lifts will land on the wrong platform day — risk · P3 · S · high (latent)
`hevy_common.py:252` keys by UTC while Strava keys by `start_date_local`; a ≥17:00-PT lift and its same-evening Strava echo would land on different days, corrupting `training_dates` joins and the #412 pushed-vs-performed loop. Currently latent (all observed lifts are morning).
*Verifier:* confirmed.

### §4 Apple Health / HAE (Lane D)

#### D-1 · BP separate-format loop breaks unconditionally on the first metric — bug · P3 (from P2) · S · high (latent)
The closing `break` in the separate-format loop (`health_auto_export_lambda.py:1528-1562`) is indented at loop level, not inside the `if` — the loop always exits after `metrics[0]` (contrast the correct combined loop `:1487-1525`).
*Verifier:* ADJUSTED — control flow confirmed byte-exact, but live raw payloads show BP arrives in the *combined* format, so the broken fallback is dead-in-practice → P3 latent.

#### D-2 · character_engine CGM TIR branch reads a field nothing writes — bug · P3 · S · high
`character_engine.py:495` reads `glucose_time_in_range_pct`; the only written name is `blood_glucose_time_in_range_pct` (`health_auto_export_lambda.py:274`). The avg-glucose fallback fires, so the component degrades rather than nulls.
*Verifier:* confirmed + found the identical dead read in `nutrition_review_lambda.py:369`.

#### D-3 · cgm_source misclassifies UTC-truncated Stelo days as "manual"; glucose aggregates are payload-scoped — data-quality · P3 · S · high
The `n ≥ 20` heuristic (`:266`) is evaluated per UTC-day payload slice. Live artifact: 2026-05-22 has 17 five-minute-interval Stelo readings labeled `manual`. Aggregates recompute from the current payload only (currently consistent — verified DDB==S3 on 3 days — but unguarded).
*Verifier:* artifact reproduced from raw S3.

#### D-4 · Datatype-level darkness is invisible: CGM/BP/SoM/workouts dark for weeks–months while apple_health reads "fresh" — observability · P2 · M · high
Last data: CGM 2026-05-23, BP 04-10, SoM 04-02, workouts 06-20. Any trickle automation keeps the partition alive; field-completeness covers only `steps`/`active_calories` (`freshness_checker_lambda.py:221`); the registry calls the source `behavioral: False` ("passive") though sensor wear and automation upkeep are behaviors.
*Verifier:* confirmed (workouts date corrected to 06-20).

#### D-5 · The XML import path is a latent clobber that also can't do its stated backfill job — and its S3 trigger doesn't exist — design · P3 (from P2) · M · high
`apple_health_lambda.py:403` full-replace `put_item` on the records HAE merge-enriches (would wipe `_rd_*` dedup maps, SoM/TIR fields, monotonic guards; unguarded all-source sums reintroduce the double-count); cutoff = partition-latest−14d makes history recovery impossible. **Verification found the "armed" claim false: no bucket notification exists for `uploads/apple-health/`** — the path is disarmed except via the manual backfill script, which reuses `save_day` verbatim (last run 06-20).
*Verifier:* ADJUSTED — code confirmed, trigger refuted → P3; decide retire vs merge-write (ADR-103 process).

#### D-6 · State of Mind: five live consumers, one day of data ever — posture · P3 · S(decision) · high
`raw/matthew/state_of_mind/` contains exactly one 221-byte file (2026-04-02); ~200 lines of normalization + consumer wiring across character/coach/site no-op for 3 months. Decide: restart the HAE automation or ledger it retire-candidate.
*Verifier:* confirmed.

#### D-7 · The webhook edge is console-managed and ADR-057's WAF rationale is false — IaC-drift · P3 · M · high
API `a76xwxt2wa` exists only as a hardcoded ARN (`ingestion_stack.py:478`); `wafv2 list-web-acls` → `[]` and WAFv2 cannot attach to HTTP APIs at all, while ADR-057 P1.2 still says "WAF protects HAE webhook… load-bearing." Real posture: static never-rotated bearer + 10 rps throttle + access logs (adequate; the doc record is wrong; the `?key=` fallback invites the token into URLs).
*Verifier:* confirmed all six sub-claims.

#### D-8 · The DI-1.6 degraded alert repeat-fires with no cooldown — 36 sends in 72h — alert-fatigue · P3 · S · high
SNS publish on every run while degraded (`freshness_checker_lambda.py:653-667`, no last-sent state). The guard works (it caught the steps collapse); a dozen identical emails a day trains the reader to ignore exactly the signal D-4 needs.
*Verifier:* confirmed and strengthened — the cron is only 1×/day, so ~33 of 36 invocations came from other invokers; fatigue is worse than the schedule implies.

#### D-9 · The units field is ignored for every non-glucose metric — latent bug · P3 · S · high
Only `process_blood_glucose` reads `units` (mmol→mg/dL, `:238-240`); water hardcodes fl-oz→mL (`:746-752`), weight assumes lbs, distance assumes miles; no validation gate on the webhook path (X-3). An HAE unit toggle would silently scale stored values ~30×/2.2×/1.6×.
*Verifier:* confirmed.

### §5 Inputs (Lane E: Habitify, Todoist, Weather, Notion ingestion)

#### E-1 · Todoist overdue/due-today filters silently return the entire active list; active_count is page-capped at 200 — bug · P2 · M · high
The `{"filter": "overdue"}` param sent to `GET /api/v1/tasks` (`todoist_lambda.py:106-126`) has no effect — decisive proof from the raw archive: 38 of 270 "overdue" tasks have `due: null`, and the overdue and due_today ID sets are identical. `get_active_tasks` fetches one page, no cursor (`:100-103`). Every record since ≥05-10 is poisoned; the decision-fatigue rule compares ~470 vs threshold 15 — permanently true (`daily_insight_compute_lambda.py:1395`); `mcp/tools_todoist.py:63-73` has the identical bug. Snapshots are point-in-time — the historical fields are unrecoverable and should be annotated.
*Verifier:* confirmed via raw archive; the alert itself still gates on `habits_breached`.

#### E-2 · Habitify past-day records freeze with unresolved "pending" — a 48% day is stored as 100% forever — bug · P2 · S · high
The last write of UTC-day D is the 23:05 UTC run; `in_progress → "pending"` when `date_str ≥ today_utc` (`habitify_lambda.py:220`) and the record is never rewritten (no `refresh_trailing_days`). Stored 2026-06-20: `completion_pct=1.0` vs `completion_pct_strict=0.4833`, `pending_count=31`. Late-evening checks are also never ingested. Fix: `refresh_trailing_days=1` — the framework hook exists.
*Verifier:* live DDB matches to the digit; the code comment claiming "pending is always 0 for past days" is provably false.

#### E-3 · slo-source-freshness adjudicated: the June red was pre-#392 misclassification (fixed); the residual is Todoist's freshness arithmetic — bug · P2 · S · high
Metric history reproduces the story: red from 06-27 (strava/macrofactor/withings lapses counted as infra under the old hand-rolled behavioral set), **4→1 within hours of the #392 deploy on 07-04**. The residual: Todoist's max *healthy* age is 62h (records dated D, written D+1 14:00 UTC) vs the 48h threshold → request-time surfaces (the public board, MCP) show "stale (infra)" 14h of every day. Classification is right (a record is written daily regardless of user action — 82/93 days have zero completions); the arithmetic isn't. Fix: `stale_hours: 72`.
*Verifier:* confirmed incl. the 4→1 drop; note the scheduled checker samples at 16:45 UTC — outside the window — so steady-state paging comes only from off-schedule runs (see X-5).

#### E-4 · Weather is absent from source_registry entirely — no freshness monitoring on any surface, and no gap backfill — gap · P3 · S · high
Never in the checker (git-history verified), not on the public board, not in MCP; `enable_gap_detection=False` means a >2-day outage leaves permanent holes. Real consumers exist (daily brief, chronicle). One registry entry fixes all three surfaces.
*Verifier:* confirmed.

#### E-5 · Two supplement writers with colliding semantics; validator specs match no writer — risk · P3 · S · high
The habitify bridge full-overwrites `SOURCE#supplements / DATE#{d}` hourly (`habitify_lambda.py:334-345`); MCP `log_supplement` appends to the same key (`tools_lifestyle.py:465-467`) — a same-day manual log is destroyed on the next bridge write (past-day logs survive). The supplements and todoist validator specs type fields no writer produces.
*Verifier:* confirmed with the same-day/past-day nuance.

#### E-6 · Notion ingestion: edits >2 days old never sync, deletions never reconcile, positional #seq orphans, 3-way doc drift, no raw archive — bug/doc · P3 · M · high
Query filters on `Date`/`created_time` only (`notion_lambda.py:231-266`) — `last_edited_time` is never consulted; deletion leaves stale records (and re-numbers siblings); docstring says daily/`life-platform/notion`, CDK comment says 5×/day, reality is hourly/`ingestion-keys`. Raw-archive gap tracked as X-7.
*Verifier:* confirmed all legs.

### §6 Integration architecture (Lens X)

#### X-1 · Hevy ingestion failure is invisible end-to-end — including a dead alarm that fakes coverage — gap+bug · **P1** · S · high
Four layers fail at once: (1) `HevyAPIError` → `return {"statusCode": 500}` from a *successful* invocation (`hevy_backfill_lambda.py:186-200`) — no Errors metric, no DLQ; (2) no INGEST_HEALTH sentinel (standalone path); (3) per-lambda error alarms removed 2026-05-29; (4) `ingest-consecutive-failures-hevy` (`monitoring_stack.py:363-374`) watches `ConsecutiveFailures Source=hevy` — a metric only the framework emits (live list-metrics: exactly the 8 framework sources), with treat-missing NOT_BREACHING, so it can never fire. A dead Hevy API key = silent forever on the primary strength source. Fix: emit the ER-01 sentinel from hevy_backfill (makes the existing alarm real) + raise on error.
*Verifier:* all four legs re-verified; the monitoring file's own comment admits non-emitters "simply never fire."

#### X-2 · pipeline_health_check "covers" notion + dropbox but they can never leave "unknown" — gap · P2 · S · high
Both are listed in `ACTIVE_API_SOURCES` (`pipeline_health_check_lambda.py:69-80`); neither writes a sentinel; a missing sentinel returns non-alerting "unknown" forever — the silently-de-scheduled case is undetectable for both.
*Verifier:* confirmed (live DDB: exactly 8 sentinels).

#### X-3 · The HAE webhook writes CGM/BP/steps unvalidated while the near-dead XML path carries the validation — gap · P2 · M · high
Zero `validate_item` references in the 1,640-line webhook lambda; the partition's schema — including `blood_glucose_avg` *critical* bounds — is enforced only on the manual XML path. The webhook's field-patch `update_item` needs a field-level validator variant, not a call-site fix.
*Verifier:* confirmed.

#### X-4 · *(merged into C-7)*

#### X-5 · Todoist freshness math false-stales request-time surfaces 14h/day — but the paging alarm samples outside the window — bug · P3 (from P2) · S · high
The E-3 arithmetic is real, but the scheduled checker runs at 16:45 UTC where the freshest record is 40.75h old — under threshold — so steady-state paging never fires; the damage is the public board + MCP false-"stale (infra)" and off-schedule checker runs. Also: CLAUDE.md still says "Todoist at 2x daily" (actual: 1×, TD-12).
*Verifier:* ADJUSTED as stated — the "structurally pages daily" claim refuted, surfaces claim stands.

#### X-6 · Phase tagging is framework+hevy only — six standalone writers depend on the manual sweep — risk · P2 · S · high
No `phase` writes in HAE/notion/macrofactor/apple_health/food_delivery/measurements; `phase_filter` passes `attribute_not_exists(#phase)`, so an untagged backfill surfaces pre-genesis data as current until the next `restart_phase_tag.py --apply`. The framework docstring names this exact debt.
*Verifier:* confirmed (live notion items carry `phase` only because the 06-08 reset sweep stamped them).

#### X-7 · Notion journal has no raw archive — DDB is the only copy of irreplaceable text — risk · P2 · S · high
No S3 write in `notion_lambda.py`; no `raw/notion/` prefix exists. The journal is simultaneously the least-observed source (`monitored: False`, no sentinel) and the least-recoverable — and J-1 shows even the DDB copy gets clobbered. One `put_object` in `write_entries` fixes it.
*Verifier:* confirmed.

#### X-8 · Default UpdateSecret on every ingestion role over-privileges the shared ingestion-keys bundle — risk · P2 · M · high
`role_policies.py:134-142` grants `GetSecretValue` **and** `UpdateSecret` by default; four lambdas (todoist, notion, dropbox, HAE) share the `ingestion-keys` bundle, so each read-only-token consumer holds write access to four sources' credentials at once.
*Verifier:* ADJUSTED — the bundling itself is a documented COST-B decision; the finding is narrowed to the default-UpdateSecret over-privilege (make it opt-in via the existing `extra_secret_actions`; consider splitting the internet-facing HAE bearer out).

#### X-9 · The raw S3 zone is three-generation fractured — replay requires per-source archaeology — risk · P3 · M · high
Legacy `raw/{source}/`, live `raw/matthew/{source}/`, and a `raw/matthew/matthew/(matthew/)` migration artifact coexist; todoist/weather lack the user segment; hevy is flat UUID-keyed; the CLAUDE.md convention matches nothing exactly. Don't mass-move (delete-protected prefixes); make `source_registry` describe each source's raw layout and fix the doc claim.
*Verifier:* confirmed via live S3 probes.

#### X-10 · Registry adoption stopped at the freshness surfaces — 8+ hand-rolled source enumerations remain, two already factually wrong — opportunity · P2 · M · high
The list: `pipeline_health_check` (3 dicts), `source_state.DECLARED_PAUSED_SOURCES` (→C-3), `data_reconciliation`, `data_export.ALL_SOURCES` (still ships dead `macrofactor_workouts`), `qa_smoke` (still declares Strava "paused (API 402)"), `mcp/config.SOURCES`, `site/data/data_sources.json` (self-labeled "single source of truth," missing hevy, March-era copy), `ingestion_validator._SCHEMAS`, the `monitoring_stack.py:363` alarm tuple. Extend the registry's facets and derive.
*Verifier:* spot-checks all reproduced.

#### X-11 · One retry policy, four implementations; one non-idempotent retry — opportunity · P3 · S · high
Inline duplicates in whoop/todoist; bare `urlopen` in weather and `hevy_common.hevy_get` (which feeds X-1's dark failure path); `hevy_write_client` retries POST/PUT routine mutations (duplicate-creation window on ambiguous 5xx).
*Verifier:* confirmed.

#### X-12 · Manual-CSV paths have zero framework benefits and two self-inflicted correctness warts (merges B-8) — risk · P3 · S · high
food_delivery rewrites lifetime streak stats from only the uploaded file's rows; measurements assigns `session_number = COUNT+1` (non-monotonic on re-import) and parses only `rows[0]` of a multi-session CSV.
*Verifier:* confirmed.

#### X-13 · The monitoring-stack comment overstates IngestAuthHealthy coverage — gap · P3 · S · high
The comment claims coverage of "notion + the SIMP-2 framework sources," but the framework's inlined breaker never emits `LifePlatform/OAuth`; only `auth_breaker.py` (notion/dropbox) and Garmin's custom path do.
*Verifier:* confirmed via live namespace dimensions.

### §7 Cross-source merge honesty (Lens M; M-1/M-2 merged into A-2/A-3)

#### M-3 · TSB is 100% proxy-derived and its stored provenance has zero consumers — honesty · P2 · M · high
Live `tsb_load_basis = {strava_days: 0, hevy_fallback_days: 9, confidence: "hevy_fallback"}` — the "authoritative" Strava-kJ leg never fires (kJ is NULL without a power meter) and the 25 kJ/min proxy runs ~2× a real ride's energy scale. Grep: nothing reads `tsb_load_basis`; meanwhile the coach prompt injects "Training fatigue (TSB −87)" (`ai_context.py:668-673`) and MCP labels the number `live_banister_model` (`tools_health.py:366`). Surface `confidence` wherever TSB renders.
*Verifier:* confirmed — live record, no-kJ probe, zero-consumer grep all reproduced.

#### M-4 · The cockpit pairs the readiness score with components that are not its inputs — honesty · P3 · S · high
`_latest_readiness` (`site_api_vitals.py:1456-1479`) returns `readiness_score` (inputs: recovery/sleep/hrv_trend/tsb) beside `component_scores` (the day-grade set: movement, habits_mvp) — live: score 60 shown with components 64/88/0/0 that don't produce it. Store and serve `readiness_components`.
*Verifier:* confirmed.

#### M-5 · The site labels an 8-day-old weight "today" and its day-delta "yesterday"; the API's staleness stamps have no v4 consumer — honesty · P2 · S · high
`/api/vitals` honestly serves `weight_as_of: 2026-06-26`; `evidence.js:1735` labels it "today" on /data/results and `:158-161` labels the 06-25→06-26 pair "yesterday" on /data/physical; `page_freshness` is consumed only by the legacy nav; `/api/last_sync` omits withings. Date-condition the labels.
*Verifier:* confirmed live.

#### M-6 · The Apple weight fallback inspects only the single latest apple_health item — engages same-day only — bug · P3 · S · high (latent)
`site_api_vitals.py:116-121`: the latest item is a steps record without `weight_lbs`, so 1,184 historical apple weight records are invisible; the character sheet runs a third, different resolution. A shared `latest_weight()` layer helper is the fix.
*Verifier:* confirmed.

#### M-7 · Device agreement has been structurally null since ~06-16 with no "why"; the MCP registry advertises it with wrong weights — doc-drift · P3 · S · high
`device_agreement = None` whenever Garmin is absent (7-day window; Garmin dead since 06-15) with no reason field; `registry.py:1057-1063` claims weights 35%/10% vs code's 40%/5%. Return `{status: "unavailable", reason: "garmin paused (ADR-074)"}` and sync the description.
*Verifier:* confirmed.

#### M-8 · The honesty gates don't cover merged/derived values — TSB reaches coach prompts ungated (merges J-7) — gap · P3 · M · high
`grounding_guard.py` scope is RHR/recovery/HRV only (documented-deliberate for weight); `coherence_invariants.py` adds only `latest_weight`. Nothing gates TSB, unified-sleep values, or journal-attributed claims (the chronicle handles journal text by prompt-level suppression, not verification). Add `tsb` to the sentinel's facts minimum; fold merge-confidence into the grounded-facts block.
*Verifier:* confirmed.

#### M-9 · /api/sleep_detail splices a different night's Whoop recovery into "last night" — honesty · P3 · S · high
When the latest Eight Sleep night lacks matching Whoop recovery, `site_api_data.py:1876-1884` substitutes the most recent night that has it; the UI renders night-A hours + night-B recovery under one dated header with no per-field date.
*Verifier:* confirmed incl. live payload.

### §8 Journal / free-text extraction (Lens J)

#### J-1 · The entire journal enrichment layer's output no longer exists in the store — every consumer silently degrades — data-loss · **P1** · S(backfill)+M(fix) · high
0 of 50 notion journal items carry `enriched_at` (or any of the 23 enrichment fields — including a 4,225-char entry). Mechanism: `notion_lambda.write_entries` does full-item `put_item` (`:548,575`), erasing the enricher's `update_item` output on any re-ingestion; the enrichment window is 2 days (`journal_enrichment_lambda.py:472-475`) so clobbered history never self-heals (14 consecutive runs found 0 entries). Blast radius: ~20 consumer sites read None — the hypothesis engine's journal columns are structurally empty, so journal↔wearable correlation is currently impossible. Fix: one `{"full_sync": true, "force": true}` backfill invoke (~50 entries × Haiku ≈ cents) + make notion writes enrichment-preserving + edit-aware re-enrichment (`enriched_at ≥ notion_last_edited`).
*Verifier:* re-probed 0/50; "structural data-loss confirmed regardless of whether the historical wipe was clobber or reset."

#### J-2 · The "direct api.anthropic.com" scaffolding is dead code, not a live ADR-062 deviation — and the analyzer still does a real, pointless secret fetch — dead-code · P3 · S · high
`call_anthropic_raw` extracts the request body and forwards to `bedrock_client.invoke()` (`retry_utils.py:189-216`) — the Anthropic URL is never dialed (this **refutes** the review baseline's pre-seeded discrepancy #5). But `journal_analyzer_lambda._get_api_key` (`:48-60,88`) still fetches `life-platform/ai-keys` for real; retiring that secret would fail the nightly run for nothing. Delete the urllib scaffolding + the live fetch.
*Verifier:* confirmed both halves.

#### J-3 · Three consumers read enriched field names the producer never writes — bug · P2 · S · high
`tools_journal.py:660-666` reads `enriched_mood_score`/`energy_score`/`stress_score`/`ownership_score` — the sentiment-trajectory tool can never produce output even with fully-enriched data; `wednesday_chronicle_lambda.py:589-590` reads `enriched_avoidance_flag` (singular) + `enriched_ownership_level`. J-1 masks this today.
*Verifier:* confirmed; raw-field fallbacks also absent, so the skip is total.

#### J-4 · The mind coach's journal signals are double-dead: unpopulated data key AND wrong schema — bug · P2 · S · high
`ai_context._build_mind_data` (`:975-987`) reads `data["journal_analysis"]` — no caller populates that key (grep: zero assignments) — and expects `enriched_*` fields while the analyzer cache carries `dominant_theme`/`sentiment_score`. Dr. Reeves has never seen a journal-derived signal through this path. Point it at `journal_entries` (already fetched by the brief).
*Verifier:* confirmed both legs.

#### J-5 · Baseline discrepancy #7 explained: the analyzer's 20-word floor vs the enricher's 20-char floor — info · — · — · high
The 2026-05-25 entries are 40 chars (~7 words): below the analyzer's floor, above the enricher's. The analyzer itself is healthy (clean post-reset rebuild 06-09). Two "too short" definitions for one corpus; align deliberately.
*Verifier:* confirmed.

#### J-6 · ~5 of 23 enriched fields have no meaningful consumer; the second Haiku pass and its prompt caching are both waste — dead-weight · P3 · S · high
`enriched_emotional_depth` has zero consumers; `enriched_defense_context` one prompt echo; the defense pass is a second Bedrock call where one merged schema would do; both `cache_control` blocks sit on ~151/~193-token system prompts — far below the ~2048-token cache floor, so caching is a no-op. Fold into the Phase-1 schema rework.
*Verifier:* confirmed with token measurements.

#### J-7 · *(merged into M-8)*

#### J-8 · /api/journal_analysis will publicly serve per-day journal one-liners the moment journaling resumes — privacy-forward · P2 · S · high
`handle_journal_analysis` (`site_api_observatory.py:1760-1771`) returns Haiku's `one_line_summary` per day; publicly routed (`site_api_lambda.py:344`, live 200); the analyzer writes no `phase` attribute so records pass the phase filter. Empty today only because the cache predates genesis. Decide deliberately: drop the field from the public payload or ADR the exposure.
*Verifier:* confirmed end-to-end.

## Per-source scorecards

Compact verdict per dimension: ✓ sound · ○ acceptable · ✗ finding(s). Full facts live in the findings above.

| source | 1 API/auth | 2 storage | 3 timing | 4 CRUD | 5 practices | 6 calcs | 7 site honesty | 8 posture verdict |
|---|---|---|---|---|---|---|---|---|
| whoop | ✓ | ✓ | ✓ | ✓ | ○ (A-8) | ✗ A-5/A-6 | ✓ | **KEEP** — load-bearing |
| eightsleep | ✗ A-1 | ✓ | ○ | ✓ | ○ | ✗ A-4 | ○ | **KEEP + fix A-1/A-4** |
| sleep_unified | ✓ | ✓ | ✗ A-3 | ○ | ✗ A-2 | ✗ A-2 | ✗ A-3/M-9 | **FIX-OR-RETIRE** — zero compute consumers; not in ADR-103 |
| withings | ✓ | ✓ | ✗ B-9 | ✓ | ✓ | ✗ B-3 | ✓ | **KEEP** — weight anchor; trim dead composition code |
| macrofactor (+dropbox) | ✓ | ✗ B-1 | ✗ B-7 | ✗ B-5 | ✗ B-2 | ✗ B-1 | ✓ | **KEEP + fix TDEE plumbing**; workouts partition = archive-only |
| food_delivery | ○ | ○ | ○ | ✗ B-6 | ✓ | ✗ B-6 | ✓ | **FIX-THEN-REPLACE** with Monarch feed |
| measurements | ✗ B-4 | ○ | ○ | ✗ X-12 | ✗ B-4 | ○ | ○ | **KEEP + re-arm** — currently theater (no trigger) |
| strava | ✓ | ✓ | ✓ | ○ | ✗ C-3 | ✗ C-5/C-6 | ✓ | **KEEP** — the reconciliation exemplar; fix C-1 before #415 |
| garmin | ○ (code) | ✓ | ✗ C-2 | ✓ | ✗ C-2 | ✓ | ✓ | **KEEP PAUSED, make coherent** — 1×/day probe or disabled rule |
| hevy (backfill) | ✓ | ✓ | ✓ | ✗ C-7/C-8 | ✗ X-1 | ✗ C-5/C-6 | ✓ | **KEEP**; webhook lambda = retire (ADR-103, reconciled) |
| apple_health / HAE | ○ D-7 | ○ | ✗ D-4 | ○ D-3 | ✗ X-3/D-4 | ✗ D-2/D-9 | ○ | **KEEP + per-datatype liveness**; XML path retire-or-merge-write (D-5) |
| habitify | ✓ | ✓ | ✗ E-2 | ✗ E-2/E-5 | ✓ | ✗ E-2 | ○ (ADR-104) | **KEEP + refresh_trailing_days=1** |
| todoist | ✓ | ✗ E-5 | ○ | ✓ | ✗ E-3 | ✗ E-1 | ✗ E-3 | **KEEP + fix E-1** — else the snapshot half is noise |
| weather | ✓ | ✓ | ✓ | ○ E-4 | ✗ E-4 | ✓ | ○ | **KEEP** at 2×/day; add registry entry |
| notion (journal) | ○ E-6 | ✗ X-7 | ○ | ✗ E-6/J-1 | ✗ X-7 | — | ✓ | **KEEP** — highest-leverage fix cluster in the review (J-1/X-7/E-6) |

## Value-per-source posture (extends ADR-103's frame)

Per ADR-103's standing rule, each source names its frame. Proposal: add a `posture` field to `site/data/data_sources.json` when it's regenerated from the registry (X-10).

- **Load-bearing:** whoop (recovery/sleep spine), withings (weight anchor), apple_health/HAE (steps + the only CGM/BP path), habitify (habit/vice engine), hevy (strength SOT), macrofactor (nutrition SOT), strava (aerobic SOT + reconciliation exemplar), notion journal (mind pillar input; currently under-realized — see roadmap)
- **Portfolio (keep, cheap):** eightsleep (env half currently dead — A-4 decides its weight), todoist (fix E-1 or it's noise), weather (context covariate)
- **Paused (coherence fixes due):** garmin (C-2)
- **Retire-candidates:** hevy-webhook FunctionURL (already ADR-103), apple_health XML path (D-5 — disarmed anyway), `macrofactor_workouts` reader wiring (B-2 repoints, partition stays as archive), State of Mind machinery **decision** (D-6: restart the automation or ledger it), sleep_reconciler **decision** (A-2/A-3: fix the field map + lookback, or retire — zero compute consumers today)

## Journal free-text extraction — roadmap (owner-requested, forward-looking)

**Design bar (given ~50 entries, none since 05-25): one entry must produce durable, connected value; every aggregate degrades to an honest "insufficient n," never a padded trend.** Full details in the findings JSON appendix; phases below are the proposal.

**Phase 1 — Repair + Extraction v2 (S-M, do first):** (1) backfill enrichment (`{"full_sync": true, "force": true}` — cents on Haiku, restores J-1's 50 entries); (2) clobber-proof `write_entries` (preserve `enriched_*` on re-ingestion) + edit-aware re-enrichment (`enriched_at ≥ notion_last_edited`; add `last_edited_time` to the Notion query so old edits sync at all — E-6); (3) merge the defense pass into pass 1 and extend the schema with `entities` `[{name, type, sentiment, role}]`, `behaviors` `[{behavior, valence, time_of_day}]`, and `causal_hints` `[{cause, effect, confidence: stated|implied, quote}]` — **the verbatim `quote` field is the load-bearing choice: it's what makes grounding possible later**; drop the dead fields (J-6); (4) fix the dead consumers (J-3 names, J-4 wiring) so extraction actually reaches the coaches; (5) delete the Anthropic scaffolding + the analyzer's live secret fetch (J-2); archive raw pages to S3 (X-7). Files: `journal_enrichment_lambda.py`, `notion_lambda.py`, `tools_journal.py`, `wednesday_chronicle_lambda.py`, `ai_context.py`. No layer change, no GSI.

**Phase 2 — Cross-entry aggregation (M):** rebuild `journal_analyzer_lambda` from per-day re-classification (it duplicates pass 1 at lower fidelity) into a **deterministic aggregator over enriched fields** (AI only for candidate phrasing): an entity registry (`ENTITY_REGISTRY#current` — per entity: first/last seen, mentions, sentiment trend, quotes), a behavior registry joined against habitify names (the free-text side of #422), and **causal-hypothesis candidates** (`HYPO_CANDIDATE#{slug}`) that the hypothesis engine reads — a hint whose cause/effect maps to tracked metrics becomes a *testable* hypothesis against wearable rows, with the journal quote as provenance; unmappable ones surface as "needs instrumentation." Resolve J-8 here (drop `one_line_summary` from the public payload or ADR it). Keep `/data/mind` aggregate-only.

**Phase 3 — The journal as a first-class N=1 instrument (L, gated on Phase 2 producing ≥1 real candidate — i.e., on journaling resuming):** (1) extraction→experiment loop: a mapped candidate auto-drafts a pre-registered hypothesis (metric, direction, window, min-n) surfaced in the daily brief as "your journal suggests X→Y; approve to track" — human-in-loop, never auto-activates; (2) retrieval grounding: when a coach references the journal, inject the stored verbatim quotes and extend the SS-10 gate so any journal-attributed claim must fuzzy-match a supplied quote — converts the chronicle's suppression policy into verified provenance for **private surfaces** (public surfaces keep suppression); (3) reading/Mind idea-graph tie-in (deterministic tag-intersection first; no real graph below ~25 entities); (4) **explicitly reject embeddings/vector search** in the ADR — brute-force scan over enriched fields is sufficient for years at this corpus size. All phases: Haiku via `bedrock_client` (budget tiers apply); journal text and quotes never on `/api/*`.

## Dropped as false positives

No finding was dropped outright, but four claims were refuted or materially corrected during verification — recorded here as proof the filter ran:

1. **Baseline pre-seed #5 refuted (J-2):** "journal enrichment calls api.anthropic.com directly — ADR-062 deviation." False as a live deviation: `retry_utils.call_anthropic_raw` forwards every call to `bedrock_client.invoke()`; the Anthropic URL is never dialed. Survives only as dead scaffolding + one pointless live secret fetch.
2. **D-5 "the XML clobber trigger is live" refuted:** no S3 bucket notification exists for `uploads/apple-health/` — the path is disarmed except via the manual backfill script. Severity P2→P3.
3. **X-5 "Todoist freshness structurally pages daily" refuted:** the scheduled checker samples at 16:45 UTC, outside the 00:00–14:00 stale window — steady-state paging never fires. The request-time false-"stale" on the public board and MCP stands. Severity P2→P3.
4. **D-1 live impact refuted:** the BP `break` bug is byte-exact real, but live payloads arrive in the *combined* format — the broken separate-format fallback is dead-in-practice. Severity P2→P3.
5. **A-3 mechanism corrected:** the unified-sleep lag is caused by `DEFAULT_LOOKBACK=1` excluding today, not by cron ordering (Eight Sleep ingests hourly). Lag itself confirmed — and understated (2 nights, not 1, for most of each day).

## What happens next (Session 2, gated)

Findings are scored per ADR-099 — hard gates first (185 test, build cap, privacy absolutes, honesty moat), then `Score = (Impact × Confidence) / Effort` with Impact = 0.35·returnability + 0.25·credibility-moat + 0.20·monetization-readiness + 0.20·durability; terciles → Now/Next/Later. Issue filing (epics + stories, labels `type:` / `area:data`, privacy-passed bodies, manifest as idempotency record) awaits Matthew's read + green-light. Machine-readable appendix: `DATA_SOURCE_HEALTH_REVIEW_2026-07_findings.json`.
