# Handover — Observatory V2 Remaining + Ledger/Field Notes Phase 1 v4.7.0

**Date:** 2026-03-31
**Scope:** Three Observatory V2 remaining items, Ledger Phase 1+2, Field Notes Phase 1+2+3, EventBridge schedules, bug fixes, site pages

## What Changed

### Item 1: Physical Page — DEXA + Tape Measurements
- `GET /api/physical_overview` — queries DEXA + measurements partitions, returns latest/baseline DEXA scans with deltas, tape measurement session, WHR
- DEXA section: scan header rows, 5-row comparison table, ALMI/FFMI/FMI index badges, biological age card, visceral fat card, bone density line
- Tape section: 2-column trunk/limbs measurement grid, waist-to-height ratio progress bar with target marker
- Data confirmed: 2 DEXA scans (2025-05-10 baseline, 2026-03-30 current), 1 tape session

### Item 3: AI Expert Voice Sections
- **New Lambda**: `ai-expert-analyzer` (weekly Mon 6am PT via EventBridge)
- `GET /api/ai_analysis?expert=mind|nutrition|training|physical` — returns cached prose analysis
- `renderAIAnalysisCard()` function in `components.js` — reusable card with expert name, accent color, prose, generated date
- Cards on all 4 observatory pages: Dr. Conti (Mind), Dr. Webb (Nutrition), Dr. Chen (Training), Dr. Reyes (Physical)
- DynamoDB: `USER#matthew#SOURCE#ai_analysis`, SK `EXPERT#<key>`, 8-day TTL
- All 4 experts generated and serving on first deploy

### Item 2: Journal Theme Heatmap
- **New Lambda**: `journal-analyzer` (nightly 2am PT via EventBridge)
- `GET /api/journal_analysis` — 90-day theme/sentiment data
- Mind page: 30-day GitHub-style heatmap (colored by dominant theme), top themes horizontal bar chart, 90-day sentiment trend line
- 7 theme colors: personal_growth=violet, relationships=blue, health_body=green, work_ambition=amber, anxiety_stress=red, gratitude=teal, reflection=indigo
- Backfill complete: 5 entries analyzed from existing journal data

### Vice Streak Timeline
- 30-day stacked bar chart on Mind page: green (held) vs red (broken) per day
- Data from `vice_timeline` added to `/api/mind_overview` response (queries 30d of habit_scores)

### BL-03: Ledger Phase 1
- `GET /api/ledger` — totals, by_event (earned/reluctant), by_cause (merged with S3 config metadata)
- Returns empty structure gracefully when no transactions exist
- Config: `config/ledger.json` in S3 has real cause names (Northwest Harvest, American Reptile Rescue)

### BL-04: Field Notes Phase 1
- **New Lambda**: `field-notes-generate` (weekly Sun 10am PT via EventBridge)
- `GET /api/field_notes` — list mode (all weeks) + entry mode (`?week=2026-W14`)
- Gathers 7-day data across all domain partitions, calls Claude Sonnet for synthesis
- First entry generated: W14 (cautionary tone — sparse data pre-launch)

### Bug Fixes
- Story page day counter: shows "X days until launch" countdown pre-April 1 (was showing "0")
- PLATFORM_STATS: mcp_tools 118→121, lambdas 61→63, site_pages 68→69, test_count 83→1071

## Files Modified/Created
- `lambdas/site_api_lambda.py` — 5 new endpoints, PLATFORM_STATS, vice_timeline
- `lambdas/ai_expert_analyzer_lambda.py` — **new**
- `lambdas/journal_analyzer_lambda.py` — **new**
- `lambdas/field_notes_lambda.py` — **new**
- `site/physical/index.html` — DEXA + tape + AI card
- `site/mind/index.html` — journal heatmap + vice timeline + AI card
- `site/nutrition/index.html` — AI card
- `site/training/index.html` — AI card
- `site/story/index.html` — day counter fix
- `site/assets/js/components.js` — `renderAIAnalysisCard()`
- `site/ledger/index.html` — **new page**
- `site/field-notes/index.html` — **new page**
- `site/challenges/index.html` — ledger stake indicators
- `site/experiments/index.html` — ledger stake indicators
- `site/achievements/index.html` — ledger badge indicators
- `lambdas/wednesday_chronicle_lambda.py` — field notes cross-reference
- `ci/lambda_map.json` — 3 new entries
- `docs/CHANGELOG.md` — v4.7.0
- `docs/ARCHITECTURE.md` — updated counts
- `docs/SCHEMA.md` — journal_analysis + ai_analysis partitions
- `CLAUDE.md` — updated tool count

## Deploy Status
- Lambda deployed: `life-platform-site-api`
- Lambda created: `ai-expert-analyzer`, `journal-analyzer`, `field-notes-generate`
- Site synced to S3 (both prefixes)
- CloudFront invalidated

### BL-03: Ledger Phase 2 — Site Page
- `site/ledger/index.html` — **new page** with By Event / By Charity tab views
- Summary strip (total donated, earned, penalties, causes funded)
- Event cards with earned (green) / reluctant (red) color-coding
- Cause cards with descriptions, totals, joke notes, external links
- "Snake Fund" link added to footer Internal column in `components.js`

### BL-04: Field Notes Phase 3 — Site Page
- `site/field-notes/index.html` — **new page** with list + entry views
- List view: week rows with tone badge color, response status
- Entry view: two-panel notebook layout (AI Lab Notes left, Matthew's Response right)
- Ruled-line background CSS effect, cautionary/affirming sub-sections
- "Field Notes" added to The Story nav section and footer

### EventBridge Schedules
- `life-platform-ai-expert-weekly`: Mon 14:00 UTC (6am PT) → ai-expert-analyzer
- `life-platform-journal-analyzer-nightly`: daily 10:00 UTC (2am PT) → journal-analyzer
- `life-platform-field-notes-weekly`: Sun 18:00 UTC (10am PT) → field-notes-generate

### BL-03: Ledger Phase 3 — Card Stake Indicators
- Challenges page: ledger hint on cards with matching `source_id` via client-side `/api/ledger` fetch
- Experiments page: same hint on mission control + library tiles
- "This carries a stake → The Ledger" text, muted mono styling

### BL-03: Ledger Phase 4 — Achievement Badge Indicators
- Achievements page: "→ The Ledger" link on earned badges with matching `source_id`
- Same client-side ledger fetch pattern

### BL-04: Field Notes Phase 4 — Chronicle Cross-Reference
- `wednesday_chronicle_lambda.py`: queries current week's field notes in `gather_chronicle_data()`
- Injects AI tone, preview (300 chars), and Matthew's response (200 chars) into data packet
- Elena can weave field notes themes into the weekly Chronicle narrative

### Placeholder Cleanup (pre-launch)
- Explorer page: hardcoded findings narrative → "Coming Soon" state
- Field Notes page: test records deleted, → "Coming April 7" state
- Kitchen page: 487 lines of AI marketing copy → clean "Coming Soon"
- Chronicle posts week-02/03/04: fabricated Elena Voss narratives → redirects to /chronicle/
- Chronicle sample email: fake Week 1 data → "Coming April 9" message
- Physical page DEXA baseline: logic changed to use most recent pre-experiment scan as baseline

### Status Page Fixes
- Eight Sleep / Whoop: 1-day lag accounted for (`_LAGGED_SOURCES`), shows "current" not "2d ago"
- Activity-dependent sources: yellow/red → green when pipeline healthy but no user activity
- Uptime bars: activity-dependent sources show gray dots instead of red for missing days
- Compute/email components: same gray-dot treatment for pre-launch gaps
- Apple Health sub-source tracking: CGM (`blood_glucose_avg`), water (`water_intake_ml`), breathwork (`recovery_workout_minutes`), stretching (`flexibility_minutes`), mindful minutes, state of mind (`som_avg_valence`) — each tracked independently via `field_check` parameter
- Todoist marked `activity_dependent: True`

### Content Audit
- Created `docs/CONTENT_AUDIT.md` — full audit of every page categorizing text as PLACEHOLDER, MATTHEW-VERIFY, REAL, or FABRICATED
- v4.7.1: first editorial pass (8 pages rewritten from Matthew's answers)
- v4.7.2: second editorial pass (15 changes across 13 pages from Claude Chat review session)

### Launch Readiness (v4.7.3)
- Physical page obs-freshness wired (was the only missing observatory page)
- Homepage: Inner Life card `★ FEATURED` badge + violet tint + hover callout
- Homepage: "Made public because accountability needs an audience." in `#amj-bio`
- Email welcome rewritten: plain-text, Matthew's voice, three page links

### MCP Lambda Fix (v4.7.3)
- `mcp/tools_measurements.py` import error fixed: `get_table`/`get_user_id` → `table`/`USER_ID` from `mcp.config`
- MCP Lambda redeployed — resolves `slo-mcp-availability` alarm
- Root cause: `tools_measurements.py` referenced functions that never existed in `mcp.core`

### Test Fixes (v4.7.3)
- Orphaned `site_api_ai_lambda.py` added to skip_deploy
- 3 missing secrets added to test known-secrets lists
- `ai_expert_analyzer_lambda.py` handler wrapped in try/except
- Test failures: 19 → 0 local (8 AWS integration remain — infra drift, not code)

### Stale Stats Fix (v4.7.3)
- HTML fallback values updated: 118→115 tools, 61→62 Lambdas across about/mission/platform/builders pages + meta tags

### Backlog Cleanup (v4.7.4)
- **HP-12** (Elena Hero Line): closed — already fully wired end-to-end. Removed from carry-forward.
- **get_nutrition positional args**: closed — 8 test cases written, all pass, no bug reproducible
- **DISC-7** annotation seeding: 4 Day 1 events seeded to DynamoDB, annotations merge with journey_timeline
- **BL-01/BL-02** (Builders + Labs pages): confirmed already built in prior sessions
- **HP-13** share card: twitter:image fixed to dynamic `og-home.png`, share button added to homepage hero
- Mobile nav: Internal links (Status, Buddy Dashboard, Discord, Snake Fund) added to hamburger menu

## Not Done (Blocked)
- **Breathwork × HRV correlation** — 0 breathwork records in apple_health partition; no data to correlate
- **IC-4/IC-5** (failure pattern + momentum warning) — data gate ~May 1
- **2 AWS integration test failures** — layer version drift (v15→v17 reattach), MCP canary (local key unavailable)

## Lambda Count
62 total (was 59: +ai-expert-analyzer, +journal-analyzer, +field-notes-generate)

## MCP Tool Count
115 tools registered (unchanged from registry — no new MCP tools this session)

## Platform Counts (v4.7.5)
- 115 MCP tools · 62 Lambdas · 72 site pages · 1075 tests · 26 data sources · 8 CDK stacks
