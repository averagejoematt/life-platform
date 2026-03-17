# Life Platform — Project Plan

> Living document. For completed work and version history, see CHANGELOG.md / CHANGELOG_ARCHIVE.md.
> Last update: 2026-03-16 (v3.7.61 — Full Board Summit gap-fill: 8 missing items added (BS-T2-7, BS-T3-5, BS-T3-6, WEB-CE, WEB-NET, WEB-WCT, EMAIL-P2/P3), IC-27–31 defined explicitly. Sprint plan (4 sprints + SIMP-1 mini) added. Board sprint review aligned. See docs/SPRINT_PLAN.md.)

---

## Active Priorities

### P0 — Completed (v3.7.15)
All P0 items from Architecture Review #8 are resolved:
- ✅ Webhook auth restored (CDK deploy LifePlatformIngestion)
- ✅ Secret state reconciled to 10 actual secrets
- ✅ IAM/secrets CI lint wired (`test_iam_secrets_consistency.py`)
- ✅ ARCHITECTURE.md secrets table updated to match reality
- ✅ CV_THRESHOLDS stale comments fixed
- ✅ SCHEMA.md added to `sync_doc_metadata.py`

---

## Backlog — Prioritized

Items are grouped by priority tier. Within each tier, items are ordered by ROI (impact ÷ effort).

### Tier 1 — Do Next (30 days)

| ID | Item | Source | Effort | Impact | Status |
|----|------|--------|--------|--------|--------|
| R13-F05 | **Remove OAuth fail-open default** — `_get_bearer_token()` returns `None` (accept-all) when API key is missing. Change to reject-all. | R13 Finding-05 | S (30min) | MEDIUM — closes false security boundary | ✅ Done (v3.7.35) |
| R13-F06 | **n-gate on-demand correlation tool** — `get_cross_source_correlation` has no minimum sample size. Add n≥14 minimum, warn at n<30, include p-value/CI in response. | R13 Finding-06, R13 Top-10 #2 | S (2h) | MEDIUM — prevents spurious correlations from being presented as insights | ✅ Done (v3.7.36) |
| R13-F09 | **Medical disclaimer in MCP health tool responses** — Add `_disclaimer` field to all health-assessment tools (risk_profile, cgm dashboard, BP dashboard, HR recovery). | R13 Finding-09, R13 Top-10 #6 | S (1h) | MEDIUM — liability protection for any sharing/productization | ✅ Done (v3.7.36) |
| R13-F04 | **CI test: secret name references vs live secrets** — grep all Lambda source for secret names, validate referenced secrets exist. Prevents Todoist-style 2-day outage. | R13 Finding-04, R13 Top-10 #4 | S (1h) | MEDIUM — prevents class of deployment bug permanently | ✅ Done (v3.7.35) |
| R13-F12 | **Rate limiting on MCP write tools** — `create_todoist_task`, `log_supplement`, `write_platform_memory`, `delete_platform_memory`, `delete_todoist_task` have no per-session rate limiting. | R13 Finding-12 | S (1h) | MEDIUM — security hardening for write path | ✅ Done (v3.7.35) |
| R13-F08-dur | **Duration alarms on Daily Brief + MCP Lambdas** — timeout-without-error is currently undetected. Add p95 duration alarms. | R13 §Observability, R13 Top-10 #8 | S (1h) | MEDIUM — catches silent degradation | ✅ Done (v3.7.36) |
| R8-QS1 | **SIMP-1: MCP tool consolidation** — Phase 1 complete (116→86 tools via 13 dispatchers). Phase 2 (EMF-driven cuts to ≤80) gated on 30-day data. | R8 Finding-5, R8 Top-10 #5 | L | HIGH | ⏳ Phase 1 done (v3.7.17–19). Phase 2 ≤80 gated ~2026-04-13 |
| R8-QS2 | **Add integration test to qa-smoke Lambda** — write test record to `SOURCE#test`, invoke 2-3 MCP tools + validate response schema, verify cache ≥10 items, verify freshness of ≥1 source. | R8 Finding-4, R8 Top-10 #3 | M (2-3h) | HIGH — catches 80% of deployment-induced failures | ✅ Done (v3.7.16) |
| R8-QS3 | **Update COST_TRACKER model routing entry** — decision log says "Haiku ~$0.10/mo" but `ai_calls.py` uses Sonnet for coaching calls (~$3/mo actual). Entry is stale, not a cost problem. | R8 §8 stale docs | S (10min) | LOW — documentation hygiene | ✅ Done (v3.7.17) |
| R8-QS4 | **Archive completed deploy scripts** — reduce 120+ scripts in `deploy/` to active-only. Run `bash deploy/archive_onetime_scripts.sh`. | R8 Finding-3, R8-6 (pending from v3.7.14) | S (15min) | LOW — DevEx / cognitive load | ✅ Done (v3.7.16) |
| TB7-1 | **GitHub `production` Environment gate** — verify exists in repo settings for CI/CD manual approval. | TB7 (pre-R8) | S (5min) | LOW — CI/CD hygiene | ✅ Done |
| TB7-2 | **Update `BRITTANY_EMAIL` env var** to real address for accountability email. | TB7 (pre-R8) | S (5min) | LOW — feature enablement | ✅ Done |

### Tier 2 — Near-Term (60 days)

| ID | Item | Source | Effort | Impact | Status |
|----|------|--------|--------|--------|--------|
| R13-F01 | **GitHub Actions CI pipeline** — pytest + cdk synth + cdk diff on push to main. Manual approval gate before cdk deploy. | R13 Finding-01, R13 Top-10 #1 | M (4h) | HIGH | ✅ Done (v3.7.45) — ci-cd.yml confirmed 7-job pipeline. `deploy/setup_github_oidc.sh` added to activate OIDC role (run once). |
| R13-F02 | **Integration tests for critical path** — I1-I14 exist in `tests/test_integration_aws.py`. I1/I2/I4-I9 now wired into CI post-deploy-checks job. I3/I10-I14 manual-only (invoke Lambdas). | R13 Finding-02, R13 Top-10 #10 | M (5h) | HIGH | ✅ Done (v3.7.45) — I4/I6/I7/I8/I9 added to post-deploy-checks; I1/I2/I5 were already wired. |
| R13-F08 | **CI test for layer version consistency** — offline pytest (LV1-LV5) + live AWS check in Plan job. | R13 Finding-08 | S (1h) | MEDIUM | ✅ Done (v3.7.38) — `tests/test_layer_version_consistency.py` (LV1-LV5) wired in test job; live AWS layer version check in Plan job. |
| R13-F15 | **FDR correction in weekly correlation compute** — Benjamini-Hochberg applied. | R13 Finding-15 | S (2h) | MEDIUM | ✅ Done (v3.7.37) — `apply_benjamini_hochberg()` in `weekly_correlation_compute_lambda.py`. |
| R13-F10 | **Consolidate d2f() into shared layer** | R13 Finding-10 | S (30min) | LOW | ✅ Done (v3.7.43) — `weekly_correlation_compute_lambda.py` switched to `from digest_utils import d2f`. |
| R13-F07 | **Quarterly PITR restore drill** — first drill executed. Next ~2026-06-15. | R13 Finding-07 | S (1h) | MEDIUM | ✅ Done (v3.7.43) — drill ran 2026-03-15: 270s restore, 6/6 partitions verified. Next drill ~2026-06-15. |
| R8-ST1 | **Google Calendar integration** — Retired (ADR-030, v3.7.46). All 7 data paths blocked by Smartsheet IT or macOS restrictions. Lambda removed from CDK (v3.7.47). | Pre-R8, TB7-18 | — | — | ❌ Retired (ADR-030) |
| R8-ST2 | **Document and test DynamoDB restore procedure** — write runbook section, execute PITR restore to test table, verify data integrity across partitions. | R8 Finding-6, R8 Top-10 #6 | S (1h) | MEDIUM — critical insurance for core data asset | ✅ Done (v3.7.17) — runbook written. Drill (actual restore) tracked as R13-F07. |
| R8-ST3 | **Create "maintenance mode" Lambda profile** — config to disable non-essential Lambdas during vacation/absence. | R8 §6 R-5, R8 Top-10 #9 | S (30min) | MEDIUM — operational resilience during absence | ✅ Done (v3.7.17) — `deploy/maintenance_mode.sh enable\|disable\|status` |
| R8-ST4 | **Add OAuth token health monitoring** — alert if any OAuth refresh token hasn't been updated in >60 days. | R8 §6 R-2, R8 Top-10 | M (2h) | MEDIUM — prevents multi-source auth cascade failure | ✅ Done (v3.7.17) — freshness_checker extended, OAuthSecretDescribe IAM added |
| R8-ST5 | **Pre-compute composite scores** — Implemented v3.7.20, then superseded by ADR-025 (v3.7.25). All fields consolidated into `computed_metrics` partition. `write_composite_scores()` call removed from lambda_handler; dead code removal tracked as CLEANUP-1. | Pre-R8, SIMP-1 prereq | — | — | ✅ Done + deprecated (ADR-025) |
| R8-ST6 | **CDK diff IAM change → blocking gate** — make CI pipeline block (not just warn) when CDK diff detects IAM/policy changes. | R8 §10 CD-4 | S (30min) | MEDIUM — prevents future IAM drift | ✅ Done (v3.7.17) — ci-cd.yml warning → error + exit 1 |
| R8-ST7 | **Tighten HAE webhook S3 write scope** — tightened from `raw/matthew/*` to 5 explicit paths. | R8 §5 IAM | S (15min) | LOW — least-privilege refinement | ✅ Done (v3.7.17) — role_policies.py updated, CDK deploy pending |

### Tier 3 — Strategic (90 days)

| ID | Item | Source | Effort | Impact | Status |
|----|------|--------|--------|--------|--------|
| R13-F14 | **MCP endpoint canary** — synthetic probe of remote MCP Function URL every 15 min. Existing canary tests DDB+S3+MCP but may not exercise the remote Function URL path. | R13 Finding-14 | S (2h) | MEDIUM — catches remote MCP downtime | ✅ Done (v3.7.40) |
| R13-F03 | **MCP monolith split assessment** — if MCP usage increases 5-10x, split into read-light (cached, metadata) and read-heavy (correlation, longitudinal, search) Lambdas. | R13 Finding-03 | L | MEDIUM — scaling readiness | Not needed now. Revisit at productization or >100 MCP calls/day. |
| R13-XR | **X-Ray tracing on MCP Lambda** — enables per-DDB-query latency diagnosis. Currently diagnosis requires log parsing. | R13 §Observability | S (2h) | LOW — operational maturity | ✅ Done (v3.7.40) |
| R8-LT1 | **Architecture Review #17** — post-sprint-4 validation. Targeting ~2026-06-08 (after Sprint 4 complete). | Board Summit | L (1 session) | HIGH — validates sprint work | Gated on Sprint 4 completion |
| R8-LT2 | **Evaluate IC-4/IC-5 readiness** — failure pattern recognition + momentum/early warning. Data maturity gate ~6-8 weeks behavioral data. | INTELLIGENCE_LAYER.md | S (assessment) | MEDIUM — next IC features | Gated on data (~May 2026) |
| R8-LT3 | **Unit tests for business logic** — pytest unit tests for scoring_engine, character_engine, day grade computation. | R8 §9 testability | M-L | MEDIUM | ✅ Done (v3.7.20) — 74/74 tests in `tests/test_business_logic.py` |
| R8-LT4 | **DynamoDB export to S3 for analytics isolation** — separate analytical workload from transactional. Export to Parquet via DDB export, query with Athena. | R8 §17 roadmap | L | LOW — premature until data volume warrants | Not started |
| R8-LT5 | **Review SLO targets** — evaluate whether 99%/99.5% targets are appropriate based on 90 days of operational data. | R8 §17 roadmap | S (assessment) | LOW — operational maturity | Gated on 90 days data |
| R8-LT6 | **Lambda@Edge auth — verify CDK management** | R8 Finding-6, R8 §4 S | S (15min) | LOW | ✅ Done (v3.7.19) — confirmed manually managed outside CDK, documented in ARCHITECTURE.md |
| R8-LT7 | **Add disclaimer to `get_hypotheses` MCP tool** — unconfirmed hypotheses require 3 observations before promotion. | R8 §12 AI-2 | S (5min) | LOW — analytical transparency | ✅ Done (v3.7.17) — registry description updated |
| Risk-7 | **Compute pipeline timing: staleness observability** — Daily Brief emits `ComputePipelineStaleness` metric. Alarm `life-platform-compute-pipeline-stale` deployed. | R8 Top-10 Risk 7 | — | MEDIUM | ✅ DONE v3.7.31 — alarm deployed `deploy/create_compute_staleness_alarm.sh` |
| R8-LT8 | **DLQ consumer: event-driven vs scheduled** | R8 §6 R-3 | S (30min) | LOW | ✅ Done (v3.7.19) — ADR-024 written, retain schedule model |
| R8-LT9 | **Pre-compute weekly correlation matrix** — `SOURCE#weekly_correlations` partition. | Pre-R8 | M (3h) | LOW | ✅ Done (v3.7.20) — `weekly-correlation-compute` Lambda, 20 pairs, Sunday 11:30 AM PT |

### Tier 2.5 — April 13 Cleanup (run before R14)

These are not architecture decisions — they're deferred deletions and one-time setups.

| ID | Item | Source | Effort | Status |
|----|------|--------|--------|--------|
| CLEANUP-1 | **Remove `write_composite_scores()` dead code** | ADR-025 + R12 Viktor | S | ✅ Done (v3.7.28) |
| CLEANUP-2 | **Lambda@Edge in `ci/lambda_map.json`** | R12 Yael | S | ✅ Done (v3.7.27) — `lambda_edge` section with cf-auth, region, CloudFront ID |
| CLEANUP-3 | **Google Calendar OAuth activation** — N/A: integration retired (ADR-030, v3.7.46). All setup scripts deleted. | R9-R13 every review | — | ❌ Retired (ADR-030) |
| CLEANUP-4 | **`ingestion_validator.py` Decimal import fix** — `_Decimal` was used in typed_fields loop with no import anywhere in the file (live NameError risk). `from decimal import Decimal as _Decimal` moved to module level. `weekly_correlation_compute_lambda.py` was already clean. | R12 Elena + Marcus | S | ✅ Done (v3.7.29) |
| SEC-3 MEDIUM | **`validate_date_range` in `mcp/utils.py`** — new stable module. Prevents unbounded DDB range scans from MCP tool date inputs. Auto-applied in `handler._validate_tool_args` step 4 to all tools with `start_date`/`end_date` or `date` args. `validate_single_date` also included. | R13 Yael / board | S | ✅ Done (v3.7.29) |
| ADR-027 EXEC | **Stable MCP core → Layer** — Layer v10 published with 6 stable mcp/ modules. Ingestion + Email stacks updated to `:10`. | ADR-027 | — | ✅ DONE v3.7.31 — `life-platform-shared-utils:10` live, CDK deployed |

---

### R16 Findings (2026-03-15, v3.7.47)

| ID | Item | Source | Effort | Impact | Status |
|----|------|--------|--------|--------|--------|
| R16-F01 | **ARCHITECTURE inline tool count 89→87** | R16 Omar | XS | LOW | ✅ Done (v3.7.48) |
| R16-F02 | **`google-calendar` secret deletion** | R16 Yael | XS | LOW | ✅ Done — already deleted in v3.7.46 |
| R16-F03 | **CDK deploy removes `google-calendar-ingestion`** | R16 Marcus | S | LOW | ✅ Done (v3.7.48) — 10/10 smoke passed |
| R16-F04 | **CI/CD pipeline activation** — OIDC role provisioned, `production` Environment confirmed, first pipeline run triggered. | R16 Elena | M | MEDIUM | ✅ Done (v3.7.48) — closes TB7-1 |
| R16-F05 | **Canary tool count threshold <50→<80** | R16 Jin | XS | LOW | ✅ Done (v3.7.48) |
| R16-F06 | **`webhook-key` deletion verified** — `DeletedDate: 2026-03-14` confirmed. Secrets count updated to 9. | R16 Yael | XS | LOW | ✅ Done (v3.7.48) |
| R14-F02 | **INTELLIGENCE_LAYER.md IC-4/IC-5 descriptions** | R14 Sarah (carry) | S | LOW | ✅ Done (v3.7.48) |
| R14-F04 | **MCP_TOOL_CATALOG.md ADR-030 retirement note** | R14 Sarah (carry) | XS | LOW | ✅ Done (v3.7.48) |

---

### Tier 4 — Deferred / Data-Gated

| ID | Item | Source | Target Date | Gate |
|----|------|--------|-------------|------|
| IC-4 | Failure pattern recognition | IC roadmap | ~May 2026 | 6-8 weeks behavioral data |
| IC-5 | Momentum / early warning | IC roadmap | ~May 2026 | 6-8 weeks behavioral data |
| IC-9 | Episodic memory ("what worked") | IC roadmap | ~June 2026 | Month 3 data |
| IC-10 | Personal response curves | IC roadmap | ~July 2026 | Month 4 data |
| IC-11 | Coaching calibration | IC roadmap | ~June 2026 | Month 3 data |
| IC-20 | Titan Embeddings (Bedrock) | IC roadmap | ~July 2026 | Month 3-4 insight corpus |
| IC-26 | Temporal pattern mining | IC roadmap | ~May 2026 | 8+ weeks data |
| IC-28 | Permanent learnings distillation | IC roadmap | ~June 2026 | Quarterly |
| COST-2 | CloudWatch EMF analysis → SIMP-1 | Pre-R8 | ~2026-04-13 | 30 days EMF data |

---

## Board Summit Roadmap (2026-03-16, updated 2026-03-16 v3.7.61)

> Joint session: Health & Personal Results Board × Technical & Product Board.
> Full summit record: `board_summit_2026-03-16.md` (in outputs).
> Board Sprint Review: `docs/reviews/BOARD_SPRINT_REVIEW_2026-03-16.md`
> **Implementation sprint plan: `docs/SPRINT_PLAN.md`** (4 sprints + SIMP-1 mini, all 45 features inventoried)

### Synthesized Priority Stack (Top 15)

Ranked by combined impact × feasibility × strategic importance across all three dimensions (personal results + website + platform).

| Rank | ID | Feature | Champion | Horizon | Status |
|------|-----|---------|----------|---------|--------|
| 1 | BS-01 | **Essential Seven Protocol** — Formalize Tier 0 habits as primary tracking interface; dedicated view, streak counts, failure analysis | Clear | **Sprint 1** | Not started |
| 2 | BS-02 | **Website Hero Redesign** — Transformation story hero with live weight data, compelling narrative hook | Moreau | **Sprint 1** | Not started |
| 3 | BS-03 | **Email Capture + Weekly Signal Newsletter** — SES-backed subscribe flow + Chronicle→email pipeline | Kim / Marcus | **Sprint 1** | Subscribe backend ✅ (v3.7.60); pipeline not started |
| 4 | BS-04 | **Pre-Computed Composite Scores** — Move expensive computations to scheduled Lambdas (extends R8-ST5/ADR-025 work) | Priya | Done | ✅ Done (ADR-025) |
| 5 | BS-05 | **AI Confidence Scoring** — 3-level badge (High/Medium/Low) on every AI-generated insight based on data completeness, sample size, effect size | Henning | **Sprint 1** | Not started (moved from Sprint 2 per Yael — must precede email-to-subscribers) |
| 6 | BS-06 | **Habit Cascade Detector** — Conditional probability matrix: P(fail Y \| failed X within 48h). Surface top-3 cascades in Daily Brief | Clear / Anika | Backlog | Not started (needs 60+ days Habitify data, ~May 2026) |
| 7 | BS-07 | **Website API Layer** — API Gateway + Lambda serving public data endpoints (extends v3.7.51 site_api work) | Marcus | **Sprint 2** | Partially done (site_api exists) |
| 8 | BS-08 | **Unified Sleep Record** — Merge Whoop/Eight Sleep/Apple Health into canonical sleep record per night in DDB | Omar / Huberman | **Sprint 2** | Conflict resolution rules doc → Sprint 1 prereq; implementation Sprint 2 |
| 9 | BS-09 | **ACWR Training Load Model** — Acute:chronic workload ratio from Whoop strain + Strava. Alert >1.3 or <0.8 | Attia / Jin | **Sprint 1** | Not started. Pure compute Lambda (no LLM). |
| 10 | BS-10 | **Meal-Level CGM Response Scorer** — Match MacroFactor meal timestamps with CGM glucose curves. Personal food response database | Patrick / Anika | Backlog | Not started (needs CGM data maturity, ~June 2026) |
| 11 | BS-11 | **Transformation Timeline (Website)** — Interactive scrollable journey visualization, shareable | Moreau / Kim | **Sprint 4** | ✅ Done (v3.7.68) |
| 12 | BS-12 | **Deficit Sustainability Tracker** — Multi-signal early warning for unsustainable caloric deficit | Norton / Attia | **Sprint 3** | ✅ Done (v3.7.67) |
| 13 | BS-13 | **N=1 Experiment Archive (Website)** — Public experiment case studies with data | Patrick / Kim | **Sprint 3** | ✅ Done (v3.7.65) |
| 14 | BS-14 | **Multi-User Data Isolation Design** — Schema design for tenant isolation (design doc only) | Yael / Omar | **Sprint 4** | ✅ Done (v3.7.68) |
| 15 | BS-15 | **Board of Directors Interactive Tool (Website)** — "Build your own health advisory board" lead magnet | Chen / Kim | Backlog | Not started |

### Personal Results Roadmap (6 Domains)

**Domain 1: Sleep & Recovery Intelligence**
- BS-08: Unified Sleep Record (Sprint 2) — conflict resolution rules → Sprint 1 prereq
- BS-SL1: Sleep Environment Optimizer — cross-reference Eight Sleep temperature data with Whoop staging to find optimal personal settings. *Sprint 3.* ✅ Done (v3.7.67)
- BS-SL2: Circadian Compliance Score — pre-sleep behavioral score from light exposure, meal timing, screen use. *Sprint 2 (Huberman: ships with BS-08).* Sonnet.
- IC-30: Sleep Environment Intelligence IC feature — *Backlog (after BS-SL1 runs 4+ weeks).*

**Domain 2: Nutrition & Metabolic Intelligence**
- BS-10: Meal-Level CGM Response Scorer (Backlog — CGM data maturity)
- BS-12: Deficit Sustainability Tracker (Sprint 3) — Opus
- BS-NU1: Protein Timing & Distribution Score (Sprint 2) — **Opus** (changed from Sonnet per Norton/Patrick)
- IC-29: Metabolic Adaptation Intelligence IC feature — TDEE divergence tracking. *Sprint 3.* Opus. ✅ Done (v3.7.67)

**Domain 3: Training & Performance Intelligence**
- BS-09: ACWR Training Load Model (Sprint 1) — pure compute Lambda, no LLM
- BS-TR1: Centenarian Decathlon Progress Tracker — elevate existing `get_centenarian_benchmarks` to living dashboard. *Sprint 2.* No LLM.
- BS-TR2: Zone 2 Cardiac Efficiency Trend — track pace-at-HR over time for repeated workout types. *Sprint 2.* No LLM.
- IC-28: Training Load Intelligence IC feature — wire ACWR into Daily Brief context. *Sprint 3.* Sonnet.

**Domain 4: Behavioral & Habit System**
- BS-01: Essential Seven Protocol (Sprint 1) — Sonnet
- BS-06: Habit Cascade Detector (Backlog — 60+ days Habitify data, ~May 2026) — Opus
- BS-BH1: Vice Streak Amplifier — dedicated streak tracker with compounding value. *Sprint 2.* Sonnet.
- BS-MP3: Decision Fatigue Detector (proactive) — elevate existing tool. *Sprint 2.* Sonnet.
- IC-27: Habit Cascade Intelligence IC feature — *Backlog (data-gated, same as BS-06).*

**Domain 5: Longevity & Biomarker Intelligence**
- BS-BM1: Biomarker Trajectory Alert System — **Backlog** (Henning: 7 draws only, CIs too wide. Gate: ≥10 blood draws ~2028+)
- BS-BM2: Genome-Informed Risk Dashboard — static personalized SNP-to-intervention page. *Sprint 4.* Opus.
- BS-BM3: DEXA-Anchored Body Composition Model — Bayesian daily estimate between scans. *Backlog (needs DEXA scan #2).*
- IC-31: Biomarker Trajectory Intelligence IC feature — *Backlog (same gate as BS-BM1).*
- BS-T2-2: Biomarker Trajectory Engine (Tier 2) — linear regression + 95% CI per biomarker. *Backlog (data-gated).*
- BS-T2-3: DEXA-Anchored Composition Model (Tier 2) — Bayesian model. *Backlog (needs DEXA #2).*

**Domain 6: Mental Performance & State of Mind**
- BS-MP1: Autonomic Balance Score — HRV + RHR + RR + sleep quality → 4-quadrant nervous system state. *Sprint 3.* **Opus** (confirmed by Anika + Huberman). ✅ Done (v3.7.67)
- BS-MP2: Journal Sentiment Trajectory — structured sentiment analysis with divergence detection. *Sprint 3.* Opus. ✅ Done (v3.7.67)
- BS-MP3: Decision Fatigue Detector (proactive alert) — *Sprint 2.* Sonnet.
- BS-T2-6: Decision Journal Analytics — calibration score, regret analysis. *Backlog (needs 50+ decisions).*

### Website Roadmap

Site map target (from 4 pages to 10):

| Page | Purpose | Sprint | Dependency |
|------|---------|--------|------------|
| `/` (Home) | Transformation story hero with live weight + streak data | **Sprint 1 (BS-02)** | public_stats.json |
| `/story` | Origin story: where he started, what he built, where he's going. Updated quarterly | Sprint 3+ | Manual content |
| `/live` | Curated privacy-calibrated dashboard: weight trend, training, Character Sheet, streaks | Sprint 4 | BS-07 API layer |
| `/journal` | Evolves from Chronicle hub to broader content: weekly signals + data essays + build logs | Exists | — |
| `/experiments` | N=1 Experiment Archive with case studies | **Sprint 3 (BS-13)** | experiment data |
| `/character` | Interactive 7-pillar explorer with educational context | Exists (evolve) | — |
| `/build` | Technical deep dives on platform architecture | Later | Manual content |
| `/tools` | Free interactive tools: sleep calc, habit quiz, BoD builder | Later (BS-15) | — |
| `/about` | Brief bio, professional context, why this exists | Sprint 3+ | Manual content |
| `/subscribe` | Focused email list landing page | ✅ Live (v3.7.60) | — |

**Interactive Features (ranked by strategic value):**
1. Transformation Timeline — `Sprint 4 (BS-11)`. Requires API layer.
2. Correlation Explorer — `Sprint 4 (WEB-CE)`. Pre-computed correlations from DDB.
3. Board of Directors Builder — `Backlog (BS-15)`.
4. N=1 Experiment Template Tool — `Backlog (WEB-NET)`. Underestimated effort; requires backend session + download.
5. Weekly Challenge Ticker — `Sprint 3 (WEB-WCT)`. Persistent element all pages.

**Content Strategy:**
- Weekly Signal (automated Wednesday, 500 words max) — evolves from Chronicle, delivered to subscribers (Sprint 1+3)
- Data Essays (monthly, 1,500-3,000 words) — SEO + shareability engine
- Build Logs (biweekly) — technical content for developer audience, cross-posted to dev.to/HN

**Email Capture & Community Phases:**
- Phase 1 (Now): SES subscribe backend ✅ live. Chronicle→email pipeline Sprint 1. Target: 500 subscribers in 6 months.
- Phase 2 (EMAIL-P2, target June 16, 2026): Monthly "Data Drop" email-exclusive content — full data export from one domain. Rewards subscribers with radical transparency content.
- Phase 3 (EMAIL-P3, target September 16, 2026): Discord or Circle community launch — invite-only from email list. Features testing ground.

**Design Language (Ava Moreau directive):**
- Dark charcoal (#0D1117) background, warm white (#E6EDF3) text, amber/gold (#F0B429) accent
- Data positive: muted teal (#2EA98F), Data negative: muted coral (#E85D5D), Secondary: cool gray (#8B949E)
- Typography: Inter (headlines + body), JetBrains Mono (data/code)
- Micro-animations on data updates; hover states on every data point; skeleton loading states; charts animate on scroll-into-view
- Emotional tone: personal notebook connected to 19 data sources, not clinical dashboard
- Prerequisite before any website feature ships: write the 50-word "why should a stranger care" paragraph

### Commercialization Assessment

**Highest-probability wedge:** AI Health Coaching Email Digest as standalone product ($29-49/month). User connects Whoop + nutrition tracker → receives daily coaching email. Lowest activation energy path.

**Three paths to $1M ARR (assessed, not committed):**
1. B2C SaaS ($39/mo × 2,200 subs) — requires multi-user arch + AI personalization + auth + compliance. 12-18 months.
2. B2B Longevity Clinic ($500/mo × 170 clinics) — white-label dashboard + HIPAA. 18-24 months.
3. Content + Community ($10/mo premium × 50K subs + info product) — fastest to first dollar, no extra engineering.

**Architecture gap for multi-user:** BS-T2-1/BS-14 (data isolation design — Sprint 4), BS-T3-1 (auth), BS-T3-2 (data source abstraction), BS-T3-3 (AI personalization framework), BS-T3-4 (compliance). Design BS-14 now; build nothing until wedge validated.

**IP assets:** Cross-source intelligence architecture, AI coaching prompt architecture (BoD personas, two-pass CoT), N=1 experiment framework, Chronicle format, personal transformation narrative.

**Unit economics reminder (Dana Torres):** Per-user cost at current architecture is ~$8-15/month. $39/month subscription has thin margins after payment processing and support costs. Model every new Opus-assigned Lambda for per-user cost at scale. Add Sonnet fast-path + Opus deep-analysis mode as TODO in daily-run Lambdas.

### Board Technical Roadmap (supplements existing tiers)

**Tier 1 additions (Next 90 Days — see SPRINT_PLAN.md for sprint assignments):**

| ID | Feature | Sprint | Model | Complexity | IC Basis |
|----|---------|--------|-------|------------|----------|
| BS-T1-1 (= BS-03) | Chronicle → Email Pipeline | Sprint 1 | Sonnet | S | — |
| BS-T1-2 (= BS-09) | ACWR Training Load Model Lambda | Sprint 1 | None | S | — |
| BS-T1-3 (= BS-05) | AI Confidence Scoring | Sprint 1 | Sonnet | M | IC-3 |
| BS-T1-4 (= BS-08) | Unified Sleep Record reconciliation | Sprint 2 | None | M | — |
| BS-T1-5 (= BS-12) | Deficit Sustainability Tracker | Sprint 3 | Opus | M | IC-3 |
| BS-T1-6 (= BS-07) | Website API Layer | Sprint 2 | None | M | — |

**Tier 2 additions (90-180 Days):**

| ID | Feature | Sprint | Model | Complexity | IC Basis |
|----|---------|--------|-------|------------|----------|
| BS-T2-1 (= BS-14) | Multi-User Data Isolation Architecture (design only) | Sprint 4 | Opus | L | — |
| BS-T2-2 | Biomarker Trajectory Engine (linear regression + 95% CI per biomarker) | Backlog | Opus | M | IC-18 |
| BS-T2-3 | DEXA-Anchored Composition Model (Bayesian) | Backlog | Opus | L | — |
| BS-T2-4 (= BS-11) | Transformation Timeline website | Sprint 4 | None | L | — |
| BS-T2-5 | Chronicle → Newsletter Delivery Pipeline (full automation + subscriber send) | Sprint 3 | None | M | — |
| BS-T2-6 | Decision Journal Analytics (calibration score, regret analysis) | Backlog | Opus | M | IC-19 |
| **BS-T2-7** | **Experiment Results Auto-Analysis** — when N=1 experiment ends, auto-run before/during/after comparisons on all relevant metrics using declared hypothesis variables. Generate structured experiment report. | **Backlog** | **Opus** | M | IC-18 |

**Tier 3 additions (180-365 Days):**

| ID | Feature | Model | Complexity | IC Basis | Notes |
|----|---------|-------|------------|----------|-------|
| BS-T3-1 | Authentication & User Accounts (Cognito or Auth0) | None | L | — | Commercialization prerequisite |
| BS-T3-2 | Data Source Abstraction Layer (plugin architecture for multi-user) | None | XL | — | Multi-user prerequisite |
| BS-T3-3 | AI Coaching Personalization Framework (decouple from Matthew-specific context) | Opus | XL | IC-3 | Multi-user prerequisite |
| BS-T3-4 | Compliance & Data Governance (HIPAA, GDPR) | None | XL | — | Commercialization prerequisite |
| **BS-T3-5** | **Real-Time Streaming Pipeline** — Replace batch-based ingestion with EventBridge + SQS for sources supporting webhooks (CGM, Whoop). Enables real-time alerts and live dashboard updates. | None | L | — | Most sources don't support true webhooks; evaluate at 180 days. ~Sep 2026. |
| **BS-T3-6** | **Cost-Optimized Multi-Tenant DynamoDB** — when user count exceeds ~10, evaluate DDB cost at scale. Current single-table design may need GSI optimization, TTL policies for ephemeral data, possible move to provisioned capacity with auto-scaling. | None | L | — | Gate: user count >10. Dana Torres: model unit economics first. |

**Statistical Validity Flags (Henning Brandt — applies to all sprint work):**
- Correlations with n<30: show "low confidence" badge regardless of p-value
- Weekly correlation matrix: report corrected significance threshold alongside each result
- Meal-level CGM scoring: minimum 5 repetitions of same meal before any claims
- DEXA-anchored model: never report lean mass estimates to >1 decimal place (DEXA itself ±1 lb)
- Any "trend" based on <12 weekly observations: re-label as "preliminary pattern"
- **New (v3.7.61):** AI Confidence Scoring (BS-05) requires written specification before implementation. Spec must define: sample size (n), effect size threshold, p-value/CI requirement, data freshness cutoff per insight type.

### IC-27 through IC-31 — Explicit Definitions

> Planned in v3.7.54 header; defined explicitly in v3.7.61.

| ID | Name | Description | Model | Gate | Sprint |
|----|------|-------------|-------|------|--------|
| IC-27 | **Habit Cascade Intelligence** | Conditional probability matrix: P(fail habit Y within 48h given fail of habit X). Surface top-3 cascade pairs in Daily Brief as predictive warnings. Build and update weekly from Habitify completion data. | Opus | 60+ days consistent Habitify data (~May 2026) | Backlog |
| IC-28 | **Training Load Intelligence** | Wire ACWR data (from BS-09) into Daily Brief context. When ACWR is elevated or suppressed, contextualize all training metrics with prescriptive guidance: specific volume adjustments, cross-reference with historical injury-risk periods, recovery protocols. | Sonnet | BS-09 live (Sprint 1) | Sprint 3 |
| IC-29 | **Metabolic Adaptation Intelligence** | Track actual TDEE vs. MacroFactor adaptive estimate divergence. When weight loss rate diverges from calorie-deficit prediction, flag metabolic adaptation: "Your effective TDEE has dropped ~X calories from baseline." Distinguish genuine adaptation from tracking inaccuracy. | Opus | 6+ weeks weight + calorie data | Sprint 3 |
| IC-30 | **Sleep Environment Intelligence** | Wire Sleep Environment Optimizer data (BS-SL1) into Daily Brief and Evening Nudge. Surface personalized temperature recommendations. Detect when environmental conditions are trending against sleep quality. Cross-reference with training load and nutrition timing. | Opus | BS-SL1 running 4+ weeks with output | Backlog (~Aug 2026) |
| IC-31 | **Biomarker Trajectory Intelligence** | Proactive flagging of biomarkers trending toward clinical thresholds. Compute linear regression + 95% CI per biomarker. Cross-reference trajectory with lifestyle data from same period: "Your LDL increased X% between Draw 5 and 6. During that period, Zone 2 training volume was Y and saturated fat intake was Z." | Opus | ≥10 blood draws (currently 7; ~2028+) | Backlog |

---

## Sprint Implementation Plan

> Full sprint plan with effort estimates, model assignments, deliverables, and prerequisites: **`docs/SPRINT_PLAN.md`**
> Board Sprint Review record: **`docs/reviews/BOARD_SPRINT_REVIEW_2026-03-16.md`**

### Sprint Overview

| Sprint | Weeks | Target | Theme | Items | Est. Hours |
|--------|-------|--------|-------|-------|-----------|
| Sprint 1 | 1-2 | ~Mar 30 | Foundation + Audience | BS-01, BS-02, BS-03, BS-05, BS-09 | ~19h |
| Sprint 2 | 3-4 | ~Apr 13 | Intelligence Core + Sleep | BS-07, BS-08, BS-SL2, BS-BH1, BS-MP3, BS-TR1, BS-TR2, BS-NU1 | ~27h |
| SIMP-1 Ph2 | 5 | ~Apr 13 | Rationalization | 89→≤80 tools, EMF review | ~5h |
| Sprint 3 | 6-9 | ~May 11 | Advanced Intelligence + Content | BS-12, BS-SL1, BS-MP1, BS-MP2, BS-13, BS-T2-5, WEB-WCT, IC-28, IC-29 | ~38h |
| Sprint 4 | 10-13 | ~Jun 8 | Website Interactive + Architecture | BS-11, WEB-CE, BS-BM2, BS-14 | ~27h | ✅ COMPLETE |

**Backlog activation schedule:**
- ~May 2026: BS-06 (Habit Cascade), IC-27, BS-T2-7 (data gates)
- ~June 2026: EMAIL-P2 Data Drop, BS-10 (CGM maturity)
- ~August 2026: IC-30 (after BS-SL1 matures)
- ~September 2026: EMAIL-P3 Community launch
- Post-DEXA: BS-BM3, BS-T2-3
- ~2028+: BS-BM1, BS-T2-2, IC-31

---

## Completed Items (Recent)

| ID | Item | Version | Date |
|----|------|---------|------|
| R13 | Architecture Review #13 conducted (B+/A-) — 15 findings, full report `docs/reviews/REVIEW_2026-03-14_v13.md` | v3.7.29 | 2026-03-14 |
| R8-P0a | Webhook auth restored (CDK IAM fix) | v3.7.15 | 2026-03-13 |
| R8-P0b | Secret state reconciled (10 actual secrets documented) | v3.7.15 | 2026-03-13 |
| R8-P0c | IAM/secrets CI lint (`test_iam_secrets_consistency.py` S1-S4) | v3.7.15 | 2026-03-13 |
| R8-P0d | ARCHITECTURE.md secrets table updated | v3.7.15 | 2026-03-13 |
| R8-P0e | CV_THRESHOLDS stale comments fixed | v3.7.15 | 2026-03-13 |
| R8-P0f | SCHEMA.md added to sync_doc_metadata.py | v3.7.15 | 2026-03-13 |
| R57 | Attia centenarian decathlon benchmarks MCP tool (`get_centenarian_benchmarks`) | v3.7.31 | 2026-03-15 |
| R6 | Per-tool 30s soft timeout in MCP handler | v3.7.31 | 2026-03-15 |
| R54 | Evening nudge Lambda (`evening-nudge`, 8 PM PT daily) | v3.7.31 | 2026-03-15 |
| R55 | Withings OAuth consecutive-error alarm | v3.7.30 | 2026-03-15 |
| R31 | MCP error standardisation (`mcp_error()`, `ERROR_CODES`) | v3.7.30 | 2026-03-15 |
| R49 | ONBOARDING.md, deploy/README.md, DATA_FLOW_DIAGRAM.md | v3.7.30 | 2026-03-15 |
| ADR-027 | Stable Layer v10 (mcp/ core modules) + CDK rollout | v3.7.31 | 2026-03-15 |
| Risk-7 | Compute pipeline staleness alarm deployed | v3.7.31 | 2026-03-15 |
| R8-P0g | Architecture Review #8 conducted (A-) | v3.7.15 | 2026-03-13 |
| TB7-* | All TB7 items closed | v3.7.8 | 2026-03-13 |
| PROD-1 | CDK migration (8 stacks) | v3.4.0 | 2026-03-10 |
| SEC-1 | Per-function IAM roles (43 dedicated) | v3.4.0 | 2026-03-10 |
| COST-A | CloudWatch alarm consolidation (87→47) | v3.4.0 | 2026-03-10 |

---

## Architecture Review History

| # | Date | Version | Grade | Key Findings |
|---|------|---------|-------|-------------|
| R16 | 2026-03-15 | v3.7.47 | A | 6 new findings (1 Medium: CI/CD activation; 5 Low: doc drift from Google Calendar retirement). All 6 R15 findings closed. 4 carried forward. MCP outage incident analyzed. Report: `docs/reviews/REVIEW_2026-03-15_v16.md` |
| R15 | 2026-03-15 | v3.7.43 | A | 6 Low findings (all doc drift). All R14 findings resolved. Zero dimension changes. Platform in steady-state. Report: `docs/reviews/REVIEW_2026-03-15_v15.md` |
| R14 | 2026-03-15 | v3.7.40 | A | 8 findings. MCP canary + X-Ray tracing. Security hardening. Report: `docs/reviews/REVIEW_2026-03-15_v14.md` |
| R13 | 2026-03-14 | v3.7.29 | B+/A- | Full external-style review. 15 findings: no CI/CD pipeline (#1 risk), no integration tests, OAuth fail-open, correlation n-gating gap, no PITR drill, layer version fragility, no medical disclaimers in MCP responses. 30-60-90 roadmap. Report: `docs/reviews/REVIEW_2026-03-14_v13.md` |
| R12 | 2026-03-15 | v3.7.25 | A- | Validator S3 bug, 4 partitions unwired, composite_scores stale. All 8 items resolved same session. |
| R11 | 2026-03-15 | v3.7.24 | A | Engineering strategy: deploy_and_verify.sh, integration tests I1-I10, auto-discover counters, checklists. All 9 items resolved. |
| R10 | 2026-03-15 | v3.7.23 | A | Double-warmer, Calendar pre-auth handler, health_context wired. All items resolved. |
| R9 | 2026-03-14 | v3.7.22 | A | tools_calendar cold-start, n-gated correlations, dedicated warmer Lambda, 9 dispatcher tests. All 21 items resolved. |
| R8 | 2026-03-13 | v3.7.15 | A- | COST-B secret drift, webhook auth broken, complexity limits. Full report: `docs/reviews/architecture_review_8_full.md` |
| R7 | 2026-03-11 | v3.5.x | — | TB7 hardening sprint (25 items) |
| R6 | 2026-03-10 | v3.4.x | — | CDK migration review |
| R1-R5 | 2026-02-28–03-09 | various | — | See `docs/reviews/` |

---

## Key Metrics

| Metric | Current | Target | Notes |
|--------|---------|--------|-------|
| MCP tools | 95 | ≤80 (SIMP-1 Phase 2) | Phase 1 complete (116→89). Sprint 3 added 5 tools (90→95). Phase 2 gated ~Apr 13 |
| Lambdas | 48 (CDK) + 1 Lambda@Edge + 1 us-east-1 (site-api) + 1 us-west-2 manual (email-subscriber) | — | |
| CloudWatch alarms | 49 | — | +SLO-5 warmer alarm (v3.7.22) |
| Monthly cost | ~$13 | <$25 | Well under budget |
| Active secrets | 9 | — | webhook-key deleted 2026-03-14; google-calendar deleted 2026-03-15 (ADR-030) |
| CI linters | 9 | — | H1-H5, S1-S4, IAM, registry, handler, wiring, DDB patterns |
| SLOs defined | 5 | — | SLO-1 through SLO-5 (warmer added v3.7.22) |
| IC features live | 16 of 31 | — | IC-29 (deficit+metabolic) + IC-30 (autonomic balance) deployed v3.7.67. |
| Data sources | 19 | — | google_calendar retired (ADR-030, v3.7.46) |
| Architecture review grade | A | A | R16 grade A. R17 targeting ~June 2026. All 4 sprints complete. |
| R13 open findings | 0 of 15 | 0 | All closed. F03 (monolith split) deferred via ADR-029. |
| CI integration tests wired | I1/I2/I4-I9 | all | I3/I10-I14 manual-only (Lambda invocation side effects or special auth) |
| Board Summit features | 45 total | — | Sprint 1-4: 26 features. Backlog: 19 features. See SPRINT_PLAN.md. |
| Email subscribers | 0 | 500 (6 months) | Subscribe backend live v3.7.60. SES sandbox exit pending. |
