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

## v4.7.0 — 2026-03-31: Observatory V2 Remaining + Ledger/Field Notes + Status Page Fixes

### Observatory V2 — Remaining Items
- **Physical page DEXA + tape measurements**: `GET /api/physical_overview`, DEXA body composition section, tape measurement grid, WHR progress bar
- **AI expert voice sections (4 pages)**: new `ai-expert-analyzer` Lambda (weekly Mon 6am PT), `GET /api/ai_analysis?expert=<key>`, `renderAIAnalysisCard()` in components.js, cards on Mind/Nutrition/Training/Physical
- **Journal theme heatmap (Mind page)**: new `journal-analyzer` Lambda (nightly 2am PT), `GET /api/journal_analysis`, 30-day heatmap + top themes bar chart + sentiment trend line
- **Vice streak timeline (Mind page)**: 30-day stacked bar chart (held vs broken), `vice_timeline` added to mind_overview API

### BL-03: The Ledger — Phases 1–4
- Phase 1: `GET /api/ledger` endpoint (totals, by_event, by_cause with S3 config metadata)
- Phase 2: `site/ledger/index.html` — By Event / By Charity tab views, Snake Fund footer link
- Phase 3: Stake indicators on challenge/experiment cards via client-side ledger fetch
- Phase 4: Badge indicators on achievement cards

### BL-04: Field Notes — Phases 1, 3, 4
- Phase 1: new `field-notes-generate` Lambda (weekly Sun 10am PT), `GET /api/field_notes` with list + entry modes
- Phase 3: `site/field-notes/index.html` — list view + two-panel notebook entry view, nav links added
- Phase 4: Chronicle cross-reference in `wednesday_chronicle_lambda.py`

### EventBridge Schedules
- `life-platform-ai-expert-weekly` (Mon 14:00 UTC), `life-platform-journal-analyzer-nightly` (daily 10:00 UTC), `life-platform-field-notes-weekly` (Sun 18:00 UTC)

### Placeholder Cleanup (pre-launch)
- Explorer page: "Coming Soon" state replacing hardcoded findings narrative
- Field Notes page: "Coming April 7" state replacing test records
- Kitchen page: marketing copy stripped to clean "Coming Soon"
- Chronicle posts week-02/03/04: fabricated Elena Voss narratives replaced with redirects
- Chronicle sample email: fake data replaced with "Coming April 9" message
- Physical page DEXA baseline: uses most recent scan before EXPERIMENT_START as baseline

### Status Page Fixes
- Eight Sleep / Whoop: 1-day lag accounted for (sleep data keyed by wake date shows "current" not "2d ago")
- Activity-dependent sources: yellow/red → green when pipeline healthy but no user activity
- Uptime bars: activity-dependent sources show gray (neutral) dots instead of red for missing days
- Compute/email components: missing days shown as gray, not red (pre-launch expected)
- Apple Health sub-source tracking: CGM, water, breathwork, stretching, mindful minutes, state of mind each tracked independently by field check
- Todoist marked activity-dependent

### Bug Fixes
- Story page day counter: shows countdown pre-April 1 instead of "0"
- PLATFORM_STATS corrected: mcp_tools 115, lambdas 62, site_pages 71, test_count 1075
- Content audit file created: `docs/CONTENT_AUDIT.md`

---

## v4.6.0 — 2026-03-31: Observatory V2 Charts + Field Notes & Ledger Phase 0

Data-first visual overhaul across 4 observatory pages. Introduces Chart.js via CDN. New Physical Observatory page. Field Notes and Ledger Phase 0 (MCP tools + DynamoDB partitions).

### Charts
- Physical Observatory (`site/physical/index.html`) — weight trajectory, 4 hero gauges, key metrics, dual-axis charts
- Nutrition: 30-day calorie & macro stacked bar + donut chart
- Training: daily exercise minutes by modality, step count, strength volume trend
- Mind: state of mind sparkline + distribution donut, meditation calendar

### API Extensions
- `training_overview`: expanded daily_steps_trend to 30d, added `is_weekend`, added `daily_modality_minutes_30d`
- `mind_overview`: added meditation field (breathwork data)

### BL-03/BL-04 Phase 0
- Field Notes: `get_field_notes`, `log_field_note_response` MCP tools + DynamoDB partition
- Ledger: `log_ledger_entry` MCP tool + DynamoDB partition + `config/ledger.json` in S3

---

## v4.5.2 — 2026-03-30: R19 Architecture Review Remediation (Phases 1-6)

R19 remediation bringing all dimensions from B+ to A. 61 Lambdas (all CDK-managed), 118 MCP tools, 68 pages.

### Phase 1: Documentation Sprint
- INFRASTRUCTURE.md: full update (removed google-calendar, added 15 missing Lambdas, updated all counts)
- ARCHITECTURE.md: body-section reconciliation (5+ internal contradictions fixed)
- INCIDENT_LOG: added 5 v4.4.0 incidents + updated patterns section
- Section 13b: R17+R18 finding dispositions added to generate_review_bundle.py
- SLOs.md: removed Google Calendar, updated monitored sources
- RUNBOOK.md: added secret deletion to Common Mistakes

### Phase 2: Architecture Integrity
- CDK adoption audit: 4 unmanaged Lambdas identified (food-delivery-ingestion, measurements-ingestion, pipeline-health-check, subscriber-onboarding)
- ADR-045: Accept 118 MCP tools as operating state (closes 4-review-old finding)

### Phase 3: Reliability & Security
- PITR restore drill: PASSED (7th consecutive review — finally executed). Item counts match exactly.
- Alarm coverage: 100% (was 71%). Created 17 missing alarms.
- Security audit: security.txt, headers (DENY/nosniff/HSTS), WAF, IAM all verified.

### Phase 4: Observability
- Structured JSON route logging on site-api (zero cost — CloudWatch Logs)
- Saved Logs Insights queries for route analytics
- Verified life-platform-ops dashboard exists

### Phase 5: Operability
- CHANGELOG updated
- All doc headers consistent (verified by audit_system_state.sh)

### Phase 6: A- to A
- CDK adoption: 4 unmanaged Lambdas (food-delivery, measurements, pipeline-health-check, subscriber-onboarding) deleted and recreated via CDK with proper IAM roles, EventBridge rules, and alarms. Zero unmanaged Lambdas remaining.
- CI dependency scanning: pip-audit added to ci-cd.yml (advisory/non-blocking)
- /api/healthz endpoint: lightweight DDB latency + freshness + warm/cold check
- INTELLIGENCE_LAYER.md: freeze label removed, updated to v4.5.1
- OPERATOR_GUIDE.md: Day-1 onboarding guide created
- ADR-045: 118 MCP tools accepted as operating state

---

## v4.5.0 — 2026-03-30: Observatory Upgrade + Usability Remediation

Observatory Phase 1+2 implementation across Physical and Nutrition pages. Full usability study remediation (20 recommendations, 15 implemented). 68 pages, 65+ API endpoints, 118 MCP tools, 60 Lambdas.

### Observatory Upgrade Phase 1
- **Physical page**: modality deep-dive cards (replacing chips), walking & steps section (Garmin), breathwork section (Apple Health), weekly physical volume 7-day heatmap, running "coming soon" teaser, 2 new hero gauges (daily steps, active modalities)
- **Nutrition page**: protein source breakdown, weekday vs weekend comparison, eating window stats, caloric periodization (training vs rest days), "What I Actually Eat" gallery
- **New API endpoints**: `GET /api/weekly_physical_summary`, `GET /api/protein_sources`
- **Extended APIs**: `training_overview` (modality_breakdown, walking, breathwork), `nutrition_overview` (weekday_vs_weekend, eating_window, periodization)

### Observatory Upgrade Phase 2
- **Physical page**: strength deep-dive section with exercise variety + volume from Hevy
- **Nutrition page**: food delivery analysis, macro deep-dives (carbs/fats/fiber with targets + adherence)
- **New API endpoints**: `GET /api/strength_deep_dive`, `GET /api/food_delivery_overview`
- **Bug fix**: `_query_source` now guards against EXPERIMENT_START > today (pre-launch BETWEEN clause error)

### Usability Study Remediation (20 items)
- **P0-1**: Start Here visitor routing modal (3 audience paths, cookie-based)
- **P0-2**: Board of Directors transparency banner on all 3 board pages
- **P0-3**: Homepage hero rewrite — transformation-first framing + meta tag updates
- **P0-4**: Labs observatory overhaul — 2-column hero with gauge ring, "What I'm Watching" flagged biomarkers, editorial pull-quote
- **P1-1**: Builders page — meta-story section, AI partnership table, updated stats (59→60 Lambdas, 116→118 tools, 26 sources), extended timeline, subscribe CTA
- **P1-2**: Elena Voss AI attribution — callout on chronicle landing + attribution on every entry
- **P1-3**: Methodology page — AI governance model section, evidence badge system with confidence thresholds table
- **P1-5**: Share button on every page (Web Share API + clipboard fallback)
- **P2-2**: PubMed evidence links on protocol cards (6 protocols mapped)
- **P2-3**: Community page at /community/ with Discord CTA
- **MISC-1**: Protocols/Experiments inline definitions + cross-links
- **MISC-2**: Mobile responsiveness rules for observatory pages
- **MISC-3**: Elena Voss pull-quotes on all 6 observatory pages
- **MISC-4**: Currently Testing experiment card on homepage
- **MISC-6**: Matt bio element with monogram on homepage

### Homepage Fixes
- Hero layout changed from CSS Grid to Flexbox to eliminate vertical gap
- Matt bio element fills space between hero and "The experiment" section
- Transformation-first framing replaces tech-first framing

---

## v4.4.0 — 2026-03-29: Launch Readiness Session

Massive 24-hour session covering pipeline validation, status page overhaul, reader engagement, subscriber email redesign, and pre-launch hardening. Platform version at session end: 67 pages, 60+ API endpoints, 116 MCP tools, 59 Lambdas.

### Status Page Overhaul
- **3-layer monitoring**: data freshness + CloudWatch alarm overlay + daily active health check Lambda
- **Pipeline health check Lambda** (`pipeline-health-check`): daily at 6 AM PT, invokes every ingestion Lambda + checks all 11 secrets for deletion. Writes results to DynamoDB, status page reads and overlays failures.
- **Proportional overall status**: green (0 red), yellow/degraded (1-2 red), red/outage (3+ red or >20%)
- **Activity-dependent sources**: show green "Pipeline ready — awaiting user activity" instead of false red
- **Data source sub-groups**: API-Based, User-Driven, Periodic Uploads, Lab & Clinical
- **Source app attribution**: each source shows "Source: Whoop" / "Source: MacroFactor via Dropbox"
- **Due-date tracking**: Labs (6mo), DEXA (12mo), Food Delivery (3mo), BP (3mo) with yellow when overdue
- **Genome**: one-time import, no daily bars, "Data on file"
- **Uptime bars**: include today as neutral, exclude from red count. All aligned from Mar 28.
- **AWS cost tracking**: MTD spend, projected monthly, % of $15 budget (Cost Explorer API, free)
- **DLQ depth monitoring**: shows dead-letter queue message count in infrastructure
- **Light/dark mode colors**: vivid neon green/red in dark mode, rich forest green/red in light mode
- **1-minute cache TTL** for near-real-time updates

### Pipeline Fixes Found & Resolved
- **Eight Sleep**: crashed for 10 days (`logger.set_date` bug). Fixed + re-authed after password change. 7 days backfilled.
- **Dropbox**: secret deleted Mar 10 — entire MacroFactor nutrition chain was silently broken. Restored.
- **Notion**: secret deleted — restored. Lambda now accepts entries without Template/Date properties.
- **Health Auto Export**: `logger.set_date` crash. Fixed + redeployed.
- **Garmin**: expired auth tokens + missing `garth`/`garminconnect` modules. Layer published. Auth pending (Garmin SSO rate limiting).
- **logger.set_date bug**: fixed across all 14 Lambdas with `hasattr` guard

### Reader Engagement (Phases 1-4)
- Phase 1: freshness indicators, "This Week" cards, sparklines, trend arrows, "Since Your Last Visit", reading paths across 8 pages
- Phase 2: guided path → replaced with section-nav checkmarks (less clutter)
- Phase 3: Weekly Recap page at `/recap/`
- Phase 4: Living Pulse feed on homepage (hidden until April 1)

### New Pages & API Endpoints
- `/labs/` — 74 biomarkers, accordion UI, `/api/labs` endpoint
- `/recap/` — weekly recap from existing endpoints
- `/mission/` — renamed from `/about/` (old URL kept for backwards compat)
- `/api/frequent_meals` — MacroFactor food log aggregation
- `/api/meal_glucose` — MacroFactor × Dexcom CGM cross-reference
- `/api/strength_benchmarks` — Hevy 1RM data
- `/api/changes-since` — delta summary for returning visitors
- `/api/observatory_week` — 7-day domain summaries

### Homepage Rewrite (Item #8)
- Full editorial pattern: 2-column hero, gauge rings, data spread, pull-quotes, observatory entry cards
- 1797 → 888 lines. Reads from `public_stats.json` for all live data.

### Subscriber Email Redesign
- Welcome email: CTA → /story/, Elena intro tightened, format expectations added
- Weekly Signal: 5-section template (numbers table, chronicle preview, worked/didn't, board quote, observatory)
- `build_weekly_signal_data()` with board/observatory rotation
- Bug fix: `subscriber_email` undefined → `subscriber.get('email', '')`
- Day 2 bridge email: new `subscriber-onboarding` Lambda with 3 curated installments

### Sleep/Glucose Observatory
- 2-column editorial hero matching Training page pattern
- Nutrition page: hardcoded meals → API-driven from MacroFactor
- Training page: strength benchmarks fallback from `/api/strength_benchmarks`

### OG Images
- 12 page-specific images generated daily (was 6)
- Meta tags updated on all affected pages

### Architectural Fixes
- CSS/JS cache: 1-year → 1-day (no content-hash filenames)
- OG image Lambda added to CDK operational stack
- Site-api CDK env vars expanded
- Security headers on API (nosniff, DENY, HSTS)
- GA4 analytics activated (G-JTKC4L8EBN)
- Canonical URLs + RSS discovery injected via components.js
- `.well-known/security.txt` created
- Protocols seeded to DynamoDB from config
- Architecture diagram adapts to light mode (SVG fills use CSS variables)
- Architecture reviews updated to R15-R18
- Status page colors: brighter in dark mode, readable in light mode

### R18 Remediation
- All 9 findings addressed (doc reconciliation, lambda_map, alarms, WAF rules, deploy script)
- R17 findings verified resolved (CORS, google_calendar, model strings)

### Cleanup
- 294 old handovers archived to `handovers/archive/`
- Stale S3 objects deleted (.git/, tmp/, root index.html, old content prefixes)
- Dead `observatory.css` deleted (17KB, zero pages loaded it)
- Expired `deprecated_secrets.txt` entry removed
- Google Calendar secret removed from test KNOWN_SECRETS

### Data Corrections
- Journey start weight: 302 → 307 (April 1 baseline, not Feb beta)
- DynamoDB profile updated
- Story page date: February → April 2026
- Whoop workout enrichment wired into training overview API

### Platform Stats (v4.4.0)
- 67 pages, 60+ API endpoints, 116 MCP tools, 59 Lambdas
- 26 data sources, 7 CDK stacks
- Pillow layer (v1), garth+garminconnect layer (v2)
- Daily health check: 16/17 pass (Garmin auth pending)

---

## v4.3.2 — 2026-03-28: PB-R1 Character-as-Anchor + Homepage Heartbeat

### Product Board Review
- Full 8-panel blind audience workshop (simulated): Reddit, tech, general public, older, younger, AI-forward, AI-skeptic, tech leads, indie builders
- Key finding: site is two products on one URL; Character Sheet should be the anchor score; return visitors need "what changed" signals
- Board vote: launch April 1 as planned with 3 surgical changes

### Backend (PB-R1)
- `site_writer.py`: Added `character` parameter to `write_public_stats()` — embeds level, tier, emoji, XP, composite score in public_stats.json
- `daily_brief_lambda.py`: Threads character_sheet data through to write_public_stats call
- Eliminates separate `/api/character_stats` fetch on homepage — one payload serves all

### Frontend (PB-R1)
- Nav level badge: `Lv X 🔨` appears in top nav on all pages, links to Character Sheet, hidden on mobile
- Elena live line: Pull-quote #2 on homepage dynamically replaces with `elena_hero_line` from public_stats.json
- Updated timestamp: Hero stats line appends "Updated Xh ago" from `_meta.refreshed_at`
- New homepage design (Claude Code): 888-line editorial layout replacing 1,700-line prior version — 4 gauge rings, 3-column data spread with sparklines, observatory entry cards, chronicle card

### Deploy Notes
- site_writer.py bundled as --extra-file in daily-brief zip (takes precedence over layer at runtime)
- Shared layer rebuild via `deploy/build_layer.sh` prepares CDK layer-build directory; full CDK deploy will sync layer
- Frontend: S3 direct upload + CloudFront invalidation

---

## v4.3.1 — 2026-03-28: R18 Architecture Review Remediation

### Documentation (R18-F01, R18-F08)
- Reconciled all doc headers with AWS audit: 59 Lambdas, 116 MCP tools, 66 pages, 25 data sources, 7 CDK stacks
- Added freeze label to INTELLIGENCE_LAYER.md (stale since v3.7.68, flagged 5 consecutive reviews)
- Created `deploy/audit_system_state.sh` for pre-review system state verification

### CI/CD (R18-F03)
- Updated lambda_map.json with og-image-generator and email-subscriber entries
- Added CI lint step for orphan Lambda source files not in lambda_map.json

### Monitoring (R18-F04)
- CloudWatch error alarm script for: og-image-generator, food-delivery-ingestion, challenge-generator, email-subscriber
- Food delivery freshness check with 90-day per-source stale threshold override

### Security (R18-F06)
- WAF endpoint-specific rate rule script: /api/ask (100/5min), /api/board_ask (100/5min)

### Operations (R18-F05)
- Created `deploy/deploy_site.sh` — canonical site deploy with link validation + sync + invalidation

### R17 Cleanup
- R17-F07 (CORS): already implemented via CORS_HEADERS dict + OPTIONS handler
- R17-F08 (google_calendar): retired file only, not in any active SOURCES list
- R17-F10 (model strings): already using os.environ.get() pattern

---

## R18 Architecture Review — 2026-03-28 (v4.3.0)

### Architecture Review
- Tech Board review #18 at v4.3.0. **Composite grade: B+** (down from A- at R17)
- Grade movement: Security B+→A- (WAF deployed), Product B+→A- (47-page product, reader engagement). Architecture A-→B+ (CDK drift, doc mismatch), Observability A-→B (monitoring didn't scale), Operability B+→B (docs materially wrong)
- Held: Cost A, Data A, AI A, Statistics A, Code Quality A→A-
- 9 new findings: R18-F01 (doc drift, HIGH), R18-F02 (CLI Lambdas outside CDK, HIGH), R18-F03 (lambda_map stale), R18-F04 (new resources unmonitored), R18-F05 (47-page manual deploy), R18-F06 (WAF rules too broad), R18-F07 (SIMP-1 regression 95→110), R18-F08 (INT_LAYER 5th consecutive stale flag), R18-F09 (cross-region worsened to 13+ routes)
- R17 findings: 4 resolved (WAF, rate limiting, privacy policy), 2 worsened, 3 persisting, 2 partially resolved
- Top priority: documentation reconciliation, CDK adoption, lambda_map update — all within launch week
- Path to A-: 2-3 focused sessions. Path to A: cross-region migration + SIMP-1 Phase 2
- Review: `docs/reviews/REVIEW_2026-03-28_v18.md`

---

## v4.3.0 — 2026-03-28: Reader Engagement, Labs Page, OG Images, Architectural Fixes

Major implementation session. 4-phase reader engagement rollout, new pages, new Lambdas, privacy fixes, and architectural cleanup.

### New Pages
- **`/labs/`** (BL-02) — Bloodwork observatory with 74 biomarkers across 18 categories, accordion UI, flag badges
- **`/recap/`** (Phase 3) — Weekly recap page compiling vital signs deltas, domain highlights, forward forecast

### New API Endpoints
- **`/api/labs`** — Reads clinical.json from S3, returns lab biomarkers
- **`/api/changes-since?ts=EPOCH`** — Delta summary for "Since Your Last Visit" homepage card
- **`/api/observatory_week?domain=X`** — 7-day domain summary with sparklines (sleep, glucose, nutrition, training, mind)

### New Lambda
- **`og-image-generator`** — Generates 6 data-driven 1200x630 PNG OG images daily using Pillow. EventBridge cron 19:30 UTC. Pillow layer published.

### Reader Engagement (Phases 1-4)
- **Phase 1:** Freshness indicators on 5 observatories, "This Week" summary cards, sparkline JS utility, "Since Your Last Visit" homepage card, reading-order links across 8 pages
- **Phase 2:** Guided 5-stop progress bar for first-time visitors, dynamic observatory selection, enhanced subscribe CTA on Character page
- **Phase 3:** Weekly Recap page at `/recap/` with vital signs, domain highlights, forecast
- **Phase 4:** Living Pulse feed on homepage with domain-colored pips, editorial headlines, sparklines

### HP-12: Elena Hero Line
- Wire `elena_hero_line` from `tldr_guidance` through to `write_public_stats()`. Appears in `public_stats.json` after next daily brief.

### HP-13: Dynamic OG Images
- 6 page-specific OG images (home, sleep, glucose, training, character, nutrition) with live stats. Meta tags updated on all 6 pages.

### Privacy & Security
- Filter `public: false` challenges (cannabis/porn) server-side + client-side
- Add `isBlocked` keyword filter to mind page vice streak rendering
- Remove behavioral signals group from status page (food delivery streak is health data, not system status)

### Architectural Fixes
- Fix CSS/JS cache from 1-year to 1-day (`max-age=86400`) — filenames have no content hash
- Add OG image Lambda to CDK operational stack (was CLI-created, causing drift)
- Add missing S3_BUCKET, S3_REGION, CORS_ORIGIN env vars to site-api CDK config
- Gitignore CLAUDE_CODE_BRIEF session files

### Bug Fixes
- Weekly snapshots: fix crash when JOURNEY_START is in the future
- Pulse feed: rename `.pulse` to `.pulse-feed` to avoid CSS conflict with nav status dot
- Sleep "This Week" dates: fix `[:5]` → `[5:]` truncation (showed "2026-" instead of "03-22")
- "This Week" card: fix flush-left alignment with proper column padding
- Duplicate reading paths: remove extras from observatory pages

### Platform Stats (v4.3.0)
- 61 Lambdas, 110 MCP tools, 26 data sources, 7 CDK stacks
- New: Pillow Lambda layer (v1), engagement.js shared utility

---

## v4.2.3 — 2026-03-28: Discord Community Integration — Strategy, Assets, Spec

Pre-launch advisory session. No Lambda code shipped. Discord community strategy defined, server icon designed (two iterations), integration spec written. All assets ready for deployment.

### Discord Community Strategy (Product Board)

**Launch timing:** April 1 confirmed (board unanimous). Two conditions: homepage human thesis above fold + mobile verified. Post on April 2 for social (April Fools' risk).

**Organic reader acquisition:** r/QuantifiedSelf, r/MacroFactor, r/whoop as primary channels. Inner Life page = highest-value share asset. One narrative entry piece (Substack/Medium) as stranger entry point. BL-01 (For Builders) reaffirmed as organic growth asset.

**Community structure:** Discord confirmed right fit for obesity/weight loss subreddit audience. Same-day server creation, drop link only if post gets traction. 3 channels max: `#welcome`, `#average-joe-updates`, `#your-journey`.

**Privacy/sharing analysis:** Coworkers — caution, Inner Life page carries asymmetric professional risk. Family — lower risk but preview Inner Life before sharing.

### Discord Server Icon (v2 — final)

Progress-fill arc: bright amber for journey so far, dimmed amber (22% opacity) for remaining arc, glowing dot at current position (default 62% fill). "AJ" bold monogram + "AVG·JOE" monospace wordmark. Dark background #08090e.

Files: `average-joe-community-512px.png` + `average-joe-community.svg`

**Pending S3 upload (Matthew runs):**
```bash
aws s3 cp ~/Downloads/average-joe-community.svg s3://matthew-life-platform/assets/images/logos/average-joe-community.svg --content-type image/svg+xml --cache-control "public, max-age=31536000"
aws s3 cp ~/Downloads/average-joe-community-512px.png s3://matthew-life-platform/assets/images/logos/average-joe-community-512px.png --content-type image/png --cache-control "public, max-age=31536000"
```

Permanent URLs once uploaded:
- `https://averagejoematt.com/assets/images/logos/average-joe-community.svg`
- `https://averagejoematt.com/assets/images/logos/average-joe-community-512px.png`

### Discord Integration Spec (`docs/DISCORD_INTEGRATION_SPEC.md`)

Three components, all deployed at launch (no staged rollout):
- **Component A (Footer Pill):** All pages, footer "Follow" column. `⌗ Join the community ↗`
- **Component B (Understated Card):** Inner Life, Chronicle entries, Accountability, Story pages
- **Component C (Section Break CTA):** Inner Life only, after mood/psychological patterns section

Constraints: Discord purple (#5865F2) never used. Word "Discord" never in copy. Homepage and observatory pages get nothing.

### Files This Session

| File | Status |
|---|---|
| `docs/DISCORD_INTEGRATION_SPEC.md` | NEW — cp from Downloads |
| `handovers/HANDOVER_v4.2.3.md` | NEW |
| `handovers/HANDOVER_LATEST.md` | UPDATED |
| `average-joe-community.svg` | Asset — needs S3 upload |
| `average-joe-community-512px.png` | Asset — needs S3 upload |

---

## v4.2.2 — 2026-03-28: Offsite Day 2 — Story/About Punch List + Status Page Spec + Food Delivery Spec

Full-day offsite session (Day 2). Three board sessions convened. Three implementation specs written and committed. Story/About pages implemented directly. Food delivery CSV analyzed (1,598 transactions, 15 years). No Lambda code shipped — specs and site page implementations ready for Claude Code handoff.

### Board Sessions

**Personal Board + Product Board — Challenges Session**
- 17 new challenges created in DynamoDB as candidates across all pillar domains
- 6 N=1 experiment proposals from current health data (HRV 29.56, recovery 40, weight 287.69, CTL 4.45, 10-day habit gap Mar 17–26)
- Sensitive challenges embargoed: `no-weed-30` and `no-porn-30` set `public: false` in challenges_catalog.json
- No-Drift Weekends adjusted for 11:30am IF window; 9:30 Protocol adjusted to 8:15pm phone lockdown

**Technical Board — Status Page Design (14-0 unanimous)**
- `/status/` path on existing domain — no new CDK stack, no new CloudFront distribution
- Footer-only navigation placement (not primary nav)
- 19 data sources with source-specific stale thresholds, 5-min server cache, 60s auto-refresh
- `docs/STATUS_PAGE_SPEC.md` — complete implementation guide for Claude Code

**Joint Boards — Food Delivery Data Integration**
- 15-year CSV analyzed: 1,598 transactions, $61,161 total spend
- Aug 2025 worst month: 68 orders, $3,674, 24 of 31 days had delivery
- Current clean streak: 3 days from March 26
- Public framing: Delivery Index (0–10, no dollar amounts) + clean streak days only
- Delivery Index calibrated: Aug 2025 = 10.0, divisor 1.55
- `docs/FOOD_DELIVERY_SPEC.md` — complete implementation guide for Claude Code

**Product Board — Story/About Review**
- All changes implemented directly this session (not deferred to Claude Code)
- `docs/STORY_ABOUT_REVIEW_SPEC.md` written

### Site Pages Implemented (deployed, commit 49f4723)

**site/about/index.html:**
- Title → "The Mission — averagejoematt.com"
- Meta/OG/Twitter tags updated with hook copy ("I've lost 100 pounds before. Multiple times.")
- Bridge paragraph added to bio opening
- JS bug fixed: `getElementById('about-weight')` now resolves
- Physical goals simplified: Half marathon + 300lb rows removed, live "Lost so far" row added
- Static "Day 1 — April 2026" → live JS day counter (shows "Launching April 1" pre-launch)

**site/story/index.html:**
- Day counter pre/post launch aware: "Launching April 1" → "Day 1" → "Day N"
- Chapter 4 two-state HTML flips on April 1 via `isLive` detection
- Waveform empty state: 30 ghost bars at 12% opacity with "Signal emerging" label
- Ghost bars hide when real waveform data renders
- Subscribe CTA moved directly after Chapter 5 ("You're welcome to watch.")

### Commits This Session
- `49f4723` — fix: story + about pre-launch punch list
- `32a3035` — docs: food delivery, status page, story/about specs

---

## v4.2.1 — 2026-03-28: Full Offsite Implementation (548 Recommendations)

Implemented all 4 parts of the pre-launch offsite board review in a single session. 20 commits, 60+ files changed.

### Major Releases
- **v4.1.0**: Decisions 16-24 + Part 3 meta-decisions (~170 features across 9 pages)
- **v4.2.0**: Decisions 25-34 + Part 4 meta-discussions (~210 features across 10 pages)
- **v4.2.1**: Audit sweep — all remaining should-haves + gap fixes

### Highlights
- Shared pipeline nav on all 6 Practice pages
- "The Weekly Signal" → "The Measured Life" site-wide
- Board personas: removed real public figures as chatbots, replaced with fictional advisors
- Accent color: neon #00e5a0 → desaturated #3db88a (rollback available)
- Retired // comment labels from 35+ pages
- Dark mode text contrast fixed (WCAG AA)
- Builders lessons rewritten for CIO credibility
- CI/CD pipeline fixed (QA updated for JS-injected nav)
- First Person page created (/first-person/)
- Experiment detail overlay (mirrors challenges popup)
- Supplement registry migrated from hardcoded JS to S3 config + API
- 3 missing API endpoints added (benchmark_trends, meal_responses, experiment_suggest)
- /api/subscriber_count endpoint added
- Genome privacy guardrails on Chronicle + MCP tools
- PubMed/Cochrane source links on 5 supplement cards
- Breadcrumbs added to 9+ content pages
- Sitemap expanded to 47 URLs
- Nav highlight bug fixed (The Story no longer always green)
- Redundant nav clutter removed from Practice pages

### Deferred to Post-Launch
PRE-13 (data publication review), 23a/23b (weekly snapshot Lambda), VIS-2 (Sleep/Glucose editorial), VIS-4 (OG images), 20p (reader challenge tracking), 21m (transformation timeline)

---

## v3.9.41-offsite-p4 — 2026-03-27: Pre-Launch Offsite Part 4 Complete (Planning)

Final session of 4-part pre-launch offsite board meeting. All 30+ pages reviewed. 34 decisions, ~548 total recommendations. No code shipped — planning session only.

### Pages Reviewed (Decisions 25–34)
- Story (25): 19 recs — fix CTA branding, add share mechanics, verify intersection cards, mobile milestone bar
- Platform (26): 17 recs — add narrative intro, lead with $13/month, expand Tool of the Week, resolve Intelligence overlap
- Intelligence (27): 17 recs — elevate Sample Daily Brief as hero, label live vs illustrative, add N=1 caveats
- Cost (28): 16 recs — **CRITICAL: reconcile cost numbers across pages**, fix mobile "Why so low?" column
- Methodology (29): 15 recs — **CRITICAL: fix "365+ Days Tracked"**, add 6th limitation, reconcile source cards
- Board (30): 20 recs — **CRITICAL: replace personas with BoD fictional advisors + "inspired by" attribution**, remove real public figures as chatbots
- Tools (31): 15 recs — reframe header, **CRITICAL: fix Matthew badges hidden on mobile**, add formula citations
- About (32): 12 recs — fix test coverage binding, expand links section, fix subscribe branding
- Home re-review (33): 13 recs — curate "What's Inside" cards, auto-hide prequel banner, verify /chronicle/sample/
- Builders (34): 18 recs — **CIO audit: rewrite 4 lessons**, remove "Senior Director", reconcile stats, add builder CTA

---

## v3.9.41 — 2026-03-27: Pre-Launch Content Review (Product Board Editorial Session)

Full editorial review across Home, Story, and About pages with Product Board content panel.

---

## v3.9.40 — 2026-03-27: Nav Spacer Architecture + Catalog Fix + UX Cleanup

---

## v3.9.39 — 2026-03-27: Pre-Launch Sweep — Nav Fixes, Mobile Scroll, Catalog Expansion

---

## v3.9.38 — 2026-03-26: Visual Asset System — 65 SVGs + 3-Page Integration

---

## v3.9.37 — 2026-03-26: Product Board Pre-Launch Punch List (23 items)

---

## v3.9.36 — 2026-03-26: Signal Doctrine Tier 2

---

## v3.9.35 — 2026-03-26: Signal Doctrine Tier 1 Rollout + Arena Voting + Experiments

---

## v3.9.34 — 2026-03-26: Signal Doctrine — Design Brief Implementation

---

## v3.9.33 — 2026-03-26: Arena v2 + Lab v2 — Challenge & Experiment Page Overhaul

---

## v3.9.32 — 2026-03-26: Sessions 3+4 — Chronicle/Subscribe + About/Builders/Throughline

---

## v3.9.31 — 2026-03-26: Website Review #4 + Story Page + Homepage Overhaul

---

## v3.9.30.1 — 2026-03-26: Story Page Content Audit + Interview Drafts

---

## v3.9.30 — 2026-03-26: Build Section Overhaul + /builders/ Page

---

## v3.9.29 — 2026-03-26: Phase D + E — Challenge XP Wiring, Auto-Verification, Nav Update

---

## v3.9.28 — 2026-03-26: Challenge System — Full Stack Build

---

## v3.9.27 — 2026-03-26: Nutrition Bug Fix + Global Countdown.js

---

## v3.9.26 — 2026-03-25: April 1 Launch Reframe — Prequel Chronicles, Baseline Snapshot

---

## v3.9.25 — 2026-03-25: Sleep + Glucose Observatory Visual Redesign (5/5 Consistency)

---

## v3.9.24 — 2026-03-26: Observatory Visual Redesign — 3 pages rebuilt (Board-voted hybrid)

---

## v3.9.23 — 2026-03-25: DISC-7 Annotations + 3 Observatory Pages (Nutrition, Training, Inner Life)

---

## v3.9.22 — 2026-03-25: Discoveries page evolution — DISC-1/DISC-2 + critical API fix

---

## v3.9.21 — 2026-03-25: Accountability page evolution — Product Board Review #4

---

## v3.9.20 — 2026-03-25: HP-09 — Section consolidation (9→7), backend deploys for HP-06/HP-12/HP-14

---

## v3.9.19 — 2026-03-25: HP-06/HP-12/HP-14 backend + frontend

---

## v3.9.13 — 2026-03-25: Benchmarks → "The Standards" — 6-domain research reference redesign

---

## v3.9.12 — 2026-03-25: Habits + Supplements page overhauls — Product Board Phase A/B/C

---

## v3.9.11 — 2026-03-24: Character page RPG overhaul — Product Board Phase A/B/C

---

## v3.9.10 — 2026-03-24: Navigation restructure — 6-section board-approved IA

---

## v3.9.9 — 2026-03-24: Content consistency architecture (ADR-034), doc sync, public_stats fix

---

## v3.9.8 — 2026-03-24: Nav update (3 new pages), Board sub-pages, sitemap expansion

---

## v3.9.7 — 2026-03-24: Data Explorer, Weekly Snapshots, Decision Fatigue Signal

---

## v3.9.6 — 2026-03-24: Dark/Light mode, Milestones Gallery, 5 spec closures

---

## v3.9.5 — 2026-03-24: CI/CD first deploy test + smoke/I1 fixes

---

## v3.9.4 — 2026-03-23: CI/CD pipeline activation — 3 blockers resolved

---

## v3.8.9 — 2026-03-22: Nav restructure — rename + reorganise

---

## v3.8.8 — 2026-03-22: Phase 0 website data fixes

---

## v3.8.7 — 2026-03-22: CI/CD pipeline activation

---

## v3.8.6 — 2026-03-22: Phase 2 /live/ + /character/ enhancements

---

## v3.8.5 — 2026-03-22: Phase 2 /discoveries/ empty state

---

## v3.8.4 — 2026-03-22: Phase 2 /experiments/ depth + Keystone group fix

---

## v3.8.3 — 2026-03-22: Phase 2 /habits/ page — Keystone Spotlight + Day-of-Week Pattern

---

## v3.8.2 — 2026-03-22: D10 baseline + Phase 1 Task 20 reading path CTAs

---

## v3.8.1 — 2026-03-22: Phase 0 Data Fixes — D1 weight null, hardcoded platform stats removed

---

## v3.8.0 — 2026-03-21: Sprint 8 — Mobile Navigation, Content Safety Filter, Grouped Footer

---

## v3.7.84 — 2026-03-20: Sprint 7 World-Class Website — Expert Panel Review + 15 Items Shipped

---

## v3.7.83 — 2026-03-20: Operational Efficiency Roadmap + Claude Code Adoption

---

## R17 Architecture Review — 2026-03-20

---

## v3.7.81 — 2026-03-19: Standardise nav + footer across all 12 pages

---

## v3.7.80 — 2026-03-19: WR-24 subscriber gate, S2-T2-2 /board/ page, sprint plan cleanup
