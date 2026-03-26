## v3.9.23 — 2026-03-25: DISC-7 Annotations + 3 Observatory Pages (Nutrition, Training, Inner Life)

### Summary
Full-stack DISC-7 behavioral response annotations shipped: MCP tool (`annotate_discovery` + `get_discovery_annotations`), site API merge in `handle_journey_timeline()`, and frontend rendering on Discoveries timeline cards. Product Board convened twice to define Observatory strategy — Matthew challenged the board to include Nutrition and Inner Life alongside Training, resulting in 5-observatory Evidence architecture. Three new pages built and deployed: Nutrition Observatory (amber accent, MacroFactor macros, protein adherence donut, trend chart), Training Observatory (crimson accent, Zone 2 ring gauge, 12-week bar chart, activity chips), Inner Life Observatory (violet accent, vice streak cards, mood valence chart, connection depth, honest "Building This" section). Three new API endpoints: `/api/nutrition_overview`, `/api/training_overview`, `/api/mind_overview`. Nav + footer updated with all 3 pages in Evidence dropdown.

### DISC-7: Discovery Annotations
- `mcp/config.py`: Added `ANNOTATIONS_PK` constant
- `mcp/tools_social.py`: `tool_annotate_discovery()` + `tool_get_discovery_annotations()` — writes to `USER#matthew#SOURCE#discovery_annotations / EVENT#{sha256_key}`
- `mcp/registry.py`: Both tools registered with schemas
- `lambdas/site_api_lambda.py`: Section 6 in `handle_journey_timeline()` — loads all annotations, merges by event_key hash match into timeline events
- `site/discoveries/index.html`: CSS `.tl-event__annotation*` classes + JS rendering "What I did" section with action tag and outcome

### Observatory Pages
- `site/nutrition/index.html`: Donut ring SVG (macro proportions), protein adherence gradient meter, area-fill trend chart, N=1 rules with watermark numbers
- `site/training/index.html`: Zone 2 animated ring gauge, activity type chips, stacked bar chart (total + Z2 overlay), centenarian framing
- `site/mind/index.html`: 3 signal cards hero, vice streak cards with bottom-fill animation, mood valence chart with zone gradient, "Building This" honest gap section
- `lambdas/site_api_lambda.py`: 3 new handlers — `handle_nutrition_overview()` (MacroFactor 30d), `handle_training_overview()` (Strava+Hevy+Whoop 90d), `handle_mind_overview()` (mood+vices+interactions+journal+temptations)
- `site/assets/js/components.js`: Evidence dropdown + footer updated (now 7 pages: Sleep, Glucose, Nutrition, Training, Inner Life, Benchmarks, Data Explorer)

### Product Board Sessions
- Round 1: Reviewed glucose + sleep pages, endorsed Training Observatory
- Round 2: Matthew challenged board on Nutrition — board agreed it's as data-rich as Sleep/Glucose
- Round 3: Matthew challenged board on Inner Life — board reversed position, acknowledged emotional health as the most differentiated content on the site
- Final consensus: 5 observatories (Sleep ✅, Glucose ✅, Nutrition ✅, Training ✅, Inner Life ✅)

### Deploy Log
- `life-platform-mcp` Lambda deployed (full mcp/ package)
- `life-platform-site-api` Lambda deployed (2x — DISC-7 merge, then observatory endpoints)
- S3: discoveries, nutrition, training, mind HTML + components.js + observatory.css
- CloudFront invalidated: 7 paths across all new pages + APIs

### Known Issues / Next Session
- Visual design quality: pages are functional but not yet at the infographic/editorial quality Matthew wants — next session should do focused visual overhaul one page at a time using Visualizer mockup workflow
- `observatory.css` exists but new pages use self-contained styles — consider consolidating
- MCP Lambda name is `life-platform-mcp` (not `life-platform-mcp-server`) — deploy_lambda.sh doesn't handle it (requires full zip with mcp/ directory)

---

## v3.9.22 — 2026-03-25: Discoveries page evolution — DISC-1/DISC-2 + critical API fix

### Summary
Product Board convened to review the Discoveries page (`/discoveries/`). Full 8-persona review produced a 12-task, 3-tier evolution spec (`docs/DISCOVERIES_EVOLUTION_SPEC.md`). Session 1 shipped DISC-1 (dynamic counterintuitive section), DISC-2 (confidence threshold on featured card), DISC-4 (mobile column fix), DISC-5 (strengthened disclaimer + analysis window dates), plus a critical bug fix: the site API was reading `record.get("pairs")` but the compute Lambda stores data as a `correlations` dict — the page was likely showing the empty state even when data existed.

### Changes

**lambdas/weekly_correlation_compute_lambda.py**
- DISC-1: Added `EXPECTED_DIRECTIONS` map (23 pairs with domain-knowledge expected direction)
- DISC-1: Added `counterintuitive` and `expected_direction` fields to each correlation result (flags when observed direction differs from expected AND |r| >= 0.2)
- Enhanced logging: counterintuitive pairs flagged with `** COUNTERINTUITIVE` in CloudWatch
- Fix: `_dec_correlations()` now handles `bool` before `int` check (Python `bool` is subclass of `int`, `Decimal("False")` crashes)

**lambdas/site_api_lambda.py** — `handle_correlations()`
- **Critical fix**: Now reads `record.get("correlations", {})` instead of `record.get("pairs", [])` — handles both dict (current compute format) and list (legacy) formats
- Added `_METRIC_META` lookup table: maps raw metric names to human-readable labels and source names (e.g. `hrv` → "Heart Rate Variability" / "Whoop")
- DISC-1: Surfaces `counterintuitive` and `expected_direction` fields in public response
- DISC-5: Surfaces `start_date` and `end_date` in standard response (already stored in DDB, now exposed)
- Field mapping fixes: `pearson_r`→`r`, `n_days`→`n`, `interpretation`→`strength` with fallbacks for both formats

**site/discoveries/index.html**
- DISC-1: Replaced 3 hardcoded counterintuitive `ci-card` elements with dynamic JS rendering from API data. Shows "no counterintuitive findings" empty state when all pairs match expected directions
- DISC-2: Featured card now filters for significant pairs only (FDR-significant OR p<0.05 with |r|>=0.3). Shows "No strong signal this week" card when no pairs qualify
- DISC-4: Mobile CSS now hides `.td-strength` column (n/strength) instead of `.td-stat` (variable names) — keeps the more important data visible on small screens
- DISC-5: N=1 disclaimer strengthened with: "These findings have not been externally validated and should not be used to make medical decisions."
- DISC-5: Analysis window dates (`start_date → end_date`) appended to the "last updated" note below stats strip

**docs/DISCOVERIES_EVOLUTION_SPEC.md** — NEW
- Full Product Board review output: 12 tasks across 3 tiers
- Tier 1 (fix what's broken): DISC-1 through DISC-5
- Tier 2 (make it a destination): DISC-6 through DISC-8 (timeline, behavioral response, bidirectional links)
- Tier 3 (growth engine): DISC-9 through DISC-12 (SEO, email CTA, auto-chronicle, share cards)
- Implementation order, data model changes, validation checklist

### Deployed
- `weekly-correlation-compute` Lambda deployed (v2)
- `life-platform-site-api` Lambda deployed
- `site/discoveries/index.html` synced to S3
- CloudFront invalidated: `/discoveries/*`, `/api/correlations*`
- Force-recomputed W13 correlations: 23 pairs, 5 FDR-significant, 1 counterintuitive, 88 days analyzed

### Validation
- API returns 23 pairs with human-readable labels and source names
- 1 counterintuitive finding detected: Steps → Sleep Score (expected positive, observed r=-0.271)
- Top pair: HRV → Recovery Score r=0.861 (Whoop × Whoop)
- 5 FDR-significant findings available for featured card

---

## v3.9.21 — 2026-03-25: Accountability page evolution — Product Board Review #4

### Summary
Product Board convened to review the Accountability page. All 8 personas provided findings. Six evolution tasks shipped in a single session: state hero enrichment with contextual explanation, 90-day accountability arc sparkline (SVG, color-coded dots, gradient fill, running average), nudge system evolved (emoji→SVG icons, live session counter, animated nudge feed), milestone tracker replaced with compact link to /achievements/, subscribe CTA with email capture, and public commitment enhanced with additional "the rule" paragraph.

### Changes

**site/accountability/index.html** — Full evolution
- State hero: new `state-hero__context` element with dynamic contextual sentence explaining WHY the state is what it is (streak + T0% + done/total + tailored message per state)
- NEW: 90-day Accountability Arc section — SVG sparkline of T0 compliance from /api/habits history, color-coded dots (green=perfect, amber=partial, red=missed), gradient fill, 100%/50% threshold lines, running average display
- Nudge system: emoji replaced with inline SVGs (fire, eye, clock, heart), live nudge counter ("N sent this visit"), animated nudge feed showing recent activity with timestamps
- Milestone tracker: removed 5-row duplicate (was redundant with /achievements/), replaced with single-line compact strip showing current streak + next milestone + link to badge gallery
- NEW: Subscribe CTA section — email input → SubscriberFunctionUrl POST, Enter key support, success/error feedback states
- Public commitment: enhanced blockquote styling (120px quote mark, more padding), added "the rule" paragraph below
- Calendar grid: responsive breakpoint added for 480px (6-col instead of 10-col)
- All API calls now use shared cached data pattern (single /api/habits fetch serves both arc + calendar)

### Deployed
- site/accountability/index.html synced to S3 + CloudFront invalidated

### Notes
- Nudge counter is session-only (in-memory on Lambda + client-side). Persistent DDB counter is a future backend task (requires CDK write-permission change).
- Subscribe CTA posts to existing SubscriberFunctionUrl (us-east-1) — no new backend needed.
- Product Board review documented: Mara (thin page, no return loop), Sofia (nudge buried, no social proof), Raj (no engagement loop, milestone duplication), Tyrell (visual sparsity, emoji inconsistency), Jordan (email capture missing, nudge goldmine), Ava (no content layer).

---

## v3.9.20 — 2026-03-25: HP-09 — Section consolidation (9→7), backend deploys for HP-06/HP-12/HP-14

### Summary
HP-09 section consolidation shipped: homepage restructured from 9 sections to 7. Day 1 vs Today moved up (immediately after hero for impact), What's New merged into Discoveries as "What the Data Found" with embedded pulse bar, standalone Quote section eliminated and embedded in About. Backend deploys completed: site-api Lambda redeployed (HP-06 dynamic correlations now live), shared layer v15 published and attached to all 15 consumers (HP-12 elena_hero_line + HP-14 chronicle_recent in write_public_stats pipeline).

### Changes

**site/index.html** (HP-09)
- Section order: Hero → Day 1 vs Today → Signals/Brief → What the Data Found → Chronicles → Features → About+Quote
- Merged "What's New" standalone section into Discoveries header as compact "// Live" pulse bar
- Renamed Discoveries heading to "What the Data Found"
- Moved Day 1 vs Today from position 6 to position 2 (immediately after hero)
- Eliminated standalone Quote section — embedded as border-left blockquote in About section
- Net: 1587 lines (was 1593), 2 sections removed, ~30% less mobile scroll depth
- All JS data loaders, share buttons, SVG glyphs, and fallback cards preserved

### Deployed
- site/index.html synced to S3 + CloudFront invalidated
- site-api Lambda deployed (HP-06 `?featured=true` live)
- Shared layer v15 published + attached to 15 consumers (HP-12/HP-14 pipeline ready)

### Notes
- HP-06: Dynamic discoveries will replace fallback cards once weekly_correlations data exists in DynamoDB
- HP-12: Elena hero one-liner will appear once daily brief passes `elena_hero_line` to write_public_stats — requires daily_brief_lambda.py edit (future session)
- HP-14: Chronicle cards will populate on next daily brief run (chronicle_recent already computed by _get_recent_chronicles)

---

## v3.9.19 — 2026-03-25: HP-06/HP-12/HP-14 backend + frontend — dynamic discoveries, Elena hero line, chronicle cards

### Summary
Three home page evolution tasks completed (from HOME_EVOLUTION_SPEC.md Product Board sprint). HP-06 adds `?featured=true&limit=3` support to `/api/correlations` so the homepage dynamic discoveries JS (deployed in v3.9.18) pulls live data instead of showing fallback cards. HP-12 adds `elena_hero_line` field to `public_stats.json` pipeline so Elena Voss's weekly one-liner appears in the hero section. HP-14 adds `chronicle_recent` array to `public_stats.json` and a new "Recent Chronicles" section on the homepage with 3 dynamically-loaded entry cards.

### Changes

**lambdas/site_api_lambda.py**
- `handle_correlations()` now accepts `event` param for query string parsing
- `?featured=true` returns flat array of top significant correlations (p<0.05 or FDR-significant), sorted by |r|
- `?limit=N` controls result count (1-20, default 3)
- Added `p`, `description`, `direction`, `metric_a`, `metric_b` fields to correlation responses
- Auto-generates description for correlations missing one
- Early-routed in `lambda_handler` before generic GET router so event is passed

**lambdas/site_writer.py** (shared layer v13)
- `write_public_stats()` accepts new `elena_hero_line` param (HP-12)
- New `_get_recent_chronicles()` helper queries last 3 chronicles from DynamoDB (HP-14)
- `chronicle_recent` array added to `public_stats.json` payload
- `elena_hero_line` field added to `public_stats.json` payload

**site/index.html**
- New `<section id="chronicle-cards">` between Discoveries and Day 1 vs Today
- JS loader reads `window.__amjStats.chronicle_recent` with fallback to direct fetch
- Responsive: stacks to 1-column on mobile (<768px)
- Graceful degradation: shows "Chronicles publish every Wednesday" fallback if no data

### Deployed
- site_api_lambda deployed
- Shared layer v13 published + attached to 15 consumers
- Site HTML synced + CloudFront invalidated

### Task status (HOME_EVOLUTION_SPEC.md)
- HP-06 ✅ (backend complete — frontend was already deployed in v3.9.18)
- HP-12 ✅ (backend complete — frontend was already deployed in v3.9.18)
- HP-14 ✅ (backend + frontend complete)

### Notes
- HP-12 `elena_hero_line` will be null until a caller (e.g. wednesday-chronicle Lambda) passes the value to `write_public_stats()`
- HP-14 `chronicle_recent` will populate automatically on next daily-brief run (reads from DynamoDB chronicle partition)
- HP-06 dynamic discoveries will show real data on next page load (replaces fallback cards)

---

## v3.9.13 — 2026-03-25: Benchmarks → "The Standards" — 6-domain research reference redesign

### Summary
Complete redesign of the Benchmarks page from a physical-lifts-only Centenarian Decathlon tracker into "The Standards" — a 6-domain, 27-benchmark research reference library. Product Board convened ground-up to redefine purpose: this page answers "what should a human be measuring, and what does 'good' look like according to the research?" Covers Physical Capacity, Sleep & Recovery, Cognitive & Intellectual, Emotional & Psychological, Social Connection, and Behavioral Discipline. Each benchmark has an evidence rating (●●●/●●/●), a letter grade (A–F), a trend arrow (▲/▶/▼ vs 30d ago), and a research citation. Interactive self-assessment lets visitors check themselves against the research. Three deploy iterations: base page, grade badges, trend indicators + API field fix.

### Changes

**site/benchmarks/index.html** (COMPLETE REWRITE)
- Renamed "Centenarian Decathlon" → "The Standards"
- 6 domains: Physical (6 benchmarks), Sleep (5), Cognitive (4), Emotional (4), Social (4), Discipline (4)
- Unique visual per domain: arc gauges, sleep architecture bars, animated bookshelf, sentiment waveform, Dunbar rings, consistency heatmap
- Letter grade badges (A–F) on every card, auto-computed from % to target
- Trend indicator row per card (▲ improving / ▶ flat / ▼ declining vs 30d ago) — hidden until `/api/benchmark_trends` endpoint exists
- Evidence legend + grade scale + trend legend in page header
- Interactive "Check Yourself Against the Research" self-assessment (6 domain questions, client-side only)
- Research citations: Mandsager (JAMA 2018), Leong (Lancet 2015), Cappuccio (Sleep 2010), Xie (Science 2013), Bavishi (SSM 2016), Holt-Lunstad (PLOS Med 2010), Dunbar (2010), Lally (EJSP 2010), Emmons (JPSP 2003), Epel (PNAS 2004), WHO-5
- Data from: `/api/vitals` (sleep, HRV, RHR, weight), `/api/habits` (T0 completion), `/api/vice_streaks` (streak days)
- No new API endpoints — uses existing site-api

### Bug fixes (across 3 iterations)
- Remapped JS data loading from non-existent `/api/character` fields to correct `/api/vitals` field names
- Fixed double `.json()` call on character response stream
- Removed `overflow: hidden` that clipped grade badges
- Fixed vice streak field name (`current_streak` not `streak_days`)

### Deployed
- 4 S3 uploads + CloudFront invalidations this session

---

## v3.9.12 — 2026-03-25: Habits + Supplements page overhauls — Product Board Phase A/B/C

### Summary
Product Board convened for two complete page rewrites. Habits page ("The Operating System") restructured from a 65-item flat list to a 3-zone behavioral architecture: Foundation (T0, 7 habits) → System (T1, 15 purpose-grouped habits) → Horizon (T2, 15 locked aspirational). 21 supplement habits and 7 hygiene habits removed — supplements now live on their own page. Supplements page ("The Pharmacy") rebuilt with evidence-first visual hierarchy: confidence rings, purpose icons, board member attribution, genome SNP badges, and an "honest assessment" transparency section. Both pages are entirely client-side rendered from embedded registry data — no new API endpoints.

### Changes

**site/habits/index.html** (COMPLETE REWRITE)
- Renamed "Habit Observatory" → "The Operating System"
- Three-zone architecture: Foundation (T0) → System (T1 by purpose) → Horizon (T2)
- 21 supplement habits removed (belong on /supplements/)
- 7 hygiene habits removed (maintenance, not transformation)
- Visible behavioral habit count: 65 → ~37
- SVG circular progress rings on T0 cards
- 30-day sparklines on T0 cards
- "The Why" quotes from `why_matthew` registry field
- Science rationale + evidence badges (strong/moderate/emerging) per habit
- Tier-based color banners with glowing status dots
- Purpose-grouped Tier 1 accordions: Sleep Architecture, Training Engine, Fuel & Metabolic, Mind & Growth, Discipline Gates, Data Signals
- Faded/locked T2 horizon cards
- Vice Discipline Gates elevated to dedicated section
- Daily Pipeline visualization (morning → evening stack flow)
- Heatmap, keystone correlations, DOW pattern, decision fatigue — all retained in Intelligence section
- SEO meta tags for "habit system", "gamify health"

**site/supplements/index.html** (COMPLETE REWRITE)
- Renamed "Supplement Protocol" → "The Pharmacy"
- "No affiliate links · No sponsorships · No brand promotions · Just the data" integrity banner
- Purpose-grouped: Longevity Foundation (6) → Muscle & Performance (5) → Metabolic (3) → Sleep (4) → Cognitive (3)
- Evidence confidence rings per card (A/B/C rating, proportional fill, tier-colored)
- Left border accent by evidence strength (green/amber/gray)
- Per-card badges: timing, board member attribution, synergy group, genome SNP
- Expandable "Why I take it" (default open) + collapsible "What the science says"
- "What I'm watching" footer per card (expected impact + validation metric)
- Genome-Informed section with 3 SNPs (VDR Bsm1, FADS2 rs1535, SLC39A4)
- "Supplements I'm Questioning" honest assessment section (7 items)
- Client-side rendering from embedded registry data (no API dependency)

### Deployed
- Habits: `aws s3 cp` to S3 + CloudFront invalidation `/habits/*`
- Supplements: download from Claude outputs → `aws s3 cp` + CloudFront invalidation `/supplements/*`

### Bugs fixed
- `reveal` class on JS-injected T0 cards caused invisible cards (IntersectionObserver timing)
- `create_file` tool writes to Claude container, not user Mac — use `Filesystem:write_file` or download

---

## v3.9.11 — 2026-03-24: Character page RPG overhaul — Product Board Phase A/B/C

### Summary
Complete Character page rewrite implementing all three phases from a Product Board review session. The page transforms from a data dashboard into a full RPG-style character sheet with tier-based visual theming, trading card hero layout, chunky stat bars, tier emblems, sparklines, visual timeline, collapsible badges, and a level-up notification CTA. The page now evolves visually as Matthew progresses through tiers (Foundation → Elite), with every accent color, glow, and emblem shape shifting automatically.

### Changes

**site/character/index.html** (COMPLETE REWRITE)

Phase A — Visual identity:
- Tier-based CSS theming via `data-tier` attribute on `<body>` (5 palettes: Foundation/green, Momentum/amber, Discipline/steel, Mastery/gold, Elite/royal)
- All `--tier-accent`, `--tier-glow`, `--tier-emblem-bg` custom properties shift per tier
- RPG-style chunky stat bars (14px tall, notch marks at 25/50/75) replacing 2px lines
- 5 tier-specific SVG emblems: hexagon → hexagon+flame → shield → ornate shield → crown+shield
- "Level up imminent" animated banner when XP ≥ 80% of next level
- Section reorder: Trading Card hero → Next Level → Intro → Radar → Pillars → Timeline → Heatmap → Badges → Methodology

Phase B — Storytelling:
- 30-day sparkline SVGs on each pillar card (8-week trend from `pillar_history`)
- Visual vertical timeline replacing flat text event log (glowing dots for level-ups)
- RPG flavor text for each tier ("The proving ground. Most people never leave this tier.")
- Trading card layout: screenshot-ready hero with emblem, all 7 pillar mini-bars, footer stats, tier dots
- XP progress bar showing exact progress to next level

Phase C — Growth:
- "Notify me on level-up" micro-subscription CTA (`source: levelup_alert`)
- SEO-optimized meta tags targeting "gamify health", "RPG character sheet", "level up life"
- Collapsible badge groups with earned/total counts (reduces mobile scroll ~40%)

### Deployed
- `aws s3 sync site/ s3://matthew-life-platform/site/ --delete`
- CloudFront invalidation `/character/*`


## v3.9.10 — 2026-03-24: Navigation restructure — 6-section board-approved IA

### Summary
Joint Product Board (8 personas) × Personal Board (14 personas) navigation architecture review across 4 rounds. Unanimous vote (20-0-1) on a 6-section restructure replacing the previous 5-section layout. New sections: Story | Pulse | Evidence | Method | Build | Follow. Multiple page renames for visitor clarity. Grouped dropdown sub-headers in Method section. Footer updated to 6 columns. All changes in `components.js` (single file, 54 pages update automatically).

### Changes

**site/assets/js/components.js** (v2.0.0 — REWRITTEN)
- 6-section nav replacing 5-section: Story, Pulse, Evidence, Method, Build, Follow
- "The" prefix dropped from all section labels (board vote: tighter, more modern)
- Page renames: Live→Today, Character Sheet→Character, Explorer→Data Explorer, Intelligence→The AI, Experiments→Active Tests, Weekly Journal→Chronicle
- New `groups` data structure for Method dropdown with sub-headers ("What I Do" / "What I Tested")
- Supplements moved from Evidence to Method (board consensus: supplements are interventions, not measurements)
- Milestones moved to Pulse (board consensus: milestones are journey/progress, not evidence)
- Sleep, Glucose, Benchmarks grouped as Evidence (case study pages proving the experiment works)
- Footer columns updated to match 6-section structure
- Bottom nav updated: Home, Today, Character, Chronicle, Ask
- Mobile overlay uses same section grouping with sub-headings
- Removed old reading-path builder (now in nav.js)

**site/assets/css/base.css** (3 additions)
- `.nav__dropdown-heading` — sub-header styling in desktop dropdown menus
- `.nav__dropdown-divider` — divider line between dropdown groups
- `.nav-overlay__subheading` — sub-header styling in mobile overlay
- Footer grid: `repeat(4, 1fr)` → `repeat(6, 1fr)` for 6-column layout

### Board Review Summary
- 4 rounds of structured debate across Product Board + Personal Board
- Key decisions: 6 sections (not 5 or 7), intent-based grouping, editorial naming voice
- Attia's trust framework adopted: Story=trust the person, Pulse=trust the commitment, Evidence=trust the results, Method=trust the approach
- Rhonda Patrick broke the tie on Supplements placement (intervention ≠ measurement)
- Huberman solved "Experiment within The Experiment" echo by proposing "The Method"
- Conti's 30-day time-box: ship now, watch visitor behavior, rename if needed

### Not deployed
- Files committed but not synced to S3. Deploy with:
  ```bash
  aws s3 sync site/ s3://matthew-life-platform/site/ --delete
  aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/assets/js/components.js" "/assets/css/base.css"
  ```

---

## v3.9.9 — 2026-03-24: Content consistency architecture (ADR-034), doc sync, public_stats fix

### Summary
Joint Product + Technical Board session on website content consistency. Built a 3-layer content architecture: `site_constants.js` (single source of truth for factual values), `components.js` (shared nav/footer/CTA/bottom-nav), `content_manifest.json` (prose inventory for journey reframes), `data_sources.json` (source registry). Created migration tooling + CI linter. Also: doc sync (17 tasks flipped ⬜→✅ in PROJECT_PLAN), REDESIGN_SPEC backend endpoints marked done, public_stats.json staleness root-caused and fixed (site_writer.py added to shared Lambda layer v11), OE-09 doc consolidation, CI/CD p3 scripts restored from archive.

### Changes

**site/assets/js/site_constants.js** (NEW — ADR-034)
- Single source of truth: journey constants (302, 185, dates, phase), platform counts, bios, OG meta descriptions, reading path definitions
- Auto-injects values into `data-const="key.path"` HTML attributes at page load

**site/assets/js/components.js** (NEW — ADR-034)
- Shared structural components: nav, mobile overlay, footer, bottom-nav, subscribe CTA, reading path
- Pages use mount-point `<div id="amj-nav">` etc. — edit once, 54 pages update
- Contains nav section definitions, footer column layout, subscribe helper function

**site/data/content_manifest.json** (NEW — ADR-034)
- Prose inventory: every journey-sensitive paragraph catalogued per-page
- Categories: constant / api_driven / prose_with_facts / narrative / archive
- `fragile_strings` list for CI lint: "302", "185", dates, tool counts
- Explicitly notes methodology/source grid lists "Oura" which is a factual error

**site/data/data_sources.json** (NEW — ADR-034)
- 19-source registry with id, name, category, metrics, ingestion method
- Replaces per-page hardcoded source lists (methodology/, platform/, about/)

**deploy/lint_site_content.py** (NEW — ADR-034)
- CI-ready validator: data-const refs resolve, fragile strings not hardcoded in migrated pages, source count consistency

**deploy/migrate_page_to_components.py** (NEW — ADR-034)
- Mechanical migration: strips inline nav/footer/CTA, replaces with mount-point divs
- `--all --dry-run` mode tested: 50 of 50 pages eligible, avg 30% size reduction
- Handles: nav+overlay, bottom-nav, footer, subscribe CTA, reading path, duplicate amjSubscribe removal

**docs/DECISIONS.md** (ADR-034 added)
- Full architecture decision record documenting the 3-layer approach, alternatives considered (Hugo, SSI, CMS, find-and-replace), and rationale

**docs/PROJECT_PLAN.md** (major sync)
- 17 task IDs flipped ⬜→✅: CHAR-1/2/3/6, PLAT-2, PROTO-2/3/4, EXP-1, HAB-4, BOARD-2, NEW-1/2/3/4, HOME-2/3
- Phase 1 summary updated, OE-09 marked done

**docs/WEBSITE_REDESIGN_SPEC.md** (sync)
- 4 "still needed" backend endpoints marked ✅ with actual function names + line numbers
- Phase 2 + Phase 3 status updated

**deploy/build_layer.sh** (ENHANCED)
- Added `site_writer.py` to shared layer module list

**ci/lambda_map.json** (ENHANCED)
- `site_writer.py` moved from skip_deploy to shared_layer.modules

**deploy/p3_build_shared_utils_layer.sh** (RESTORED from archive)
- Was in `deploy/archive/20260311/` but CI/CD pipeline references `deploy/`
- Updated module list includes `site_writer.py`, `sick_day_checker.py`, `digest_utils.py`

**deploy/p3_attach_shared_utils_layer.sh** (RESTORED from archive)
- Updated consumer list matches ci/lambda_map.json (15 consumers)

**docs/ONBOARDING.md** (sync)
- Dead `USER_GUIDE.md` ref → `PLATFORM_GUIDE.md`; sources 20→19; tools 88→95; Lambdas 42→49; Google Calendar removed

**docs/PLATFORM_GUIDE.md** (sync)
- Sources 20→19; Google Calendar retired in data sources + auto-sync + NL query section

**docs/MCP_TOOL_CATALOG.md** (sync)
- Dead `USER_GUIDE.md` ref → ARCHITECTURE.md + SCHEMA.md

### Deployed
- `python3 deploy/fix_public_stats.py --write` — fresh public_stats.json from live DynamoDB
- `npx cdk deploy LifePlatformCore` — shared layer v11 published with site_writer.py
- `bash deploy/p3_attach_shared_utils_layer.sh` — all 15 consumers on layer v11
- Tomorrow's daily brief will auto-refresh public_stats.json via site_writer in the layer

---

## v3.9.8 — 2026-03-24: Nav update (3 new pages), Board sub-pages, sitemap expansion

### Summary
Nav dropdown update across all 45+ HTML files adding Explorer, Milestones, and Weekly Snapshots links. Built BOARD-2 Technical Board and Product Board sub-pages with cross-linked tab navigation. Updated sitemap.xml. Confirmed HOME-3 complete.

### Changes

**deploy/update_nav_links.py** (NEW)
- Idempotent batch nav updater — adds /explorer/, /achievements/, /weekly/ to desktop dropdown, mobile overlay, and footer across all site HTML files

**site/board/technical/index.html** (NEW — BOARD-2)
- 12 technical persona roster with bios, standing questions, archetype descriptions
- Architecture review stats (13 reviews, A− grade, 3 open findings)
- 3 standing sub-board cards (Architecture Review, Intelligence & Data, Productization)
- "How it works" section explaining review cadence and intentional disagreement

**site/board/product/index.html** (NEW — BOARD-2)
- 8 product persona roster with bios, standing questions
- 4 designed tension pair visualizations (Simplify vs Features, Marketing vs Rigor, etc.)
- Decision framework section with throughline tiebreaker rule

**site/board/index.html** (ENHANCED)
- Added 3-tab board navigation (Health / Technical / Product)
- Board tabs CSS with responsive stacking

**site/assets/js/nav.js** (ENHANCED)
- Reading paths updated: /board/ → /board/technical/ → /board/product/ → /platform/

**site/sitemap.xml** (ENHANCED)
- Added /board/technical/, /board/product/, /weekly/, /achievements/

**45 site HTML files** (BATCH UPDATE)
- Desktop dropdown "The Data": +Explorer, +Milestones after Benchmarks
- Desktop dropdown "Follow": +Weekly Snapshots after Weekly Journal
- Mobile overlay: same additions
- Footer: same additions

**docs/WEBSITE_REDESIGN_SPEC.md** (UPDATED)
- BOARD-2 marked ✅, HOME-3 confirmed ✅

---

## v3.9.7 — 2026-03-24: Data Explorer, Weekly Snapshots, Decision Fatigue Signal, 5 more spec closures

### Summary
Phase 2+3 build sprint. Two new pages (Data Explorer at /explorer/, Weekly Snapshots at /weekly/), one new habits feature (HAB-4 Decision Fatigue Signal), and 5 previously-unverified spec items confirmed as already shipped.

### Changes

**site/explorer/index.html** (NEW — NEW-1)
- Interactive correlation explorer with filterable card grid
- Filter chips: All / Strong / FDR Significant / Predictive (lagged) / Positive / Negative
- Clickable detail panel with interpretation text, strength labels, methodology
- Consumes `/api/correlations` endpoint

**site/weekly/index.html** (NEW — NEW-2)
- Weekly report card with prev/next week navigation
- Key numbers grid, 7-day heatmap strip, character pillar scores row
- Auto-generated summary narrative, empty-week state
- Archive grid of all weeks since journey start
- Consumes `/api/snapshot` and `/api/journey_waveform`

**site/habits/index.html** (HAB-4)
- Decision Fatigue Signal section added before email CTA
- Fatigue index gauge (0-100), 14-day sparkline, trend detection
- Three-tier color-coded insight text, auto-hides with insufficient data

**site/assets/js/nav.js**
- Added reading paths for /explorer/, /weekly/, /achievements/

**docs/WEBSITE_REDESIGN_SPEC.md**
- HOME-2, PROTO-2, PROTO-3, PROTO-4, EXP-1, HAB-4, NEW-1, NEW-2 marked ✅

---

## v3.9.6 — 2026-03-24: Dark/Light mode, Milestones Gallery, 5 spec closures, CHRON-3 fix script

### Summary
NEW-4 dark/light mode toggle implemented across all pages via CSS custom properties + nav.js injection.
NEW-3 Milestones Gallery page built at /achievements/ pulling from /api/achievements endpoint.
CHAR-1, CHAR-2, CHAR-3, CHAR-6, PLAT-2 confirmed already shipped and marked in spec.
CHRON-3 root cause diagnosed (handler mismatch) and fix script written.

### Changes

**site/assets/css/tokens.css**
- Added `:root[data-theme="light"]` block with warm off-white palette, darker greens for legibility

**site/assets/js/nav.js**
- Theme toggle button auto-injected into nav on all pages (sun/moon SVG icons)
- Reads/writes localStorage for persistence, defaults to dark

**site/assets/css/base.css**
- Added `.theme-toggle` button styles + light mode nav backdrop override

**site/achievements/index.html** (NEW)
- Full Milestones Gallery page: progress ring, summary strip, category-grouped badge grid
- Pulls live data from `/api/achievements` endpoint
- Category colors: streak (amber), level (green), milestone (blue), data (purple), science (red)
- Earned badges show date chips + glow; locked badges show unlock hints

**deploy/fix_chronicle_handler.sh** (NEW)
- CHRON-3 fix: updates Lambda handler from `lambda_function.lambda_handler` to `wednesday_chronicle_lambda.lambda_handler`
- Also checks chronicle-approve and chronicle-email-sender handlers
- Verifies EventBridge schedule rule

**docs/WEBSITE_REDESIGN_SPEC.md**
- CHAR-1, CHAR-2, CHAR-3, CHAR-6, PLAT-2: marked ✅ confirmed shipped
- NEW-3: marked ✅ page built
- NEW-4: marked ✅ implemented

---

## v3.9.5 — 2026-03-24: CI/CD first deploy test + smoke/I1 fixes

### Summary
First end-to-end CI/CD deploy test completed. Pipeline deployed canary Lambda to AWS successfully.
Two post-deploy test failures fixed: qa-smoke Lambda not yet created (graceful skip added),
I1 handler check not respecting `not_deployed` flag (filter added). Pipeline confirmed fully
green on re-run. Production environment approval gate verified.

### Changes

**lambdas/canary_lambda.py**
- Added CI/CD pipeline version marker (docstring comment — deploy trigger)

**.github/workflows/ci-cd.yml**
- Smoke test: check if qa-smoke Lambda exists before invoking; warn and skip if missing
- Prevents false failure when qa-smoke CDK skeleton not yet deployed

**tests/test_integration_aws.py**
- I1 test: added `_load_not_deployed_functions()` helper
- Skips Lambdas flagged `not_deployed` in lambda_map.json (google-calendar, dlq-consumer)
- Prevents false failures for deliberately undeployed CDK skeletons

**ci/lambda_map.json**
- Marked `dlq-consumer` as `not_deployed: true` (Lambda not yet created in AWS)

---

## v3.9.4 — 2026-03-23: CI/CD pipeline activation — 3 blockers resolved

### Summary
Activated the dormant CI/CD pipeline (GitHub Actions + OIDC). The pipeline was fully designed
(7 jobs, auto-rollback, 9 integration checks) but had never passed. Three sequential blockers
resolved: F821 lint errors, missing boto3 CI dependency, bash pipefail crash in deprecated
secrets scan. Shared layer (v10) attached to all 15 consumer Lambdas. Pipeline now passing
lint + unit tests + plan (pending final verification). Draft `ask_endpoint.py` archived.

### Changes

**lambdas/daily_brief_lambda.py**
- Fix F821: `hrv_30d_recs` undefined in `lambda_handler` trend-building section
- Added local `_whoop_30d = fetch_range("whoop", ...)` call (was referencing variable
  from `gather_daily_data()` scope which doesn't exist in `lambda_handler`)
- All 3 trend arrays (HRV, sleep, recovery) now use `_whoop_30d` instead of `hrv_30d_recs`

**lambdas/ask_endpoint.py → deploy/archive/ask_endpoint.py**
- Archived draft integration file (7 F821 errors: `_error`, `CORS_HEADERS` undefined)
- Was never deployed — functionality already merged into `site_api_lambda.py`

**.github/workflows/ci-cd.yml**
- Add `boto3 botocore` to test job dependencies (was only installing `pytest`)
- Remove unsupported `--quiet` flag from `python3 -m venv` in CDK diff step
- Fix deprecated secrets scan: add `|| true` to grep pipeline to prevent
  `bash -eo pipefail` crash when zero matches found (false positive failure)
- Fix layer version check: JMESPath used `LayerArn` but AWS API returns `Arn`
  (both Plan and Deploy jobs had same bug — layers were attached but query found nothing)

**AWS infrastructure**
- Attached `life-platform-shared-utils:10` layer to all 15 consumer Lambdas
  (daily-brief, weekly-digest, monthly-digest, nutrition-review, wednesday-chronicle,
  weekly-plate, monday-compass, anomaly-detector, character-sheet-compute,
  daily-metrics-compute, daily-insight-compute, adaptive-mode-compute,
  hypothesis-engine, dashboard-refresh, weekly-correlation-compute)

### CI/CD pipeline status
- OIDC role: ✅ exists (`github-actions-deploy-role`)
- Lint + Syntax: ✅ passing
- Unit Tests (8 linters + deprecated secrets scan): ✅ passing
- Plan (CDK diff + AWS checks + layer verify): ✅ passing (run 23470795396)
- Deploy: ✅ ready (skipped correctly — no code changes in dispatch run)
- GitHub `production` Environment: needs verification (manual approval gate for deploys)

---

## v3.8.9 — 2026-03-22: Nav restructure — rename + reorganise

### Summary
Board-reviewed navigation restructure. Consulted all 6 AI board personas on clarity and
throughline alignment. Applied renaming and structural changes across all 44 HTML files.
Zero URL changes — only nav labels and groupings updated.

### Changes

**All `site/**/*.html` (44 files) — desktop nav + mobile overlay**
- THE STORY: removed "Home" dropdown child (logo links home); renamed "About" → "The Mission"
- THE DATA: renamed "Character" → "Character Sheet"; renamed "Accountability" → "Progress";
  moved Sleep, Glucose, Supplements, Benchmarks from THE SCIENCE into THE DATA
- THE SCIENCE: now only Protocols, Experiments, Discoveries (the methodology pipeline)
- THE BUILD: renamed "Board" → "AI Board"
- FOLLOW: renamed "Chronicle" → "Weekly Journal"; renamed "Ask" → "Ask the Data"
- `is-active` parent-dropdown class correctly migrated for pages whose active item moved
  from THE SCIENCE to THE DATA (sleep, glucose, supplements, benchmarks pages)

**site/start/index.html**
- Path card title "The Chronicle" → "Weekly Journal"; CTA "Read the chronicle →" → "Read the journal →"

**docs/WEBSITE_ROADMAP.md**
- Updated "Navigation Architecture" section to reflect 5-section dropdown structure

### Board findings (condensed)
- Unanimous: "My Story" vs "About" was the #1 friction point — two doors to the same room
- "Chronicle" is opaque to new visitors; "Weekly Journal" is immediately legible
- THE SCIENCE was bloated at 8 items; Sleep/Glucose/Supplements/Benchmarks are data views, not science
- "Board" in THE BUILD reads as kanban/dashboard; "AI Board" disambiguates

---

## v3.8.8 — 2026-03-22: Phase 0 website data fixes

### Summary
Surgical data fixes across the live site per WEBSITE_REDESIGN_SPEC.md Phase 0 task list.
No page redesigns — these are correctness fixes only.

### Changes

**lambdas/site_api_lambda.py**
- G-3: `handle_vitals()` — always return last known weight via `_latest_item("withings")` regardless
  of date window; add `weight_as_of` field to response; fix `if current_weight` to `is not None`
- G-4: `handle_journey()` — remove `_error(503)` fallback when no 120d weight data;
  fall back to `_latest_item("withings")` for last known weight; if no weight at all,
  use journey start (302 lbs) so progress_pct always computes

**site/index.html**
- G-3: Ticker weight display — secondary fetch to `/api/vitals` when public_stats has null weight;
  shows "287.7 LBS (MAR 7)" format when `weight_as_of` is >3 days old

**site/story/index.html** — STORY-1
- Add IDs `story-lambda-count`, `story-data-sources-stat`, `story-tools-count` to data-moment spans
- Wire to `platform.lambdas`, `platform.data_sources`, `platform.mcp_tools` in existing loader
- test_count and monthly_cost left static (not in public_stats.json yet)

**site/platform/index.html** — PLAT-1
- Add IDs `plat-mcp-tools`, `plat-data-sources`, `plat-lambdas` to header stat cards
- New JS loader reads public_stats.json and updates all three values on page load

**site/protocols/index.html** — PROTO-1
- Remove hardcoded fallback adherence values (78%, 82%, 90%, etc.)
- `applyFallback()` now shows "—" (em dash) when API is unavailable

### Investigated (no code change needed)
- CHRON-1: All post navs (week-00, 01, 02, 03) already have current 5-section structure ✓
- CHRON-2: `site/journal/posts/week-01/` exists but has no content ("See S3" placeholder);
  added to backlog for Elena Voss content generation session
- G-5: Streak already defaults to 0 in unified loader (line 1354, `!= null` check) ✓
- G-7: `/api/subscribe` routes to `email_subscriber_lambda.py` via CloudFront; code looks correct;
  suspect SES verification issue — check `lifeplatform@mattsusername.com` verified in us-west-2

### Pending (requires Matthew input)
- G-8: Privacy page contact email `matt@averagejoematt.com` — confirm correct address

---

## v3.8.7 — 2026-03-22: CI/CD pipeline activation

### Summary
The GitHub Actions CI/CD pipeline (ci-cd.yml) was fully built post-R13 but never activated.
This version fixes the one outstanding gap (lambda_map.json) and activates the pipeline.
The pipeline covers: lint → pytest (83+ tests) → plan (cdk diff + layer check) → deploy
(manual approval gate) → smoke test → auto-rollback → SNS notify on failure.

### Changes

**ci/lambda_map.json** — site_api fix
- Moved `lambdas/site_api_lambda.py` from `skip_deploy` → `lambdas` section
  with `function: life-platform-site-api`. Was incorrectly skipped (it's a real
  deployed Lambda in us-west-2, deployable via deploy_lambda.sh).
- Bumped `_updated` to v3.8.7.

**Activation steps (run manually):**
1. `bash deploy/setup_github_oidc.sh` — creates OIDC provider + IAM role in AWS
2. Create 'production' Environment in GitHub repo settings
3. `git add -A && git commit -m "v3.8.7: activate CI/CD pipeline" && git push`
4. Approve the deploy job in GitHub Actions UI (or skip if no Lambda changes)

---

## v3.8.6 — 2026-03-22: Phase 2 /live/ + /character/ enhancements

### Summary
Phase 2 completes its first three targets. /live/ gets a glucose snapshot panel (new data
not previously shown). /character/ gets a live state banner and dynamic tier highlighting.

### Changes

**site/live/index.html** — Glucose snapshot panel
- New `<!-- Glucose Snapshot -->` panel-section inserted after sleep section.
  Shows: Time In Range % (today) with progress bar and status label, 30-day TIR avg,
  variability status, days tracked, and a 20-point TIR sparkline SVG.
- New `initGlucose()` async function fetches `/api/glucose` (endpoint exists; was unused on live page).
  Gracefully hides the section on 503 or missing data.
- Added `initGlucose()` call in init sequence (after sleep, before training).

**site/character/index.html** — Live state banner + dynamic tier
- New `#char-state-banner` div inserted between page-header and intro narrative.
  Two rows: Level · Tier · Days active | Strongest pillar → Bottleneck pillar.
  All fields populated by `hydrate()` from live character data.
- `hydrate()` extended: populates banner fields (cbs-level, cbs-tier, cbs-days,
  cbs-strongest, cbs-bottleneck). Tier highlight logic resets all 4 tier rows to
  `text-faint` then marks the current tier in `accent` with `← current` label.
- Tier description rows now have IDs (td-foundation, td-momentum, td-chisel, td-elite)
  and `.td-name` / `.td-desc` classes for JS targeting.
- Removed hardcoded `color:var(--accent)` on Chisel row; tier is now data-driven.

---

## v3.8.5 — 2026-03-22: Phase 2 /discoveries/ empty state

### Summary
Task 47: /discoveries/ no longer shows a blank page when correlation data is absent.
Replaced bare "No correlation data yet." messages with a rich empty state showing
days collected, a progress bar toward the 90-day rolling window, and a clear unlock
condition. When data IS present, adds a "last updated" note below the stats strip.

### Changes

**site/discoveries/index.html** — JS rewrite
- `renderEmptyState()`: calculates days since journey start (2026-02-09), pct toward
  90-day window, needed days remaining. Renders consistent banner in featured card,
  spotlight grid, and archive table.
- `loadDiscoveries()`: early-exit to `renderEmptyState()` on 503, empty pairs, or fetch
  error. Removes now-dead `strong` variable and the `if (top)` branch.
- Last-updated note injected below stats strip when data loads: week of last run,
  next run day (Sunday), days tracked count.
- Minor: spotlight tag spacing fix (space before `·`).

---

## v3.8.4 — 2026-03-22: Phase 2 /experiments/ depth + Keystone group fix

### Summary
Two items: /experiments/ page gets Active Experiment Spotlight + delta chips on completed cards.
Keystone Spotlight group data fix — `handle_habits()` was reading `SOURCE#habit_scores` for
group data but groups live in `SOURCE#habitify` as `by_group`. Added second DynamoDB query
to cross-join. Verified live: `keystone_group: "Nutrition"` at 63% 90-day avg.

### Changes

**lambdas/site_api_lambda.py** — two endpoints updated
- `handle_experiments()`: returns `outcome`, `result_summary`, `primary_metric`,
  `baseline_value`, `result_value`, `metrics_tracked`, `duration_days`, `days_in`,
  `progress_pct`, `confirmed`, `hypothesis_confirmed`. All previously dropped silently.
- `handle_habits()`: added second DynamoDB query against `SOURCE#habitify` to pull
  `by_group` data. Cross-joined into history `groups` field when `habit_scores` has
  no flat `group_*` fields. `pct` (0.0–1.0) converted to 0–100 integer.
  `group_90d_avgs` and `keystone_group` now populate correctly.

**site/experiments/index.html** — Phase 2 content depth
- Active Experiment Spotlight: accent-bordered card above filter list showing name,
  hypothesis, day counter, progress bar (if `planned_duration_days` set), metric chips.
  Hidden when no active experiment.
- Delta chips on completed cards: `↑ +8.2 HRV` / `↓ -4.1 weight` in green/red.
  Lower-is-better metrics (weight, rhr, glucose) auto-flip color logic.
- Confirmed/refuted badges from `hypothesis_confirmed` field.
- Primary metric replaces generic Category field when available.

### Verification
- `keystone_group: "Nutrition"`, `keystone_group_pct: 63` — confirmed live
- `by_group` has all 9 groups: Nutrition, Growth, Wellbeing, Data, Performance,
  Discipline, Recovery, Hygiene, Supplements
- `best_day: 6` (Sunday is strongest day)

---

## v3.8.3 — 2026-03-22: Phase 2 /habits/ page — Keystone Spotlight + Day-of-Week Pattern

### Summary
First Phase 2 content-depth item. `/habits/` page gains two new intelligence sections
powered by new fields added to `handle_habits()` in `site_api_lambda.py`. Both sections
are gracefully hidden when group/DOW data is absent from DynamoDB — no empty states.

### Changes

**lambdas/site_api_lambda.py** — handle_habits() extended
- `day_of_week_avgs`: [Mon–Sun] average Tier 0 completion % over 90 days.
- `best_day` / `worst_day`: index (0=Mon, 6=Sun) of peak and most vulnerable day.
- `group_90d_avgs`: dict of per-group 90-day adherence averages.
- `keystone_group` / `keystone_group_pct`: strongest habit group by 90-day avg.
- All new fields are additive — backwards compatible with existing page JS.

**site/habits/index.html** — two new sections added
- Keystone Spotlight: accent-bordered card showing #1 group name, 90-day %, and
  contextual description. Position: between Tier 0 streak block and Weekly Trend.
- Day of Week Pattern: 7-bar chart (green=best, red=worst) with insight line.
  Position: between Weekly Trend and Streak Records.
- Both sections hidden by default (`display:none`); shown only when API returns data.
- All 9 group descriptions pre-coded in `KEYSTONE_DESCRIPTIONS` map.

### Deploy
- `lambdas/site_api_lambda.py` → deployed to `life-platform-site-api` (us-west-2) manually.
- `site/habits/` synced to S3 + CloudFront invalidated `/habits/*` + `/api/habits`.

---

## v3.8.2 — 2026-03-22: D10 baseline + Phase 1 Task 20 reading path CTAs

### Summary
Completes Phase 0 (D10 — last remaining data fix) and Phase 1 Task 20 (reading path CTAs).
D10: the compare card Day 1 column now pulls from `public_stats.json` baseline object
instead of hardcoded HTML values. Baseline flows: profile → daily_brief Lambda → site_writer
→ public_stats.json. Phase 1 Tasks 13-19 + 21 were already done by Claude Code sessions;
Task 20 (reading path CTAs) is the final Phase 1 item.

### Changes

**lambdas/site_writer.py** — v1.3.0
- Added `baseline: dict = None` parameter to `write_public_stats()`.
- Passes baseline into `public_stats.json` payload as top-level `"baseline"` key.
- Tightened `CacheControl` from 24h to 1h for more responsive updates.
- Version bumped: v1.2.0 → v1.3.0.

**lambdas/daily_brief_lambda.py** — v2.82.2
- Extended `write_public_stats()` call to pass `baseline={}` dict.
- Reads `baseline_date`, `baseline_weight_lbs`, `baseline_hrv_ms`, `baseline_rhr_bpm`,
  `baseline_recovery_pct` from PROFILE#v1; falls back to Feb 22 actuals (302.0 / 45 / 62 / 55%).

**deploy/add_reading_path_ctas.py** — new script
- Injects "Continue the story" reading-path CTAs before `<!-- Mobile bottom nav -->` on
  7 pages: /story/ /live/ /character/ /habits/ /experiments/ /discoveries/ /intelligence/
- Each CTA links to the next logical page in the story loop.
- Idempotent: skips pages that already have reading-path markup.

**deploy/deploy_d10_phase1.sh** — new script
- Orchestrates full deploy: inject CTAs → fix_public_stats --write → Lambda deploy →
  S3 sync → CloudFront invalidation.

### Website Strategy Status
- Phase 0: ✅ COMPLETE (D1–D10 all resolved)
- Phase 1: ✅ COMPLETE (Tasks 13–21 all done)
- Next: Phase 2 — content depth (habits page, character expansion, accountability rethink)

---

## v3.8.1 — 2026-03-22: Phase 0 Data Fixes — D1 weight null, hardcoded platform stats removed

### Summary
Diagnosed and fixed the root cause of `public_stats.json` being frozen since March 16.
Root cause: the sick day Lambda early-return path skipped `write_public_stats`, so every
sick day left the S3 file unchanged. Withings data stops at 2026-03-07 (last weigh-in
before illness). Fixed with a 30-day lookback that correctly surfaces the last known weight.
All hardcoded platform stats removed from both the Lambda and the rebuild script —
everything now sourced from profile, DynamoDB computed_metrics, or auto-discovered from
source files (registry.py, CDK stacks, CHANGELOG).

### Changes

**lambdas/daily_brief_lambda.py** — v2.82.1
- **D1-FIX**: Added `write_public_stats` call to sick day early-return path — website
  no longer goes stale during multi-day illness periods. Uses `gather_daily_data` data
  already in memory (30-day Withings lookback) — zero extra DynamoDB cost.
- **Hardcodes removed**: `mcp_tools`, `data_sources`, `lambdas`, `last_review_grade`
  now pulled from `profile.get("platform_meta", {})` in both sick day and normal paths.
- **Hardcodes removed**: `zone2_target_min` now pulled from profile (`zone2_weekly_target_min`
  or `zone2_target_min_weekly`), with 150 as last-resort fallback only.

**deploy/fix_public_stats.py** — new script
- One-shot script to rebuild and push `public_stats.json` to S3 from live DynamoDB data.
- Zero hardcoded values: weight from Withings (30-day lookback), vitals from Whoop,
  training from `computed_metrics`, platform counts auto-discovered from registry.py +
  CDK stacks + CHANGELOG.md.
- Runs CloudFront invalidation automatically on `--write`.
- Usage: `python3 deploy/fix_public_stats.py` (dry run) / `--write` (push live).

**deploy/deploy_daily_brief_fix.sh** — new script
- Packages and deploys `daily-brief` Lambda with all required layer files.

### Data fixes applied (live on averagejoematt.com)
| Field | Before | After |
|-------|--------|-------|
| `vitals.weight_lbs` | null | 287.7 lbs |
| `journey.current_weight_lbs` | 0.0 | 287.69 lbs |
| `journey.lost_lbs` | 0 | 14.3 lbs |
| `journey.progress_pct` | 0% | 12.2% |
| `journey.weekly_rate_lbs` | 287.69 (broken) | -2.45 lbs/wk |
| `journey.days_in` | missing | 28 |
| `journey.projected_goal_date` | null | 2027-03-07 |
| `training.total_miles_30d` | 0 | 34.6 |
| `training.activity_count_30d` | 0 | 18 |
| `training.zone2_this_week_min` | 42 | 42 (now live) |
| `platform.mcp_tools` | 87 (stale) | 95 (from registry.py) |
| `platform.lambdas` | 42 (stale) | 50 (from CDK stacks) |
| `platform.last_review_grade` | A (stale) | A- (from CHANGELOG) |

### DynamoDB changes
- `USER#matthew / PROFILE#v1`: added `platform_meta` map field
  (`mcp_tools`, `data_sources`, `lambdas`, `last_review_grade`)

### Deploys
- Lambda `daily-brief` (us-west-2): ✅ 2026-03-22
- S3 `site/public_stats.json`: ✅ 2026-03-22 (CloudFront invalidation I35NKA9GH69M27BAVXM1U6L4XH + ID90AC5Z3GENXGHAPXKGQ0UEP)

---

## v3.8.0 — 2026-03-21: Sprint 8 — Mobile Navigation, Content Safety Filter, Grouped Footer

### Summary
Unified Board Summit #3 convened (Technical Board, Personal Board, Web Board — 30+ personas including Jony Ive, Lenny Rachitsky, Julie Zhuo, Andrew Chen, David Perell, Ethan Mollick). Three critical findings: (1) mobile visitors have ZERO navigation (nav__links display:none with no hamburger), (2) site needs three-tier nav architecture (top nav for discovery, bottom nav for engagement, footer for completeness), (3) content filter needed to hide sensitive vices from all public surfaces. All 30 HTML pages patched. Content filter deployed to site-api Lambda.

### Navigation Architecture (30 pages patched)
- **Mobile hamburger menu** — ☰ icon in top-right, opens full-page overlay with grouped sections (The Journey / The Data / The Platform / Follow)
- **Mobile bottom nav** — persistent 60px bar with 5 thumb-zone icons: Home · Ask · Score · Journal · More
- **Updated top nav** (desktop) — Story · Live · Journal · Platform · About · [Subscribe →] (was: Story · Live · Journal · Platform · Character)
- **Grouped footer v2** — 4-column layout (The Journey / The Data / The Platform / Follow) replaces flat 12-link footer
- **nav.js shared component** — handles hamburger toggle, bottom nav active state, overlay open/close, keyboard escape, theme toggle prep

### Content Safety Filter
- **S3 config** — `config/content_filter.json` with blocked vices ("No porn", "No marijuana") and blocked keywords
- **Lambda integration** — `_load_content_filter()` loads from S3 (cached in warm container), `_scrub_blocked_terms()` strips mentions from AI responses, `_is_blocked_vice()` utility for future endpoints
- **System prompt** — `/api/ask` prompt now explicitly instructs Claude to never mention blocked terms
- **Response scrubbing** — both `/api/ask` and `/api/board_ask` responses pass through `_scrub_blocked_terms()` before returning

### Website Versioning Infrastructure
- **`deploy/rollback_site.sh`** — git-tag-based rollback: checkout tag → S3 sync → CloudFront invalidate
- **`site-v3.8.0` tag** — first tagged deploy for instant rollback capability
- **Theme system architecture** designed (Layer 1: git tags for structural, Layer 3: CSS data-theme for visual) — implementation deferred to next session

### Unified Board Summit #3 — Feature Vision
- Full inventory of 87+ MCP tools mapped to proposed website pages
- 12 new page concepts identified with data sources already built (habits, achievements, supplements, benchmarks, glucose, sleep, intelligence, progress, accountability, methodology, journal/archive, genome)
- Gamification vision: SVG avatar evolving with pillar tiers, badge/achievement wall, "since your last visit" indicators
- Commercialization ladder: Free newsletter → Premium ($10/mo) → Course ($99-299) → Community ($29/mo) → Advisory ($500+/hr)
- Full website roadmap written to `docs/WEBSITE_ROADMAP.md` for Claude Code continuation

### Files Created
| File | Purpose |
|------|---------|
| `site/assets/js/nav.js` | Shared navigation JS component |
| `site/assets/css/base.css` (appended) | +5,219 chars: hamburger, bottom nav, overlay, grouped footer CSS |
| `seeds/content_filter.json` | Content safety filter config (uploaded to S3) |
| `deploy/deploy_sprint8_nav.py` | Master nav patching script (30 pages) |
| `deploy/patch_content_filter.py` | Lambda content filter integration script |
| `deploy/rollback_site.sh` | Git-tag-based site rollback script |
| `docs/WEBSITE_ROADMAP.md` | Comprehensive roadmap for Claude Code continuation |
| `handovers/HANDOVER_v3.8.0.md` | Session handover |

### Deploys
- S3 site sync: ✅ (30 pages + nav.js + base.css)
- CloudFront invalidation: ✅ (`I8XRHMEYNI8GYEPZFJZHDVCTQJ`)
- Lambda life-platform-site-api (us-east-1): ✅ (content filter)
- S3 config: ✅ (`config/content_filter.json`)
- Git tag: ✅ (`site-v3.8.0`)

### Key Metrics Update
| Metric | Before | After |
|--------|--------|-------|
| Website pages | 15 | 15 (no new pages, all patched) |
| HTML files patched | 0 | 30 |
| Mobile navigation | None (display:none) | Hamburger + bottom nav + overlay |
| Content filter | None | 3-layer (S3 config + prompt + response scrub) |
| Git tags | None | site-v3.8.0 (first tagged deploy) |

---

## v3.7.84 — 2026-03-20: Sprint 7 World-Class Website — Expert Panel Review + 15 Items Shipped

### Summary
Conducted a 30+ persona expert panel website strategy review (Jony Ive, Peter Attia, Paul Graham, Andrew Chen, David Perell, Lenny Rachitsky, full Technical Board + Personal Board). Key finding: "The site has world-class infrastructure but undersells the story by 10x." Created Sprint 7 (19 items, WR-14 through WR-46) and shipped 15 of 19 items in-session. 4 new pages live. 5 new homepage sections. Multiple /platform/ and /character/ enhancements. Site-api safety filter deployed. CloudFront 404 routing fixed via CDK.

### New Pages Live
- `/protocols/` — 6 protocol cards (sleep, training, nutrition, metabolic, habits, supplements) with data sources and compliance status (WR-39)
- `/platform/reviews/` — Public architecture review #17: 14-member AI board grades, selected findings, grade history (WR-36)
- `/journal/sample/` — Newsletter sample page with browser-frame mock email UI for The Weekly Signal (WR-32)
- `/404.html` — Branded 404 page matching site design language (WR-28)

### Homepage Enhancements
- **WR-38: Discoveries section** — 3 real correlations with r values, p values, and sample sizes (sleep→recovery, bed temp→deep sleep, Zone 2→HRV)
- **WR-33: Day 1 vs Today comparison card** — side-by-side: weight 302→287.7, HRV 45→66 (+47%), RHR 62→52, recovery 55%→89%
- **WR-31: "New here? Start with the story" CTA** — amber banner in hero section
- **WR-30: Real daily brief excerpt** — replaced "coming soon" placeholder with actual AI coaching brief content
- **WR-29: Fixed live data double-path bug** — `/site/public_stats.json` → `/public_stats.json` (CloudFront origin already adds `/site` prefix)
- Sample issue links added to all email CTAs across homepage, platform, character pages

### /platform/ Enhancements
- **WR-34: Animated data flow diagram** — SVG with animated green dots showing 19 Sources → Ingest → Store → Serve → Emails/Website/Ask
- **WR-35: FinOps cost section** — $13/month total, $3 Claude, $10 AWS, 0 engineers grid
- **WR-44: Tool of the Week spotlight** — `get_sleep_environment_analysis` with input/output/finding
- Link to public architecture review from reviews section

### /character/ Enhancements
- **WR-37: Scoring methodology section** — pillar data sources table showing what feeds each of the 7 pillars
- Sample issue link added to email CTA

### Infrastructure
- **WR-28: CloudFront 404/403 fix** — CDK updated: 404→custom 404.html, 403→200/index.html for S3 routing. Deployed via `cdk deploy LifePlatformWeb`.
- **WR-40: /api/ask response safety filter** — 6 blocked regex categories (PII, financial, medical diagnosis, credentials) + system prompt safety guardrails. Deployed to us-east-1.
- `deploy/deploy_sprint7_tier0.sh` — deploy script handling us-east-1 site-api Lambda

### Documentation
- `docs/reviews/WEBSITE_PANEL_REVIEW_2026-03-20.md` — Full 10-section expert panel review document
- `docs/PROJECT_PLAN.md` — Website Strategy Review #2 section added (19 items)
- `docs/SPRINT_PLAN.md` — Sprint 7 added (3 tiers, 19 items, 15 complete)
- `site/sitemap.xml` — 5 new entries (board, journal/sample, subscribe, protocols, platform/reviews)

### Sprint 7 Scorecard
| Tier | Total | Done | Remaining |
|------|-------|------|-----------|
| Tier 0 (Foundations) | 7 | 5 built + 2 Matthew-only | WR-14 (/story/ prose), WR-15 (photos) |
| Tier 1 (Retention) | 8 | 8 | All complete |
| Tier 2 (Growth) | 4 buildable | 1 | WR-43 (heartbeat), WR-45 (media kit), WR-46 (open data) |

### Deploys
- S3 site sync: ✅ (3 syncs this session)
- CloudFront invalidation: ✅ (3 invalidations)
- CDK LifePlatformWeb: ✅ (WR-28 error responses)
- Lambda life-platform-site-api (us-east-1): ✅ (WR-40 safety filter)

### Key Metrics Update
| Metric | Before | After |
|--------|--------|-------|
| Website pages live | 12 | 15 (+protocols, +platform/reviews, +journal/sample) |
| Homepage sections | 4 | 7 (+discoveries, +comparison card, +start-here CTA) |
| Sprint 7 items | 0/19 | 15/19 |
| WR items total | WR-24 | WR-46 |

---

## v3.7.83 — 2026-03-20: Operational Efficiency Roadmap + Claude Code Adoption

### Changes

**docs/PROJECT_PLAN.md** — updated
- Added Operational Efficiency Roadmap section (OE-01 through OE-10), stack-ranked by ROI
- Derived from full conversation history analysis across all Life Platform sessions
- Covers: Claude Code adoption, shell aliases, tool surface management, Project Knowledge, terminal anti-patterns, test discipline, memory strategy, Deep Research, doc consolidation, dev environment

**OE-01: Claude Code installed and verified (v2.1.80)**
- Native binary installed via `curl -fsSL https://claude.ai/install.sh | bash`
- PATH configured in ~/.zshrc
- Authenticated via browser (uses existing Pro subscription)
- First session launched in life-platform directory
- Claude Code cheat sheet PDF created (2-page transition guide: before/after comparisons, essential commands, Chat vs Code decision matrix)

---

## R17 Architecture Review — 2026-03-20

### Summary
Architecture Review #17 conducted (grade A-). 13 findings across security, observability, architecture, compliance, and code hygiene. 6 board decisions made. Sprint 6 (R17 Hardening) created with 18 items across 3 tiers. Grade drops from A to A- because the platform crossed the public-exposure threshold (AI endpoints on the open internet) and defensive controls haven't fully caught up.

Key board decisions: WAF rate-based rules on CloudFront (+$7/mo, replaces in-memory rate limiting as primary layer), move site-api to us-west-2 (60-day, $0), separate Anthropic API key for public endpoints (+$0.40/mo), graceful degradation pattern for AI calls (no new deps), UptimeRobot free tier for external monitoring. Platform cost increases from ~$13 to ~$20.40/month (under $25 budget cap). All decisions approved by Matthew.

Critical pre-DIST-1 items: WAF, privacy policy page, CloudWatch dashboard, PITR drill, separate API key.

### Changes

**docs/reviews/REVIEW_2026-03-20_v17.md** — new
- Full R17 review document (14-member board, 13 findings, 6 board decisions)
- Per-panelist grades: Yael B+ (security gaps on public endpoints), Raj B+ (distribution vs infrastructure ratio), Viktor B+ (attack surface analysis), all others A- to A
- Board deliberation on 6 open decisions with full rationale

**docs/SPRINT_PLAN.md** — updated
- Sprint 6 (R17 Hardening) added: 8 Tier 0 items (pre-DIST-1), 6 Tier 1 (60-day), 4 Tier 2 (90-day)
- Sprint Timeline Summary updated with Sprint 6 and corrected R18 target
- Footer updated with R17 review reference

### Architecture Review #17 Findings Summary
| ID | Severity | Finding |
|----|----------|---------|
| R17-F01 | Critical | Public AI endpoints lack persistent rate limiting |
| R17-F02 | High | In-memory rate limiting resets on cold start |
| R17-F03 | High | No WAF on public-facing CloudFront distributions |
| R17-F04 | Medium | Subscriber email verification has no rate limit |
| R17-F05 | High | Cross-region DynamoDB reads (site-api us-east-1 → DDB us-west-2) |
| R17-F06 | Medium | No observability on public API endpoints |
| R17-F07 | Medium | CORS headers not evidenced on site API |
| R17-F08 | Low | google_calendar still in config.py SOURCES list |
| R17-F09 | Low | MCP Lambda memory discrepancy in documentation |
| R17-F10 | Low | Site API AI calls use hardcoded model strings |
| R17-F11 | Medium | No privacy policy or terms of service on public website |
| R17-F12 | Medium | PITR restore drill still not executed (carried since R13) |
| R17-F13 | Medium | 95 tools creates context window pressure for Claude |

---

## v3.7.81 — 2026-03-19: Standardise nav + footer across all 12 pages

### Summary
Navigation audit revealed 8 of 12 pages were unreachable from the main nav — including /story/ (the distribution gate), /board/, /ask/, /explorer/, /experiments/, /biology/, /about/, and /live/. New consistent nav ships Story · Live · Journal · Platform · Character · Subscribe across all 12 pages. New full footer links all 12 pages. `deploy/update_nav.py` added for future nav maintenance.

### Changes

**deploy/update_nav.py** — new script
- Regex-patches nav + footer blocks across all 12 site pages in one pass
- Per-page active state on nav links, dry-run mode

**All 12 site pages — nav updated**
- Old: The experiment · The platform · Journal · Character (4 items, inconsistent)
- New: Story · Live · Journal · Platform · Character · [Subscribe →] (6 items, consistent)
- /story/ promoted into nav — was completely invisible despite being the distribution gate
- /live/ promoted into nav — was only reachable via homepage dual-CTA

**All 12 site pages — footer updated**
- Old: Story · Journal · Platform · Character · Subscribe
- New: Story · Live · Journal · Platform · Character · Experiments · Explorer · Biology · Ask · Board · About · Subscribe + Privacy
- /board/, /ask/, /explorer/, /experiments/, /biology/ no longer orphaned

### Deploys
- 12 static pages: ✅ S3 synced, CloudFront invalidated `/*`

---

## v3.7.80 — 2026-03-19: WR-24 subscriber gate, S2-T2-2 /board/ page, sprint plan cleanup

### Summary
Three pure dev items shipped: (1) WR-24 — subscriber verification gate on /ask/ (3 anon q/hr → 20/hr for confirmed subscribers via HMAC token + /api/verify_subscriber endpoint); (2) S2-T2-2 — "What Would My Board Say?" lead magnet page at /board/ with 6 AI personas (Attia, Huberman, Patrick, Norton, Clear, Goggins) and /api/board_ask endpoint; (3) Sprint plan cleanup marking S2-T1-9 and S2-T1-10 as done. CDK deployed LifePlatformWeb with 2 new CloudFront behaviors. Full site synced to S3.

### Changes

**lambdas/site_api_lambda.py**
- `_get_token_secret()` — derives HMAC signing secret from existing Anthropic API key (no new secrets)
- `_generate_subscriber_token(email)` — 24hr HMAC token (base64-encoded, `email:expires:sig` format)
- `_validate_subscriber_token(token)` — constant-time compare, expiry check
- `_is_confirmed_subscriber(email)` — DDB lookup: `USER#matthew#SOURCE#subscribers / EMAIL#{sha256}`, `status=="confirmed"`
- `_handle_verify_subscriber(event)` — GET `/api/verify_subscriber?email=...` → 404 if not found, 200 + token if confirmed
- `PERSONA_PROMPTS` — 6 persona system prompts (Attia, Huberman, Patrick, Norton, Clear, Goggins)
- `_handle_board_ask(event)` — POST `/api/board_ask` → per-persona Haiku 4.5 calls, 5/hr IP rate limit
- `ROUTES` dict updated, `lambda_handler` updated, `CORS_HEADERS` updated
- `_ask_rate_check(ip_hash, limit=3)` — parameterised limit (was hardcoded 5)

**site/ask/index.html — WR-24 subscriber gate**
- `MAX_QUESTIONS = 3`, `SUBSCRIBER_LIMIT = 20`, `effectiveLimit()`, `verifySubscriber()`
- Rate-banner replaced with subscriber gate UI
- `X-Subscriber-Token` header forwarded on every `/api/ask` POST

**site/board/index.html — S2-T2-2 new page**
- "What Would My Board Say?" — 6 AI personas, selector grid, skeleton loaders, subscribe CTA

**cdk/stacks/web_stack.py**
- Added `/api/verify_subscriber` and `/api/board_ask` cache behaviors

**docs/SPRINT_PLAN.md**
- S2-T1-9, S2-T1-10 marked ✅ Done; WR-24 + S2-T2-2 added as completed Sprint 5 rows

### Deploys
- `LifePlatformWeb` CDK stack: ✅ 2026-03-19 (130s)
- `site/ask/index.html`, `site/board/index.html`: ✅ S3 synced
- CloudFront: ✅ Invalidated `/*`

---
