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
