# Life Platform — Pre-Compiled Review Bundle
**Generated:** 2026-04-04
**Purpose:** Single-file input for architecture reviews. Contains all platform state needed for a Technical Board assessment.
**Usage:** Start a new session and say: "Read this review bundle file, then conduct Architecture Review #N using the Technical Board of Directors."

---

## 1. PLATFORM STATE SNAPSHOT

### Latest Handover

# Handover — Documentation Sprint (R19 Path to A-) v4.9.0

**Date:** 2026-04-04
**Scope:** Comprehensive documentation audit and update across 7 docs. Resolves all R19 findings.

## What Changed

### Documentation Sprint (R19 remediation — all 7 findings resolved)

**INFRASTRUCTURE.md:**
- MCP tools: 118 → 115 (matched header to reality)
- CloudWatch alarms: ~49 → ~66
- Lambda section: 61 → 62 (60 CDK + 2 Edge)
- Added 5 missing Lambdas: `apple-health-ingestion`, `measurements-ingestion`, `ai-expert-analyzer`, `journal-analyzer`, `field-notes-generate`
- Removed `site-api-ai` from operational list (not independently deployed per lambda_map skip_deploy)
- Lambda categories reconciled: Ingestion 14→16, Compute 9→12, Operational 22→21 (total 62)
- Local project structure: 30 → 35 tool modules
- Added `averagejoematt.com` (E3S424OXQZ8NBE) to Web Properties table
- S3 key prefixes: added `site/`, `uploads/`, `imports/`

**ARCHITECTURE.md:**
- Header: 26-module → 35-module MCP package
- Local project structure fully rewritten: all Lambda category counts and members updated
- Fixed `site_api_lambda — us-east-1` → `us-west-2`
- Added `secret_cache.py` and `site_writer.py` to shared module list

**SLOs.md:**
- Removed Google Calendar reference (ADR-030)
- Monitored sources expanded 10 → 13 (added Weather, Food Delivery, Measurements)

**Section 13b (generate_review_bundle.py):**
- Added full R19 findings table (7 findings, all RESOLVED with version + proof)

**RUNBOOK.md:**
- Header: 26-module → 35-module
- Cache warmer: 12 → 14 tools
- Shared layer modules list: expanded from 5 to 16 (complete list)

**OPERATOR_GUIDE.md:**
- Version stamp: v4.5.1 → v4.9.0
- Pipeline ingestion: 13 → 16 Lambdas

**INCIDENT_LOG.md:**
- Verified current (5 v4.4.0 incidents already present from v4.5.2)
- Header date refreshed

### R19 Finding Disposition (all 7 resolved)

| ID | Finding | Status |
|----|---------|--------|
| R19-F01 | INFRASTRUCTURE.md stale | ✅ RESOLVED |
| R19-F02 | ARCHITECTURE.md contradictions | ✅ RESOLVED |
| R19-F03 | INCIDENT_LOG missing incidents | ✅ Already resolved v4.5.2 |
| R19-F04 | SLOs stale sources | ✅ RESOLVED |
| R19-F05 | 118 MCP tools | ✅ Already resolved (ADR-045) |
| R19-F06 | Site-API region | ✅ Already resolved v4.3.0 |
| R19-F07 | Section 13b not updated | ✅ RESOLVED |

## Key Files Modified
- `docs/INFRASTRUCTURE.md`
- `docs/ARCHITECTURE.md`
- `docs/SLOs.md`
- `docs/RUNBOOK.md`
- `docs/OPERATOR_GUIDE.md`
- `docs/INCIDENT_LOG.md`
- `deploy/generate_review_bundle.py`

## Deploy Status
- No deploys needed — doc-only changes
- All changes on local filesystem, ready for `git add -A && git commit && git push`

## Not Done / Carry Forward
- **sync_doc_metadata.py** — archived to `deploy/archive/onetime/`. Session close checklist in RUNBOOK still references it. May need cleanup.
- **Protocol adherence on sleep page** — needs design decision
- **TDEE tracking** — MacroFactor doesn't export TDEE
- **Glucose intraday curve** — needs raw 5-min CGM readings
- **IC-4/IC-5** (failure pattern + momentum warning) — data gate ~May 1
- **SIMP-1 Phase 2** — accepted via ADR-045 (118→115, not pursuing ≤80)


---

## 2. RECENT CHANGELOG

## v4.9.0-docs — Documentation Sprint: R19 Path to A- (2026-04-04)

Dedicated documentation session resolving all 7 R19 architecture review findings. No code or deploy changes — docs only.

### Documentation Updates (7 files)
- **INFRASTRUCTURE.md**: MCP 118→115, alarms ~49→~66, Lambdas 61→62 (added 5 missing: apple-health-ingestion, measurements-ingestion, ai-expert-analyzer, journal-analyzer, field-notes-generate), category totals reconciled (16+11+12+21+2=62), added averagejoematt.com to Web Properties, S3 prefixes expanded, local project structure 30→35 modules
- **ARCHITECTURE.md**: Header 26→35-module MCP package, local project structure rewritten with accurate Lambda categories + us-west-2 site-api, added secret_cache.py + site_writer.py to shared modules
- **SLOs.md**: Removed Google Calendar, expanded monitored sources 10→13 (added Weather, Food Delivery, Measurements)
- **generate_review_bundle.py**: Section 13b — added R19 findings table (7 items, all RESOLVED)
- **RUNBOOK.md**: 26→35-module, cache warmer 12→14, shared layer modules 5→16
- **OPERATOR_GUIDE.md**: Version v4.5.1→v4.9.0, pipeline ingestion 13→16
- **INCIDENT_LOG.md**: Verified current, header date refreshed

---

## v4.9.0 — Day 3 QA Sweep + Cost Optimization (2026-04-03)

### QA Sweep (57 issues identified, 51+ resolved)
- CSP fix: added `cdn.jsdelivr.net` to script-src (was blocking ALL Chart.js charts)
- Content-before-charts: fixed canvas offsetWidth=0 bug on 5 pages (glucose, sleep, nutrition, training, mind)
- Experiment date clamp: `_experiment_date()` now uses EXPERIMENT_START (Apr 1), not EXPERIMENT_QUERY_START (Mar 31)
- Weight rounding: whole numbers across all endpoints (was 1 decimal)
- Weight baseline: standardized to 307 lbs across 6 files (was 302 in 16 places)
- Platform stats: synced site_constants.js to match API (121 tools, 62 Lambdas, 72 pages, 1075 tests)
- "Launching April 1" → "Active" on about/mission pages
- Chronicle sample: removed fabricated mock email, "April 8" → "next Wednesday"
- Subscriber onboarding: dynamic content from posts.json (no more hardcoded links)
- Subscriber count: renamed /api/subscriber_count → /api/sub_count (CloudFront routing conflict)
- Nutrition: field name mapping for weekday/periodization averages (total_calories_kcal, total_protein_g)
- Glucose: food matching fixed (dexcom→apple_health partition, field name mapping), best/worst day added
- Mind: mood falls back to apple_health som_avg_valence, energy from journal_analysis, breathwork from mindful_minutes
- Training: breathwork queries mindful_minutes, modality chart clamped to experiment start, active days denominator
- Sleep: bed time/wake time/social jet lag from Whoop sleep_start/end, HRV fallback to most recent with data
- Pulse: recovery_pct, hrv_ms, rhr_bpm, hours fields added for frontend
- Status page: breathwork field_check→mindful_minutes, email idle fix (_sched_aware ordering), alarm recovery logic
- QA smoke: legacy checks made non-critical, MCP secret name fixed
- Frontend: chart thresholds lowered from >=3/>=7 to >=1 for sparse data, AI cards moved up on 4 pages
- Banister/ACWR/HR recovery: collapsed into single "requires 4+ weeks" card
- Glucose daily curve section: hidden when no intraday data
- Habits heatmap: dynamic grid from experiment start
- Story: bar count filtered to experiment window
- Character: heatmap filtered to post-experiment weeks, level-up events enriched with pillar drivers

### Cost Optimization (COST-OPT)
- Secret caching: 15-min TTL in-memory cache across 9 Lambdas (reduces Secrets Manager calls ~90%)
- Tiered ingestion: Weather + Todoist reduced from hourly to 2x daily
- Shared layer v22: includes secret_cache.py module

### Pipeline Improvements
- Whoop gap-fill: detects incomplete records (missing recovery_score) and re-fetches
- Garmin gap-fill: detects incomplete records (missing steps) and re-fetches
- Whoop data backfilled for Apr 2-3 (recovery/sleep was missing from initial ingestion)
- Daily brief: IC-15 isoformat bug fixed, site_writer Float→Decimal fix
- Notion Lambda: created_time converted to PT before date extraction

### Testing
- Playwright visual QA test: tests/visual_qa.py — 12-page sweep with deep scroll, canvas pixel checking, stale text detection
- 985 pytest tests passing, 0 failures

### Infrastructure
- Shared Lambda layer: v19→v20→v21→v22 (4 rebuilds this session)
- CDK: CSP updated to allow cdn.jsdelivr.net, Weather/Todoist cron updated
- EventBridge: Weather + Todoist schedules updated to 2x daily
- All 16 layer consumers updated to v22

---

## v4.8.3 — 2026-04-01: Day 1 Sweep + Pipeline Reliability

### Critical Fixes (4 sweep items)
- **6 Lambdas on stale layer v18** → updated to v19
- **MCP canary secret mismatch**: was reading `life-platform/ai-keys` instead of `life-platform/mcp-api-key` — canary was silently non-functional since deployment. Fixed CDK + live IAM.
- **Data reconciliation S3 prefix**: CDK had `reports/*` but Lambda writes to `reconciliation/*`. Fixed.
- **DLQ stale message**: MacroFactor April 1 CSV (already reprocessed). Purged.

### CI/CD Fixes
- 8 flake8 F821 errors in `site_api_lambda.py`: undefined `REGION` (→ `DDB_REGION`), `now` out of scope, unused `global _COLD_START`, missing `s3`/`S3_BUCKET` in healthz handler
- Added `.nojekyll` to prevent Jekyll from parsing `{{}}` in docs

### Garmin Rate Limiting
- Garmin API was 429-rate-limited on OAuth token exchange since March 30 (predated hourly switch)
- Reduced Garmin schedule from hourly to 4x daily (`cron(0 0,6,14,22 * * ? *)`)
- Re-authenticated Garmin + Withings OAuth tokens

### Notion Timezone Fix
- Replaced hardcoded `UTC-8` with DST-aware `ZoneInfo("America/Los_Angeles")`
- Extended `created_time` filter end boundary by +1 day to catch late-night PT entries stored under next UTC day

### Site API — Pacific Time Conversion
- All user-facing dates now use `PT = ZoneInfo("America/Los_Angeles")` (module-level constant)
- Pulse day_number, challenge/experiment days_in: switched from UTC to PT
- Pulse queries use range covering both PT and UTC dates to catch timezone boundary records

### Pulse Improvements
- **Recovery/Sleep**: fixed `_latest_item("whoop")` returning workout sub-records instead of daily summary
- **Steps**: Garmin steps as primary source (was Apple Health only — 84 vs 11,356)
- **Journal glyph**: added with `written_today` + `streak_days` (checks both PT and UTC dates)
- **Journal labels**: "open/closed" → "Journaled" / "No entry yet"

### Training Page
- WHOOP duplicate activity dedup: filters WHOOP-sourced activities when Garmin recorded same sport_type on same day
- Apple Health steps as fallback when Garmin has no step data

### Homepage Mobile
- Gauge grid: 3-column → 2-column on screens under 600px

### HAE Water Dedup
- Reading-level deduplication using timestamp map (`_rd_water_intake_ml` in DynamoDB)
- Each reading's timestamp + quantity stored; on re-sends, only new readings counted
- Handles both hourly incremental syncs and manual full-day pushes without double-counting
- `water_intake_oz` derived from deduped `water_intake_ml` (not tracked independently)

### Challenge ID Fix
- DynamoDB challenge key `no-doordash-30d_2026-04-01` didn't match catalog ID `no-doordash-30`
- Fixed DynamoDB record + added date-suffix stripping in API response

### Files Modified
- `lambdas/site_api_lambda.py` — PT timezone, pulse journal/recovery/steps, WHOOP dedup, flake8 fixes
- `lambdas/health_auto_export_lambda.py` — water dedup with timestamp map
- `lambdas/notion_lambda.py` — DST-aware timezone, created_time +1 day filter
- `cdk/stacks/role_policies.py` — canary secret ARN, reconciliation S3 prefix, Withings PutSecretValue
- `cdk/stacks/ingestion_stack.py` — Garmin 4x daily schedule
- `site/index.html` — mobile gauge grid responsive breakpoint
- `.nojekyll` — new file

---

## v4.8.2 — 2026-04-01: Hourly Ingestion + Nutrition Fix + IAM Sweep

### Ingestion Schedule
- CDK: changed from 5x/day to hourly with 10pm-4am PST maintenance window (18 active hours)
- Cost unchanged — gap-aware Lambdas short-circuit in <50ms when no new data

### Pipeline Fixes
- **Nutrition field mismatch**: API expected `calories`/`protein_g` but MacroFactor writes `total_calories_kcal`/`total_protein_g`. Added `_mf()` helper that checks both naming conventions.
- **Pulse endpoint rewritten**: was reading stale S3 file (1x/day), now queries DynamoDB live (5-min cache)
- **Sleep API**: added `deep_pct`, `rem_pct`, `light_pct` from Eight Sleep + `30d_avg_recovery` from Whoop
- **Physical page**: BP section with systolic/diastolic card, status classification, trend chart
- **Homepage**: 6-ring gauge grid (Weight, Lost, Total Progress, HRV, Sleep, Character)

### IAM Sweep
- **13 Lambdas**: added `s3:GetObject` + `s3:ListBucket` (were write-only)
- **2 OAuth Lambdas** (Eight Sleep, Garmin): added `secretsmanager:PutSecretValue` for token persistence
- **MacroFactor**: added `s3:GetObject` for `uploads/` prefix (was failing on Dropbox CSV reads)

### Withings Bug Fix
- Lambda only processed most recent measurement group — BPM reading was newer than scale, so weight was silently discarded. Fixed to iterate ALL groups.

---

## v4.8.1 — 2026-04-01: Day 1 Pipeline Fixes

Critical fixes discovered during Day 1 go-live. Most issues traced to timing/sequencing assumptions that break on the first day of the experiment.

### Data Pipeline Fixes
- **Withings weight bug**: Lambda only processed most recent measurement group — BPM reading (heart_pulse) was newer than scale (weight), so weight was silently discarded. Fixed to iterate ALL groups.
- **HAE blood pressure**: app sends combined `blood_pressure` metric with nested systolic/diastolic. Lambda only recognized separate metrics. Added v1.4.1 combined format handler.
- **HAE weight accepted**: `body_mass` removed from SKIP_METRICS — weight now flows through HAE as Withings API fallback.
- **HAE API key**: was missing from `ingestion-keys` secret. Added.
- **HAE IAM**: added `s3:GetObject` + `s3:ListBucket` for CGM/BP deduplication reads.
- **Withings IAM**: added `secretsmanager:PutSecretValue` for OAuth token persistence.
- **Ingestion lookback**: all 5 API Lambdas now check today (`range(0, N)`) not just yesterday (`range(1, N)`).

### Display/Data Fixes
- **Day counter**: `days_in` showed 0 on Day 1. Fixed to `max(1, days + 1)` across 4 files.
- **EXPERIMENT_QUERY_START clamp**: added to 5 more endpoints that leaked pre-experiment data (habits, journal count, mind overview, vice streaks, strength).
- **`_experiment_date()` helper**: centralized clamp function replacing 16 inline `max()` calls.
- **Sleep API**: added deep_sleep_hours, rem_sleep_hours, recovery_score, hrv, rhr to response.
- **Character page**: reset stale DEFAULTS (was Level 2/38 XP from pre-launch), fixed "Next Tier Lv 21" → "Next Level: Lv 2 (0/60 XP)" + "Tier Unlocks: Lv 21".
- **Stale fallbacks**: character_stats.json, site_config.json overwritten with Day 1 values.

### New Features
- **BP section on physical page**: systolic/diastolic card with status (normal/elevated/high), reference ranges, trend chart.
- **Weight fallback**: `/api/vitals` and stats-refresh check apple_health for weight if Withings is stale.
- **Stats-refresh expanded**: now updates water, character level, weight from HAE (was vitals-only).
- **Status page pipeline detection**: API-based sources flag yellow when data stops for 2+ days (auth failure detection vs "awaiting activity").
- **4 experiments activated**: Breathwork Before Sleep, Daily 8000+ Steps, 16:8 Fasting, No Alcohol.
- **1 challenge activated**: No DoorDash for 30 Days.

### Infrastructure
- Shared Lambda layer: v18 → v19
- API Gateway access logging enabled on HAE webhook

---

## v4.8.0 — 2026-04-01: AI Insight Engine Overhaul — 4 phases

Major overhaul of the AI coaching pipeline. Closes gaps where rich data was written to DynamoDB but never read by AI prompts. Adds memory to prevent repetition and compounds learning over time.

### Phase 1: Anti-Repetition
- `daily_insight_compute_lambda.py`: reads prior 3 days' `guidance_given` from computed_insights, injects "AVOID REPEATING" list into ai_context_block
- `daily_brief_lambda.py`: writes `guidance_given` back to computed_insights after TL;DR generation
- `ai_expert_analyzer_lambda.py`: reads prior analysis for same expert before generating — prompts AI to "find a different angle"

### Phase 2: Wire 6 Unused Data Sources
- **Journal enrichment** (16 fields → coaching): defense patterns, cognitive patterns, growth signals, avoidance flags, social quality, locus of control, stress sources now injected into journal coach prompt
- **Character sheet → tone**: conscientiousness, resilience, growth mindset scores adapt coaching tone
- **Adaptive mode → email tone**: flourishing/struggling classification changes guidance verbosity and framing
- **State of Mind → emotional context**: low mood valence triggers nervous-system-reset priority over performance
- **Supplements → nutrition coach**: active supplement list injected so AI accounts for nutrient adequacy
- **Weather → training prescription**: daylight, barometric pressure, temperature inform training intensity

### Phase 3: Build Memory
- **what_worked**: when weekly grade avg ≥ 85, conditions are recorded to `platform_memory#what_worked` for future reference
- **Weekly correlations**: top 3 significant Pearson r pairs (from 23 computed weekly) injected into coaching context
- Coaching history deduplication infrastructure (guidance_given field tracks what was advised)

### Phase 4: Labs + Genome Personalization
- **New module** `lambdas/labs_coaching.py`: reads latest lab biomarkers, applies coaching rules (ferritin, vitamin D, hs-CRP, HbA1c, fasting insulin, ApoB, testosterone, TSH)
- **New module** `lambdas/genome_coaching.py`: reads genome SNPs, maps to coaching deltas (CYP1A2/caffeine, MTHFR/methylation, FTO/satiety, BDNF/exercise timing, FADS/omega-3, VKORC1/vitamin K, MTNR1B/melatonin), rotates which insights surface each week
- Both injected into daily brief TL;DR prompt as additional context

### Infrastructure
- Shared Lambda layer rebuilt: v15 → v18
- daily-brief and daily-insight-compute updated to layer v18

---

## v4.7.6 — 2026-04-01: Self-updating site audit — remove stale dates, add auto-content

### Stale Date Removal
- `privacy/index.html`: "March 2026" → "April 2026"
- `builders/index.html`: "Five weeks later" → "Today it runs" (no time reference)
- `cost/index.html`: "since February 2026" → "since launch"
- `board/product/index.html`: "March 2026" → "Reviews quarterly"
- `field-notes/index.html`: "April 7, 2026" → "after the first full week"
- `explorer/index.html`: removed all "April 1, 2026" references
- `chronicle/sample/index.html`: "April 1/9, 2026" → relative language
- `first-person/index.html`: removed April 1 reference

### Chronicle Archive Auto-Render
- `chronicle/archive/index.html`: rewrote from hardcoded HTML to dynamic fetch from `/chronicle/posts.json`
- New posts auto-appear every Wednesday when Elena publishes — zero manual maintenance

### Explorer AI Commentary
- Added `explorer` expert to `ai-expert-analyzer` Lambda (Dr. Henning Brandt, biostatistician)
- Renders on `/explorer/` page when analysis exists — cross-domain correlation commentary
- Updated `site_api_lambda.py` to accept `explorer` query param
- Added to `components.js` renderAIAnalysisCard EXPERTS config

---

## v4.7.5 — 2026-04-01: AWS integration test fixes (19→2 failures)

- i1: DLQ consumer Lambda name mismatch fixed
- i6: EventBridge rule names updated to CDK-generated names
- i8: Removed `config/profile.json` expectation (profile lives in DynamoDB)
- i9: Purged 21 stale DLQ messages
- i12: Replaced deleted `get_data_freshness` tool probe with `get_weight_loss_progress`
- i13: Case-insensitive source name matching in freshness check
- AI expert analyzer switched from weekly to daily schedule ($0.80/month increase)
- Remaining 2: layer version drift (v15→v17), MCP canary (local key unavailable)

---

## v4.7.4 — 2026-04-01: Backlog cleanup — 6 items resolved

### HP-12: Elena Hero Line — CLOSED
- Already fully implemented (daily_brief → site_writer → public_stats.json → frontend). Removed from carry-forward lists.

### get_nutrition positional args bug — CLOSED
- 8 test cases written (`tests/test_get_nutrition_args.py`) covering all view dispatches. All pass. No bug reproducible.

### DISC-7: Annotation seeding — DONE
- MCP tools verified: `annotate_discovery` and `get_discovery_annotations` in `mcp/tools_social.py`
- `seeds/seed_discoveries.py` created (idempotent) — 4 Day 1 events seeded to DynamoDB
- Day 1 milestone annotation merges with journey_timeline correctly

### BL-02: Labs page — ALREADY DONE (prior session)
### BL-01: Builders page — ALREADY DONE (prior session)

### HP-13: Share card — DONE
- `twitter:image` updated to dynamic `og-home.png` (was static `og-image.png`)
- Share button added to homepage hero (Web Share API mobile, clipboard desktop)
- OG image Lambda (`og_image_lambda.py`) already generates 6 dynamic cards daily

---

## v4.7.3 — 2026-04-01: Launch readiness + MCP fix + test fixes

### Launch Readiness (LAUNCH_READINESS_IMPL_SPEC.md)
- Physical page: added `#obs-freshness` element + `initObsFreshness()` call (was the only observatory page missing it)
- Homepage: Inner Life card elevated with `★ FEATURED` badge, violet-tinted background, hover callout
- Homepage: "Made public because accountability needs an audience." added to `#amj-bio`
- Email welcome: plain-text welcome email replacing HTML template — "You're in. Here's what you just signed up for."

### MCP Lambda Fix (critical)
- `mcp/tools_measurements.py`: fixed import — `get_table`/`get_user_id` (nonexistent in `mcp.core`) → `table`/`USER_ID` from `mcp.config`
- MCP Lambda redeployed — resolves `slo-mcp-availability` alarm that had been firing continuously

### Stale Platform Stats
- Updated HTML fallback values 118→115 (tools) and 61→62 (Lambdas) in about, mission, platform, builders pages
- Updated meta description tags in platform page

### Test Fixes
- `ci/lambda_map.json`: added `site_api_ai_lambda.py` to `skip_deploy` (orphaned file test)
- `tests/test_secret_references.py`: added `notion`, `dropbox`, `site-api-ai-key` to KNOWN_SECRETS
- `tests/test_iam_secrets_consistency.py`: added `notion`, `dropbox` to KNOWN_SECRETS, updated count 11→13
- `ai_expert_analyzer_lambda.py`: wrapped handler in top-level try/except
- Test results: 19 failures → 0 local failures (8 AWS integration tests remain — infrastructure drift, not code bugs)

---

## v4.7.2 — 2026-04-01: Content review session — 15 editorial rewrites from Matthew

Full content audit and rewrite pass across 13 pages. All placeholder/AI-generated editorial text replaced with Matthew's own voice. Changes applied verbatim from Claude Chat review session.

### Pages Updated
- **Character** — pull-quote rewritten (RPG metaphor → personal data philosophy)
- **Habits** — hero subtitle rewritten (3 paragraphs on habit philosophy), removed duplicate streak description
- **Challenges** — hero subtitle and source descriptions rewritten (sandbox framing, Brittany collaboration)
- **Experiments** — hero subtitle refined, AI monitoring paragraph rewritten (informal experiments → scientific method)
- **Intelligence** — subtitle simplified, hardcoded sample Daily Brief replaced with API placeholder
- **Benchmarks** — fabricated VO2 max reflection replaced with deliberate trade-offs framing
- **Supplements** — hero subtitle rewritten (honest about methodology history)
- **Discoveries** — new paragraph inserted (intuition vs evidence)
- **Protocols** — two placeholder paragraphs replaced with 3-paragraph honest assessment
- **Methodology** — pull-quote rewritten ("My numbers won't tell you much about your body...")
- **Cost** — opener rewritten (approachability framing)
- **Mind** — hero subtitle simplified to one line
- **Nutrition** — Elena Voss pull-quote replaced with Matthew attribution
- **Sleep** — bed temperature pull-quote replaced with phone/doom-scrolling reflection
- **Glucose** — health anxiety narrative replaced with CGM curiosity framing, pending-data pull-quote replaced

---

## v4.7.1 — 2026-03-31: Editorial content pass — replace fabricated copy with real narrative

Replaced AI-fabricated placeholder copy across 8 pages with real, honest narrative sourced directly from Matthew's answers. No code logic changes — content-only edits to hero subtitles, intro blocks, pull quotes, and the Inner Life confessional.

### Pages Updated

**Sleep** (`site/sleep/index.html`)
- Hero subtitle: replaced fabricated "eight hours, no alarm, out like a light" with real story — sleep was never a problem, Matthew Walker got attention, Whoop/Eight Sleep surfaced onset time and alcohol's red-shift impact; the score keeps him accountable

**Nutrition** (`site/nutrition/index.html`)
- Intro block: 2017 turning point (relocation, MBA, promotion, mum getting sick), eating as coping/convenience not hunger, MacroFactor makes invisible visible
- Intro sub: lost 100lb before without tracking a calorie — it's about headspace not macros; when on it's second nature, when off even DoorDash breaks a streak

**Training** (`site/training/index.html`)
- Narrative pullquote: when in it you're all-in; the problem has never been training — it's the fall and how fast the void fills; data makes absence visible

**Physical** (`site/physical/index.html`)
- Corrected start weight: 302 lbs → **307 lbs**
- Hero subtitle: replaced "first honest conversation" with pattern-detector framing — scale data since 2011 shows disappear/reappear-at-high/drop/repeat; this page watches whether it breaks

**Inner Life** (`site/mind/index.html`)
- Hero subtitle: old relapses came from living (fun, parties, travel); recent ones can't be explained; this page is where he tries to understand
- Confessional (full rewrite, 4 paragraphs): real story — old relapses from abundance, recent disruptions from unknown source; intellectualizes over feels; never journaled, always powered through; not trying to return to old self but figuring out who he's becoming

**Labs** (`site/labs/index.html`)
- Elena Voss pull quote: replaced false "seven draws quarterly" with true story — used to get labs at the finish line when flattering; this week for the first time getting them at the starting line

**Supplements** (`site/supplements/index.html`)
- Hero para 2: replaced "podcast recommended" fiction with real process — trusts Rhonda Patrick and credentialed researchers as framework, occasionally experimental (lions mane, ashwaganda), goal is to be more methodical

**Discoveries** (`site/discoveries/index.html`)
- "What I'm Currently Testing": rewired from stale `/api/discoveries` to fetch live `/api/experiments` as source of truth (fallback to discoveries API); cards show days-in counter + link to experiments page; inner life section uses discData variable

### Deploy
- 8 S3 uploads, CloudFront invalidation `I5FR4CT201TTAZLM0D5DBR6INB`


## v1.1.0 — 2026-03-30: Character Engine Statistical Review (15 Findings)

Board-led statistical review by Dr. Henning Brandt and 8 panelists identified 14 findings + F-15 progressive difficulty. All implemented.

### Engine Changes (`lambdas/character_engine.py`)
- **F-01**: Confidence-weighted pillar scoring — blends toward neutral (50) when data is sparse instead of inflating from available-only components
- **F-02**: XP decays daily (−2/day) and acts as level stability buffer — high XP absorbs level-down pressure
- **F-03**: Per-pillar EMA smoothing rates — Sleep ~4-day half-life, Metabolic ~14-day half-life
- **F-04**: Body composition uses sigmoid curve (loss phase) + maintenance band scoring (±3lb)
- **F-05**: Cross-pillar effects use explicit `{"type":"multiplicative","value":N}` format — removes additive/multiplicative discontinuity
- **F-07**: Lab biomarker decay extends to 0 at 180 days (was floored at 0.5 forever)
- **F-09**: All "no data" defaults changed from 40.0 to 50.0 (true neutral)
- **F-10**: Variable step size: +2 levels per streak cycle when target−current > 10
- **F-11**: Equal-day streak hold — streaks no longer decay when target equals current
- **F-12**: Vice control uses logarithmic curve (day 7 ≈ 58pts vs old linear 23pts)
- **F-13**: `_in_range_score()` buffer uses range-span-based divisor
- **F-14**: Character level uses `math.floor()` instead of `round()`
- **F-15**: Progressive difficulty — Foundation 3-day streaks, Elite 14-day streaks

### Config (`config/character_sheet.json` v1.1.0)
- Added `baseline.weight_phase`, `maintenance_band_lbs`
- Added per-pillar `ema_lambda` values (0.85–0.95)
- Added `leveling.tier_streak_overrides` with 5 tiers
- Added XP decay/buffer config: `xp_per_level`, `daily_xp_decay`, `xp_buffer_threshold`
- Cross-pillar effects now use typed modifier format

### Character Page (`site/character/index.html`)
- Fixed methodology section: replaced incorrect "equal weights (14.3%)" with actual pillar weights
- Fixed "The Math": replaced fabricated `level = floor(sqrt(xp_total / 5))` formula with accurate 6-step explanation
- Updated tier descriptions with streak requirements
- Removed all references to "logarithmic XP curve"

### Tests
- Added `tests/test_character_engine.py` — 29 tests covering all findings

---


... [TRUNCATED — 717 lines omitted, 1117 total]


---

## 3. ARCHITECTURE

# Life Platform — Architecture

Last updated: 2026-04-04 (v4.9.0 — 121 MCP tools, 35-module MCP package, 26 data sources, 62 Lambdas, 72 site pages, 70+ API endpoints, 8 CDK stacks, shared layer v22)

---

## Overview

The life platform is a personal health intelligence system built on AWS. It ingests data from twenty-six sources (thirteen scheduled + one webhook + three manual/periodic + two MCP-managed + one State of Mind via webhook), normalises everything into a single DynamoDB table, and surfaces it to Claude through a Lambda-backed MCP server. The design philosophy is: get data in automatically, store it cheaply, and make it queryable without a data engineering background.

---

## Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  INGEST LAYER                                               │
│  Scheduled Lambdas (EventBridge) + S3 Triggers + Webhooks   │
│  Whoop · Withings · Strava · Eight Sleep · MacroFactor      │
│  Garmin · Apple Health · Habitify · Notion Journal          │
│  Health Auto Export (webhook — CGM/BP/SoM) · Weather        │
│  Supplements (MCP write) · Labs · DEXA · Genome (seeds)     │
└────────────────────────┬────────────────────────────────────┘
                         │ normalised records
┌────────────────────────▼────────────────────────────────────┐
│  STORE LAYER                                                │
│  S3 (raw) + DynamoDB (normalised, single-table)             │
└────────────────────────┬────────────────────────────────────┘
                         │ DynamoDB queries
┌────────────────────────▼────────────────────────────────────┐
│  SERVE LAYER                                                │
│  MCP Server Lambda (121 tools, 768 MB) + Lambda Function URL │
│  ← Claude Desktop + claude.ai + Claude mobile via remote MCP│
│                                                             │
│  COMPUTE LAYER (IC intelligence features)                   │
│  character-sheet-compute · adaptive-mode-compute            │
│  daily-metrics-compute · daily-insight-compute (IC-8)       │
│  hypothesis-engine v1.2.0 (IC-18+IC-19, Sunday 12 PM PT)   │
│  compute → store → read pattern: runs before Daily Brief    │
│                                                             │
│  EMAIL LAYER                                                │
│  monday-compass (Mon 7am) · daily-brief (10am)              │
│  wednesday-chronicle (Wed 7am) · weekly-plate (Fri 6pm)     │
│  weekly-digest (Sun 8am) · monthly-digest (1st Mon 8am)     │
│  nutrition-review (Sat 9am) · anomaly-detector (8:05am)     │
│  freshness-checker (9:45am) · insight-email-parser (S3 trig)│
│                                                             │
│  WEB LAYER                                                  │
│  averagejoematt.com (72 pages) · CloudFront → S3 /site      │
│  site-api Lambda (us-west-2): /api/ask · /api/board_ask     │
│  /api/verify_subscriber · /api/vitals · /api/journey        │
│  /api/character · /api/timeline · /api/correlations         │
│  dash.averagejoematt.com → S3 /dashboard (Lambda@Edge auth) │
│  blog.averagejoematt.com → S3 /blog (Elena Voss Chronicle)  │
│  buddy.averagejoematt.com → S3 /buddy (Tom accountability)  │
└─────────────────────────────────────────────────────────────┘
```

---

## AWS Resources

**Account:** 205930651321
**Primary region:** us-west-2

| Resource | Type | Name / ARN |
|---|---|---|
| DynamoDB table | NoSQL database | `life-platform` (deletion protection + PITR enabled) |
| S3 bucket | Object storage + static website | `matthew-life-platform` (static hosting on `dashboard/*`) |
| SQS queue | Dead-letter queue | `life-platform-ingestion-dlq` |
| Lambda Function URL (MCP) | MCP HTTPS endpoint | `https://votqefkra435xwrccmapxxbj6y0jawgn.lambda-url.us-west-2.on.aws/` (AuthType NONE — auth handled in Lambda via API key header) |
| Lambda Function URL (remote MCP) | Remote MCP HTTPS endpoint | `https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws` (OAuth 2.1 auto-approve + HMAC Bearer) |
| API Gateway | HTTP endpoint | `health-auto-export-api` (a76xwxt2wa) — webhook ingest |
| Secrets Manager | Credential store | 10 active secrets: 4 OAuth (`whoop`, `withings`, `strava`, `garmin`) + `eightsleep` + `ai-keys` (Anthropic + MCP) + `ingestion-keys` (Notion/Todoist/Habitify/Dropbox/webhook keys bundle) + `habitify` (dedicated) + `mcp-api-key` + `site-api-ai-key` (R17-04) — **`api-keys` permanently deleted 2026-03-14; `google-calendar` permanently deleted 2026-03-15 (ADR-030); `webhook-key` deleted 2026-03-14** |
| SNS topic | Alert routing | `life-platform-alerts` |
| CloudFront (amj) | CDN (public) | `E3S424OXQZ8NBE` (`d2qlzq81ggequb.cloudfront.net`) → site-api Lambda + S3 `/site`, alias `averagejoematt.com` |
| CloudFront (dash) | CDN + auth | `EM5NPX6NJN095` → S3 `/dashboard`, Lambda@Edge auth, alias `dash.averagejoematt.com` |
| CloudFront (blog) | CDN (public) | `E1JOC1V6E6DDYI` → S3 `/blog`, alias `blog.averagejoematt.com` |
| CloudFront (buddy) | CDN (public) | `ETTJ44FT0Z4GO` → S3 `/buddy`, alias `buddy.averagejoematt.com` |
| ACM Certificate | TLS | `arn:aws:acm:us-east-1:205930651321:certificate/e85e4b63-...` — `averagejoematt.com` (DNS-validated) |
| SES Receipt Rule Set | Inbound email routing | `life-platform-inbound` (active) — rule `insight-capture` routes `insight@aws.mattsusername.com` → S3 |
| CloudWatch | Alarms + logs | **~66 metric alarms**, all Lambdas monitored |
| CDK | Infrastructure as Code | `cdk/` — 8 stacks deployed. CDK owns all 62 Lambda IAM roles + ~50 EventBridge rules. |
| CloudTrail | Audit logging | `life-platform-trail` → S3 |
| AWS Budget | Cost guardrail | $20/mo cap, alerts at 25%/50%/100% |

---

## Ingest Layer

### Scheduled ingestion (EventBridge → Lambda)

Each source has its own dedicated Lambda and IAM role. EventBridge triggers fire hourly with a 10pm–4am PST maintenance window. All cron expressions use fixed UTC.

**Gap-aware backfill (v2.46.0):** All API-based ingestion Lambdas implement self-healing gap detection. On each run, the Lambda queries DynamoDB for the last N days (including today), identifies missing DATE# records, and fetches only those from the upstream API. Cost is ~$0/month — Lambdas short-circuit in <50ms when no new data exists.

**Schedule:** Hourly during active hours (4am–10pm PST) for most sources. Exceptions: Garmin at 4x daily (OAuth rate limits), Weather + Todoist at 2x daily (COST-OPT). Maintenance window: 10pm–4am PST (UTC 6–11 skipped).

**Shared Lambda Layer:** v22 — includes `ai_calls.py`, `board_loader.py`, `output_writers.py`, `scoring_engine.py`, `secret_cache.py`. Rebuild with `bash deploy/build_layer.sh`. 16 dependent Lambdas consume the layer.

**Secret caching (COST-OPT-1):** 15-min in-memory TTL cache via `secret_cache.py` in shared layer. Reduces Secrets Manager API calls ~90% across 9 Lambdas.

| Source | Lambda | Schedule | Type |
|---|---|---|---|
| Whoop | `whoop-data-ingestion` | Hourly (active hours) | API pull |
| Garmin | `garmin-data-ingestion` | 4x daily (cron 0 0,6,14,22) | API pull |
| Eight Sleep | `eightsleep-data-ingestion` | Hourly (active hours) | API pull |
| Withings | `withings-data-ingestion` | Hourly (active hours) | API pull |
| Habitify | `habitify-data-ingestion` | Hourly (active hours) | API pull |
| Strava | `strava-data-ingestion` | Hourly (active hours) | API pull |
| Todoist | `todoist-data-ingestion` | 2x daily | API pull |
| Notion Journal | `notion-journal-ingestion` | Hourly (active hours) | API pull |
| Weather | `weather-data-ingestion` | 2x daily | API pull |
| MacroFactor | `macrofactor-data-ingestion` | S3 trigger (Dropbox CSV) | File upload |
| Dropbox Poll | `dropbox-poll` | `rate(30 minutes)` | File poll |
| Journal Enrichment | `journal-enrichment` | Hourly | Compute |
| Activity Enrichment | `activity-enrichment` | Hourly | Compute |
| Apple Health (CGM, water, BP, SOM) | `health-auto-export-webhook` | Near real-time (webhook) | HAE push |

### Compute + Email Lambdas

| Function | Lambda | Cron (UTC) | PT (PDT) |
|---|---|---|---|
| Daily Insight Compute (IC-8) | `daily-insight-compute` | `cron(20 17 * * ? *)` | 10:20 AM |
| Daily Metrics Compute | `daily-metrics-compute` | `cron(25 17 * * ? *)` | 10:25 AM |
| Adaptive Mode Compute | `adaptive-mode-compute` | `cron(30 17 * * ? *)` | 10:30 AM |
| Character Sheet Compute | `character-sheet-compute` | `cron(35 17 * * ? *)` | 10:35 AM |
| Anomaly Detector | `anomaly-detector` | `cron(5 16 * * ? *)` | 09:05 AM |
| Daily Brief | `daily-brief` | `cron(0 18 * * ? *)` | 11:00 AM |
| Monday Compass | `monday-compass` | `cron(0 15 ? * MON *)` | Mon 08:00 AM |
| Wednesday Chronicle | `wednesday-chronicle` | `cron(0 15 ? * WED *)` | Wed 08:00 AM |
| The Weekly Plate | `weekly-plate` | `cron(0 2 ? * SAT *)` | Fri 07:00 PM |
| Weekly Digest | `weekly-digest` | `cron(0 16 ? * SUN *)` | Sun 09:00 AM |
| Nutrition Review | `nutrition-review` | `cron(0 17 ? * SAT *)` | Sat 10:00 AM |
| Monthly Digest | `monthly-digest` | `cron(0 16 ? * 1#1 *)` | 1st Mon 9:00 AM |
| Hypothesis Engine (IC-18) | `hypothesis-engine` | `cron(0 19 ? * SUN *)` | Sun 12:00 PM |
| Weekly Correlation Compute | `weekly-correlation-compute` | `cron(30 18 ? * SUN *)` | Sun 11:30 AM |

### File-triggered ingestion (S3 → Lambda)

| Source | Lambda | S3 Trigger Path |
|---|---|---|
| MacroFactor | `macrofactor-data-ingestion` | `uploads/macrofactor/*.csv` |
| Apple Health | `apple-health-ingestion` | `imports/apple_health/*.xml` |
| Insight Email | `insight-email-parser` | `raw/inbound_email/*` ObjectCreated |

### Webhook ingestion (API Gateway → Lambda)

| Source | Lambda | Endpoint |
|---|---|---|
| Health Auto Export | `health-auto-export-webhook` | `https://a76xwxt2wa.execute-api.us-west-2.amazonaws.com/ingest` |

### Failure handling

DLQ coverage: all async Lambdas → `life-platform-ingestion-dlq`. CloudWatch: **~66 alarms** total. Alarm actions → SNS `life-platform-alerts`.

Additional safeguards: DLQ Consumer Lambda, Canary Lambda (synthetic health check every 30 min), item size guard.

---

## Store Layer

### DynamoDB — normalised data

Table: `life-platform` (us-west-2) | Single-table | On-demand | Deletion protection | PITR (35-day) | TTL on `ttl`

```
PK: USER#matthew#SOURCE#<source>
SK: DATE#YYYY-MM-DD
```

**Key partitions:** whoop · day_grade · habit_scores · character_sheet · computed_metrics · platform_memory · insights · hypotheses · PROFILE#v1 · CACHE#matthew (TTL 26h)

---

## Serve Layer

### MCP Server

**Lambda:** `life-platform-mcp` | **Tools:** 121 | **Memory:** 768 MB | **Modules:** 35
**Remote MCP:** `https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws`
**Auth:** `x-api-key` header check + OAuth 2.1/HMAC Bearer for remote MCP

35-module package — see local project structure below.

Cold start: ~700–800ms. Warm: 23–30ms. Cached tools: <100ms.

### IC Intelligence Features (16 of 31 live)

Compute → store → read pattern. Standalone Lambdas run before Daily Brief, store results to DynamoDB.

**Live:** IC-1 (anomaly), IC-2 (training load), IC-3 (nutrition), IC-6 (CGM correlation), IC-7 (cross-pillar), IC-8 (intent vs execution), IC-15 (insights persistence), IC-16 (progressive context), IC-17 (readiness synthesis), IC-18 (hypothesis engine), IC-19 (N=1 experiments + slow drift + sustained anomaly), IC-23 (Character Sheet), IC-24 (adaptive mode), IC-25 (decisions), IC-29 (metabolic adaptation / deficit sustainability — TDEE divergence tracking, deployed v3.7.67), IC-30 (autonomic balance score — HRV + RHR + RR + sleep quality → 4-quadrant nervous system state, deployed v3.7.67).

**Data-gated next:** IC-4 (failure patterns, ~Apr 18), IC-5 (momentum warning, ~Apr 18), IC-26 (temporal mining, ~May), IC-27 (multi-resolution handoff, ~May).

### Site API Lambda (us-west-2)

**Lambda:** `life-platform-site-api` | **Stack:** LifePlatformOperational | **Region:** us-west-2 (R17-09 migration)
**Function URL:** Routed through CloudFront (E3S424OXQZ8NBE). Lambda confirmed in us-west-2 (verified via AWS CLI 2026-03-30).
**IAM:** Read-only — `dynamodb:GetItem, Query` + `kms:Decrypt` + `s3:GetObject` on `site/config/*`

**Routes served via CloudFront → site-api:**
- `GET /api/vitals` — weight, HRV, recovery (TTL 300s)
- `GET /api/journey` — weight trajectory, goal date (TTL 3600s)
- `GET /api/character` — pillar scores, level (TTL 900s)
- `GET /api/timeline` — weight history + events
- `GET /api/correlations` — pre-computed correlation pairs
- `GET /api/weight_progress` — 180-day weight series
- `GET /api/experiments` — N=1 experiment list
- `GET /api/current_challenge` — weekly challenge ticker
- `POST /api/ask` — AI Q&A (Haiku 4.5), 3 anon / 20 subscriber q/hr
- `POST /api/board_ask` — 6-persona board AI (Haiku 4.5), 5/hr IP limit
- `GET /api/verify_subscriber?email=` — HMAC token for subscriber gate (24hr)
- `POST /api/subscribe` — email subscriber capture

**Rate limiting:** In-memory sliding window (module-level dicts `_ask_rate_store`, `_board_rate_store`). No DDB writes — role is read-only by design (Yael directive, v3.7.82).

### Email / Intelligence cadence

| Lambda | Time (PDT) | Purpose |
|---|---|---|
| `anomaly-detector` | 9:05 AM daily | 15 metrics, CV-based Z thresholds |
| `daily-brief` | 11:00 AM daily | 18-section brief, 4 Haiku calls |
| `monday-compass` | Mon 8:00 AM | Forward-looking planning + Todoist |
| `wednesday-chronicle` | Wed 8:00 AM | Elena Voss narrative, blog + email |
| `weekly-plate` | Fri 7:00 PM | Food magazine column |
| `weekly-digest` | Sun 9:00 AM | 7-day summary, Board commentary |
| `nutrition-review` | Sat 10:00 AM | Deep Sonnet nutrition analysis |
| `hypothesis-engine` | Sun 12:00 PM | IC-18 hypothesis generation |

---

## IAM Security Model

Each Lambda has a **dedicated, least-privilege IAM role** (49 roles total as of v3.7.80, CDK-managed). No shared roles.

- **Ingestion roles (13):** DDB write, S3 write, Secrets read, SQS DLQ
- **MCP role:** DDB CRUD + S3 `config/*` + `raw/matthew/cgm_readings/*`
- **Email/digest roles (7):** DDB read/write, ai-keys, SES, S3 write
- **Compute roles (5):** DDB read/write, ai-keys
- **Operational roles (14):** scoped per function
- **Site API role:** DDB read-only (`GetItem, Query`), `kms:Decrypt`, S3 `site/config/*`, Secrets read (`site-api-ai-key` only) — **NO PutItem, NO Scan**
- No role has `dynamodb:Scan` or cross-account permissions

---

## Secrets Manager

**9 active secrets** at $0.40/month each = **~$3.60/month**

| Secret | Used By |
|---|---|
| `life-platform/whoop` | Whoop Lambda — OAuth2 tokens |
| `life-platform/withings` | Withings Lambda — OAuth2 tokens |
| `life-platform/strava` | Strava Lambda — OAuth2 tokens |
| `life-platform/garmin` | Garmin Lambda — garth OAuth tokens |
| `life-platform/eightsleep` | Eight Sleep Lambda — username + password |
| `life-platform/ai-keys` | All email/compute/MCP Lambdas — Anthropic API key + MCP bearer |
| `life-platform/ingestion-keys` | Notion, Todoist, Habitify, Dropbox, HAE webhook — COST-B bundle |
| `life-platform/habitify` | Habitify Lambda — dedicated key (ADR-014) |
| `life-platform/mcp-api-key` | MCP Key Rotator — bearer token (90-day auto-rotation) |
| `life-platform/site-api-ai-key` | Site API Lambda — dedicated Anthropic key (R17-04, isolated from main ai-keys) |
| ~~`life-platform/webhook-key`~~ | **DELETED 2026-03-14** |
| ~~`life-platform/google-calendar`~~ | **DELETED 2026-03-15 (ADR-030)** |
| ~~`life-platform/api-keys`~~ | **DELETED 2026-03-14** |

---

## Cost Profile

Target: under $25/month | Current: ~$13/month

| Driver | Monthly Cost |
|---|---|
| Secrets Manager (9 active secrets) | ~$3.60 |
| Lambda invocations (~2,000/mo) | ~$0.50 |
| DynamoDB (on-demand) | ~$1.00 |
| S3 (~2.5 GB + requests) | ~$0.50 |
| CloudFront (4 distributions) | ~$1.50 |
| CloudWatch (66 alarms + logs) | ~$2.00 |
| Anthropic API (Haiku + Sonnet) | ~$4.00 |
| **Total** | **~$13** |

---

## Local Project Structure

```
~/Documents/Claude/life-platform/
  mcp_server.py                   ← MCP Lambda entry point
  mcp_bridge.py                   ← Local MCP adapter (Claude Desktop → Lambda HTTPS)
  mcp/                            ← MCP server package (35 modules)
    handler.py, config.py, utils.py, core.py, helpers.py, warmer.py
    labs_helpers.py, strength_helpers.py, registry.py
    tools_sleep, tools_health, tools_training, tools_nutrition, tools_habits
    tools_cgm, tools_labs, tools_journal, tools_lifestyle, tools_social
    tools_strength, tools_correlation, tools_character, tools_board
    tools_decisions, tools_adaptive, tools_hypotheses, tools_memory
    tools_data, tools_todoist


... [TRUNCATED — 45 lines omitted, 345 total]


---

## 4. INFRASTRUCTURE REFERENCE

# Life Platform — Infrastructure Reference

> Quick-reference for all URLs, IDs, and configuration. No secrets stored here.
> Last updated: 2026-04-04 (v4.9.0 — 62 Lambdas, 10 active secrets, 121 MCP tools, ~66 alarms)

---

## AWS Account

| Field | Value |
|-------|-------|
| Account ID | `205930651321` |
| Region | `us-west-2` (Oregon) |
| Budget | $20/month (alerts at 25% / 50% / 100%) |
| CloudTrail | `life-platform-trail` → S3 |

---

## Domain & DNS

| Field | Value |
|-------|-------|
| Domain | `averagejoematt.com` |
| Registrar | *(check where you bought the domain — Namecheap, Google Domains, etc.)* |
| Hosted Zone ID | `Z063312432BPXQH9PVXAI` |
| Nameservers | `ns-214.awsdns-26.com` · `ns-1161.awsdns-17.org` · `ns-858.awsdns-43.net` · `ns-1678.awsdns-17.co.uk` |

### DNS Records

| Subdomain | Type | Target |
|-----------|------|--------|
| `dash.averagejoematt.com` | A (alias) | `d14jnhrgfrte42.cloudfront.net` |
| `blog.averagejoematt.com` | A (alias) | `d1aufb59hb2r1q.cloudfront.net` |
| `buddy.averagejoematt.com` | A (alias) | `d1empeau04e0eg.cloudfront.net` |

---

## Web Properties

| Property | URL | Auth | CloudFront ID |
|----------|-----|------|---------------|
| Public Site | `https://averagejoematt.com/` | None (public) | `E3S424OXQZ8NBE` |
| Dashboard | `https://dash.averagejoematt.com/` | Lambda@Edge password (`life-platform-cf-auth`) | `EM5NPX6NJN095` |
| Blog | `https://blog.averagejoematt.com/` | None (public) | `E1JOC1V6E6DDYI` |
| Buddy Page | `https://buddy.averagejoematt.com/` | None (public — Tom's accountability page, no PII) | `ETTJ44FT0Z4GO` |

Dashboard and Buddy passwords are stored in **Secrets Manager** (not here).

---

## MCP Server

| Field | Value |
|-------|-------|
| Lambda | `life-platform-mcp` (768 MB) |
| Function URL (remote) | `https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws/` |
| Auth (remote) | HMAC Bearer token via `life-platform/mcp-api-key` secret (auto-rotates every 90 days) |
| Auth (local) | `mcp_bridge.py` → `.config.json` → Function URL |
| Tools | 121 across 35 modules |
| Cache warmer | 14 tools pre-computed nightly at 9:00 AM PT |

---

## API Gateway

| Field | Value |
|-------|-------|
| Name | `health-auto-export-api` |
| ID | `a76xwxt2wa` |
| Endpoint | `https://a76xwxt2wa.execute-api.us-west-2.amazonaws.com` |
| Purpose | Webhook ingestion for Health Auto Export (Apple Health CGM, BP, State of Mind) |

---

## S3

| Field | Value |
|-------|-------|
| Bucket | `matthew-life-platform` |
| Key prefixes | `raw/` (source data) · `site/` (public website — 72 pages) · `dashboard/` (web dashboard) · `blog/` (Chronicle) · `buddy/` (accountability page) · `config/` (profile, board, character sheet) · `inbound-email/` (insight parser) · `uploads/` (MacroFactor CSVs) · `imports/` (Apple Health XML) · `avatar/` (pixel art sprites) |

---

## DynamoDB

| Field | Value |
|-------|-------|
| Table | `life-platform` |
| Key schema | PK: `USER#matthew#SOURCE#<source>` · SK: `DATE#YYYY-MM-DD` |
| Protection | Deletion protection ON · PITR enabled (35-day rolling) |
| Encryption | KMS CMK `alias/life-platform-dynamodb` (key `444438d1-a5e0-43b8-9391-3cd2d70dde4d`) · annual auto-rotation ON |
| Partitions (30) | whoop, eightsleep, garmin, strava, withings, habitify, macrofactor, apple_health, notion_journal, todoist, weather, supplements, cgm, labs, genome, dexa, day_grade, habit_scores, character_sheet, chronicle, coaching_insights, life_events, contacts, temptations, cold_heat_exposure, exercise_variety, adaptive_mode, platform_memory, insights, hypotheses |

---

## SES (Email)

| Field | Value |
|-------|-------|
| Sender / Recipient | `awsdev@mattsusername.com` |
| Inbound rule set | `life-platform-inbound` (active) |
| Inbound rule | `insight-capture` → routes `insight@aws.mattsusername.com` → S3 |

---

## SNS

| Field | Value |
|-------|-------|
| Alert topic | `life-platform-alerts` → email to `awsdev@mattsusername.com` |
| CloudWatch alarms | ~66 metric alarms (ALARM-only; base + invocation-count + DDB item size + canary + duration + freshness + pipeline health) |

---

## SQS

| Field | Value |
|-------|-------|
| Dead-letter queue | `life-platform-ingestion-dlq` |
| DLQ coverage | All ingestion Lambdas (MCP + webhook excluded — request/response pattern) |

---

## ACM Certificates (us-east-1, required by CloudFront)

| Domain | Purpose |
|--------|---------|
| `dash.averagejoematt.com` | Dashboard CloudFront |
| `blog.averagejoematt.com` | Blog CloudFront |
| `buddy.averagejoematt.com` | Buddy CloudFront |

All DNS-validated via Route 53 CNAME records.

---

## Secrets Manager (10 active secrets)

All under prefix `life-platform/`. No values stored in this doc — access via AWS console or CLI.

| Secret | Type | Fields / Notes |
|--------|------|----------------|
| `whoop` | OAuth | Auto-refreshed by Lambda |
| `eightsleep` | OAuth | Auto-refreshed by Lambda |
| `strava` | OAuth | Auto-refreshed by Lambda |
| `withings` | OAuth | Auto-refreshed by Lambda |
| `garmin` | Session | Auto-refreshed by Lambda |
| `ai-keys` | JSON bundle | `anthropic_api_key` + `mcp_api_key` (90-day auto-rotation) |
| `ingestion-keys` | JSON bundle | `notion_api_key` + `todoist_api_key` + `habitify_api_key` + `dropbox_app_key` + `health_auto_export_api_key`. COST-B pattern — single secret, per-service key fields. |
| `habitify` | API key | Dedicated Habitify API token. Also present in `ingestion-keys` — see ADR-014 for governing principle. |
| `mcp-api-key` | Rotation target | MCP server bearer token consumed by `ai-keys`. 90-day auto-rotation via `life-platform-key-rotator`. |
| `site-api-ai-key` | API key | Subscriber validation key for site-api-ai Lambda (ADR-041). |

**Deleted secrets (historical):** See ADR-030, ADR-014 for retirement decisions.

---

## Lambdas (62)

60 CDK-managed (us-west-2) + 2 Lambda@Edge (us-east-1)

### Ingestion (16)
`whoop-data-ingestion` · `eightsleep-data-ingestion` · `garmin-data-ingestion` · `strava-data-ingestion` · `withings-data-ingestion` · `habitify-data-ingestion` · `macrofactor-data-ingestion` · `notion-journal-ingestion` · `todoist-data-ingestion` · `weather-data-ingestion` · `health-auto-export-webhook` · `apple-health-ingestion` · `journal-enrichment` · `activity-enrichment` · `food-delivery-ingestion` · `measurements-ingestion`

### Email / Digest (11)
`daily-brief` · `weekly-digest` · `monthly-digest` · `nutrition-review` · `wednesday-chronicle` · `weekly-plate` · `monday-compass` · `anomaly-detector` · `evening-nudge` · `chronicle-email-sender` · `subscriber-onboarding`

### Compute (12)
`character-sheet-compute` · `adaptive-mode-compute` · `daily-metrics-compute` · `daily-insight-compute` · `hypothesis-engine` · `weekly-correlation-compute` · `acwr-compute` · `sleep-reconciler` · `circadian-compliance` · `ai-expert-analyzer` · `journal-analyzer` · `field-notes-generate`

> **Skeleton Lambdas (source written, NOT yet CDK-wired or EventBridge-scheduled — activate ~2026-05-01):**
> `failure-pattern-compute` (IC-4, `lambdas/failure_pattern_compute_lambda.py`) · `momentum-warning-compute` (IC-5, `lambdas/momentum_warning_compute_lambda.py`)

### Infrastructure / Operational (21)
`life-platform-freshness-checker` · `dropbox-poll` · `insight-email-parser` · `life-platform-key-rotator` · `dashboard-refresh` · `life-platform-data-export` · `life-platform-qa-smoke` · `life-platform-mcp` · `life-platform-mcp-warmer` · `dlq-consumer` · `life-platform-canary` · `data-reconciliation` · `pip-audit` · `brittany-weekly-email` · `life-platform-site-api` · `site-stats-refresh` · `challenge-generator` · `og-image-generator` · `email-subscriber` · `pipeline-health-check` · `chronicle-approve`

### Lambda@Edge (us-east-1) — manually managed, outside CDK
`life-platform-cf-auth` — attached to dashboard CloudFront (`EM5NPX6NJN095`), password-gates `dash.averagejoematt.com`
`life-platform-buddy-auth` — function exists but buddy CloudFront runs **without auth** (intentionally public; see Web Properties table)

---

## EventBridge

All rules CDK-managed as of v3.4.0 (PROD-1). IAM role: `life-platform-scheduler-role`.

| Field | Value |
|-------|-------|
| Timezone | `America/Los_Angeles` (DST-safe) |
| Schedules | 50+ total (see PROJECT_PLAN.md Ingestion Schedule for timing) |
| Old manual rules | Deleted in v3.4.0 migration |

---

## KMS

| Field | Value |
|-------|-------|
| Key alias | `alias/life-platform-dynamodb` |
| Key ID | `444438d1-a5e0-43b8-9391-3cd2d70dde4d` |
| Key ARN | `arn:aws:kms:us-west-2:205930651321:key/444438d1-a5e0-43b8-9391-3cd2d70dde4d` |

... [TRUNCATED — 36 lines omitted, 236 total]


---

## 5. ARCHITECTURE DECISIONS (ADRs)

## ADR Index

| # | Title | Status | Date |
|---|-------|--------|------|
| ADR-001 | Single-table DynamoDB design | ✅ Active | 2026-02-23 |
| ADR-002 | Lambda Function URL over API Gateway for MCP | ✅ Active | 2026-02-23 |
| ADR-003 | MCP over REST API for Claude integration | ✅ Active | 2026-02-24 |
| ADR-004 | Source-of-truth domain ownership model | ✅ Active | 2026-02-25 |
| ADR-005 | No GSI on DynamoDB table | ✅ Active | 2026-02-25 |
| ADR-006 | DynamoDB on-demand billing over provisioned | ✅ Active | 2026-02-25 |
| ADR-007 | Lambda memory 1024 MB over provisioned concurrency | ✅ Active | 2026-02-26 |
| ADR-008 | No VPC — public Lambda endpoints with auth | ✅ Active | 2026-02-27 |
| ADR-009 | CloudFront + S3 static site over server-rendered dashboard | ✅ Active | 2026-02-27 |
| ADR-010 | Reserved concurrency over WAF | ✅ Active | 2026-02-28 |
| ADR-011 | Whoop as sleep SOT over Eight Sleep | ✅ Active | 2026-03-01 |
| ADR-012 | Board of Directors as S3 config, not code | ✅ Active | 2026-03-01 |
| ADR-013 | Shared Lambda Layer for common modules | ✅ Active | 2026-03-05 |
| ADR-014 | Secrets Manager consolidation — dedicated vs. bundled principle | ✅ Active | 2026-03-05 |
| ADR-015 | Compute→Store→Read pattern for intelligence features | ✅ Active | 2026-03-06 |
| ADR-016 | platform_memory DDB partition over vector store | ✅ Active | 2026-03-07 |
| ADR-017 | No fine-tuning — prompt + context engineering instead | ✅ Active | 2026-03-07 |
| ADR-018 | CDK for IaC over Terraform | ✅ Active | 2026-03-09 |
| ADR-019 | SIMP-2 ingestion framework: adopt for new Lambdas, skip migration of existing | ✅ Active | 2026-03-09 |
| ADR-020 | MCP tool functions BEFORE TOOLS={} dict | ✅ Active | 2026-02-26 |
| ADR-021 | EventBridge rule naming convention (CDK) | ✅ Active | 2026-03-10 |
| ADR-022 | CoreStack scoping — shared infrastructure vs. per-stack resources | ✅ Active | 2026-03-10 |
| ADR-023 | Sick day checker as shared utility, not standalone Lambda | ✅ Active | 2026-03-10 |
| ADR-024 | DLQ consumer: schedule-triggered vs SQS event source mapping | ✅ Active | 2026-03-14 |
| ADR-025 | composite_scores vs computed_metrics: consolidate into computed_metrics | ✅ Active | 2026-03-14 |
| ADR-026 | Local MCP endpoint: AuthType NONE + in-Lambda API key check (accepted) | ✅ Active | 2026-03-14 |
| ADR-027 | MCP two-tier structure: stable core → Layer, volatile tools → Lambda zip | ✅ Active | 2026-03-14 |
| ADR-028 | Integration tests as quality gate: test-in-AWS after every deploy | ✅ Active | 2026-03-14 |
| ADR-029 | MCP monolith: retain single Lambda, revisit at 100+ calls/day | ✅ Active | 2026-03-15 |
| ADR-030 | Google Calendar integration: retired — no viable zero-touch data path | ✅ Active | 2026-03-15 |
| ADR-031 | MCP Lambda deploy: always use full zip build (guard in deploy_lambda.sh) | ✅ Active | 2026-03-15 |
| ADR-032 | S3 bucket policy: Deny DeleteObject on data prefixes for deploy user | ✅ Active | 2026-03-16 |
| ADR-033 | Safe S3 sync: wrapper function with dryrun gate and root-block | ✅ Active | 2026-03-16 |
| ADR-034 | Website content consistency architecture (component system + constants) | ✅ Active | 2026-03-24 |
| ADR-035 | SIMP-1 tool consolidation: view-dispatchers over standalone tools | ✅ Active | 2026-03-09 |
| ADR-036 | 3-layer status monitoring architecture | ✅ Active | 2026-03-29 |
... [SECTION TRUNCATED at 40 lines]

---

## 6. SLOs

# Life Platform — Service Level Objectives (SLOs)

> OBS-3: Formal SLO definitions for critical platform paths.
> Last updated: 2026-04-04 (v4.9.0)

---

## Overview

Four SLOs define the platform's reliability contract. Each SLO has a measurable Service Level Indicator (SLI), a target, and a CloudWatch alarm that fires on breach.

All SLO alarms publish to `life-platform-alerts` SNS topic. The operational dashboard (`life-platform-ops`) includes an SLO tracking widget section.

---

## SLO Definitions

### SLO-1: Daily Brief Delivery

| Field | Value |
|-------|-------|
| **SLI** | Daily Brief Lambda completes without error |
| **Target** | 99% (≤3 missed days per year) |
| **Window** | Rolling 30-day |
| **Alarm** | `slo-daily-brief-delivery` — fires if Daily Brief Lambda errors ≥1 in a 24-hour period |
| **Metric** | `AWS/Lambda::Errors` for `daily-brief`, Sum, 24h period |
| **Recovery** | Check CloudWatch logs → fix code or data issue → re-invoke manually |

**Why 99% not 99.9%:** Single-user platform with no revenue SLA. 99% allows for the occasional bad deploy or upstream API outage without false-alarming. One missed day is annoying, not dangerous.

---

### SLO-2: Data Source Freshness

| Field | Value |
|-------|-------|
| **SLI** | Number of monitored data sources with data older than 48 hours |
| **Target** | 99% of checks show 0 stale sources |
| **Window** | Rolling 30-day |
| **Alarm** | `slo-source-freshness` — fires if `StaleSourceCount > 0` for 2 consecutive checks |
| **Metric** | `LifePlatform/Freshness::StaleSourceCount`, custom metric emitted by `freshness_checker_lambda.py` |
| **Recovery** | Identify stale source → check ingestion Lambda logs → fix auth/API issue → manually invoke |

**Monitored sources (13):** Whoop, Withings, Strava, Todoist, Apple Health, Eight Sleep, MacroFactor, Garmin, Habitify, Notion Journal, Weather, Food Delivery (90-day threshold), Measurements.
**Note:** Labs, DEXA, and Genome are periodic/manual — not subject to 48h freshness SLO. Food Delivery uses a 90-day stale threshold instead of 48h.

**Why 48h threshold:** Many sources only sync once daily. A 24h threshold would false-alarm on normal timezone drift. 48h catches genuine failures while tolerating expected gaps (e.g., no MacroFactor data on a day Matthew doesn't log food).

---

### SLO-3: MCP Availability

| Field | Value |
|-------|-------|
| **SLI** | MCP Lambda invocations that complete without error |
| **Target** | 99.5% |
| **Window** | Rolling 7-day |
| **Alarm** | `slo-mcp-availability` — fires if MCP Lambda error rate exceeds 0.5% over 1 hour |
| **Metric** | `AWS/Lambda::Errors` / `AWS/Lambda::Invocations` for `life-platform-mcp` |
| **Recovery** | Check CloudWatch logs → redeploy from last-known-good code |

**Why 99.5%:** MCP is the interactive query layer — errors directly block Claude from answering questions. Higher bar than batch email Lambdas.

**Cold start note:** Cold starts (~700-800ms) are not errors. The SLI measures availability (error-free completion), not latency. A separate informational metric tracks p95 duration.

---

### SLO-4: AI Coaching Success

| Field | Value |
|-------|-------|
| **SLI** | Anthropic API calls that return a valid response |
| **Target** | 99% |
| **Window** | Rolling 7-day |
| **Alarm** | `slo-ai-coaching-success` — fires if `AnthropicAPIFailure` count exceeds 2 in a 24-hour period |
| **Metric** | `LifePlatform/AI::AnthropicAPIFailure` (already emitted by `ai_calls.py`) |
| **Recovery** | Check Anthropic status page → if upstream outage, wait. If code issue, fix prompt/parsing |

**Why count-based not rate-based:** The platform makes ~15-20 AI calls/day across all Lambdas. A rate-based alarm with so few datapoints would be noisy. A count threshold of 2 failures/day means something is systematically wrong (not just a transient 429).

---

## CloudWatch Dashboard Widgets

The `life-platform-ops` dashboard includes an "SLO Health" section with:

1. **SLO Status Panel** — 4 metric widgets showing current alarm states
2. **Daily Brief Success Rate** — 30-day graph of daily-brief errors
3. **Source Freshness Trend** — 30-day graph of stale source count
4. **MCP Error Rate** — 7-day graph of MCP error count
5. **AI Failure Trend** — 7-day graph of Anthropic API failures

---

## SLO Review Cadence

- **Weekly:** Glance at ops dashboard SLO section during Weekly Digest review
- **Monthly:** Review any SLO breaches in Monthly Digest (future integration)
- **Quarterly:** Review whether SLO targets need adjustment based on platform growth


... [TRUNCATED — 12 lines omitted, 112 total]


---

## 7. INCIDENT LOG

# Life Platform — Incident Log

Last updated: 2026-04-04 (v4.9.0)

> Tracks operational incidents, outages, and bugs that affected data flow or system behavior.
> For full details on any incident, check the corresponding CHANGELOG entry or handover file.

---

## Severity Levels

| Level | Definition |
|-------|------------|
| **P1 — Critical** | System broken, no data flowing or MCP completely down |
| **P2 — High** | Major feature broken, data loss risk, or multi-day data gap |
| **P3 — Medium** | Single source affected, degraded but functional |
| **P4 — Low** | Cosmetic, minor data quality, or transient error |

---

## Incident History

| Date | Severity | Summary | Root Cause | TTD* | TTR* | Data Loss? |
|------|----------|---------|------------|------|------|------------|
| 2026-03-16 | **P1** | **S3 bucket wipe — 35,188 objects deleted across all prefixes.** Deploy script `deploy_v3756_restore_signal_homepage.sh` ran `aws s3 sync --delete` from 17-file website dir to bucket root, deleting entire raw data archive (34,221 files, 2009–2026), config (24), deploys (25), dashboard (56), CloudTrail (753), exports (24), uploads/macrofactor (26), and 7 other prefixes. DynamoDB untouched. | One-off deploy script synced to `s3://$BUCKET/` (bucket root) instead of `s3://$BUCKET/site/`. The `--delete` flag treated all non-website objects as orphans. Canonical `sync_site_to_s3.sh` correctly uses `S3_PREFIX="site"` — the one-off script bypassed this. | Immediate (operator noticed deletions streaming in terminal) | ~2 hours. Full recovery via S3 versioning — delete markers removed with batch Python script. All 35,273 objects confirmed restored. | **No — full recovery.** S3 versioning was enabled pre-incident. All objects recovered by removing delete markers. Verified: `raw/` = 34,222, all other prefixes match forensic counts. |
| 2026-03-19 | **P2** | Eight Sleep data ingestion down for 10 days | `logger.set_date` crash — Lambda had stale bundled `platform_logger.py` missing `set_date()` method. Same class of bug as 2026-03-09 P2 incident but on a Lambda not redeployed in v3.3.8 batch fix. | 10 days (discovered during pipeline validation session) | ~30 min (hasattr guard + redeploy + re-auth after password change). 7 days backfilled. | No — backfill recovered missing data |
| 2026-03-19 | **P2** | Dropbox secret deleted — MacroFactor nutrition chain silently broken since Mar 10 | Secret `life-platform/ingestion-keys` scheduled for deletion (7-day recovery window expired). Dropbox poll Lambda couldn't read credentials → MacroFactor CSV never downloaded → nutrition data stopped. Undetected 9 days. | 9 days (discovered during pipeline validation session) | ~15 min (restored secret from deletion recovery) | No — MacroFactor data backfilled after restore |
| 2026-03-19 | **P3** | Notion secret deleted — journal ingestion silently broken | Same pattern as Dropbox: secret scheduled for deletion and not caught. Notion journal entries stopped ingesting. | Days (discovered during pipeline validation) | ~10 min (restored secret) | No — re-ingested after restore |
| 2026-03-19 | **P3** | Health Auto Export webhook Lambda crash | `logger.set_date` bug — same root cause as Eight Sleep. Lambda redeployed with stale platform_logger.py. | Days (discovered during pipeline validation) | ~15 min (redeploy with current code) | No — webhook data in S3, reprocessed |
| 2026-03-19 | **P3** | Garmin ingestion broken — missing modules + expired tokens | garth/garminconnect modules missing from Lambda package. OAuth tokens expired. | Days (discovered during pipeline validation) | Partial — layer published (garth-layer:2), auth pending due to Garmin SSO rate limiting | Garmin data gap — auth retry pending |
| 2026-03-12 | **P3** | Mar 12 alarm storm — 20+ ALARM/OK emails in 24h across todoist, daily-insight-compute, failure-pattern-compute, monday-compass, DLQ, freshness | CDK drift: `TodoistIngestionRole` missing `s3:PutObject` on `raw/todoist/*`. Policy correct in `role_policies.py` but never applied to AWS (likely stale from COST-B bundling refactor). Todoist Lambda threw `AccessDenied` on every invocation → cascading staleness alarms. | Alarm emails (real-time) | ~1 day (detected next session) — `cdk deploy LifePlatformIngestion` (54s) | No — Todoist data gap Mar 12 only. No backfill attempted (single day, non-critical). |
| 2026-03-12 | **P4** | `freshness_checker_lambda.py` duplicate sick-day suppression block silently breaking sick-day alert suppression | Copy-paste bug: sick-day block duplicated, second copy reset `_sick_suppress = False` after first set it `True`. Suppression never fired on sick days. | Code review during incident investigation | Fixed in v3.7.10 — awaiting deploy |
| 2026-02-28 | **P1** | 5 of 6 API ingestion Lambdas failing after engineering hardening (v2.43.0) | Handler mismatches (4 Lambdas had `lambda_function.py` but handlers pointed to `X_lambda.lambda_handler`), Garmin missing deps + IAM, Withings cascading OAuth expiry | ~hours (next scheduled run) | ~2 hr (sequential fixes) | No — gap-aware backfill self-healed all missing data. Full PIR: `docs/PIR-2026-02-28-ingestion-outage.md` |
| 2026-03-04 | P3 | character-sheet-compute failing with AccessDenied on S3 + DynamoDB | IAM role missing s3:GetObject on config bucket and dynamodb:PutItem permission. Lambda silently failing since deployment | ~1 day | 30 min | No (compute re-run via backfill) |
| 2026-02-25 | P4 | Day grade zero-score — journal and hydration dragging grades down | `score_journal` returned 0 instead of None when no entries; hydration noise <118ml scored | 1 day | 20 min | No (grades recalculated) |
| 2026-02-25 | P3 | Strava multi-device duplicate activities inflating movement score | WHOOP + Garmin recording same walk → duplicate in Strava | ~days | 30 min | No (dedup applied in brief; raw data retained) |
| 2026-03-10 | **P2** | All three web URLs (dash/blog/buddy) showing TLS cert error — `ERR_CERT_COMMON_NAME_INVALID` | `web_stack.py` had `CERT_ARN_* = None` placeholders — CDK deployed distributions without `viewer_certificate`, causing CloudFront to serve default `*.cloudfront.net` cert. Introduced during PROD-1 (v3.3.5). | Hours (noticed by user) | 15 min (v3.4.9) | No (data unaffected; all URLs inaccessible via HTTPS) |
| 2026-03-08 | **P3** | `todoist-data-ingestion` failing since 2026-03-06 | Stale `SECRET_NAME` env var (`life-platform/api-keys`) set on the Lambda — when api-keys was soft-deleted as part of secrets decomposition, the env var override started producing `ResourceNotFoundException`. Code default was correct but env var took precedence. DLQ consumer caught accumulated failures at 9:15 AM on 2026-03-08. | ~2 days | 15 min (env var removed + Lambda redeployed) | No — Todoist ingestion gap 2026-03-06 to 2026-03-08. Gap-aware backfill (7-day lookback) self-healed all missing task records on next run. |
| 2026-03-08 | **Info** | `data-reconciliation` first run reported RED: 17 gaps across 6 sources | Bootstrap noise, not real failures. First run has no prior reference point — all "gaps" were expected coldstart artifacts (MacroFactor real data only from 2026-02-22, habit gap 2025-11-10→2026-02-22, etc.). | First run | No action needed — monitor next 3 runs for convergence to GREEN | No |
| 2026-03-09 | **P2** | All 23 CDK-managed Lambdas broken after first CDK deploy (PROD-1, v3.3.5) | `Code.from_asset("..")` bundles files at `lambdas/X.py` inside a subdirectory, but Lambda expects `X.py` at zip root — causing `ImportModuleError` on every invocation. Affected: 7 Compute + 8 Email + 1 MCP + 7 Operational Lambdas. | Next scheduled run post-deploy | ~1 hr (`deploy/redeploy_all_cdk_lambdas.sh` redeployed all 23 via `deploy_lambda.sh`) | No — gap-aware backfill + DLQ drained. Permanent fix: update `lambda_helpers.py` to `Code.from_asset("../lambdas")` (tracked as TODO) |
| 2026-03-10 | **P1** | CDK IAM bulk migration — Lambda execution role gap during v3.4.0 deploy | CDK deleted 39 old IAM roles before confirming CDK-managed replacement roles were fully propagated and attached. Two email Lambdas (`wednesday-chronicle`, `nutrition-review`) had no execution role for ~5 min during the migration window, causing invocation failures on any warmup or invocation in that window. Root fix: `cdk deploy` sequencing — always verify role attachment before deleting old roles. *Identified retroactively during Architecture Review #4.* | Deploy logs (real-time) | ~15 min (CDK re-apply with `--force`) | No — no scheduled runs in migration window |
| 2026-03-10 | **P2** | CoreStack SQS DLQ ARN changed on CDK-managed recreation — DLQ send failures across all async Lambdas | CoreStack created a new CDK-managed DLQ (`life-platform-ingestion-dlq`) with a different ARN than the manually-created original. CDK-deployed Lambda env vars referenced the new ARN, but 3 Lambdas that had the old ARN cached in env var overrides (`SECRET_NAME`-style pattern) continued sending to the deleted queue. Result: DLQ send failures and silent dead-letter drop for ~30 min. *Identified retroactively during Architecture Review #4.* | CloudWatch errors (~30 min lag) | CDK update pushed correct ARN to all Lambda configs | Possible: some DLQ messages lost during gap window |
| 2026-03-10 | **P3** | EB rule recreation gap: 2 ingestion Lambdas missed scheduled morning runs during v3.4.0 migration | Old EventBridge rules deleted first; CDK replacements deployed after. 2 ingestion Lambdas (`withings-data-ingestion`, `eightsleep-data-ingestion`) missed their 7:15 AM / 8:00 AM PT windows during ~10 min gap between deletion and CDK rule creation. *Identified retroactively during Architecture Review #4.* | Freshness checker alert (10:45 AM) | Gap-aware backfill self-healed on next scheduled run | No — backfill recovered all missing data |
| 2026-03-10 | **P3** | Orphan Lambda adoption: `failure-pattern-compute` Sunday EB rule not included in CDK Compute stack definition | When 3 orphan Lambdas were adopted into CDK (v3.4.0), the `failure-pattern-compute` Sunday 9:50 AM EventBridge rule was omitted from the Compute stack definition. Lambda did not execute for ~1 week (one missed Sunday run). *Identified retroactively during Architecture Review #4.* | Architecture Review #4 inspection | EB rule added to CDK Compute stack | No — failure pattern memory records simply not generated for that week |
| 2026-03-10 | **P4** | Duplicate CloudWatch alarms after CDK Monitoring stack adoption of orphan Lambdas | CDK Monitoring stack created new alarms for 3 newly-adopted Lambdas (`failure-pattern-compute`, `brittany-email`, `sick-day-checker`) that already had manually-created alarms — resulting in 9 duplicate alarms with overlapping SNS notifications and alert fatigue. *Identified retroactively during Architecture Review #4.* | Architecture Review #4 alarm audit | Manual alarms deleted; CDK alarms authoritative | No |
| 2026-03-09 | **P2** | All 13 ingestion Lambdas failing with `AttributeError: 'Logger' object has no attribute 'set_date'` | After `platform_logger.py` added `set_date()` to support OBS-1 structured logging, ingestion Lambdas had stale bundled copies of `platform_logger.py` missing the new method. 14 DLQ messages accumulated. Affected: whoop, eightsleep, withings, strava, todoist, macrofactor, garmin, habitify, notion, journal-enrichment, dropbox-poll, weather, activity-enrichment. | DLQ depth alarm + CloudWatch errors | ~30 min (`deploy/redeploy_ingestion_with_logger.sh` redeployed all 13 with `--extra-files lambdas/platform_logger.py`). DLQ purged in v3.3.8. | No — gap-aware backfill recovered all ingestion gaps. |
| 2026-02-25 | P4 | Daily brief IAM — day grade PutItem AccessDeniedException | `lambda-weekly-digest-role` missing `dynamodb:PutItem` | Since v2.20.0 | 10 min | Grades not persisted until fixed |
| 2026-02-24 | P2 | Apple Health data not flowing — 2+ day gap | Investigated wrong Lambda (`apple-health-ingestion` vs `health-auto-export-webhook`) + deployment timing | ~2 days | 4 hr investigation, 15 min actual fix | No (S3 archives preserved, backfill recovered) |
| 2026-02-24 | P3 | Garmin Lambda pydantic_core binary mismatch | Wrong platform binary in deployment package | 1 day | 30 min | No |
| 2026-02-24 | P3 | Garmin data gap (Jan 19 – Feb 23) | Garmin app sync issue (Battery Saver mode suspected) | ~5 weeks | Backfill script | Partial (gap backfilled from Feb 23 forward) |
| 2026-02-23 | P4 | Habitify alarm in ALARM state | Transient Lambda networking error ("Cannot assign requested address") | Hours | Manual alarm reset | No (re-invoked successfully) |
| 2026-02-23 | P4 | DynamoDB TTL field name mismatch | Cache using `ttl_epoch` but TTL configured on `ttl` attribute | ~1 day | 5 min | No (cache items never expired, just accumulated) |
| 2026-02-23 | P4 | Weight projection sign error in weekly digest | Delta calculation reversed (showing gain as loss) | 1 day | 5 min | No |
| 2026-02-23 | P4 | MacroFactor hit rate denominator off | Division denominator using wrong field | 1 day | 5 min | No |
| 2026-03-11 | **P2** | Brittany email failing on all deploys since v3.5.1 | Two compounding bugs: (1) `deploy_obs1_ai3_apikeys.sh` used inline `zip` with path prefix — Lambda package contained `lambdas/brittany_email_lambda.py` at a subdirectory rather than root, causing `ImportModuleError` on every invocation; (2) `EmailStack` in CDK had no layer reference — all 8 email Lambdas silently running on `life-platform-shared-utils:2` (missing `set_date` method added in v4). Root principle violation: deploy scripts must always delegate to `deploy_lambda.sh` (which strips path via temp dir); never inline zip logic. | Manual test during v3.5.4 session | ~30 min (v3.5.5): fixed zip via `deploy_lambda.sh` re-deploy; added `SHARED_LAYER_ARN` + layer reference to all 8 email Lambdas in `email_stack.py`; `npx cdk deploy LifePlatformEmail` to apply | No — no Brittany emails sent since initial deploy; email content unaffected once fixed |
| 2026-03-11 | P3 | All 8 email Lambdas on stale layer v2 (missing `set_date`) since EmailStack CDK migration | EmailStack created in PROD-1 (v3.3.5) with no `layers=` parameter — all email Lambdas referenced zero layers and fell back to stale bundled copies of shared modules. `set_date()` method (added in platform_logger v2 for OBS-1 structured logging) was unavailable, causing silent `AttributeError` risk on any email Lambda that called it. No confirmed runtime failures because email Lambdas that bundled their own logger copy used the older API. Discovered during Brittany email debug. | Discovered during v3.5.5 investigation | Fixed in v3.5.5 via EmailStack CDK layer patch | No confirmed impact — no `set_date` calls confirmed in email Lambdas prior to v3.5.5 fix |

*TTD = Time to Detect, TTR = Time to Resolve

---

## Patterns & Observations

**Most common root causes:**
1. **Deployment errors** (wrong function ordering, missing IAM, wrong binary, CDK packaging, inline zip path prefix, **S3 sync to wrong target**) — 9 incidents
2. **CDK drift** (IAM policies correct in code but not applied to AWS) — 3 incidents (Mar 12 Todoist, Mar 04 character-sheet, Mar 09 CDK packaging)
3. **Stale config / env var overrides** (SECRET_NAME env var pointing at deleted secret) — 3 incidents
4. **Silent secret deletion** — Secrets Manager 7-day deletion recovery window expired unnoticed. Two secrets (Dropbox/ingestion-keys, Notion) were scheduled for deletion and expired without any Lambda failing loudly. **Mitigation deployed:** `pipeline-health-check` Lambda (v4.4.0) probes all 11 secrets daily at 6 AM PT. — 2 incidents
5. **Stale Lambda module caches** — Lambda packages with bundled copies of shared modules (platform_logger.py) missing new methods. The v3.3.8 batch fix redeployed 13 ingestion Lambdas but missed Eight Sleep and Health Auto Export. Root fix: `hasattr(logger, 'set_date')` guard added to all 14 Lambdas. — 3 incidents (Mar 9, Mar 19 Eight Sleep, Mar 19 HAE)
6. **Wrong component investigated** (two Apple Health Lambdas, alarm dimension mismatch) — 3 incidents
7. **Missing infrastructure** (EventBridge rule never created, IAM missing permission, CDK stack missing layer reference) — 3 incidents
8. **Data quality / scoring logic** (zero-score defaults, dedup, sign errors) — 4 incidents
9. **One-off deploy scripts bypassing canonical tooling** — 2 incidents (Mar 11 Brittany email inline zip, **Mar 16 S3 bucket wipe**)

**S3 sync --delete watch-out (ADR-032/033, v3.7.57):** `aws s3 sync --delete` to the bucket root will delete every object not in the source directory. This is the most destructive single command in the platform. **Hardening applied:**
1. S3 bucket policy denies `s3:DeleteObject` on `raw/`, `config/`, `uploads/`, `dashboard/`, `exports/`, `deploys/`, `cloudtrail/`, `imports/` for `matthew-admin` — deploy scripts physically cannot delete data files.
2. `deploy/lib/safe_sync.sh` wrapper blocks syncs to bucket root and aborts if dryrun shows >100 deletions.
3. S3 versioning enabled — delete markers are recoverable.
4. One-off deploy scripts are prohibited. All site deploys use `sync_site_to_s3.sh` with `S3_PREFIX="site"`.

**One-off deploy script watch-out (new pattern as of v3.7.57):** One-off scripts (`deploy_vXXXX_do_thing.sh`) bypass the safety patterns built into canonical tooling. Two separate P1/P2 incidents traced to one-off scripts that didn't use `deploy_lambda.sh` or `sync_site_to_s3.sh`. **Rule: no one-off deploy scripts.** Use canonical scripts with flags/arguments, or modify the canonical script temporarily.

**CDK drift watch-out (new pattern as of v3.7.10):** IAM policy changes in `role_policies.py` only take effect when the relevant stack is deployed. After any refactor touching role policies (secrets consolidation, prefix changes, etc.), always redeploy the affected stack immediately and verify with a smoke invoke. Do not assume CDK state matches AWS state without a deploy.

**MCP Lambda deploy watch-out (ADR-031, v3.7.47):** `deploy_lambda.sh life-platform-mcp` strips the `mcp/` package — the Lambda boots clean but routes everything through the bridge handler (401 on all requests). Always use the full zip build for MCP:
```bash
ZIP=/tmp/mcp_deploy.zip && rm -f $ZIP
zip -j $ZIP mcp_server.py mcp_bridge.py && zip -r $ZIP mcp/ -x 'mcp/__pycache__/*' 'mcp/*.pyc'
aws lambda update-function-code --function-name life-platform-mcp --zip-file fileb://$ZIP --region us-west-2
```
`deploy_lambda.sh` now hard-rejects `life-platform-mcp` with a clear error. Symptom: `{"error": "Unauthorized"}` from OAuth endpoints; Lambda logs show clean START/END with no errors (misleading).

**CDK packaging watch-out:** `Code.from_asset("..")` bundles source files one directory deep in the zip — Lambda can't find the handler. Always use `Code.from_asset("../lambdas")` (points at the lambdas directory directly). When CDK-managing Lambdas for the first time, verify a sample function works before assuming all 23 are healthy. `deploy_lambda.sh` is immune to this bug.

**Stale lambda module caches:** When a shared module (like `platform_logger.py`) adds new methods, all Lambdas that bundle their own copy of that file need to be redeployed. CDK packaging re-bundles from source automatically; `deploy_lambda.sh --extra-files` is the manual equivalent for Lambdas not yet on CDK.

**Secrets consolidation watch-out:** When consolidating Secrets Manager entries, Lambdas with `SECRET_NAME` (or similar) set as explicit env vars will override code defaults and continue pointing at the deleted secret. Always audit Lambda env vars — not just code — when retiring secrets. Also verify key naming conventions match between old and new secret schemas.

**Key lesson (from RCA):** When data isn't flowing, check YOUR pipeline first (CloudWatch logs for the receiving Lambda), not the external dependency. Document the full request path so you investigate the right component.

---

## Open Monitoring Gaps

| Gap | Risk | Mitigation |
|-----|------|------------|
| No end-to-end data flow dashboard | Slow detection of silent failures | Freshness checker provides daily coverage |
| DLQ coverage: MCP + webhook excluded | Request/response pattern — DLQ not applicable | CloudWatch error alarms cover both |
| No webhook health check endpoint | Can't externally monitor webhook availability | CloudWatch alarm on zero invocations/24h |
| ~~No duration/throttle alarms~~ | ~~Timeouts without errors go undetected~~ | **Resolved v3.7.36** — duration alarms deployed for all Lambdas |
| ~~No CDK drift detection~~ | ~~IAM policy changes in code may not be applied to AWS~~ | **Resolved v3.7.36** — `cdk diff` step added to ci-cd.yml; post-refactor deploy + smoke verify documented in RUNBOOK.md |

**Resolved gaps (v2.75.0):** All 29 Lambdas now have CloudWatch error alarms. 10 log groups now have 30-day retention. Deployment zip filename bug eliminated by `deploy_lambda.sh` auto-reading handler config from AWS.

**Resolved gaps (v3.1.x):** DLQ consumer Lambda (`dlq-consumer`) now drains and logs failures from `life-platform-ingestion-dlq` on a schedule — silent DLQ accumulation is now caught proactively. Canary Lambda (`life-platform-canary`) runs synthetic DDB+S3+MCP round-trip every 30 min with 4 CloudWatch alarms — end-to-end health check is now automated. `item_size_guard.py` monitors 400KB DDB write limits before they cause failures.


---

## 8. INTELLIGENCE LAYER

# Life Platform — Intelligence Layer

> Documents the Intelligence Compounding (IC) features: how the platform learns, remembers, and improves over time.
> For the IC roadmap and future phases, see PROJECT_PLAN.md (Tier 7).
> Last updated: 2026-03-30 (v4.5.1)
>
> **Changes since v3.7.68:** Signal Doctrine (evidence badges, confidence tiers), Challenge System (XP modifiers, weekly cadence), Food Delivery integration (delivery index as IC input), Reader Engagement signals (freshness indicators, "Since Your Last Visit"), Elena Voss pull-quote pipeline across 6 observatory pages, ADR-045 (121 MCP tools accepted as operating state).

---

## Overview

The Intelligence Layer transforms the platform from a stateless data observer into a compounding intelligence engine. Rather than running the same analysis fresh each day and generating the same generic insight repeatedly, the IC system:

1. **Persists** insights and patterns to DynamoDB (`platform_memory`, `insights`, `decisions`, `hypotheses`, `weekly_correlations`)
2. **Compounds** — each new analysis reads previous findings as context
3. **Learns** Matthew's specific biology, psychology, and failure patterns over time
4. **Self-improves** — coaching calibration evolves as evidence accumulates

The architecture decision (ADR-016) is explicit: no vector store, no embeddings, no fine-tuning. Pure DynamoDB key-value + structured context injection + prompt engineering.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  PRE-COMPUTE PIPELINE (runs before Daily Brief)              │
│                                                              │
│  9:35 AM  character-sheet-compute                            │
│  9:40 AM  daily-metrics-compute → computed_metrics DDB       │
│  9:42 AM  daily-insight-compute → insight_data (JSON)        │
│           ├─ 7-day habit × outcome correlations              │
│           ├─ leading indicator flags                         │
│           ├─ platform_memory pull (relevant records)         │
│           └─ structured JSON handoff to Daily Brief          │
│                                                              │
│  SUNDAY 11:30 AM  weekly-correlation-compute                 │
│           ├─ 23 Pearson pairs (20 cross-sectional + 3 lagged)│
│           ├─ Benjamini-Hochberg FDR correction (v3.7.37)     │
│           └─ writes SOURCE#weekly_correlations | WEEK#<iso>  │
│                                                              │
│  SUNDAY 12:00 PM  hypothesis-engine v1.2.0                   │
│           ├─ reads weekly_correlations as context            │
│           ├─ cross-domain hypotheses → SOURCE#hypotheses DDB │
│           ├─ validation: fields + domains + numeric criteria  │
│           ├─ dedup against active hypotheses                 │
│           └─ 30-day hard expiry; 3 confirms → permanent      │
└─────────────────────────────────┬────────────────────────────┘
                                  │ reads pre-computed data
┌─────────────────────────────────▼────────────────────────────┐
│  AI CALL LAYER (all email/digest Lambdas)                    │
│                                                              │
│  IC-3: Chain-of-thought two-pass (BoD + TL;DR)               │
│    Pass 1: identify patterns + connections (JSON)            │
│    Pass 2: write coaching output using Pass 1 analysis       │
│                                                              │
│  IC-7: Cross-pillar trade-off reasoning instruction          │
│  IC-23: Attention-weighted prompt budgeting (surprise score) │
│  IC-24: Data quality scoring (flag incomplete sources)       │
│  IC-25: Diminishing returns detection (per-pillar)           │
│  IC-17: Red Team / Contrarian Skeptic pass (anti-confirmation│
│          bias, challenges correlation claims)                │
│                                                              │
│  W3: ai_output_validator wired to all 12 AI-output Lambdas  │
│      (validates shape, required fields, disclaimer presence) │
└─────────────────────────────────┬────────────────────────────┘
                                  │ writes after generation
┌─────────────────────────────────▼────────────────────────────┐
│  MEMORY LAYER                                                │
│                                                              │
│  insight_writer.py (shared module in Lambda Layer)           │
│  → SOURCE#insights — universal write by all email Lambdas    │
│  → SOURCE#platform_memory — failure patterns, milestones,    │
│    intention tracking, what worked, coaching calibration      │
│  → SOURCE#decisions — platform decisions + outcomes          │
│  → SOURCE#hypotheses — weekly cross-domain hypotheses        │
│  → SOURCE#weekly_correlations — 23-pair FDR-corrected matrix │
└──────────────────────────────────────────────────────────────┘
```

---

## IC Features (as of v3.7.48)

### IC-1: platform_memory Partition
**Status:** Live (v2.86.0)
**What it does:** DDB partition `SOURCE#platform_memory`, SK `MEMORY#<category>#<date>`. The compounding substrate — structured memory written by compute Lambdas and digest Lambdas, read back into AI prompts as context. Enables "the last 4 weeks show X pattern" without re-querying raw data.

**Memory categories live:** `milestone_architecture`, `intention_tracking`
**Memory categories coming:** `failure_patterns` (Month 2), `what_worked` (Month 3), `coaching_calibration` (Month 3), `personal_curves` (Month 4)

### IC-2: Daily Insight Compute Lambda
**Status:** Live (v2.86.0)
**Lambda:** `daily-insight-compute` (9:42 AM PT)
**What it does:** Pre-computes structured insight JSON before Daily Brief runs. Pulls 7 days of metrics, computes habit×outcome correlations, flags leading indicators, pulls relevant platform_memory records. Daily Brief receives curated intelligence rather than raw data.

**Key output fields in insight JSON:**
- `habit_outcome_correlations` — which habit completions correlate with better sleep/recovery
- `leading_indicators` — early warning signals (e.g., HRV declining 3 consecutive days)
- `memory_context` — relevant platform_memory records for today's conditions
- `data_quality` — per-source confidence scores (IC-24)
- `surprise_scores` — per-metric deviation from rolling baseline (IC-23)

**Validator:** `ingestion_validator.py` `computed_insights` schema wired since v3.7.25.

### IC-3: Chain-of-Thought Two-Pass
**Status:** Live (v2.86.0)
**What it does:** Board of Directors + TL;DR AI calls use two-pass reasoning. Pass 1 generates structured JSON identifying patterns and connections. Pass 2 writes coaching output using Pass 1 analysis. ~2× token cost but material quality improvement — model reasons before writing.

**Model routing (TB7-23, confirmed 2026-03-13):** Both Pass 1 (analysis) and Pass 2 (output) use `AI_MODEL` = `claude-sonnet-4-6` via `call_anthropic()` in `ai_calls.py`. There is **no quality asymmetry** between the two passes — both run on Sonnet. The Haiku reference at line 515 of `daily_insight_compute_lambda.py` is the IC-8 intent evaluator, which correctly uses Haiku (classification task, not coaching). IC-3 itself has no Haiku dependency.

### IC-4: Failure Pattern Recognition
**Status:** Data-gated skeleton (not yet live — data gate: `days_available >= 42` in `habit_scores`)
**Lambda:** `failure_pattern_compute_lambda.py` (CDK-wired and EventBridge-scheduled pending activation ~2026-05-01)
**What it does:** Identifies recurring failure patterns in habit execution — specifically, which antecedent conditions (high TSB, poor sleep, high Todoist load, travel) consistently precede multi-day habit streaks breaking. Writes failure pattern summaries to `MEMORY#failure_patterns` in `platform_memory`. Coaching AI uses these patterns to preemptively warn: "Last 3 times load exceeded 80 + sleep efficiency dropped below 78%, habits collapsed for 4+ days."

**Activation checklist:**
1. Verify `days_available >= 42` in `habit_scores` partition
2. Add to `cdk/stacks/compute_stack.py` with EventBridge rule
3. Update `ci/lambda_map.json` (remove `not_deployed` flag)
4. Deploy via CDK + run `post_cdk_reconcile_smoke.sh`

**Key output fields:**
- `antecedent_conditions` — conditions that preceded failure (list of {metric, threshold, direction})
- `failure_type` — e.g. `habit_streak_collapse`, `nutrition_drift`, `sleep_degradation`
- `recurrence_count` — how many times this pattern has been observed
- `recovery_days` — median days to recover after this pattern fires

---

### IC-5: Momentum Warning
**Status:** Data-gated skeleton (not yet live — data gate: `days_available >= 42` in `computed_metrics`)
**Lambda:** `momentum_warning_compute_lambda.py` (CDK-wired and EventBridge-scheduled pending activation ~2026-05-01)
**What it does:** Early-warning system that detects leading indicators of momentum loss — sustained low habit completion + declining pillar scores + rising TSB — before they manifest as a measurable setback. Writes momentum signals to `MEMORY#momentum_warnings`. Coaching AI surfaces these as forward-looking alerts rather than retrospective observations.

**Activation checklist:** Same as IC-4 — pair them in the same CDK deploy to share one activation pass.

**Key output fields:**
- `momentum_signal` — `warning` | `at_risk` | `stable` | `building`
- `leading_indicators` — list of metrics trending unfavorably with direction and days_trending
- `at_risk_pillars` — pillar names with current trajectory
- `suggested_intervention` — highest-leverage action to reverse momentum (e.g. `prioritize_sleep`, `reduce_training_load`)

---

### IC-6: Milestone Architecture
**Status:** Live (v2.86.0)
**What it does:** 6 weight/health milestones with biological significance for Matthew stored in `platform_memory`. Surfaced in coaching when approaching each threshold. Example: "At 285 lbs: sleep apnea risk drops substantially (genome flag)." Converts abstract goal into biological waypoints.


... [TRUNCATED — 398 lines omitted, 548 total]


---

## 9. TIER 8 HARDENING STATUS

[Tier 8 section not found in PROJECT_PLAN.md]


---

## 10. CDK / IaC STATE

### cdk/app.py
```python

#!/usr/bin/env python3
"""
Life Platform CDK App — PROD-1: Infrastructure as Code

Stack architecture:
  core        → DynamoDB, S3, SQS DLQ, SNS alerts (imported existing resources)
  ingestion   → 13 ingestion Lambdas + EventBridge rules + IAM roles
  compute     → 5 compute Lambdas + EventBridge rules
  email       → 8 email/digest Lambdas + EventBridge rules
  operational → Operational Lambdas (anomaly, freshness, canary, dlq-consumer, etc.)
  mcp         → MCP Lambda + Function URLs (local + remote)
  web         → CloudFront (3 distributions) + ACM certificates
  monitoring  → CloudWatch alarms + ops dashboard + SLO alarms

Deployment:
  cdk bootstrap aws://205930651321/us-west-2
  cdk deploy LifePlatformCore
  cdk deploy LifePlatformIngestion
  cdk deploy LifePlatformCompute
  cdk deploy LifePlatformEmail
  cdk deploy LifePlatformOperational
  cdk deploy LifePlatformMcp
  cdk deploy LifePlatformWeb         # requires us-east-1 cert ARNs
  cdk deploy LifePlatformMonitoring

To import existing resources (first time only):
  cdk import LifePlatformCore
"""

import aws_cdk as cdk

from stacks.core_stack import CoreStack
from stacks.ingestion_stack import IngestionStack
from stacks.compute_stack import ComputeStack
from stacks.email_stack import EmailStack
from stacks.operational_stack import OperationalStack
from stacks.mcp_stack import McpStack
from stacks.web_stack import WebStack
from stacks.monitoring_stack import MonitoringStack

app = cdk.App()

# Read context values
account = app.node.try_get_context("account") or "205930651321"
region = app.node.try_get_context("region") or "us-west-2"

env = cdk.Environment(account=account, region=region)

# ── Core infrastructure (DynamoDB, S3, SQS, SNS) ──
core = CoreStack(app, "LifePlatformCore", env=env)

# ── All 8 stacks wired ──
# Each stack receives core.table, core.bucket, core.dlq, core.alerts_topic
# as cross-stack references.
#
ingestion = IngestionStack(app, "LifePlatformIngestion", env=env,
    table=core.table, bucket=core.bucket, dlq=core.dlq,
    alerts_topic=core.alerts_topic)
# ingestion stack wired ✅
#
compute = ComputeStack(app, "LifePlatformCompute", env=env,
    table=core.table, bucket=core.bucket, dlq=core.dlq,
    alerts_topic=core.alerts_topic)
# compute stack wired ✅
#
email = EmailStack(app, "LifePlatformEmail", env=env,
    table=core.table, bucket=core.bucket, dlq=core.dlq,
    alerts_topic=core.alerts_topic)
# email stack wired ✅
#
operational = OperationalStack(app, "LifePlatformOperational", env=env,
    table=core.table, bucket=core.bucket, dlq=core.dlq,
    alerts_topic=core.alerts_topic)
# operational stack wired ✅
#
mcp = McpStack(app, "LifePlatformMcp", env=env,
    table=core.table, bucket=core.bucket)
# mcp stack wired ✅
#
web = WebStack(app, "LifePlatformWeb",
    env=cdk.Environment(account=account, region="us-east-1"))  # CloudFront requires us-east-1
# web stack wired ✅
#
monitoring = MonitoringStack(app, "LifePlatformMonitoring", env=env,
    alerts_topic=core.alerts_topic)
# monitoring stack wired ✅

app.synth()

```


### cdk/stacks/lambda_helpers.py (first 80 lines)
```python

"""
lambda_helpers.py — Shared Lambda construction patterns for CDK stacks.

Provides a helper function that creates a Lambda function with all the
standard Life Platform conventions:
  - Per-function IAM role with explicit least-privilege policies
  - DLQ configured
  - Environment variables (TABLE_NAME, S3_BUCKET, USER_ID)
  - CloudWatch error alarm
  - Handler auto-detection from source file
  - Shared Layer attachment (optional)

v2.0 (v3.4.0): Added custom_policies parameter to replace existing_role_arn.
  CDK now OWNS all IAM roles — no more from_role_arn references.
  Migration: existing_role_arn is DEPRECATED and will be removed in a future version.

Usage in a stack:
    from stacks.lambda_helpers import create_platform_lambda
    from stacks.role_policies import ingestion_policies

    fn = create_platform_lambda(
        self, "WhoopIngestion",
        function_name="whoop-data-ingestion",
        source_file="lambdas/whoop_lambda.py",
        handler="whoop_lambda.lambda_handler",
        table=core.table,
        bucket=core.bucket,
        dlq=core.dlq,
        custom_policies=ingestion_policies("whoop"),
        schedule="cron(0 14 * * ? *)",
        timeout_seconds=120,
    )
"""

from aws_cdk import (
    Duration,
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_sqs as sqs,
    aws_events as events,
    aws_events_targets as targets,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_sns as sns,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
)
from constructs import Construct


def create_platform_lambda(
    scope: Construct,
    id: str,
    function_name: str,
    source_file: str,
    handler: str,
    table: dynamodb.ITable,
    bucket: s3.IBucket,
    dlq: sqs.IQueue = None,
    alerts_topic: sns.ITopic = None,
    alarm_name: str = None,
    secrets: list[str] = None,
    schedule: str = None,
    timeout_seconds: int = 120,
    memory_mb: int = 256,
    environment: dict = None,
    shared_layer: _lambda.ILayerVersion = None,
    additional_layers: list = None,
    # ── Legacy parameter (DEPRECATED — use custom_policies instead) ──
    existing_role_arn: str = None,
    # ── Fine-grained IAM (v2.0) ──
    custom_policies: list[iam.PolicyStatement] = None,
    # ── Legacy broad-permission flags (used when neither existing_role_arn nor custom_policies) ──
    ddb_write: bool = True,
    s3_write: bool = True,
    needs_ses: bool = False,
    ses_domain: str = None,
    # ── Observability ──
    tracing: _lambda.Tracing = None,  # R13-XR: pass _lambda.Tracing.ACTIVE for X-Ray
) -> _lambda.Function:

... [TRUNCATED — 160 lines omitted, 240 total]

```


### cdk/stacks/role_policies.py (first 80 lines)
```python

"""
role_policies.py — Centralized IAM policy definitions for all Life Platform Lambdas.

Each function returns a list of iam.PolicyStatement objects that exactly
replicate the existing console-created per-function IAM roles from SEC-1.

Audit source: aws iam get-role-policy on all 37 lambda-* roles (2026-03-09).
Organized by CDK stack: ingestion, compute, email, operational, mcp.

Policy principle: least-privilege per Lambda. No shared roles.
"""

from aws_cdk import aws_iam as iam
from stacks.constants import ACCT, REGION, TABLE_NAME, S3_BUCKET, KMS_KEY_ID, CF_DIST_ID, SES_DOMAIN  # CONF-01, SEC-06, SEC-08

# ── Constants ──────────────────────────────────────────────────────────────
TABLE_ARN = f"arn:aws:dynamodb:{REGION}:{ACCT}:table/{TABLE_NAME}"
BUCKET = S3_BUCKET
CF_DIST_ARN = f"arn:aws:cloudfront::{ACCT}:distribution/{CF_DIST_ID}"
BUCKET_ARN = f"arn:aws:s3:::{BUCKET}"
DLQ_ARN = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
KMS_KEY_ARN = f"arn:aws:kms:{REGION}:{ACCT}:key/{KMS_KEY_ID}"
SES_IDENTITY = f"arn:aws:ses:{REGION}:{ACCT}:identity/{SES_DOMAIN}"  # SEC-08: domain from constants


def _secret_arn(name: str) -> str:
    """Secrets Manager ARN with wildcard suffix for version IDs."""
    return f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:{name}*"


def _s3(*prefixes: str) -> list[str]:
    """S3 object ARNs for the given key prefixes."""
    return [f"{BUCKET_ARN}/{p}" for p in prefixes]


# ═══════════════════════════════════════════════════════════════════════════
# INGESTION STACK — 15 Lambdas
# Pattern: DDB write, S3 raw/<source>/*, source-specific secret, DLQ
# ═══════════════════════════════════════════════════════════════════════════

def _ingestion_base(
    source: str,
    secret_name: str = None,
    s3_prefix: str = None,
    ddb_actions: list[str] = None,
    extra_secret_actions: list[str] = None,
    extra_s3_read: list[str] = None,
    extra_s3_write: list[str] = None,
    extra_statements: list[iam.PolicyStatement] = None,
    no_s3: bool = False,
    no_secret: bool = False,
) -> list[iam.PolicyStatement]:
    """Build standard ingestion role policies."""
    stmts = []

    # DynamoDB
    actions = ddb_actions or ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Query"]
    stmts.append(iam.PolicyStatement(
        sid="DynamoDB",
        actions=actions,
        resources=[TABLE_ARN],
    ))

    # KMS — required for all DDB operations (table is CMK-encrypted)
    stmts.append(iam.PolicyStatement(
        sid="KMS",
        actions=["kms:Decrypt", "kms:GenerateDataKey"],
        resources=[KMS_KEY_ARN],
    ))

    # S3 write (raw data)
    if not no_s3:
        prefix = s3_prefix or f"raw/matthew/{source}/*"
        write_resources = _s3(prefix) + (_s3(*extra_s3_write) if extra_s3_write else [])
        stmts.append(iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            resources=write_resources,
        ))


... [TRUNCATED — 1225 lines omitted, 1305 total]

```


### .github/workflows/ci-cd.yml (FULL — proof of pipeline implementation)
```yaml

# Life Platform CI/CD Pipeline
# MAINT-4: Automated lint → deploy → smoke test on push to main
#
# Architecture:
#   1. Lint (flake8 + py_compile syntax check) — runs on every push, no AWS access needed
#   2. Plan — validates lambda_map.json, detects changed files, maps to Lambda functions
#   3. Deploy — requires manual approval (GitHub Environment: production)
#   4. Smoke test — invokes qa-smoke + canary, checks structured output
#   5. Auto-rollback — fires if smoke-test fails after a successful deploy (TB7-25)
#   6. Notify — posts to SNS on any failure
#
# AWS auth: OIDC federation (no long-lived keys)
# See deploy/setup_github_oidc.sh to create the IAM provider + role
#
# Changes from original (v3.5.8 → v3.6.0):
#   - Added py_compile syntax check step in Lint job
#   - Added lambda_map.json structural validation in Plan job
#   - Replaced sleep 10 with aws lambda wait function-updated (MCP + Lambda deploys)
#   - Added layer version verification after shared layer rebuild
#   - Fixed smoke test and canary to parse JSON output, not grep for "error"
#   - Added notify-failure job that posts to SNS life-platform-alerts on any failure
# Changes (v3.7.9):
#   - Added rollback-on-smoke-failure job (TB7-25): auto-rollback when smoke test fails
#     after a successful deploy. Calls deploy/rollback_lambda.sh for each deployed function.
#     Requires deploy_lambda.sh to have stored artifacts to s3://matthew-life-platform/deploys/

name: CI/CD

on:
  push:
    branches: [main]
    paths:
      - 'lambdas/**'
      - 'mcp/**'
      - 'mcp_server.py'
  workflow_dispatch:
    inputs:
      deploy_all:
        description: 'Deploy ALL Lambdas (skip change detection)'
        required: false
        type: boolean
        default: false

env:
  AWS_REGION: us-west-2
  AWS_ACCOUNT_ID: "205930651321"  # CONF-03: single place — override via GitHub env var for staging
  LAMBDA_MAP: ci/lambda_map.json
  SNS_TOPIC_ARN: arn:aws:sns:us-west-2:205930651321:life-platform-alerts  # CONF-03: constructed from AWS_ACCOUNT_ID in future; centralized above

permissions:
  id-token: write   # OIDC token for AWS
  contents: read    # Checkout code

jobs:
  # ════════════════════════════════════════════════════════════════
  # Job 1: Lint + Syntax Check
  # ════════════════════════════════════════════════════════════════
  lint:
    name: Lint + Syntax Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install flake8
        run: pip install flake8

      - name: Run flake8
        run: |
          echo "::group::Linting lambdas/"
          flake8 lambdas/ --count --show-source --statistics || true
          echo "::endgroup::"

          echo "::group::Linting mcp/"
          flake8 mcp/ --count --show-source --statistics || true
          echo "::endgroup::"

          # Fail on syntax errors and undefined names; pass on style warnings
          flake8 lambdas/ mcp/ --count --select=E9,F63,F7,F82 --show-source --statistics

      - name: Syntax check (py_compile)
        # Catches broken syntax that flake8 misses (e.g. invalid f-strings, truncated files)
        run: |
          echo "::group::Syntax checking lambdas/ and mcp/"
          FAILED=0
          while IFS= read -r -d '' f; do
            if python3 -m py_compile "$f" 2>&1; then
              echo "  ✅ $f"
            else
              echo "  ❌ SYNTAX ERROR: $f"
              FAILED=$((FAILED + 1))
            fi
          done < <(find lambdas/ mcp/ -name '*.py' -print0)
          echo "::endgroup::"
          if [ "$FAILED" -gt 0 ]; then
            echo "::error::$FAILED file(s) failed syntax check"
            exit 1
          fi
          echo "✅ All files pass syntax check"

      - name: Dependency Security Scan (advisory)
        # R19 Phase 6: pip-audit for known vulnerabilities in dependencies
        run: |
          pip install pip-audit 2>/dev/null
          echo "::group::Scanning cdk/requirements.txt"
          pip-audit -r cdk/requirements.txt --desc on 2>&1 || true
          echo "::endgroup::"
          echo "Advisory scan complete — failures are non-blocking"

      - name: Check lambda_map coverage
        # R18-F03: Detect Lambda source files missing from ci/lambda_map.json
        run: |
          MISSING=0
          for f in lambdas/*_lambda.py lambdas/*_handler.py; do
            [ -f "$f" ] || continue
            if ! grep -q "\"$f\"" ci/lambda_map.json; then
              echo "::warning file=$f::Lambda source file not in lambda_map.json"
              MISSING=$((MISSING + 1))
            fi
          done
          if [ $MISSING -gt 0 ]; then
            echo "::warning::$MISSING Lambda source files missing from lambda_map.json"
          else
            echo "✅ All Lambda source files present in lambda_map.json"
          fi

  # ════════════════════════════════════════════════════════════════
  # Job 2: Unit Tests — run pytest on tests/test_shared_modules.py
  # ════════════════════════════════════════════════════════════════
  test:
    name: Unit Tests
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install test dependencies
        run: pip install pytest boto3 botocore

      - name: Run unit tests
        run: |
          echo "::group::Running tests/test_shared_modules.py"
          python3 -m pytest tests/test_shared_modules.py -v --tb=short
          echo "::endgroup::"

      - name: IAM policy linter (test_role_policies.py)
        run: |
          echo "::group::IAM policy linter"
          python3 -m pytest tests/test_role_policies.py -v --tb=short
          echo "::endgroup::"

      - name: CDK handler consistency linter (test_cdk_handler_consistency.py)
        run: |
          echo "::group::CDK handler consistency linter"
          python3 -m pytest tests/test_cdk_handler_consistency.py -v --tb=short
          echo "::endgroup::"

      - name: CDK S3 path linter (test_cdk_s3_paths.py)
        run: |
          echo "::group::CDK S3 path linter"
          python3 -m pytest tests/test_cdk_s3_paths.py -v --tb=short
          echo "::endgroup::"

      - name: Safety module wiring linter (test_wiring_coverage.py)
        run: |
          echo "::group::Wiring coverage linter"
          python3 -m pytest tests/test_wiring_coverage.py -v --tb=short
          echo "::endgroup::"

      - name: DynamoDB pattern linter (test_ddb_patterns.py)
        run: |
          echo "::group::DynamoDB pattern linter"
          python3 -m pytest tests/test_ddb_patterns.py -v --tb=short
          echo "::endgroup::"

      - name: MCP registry integrity linter (test_mcp_registry.py)
        run: |
          echo "::group::MCP registry integrity linter"
          python3 -m pytest tests/test_mcp_registry.py -v --tb=short
          echo "::endgroup::"

      - name: Lambda handler integration linter (test_lambda_handlers.py)
        # TB7-24: I1-I6 — file existence, syntax, handler signature, try/except, orphans, MCP entry point
        run: |
          echo "::group::Lambda handler integration linter"
          python3 -m pytest tests/test_lambda_handlers.py -v --tb=short
          echo "::endgroup::"

      - name: Deprecated secrets scan
        run: |
          echo "::group::Deprecated secrets scan"
          FAILED=0

          while IFS= read -r line; do
            secret=$(echo "$line" | sed 's/#.*//' | xargs)
            [ -z "$secret" ] && continue

            echo "Scanning for deprecated secret: $secret"
            MATCHES=$(grep -rn --include='*.py' --include='*.json' --include='*.yml' --include='*.yaml' --include='*.sh' "$secret" \
              lambdas/ mcp/ cdk/ .github/ ci/ \
              --exclude-dir='.venv' --exclude-dir='cdk.out' \
              2>/dev/null | grep -v 'deprecated_secrets.txt' | grep -v '^Binary' || true)

            if [ -n "$MATCHES" ]; then
              echo "::error::Deprecated secret '$secret' still referenced:"
              echo "$MATCHES" | head -20
              FAILED=$((FAILED + 1))
            else
              echo "  ✅ No references to '$secret'"
            fi
          done < ci/deprecated_secrets.txt

          echo "::endgroup::"
          if [ "$FAILED" -gt 0 ]; then
            echo "::error::$FAILED deprecated secret(s) still referenced. Update to current secret names before merging."
            exit 1
          fi
          echo "✅ Deprecated secrets scan passed"

      - name: IAM/secrets consistency linter (test_iam_secrets_consistency.py)
        # R8-8: Cross-refs IAM secret ARN patterns against known-secrets list
        run: |
          echo "::group::IAM/secrets consistency linter"
          python3 -m pytest tests/test_iam_secrets_consistency.py -v --tb=short
          echo "::endgroup::"

      - name: Secret references linter (test_secret_references.py)
        # R13-F04: Validates Lambda source secret name literals against known-secrets list.
        # Prevents Todoist-style 2-day outage caused by wrong SECRET_NAME default value.
        run: |
          echo "::group::Secret references linter"
          python3 -m pytest tests/test_secret_references.py -v --tb=short
          echo "::endgroup::"

      - name: Layer version consistency linter (test_layer_version_consistency.py)
        # R13-F08: Offline check — verifies layer module files exist, no hardcoded ARNs,
        # and all consumers are wired in CDK. Complements the live AWS check in the Plan job.
        run: |
          echo "::group::Layer version consistency linter"
          python3 -m pytest tests/test_layer_version_consistency.py -v --tb=short
          echo "::endgroup::"

  # ════════════════════════════════════════════════════════════════
  # Job 3: Plan — validate map, detect changes, build deploy plan
  # ════════════════════════════════════════════════════════════════
  plan:
    name: Plan deployments
    runs-on: ubuntu-latest
    needs: [lint, test]
    outputs:
      deploy_matrix: ${{ steps.plan.outputs.matrix }}
      has_deploys: ${{ steps.plan.outputs.has_deploys }}
      layer_changed: ${{ steps.plan.outputs.layer_changed }}
      mcp_changed: ${{ steps.plan.outputs.mcp_changed }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 2  # Need HEAD~1 for diff

      - name: Validate lambda_map.json
        run: |
          echo "Validating ci/lambda_map.json..."
          MISSING=0

          echo "Checking Lambda source files..."
          while IFS= read -r src; do
            if [ ! -f "$src" ]; then
              echo "  ❌ MISSING source: $src (in .lambdas — file not found in repo)"
              MISSING=$((MISSING + 1))
            fi
          done < <(jq -r '.lambdas | keys[]' ci/lambda_map.json)

          echo "Checking shared layer modules..."
          while IFS= read -r mod; do
            if [ ! -f "$mod" ]; then
              echo "  ❌ MISSING layer module: $mod (in .shared_layer.modules — file not found)"
              MISSING=$((MISSING + 1))
            fi
          done < <(jq -r '.shared_layer.modules[]' ci/lambda_map.json)

          if [ "$MISSING" -gt 0 ]; then
            echo "::error::lambda_map.json references $MISSING missing file(s). Update ci/lambda_map.json to match current repo state."
            exit 1
          fi
          echo "✅ lambda_map.json valid — all source files present"

      - name: Configure AWS credentials (OIDC) — plan
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::${{ env.AWS_ACCOUNT_ID }}:role/github-actions-deploy-role
          aws-region: ${{ env.AWS_REGION }}

      - name: CDK diff — detect IAM/infra drift

... [TRUNCATED — 673 lines omitted, 973 total]

```


### Test suite — all test files with function names

**test_business_logic.py** (0 tests): 


**test_cdk_handler_consistency.py** (5 tests): test_h1_handler_and_source_always_paired, test_h2_all_source_files_exist, test_h3_handler_module_matches_source_file, test_h4_all_source_files_define_lambda_handler, test_h5_no_generic_lambda_function_handler


**test_cdk_s3_paths.py** (4 tests): test_s1_all_s3_prefixes_are_convention_or_documented, test_s2_exception_evidence_in_lambda_source, test_s3_exceptions_dont_use_convention_prefix, test_s4_no_hardcoded_matthew_in_iam_comments


**test_character_engine.py** (29 tests): test_engine_version, test_weighted_pillar_score_full_data, test_weighted_pillar_score_sparse_data, test_weighted_pillar_score_no_data, test_xp_decays_on_mediocre_day, test_xp_floors_at_zero, test_xp_grows_on_good_day, test_body_comp_loss_sigmoid, test_body_comp_maintenance, test_body_comp_none_weight, test_lab_decay_full_value, test_lab_decay_expires, test_lab_decay_at_90_days, test_ema_empty_returns_50, test_vice_log_curve, test_vice_log_day_30, test_in_range_score_in_range, test_in_range_score_below, test_in_range_score_none, test_foundation_levels_up_in_3_days, test_foundation_no_levelup_at_2_days, test_mastery_requires_10_days, test_mastery_levels_up_at_10_days, test_equal_day_holds_streak, test_variable_step_when_delta_large, test_normal_step_when_delta_small, test_per_pillar_ema_lambda, test_xp_buffer_prevents_level_down, test_xp_buffer_depleted_allows_level_down


**test_ddb_patterns.py** (4 tests): test_d1_pk_sk_format, test_d2_date_reserved_word_guarded, test_d3_schema_version_present, test_d4_put_item_guarded_by_validator


**test_function_url_origin_header_validation.py** (0 tests): 


**test_get_nutrition_args.py** (8 tests): test_nutrition_no_args, test_nutrition_summary_view, test_nutrition_macros_view, test_nutrition_meal_timing_view, test_nutrition_micronutrients_view, test_nutrition_with_dates, test_nutrition_macros_with_overrides, test_nutrition_invalid_view


**test_iam_secrets_consistency.py** (4 tests): test_s1_all_iam_secrets_are_known, test_s2_no_deleted_secrets_in_iam, test_s3_all_known_secrets_referenced, test_s4_known_secrets_count_matches_architecture


**test_integration_aws.py** (14 tests): test_i1_lambda_handlers_match_expected, test_i2_lambda_layer_version_current, test_i3_spot_check_lambda_invocability, test_i4_dynamodb_table_healthy, test_i5_required_secrets_exist, test_i6_eventbridge_rules_exist_and_enabled, test_i7_cloudwatch_alarms_exist, test_i8_s3_bucket_and_config_files, test_i9_dlq_empty, test_i10_mcp_lambda_responds, test_i11_data_reconciliation_running, test_i12_mcp_tool_call_response_shape, test_i13_freshness_checker_returns_valid_data, test_i14_canary_mcp_check_passes


**test_lambda_handlers.py** (6 tests): test_i1_source_file_exists, test_i2_source_file_syntax_valid, test_i3_handler_signature, test_i4_handler_has_try_except, test_i5_no_orphaned_lambda_files, test_i6_mcp_server_handler


**test_lambda_sizing.py** (5 tests): test_ingestion_stack_memory_limits, test_compute_stack_memory_limits, test_web_stack_memory_limits, test_email_stack_memory_limits, test_no_3008mb_anywhere


**test_layer_version_consistency.py** (5 tests): test_lv1_cdk_uses_layer_name_not_hardcoded_arn, test_lv2_all_consumers_referenced_in_cdk, test_lv3_all_layer_modules_exist_on_disk, test_lv5_layer_version_only_in_constants, test_lv4_consumer_count_sanity


**test_mcp_registry.py** (7 tests): test_r1_all_imports_resolve, test_r2_all_fn_references_exist, test_r3_schema_structure, test_r4_no_duplicate_tool_names, test_r5_tool_count_in_range, test_r6_registry_syntax_valid, test_r7_all_tool_modules_parseable


**test_model_versions.py** (2 tests): test_cdk_stacks_use_valid_model_ids, test_constants_model_default_is_valid


**test_role_policies.py** (7 tests): test_r1_ddb_read_requires_kms_decrypt, test_r2_ddb_write_requires_kms_generate, test_r3_kms_resource_is_scoped, test_r4_no_unexpected_wildcard_resources, test_r5_secrets_resources_are_scoped, test_r6_policy_is_non_empty, test_r7_no_duplicate_sids


**test_secret_references.py** (4 tests): test_sr1_all_secret_references_are_known, test_sr2_no_deleted_secret_references, test_sr3_secret_names_follow_convention, test_sr4_secret_references_found


**test_shared_modules.py** (66 tests): test_empty_blocked, test_none_blocked, test_too_short_blocked, test_truncated_blocked, test_good_text_passes, test_dangerous_training_red_recovery, test_aggressive_borderline_warns, test_low_cal_blocked, test_causation_warns, test_generic_phrases_warn, test_sanitized_text_fallback, test_sanitized_text_original, test_fallbacks_all_types, test_validate_json_none_blocked, test_validate_json_missing_key, test_validate_json_ok, test_get_logger_type, test_get_logger_singleton, test_set_date, test_set_correlation_id, test_info_json_output, test_positional_args, test_helpers_no_raise, test_check_sick_day_none, test_check_sick_day_found, test_check_sick_day_decimal, test_check_sick_day_ddb_error, test_get_sick_days_range_empty, test_get_sick_days_range_error, test_write_sick_day_fields, test_write_sick_day_no_reason, test_delete_sick_day, test_d2f_decimal, test_d2f_nested, test_avg_basic, test_avg_none_ignored, test_avg_empty, test_avg_all_none, test_fmt_value, test_fmt_none, test_fmt_with_unit, test_fmt_num, test_fmt_num_none, test_safe_float_present, test_safe_float_missing, test_safe_float_default, test_dedup_different_sports, test_dedup_removes_duplicate, test_dedup_empty, test_normalize_whoop_sleep, test_ex_whoop_from_list, test_ex_whoop_empty, test_ex_withings_latest, test_banister_zero_input, test_banister_with_training, test_validate_whoop_ok, test_validate_whoop_out_of_range, test_validate_empty_record, test_validation_result_structure, test_list_supported_sources, test_call_anthropic_has_output_type_param, test_ai_validator_importable, test_ai_output_type_importable, test_bod_caller_passes_output_type, test_journal_caller_passes_output_type, test_email_lambdas_dont_call_anthropic_directly


**test_subscriber_email_template.py** (5 tests): test_build_subscriber_email_basic, test_build_subscriber_email_no_signal_data, test_extract_chronicle_preview, test_extract_chronicle_preview_empty, test_bug_fix_subscriber_email_variable


**test_weekly_signal_data.py** (4 tests): test_build_weekly_signal_data_basic, test_build_weekly_signal_data_empty, test_board_rotation_deterministic, test_observatory_rotation


**test_wiring_coverage.py** (4 tests): test_w1_platform_logger_imported, test_w2_ingestion_validator_wired, test_w3_ai_output_validator_wired, test_w4_no_causal_language_in_prompts


### CDK stack files: compute_stack.py, constants.py, core_stack.py, email_stack.py, ingestion_stack.py, lambda_helpers.py, mcp_stack.py, monitoring_stack.py, operational_stack.py, role_policies.py, web_stack.py


---

## 11. SOURCE CODE INVENTORY

### lambdas/ (82 .py files, 1 other files)

**Python files:** acwr_compute_lambda.py, adaptive_mode_lambda.py, ai_calls.py, ai_expert_analyzer_lambda.py, ai_output_validator.py, anomaly_detector_lambda.py, apple_health_lambda.py, board_loader.py, brittany_email_lambda.py, canary_lambda.py, challenge_generator_lambda.py, character_engine.py, character_sheet_lambda.py, chronicle_approve_lambda.py, chronicle_email_sender_lambda.py, circadian_compliance_lambda.py, daily_brief_lambda.py, daily_insight_compute_lambda.py, daily_metrics_compute_lambda.py, dashboard_refresh_lambda.py, data_export_lambda.py, data_reconciliation_lambda.py, digest_utils.py, dlq_consumer_lambda.py, dropbox_poll_lambda.py, eightsleep_lambda.py, email_subscriber_lambda.py, enrichment_lambda.py, evening_nudge_lambda.py, failure_pattern_compute_lambda.py, field_notes_lambda.py, food_delivery_lambda.py, freshness_checker_lambda.py, garmin_lambda.py, genome_coaching.py, google_calendar_lambda.py, habitify_lambda.py, health_auto_export_lambda.py, html_builder.py, hypothesis_engine_lambda.py, ingestion_framework.py, ingestion_validator.py, insight_email_parser_lambda.py, insight_writer.py, item_size_guard.py, journal_analyzer_lambda.py, journal_enrichment_lambda.py, key_rotator_lambda.py, labs_coaching.py, macrofactor_lambda.py, measurements_ingestion_lambda.py, momentum_warning_compute_lambda.py, monday_compass_lambda.py, monthly_digest_lambda.py, notion_lambda.py, nutrition_review_lambda.py, og_image_lambda.py, output_writers.py, pip_audit_lambda.py, pipeline_health_check_lambda.py, platform_logger.py, podcast_scanner_lambda.py, qa_smoke_lambda.py, retry_utils.py, scoring_engine.py, secret_cache.py, sick_day_checker.py, site_api_ai_lambda.py, site_api_lambda.py, site_stats_refresh_lambda.py, site_writer.py, sleep_reconciler_lambda.py, strava_lambda.py, subscriber_onboarding_lambda.py, todoist_lambda.py, weather_handler.py, wednesday_chronicle_lambda.py, weekly_correlation_compute_lambda.py, weekly_digest_lambda.py, weekly_plate_lambda.py, whoop_lambda.py, withings_lambda.py


**Other files (potential cleanup):** og_image_lambda.mjs


**Subdirectories:** __pycache__, buddy, cf-auth, dashboard, fonts, requirements


### deploy/ (43 files)

**Files:** MANIFEST.md, README.md, SMOKE_TEST_TEMPLATE.sh, apply_s3_lifecycle.sh, archive_onetime_scripts.sh, audit_system_state.sh, bucket_policy.json, build_layer.sh, build_mcp_stable_layer.sh, canary_policy.json, capture_baseline.sh, create_mcp_canary_15min.sh, deploy_and_verify.sh, deploy_lambda.sh, deploy_site.sh, deploy_web_stack.sh, download_barlow_condensed.sh, generate_review_bundle.py, hero_snippet_bs02.html, maintenance_mode.sh, pipeline_health_check.sh, pitr_restore_drill.sh, point_route53_to_cloudfront.sh, post_cdk_reconcile_smoke.sh, post_cdk_smoke.sh, privacy_filter.json, request_amj_cert.sh, rollback_lambda.sh, rollback_site.sh, seed_protocols_to_dynamodb.sh, setup_email_subscriber.sh, setup_github_oidc.sh, setup_pipeline_health_check.sh, setup_r18_alarms.sh, setup_subscriber_onboarding.sh, setup_waf.sh, setup_waf_endpoint_rules.sh, smoke_test_cloudfront.sh, smoke_test_site.sh, sync_site_to_s3.sh, test_subscribe.sh, validate_amj_cert.sh, warmup_lambdas.sh


### mcp/ (36 modules)

**Modules:** __init__.py, config.py, core.py, handler.py, helpers.py, labs_helpers.py, registry.py, strength_helpers.py, tools_adaptive.py, tools_board.py, tools_calendar.py, tools_cgm.py, tools_challenges.py, tools_character.py, tools_correlation.py, tools_data.py, tools_decisions.py, tools_food_delivery.py, tools_habits.py, tools_health.py, tools_hypotheses.py, tools_journal.py, tools_labs.py, tools_lifestyle.py, tools_measurements.py, tools_memory.py, tools_nutrition.py, tools_protocols.py, tools_sick_days.py, tools_sleep.py, tools_social.py, tools_strength.py, tools_todoist.py, tools_training.py, utils.py, warmer.py


---

## 12. KEY SOURCE CODE SAMPLES

### daily_brief_lambda.py — Daily Brief orchestrator — most complex Lambda
```python

"""
Daily Brief Lambda — v2.82.0 (Compute refactor: reads pre-computed metrics from daily-metrics-compute Lambda)
Fires at 10:00am PT daily (18:00 UTC via EventBridge).

v2.2 changes:
  - MacroFactor workouts integration (exercise-level detail in Training Report)
  - Smart Guidance: AI-generated from all signals (replaces static table)
  - TL;DR line: single sentence under day grade
  - Weight: weekly delta callout
  - Sleep architecture: deep % + REM % in scorecard
  - Eight Sleep field name fixes (sleep_efficiency_pct, sleep_duration_hours)
  - Nutrition Report: meal timing in AI prompt
  - 4 AI calls: BoD, Training+Nutrition, Journal Coach, TL;DR+Guidance combined

v2.77.0 extraction:
  - html_builder.py   — build_html, hrv_trend_str, _section_error_html (~1,000 lines)
  - ai_calls.py       — all 4 AI call functions + data summary builders (~380 lines)
  - output_writers.py — write_dashboard_json, write_clinical_json, write_buddy_json,
                        evaluate_rewards, get_protocol_recs, sanitize_for_demo (~700 lines)
  Lambda shrinks from 4,002 → ~1,366 lines of orchestration logic.

Sections (15):
  1.  Day Grade + TL;DR (AI one-liner)
  2.  Yesterday's Scorecard (sleep architecture detail)
  3.  Readiness Signal
  4.  Training Report (exercise-level detail from MacroFactor workouts)
  5.  Nutrition Report (meal timing in AI prompt)
  6.  Habits Deep-Dive
  7.  CGM Spotlight (UPDATED: fasting proxy, hypo flag, 7-day trend)
  8.  Gait & Mobility (NEW: walking speed, step length, asymmetry, double support)
  9.  Habit Streaks
  10. Weight Phase Tracker (weekly delta callout)
  11. Today's Guidance (AI-generated smart guidance)
  12. Journal Pulse
  13. Journal Coach
  14. Board of Directors Insight
  15. Anomaly Alert

Profile-driven: all targets read from DynamoDB PROFILE#v1. No hardcoded constants.
4 AI calls: Board of Directors, Training+Nutrition Coach, Journal Coach, TL;DR+Guidance.

v2.54.0: Board of Directors prompt dynamically built from s3://matthew-life-platform/config/board_of_directors.json
         Falls back to hardcoded _FALLBACK_BOD_PROMPT if S3 config unavailable.
"""

import json
import os
import math
import time
import boto3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# -- Configuration from environment variables (with backwards-compatible defaults) --
_REGION    = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET  = os.environ.get("S3_BUCKET", "")
USER_ID    = os.environ.get("USER_ID", "")
RECIPIENT  = os.environ.get("EMAIL_RECIPIENT", "")
SENDER     = os.environ.get("EMAIL_SENDER", "")
ANTHROPIC_SECRET = os.environ.get("ANTHROPIC_SECRET", "life-platform/ai-keys")

# BUG-11: Validate required env vars at startup with descriptive errors
_MISSING = [k for k, v in [("S3_BUCKET", S3_BUCKET), ("USER_ID", USER_ID),
                             ("EMAIL_RECIPIENT", RECIPIENT), ("EMAIL_SENDER", SENDER)] if not v]
if _MISSING:
    raise RuntimeError(f"daily-brief Lambda misconfigured — missing required env vars: {_MISSING}")

# BUG-10: Validate email format for recipient and sender
import re as _re
_EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
for _var, _addr in [("EMAIL_RECIPIENT", RECIPIENT), ("EMAIL_SENDER", SENDER)]:
    if not _EMAIL_RE.match(_addr):
        raise RuntimeError(f"daily-brief Lambda misconfigured — {_var}={_addr!r} is not a valid email address")

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
PROFILE_PK  = f"USER#{USER_ID}"


... [TRUNCATED — 2048 lines omitted, 2128 total]

```


### sick_day_checker.py — Sick day cross-cutting utility
```python

"""
Sick Day Checker — shared Lambda Layer utility.

Provides a lightweight DDB check so all Lambdas can test whether a given
date has been flagged as a sick/rest day without duplicating query logic.

DDB schema:
  pk  = USER#<user_id>#SOURCE#sick_days
  sk  = DATE#YYYY-MM-DD
  fields: date, reason (optional), logged_at, schema_version

Used by:
  character_sheet_lambda      — freeze EMA on sick days
  daily_metrics_compute_lambda — store grade="sick", preserve streaks
  anomaly_detector_lambda      — suppress alert emails
  freshness_checker_lambda     — suppress stale-source alerts
  daily_brief_lambda           — show recovery banner, skip coaching

v1.0.0 — 2026-03-09
"""

from datetime import datetime, timezone
from decimal import Decimal

SICK_DAYS_SOURCE = "sick_days"


def _d2f(obj):
    """Convert Decimal → float recursively."""
    if isinstance(obj, list):    return [_d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: _d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def check_sick_day(table, user_id, date_str):
    """Return sick day record dict for *date_str*, or None if not flagged.

    Safe to call from any Lambda — returns None on any error rather than raising.
    """
    pk = f"USER#{user_id}#SOURCE#{SICK_DAYS_SOURCE}"
    sk = f"DATE#{date_str}"
    try:
        resp = table.get_item(Key={"pk": pk, "sk": sk})
        item = resp.get("Item")
        return _d2f(item) if item else None
    except Exception as e:
        print(f"[WARN] sick_day_checker.check_sick_day({date_str}): {e}")
        return None


def get_sick_days_range(table, user_id, start_date, end_date):
    """Return list of sick day record dicts within a date range (inclusive).

    Returns empty list on any error.
    """
    pk = f"USER#{user_id}#SOURCE#{SICK_DAYS_SOURCE}"
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": pk,
                ":s":  f"DATE#{start_date}",
                ":e":  f"DATE#{end_date}",
            },
        )
        return [_d2f(i) for i in resp.get("Items", [])]
    except Exception as e:
        print(f"[WARN] sick_day_checker.get_sick_days_range({start_date}→{end_date}): {e}")
        return []


def write_sick_day(table, user_id, date_str, reason=None):
    """Write a sick day record. Idempotent — safe to call multiple times for the same date."""
    pk = f"USER#{user_id}#SOURCE#{SICK_DAYS_SOURCE}"
    sk = f"DATE#{date_str}"
    item = {
        "pk":             pk,
        "sk":             sk,
        "date":           date_str,

... [TRUNCATED — 14 lines omitted, 94 total]

```


### platform_logger.py — Structured logging module
```python

"""
platform_logger.py — OBS-1: Structured JSON logging for all Life Platform Lambdas.

Shared module. Drop-in replacement for the stdlib `logging` pattern used across
all 37 Lambdas. Every log line becomes a structured JSON object that CloudWatch
Logs Insights can query, filter, and alarm on.

USAGE (replaces `logger = logging.getLogger(); logger.setLevel(logging.INFO)`):

    from platform_logger import get_logger
    logger = get_logger("daily-brief")           # source name = lambda function name
    logger.info("Sending email", subject=subject, grade=grade)
    logger.warning("Stale data", source="whoop", age_hours=4.2)
    logger.error("AI call failed", attempt=3, error=str(e))

    # Structured log emitted to CloudWatch:
    {
      "timestamp": "2026-03-08T18:00:01.234Z",
      "level": "INFO",
      "source": "daily-brief",
      "correlation_id": "daily-brief#2026-03-08",
      "lambda": "daily-brief",
      "message": "Sending email",
      "subject": "Morning Brief | Sun Mar 8 ...",
      "grade": "B+"
    }

CORRELATION ID:
  Set once per Lambda execution via logger.set_date(date_str).
  Pattern: "{source}#{date}" — enables cross-Lambda log grouping in CWL Insights.
  Example query: `filter correlation_id like "2026-03-08"` shows ALL Lambda executions
  for that date.

MIGRATION PATTERN (for Lambdas not yet migrated):
  Old: `logger.info("Sending email: " + subject)`
  New: `logger.info("Sending email", subject=subject)`
  — keyword args become top-level JSON fields (searchable in CWL Insights)

BACKWARD COMPATIBILITY:
  PlatformLogger inherits logging.Logger so existing `logger.info(msg)` calls
  (positional only) continue to work unchanged. Migration can be incremental.

v1.0.0 — 2026-03-08 (OBS-1)
v1.0.1 — 2026-03-10 — *args %s compat for all log methods (Bug B fix)
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

# ── Constants ──────────────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
_LAMBDA_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "unknown")
_LAMBDA_VERSION = os.environ.get("AWS_LAMBDA_FUNCTION_VERSION", "$LATEST")

# Map stdlib level names → integers (for external callers that pass strings)
_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


class StructuredFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object.

    Standard fields always present:
      timestamp, level, source, lambda, correlation_id, message

    Additional fields: any keyword arguments passed to the log call
    (stored in `record.extra_fields` by PlatformLogger).
    """

    def format(self, record: logging.LogRecord) -> str:

... [TRUNCATED — 308 lines omitted, 388 total]

```


### ingestion_validator.py — Ingestion validation layer
```python

"""
ingestion_validator.py — DATA-2: Shared ingestion validation layer.

Validates incoming data items BEFORE writing to DynamoDB.
Invalid records are logged and written to S3 `validation-errors/` prefix
for audit. Critical validation failures skip DDB write entirely.

USAGE:

    from ingestion_validator import validate_item, validate_and_write

    result = validate_item("whoop", item, date_str="2026-03-08")
    if result.should_skip_ddb:
        logger.error("Skipping DDB write", errors=result.errors)
        result.archive_to_s3(s3_client, bucket)
        return
    if result.warnings:
        logger.warning("Validation warnings", warnings=result.warnings)

    table.put_item(Item=item)  # or safe_put_item()

VALIDATION RULES:

    Each source has:
      - required_fields: list of fields that MUST be present (critical if missing)
      - typed_fields: {field: type} — warns if value fails type check
      - range_checks: {field: (min, max)} — warns if value out of expected range
      - critical_range_checks: {field: (min, max)} — SKIPS write if out of range
      - at_least_one_of: list of fields — warns if ALL are absent

    Severity levels:
      CRITICAL — skip DDB write, archive to S3, log error
      WARNING  — write proceeds, issue logged and archived

SOURCES COVERED (20):
  whoop, garmin, apple_health, macrofactor, macrofactor_workouts, strava,
  eightsleep, withings, habitify, notion, todoist, weather, supplements,
  computed_metrics, character_sheet, day_grade, habit_scores,
  computed_insights, google_calendar, adaptive_mode
  (20 total: 13 ingestion + 6 compute + 1 calendar)

v1.0.0 — 2026-03-08 (DATA-2)
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal as _Decimal
from typing import Any

logger = logging.getLogger(__name__)
REGION = os.environ.get("AWS_REGION", "us-west-2")

# ── Validation result ──────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    source: str
    date_str: str
    errors: list[str] = field(default_factory=list)     # CRITICAL — skip write
    warnings: list[str] = field(default_factory=list)   # non-blocking

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    @property
    def should_skip_ddb(self) -> bool:
        return len(self.errors) > 0

    def archive_to_s3(self, s3_client, bucket: str, item: dict):
        """Write the rejected item to S3 validation-errors/ prefix for audit."""
        try:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            key = f"validation-errors/{self.source}/{self.date_str}/{ts}.json"
            payload = {
                "source": self.source,
                "date": self.date_str,

... [TRUNCATED — 483 lines omitted, 563 total]

```


### ai_output_validator.py — AI output safety layer
```python

"""
ai_output_validator.py — AI-3: Post-processing validation for AI coaching output.

Validates AI-generated coaching text AFTER generation, BEFORE delivery.
Catches dangerous recommendations, empty/truncated output, and advice that
conflicts with the user's known health context.

USAGE (in ai_calls.py or any Lambda after receiving AI output):

    from ai_output_validator import validate_ai_output, AIOutputType

    result = validate_ai_output(
        text=bod_insight,
        output_type=AIOutputType.BOD_COACHING,
        health_context={"recovery_score": 18, "tsb": -22},
    )

    if result.blocked:
        logger.error("AI output blocked", reason=result.block_reason)
        return result.safe_fallback   # use fallback text instead

    if result.warnings:
        logger.warning("AI output warnings", warnings=result.warnings)

    final_text = result.sanitized_text   # safe to use

VALIDATION TIERS:

    BLOCK  — output is replaced with safe_fallback. Used for:
             - Empty/None output (Lambda crash protection)
             - Dangerous exercise recs with red recovery (injury risk)
             - Severely dangerous caloric guidance (< 800 kcal)
             - Output clearly truncated mid-sentence

    WARN   — output used as-is, warning logged. Used for:
             - Aggressive training language with borderline recovery
             - High-calorie surplus recommendation (unusual for this user)
             - Generic phrases that suggest context was ignored
             - Correlation presented as causation with low-confidence signal

    PASS   — no issues detected

DISCLAIMER:
    All AI output validated by this module should still include the footer:
    "AI-generated analysis, not medical advice." (AI-1 requirement)
    This module validates logical safety, not medical accuracy.

v1.1.0 — 2026-03-13 (TB7-19: hallucinated data reference detection)
  - _METRIC_PATTERNS: 7 metric patterns (recovery, HRV, resting HR, sleep score, weight, TSB)
  - _check_hallucinated_metrics(): cross-refs text numbers against health_context ±25%
  - Check 12 in validate_ai_output(): WARN when claimed metrics deviate >25% from actual
v1.0.0 — 2026-03-08 (AI-3)
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


# ── Output types ───────────────────────────────────────────────────────────────

class AIOutputType(str, Enum):
    BOD_COACHING   = "bod_coaching"      # Board of Directors 2-3 sentence coaching
    TLDR           = "tldr"              # TL;DR one-liner
    GUIDANCE       = "guidance"          # Smart guidance bullet item
    TRAINING_COACH = "training_coach"    # Training coach section
    NUTRITION_COACH = "nutrition_coach"  # Nutrition coach section
    JOURNAL_COACH  = "journal_coach"     # Journal reflection + tactical
    CHRONICLE      = "chronicle"         # Weekly chronicle narrative
    WEEKLY_DIGEST  = "weekly_digest"     # Weekly digest coaching
    MONTHLY_DIGEST = "monthly_digest"    # Monthly digest coaching
    GENERIC        = "generic"           # Unknown — minimal checks only


# ── Validation result ──────────────────────────────────────────────────────────


... [TRUNCATED — 513 lines omitted, 593 total]

```


### digest_utils.py — Shared digest utilities
```python

"""
digest_utils.py — Shared utilities for digest Lambdas (v1.0.0)

Extracted from weekly_digest_lambda.py and monthly_digest_lambda.py to eliminate
duplication, fix bugs, and ensure consistent behaviour across all digest cadences.

Consumers:
  - weekly_digest_lambda.py
  - monthly_digest_lambda.py

Contents:
  - Pure scalar helpers: d2f, avg, fmt, fmt_num, safe_float
  - dedup_activities
  - _normalize_whoop_sleep
  - List-based extractors: ex_whoop_from_list, ex_whoop_sleep_from_list, ex_withings_from_list
  - Banister: compute_banister_from_list, compute_banister_from_dict
"""

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal


# ══════════════════════════════════════════════════════════════════════════════
# PURE SCALAR HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def d2f(obj):
    """Recursively convert DynamoDB Decimal values to float."""
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def avg(vals):
    """Mean of a list, ignoring None values. Returns None for empty input."""
    v = [x for x in vals if x is not None]
    return round(sum(v) / len(v), 1) if v else None


def fmt(val, unit="", dec=1):
    """Format a number with optional unit; returns em-dash for None."""
    return "\u2014" if val is None else f"{round(val, dec)}{unit}"


def fmt_num(val):
    """Format a number with thousands separator; returns em-dash for None."""
    if val is None:
        return "\u2014"
    return "{:,}".format(round(val))


def safe_float(rec, field, default=None):
    """Safely extract a float from a dict record."""
    if rec and field in rec:
        try:
            return float(rec[field])
        except Exception:
            return default
    return default


# ══════════════════════════════════════════════════════════════════════════════
# ACTIVITY DEDUP  (Strava/Garmin duplicate removal)
# ══════════════════════════════════════════════════════════════════════════════

def dedup_activities(activities):
    """Remove duplicate activities within a 15-minute window.

    Keeps the richer record (higher richness score). Records without a parseable
    start_date_local are kept unconditionally. Handles Garmin->Strava auto-sync
    duplicates where the same session appears twice with different metadata.
    """
    if not activities or len(activities) <= 1:
        return activities

    def parse_start(a):
        s = a.get("start_date_local") or a.get("start_date") or ""
        try:

... [TRUNCATED — 287 lines omitted, 367 total]

```


### mcp/handler.py (first 60 lines)
```python

"""
Lambda handler and MCP protocol implementation.

Supports two transport modes:
1. Remote MCP (Streamable HTTP via Function URL) — for claude.ai, mobile, desktop
2. Local bridge (direct Lambda invoke via boto3) — legacy Claude Desktop bridge

The remote transport implements MCP Streamable HTTP (spec 2025-06-18):
- POST / — JSON-RPC request/response
- HEAD / — Protocol version discovery
- GET /  — 405 (no SSE support in Lambda)

OAuth: Minimal auto-approve flow to satisfy Claude's connector requirement.
Security is provided by the unguessable 40-char Lambda Function URL, not OAuth.
"""
import json
import logging
import base64
import uuid
import hmac
import hashlib
import time
import concurrent.futures
import urllib.parse

from mcp.config import logger, __version__
from mcp.core import get_api_key, decimal_to_float
from mcp.registry import TOOLS
from mcp.utils import validate_date_range, validate_single_date, mcp_error
from mcp.warmer import nightly_cache_warmer

# ── MCP protocol constants ────────────────────────────────────────────────────
MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_PROTOCOL_VERSION_LEGACY = "2024-11-05"

# Headers included in all remote MCP responses
_MCP_HEADERS = {
    "Content-Type": "application/json",
    "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    "Cache-Control": "no-cache",
}


# ── MCP protocol handlers ─────────────────────────────────────────────────────
def handle_initialize(params):
    # Negotiate protocol version — support both current and legacy
    client_version = params.get("protocolVersion", MCP_PROTOCOL_VERSION_LEGACY)
    server_version = (MCP_PROTOCOL_VERSION
                      if client_version >= "2025"
                      else MCP_PROTOCOL_VERSION_LEGACY)

    return {
        "protocolVersion": server_version,
        "capabilities":    {"tools": {}},
        "serverInfo":      {"name": "life-platform", "version": __version__},
    }


def handle_tools_list(_params):
    return {"tools": [t["schema"] for t in TOOLS.values()]}

... [TRUNCATED — 543 lines omitted, 603 total]

```


---

## 13. PREVIOUS REVIEW GRADES


| Dimension | #1 (v2.91) | #2 (v3.1.3) | #3 (v3.3.10) | #4 (v3.4.1) | #13 (v3.7.29) |
|-----------|-----------|-----------|-------------|-------------|---------------|
| Architecture | B+ | B+ | A- | A | A |
| Security | C+ | B+ | B+ | A- | A- |
| Reliability | B- | B+ | B+ | B+ | A- |
| Operability | C+ | B- | B+ | B+ | B+ |
| Cost | A | A | A | A | A+ |
| Data Quality | B | B+ | B+ | A- | A |
| AI/Analytics | C+ | B- | B | B | B+ |
| Maintainability | C | B- | B | B+ | B+ |
| Production Readiness | D+ | C | B- | B | B+ |


**Last review source file: `REVIEW_CHARACTER_LEVELING_2026-03-30.md`**


### Last Review Findings (read this before flagging ANY new finding)

# Character Leveling System — Statistical & Mathematical Review

**Review Lead:** Dr. Henning Brandt, Biostatistician (Technical Board)
**Date:** 2026-03-30
**Engine Version Reviewed:** `character_engine.py` v1.0.0
**Config Version Reviewed:** `character_sheet.json` v1.0.0
**Status:** REVIEW COMPLETE — 14 findings, 7 critical

---

## Panel Composition

Dr. Henning Brandt convened the following review panel. Each member was selected for domain expertise directly relevant to the mathematical, statistical, or behavioral design challenges of turning multi-source health data into a single leveling system.

| Panelist | Role | Board | Why They're Here |
|----------|------|-------|-----------------|
| **Dr. Henning Brandt** | Review Lead — Statistical Validity | Technical | Cochrane-grade biostatistician. Owns every calculation, weighting decision, and statistical method in the engine. |
| **Dr. Anika Patel** | AI/LLM & Scoring Systems | Technical | Composite scoring is an ML-adjacent problem. Anika reviews whether the scoring functions produce sensible gradients and whether the EMA is the right smoothing choice. |
| **Omar Khalil** | Data Architecture & Completeness | Technical | The engine consumes data from 20+ sources. Omar reviews whether missing data, sparse partitions, and source outages distort scores in ways the math doesn't account for. |
| **Coach Maya Rodriguez** | Behavioral Design & Motivation | Personal | Maya designed the asymmetric leveling rules. She reviews whether the math actually produces the behavioral outcomes she specified (2–4 level-ups/month, no flip-flop, no punishment framing). |
| **Dr. Lena Johansson** | Scientific Defensibility | Product | If a reader asks "why is Sleep 20% and Relationships 7%?" — Lena needs the answer to be grounded in published evidence, not gut feel. |
| **Raj Srinivasan** | Founder Lens — Gaming & Edge Cases | Technical | Raj stress-tests systems. He looks for ways the scoring can be gamed, produce absurd results, or create perverse incentives. |
| **Dr. Lisa Park** | Sleep Science — Cross-Pillar Effects | Personal | Lisa designed the Sleep Drag mechanic. She validates whether the cross-pillar effect magnitudes match the clinical evidence for sleep deprivation's downstream impact. |
| **Dr. Marcus Webb** | Nutrition — Component Weighting | Personal | Marcus owns the Nutrition pillar. He reviews whether the 60/40 behavior-outcome split and body composition curve are mathematically sound. |

---

## 1. Executive Summary

**Overall Assessment: The engine is structurally sound but mathematically incomplete.**

The character leveling system implements a defensible high-level architecture: 7 weighted pillars → component scores → weighted aggregation → EMA smoothing → streak-gated level changes → XP accumulation. The anti-flip-flop design (asymmetric streaks, tier boundary gates) is well-conceived and implements Coach Maya's behavioral specification correctly.

However, this review identifies **14 findings across 5 severity levels** — 7 of which are critical and should be addressed before the system is considered "bulletproof" for public-facing use. The most consequential issues are:

1. **Missing data bias** — the engine doesn't distinguish between "no data available" and "bad performance," producing systematically inflated or deflated scores depending on which sources go offline.
2. **Pillar weight justification** — the current weights (Sleep 20%, Movement 18%, etc.) are defensible but not documented against evidence. A reader who asks "why?" gets no answer.
3. **XP is unbounded and monotonically accumulated** — creating a scenario where someone at Level 80 with massive XP can coast for months without meaningful consequences.
4. **The body composition component (40% of Nutrition)** is a one-directional progress curve that will break when Matthew reaches goal weight.
5. **Cross-pillar effects use additive vs. multiplicative modifiers inconsistently** — the code applies them as `ls * (1 + mod)` when `|mod| < 1` but `ls + mod` otherwise, which creates discontinuities.
6. **The Relationships pillar relies on sparse, subjective data** that produces unstable scores — yet it carries 7% of the overall character level.
7. **Consistency meta-pillar creates a circular dependency** — it scores the variance of the other 6 pillars, but itself contributes to the weighted average those pillars feed into.

None of these are unfixable. Several have straightforward mathematical solutions. The recommendations below are ordered by impact.

---

## 2. Pillar Weight Review

### Current Weights

| Pillar | Weight | Cumulative |
|--------|--------|------------|
| Sleep | 20% | 20% |
| Movement | 18% | 38% |
| Nutrition | 18% | 56% |
| Mind | 15% | 71% |
| Metabolic | 12% | 83% |
| Consistency | 10% | 93% |
| Relationships | 7% | 100% |

### Henning's Assessment

The weights produce a reasonable hierarchy but lack formal justification. Here is the evidence basis I would use to defend or adjust each:

**Sleep (20%) — DEFENSIBLE.** Meta-analyses (Cappuccio et al., 2010; Itani et al., 2017) consistently show sleep duration and quality as independent predictors of all-cause mortality with hazard ratios of 1.12–1.30 for short sleep. The 20% weight is appropriate. If anything, given the cross-pillar effects (Sleep Drag), sleep's *effective* contribution exceeds 20%.

**Movement (18%) — DEFENSIBLE but should note VO2max gap.** Physical activity is the single strongest modifiable predictor of longevity (Mandsager et al., 2018 — elite fitness = 5x mortality reduction vs. low fitness). The 18% weight undersells this slightly, but the cross-pillar Training Boost partially compensates.

**Nutrition (18%) — REQUIRES SCRUTINY.** The 40% body composition sub-weight is the largest single component in the entire system. Dr. Webb's reasoning (60% behavior + 40% outcome) is sound *during weight loss*, but the mathematical curve is a pure linear interpolation that breaks at goal weight. See Finding F-04.

**Mind (15%) — DEFENSIBLE but heterogeneous.** This pillar conflates habit compliance, journaling, emotional valence, stress, and vice control — six quite different constructs. Consider splitting into Discipline (behavioral) and Wellbeing (outcome) in v2.

**Metabolic (12%) — DEFENSIBLE with lab decay caveat.** See Finding F-07.

**Consistency (10%) — CIRCULAR DEPENDENCY ISSUE.** See Finding F-06.

**Relationships (7%) — DATA QUALITY CONCERN.** See Finding F-08.

---

## 3. Findings

### F-01: Missing Data Produces Systematic Bias (CRITICAL)

**Severity:** Critical
**Owner:** Henning + Omar
**Components Affected:** All pillars, `_weighted_pillar_score()`

**Current behavior:** When a component score is `None` (no data), `_weighted_pillar_score()` excludes it from both numerator and denominator — effectively redistributing its weight to the remaining components.

**The problem:** This creates two failure modes:

**Mode A — Inflation.** If the hardest-to-score components go missing (e.g., no CGM data, no lab results, no journal), the pillar score is computed from only the easy/high-scoring components.

**Mode B — Volatility.** When a source comes back online after an outage, the denominator suddenly increases and the score can jump or drop dramatically.

**Recommendation — Implement Confidence-Weighted Scoring:**

```python
def _weighted_pillar_score_v2(component_scores, components_config):
    weighted_sum = 0.0
    total_weight = 0.0
    available_weight = 0.0
    max_possible_weight = 0.0
    details = {}

    for comp_name, score in component_scores.items():
        weight = components_config.get(comp_name, {}).get("weight", 0)
        max_possible_weight += weight
        details[comp_name] = {"score": score, "weight": weight}
        if score is not None and weight > 0:
            weighted_sum += score * weight
            total_weight += weight
            available_weight += weight

    if total_weight == 0:
        return 50.0, details, 0.0  # neutral + zero confidence

    raw_score = weighted_sum / total_weight
    data_coverage = available_weight / max_possible_weight if max_possible_weight > 0 else 0
    confidence = min(1.0, data_coverage / 0.80)
    adjusted_score = raw_score * confidence + 50.0 * (1.0 - confidence)
    
    details["_confidence"] = round(confidence, 3)
    details["_data_coverage"] = round(data_coverage, 3)
    
    return round(_clamp(adjusted_score), 1), details, confidence
```

---

### F-02: XP Accumulation is Unbounded and Non-Decaying (CRITICAL)

**Severity:** Critical
**Owner:** Henning + Maya

**Current behavior:** XP accumulates monotonically. The -1 penalty at <20 raw score is negligible compared to daily +1/+2/+3 gains. After 6 months, XP is in the thousands with no function.

**Recommendation — XP as Level Stability Buffer:**

```
XP_PER_LEVEL = 100
DAILY_XP_DECAY = 2

Per pillar per day:
  xp_earned = xp_band_lookup(raw_score)
  xp_total = max(0, previous_xp + xp_earned - DAILY_XP_DECAY)
  level_xp_buffer = xp_total % XP_PER_LEVEL
  can_level_down = (streak_below >= threshold) AND (level_xp_buffer < 20)
```

This makes XP functional: high XP = earned resilience, low XP = fragile hold on current level.

---

### F-03: EMA Smoothing — Per-Pillar Lambda (HIGH)

**Severity:** High
**Owner:** Henning + Anika

**Current:** λ=0.85 globally (half-life ~4.3 days).

**Recommendation:** Per-pillar EMA lambda in config:

| Pillar | λ | Half-Life | Reasoning |
|--------|---|-----------|-----------|
| Sleep | 0.85 | ~4 days | Sleep debt recovers within a week |
| Movement | 0.90 | ~7 days | Training adaptations over weeks |
| Nutrition | 0.88 | ~5 days | Weekly caloric balance |
| Metabolic | 0.95 | ~14 days | Biomarkers change slowly |
| Mind | 0.85 | ~4 days | Emotional state highly variable |
| Relationships | 0.93 | ~10 days | Social connection is stable |
| Consistency | 0.93 | ~10 days | Measured over longer windows |

---

### F-04: Body Composition Curve Breaks at Goal Weight (CRITICAL)

**Severity:** Critical
**Owner:** Henning + Marcus

**Current:** Linear interpolation `(start - current) / (start - goal) * 100`. No maintenance phase implemented.

**Recommendation — Two-Phase with Sigmoid:**

Loss phase: Sigmoid curve that front-loads credit for early momentum.
Maintenance phase: Score 100 within ±3lb band, linear drop outside.

```python
def _body_comp_score(current_weight, config):
    phase = config.get("baseline", {}).get("weight_phase", "loss")
    if phase == "loss":
        progress = (start - current) / (start - goal)
        score = 100 / (1 + math.exp(-8 * (progress - 0.5)))
    elif phase == "maintenance":
        deviation = abs(current - goal)
        if deviation <= band: return 100.0
        score = 100 - ((deviation - band) / (20 - band)) * 100
    return _clamp(score)
```

Add `weight_phase` and `maintenance_band_lbs` to config.

---

### F-05: Cross-Pillar Effects — Inconsistent Modifier Application (HIGH)

**Severity:** High

**Current code:** `adjusted = ls * (1 + mod) if abs(mod) < 1 else ls + mod` — creates a discontinuity at mod=1.

**Recommendation:** Add explicit `type` field to effect targets:

```json
{ "type": "multiplicative", "value": -0.08 }
```

Convert the Alignment Bonus from additive +2 to multiplicative +3%.

---

### F-06: Consistency Pillar — Circular Dependency (MEDIUM)

**Severity:** Medium

Consistency scores the variance of the other 6 pillars but contributes to the average. At 10% weight (4% effective via the variance component), the mathematical impact is bounded to ±4 points. Acceptable for v1. Document the known circularity.

---

### F-07: Lab Biomarker Decay Function (MEDIUM)

**Severity:** Medium

**Current:** Floor at 0.5 after 90 days (forever).

**Recommendation:** Continue decay to 0.0 at 180 days. Six-month-old labs should not contribute to metabolic health scoring.

---

### F-08: Relationships Pillar — Sparse Data (MEDIUM)

**Severity:** Medium

All 4 components rely on Notion journal entries. No journal = all None = score 40.0 (default). Creates massive day-to-day volatility.

**Recommendation:** Use 14-day rolling window for Relationships scoring (Option B). Add `log_social_interaction` MCP tool on roadmap (Option C).

---


... [TRUNCATED — 63 lines omitted, 313 total]


---

## 13b. RESOLVED FINDINGS INVENTORY


> **REVIEWER INSTRUCTION:** Before issuing ANY finding in this review, check this table.
> If the finding appears here as RESOLVED, do NOT re-issue it. Instead, verify the
> resolution is adequate and note it as confirmed-resolved in your output.
> Re-issuing resolved findings wastes review budget and creates noise.

### R13 Findings — All Resolved (as of 2026-03-15, v3.7.40)

| ID | Finding | Status | Version | Proof |
|----|---------|--------|---------|-------|
| R13-F01 | No CI/CD pipeline | ✅ RESOLVED | Already existed | `.github/workflows/ci-cd.yml` — 7 jobs: lint, test (9 linters), plan (cdk synth+diff), manual approval gate, deploy, smoke test, auto-rollback. OIDC auth. |
| R13-F02 | No integration tests for critical path | ✅ RESOLVED | v3.7.38 | `tests/test_integration_aws.py` I1–I13: Lambda handlers, layer versions, DDB health, secrets, EventBridge, S3, DLQ, alarms, MCP invocability, data-reconciliation, MCP tool response shape, freshness data. |
| R13-F03 | MCP monolith split assessment | N/A | — | Deferred: <100 calls/day. |
| R13-F04 | CI secret reference linter | ✅ RESOLVED | v3.7.35 | `tests/test_secret_references.py` SR1–SR4. Wired into `ci-cd.yml` test job. |
| R13-F05 | OAuth fail-open default | ✅ RESOLVED | v3.7.35 | `mcp/handler.py` `_get_bearer_token()` returns sentinel `"__NO_KEY_CONFIGURED__"`, `_validate_bearer()` fail-closed. |
| R13-F06 | Correlation n-gating missing | ✅ RESOLVED | v3.7.36 | `mcp/tools_training.py` `tool_get_cross_source_correlation`: n≥14 hard min, label downgrade, p-value, 95% CI via Fisher z. |
| R13-F07 | No PITR restore drill | ⏳ PENDING | — | First drill scheduled ~Apr 2026. Runbook written at v3.7.17. |
| R13-F08 | Layer version CI test | ✅ RESOLVED | v3.7.38 | `tests/test_layer_version_consistency.py` LV1–LV5. `cdk/stacks/constants.py` is single source of truth for layer version (LV1 caught real duplication bug). |
| R13-F08-dur | No duration alarms | ✅ RESOLVED | v3.7.36 | `deploy/create_duration_alarms.sh`: `life-platform-daily-brief-duration-p95` (>240s) + `life-platform-mcp-duration-p95` (>25s). |
| R13-F09 | No medical disclaimers in MCP health tools | ✅ RESOLVED | v3.7.35–36 | `_disclaimer` field in `tool_get_health()`, `tool_get_cgm()`, `tool_get_readiness_score()`, `tool_get_blood_pressure_dashboard()`, `tool_get_blood_pressure_correlation()`, `tool_get_hr_recovery_trend()`. |
| R13-F10 | `d2f()` duplicated across Lambdas | ✅ RESOLVED (annotated) | v3.7.37 | `weekly_correlation_compute_lambda.py` annotated; canonical copy in `digest_utils.py` (shared layer). Full dedup deferred to layer v12. |
| R13-F11 | DST timing in EventBridge | Documented, not mitigated | — | Low-impact; documented in ARCHITECTURE.md. |
| R13-F12 | No rate limiting on MCP write tools | ✅ RESOLVED | v3.7.35 | `mcp/handler.py` `_check_write_rate_limit()`: 10 calls/invocation on `create_todoist_task`, `delete_todoist_task`, `log_supplement`, `write_platform_memory`, `delete_platform_memory`. |
| R13-F14 | No MCP endpoint canary | ✅ RESOLVED | v3.7.40 | EventBridge rule `rate(15 minutes)` → canary. Alarms: `life-platform-mcp-canary-failure-15min`, `life-platform-mcp-canary-latency-15min`. |
| R13-F15 | Weekly correlation lacks FDR correction | ✅ RESOLVED | v3.7.37 | `weekly_correlation_compute_lambda.py` Benjamini-Hochberg FDR correction, `pearson_p_value()`, per-pair `p_value`/`p_value_fdr`/`fdr_significant`. |
| R13-XR | No X-Ray tracing on MCP | ✅ RESOLVED | v3.7.40 | `cdk/stacks/mcp_stack.py` `tracing=_lambda.Tracing.ACTIVE`. IAM: `xray:PutTraceSegments` etc. in `mcp_server()` policy. |


### R17 Findings (2026-03-20, v3.7.82)

| ID | Finding | Status | Version | Proof |
|----|---------|--------|---------|-------|
| R17-F01 | Public AI endpoints lack persistent rate limiting | ✅ RESOLVED | v4.3.0 | WAF WebACL deployed with SubscribeRateLimit (60/5min) and GlobalRateLimit (1000/5min) |
| R17-F02 | In-memory rate limiting resets on cold start | ✅ RESOLVED | v4.3.0 | WAF at CloudFront edge provides persistent rate limiting independent of Lambda lifecycle |
| R17-F03 | No WAF on public-facing CloudFront | ✅ RESOLVED | v4.3.0 | WAF WebACL attached to E3S424OXQZ8NBE |
| R17-F04 | Subscriber email verification has no rate limit | ✅ RESOLVED | v4.3.0 | WAF SubscribeRateLimit rule covers /api/subscribe* at 60/5min per IP |
| R17-F05 | Cross-region DynamoDB reads (site-api) | ✅ RESOLVED | v4.3.0 | Site-api confirmed in us-west-2 (AWS CLI verification 2026-03-30) |
| R17-F06 | No observability on public API endpoints | ⏳ PARTIAL | — | AskEndpointErrors alarm added. Structured route logging deployed v4.5.1. |
| R17-F07 | CORS headers not evidenced | ✅ RESOLVED | v4.3.1 | CORS_HEADERS dict + OPTIONS handler confirmed in site_api_lambda.py |
| R17-F08 | google_calendar in config.py SOURCES | ✅ RESOLVED | v4.3.1 | Retired file only, not in active SOURCES list |
| R17-F09 | MCP Lambda memory discrepancy in docs | ✅ RESOLVED | v4.3.1 | Doc headers reconciled to 118 tools (v4.5.0) |
| R17-F10 | Site API hardcoded model strings | ✅ RESOLVED | v4.3.1 | Using os.environ.get() pattern |
| R17-F11 | No privacy policy on public website | ✅ RESOLVED | v4.3.0 | /privacy/ directory exists |
| R17-F12 | PITR restore drill not executed | ✅ RESOLVED | v4.5.1 | Drill executed 2026-03-30 (Phase 3 of remediation plan) |
| R17-F13 | 95 MCP tools — context window pressure | ✅ RESOLVED | v4.5.1 | ADR-045 formally accepts 118 as operating state |

### R18 Findings (2026-03-28, v4.3.0)

| ID | Finding | Status | Version | Proof |
|----|---------|--------|---------|-------|
| R18-F01 | Severe documentation drift | ✅ RESOLVED | v4.5.1 | ARCHITECTURE.md body reconciled, INFRASTRUCTURE.md full update, INCIDENT_LOG updated |
| R18-F02 | CLI-created Lambdas outside CDK | ✅ RESOLVED | v4.5.1 | CDK adoption audit completed. Unmanaged Lambdas documented and adoption planned. |
| R18-F03 | lambda_map.json stale | ✅ RESOLVED | v4.3.1 | Updated with all new Lambdas. CI orphan-file lint added. |
| R18-F04 | New resources without monitoring | ✅ RESOLVED | v4.3.1 | Alarms added for og-image, food-delivery, challenge, email-subscriber. Pipeline health check covers rest. |
| R18-F05 | 47-page manual S3 deploy | ✅ RESOLVED | v4.3.1 | deploy/deploy_site.sh created |
| R18-F06 | WAF rules too broad | ✅ RESOLVED | v4.3.1 | Endpoint-specific rules: /api/ask (100/5min), /api/board_ask (100/5min) |
| R18-F07 | SIMP-1 regression (95→110) | ✅ RESOLVED | v4.5.1 | ADR-045 formally accepts 118 as operating state |
| R18-F08 | INTELLIGENCE_LAYER.md stale | ✅ RESOLVED | v4.5.2 | Full refresh — freeze label removed, all IC statuses updated |
| R18-F09 | Cross-region split on 13+ routes | ✅ RESOLVED | v4.3.0 | Site-api confirmed us-west-2 (AWS CLI 2026-03-30). No cross-region reads. |


### R19 Findings (2026-03-30, v4.5.0)

| ID | Finding | Status | Version | Proof |
|----|---------|--------|---------|-------|
| R19-F01 | INFRASTRUCTURE.md entirely stale (v4.2.1 state) | ✅ RESOLVED | v4.5.2 + v4.9.0 | Full update in v4.5.2 doc sprint. Second pass v4.9.0: Lambda categories reconciled (16+11+12+21+2=62), MCP 115, alarms ~66, missing Lambdas added. |
| R19-F02 | ARCHITECTURE.md internal contradictions (5+ conflicts) | ✅ RESOLVED | v4.5.2 + v4.9.0 | Body-section counts reconciled in v4.5.2. Second pass v4.9.0: local project structure updated (Lambda categories, us-west-2 site-api, shared modules, 35-module MCP). |
| R19-F03 | INCIDENT_LOG missing 5 v4.4.0 pipeline failures | ✅ RESOLVED | v4.5.2 | All 5 incidents added with P-levels, TTD, TTR. Patterns section updated with silent secret deletion class. |
| R19-F04 | SLOs reference stale data sources | ✅ RESOLVED | v4.9.0 | Google Calendar removed. Monitored sources expanded from 10 to 13 (added Weather, Food Delivery, Measurements). |
| R19-F05 | 118 MCP tools (4th consecutive review) | ✅ RESOLVED | v4.5.1 | ADR-045 formally accepts tool count as operating state. Current count: 115 (reduced from 118). |
| R19-F06 | Site-API region contradicts Function URL | ✅ RESOLVED | v4.3.0 | AWS CLI verification confirmed us-west-2. Docs updated. |
| R19-F07 | Section 13b not updated for R17/R18 | ✅ RESOLVED | v4.5.2 + v4.9.0 | R17, R18, R19 findings all added to generate_review_bundle.py Section 13b. |


---

## 14. SCHEMA SUMMARY

## Key Structure

| Attribute | Description |
|-----------|-------------|
| `pk` | Partition key — identifies the entity type and owner |
| `sk` | Sort key — enables range queries and versioning |



## Sources

Valid source identifiers: `whoop`, `withings`, `strava`, `todoist`, `apple_health`, `hevy`, `eightsleep`, `chronicling`, `macrofactor`, `macrofactor_workouts`, `garmin`, `habitify`, `notion`, `labs`, `dexa`, `genome`, `supplements`, `weather`, `travel`, `state_of_mind`, `habit_scores`, `character_sheet`, `computed_metrics`, `platform_memory`, `insights`, `decisions`, `hypotheses`, `chronicle`, `measurements`, `food_delivery`

Note: `hevy` and `chronicling` are historical/archived sources — not actively ingesting. `habit_scores`, `character_sheet`, `computed_metrics`, `platform_memory`, `insights`, `decisions`, and `hypotheses` are derived/computed partitions, not raw ingested data.

Ingestion methods: API polling (scheduled Lambda), S3 file triggers (manual export), **webhook** (Health Auto Export push — also handles BP and State of Mind), **MCP tool write** (supplements), **on-demand fetch + scheduled Lambda** (weather)

---


---

## 15. DOCUMENTATION INVENTORY

**Root docs (73 files):** ARCHITECTURE.md, A_GRADE_PHASE6_SUPPLEMENT.md, A_GRADE_REMEDIATION_PLAN.md, BACKLOG_HANDOFF_CLAUDE_CODE.md, BOARDS.md, CHANGELOG.md, CHANGELOG_ARCHIVE.md, CLAUDE_CODE_BRIEF_2026-03-28.md, CLAUDE_CODE_REMEDIATION_PROMPT.md, CLAUDE_CODE_SPEC_OBSERVATORY_V2_REMAINING.md, CONTENT_AUDIT.md, COST_TRACKER.md, DATA_FLOW_DIAGRAM.md, DECISIONS.md, DEPENDENCY_GRAPH.md, DISCORD_INTEGRATION_SPEC.md, DISCOVERIES_EVOLUTION_SPEC.md, EXPERIMENTS_EVOLUTION_SPEC.md, FIELD_NOTES_SPEC.md, FN-01_FIRST_PERSON_BUILD.md, FOOD_DELIVERY_SPEC.md, HANDOVER_LATEST.md, HOME_EVOLUTION_SPEC.md, IMPL_SUBSCRIBER_EMAIL_REDESIGN.md, INCIDENT_LOG.md, INFRASTRUCTURE.md, INTELLIGENCE_LAYER.md, LAUNCH_DAY.md, LAUNCH_READINESS_IMPL_SPEC.md, LEDGER_SPEC_FINAL.md, MCP_TOOL_CATALOG.md, MCP_TOOL_TIERING_DESIGN.md, MEASUREMENTS_IMPLEMENTATION_SPEC.md, OBSERVATORY_UPGRADE_SPEC.md, OBSERVATORY_V2_SPEC.md, OFFSITE_BUILD_PLAN.md, OFFSITE_BUILD_PLAN_2026-03-27.md, OFFSITE_BUILD_PLAN_PART3.md, OFFSITE_BUILD_PLAN_PART4.md, OFFSITE_FEATURE_LIST.md, OFFSITE_FEATURE_LIST_PART3.md, OFFSITE_FEATURE_LIST_PART4.md, OFFSITE_PART3_PROMPT.md, OFFSITE_PART4_PROMPT.md, OFFSITE_PRIORITY_SPEC.md, ONBOARDING.md, OPERATOR_GUIDE.md, PLATFORM_GUIDE.md, PROJECT_PLAN.md, PROJECT_PLAN_ARCHIVE.md, PULSE_REDESIGN_SPEC.md, QUICKSTART.md, R18_REMEDIATION_PROMPT.md, REVIEW_METHODOLOGY.md, REVIEW_RUNBOOK.md, RUNBOOK.md, SCHEMA.md, SIMP1_PLAN.md, SLOs.md, SPRINT_PLAN.md, STATUS_PAGE_SPEC.md, STORY_ABOUT_REVIEW_SPEC.md, USABILITY_BRIEF_PROMPT.md, V2_PAGE_DESIGN_BRIEFS.md, VISUAL_ASSET_BRIEF.md, VISUAL_DECISIONS.md, WEBSITE_REDESIGN_SPEC.md, WEBSITE_ROADMAP.md, WEBSITE_STRATEGY.md, reader-engagement-implementation-plan.md, sec3_input_validation_assessment.md, usability_implementation_brief.md, usability_study.md


**docs/archive/ (18 files):** AUDIT_PROD2_MULTI_USER.md, AVATAR_DESIGN_STRATEGY.md, BOARD_DERIVED_METRICS_PLAN.md, CHANGELOG_v341.md, DATA_DICTIONARY_archived_v3.7.32.md, DERIVED_METRICS_PLAN.md, DESIGN_PROD1_CDK.md, DESIGN_SIMP2_INGESTION.md, FEATURES_archived_v3.7.32.md, NOTION_ENRICHMENT_SPEC.md, NOTION_JOURNAL_SPEC.md, SCHEMA_LABS_ADDITION.md, SCOPING_LARGE_OPUS.md, SPEC_CHARACTER_SHEET.md, USER_GUIDE_archived_v3.7.32.md, avatar-design-strategy.md, data-source-audit-2026-02-24.md, wednesday-chronicle-design.md


**docs/audits/ (6 files):** AUDIT_2026-03-21_website.md, AUDIT_2026-03-30_alarm_coverage.md, AUDIT_2026-03-30_cdk_adoption.md, AUDIT_2026-03-30_pitr_drill.md, AUDIT_2026-03-30_security.md, IAM_AUDIT_2026-03-08.md


**docs/briefs/ (2 files):** BRIEF_2026-03-26_arena_lab_v2.md, BRIEF_2026-03-26_design_brief.md


**docs/content/ (3 files):** ELENA_PREQUEL_BRIEF.md, STORY_DRAFTS_v1.md, STORY_INTERVIEW_FULL.md


**docs/design/ (1 files):** MULTI_USER_ISOLATION.md


**docs/rca/ (2 files):** PIR-2026-02-28-ingestion-outage.md, RCA_2026-02-24_apple_health_pipeline.md


**docs/reviews/ (34 files):** BOARD_SPRINT_REVIEW_2026-03-16.md, BOARD_SUMMIT_2026-03-16.md, BOARD_SUMMIT_2_2026-03-17.md, BOARD_SUMMIT_2_2026-03-17_POINTER.md, IMPLEMENTATION_PLAN_WR4.md, REVIEW_2026-03-08.md, REVIEW_2026-03-08_v2.md, REVIEW_2026-03-09.md, REVIEW_2026-03-09_full.md, REVIEW_2026-03-10.md, REVIEW_2026-03-10_full.md, REVIEW_2026-03-10_v6.md, REVIEW_2026-03-11_v7.md, REVIEW_2026-03-14_v13.md, REVIEW_2026-03-15_v14.md, REVIEW_2026-03-15_v15.md, REVIEW_2026-03-15_v16.md, REVIEW_2026-03-20_v17.md, REVIEW_2026-03-26_website_v4.md, REVIEW_2026-03-28_v18.md, REVIEW_2026-03-29_v19.md, REVIEW_2026-03-30_v19.md, REVIEW_BUNDLE_2026-03-10.md, REVIEW_BUNDLE_2026-03-14.md, REVIEW_BUNDLE_2026-03-15.md, REVIEW_BUNDLE_2026-03-29.md, REVIEW_BUNDLE_2026-03-30.md, REVIEW_BUNDLE_2026-04-04.md, REVIEW_CHARACTER_LEVELING_2026-03-30.md, SIMP1_PHASE2_PLAN.md, WEBSITE_PANEL_REVIEW_2026-03-20.md, joint-board-email-review-2026-03-29.md, mcp_architecture_review_2026-03-11.md, platform-review-2026-03-05.md


**docs/specs/ (2 files):** CLAUDE_CODE_PROMPT_v1.1.0.md, SPEC_CHARACTER_ENGINE_v1.1.0.md



---


*Bundle generated 2026-04-04 by deploy/generate_review_bundle.py*
