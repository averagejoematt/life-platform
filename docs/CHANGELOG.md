## v3.9.41 — 2026-03-27: Pre-Launch Content Review (Product Board Editorial Session)

Full editorial review across Home, Story, and About pages with Product Board content panel (Ava Moreau, Sofia Herrera, Jordan Kim, Margaret Calloway, Elena Voss, Mara Chen). Matthew provided detailed page-by-page feedback; board aligned and added independent catches.

### Home Page
- **Hero tagline**: "For real this time" → "One person. Nineteen data sources. Every week, publicly."
- **Hero narrative**: Broadened beyond weight — frames around being drowning in advice, wanting to listen to yourself, AI as lens for sleep/habits/mental state/relationships/happiness
- **"Why I'm doing this in public"**: Rewritten — focuses on curiosity about AI reading full life picture + disappearing pattern + honesty
- **Ticker**: "FOR REAL THIS TIME" → "THE EXPERIMENT BEGINS"
- **Meta/OG/title tags**: Updated to match broader framing ("The Measured Life — AI Health Experiment")
- **Bug fixes**: Removed duplicate subscribe line, duplicate "See a sample issue" link, duplicate social proof script, duplicate subscribe redirect
- Removed "Senior Director at a SaaS company" from about section

### Story Page
- **Ch 1**: "Three times, actually — maybe four" → "Multiple times"
- **Ch 1**: May 2025 passage leads with 5am gym/diet, not stretching
- **Ch 1**: Slide paragraph rewritten — family, gentleman's agreement, Mondays counting to 100lbs
- **Ch 1**: "Disgust" → "Disappointment" + promise elaboration (covenant, Rolex as covenant, trust question)
- **Ch 2**: De-doxxed biographical details (removed ages, sailing, cities, relationships), added athletics (300lb lifts, 16-mile runs, competitive sports), isolation trigger framing
- **Ch 2**: Pattern paragraph — limbic system/dopamine framing, purpose hypothesis, 5am gym sessions lead
- **Ch 3**: Rewritten as product journey — AI therapy → optimization → data idea → mind spiraling. Removed "Senior Director", "terrifying"
- **Ch 4**: Simplified to forward-looking — 10yr weight logs, stock-ticker pattern, "no data on mind yet"
- **Ch 5**: Cheerleader/mum passage removed. Replaced with disappearing pattern, honesty, accountability
- **Waveform**: Moved from bottom of page to between Ch 1 and Ch 2 for visual impact. Renamed "The Pattern"
- **Meta tags**: Updated OG descriptions

### About Page
- **Mission Brief sidebar**: Replaced weight/location/job blocks with dossier-style visual showing physical targets (weight, run, strength, movement), mental targets (social, mental health, journaling, satisfaction), system targets (character score 80+, no 5-month gaps), and current status
- **"Senior Director"**: Removed from header, meta, bio prose, sidebar throughout
- **Press/media section**: Replaced with warm "If You Want to Connect" section
- **Media kit**: Removed entirely (speaking, bios, talk topics, booking, assets) — 60 lines stripped. Re-add after meaningful traffic
- Dead `copyBio()` function removed

### Bug Fixes (All Pages)
- Removed stray `</div>` after nav mount on story + about pages
- Duplicate dark mode toggle: nav.js was injecting second theme-toggle button alongside the one in components.js — removed nav.js duplicate

### Files Modified
- `site/index.html` — hero, narrative, "why public", meta tags, ticker, 4 duplicate bugs
- `site/story/index.html` — all 5 chapters rewritten, waveform repositioned, meta tags, stray div
- `site/about/index.html` — mission brief sidebar, connect section, media kit removed, meta tags, stray div, dead code
- `site/assets/js/nav.js` — removed duplicate theme toggle (30 lines)
- `deploy/cleanup_mediakit.py` — one-time script for media kit removal

---

## v3.9.40 — 2026-03-27: Nav Spacer Architecture + Catalog Fix + UX Cleanup

Tech Board–approved nav spacer architecture (5-1-1 vote), Product Board–approved hierarchy tab removal (7-0 vote). Fixed challenge catalog format bug that broke all 65 tiles. Swept Arena/Lab naming to Challenges/Experiments everywhere. Centered home page comparison. Fixed dropdown headings. 37-file nav-height sweep.

### Architecture (Tech Board Approved — 5-1-1)
- **Nav spacer pattern**: components.js injects `.nav-spacer` div after nav — single source of truth for fixed-nav clearance
- `.nav-spacer` CSS class in base.css (height: var(--nav-height))
- `deploy/nav_spacer_sweep.sh` — automated 3-pattern sweep across all 37 page files
  - Pattern A: `calc(var(--nav-height) + var(--space-XX))` → `var(--space-XX)` (bulk of files)
  - Pattern B: `margin-top:var(--nav-height)` on tickers → `margin-top:0` (home, achievements, chronicle)
  - Pattern C: `top:var(--nav-height)` on fixed elements → kept intentionally (chronicle reading progress)

### UX (Product Board Approved — 7-0)
- **Hierarchy tab bar removed** from all method pages — breadcrumb + main nav sufficient for wayfinding
- **"Where This Fits" contextual blurb kept** — provides relationship context without competing navigation
- `buildHierarchyNav()` now returns only the blurb, no tab bar

### Fixes
- **Challenge catalog format**: v3.9.39 expansion rewrote JSON as flat list instead of `{categories, challenges}` dict — API crashed, only DynamoDB active records showed. Rebuilt with proper wrapper — all 65 tiles restored
- **S3 path mismatch**: challenge catalog + experiment library uploaded to `config/` but Lambda reads `site/config/` — fixed
- **Name consistency**: "The Arena" → "Challenges" and "The Lab" → "Experiments" in breadcrumbs, `<title>`, `<h1>`, OG tags, pipeline navs
- **Pipeline navs removed** from challenges + discoveries pages (inconsistent — appeared on some pages, not others)
- **Discoveries page**: added missing breadcrumb + hierarchy-nav mount
- **Dropdown headings**: "What I Do" / "What I Tested" now visually distinct (font-weight: 700, color: accent-dim)
- **Home page Day 1 vs Today**: centered grid + heading + CTA (was left-aligned)

### Files Modified
- `site/assets/js/components.js` — nav spacer injection, hierarchy tab bar removal
- `site/assets/css/base.css` — .nav-spacer class, dropdown heading styling
- `site/index.html` — Day 1 vs Today centering
- `site/challenges/index.html` — name cleanup, pipeline nav removed
- `site/experiments/index.html` — name cleanup
- `site/discoveries/index.html` — pipeline nav removed, breadcrumb + hierarchy mount added
- `seeds/challenges_catalog.json` — rebuilt with proper dict format
- 37 page HTML files — nav-height clearance removed (via sweep script)
- `deploy/nav_spacer_sweep.sh` — reusable sweep script

---

## v3.9.39 — 2026-03-27: Pre-Launch Sweep — Nav Fixes, Mobile Scroll, Catalog Expansion

Consolidated all undone items from 10+ sessions into action plan. Fixed nav naming (Arena→Challenges), mobile menu scroll bug, verified subscribe flow, built baseline capture script, expanded challenge catalog 34→66 and experiment library 58→71.

### Fixes
- Nav rename: "The Arena" → "Challenges", "Active Tests" → "Experiments" (components.js, 3 locations)
- Mobile hamburger menu scroll: overlay now scrollable, page behind locked (iOS-safe body position fix)

### Infrastructure
- `deploy/capture_baseline.sh` — Day 1 snapshot script (character, daily data, habits, vices → platform_memory)
- Subscribe flow verified: Lambda → SES → confirmation email ✅
- Warmup script tested (2 endpoints flagged: character_stats 503, subscriber_count 405)

### Content Expansion
- Challenge catalog: 34 → 66 (+32 across all 6 categories)
- Experiment library: 58 → 71 (+13 including sauna, cold plunge, journaling modalities, social protocols, supplement timing)

### Documentation
- `docs/ACTION_PLAN_APRIL_LAUNCH.md` — 23-item consolidated action plan across 4 phases
- Phase B visual prompt package for Recraft/Midjourney

---

## v3.9.38 — 2026-03-26: Visual Asset System — 65 SVGs + 3-Page Integration

Product Board visual strategy session → creative direction document → 65 SVG assets generated → wired into milestones, live, and character pages → deployed to CloudFront.

### Visual Strategy
- Full 8-persona Product Board convened on site visual identity gap
- Defined 5-phase visual execution plan across 6 asset categories
- Decisions: editorial illustration avatar style (NYT), geometric Phase A badges now, rich Phase B roadmapped
- `docs/VISUAL_ASSET_BRIEF.md` — comprehensive creative direction with AI prompt templates for Recraft/Midjourney

### Assets Generated (65 SVGs)
- **26 custom icons** (`site/assets/icons/custom/`) — geometric, 24×24, stroke-only, `currentColor` adaptable
- **39 achievement badges** (`site/assets/img/badges/`) — military insignia meets data terminal aesthetic
- **SVG sprite** for `<use>` reference pattern
- **Generator script** (`deploy/generate_visual_assets.py`) — regenerates entire set from source definitions
- Badge categories: streaks (5), levels (6), weight (8), data (4), experiments (4), challenges (5), vice streaks (4), running (3)

### Site Integration
- **Milestones page**: `BADGE_ICONS` emoji → `badgeSvgPath()` loading SVG files; `CATEGORY_META` emoji → custom icon `<img>` tags
- **Live page**: 60-line `GLYPH_ICONS` inline SVG functions → CSS mask-image system (10 lines); state coloring via `.glyph__ring--{state} .glyph__icn`
- **Character page**: 13 hardcoded badge emoji → SVG `<img>` references

### Files Created
- `docs/VISUAL_ASSET_BRIEF.md`, `docs/VISUAL_DECISIONS.md`
- `deploy/generate_visual_assets.py`, `deploy/deploy_visual_assets.sh`
- `site/assets/icons/custom/*.svg` (26 icons + sprite.svg)
- `site/assets/img/badges/*.svg` (39 badges)

### Files Modified
- `site/achievements/index.html`, `site/live/index.html`, `site/character/index.html`

---

## v3.9.37 — 2026-03-26: Product Board Pre-Launch Punch List (23 items)

All 23 items from the Product Board pre-launch review, preparing for April 1 go-live.

### Must Fix (Launch Blockers)
- **PB-1**: Journal → Chronicle 301 redirects — all `/journal/*` pages now redirect to `/chronicle/*`
- **PB-2**: Fixed stray `</div>` DOM mismatch on homepage
- **PB-3**: Belt-and-suspenders prequel banner hide (checks `AMJ_EXPERIMENT.isLive` AND raw date)
- **PB-4**: Subscribe success redirects to new `/subscribe/confirm/` page
- **PB-5**: AI Brief hardcoded sample replaced with honest fallback
- **PB-7**: `/start/` page redirects to `/`
- Fixed `/journal/` → `/chronicle/` link in subscriber welcome email

### High Impact
- **PB-8**: "Why I'm doing this" About section moved UP on homepage (before data grids)
- **PB-9**: "See a sample issue →" link below hero subscribe input
- **PB-10**: One-liner added to subscribe: "A weekly email. Real data, real failures, no filter."
- **PB-11**: "Day X — Early data" banners on 5 observatory pages (sleep, glucose, nutrition, training, mind)
- **PB-12**: Hero animation delays halved (0.7s → 0.35s max)
- **PB-13**: Lambda warm-up script (`deploy/warmup_lambdas.sh`)
- **PB-14**: Feature card hover: inline JS → CSS `.feature-card:hover`
- **PB-15**: OG meta descriptions updated on 5 key subpages

### Nice to Have
- **PB-16**: Subscriber count social proof (dynamic, hidden if <5)
- **PB-17**: `/subscribe/confirm/` page with 4-panel "while you wait" navigation
- **PB-18**: Vital quadrant grid single-column on mobile (≤480px)
- **PB-19**: Observatory accent colors on homepage feature cards (sleep=purple, glucose=amber, habits=green)
- **PB-20**: Dark/light mode toggle wired into nav (persists via localStorage)
- **PB-21**: Glossary tooltips on ticker metrics (HRV, Recovery, Streak)
- **PB-22**: "Most Interesting Correlations" curated section on Data Explorer
- **PB-23**: Week 04 chronicle entry synced from `/journal/` to `/chronicle/`

### Incident
- S3 `sync --delete` removed `public_stats.json` (Lambda-generated, not in local site/) — **homepage broken for ~5 min**
- Restored via `site-stats-refresh` Lambda invocation
- Deploy script fixed with `--exclude` for all Lambda-generated S3 files
- Hotfix also fixed CSS leak (missing `<style>` tags) and duplicate theme toggle from patch running twice

### Files Created
- `site/subscribe/confirm/index.html`, `deploy/warmup_lambdas.sh`, `deploy/patch_v3.9.37_product_board.py`, `deploy/deploy_v3.9.37.sh`, `deploy/hotfix_v3.9.37.sh`, `site/chronicle/posts/week-04/index.html`

### Files Modified
- `site/index.html` (12 items), `site/assets/js/components.js` (theme toggle), `site/journal/**` (redirects), `site/start/index.html` (redirect), 5 observatory pages (Day X banners), 5 subpages (OG tags), `site/explorer/index.html` (curated section), `lambdas/email_subscriber_lambda.py` (journal→chronicle)

---

## v3.9.36 — 2026-03-26: Signal Doctrine Tier 2 — 5-Section Nav + Observatory Accents + Podcast Scanner

### Summary
Shipped Signal Doctrine Tier 2: complete navigation restructure from 6 sections to 5 (The Story / The Data / The Science / The Build / Follow), Product Board-approved bottom nav routing (8-0 vote: Follow→/subscribe/), observatory pillar accent colors on 5 pages, home page sparklines + count-up animations, story-mode narrative intros on Sleep + Glucose pages, and Podcast Intelligence Phase 2 scanner Lambda.

### Product Board Session
Full 8-persona Product Board convened on two questions:
- **Bottom nav routing**: Unanimous (8-0) — Follow tab routes to `/subscribe/` not `/chronicle/`. Rationale: conversion funnel, one-tap to subscribe form.
- **Nav section names**: Desktop uses articles ("The Story" / "The Data" / "The Science" / "The Build" / "Follow"). Mobile bottom nav drops articles for space ("Story" / "Data" / "Science" / "Build" / "Follow"). Sofia's compromise adopted (6-2, James + Raj abstained).

### What Shipped
- **5-section nav restructure** (`components.js` v3.0.0): The Story (Home, My Story, The Mission) | The Data (My Numbers + The Evidence, grouped dropdown) | The Science (What I Do + What I Tested, grouped dropdown) | The Build (7 items) | Follow (4 items)
- **Bottom nav** (mobile): Story→`/` | Data→`/live/` | Science→`/stack/` | Build→`/platform/` | Follow→`/subscribe/` (mail envelope icon)
- **Footer**: Updated to 5-column layout matching new IA
- **nav.js v2.0.0**: Badge map, reading paths, and active states synced to new 5-section IA
- **Observatory pillar accents**: `--obs-accent` CSS custom property on sleep (purple), glucose (amber), nutrition (amber), training (green), mind (violet) pages
- **Home sparklines**: 7-day SVG mini-sparklines on vital quadrant cards (Body weight, Recovery HRV)
- **Count-up animations**: Wired `data-count-up` on dynamically-populated stat values
- **Sleep narrative intro**: Story-mode serif paragraph above signal dashboard ("The thing I thought I was good at.")
- **Glucose narrative intro**: Story-mode serif paragraph above signal dashboard ("The number that quieted the anxiety.")
- **Podcast scanner Lambda**: Weekly YouTube RSS scanner → Claude Haiku extraction → DynamoDB candidates for review. Config at `config/podcast_watchlist.json` (7 podcasts: Huberman, Attia, Patrick, Norton, Wolf, Chatterjee, Hill)

### Deploy Scripts Created
| Script | Purpose |
|--------|---------|
| `deploy/fix_follow_route.py` | Bottom nav Follow → /subscribe/ + mail icon |
| `deploy/fix_follow_badge.py` | nav.js BADGE_MAP key sync |
| `deploy/patch_tier2_observatory.py` | --obs-accent pillar colors on 5 observatory pages |
| `deploy/patch_tier2_home.py` | Sparkline containers + count-up wiring on home page |
| `deploy/patch_tier2_narrative.py` | Story-mode narrative intros on sleep + glucose |
| `deploy/deploy_v3.9.36.sh` | Master deploy orchestrator (8 steps) |

### Files Modified
| File | Change |
|------|--------|
| `site/assets/js/components.js` | Complete rewrite — 5-section IA, grouped dropdowns, /subscribe/ bottom nav |
| `site/assets/js/nav.js` | Reading paths, badge map, active states synced to 5-section IA |
| `site/sleep/index.html` | --obs-accent + narrative intro |
| `site/glucose/index.html` | --obs-accent + narrative intro |
| `site/nutrition/index.html` | --obs-accent |
| `site/training/index.html` | --obs-accent |
| `site/mind/index.html` | --obs-accent |
| `site/index.html` | Sparkline containers + count-up wiring |

### Files Created
| File | Purpose |
|------|---------|
| `lambdas/podcast_scanner_lambda.py` | Weekly podcast scanner (YouTube RSS → Haiku extraction → DDB) |

### Manual Follow-up
1. Create podcast scanner Lambda in AWS (command in deploy script output)
2. Add EventBridge weekly schedule rule
3. Version bump in `deploy/sync_doc_metadata.py` (v3.9.35 → v3.9.36) + run `--apply`

---

## v3.9.35 — 2026-03-26: Signal Doctrine Tier 1 Rollout + Arena Voting + Experiments

### Summary
Rolled out Signal Doctrine design language to all 11 remaining data pages (body-signal typography, breadcrumbs, reading-path-v2 navigation, animations.js). Added 7-segment pillar ring chart to Character page. Deployed lifecycle gaps (overdue detection, catalog_id, challenge badges). Added 6 new experiments from Product Board brainstorm. Created podcast intelligence pipeline config. Challenge voting + follow infrastructure confirmed deployed.

### What Shipped
- **Design Brief Tier 1 rollout**: `body-signal` class, breadcrumbs, reading-path-v2, animations.js applied to: sleep, glucose, supplements, habits, benchmarks, protocols, platform, intelligence, challenges, experiments, explorer (11 pages)
- **Character pillar ring chart**: 7-segment SVG ring in pillar colors with animated fill on load, replacing the static composite score number
- **Lifecycle gaps deployed**: overdue detection in `list_challenges`, `catalog_id` param in `create_challenge`, 5 new challenge achievement badges (Arena Debut/Regular/Veteran/Legend/Flawless)
- **6 new experiments**: sauna-2x-week, cold-plunge-3x, zone2-150min, morning-sunlight-blue-blockers, TRF-12pm-8pm, eliminate-alcohol-30d
- **Podcast intelligence config**: `config/podcast_watchlist.json` with 7 podcasts (Huberman, Attia, Patrick, Norton, Wolf, Chatterjee, Hill) + extraction prompt for future automated scanner
- **Challenge voting confirmed**: Backend (`/api/challenge_vote`, `/api/challenge_follow`) + frontend vote buttons already in production from v3.9.33

### Deploy Scripts Created
| Script | Purpose |
|--------|---------|
| `deploy/apply_design_brief.py` | Apply body-signal + breadcrumbs + reading paths + animations.js to 11 pages |
| `deploy/patch_character_ring.py` | Add 7-segment pillar ring chart to character page |
| `deploy/add_experiments.py` | Append 6 new experiments to library |
| `deploy/deploy_v3.9.35.sh` | Master deploy orchestrator (all steps in order) |
| `deploy/bump_version.py` | Version bump in sync_doc_metadata.py |

### Files Modified
| File | Change |
|------|--------|
| `site/{sleep,glucose,supplements,habits,benchmarks,protocols,platform,intelligence,challenges,experiments,explorer}/index.html` | body-signal + breadcrumb + reading-path-v2 + animations.js |
| `site/character/index.html` | 7-segment pillar ring chart (CSS + JS + mount point) |
| `config/experiment_library.json` | +6 experiments (58 total) |
| `config/podcast_watchlist.json` | NEW — 7 podcasts for future scanner |
| `deploy/sync_doc_metadata.py` | Version bump v3.9.34 → v3.9.35 |

---

## v3.9.34 — 2026-03-26: Signal Doctrine — Design Brief Implementation

### Summary
Product Board (8 personas + external consultants) delivered comprehensive design brief for April 1st launch. "Signal Doctrine" visual identity: two-mode typography (signal/story), coral CTA accent, pillar color system, warm light mode, noise texture, card hover lifts, reading paths, and staggered reveals. Foundation CSS shipped site-wide; page-level changes applied to 8 pages. Inter font self-hosted.

### What Shipped
- **tokens.css overhaul**: Coral CTA ramp (`--c-coral-*`), 7 pillar color tokens (`--pillar-movement` through `--pillar-discipline`), body typography tokens (`--text-body-signal`, `--text-body-story`), warm light mode palette (`#fafaf8` bg, `#008f5f` accent), surface brightness bump, light mode pillar variants
- **base.css: 15 new component blocks (DB-07→DB-21)**: `.body-signal`/`.body-story` classes, `.btn--cta` coral button, `.pull-quote`, `.breadcrumb`, card hover lift (`.vital:hover`), `.reveal-grid` staggered animations, `.divider-dots`/`.divider-fade`, dark mode text glow on vital values, noise texture overlay via SVG, light mode card shadows, `.reading-time`, `.sparkline` styles, pillar border/dot utilities, `.reading-path-v2` prev/next nav
- **Inter font**: Self-hosted 400/500/600 weights via `deploy/download_inter_fonts.sh`
- **noise.svg**: Tileable SVG noise texture at `/assets/images/noise.svg`
- **animations.js**: Shared scroll reveal observer, number count-up, signal bar fill, back-to-top — vanilla JS, respects `prefers-reduced-motion`
- **Homepage**: Coral subscribe CTA (`btn--cta`), reading path (Subscribe ↔ Story)
- **Story page**: `body-story` class (Lora 17px serif), reading path (Home ↔ About)
- **About page**: `body-story` class, reading path (Story ↔ Live)
- **Chronicle page**: `body-story` class, animations.js
- **Live page**: Reading path (About ↔ Character), animations.js
- **Character page**: Reading path (Live ↔ Habits), animations.js
- **Discoveries page**: Reading path (Experiments ↔ Sleep), animations.js
- **Subscribe page**: Coral CTA button (`btn--cta`)

### Design Brief
Full brief at `docs/briefs/BRIEF_2026-03-26_design_brief.md` — 8 parts: diagnosis, direction, site-wide proposals (typography, color, dark/light mode, motion, visual elements), nav restructure, page-specific upgrades (3 priority tiers), CSS implementation checklist, board member statements, priority matrix.

### Files Modified
| File | Change |
|------|--------|
| `site/assets/css/tokens.css` | Complete rewrite — coral, pillars, warm light mode, body tokens |
| `site/assets/css/base.css` | Inter @font-face + 15 DB component blocks appended |
| `site/assets/images/noise.svg` | NEW — tileable SVG noise texture |
| `site/assets/js/animations.js` | NEW — shared animation utilities |
| `site/assets/fonts/inter-{400,500,600}.woff2` | NEW — self-hosted Inter font |
| `site/index.html` | Coral CTA, reading path, animations.js |
| `site/story/index.html` | body-story, reading path, animations.js |
| `site/about/index.html` | body-story, reading path, animations.js |
| `site/chronicle/index.html` | body-story, animations.js |
| `site/live/index.html` | Reading path, animations.js |
| `site/character/index.html` | Reading path, animations.js |
| `site/discoveries/index.html` | Reading path, animations.js |
| `site/subscribe/index.html` | Coral CTA button |
| `deploy/download_inter_fonts.sh` | NEW — font download + S3 upload script |
| `deploy/sync_doc_metadata.py` | Version bump v3.9.33 → v3.9.34 |
| `docs/briefs/BRIEF_2026-03-26_design_brief.md` | NEW — full Product Board design brief |

---

## v3.9.33 — 2026-03-26: Arena v2 + Lab v2 — Challenge & Experiment Page Overhaul

### Summary
Product Board convened (8 personas) to review /challenges/ and /experiments/ pages. Both redesigned from verbose document layouts to immersive visual tile walls. 35 challenges seeded across 6 categories. Three lifecycle gaps identified and coded: overdue detection, catalog→DDB bridge (catalog_id), and achievements integration (5 new challenge badges). Implementation brief written for next session: challenge voting ("I'd try this"), podcast intelligence pipeline, and 6 new experiments.

### What Shipped (Deployed)
- `/challenges/` Arena v2 — icon-forward tile grid, category filter bar, detail overlay with evidence + board quotes, collapsed methodology, active hero with check-in dots
- `/experiments/` Lab v2 — compact tile grid with evidence rings, vote buttons, category tabs, compact mission control, collapsed H/P/D, detail overlay
- `challenges_catalog.json` — 35 challenges (Movement 7, Sleep 3, Nutrition 5, Mind 7, Social 7, Discipline 5) with icons, evidence tiers, board recommenders, protocols. Config-driven from S3.
- `/api/challenge_catalog` endpoint — new handler + route in site_api_lambda.py
- `experiment_library.json` copied to `site/config/` (Lambda reads from `site/config/` but file was only at `config/`)

### What's Coded (Awaiting Deploy)
- `mcp/tools_challenges.py` — `catalog_id` field on create_challenge; overdue detection in list_challenges (days_since_activation, overdue bool, days_overdue); summary includes overdue count
- `mcp/registry.py` — `catalog_id` added to create_challenge schema
- `lambdas/site_api_lambda.py` — handle_achievements() queries challenges partition, counts completed + perfect challenges, 5 new badges (Arena Debut/Regular/Veteran/Legend/Flawless)
- `site/achievements/index.html` — challenge category (amber), badge icons, CSS color

### Product Board Decisions
- Challenge voting framed as "I'd try this" (pledge, not vote) with email capture — reuses experiment vote/follow infrastructure
- Podcast intelligence pipeline Phase 1 = conversational (tell Claude what you heard, it creates the entry). Phase 2 = automated weekly scanner Lambda (~$0.40/month)
- Evidence tier comes from cited research, not the podcast — podcast is discovery mechanism, not evidence source

### Files Created
- `seeds/challenges_catalog.json` — 35-challenge catalog
- `deploy/deploy_challenges_overhaul.sh` — Arena v2 deploy script
- `deploy/deploy_experiments_v2.sh` — Lab v2 deploy script
- `deploy/deploy_lifecycle_gaps.sh` — 3 gap fixes deploy script
- `docs/briefs/BRIEF_2026-03-26_arena_lab_v2.md` — Full implementation brief for remaining work

### Files Modified
- `site/challenges/index.html` — Complete rewrite (Arena v2)
- `site/experiments/index.html` — Complete rewrite (Lab v2)
- `lambdas/site_api_lambda.py` — challenge_catalog handler/route + achievements challenge badges
- `mcp/tools_challenges.py` — catalog_id + overdue detection
- `mcp/registry.py` — catalog_id schema
- `site/achievements/index.html` — Challenge category + icons

### Next Session (from Implementation Brief)
1. Deploy lifecycle gaps: `python3 -m pytest tests/test_mcp_registry.py -v && bash deploy/deploy_lifecycle_gaps.sh`
2. Challenge voting frontend + backend (Task 1 in brief)
3. Podcast schema extension + detail overlay rendering (Task 2a in brief)
4. Seed 6 new experiments from brainstorm (Task 3 in brief)

---

## v3.9.32 — 2026-03-26: Sessions 3+4 — Chronicle/Subscribe + About/Builders/Throughline

### Summary
Completed Sessions 3 and 4 of the WR4 implementation plan (23 of 25 tasks). All pre-launch blockers cleared. Last remaining blocker (/chronicle/sample/) shipped. Elena Voss bio page created. Subscribe funnel unified to "The Weekly Signal." About page softened. Builders page extended with GitHub rationale. Throughline connectors added across 5 pages. Experiments and discoveries get honest empty states.

### What Shipped

**Session 3 — Chronicle + Subscribe Funnel (tasks 3.1–3.10)**
- 🔴 FINAL BLOCKER CLEARED: `/chronicle/sample/` page — email preview mock with data grid, chronicle excerpt, board commentary, and "what you get" breakdown
- Chronicle numbering explainer added below series intro cards
- Elena Voss bio page created (`site/elena/index.html`) — editorial prose, 3 rules, technical details
- Chronicle "About the reporter" link → `/elena/` (was `/about/`)
- Subscribe naming unified to "The Weekly Signal" (title, eyebrow, button)
- Subscribe page updated with sample link + "Week 1 ships after April 1"
- Contextual CTA messaging: 5 variants by page context in `components.js`
- Sticky subscribe bar toned down: 60-second delay before showing
- Per-article OG meta tags verified (already existed on all 4 articles)

**Session 4 — About + Builders + Experiments + Throughline (tasks 4.1–4.15)**
- About page press/speaking softened: "I'd love to talk about this" + "First interviews welcome" + honest framing
- "Why not Apple Health?" callout added to about page
- Builders page: GitHub rationale section ("Why the Repo Is Private") with alternative links
- Experiments: "Experiments begin on Day 1" empty state
- Discoveries: "Discoveries populate over time" empty state with 4-6 week signal timeline
- Homepage about section: Story link added before Chronicle
- Chronicle → Data throughline: Explorer + Pulse links
- Live/Pulse → Story throughline: callout bar
- Platform → Chronicle throughline: callout bar
- Deferred to post-launch: 4.6 ("How I built this" walkthrough), 4.15 (data page journey callouts)

### Files Created
- `site/elena/index.html` — Elena Voss bio/byline page
- `site/chronicle/sample/index.html` — Newsletter sample issue page

### Files Modified
- `site/chronicle/index.html` — Numbering explainer, reporter link, data throughline
- `site/subscribe/index.html` — Title, eyebrow, button, sample link
- `site/index.html` — Sticky bar 60s delay, about section story link
- `site/assets/js/components.js` — Contextual CTA messaging
- `site/about/index.html` — Press tone, Apple Health callout
- `site/builders/index.html` — GitHub rationale section
- `site/experiments/index.html` — Empty state
- `site/discoveries/index.html` — Empty state
- `site/platform/index.html` — Chronicle throughline
- `site/live/index.html` — Story throughline

---

## v3.9.31 — 2026-03-26: Website Review #4 + Story Page + Homepage Overhaul

### Summary
Product Board conducted comprehensive pre-launch website audit (Review #4) with 5 simulated audience personas and 8-member board synthesis. Identified 47 implementation tasks across 5 sessions. Completed Sessions 1 and 2 — story page content and homepage integrity fixes.

### What Shipped

**Session 0 — Quick fixes (earlier in session)**
- Footer logo AMJ → AJM (`components.js`)
- Story page placeholder blocks hidden via CSS
- Chronicle: removed "Silence in the Data" + "First Contact" from `posts.json`
- All 4 seed experiments abandoned (Tongkat Ali, NMN, Creatine, Berberine) — cleaned DynamoDB

**Session 1 — Story Page (tasks 1.1–1.10)**
- All 5 chapters implemented from `STORY_DRAFTS_v1.md` into `site/story/index.html`
- Chapter 1: "The Moment" (302 lbs, the cycle, DoorDash spiral, "why does it keep coming back?")
- Chapter 2: "The Problem With Previous Attempts" (pattern diagnosis, coping mechanism insight)
- Chapter 3: "The Build" (first Lambda, Claude partnership, professional angle)
- Chapter 4: "What the Data Has Shown" (supplements→sleep, CGM→anxiety, platform didn't prevent relapse)
- Chapter 5: "Why Public" (losing cheerleader, accountability, building toward 185)
- Pull quote updated to real words from interview
- Editorial typography: 18px font, 1.9 line-height, chapter dividers, throughline callout component
- Throughline links: Ch3→/platform/, Ch4→/explorer/, Ch5→/chronicle/, story-nav→/live/
- Journey timeline moved below story body for uninterrupted reading
- About page: "production code" wording fixed (task 4.1)

**Session 2 — Homepage (tasks 2.1–2.9)**
- 🔴 BLOCKER RESOLVED: Fake discovery cards removed (fabricated r-values, p-values)
- Replaced with 3 narrative insight cards from real interview observations (supplements→sleep, CGM→anxiety, platform→relapse)
- Dynamic correlation loader preserved — will auto-replace with real FDR data when available
- Hero simplified: removed stat chips, heartbeat canvas, "Start here" box (~11 elements → ~6)
- Dual-path CTAs updated: "Read My Story" is now primary left-side CTA (was "Prequel Chronicles")
- "Day 1 vs Today" empty states fixed: shows "Apr 1" / "data starts Day 1" instead of dashes/loading

### Files Created
- `docs/reviews/REVIEW_2026-03-26_website_v4.md` — Full review with 5 personas, 8 board members, page rankings
- `docs/reviews/IMPLEMENTATION_PLAN_WR4.md` — 47-task implementation plan across 5 sessions

### Files Modified
- `site/story/index.html` — Complete rewrite (5 chapters, editorial CSS, throughline links)
- `site/index.html` — Discovery cards, hero simplification, empty states
- `site/about/index.html` — "production code" wording
- `site/assets/js/components.js` — Footer AMJ→AJM
- `site/journal/posts.json` — Removed 2 articles

### Pre-Launch Blockers Remaining (from WR4)
- ~~Story page content~~ ✅ DONE
- ~~Fake discovery cards~~ ✅ DONE
- ~~About page wording~~ ✅ DONE
- Chronicle sample page (`/chronicle/sample/`) — Session 3
- Homepage hero further simplification (ticker) — Session 2 stretch

### Next Session (Session 3: Chronicle + Subscribe Funnel)
See `docs/reviews/IMPLEMENTATION_PLAN_WR4.md` tasks 3.1–3.10:
- Chronicle numbering explainer
- Elena Voss bio page (`site/elena/index.html`)
- /chronicle/sample/ page (pre-launch blocker)
- Subscribe CTA messaging unification
- Sticky subscribe bar timing adjustment

---

## v3.9.30.1 — 2026-03-26: Story Page Content Audit + Interview Drafts

### Summary
Product Board + Throughline Editorial content audit across all site pages. Identified placeholder content, ghost-written text needing validation, and narrative gaps. Conducted full 20-question interview with Matthew covering all 5 story page chapters. Drafted all chapters, confirmed homepage quote, flagged homepage corrections.

### Content Created
- `docs/content/ELENA_PREQUEL_BRIEF.md` — Raw interview brief for Elena Voss prequel article with privacy guardrails
- `docs/content/STORY_INTERVIEW_FULL.md` — Full interview transcript organized by chapter (20 questions)
- `docs/content/STORY_DRAFTS_v1.md` — All 5 story page chapters drafted in Matthew's voice

### Key Decisions
- **Homepage quote confirmed**: "I used to be the protagonist of my own life. Somewhere along the way, I became a spectator." — replacing placeholder
- **Homepage hero narrative**: "Got sick" framing replaced with honest DoorDash spiral narrative
- **Discovery cards**: All 3 homepage discovery cards confirmed as placeholders — need real data or honest treatment
- **About page**: "Never shipped production code" needs rewording to "never written and deployed production application code"
- **Rolex detail**: Approved for public site (story page Chapter 1)
- **Chapter 4 approach**: Board-recommended 3-part structure (sleep signal, CGM anxiety relief, platform didn't prevent relapse)

### Pending
- Matthew to redline all 5 chapter drafts
- Implement approved prose into site HTML files
- Replace homepage quote, hero narrative, discovery cards
- Fix about page wording
- Elena prequel article (using saved brief)

---

## v3.9.30 — 2026-03-26: Build Section Overhaul + /builders/ Page

### Summary
Joint Product Board + Technical Board review of all 6 Build section pages. Implemented board recommendations across every page, plus created a new `/builders/` page targeting the technical/HN audience.

### New Page: `/builders/`
- Created `site/builders/index.html` — "For Builders" page
- 5 sections: The Stack (8-row reference table), Key Decisions (8 ADR cards), Lessons Learned (8 real incidents with gotcha warnings), Build Timeline (5-week progression), Getting Started (build-first vs skip-until-later split)
- Stats strip: 52 Lambdas, 103 tools, 19 sources, 33 ADRs, $13/mo, A- grade
- Minimum viable platform spec: 3 Lambdas + 1 DDB + 1 EventBridge + 1 SES = $2–4/month, one weekend
- Added to Build dropdown nav + footer in `components.js`

### `/cost/` Improvements
- Added "DIY with ChatGPT + spreadsheets" comparison row (Free, ~10 hrs/week manual)
- Added cost-per-insight callout: $0.43/daily brief, $0.13/data source/month, 0 idle cost

### `/board/` UX Overhaul
- Pre-loaded demo response on page load (sleep vs exercise question, all 6 personas)
- Per-persona accent colors on response cards (Vasquez=blue, Okafor=purple, Patrick=green, Norton=amber, Clear=teal, Goggins=red)
- Free question limit increased 3 → 5
- Added `renderPersonaCard()` shared function for consistent styling

### `/platform/` Cleanup
- Removed 80-line hub grid (duplicated nav/footer), replaced with clean 3×2 "Explore the Build" CTA grid

### `/methodology/` Enhancements
- Moved signature quote to hero area
- Added "Methodology in Action" 4-step case study: raw signal → hypothesis → observation → action
- Removed duplicate quote from bottom

### `/intelligence/` Addition
- New "Sample Daily Brief" section between pipeline diagram and feature grid
- Shows redacted real email: 3 priorities, coaching insight, vitals strip

### `/tools/` Expansion (3 → 6 calculators)
- Sleep Efficiency Scorer: time-in-bed vs actual sleep, clinical grading (Excellent/Good/Fair/Poor)
- Deficit Sustainability Calculator: deficit %, risk level, timeline with metabolic adaptation buffer, protein minimums
- VO2max Estimator: Rockport walk test formula, age-group ACSM percentiles, Attia centenarian targets
- Updated page description to reflect 6 tools

### Files Created
- `site/builders/index.html` — New page

### Files Modified
- `site/cost/index.html` — DIY row + cost-per-insight
- `site/board/index.html` — Demo response, persona colors, limit bump
- `site/platform/index.html` — Hub grid → CTA grid
- `site/methodology/index.html` — Hero quote, case study
- `site/intelligence/index.html` — Sample Daily Brief
- `site/tools/index.html` — 3 new calculators
- `site/assets/js/components.js` — /builders/ in nav + footer
- `deploy/sync_doc_metadata.py` — Version bump v3.9.29 → v3.9.30

---

## v3.9.29 — 2026-03-26: Phase D + E — Challenge XP Wiring, Auto-Verification, Nav Update

### Summary
Three items: wired challenge completion XP into character sheet compute pipeline, added metric auto-verification for challenges, and added /challenges/ (The Arena) to site navigation.

### Nav Update
- Added `/challenges/` as "The Arena" to `site/assets/js/components.js`:
  - SECTIONS → Method → "What I Tested" dropdown group
  - Footer → Method column
  - HIER_ITEMS hierarchy nav bar
  - HIER_CONTEXT blurb for /challenges/ path

### Phase D — Challenge XP → Character Sheet
- `lambdas/character_sheet_lambda.py` v1.2.0:
  - After `compute_character_sheet()`, queries `SOURCE#challenges` for challenges completed yesterday
  - Maps challenge domain → pillar (e.g., movement→movement, mental→mind, discipline→consistency)
  - Adds bonus XP to pillar `xp_total` in the character record
  - Sets `xp_consumed_at` on challenge record to prevent double-counting
  - Adds `challenge_bonus_xp` dict to character record for transparency
  - Surfaces `challenge_bonus_xp` per-pillar in `write_character_stats` site output
  - Fully non-fatal: wrapped in try/except, character sheet still writes even if challenge query fails

### Phase E — Metric Auto-Verification
- `mcp/tools_challenges.py`:
  - Added `AUTO_METRIC_MAP` — 8 supported metrics: daily_steps, weight_lbs, eating_window_hours, zone2_minutes, sleep_hours, hrv, calories, protein_g
  - Added `_check_metric_targets()` function — queries DDB source partitions, compares against min/max/exact targets
  - Wired into `checkin_challenge`: for `metric_auto` mode, metric result overrides manual input; for `hybrid` mode, auto-check runs but manual flag respected
  - Auto-verification results stored in each checkin's `auto_verification` field
  - Results returned in checkin response for full transparency
- Science scan source already wired in `challenge_generator_lambda.py` prompt — lights up automatically when health data flows

### Files Modified
- `site/assets/js/components.js` — Nav, footer, hierarchy nav, hierarchy context
- `lambdas/character_sheet_lambda.py` — Phase D challenge XP wiring (v1.2.0)
- `mcp/tools_challenges.py` — Phase E auto-verification engine + checkin integration
- `deploy/sync_doc_metadata.py` — Version bump v3.9.28 → v3.9.29

---

## v3.9.28 — 2026-03-26: Challenge System — Full Stack Build

### Summary
Built the complete Challenge system across 3 phases. Joint Product Board + Technical Board session established the split: Experiments ("The Lab") = science with hypotheses; Challenges ("The Arena") = action with gamification. Five generation sources: journal mining, data signals, hypothesis graduates, science scans, manual/community.

### Phase A — Data Foundation
- Added `CHALLENGES_PK` to `mcp/config.py`
- Created `mcp/tools_challenges.py` with 5 MCP tools: `create_challenge`, `activate_challenge`, `checkin_challenge`, `list_challenges`, `complete_challenge`
- Registered all 5 tools in `mcp/registry.py` (103 tools total, 7/7 tests passed)
- Updated `site_api_lambda.py`: `/api/challenges` now reads from DynamoDB (S3 fallback), new `/api/challenge_checkin` POST endpoint
- DynamoDB schema: `pk=USER#matthew#SOURCE#challenges`, `sk=CHALLENGE#<slug>_<date>`
- XP system: base XP by difficulty (easy=25, moderate=50, hard=100) × success rate, 1.5× bonus for perfect completion
- Badge system: milestone badges at 1, 5, 10, 25 completions + perfect completion badges

### Phase B — AI Generation Pipeline
- Created `lambdas/challenge_generator_lambda.py` — weekly AI pipeline
- Gathers 14d context: enriched journal entries, character sheet pillars, habit scores (missed T0, vice streaks), confirmed hypotheses, health snapshot (HRV, recovery, weight)
- Calls Claude Sonnet with structured prompt → 0-5 challenge candidates with dedup
- Added to `ci/lambda_map.json` (not_deployed: true, needs CDK)
- Estimated cost: ~$0.05/week

### Phase C — The Arena Page
- Created `site/challenges/index.html` — full page with amber accent theme
- Active Challenge Hero: countdown ring, check-in calendar strip, daily check-in buttons
- Candidates Grid: source badges showing what triggered each challenge
- Completed Record: XP earned, success rates, badge unlocks
- Pipeline nav: Protocols → Experiments → Challenges → Discoveries
- Updated `site/experiments/index.html`: removed Zone 2.5, replaced with single-line CTA to /challenges/

### Board Session
- Product Board (8 personas) unanimous: split experiments and challenges into separate pages
- Technical Board designed DynamoDB schema, generation pipeline, and verification methods
- Documented 5-source challenge generation architecture
- Established visual language: Lab=green/clinical, Arena=amber/energetic

---

## v3.9.27 — 2026-03-26: Nutrition Bug Fix + Global Countdown.js

### Summary
Fixed positional args bug in `get_nutrition` MCP tool (3 broken `query_source_range` calls replaced with correct `query_source` signature). Cleaned up unused `query_source_range` imports from tools_nutrition.py. Added dynamic countdown.js loader to components.js so all ~50+ pages automatically get the Day N badge and experiment counter — no per-page HTML edits needed.

### Fixed
- `tools_nutrition.py` — 3 call sites passing positional args to `query_source_range(table, pk, start, end)` replaced with `query_source(source, start, end)`. Affected: `tool_get_nutrition_summary`, `tool_get_macro_targets` (×2 for macrofactor + withings)
- Removed unused `query_source_range` import from `tools_nutrition.py`

### Changed
- `site/assets/js/components.js` — Added dynamic script loader for countdown.js at end of IIFE. Guard: checks `window.AMJ_EXPERIMENT` to skip if page already includes countdown.js explicitly. All pages using shared components now get Day N badge automatically.

### Deploy Notes
- MCP Lambda redeploy needed (nutrition fix)
- S3 site sync + CloudFront invalidation (components.js change)

---

## v3.9.26 — 2026-03-25: April 1 Launch Reframe — Prequel Chronicles, Baseline Snapshot

### Summary
Product Board emergency session unanimously endorsed reframing all pre-April data as the "testing window" with April 1, 2026 as Day 1 of the public experiment. Chronicle archive relabeled with prequel numbering (Week −5 through Week −1). New "The Interview" chronicle written — Elena Voss's first direct conversation with Matthew covering the relapse, the gap, and what Day 1 means. Global countdown/Day N component added to homepage and archive. Baseline snapshot MCP tool built for April 1 Day 1 capture.

### Added
- `site/assets/js/countdown.js` — Global Day N / T-minus counter component. Before April 1: "T-{N}" nav badge + countdown. After April 1: "DAY {N}" badge. Exposes `window.AMJ_EXPERIMENT` global.
- `site/journal/posts/week-minus-1/index.html` — "The Interview" (Prequel Week −1). Elena's first direct Q&A with Matthew. Covers relapse, testing window reframe, April 1 commitment.
- `capture_baseline` MCP tool (tools_memory.py) — Captures 8-domain snapshot (weight, BP, HRV/recovery, Character Sheet, habits, vices, glucose, nutrition) into platform_memory. Safe by default (won't overwrite without `force=true`).
- `baseline_snapshot` added to platform_memory VALID_CATEGORIES
- `.experiment-counter`, `.nav-day-badge` styles in base.css

### Changed
- `site/index.html` — Hero rewritten with countdown, "Day 1. For real this time." headline, prequel banner (auto-hides after April 1), subscribe label "Follow from Day 1"
- `site/chronicle/archive/index.html` — All episodes relabeled as Prequel series (Prologue, Week −5 through −1). Phase divider added. April 1 Week 1 teaser replaces "coming soon" placeholder.
- `site/chronicle/posts.json` + `site/journal/posts.json` — Rewritten with prequel framing, negative week numbers, `phase: "prequel"` field
- `site/assets/js/site_constants.js` — Added `experiment_start: '2026-04-01'`, phase → 'Launch', hero copy/tagline/cta rewritten for April 1
- Meta tags updated on homepage for April 1 launch messaging
- `countdown.js` loaded on homepage + chronicle archive

### Deploy Notes
- MCP Lambda redeployed (full mcp/ package) for capture_baseline tool
- CloudFront invalidation `/*`
- Day 1 action: run `capture_baseline` MCP tool with no args on April 1 morning

---

## v3.9.25 — 2026-03-25: Sleep + Glucose Observatory Visual Redesign (5/5 Consistency)

### Summary
Sleep and Glucose observatory pages rebuilt from scratch using the v3.9.24 board-voted hybrid design pattern. All 5 observatories now share the same visual language: 2-column hero with gauge rings, pull-quotes with watermark numbers and N=1 badges, 3-column editorial data sections, left-accent rule cards, mid-page cross-links, 2-column narrative with protocol items, and 3-column methodology.

### Domain Color Map (complete)
| Observatory | Accent | Hex |
|-------------|--------|-----|
| Nutrition | Amber | `#f59e0b` |
| Training | Red | `#ef4444` |
| Inner Life | Violet | `#818cf8` |
| Sleep | Blue | `#60a5fa` |
| Glucose | Teal | `#2dd4bf` |

### Sleep Observatory
- Hero gauges: Avg Duration, Sleep Score (30d), Deep %, Recovery
- 3-column editorial: Deep / REM / HRV breakdown with accent bars
- Temperature discovery card (conditional on `optimal_temp_f` from API)
- Pull-quotes: Bed temp 68°F sweet spot, Screen-off +12% HRV, Alcohol −18pts
- 4 rule cards: Screen-off, Temperature, Alcohol, Bed time consistency
- Cross-links: Training (recovery) + Character (sleep pillar)
- API: `/api/sleep_detail` (unchanged)

### Glucose Observatory
- Hero gauges: TIR %, Avg Glucose, Variability SD, Optimal %
- 3-column editorial: Optimal (70–120) / In-Range (70–180) / Elevated (>140)
- Meal response table: 5 foods from protein shake (+6) to pizza (+55)
- Pull-quotes: Protein shake spike, Post-meal walk −15–25mg/dL, Fiber variability
- 4 rule cards: Protein-first ordering, Post-meal walk, Fiber >30g, Sleep→glucose
- Cross-links: Nutrition (MacroFactor × CGM) + Character (metabolic pillar)
- API: `/api/glucose` (unchanged)

### Files Modified
- `site/sleep/index.html` — Complete rewrite to v3.9.24 design pattern
- `site/glucose/index.html` — Complete rewrite to v3.9.24 design pattern
- `deploy/sync_doc_metadata.py` — Version bump v3.9.19 → v3.9.25

### Deploy Log
- S3: 2 files synced (sleep, glucose index.html)
- CloudFront: Invalidation I2JSIE9H2IROP4EO5JB2BN7N1A (`/sleep/*`, `/glucose/*`)
- No Lambda changes

---

## v3.9.24 — 2026-03-26: Observatory Visual Redesign — 3 pages rebuilt (Board-voted hybrid)

### Summary
Product Board convened for visual design overhaul of the 3 observatory pages built in v3.9.23 (Nutrition, Training, Inner Life). Three visual concepts mocked up in Visualizer (A: The Plate, B: The Editorial, C: The Infographic). Full 8-persona vote produced a B-dominant hybrid direction: B's 2-column editorial hero + C's gauge row (5-3 vote), B's 3-column macro editorial (5-2-1), B's pull-quotes with N=1 evidence badges (8-0 unanimous), C's bordered rule cards with left accent (6-2), pull-quotes established as cross-observatory reusable pattern (8-0 unanimous). All 3 pages rebuilt from scratch and deployed.

### Design System Pattern Established
- **Hero**: 2-column editorial layout (eyebrow with dash accent, display title, subtitle) + 4 mini gauge rings (animated SVG arcs with staggered delays)
- **Pull-quotes**: Staggered throughout page (2-3 per page), oversized watermark numbers (01/02/03), `N=1 · Correlational` / `N=1 · CGM-confirmed` / `N=1 · Observational` evidence badges per Lena Johansson's amendment
- **Section headers**: Monospace uppercase with trailing dash line (`::after` pseudo-element)
- **Data sections**: 3-column editorial spread with thin accent bars, display-type numbers
- **Rule cards**: Left accent border (page color), monospace `Rule 01` header with trailing fade line
- **Cross-links**: Mid-page contextual cards (not just footer), inline links woven through narrative
- **Color coding**: Nutrition=amber (#f59e0b), Training=red (#ef4444), Inner Life=violet (#a78bfa)

### Product Board Vote Results
| Decision | Winner | Vote |
|----------|--------|------|
| Hero section | C's gauge row in B's 2-col layout | 5-3 |
| Macro/data breakdown | B's 3-column editorial | 5-2-1 |
| N=1 findings | B's pull-quotes + evidence badges | 8-0 |
| Rules section | C's bordered cards + left accent | 6-2 |
| Cross-observatory pattern | Pull-quotes as signature | 8-0 |

### Files Modified
- `site/nutrition/index.html` — Complete rewrite: 2-col hero + gauge row, 3 pull-quotes, editorial macro spread, protein adherence card, bordered rule cards, mid-page cross-links
- `site/training/index.html` — Complete rewrite: 2-col hero + gauge row (Z2/workouts/strain/strength), 3 pull-quotes, 3-col Z2 detail, activity chips, bordered rule cards, cross-links to nutrition + sleep
- `site/mind/index.html` — Complete rewrite: 2-col hero + gauge row (mind pillar/resist rate/journal/vices), 3 pull-quotes, vice streak grid with left accent, connection + willpower bars, mood chart, honest gap section

### Deploy Log
- S3: 3 files synced (nutrition, training, mind index.html)
- CloudFront: 3 invalidations (nutrition/*, training/*, mind/*)

### Next Steps
1. Check live pages and iterate on any visual issues
2. Consider applying same pattern to Sleep + Glucose observatories for full consistency
3. SIMP-1 Phase 2 + ADR-025 cleanup still targeted ~April 13
4. DISC-7 annotation testing/seeding still pending

---

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
