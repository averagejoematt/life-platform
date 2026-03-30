# Life Platform — Pre-Compiled Review Bundle
**Generated:** 2026-03-29
**Purpose:** Single-file input for architecture reviews. Contains all platform state needed for a Technical Board assessment.
**Usage:** Start a new session and say: "Read this review bundle file, then conduct Architecture Review #N using the Technical Board of Directors."

---

## 1. PLATFORM STATE SNAPSHOT

### Latest Handover

# Latest Handover Pointer
→ See [HANDOVER_v4.4.0.md](HANDOVER_v4.4.0.md)


---

## 2. RECENT CHANGELOG

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

... [TRUNCATED — 172 lines omitted, 572 total]


---

## 3. ARCHITECTURE

# Life Platform — Architecture

Last updated: 2026-03-29 (v4.4.0 — 116 MCP tools, 25-module MCP package, 26 data sources, 59+ Lambdas, 67 site pages, 60+ API endpoints, 7 CDK stacks)

---

## Overview

The life platform is a personal health intelligence system built on AWS. It ingests data from twenty-five sources (twelve scheduled + one webhook + three manual/periodic + two MCP-managed + one State of Mind via webhook), normalises everything into a single DynamoDB table, and surfaces it to Claude through a Lambda-backed MCP server. The design philosophy is: get data in automatically, store it cheaply, and make it queryable without a data engineering background.

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
│  MCP Server Lambda (95 tools, 768 MB) + Lambda Function URL │
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
│  averagejoematt.com (66 pages) · CloudFront → S3 /site      │
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
| CloudWatch | Alarms + logs | **~49 metric alarms**, all Lambdas monitored |
| CDK | Infrastructure as Code | `cdk/` — 8 stacks deployed. CDK owns all 49 Lambda IAM roles + ~50 EventBridge rules. |
| CloudTrail | Audit logging | `life-platform-trail` → S3 |
| AWS Budget | Cost guardrail | $20/mo cap, alerts at 25%/50%/100% |

---

## Ingest Layer

### Scheduled ingestion (EventBridge → Lambda)

Each source has its own dedicated Lambda and IAM role. EventBridge triggers fire daily. All cron expressions use fixed UTC.

**Gap-aware backfill (v2.46.0):** All 6 API-based ingestion Lambdas implement self-healing gap detection. On each run, the Lambda queries DynamoDB for the last N days, identifies missing DATE# records, and fetches only those from the upstream API.

| Source | Lambda | Cron (UTC) | PT (PDT) |
|---|---|---|---|
| Whoop | `whoop-data-ingestion` | `cron(0 14 * * ? *)` | 07:00 AM |
| Garmin | `garmin-data-ingestion` | `cron(0 14 * * ? *)` | 07:00 AM |
| Notion Journal | `notion-journal-ingestion` | `cron(0 14 * * ? *)` | 07:00 AM |
| Withings | `withings-data-ingestion` | `cron(15 14 * * ? *)` | 07:15 AM |
| Habitify | `habitify-data-ingestion` | `cron(15 14 * * ? *)` | 07:15 AM |
| Strava | `strava-data-ingestion` | `cron(30 14 * * ? *)` | 07:30 AM |
| Journal Enrichment | `journal-enrichment` | `cron(30 14 * * ? *)` | 07:30 AM |
| Todoist | `todoist-data-ingestion` | `cron(45 14 * * ? *)` | 07:45 AM |
| Eight Sleep | `eightsleep-data-ingestion` | `cron(0 15 * * ? *)` | 08:00 AM |
| Activity Enrichment | `activity-enrichment` | `cron(30 15 * * ? *)` | 08:30 AM |
| MacroFactor | `macrofactor-data-ingestion` | `cron(0 16 * * ? *)` | 09:00 AM |
| Weather | `weather-data-ingestion` | `cron(45 13 * * ? *)` | 06:45 AM |
| Dropbox Poll | `dropbox-poll` | `rate(30 minutes)` | every 30m |

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

DLQ coverage: all async Lambdas → `life-platform-ingestion-dlq`. CloudWatch: **~49 alarms** total. Alarm actions → SNS `life-platform-alerts`.

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

**Lambda:** `life-platform-mcp` | **Tools:** 95 | **Memory:** 768 MB | **Modules:** 31
**Remote MCP:** `https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws`
**Auth:** `x-api-key` header check + OAuth 2.1/HMAC Bearer for remote MCP

31-module package — see local project structure below.

Cold start: ~700–800ms. Warm: 23–30ms. Cached tools: <100ms.

### IC Intelligence Features (16 of 31 live)

Compute → store → read pattern. Standalone Lambdas run before Daily Brief, store results to DynamoDB.

**Live:** IC-1 (anomaly), IC-2 (training load), IC-3 (nutrition), IC-6 (CGM correlation), IC-7 (cross-pillar), IC-8 (intent vs execution), IC-15 (insights persistence), IC-16 (progressive context), IC-17 (readiness synthesis), IC-18 (hypothesis engine), IC-19 (N=1 experiments + slow drift + sustained anomaly), IC-23 (Character Sheet), IC-24 (adaptive mode), IC-25 (decisions), IC-29 (metabolic adaptation / deficit sustainability — TDEE divergence tracking, deployed v3.7.67), IC-30 (autonomic balance score — HRV + RHR + RR + sleep quality → 4-quadrant nervous system state, deployed v3.7.67).

**Data-gated next:** IC-4 (failure patterns, ~Apr 18), IC-5 (momentum warning, ~Apr 18), IC-26 (temporal mining, ~May), IC-27 (multi-resolution handoff, ~May).

### Site API Lambda (us-west-2)

**Lambda:** `life-platform-site-api` | **Stack:** LifePlatformOperational | **Region:** us-west-2 (R17-09 migration)
**Function URL:** `https://lxhjl2qvq2ystwp47464uhs2jti0hpdcq.lambda-url.us-east-1.on.aws/`
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
| CloudWatch (49 alarms + logs) | ~$2.00 |
| Anthropic API (Haiku + Sonnet) | ~$4.00 |
| **Total** | **~$13** |

---

## Local Project Structure

```
~/Documents/Claude/life-platform/
  mcp_server.py                   ← MCP Lambda entry point
  mcp_bridge.py                   ← Local MCP adapter (Claude Desktop → Lambda HTTPS)
  mcp/                            ← MCP server package (32 modules)
    handler.py, config.py, utils.py, core.py, helpers.py, warmer.py
    labs_helpers.py, strength_helpers.py, registry.py
    tools_sleep, tools_health, tools_training, tools_nutrition, tools_habits
    tools_cgm, tools_labs, tools_journal, tools_lifestyle, tools_social
    tools_strength, tools_correlation, tools_character, tools_board
    tools_decisions, tools_adaptive, tools_hypotheses, tools_memory
    tools_data, tools_todoist

  lambdas/
    # 13 ingestion Lambdas (whoop, withings, strava, garmin, habitify,
    #   eightsleep, macrofactor, notion, todoist, weather, apple_health,
    #   health_auto_export, dropbox_poll)
    # 2 enrichment (enrichment_lambda, journal_enrichment)
    # 7 email/digest (daily_brief, weekly_digest_v2, monthly_digest,
    #   nutrition_review, wednesday_chronicle, weekly_plate, monday_compass)

... [TRUNCATED — 27 lines omitted, 327 total]


---

## 4. INFRASTRUCTURE REFERENCE

# Life Platform — Infrastructure Reference

> Quick-reference for all URLs, IDs, and configuration. No secrets stored here.
> Last updated: 2026-03-28 (v4.2.1 — 52 Lambdas, 9 active secrets, 105 MCP tools, ~49 alarms)
> Note: `webhook-key` scheduled for deletion 2026-03-15 (7-day recovery window). Count reflects post-deletion state.

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
| Tools | 105 across 32 modules |
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
| Key prefixes | `raw/` (source data) · `dashboard/` (web dashboard) · `blog/` (Chronicle) · `buddy/` (accountability page) · `config/` (profile, board, character sheet) · `inbound-email/` (insight parser) · `avatar/` (pixel art sprites) |

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
| CloudWatch alarms | ~49 metric alarms (ALARM-only; base + invocation-count + DDB item size + canary + new Lambda alarms) |

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

## Secrets Manager (9 active secrets)

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
| `google-calendar` | Google Calendar Lambda | OAuth2 refresh_token + client credentials. CMK-encrypted. Auto-refreshed by Lambda. Added v3.7.22. |
| ~~`webhook-key`~~ | ~~Reserved~~ | ~~**SCHEDULED FOR DELETION 2026-03-15** (recovery window 7 days). No Lambda ever read this secret (LastAccessed: None). Saves ~$0.40/mo.~~ |
| ~~`api-keys`~~ | ~~Legacy bundle~~ | ~~**PERMANENTLY DELETED 2026-03-14.** All Lambdas migrated to per-service secrets.~~ |

---

## Lambdas (45)

43 CDK-managed (us-west-2) + 2 Lambda@Edge (us-east-1)

### Ingestion (14)
`whoop-data-ingestion` · `eightsleep-data-ingestion` · `garmin-data-ingestion` · `strava-data-ingestion` · `withings-data-ingestion` · `habitify-data-ingestion` · `macrofactor-data-ingestion` · `notion-journal-ingestion` · `todoist-data-ingestion` · `weather-data-ingestion` · `health-auto-export-webhook` · `journal-enrichment` · `activity-enrichment` · `google-calendar-ingestion`

### Email / Digest (9)
`daily-brief` · `weekly-digest` · `monthly-digest` · `nutrition-review` · `wednesday-chronicle` · `weekly-plate` · `monday-compass` · `anomaly-detector` · `evening-nudge`

### Compute (6)
`character-sheet-compute` · `adaptive-mode-compute` · `daily-metrics-compute` · `daily-insight-compute` · `hypothesis-engine` · `weekly-correlation-compute`

> **Skeleton Lambdas (source written, NOT yet CDK-wired or EventBridge-scheduled — activate ~2026-05-01):**
> `failure-pattern-compute` (IC-4, `lambdas/failure_pattern_compute_lambda.py`) · `momentum-warning-compute` (IC-5, `lambdas/momentum_warning_compute_lambda.py`)

### Infrastructure (14)
`life-platform-freshness-checker` · `dropbox-poll` · `insight-email-parser` · `life-platform-key-rotator` · `dashboard-refresh` · `life-platform-data-export` · `life-platform-qa-smoke` · `life-platform-mcp` · `life-platform-mcp-warmer` · `dlq-consumer` · `life-platform-canary` · `data-reconciliation` · `pip-audit` · `brittany-weekly-email`

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
> Last updated: 2026-03-28 (v4.2.1)

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

**Monitored sources (10):** Whoop, Withings, Strava, Todoist, Apple Health, Eight Sleep, MacroFactor, Garmin, Habitify, Google Calendar.

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

---

... [TRUNCATED — 11 lines omitted, 111 total]


---

## 7. INCIDENT LOG

# Life Platform — Incident Log

Last updated: 2026-03-16 (v3.7.57)

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
4. **Wrong component investigated** (two Apple Health Lambdas, alarm dimension mismatch) — 3 incidents
5. **Missing infrastructure** (EventBridge rule never created, IAM missing permission, CDK stack missing layer reference) — 3 incidents
6. **Data quality / scoring logic** (zero-score defaults, dedup, sign errors) — 4 incidents
7. **One-off deploy scripts bypassing canonical tooling** — 2 incidents (Mar 11 Brittany email inline zip, **Mar 16 S3 bucket wipe**)

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

> **This document is frozen at v3.7.68 (2026-03-17).** The platform is now at v4.3.0+.
> For IC changes after v3.7.68 — including signal doctrine, challenge system modifiers,
> food delivery integration, and reader engagement signals — see CHANGELOG.md.
> A full refresh is planned for ~May 2026.

# Life Platform — Intelligence Layer

> Documents the Intelligence Compounding (IC) features: how the platform learns, remembers, and improves over time.
> For the IC roadmap and future phases, see PROJECT_PLAN.md (Tier 7).
> Last updated: 2026-03-17 (v3.7.68)

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

... [TRUNCATED — 401 lines omitted, 551 total]


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


... [TRUNCATED — 1149 lines omitted, 1229 total]

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
        run: |
          echo "::group::CDK diff"
          node --version
          npm install -g aws-cdk --quiet

          cd cdk
          python3 -m venv .venv
          source .venv/bin/activate
          pip install -r requirements.txt --quiet

... [TRUNCATED — 664 lines omitted, 964 total]

```


### Test suite — all test files with function names

**test_business_logic.py** (0 tests): 


**test_cdk_handler_consistency.py** (5 tests): test_h1_handler_and_source_always_paired, test_h2_all_source_files_exist, test_h3_handler_module_matches_source_file, test_h4_all_source_files_define_lambda_handler, test_h5_no_generic_lambda_function_handler


**test_cdk_s3_paths.py** (4 tests): test_s1_all_s3_prefixes_are_convention_or_documented, test_s2_exception_evidence_in_lambda_source, test_s3_exceptions_dont_use_convention_prefix, test_s4_no_hardcoded_matthew_in_iam_comments


**test_ddb_patterns.py** (4 tests): test_d1_pk_sk_format, test_d2_date_reserved_word_guarded, test_d3_schema_version_present, test_d4_put_item_guarded_by_validator


**test_function_url_origin_header_validation.py** (0 tests): 


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

### lambdas/ (75 .py files, 1 other files)

**Python files:** acwr_compute_lambda.py, adaptive_mode_lambda.py, ai_calls.py, ai_output_validator.py, anomaly_detector_lambda.py, apple_health_lambda.py, board_loader.py, brittany_email_lambda.py, canary_lambda.py, challenge_generator_lambda.py, character_engine.py, character_sheet_lambda.py, chronicle_approve_lambda.py, chronicle_email_sender_lambda.py, circadian_compliance_lambda.py, daily_brief_lambda.py, daily_insight_compute_lambda.py, daily_metrics_compute_lambda.py, dashboard_refresh_lambda.py, data_export_lambda.py, data_reconciliation_lambda.py, digest_utils.py, dlq_consumer_lambda.py, dropbox_poll_lambda.py, eightsleep_lambda.py, email_subscriber_lambda.py, enrichment_lambda.py, evening_nudge_lambda.py, failure_pattern_compute_lambda.py, food_delivery_lambda.py, freshness_checker_lambda.py, garmin_lambda.py, google_calendar_lambda.py, habitify_lambda.py, health_auto_export_lambda.py, html_builder.py, hypothesis_engine_lambda.py, ingestion_framework.py, ingestion_validator.py, insight_email_parser_lambda.py, insight_writer.py, item_size_guard.py, journal_enrichment_lambda.py, key_rotator_lambda.py, macrofactor_lambda.py, measurements_ingestion_lambda.py, momentum_warning_compute_lambda.py, monday_compass_lambda.py, monthly_digest_lambda.py, notion_lambda.py, nutrition_review_lambda.py, og_image_lambda.py, output_writers.py, pip_audit_lambda.py, pipeline_health_check_lambda.py, platform_logger.py, podcast_scanner_lambda.py, qa_smoke_lambda.py, retry_utils.py, scoring_engine.py, sick_day_checker.py, site_api_lambda.py, site_stats_refresh_lambda.py, site_writer.py, sleep_reconciler_lambda.py, strava_lambda.py, subscriber_onboarding_lambda.py, todoist_lambda.py, weather_handler.py, wednesday_chronicle_lambda.py, weekly_correlation_compute_lambda.py, weekly_digest_lambda.py, weekly_plate_lambda.py, whoop_lambda.py, withings_lambda.py


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


... [TRUNCATED — 1962 lines omitted, 2042 total]

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


**Last review source file: `REVIEW_2026-03-28_v18.md`**


### Last Review Findings (read this before flagging ANY new finding)

# Life Platform — Architecture Review #18

**Date:** 2026-03-28 | **Version:** v4.3.0 | **Reviewer:** Technical Board of Directors (full 14-member panel)
**Prior grade baseline:** Review #17 (v3.7.82, 2026-03-20) — grade A-
**Delta:** v3.7.82 → v4.3.0 — 58+ releases across 8 days of intensive pre-launch building
**Artifacts reviewed:** ARCHITECTURE.md, INFRASTRUCTURE.md, PROJECT_PLAN.md, DECISIONS.md, INTELLIGENCE_LAYER.md, SCHEMA.md, SLOs.md, INCIDENT_LOG.md, CHANGELOG.md (v3.7.82→v4.3.0), lambda_map.json, ci-cd.yml, site/ directory listing, handover-2026-03-28-implementation.md, R17 review, past conversation history (WAF deploy, offsite sessions)

---

## Executive Summary

Review #18 covers the most intensive building period in the platform's history — 58+ releases in 8 days that transformed the platform from a 12-page website with basic API endpoints into a 47+ page editorial product with reader engagement systems, new data sources, dynamic OG images, observatory pages across 5 health domains, a labs/bloodwork page, weekly recaps, a living pulse feed, food delivery behavioural tracking, and a Discord community strategy ready for April 1 launch.

**Overall assessment: B+**

The grade drops from A- to B+ — not because the engineering got worse (it didn't; the code quality and architectural patterns remain strong), but because the platform's *surface area* has expanded dramatically while the *governance, documentation, and operational controls* have not kept pace. The platform has outgrown its documentation. ARCHITECTURE.md says "12 pages" when there are 47+. It says "95 MCP tools" in one section and "110" in the header. INFRASTRUCTURE.md says "52 Lambdas" while ARCHITECTURE.md says "61." The INTELLIGENCE_LAYER.md hasn't been updated since v3.7.68. New Lambdas were created via CLI, not CDK. The lambda_map.json is missing entries. MCP tools grew from 95 to 110 when the plan was to shrink to 80.

This is the predictable consequence of a sprint-to-launch: speed was correctly prioritised over documentation and operational hygiene. But the gap is now large enough that it represents real risk — an operator who reads the docs will have a materially wrong understanding of what's running. That's the dividing line between A- and B+.

**Defining story of this delta:** A solo developer, three days before public launch, shipped a reader engagement system with progress bars, freshness indicators, sparklines, a living pulse feed, dynamic OG images, a food delivery behavioural data integration, a labs observatory, and a weekly recap page — all while maintaining architectural coherence, cost discipline (~$13/month + $6 WAF), and zero data-loss incidents. This is genuinely impressive execution. The B+ reflects what was *deferred* to ship, not what was *shipped*.

---

## Board Grades by Panelist

| Panelist | Domain | R17 | R18 | Δ | Key Comment |
|----------|--------|-----|-----|---|-------------|
| **Priya Nakamura** | Architecture | A- | B+ | ↓ | "The three-layer design holds. But 6+ Lambdas created via CLI, not CDK. The lambda_map is stale. The 47-page site with manual S3 sync and no build step is approaching its operational ceiling." |
| **Marcus Webb** | AWS | A- | B+ | ↓ | "WAF deployed — good. But og-image-generator and food-delivery Lambda both created via CLI with manual IAM policies. CDK drift is accumulating. The 8 CDK stacks don't cover all 50+ Lambdas." |
| **Yael Cohen** | Security+IAM | B+ | A- | ↑ | "WAF on CloudFront is the single biggest security improvement since R1. Separate site-api AI key deployed. Privacy page exists. Public:false challenge filtering is correct. The cold-start rate-limit gap is now a secondary concern behind WAF." |
| **Jin Park** | SRE | A- | B | ↓ | "The operational surface tripled. 47 pages, 8+ new API endpoints, 2+ new Lambdas, OG image generation cron — but no new alarms for any of them. The og-image-generator has no CloudWatch alarm. Food delivery Lambda has no freshness check. The monitoring didn't scale with the system." |
| **Elena Reyes** | Code Quality | A | A- | ↓ | "The code itself remains well-structured. ADR-034 (content consistency) is architecturally sound. But the sprint produced documentation debt that would block any new engineer: 3 different Lambda counts, 3 different tool counts, an intelligence layer doc from 2 weeks ago. The CHANGELOG is excellent — that's where the truth lives now." |
| **Omar Khalil** | Data | A | A | = | "Food delivery integration is clean — 1,598 records, proper PK/SK pattern, privacy guardrails (no dollar amounts public). Protocols migration from S3 to DynamoDB is correct. No data quality regressions." |
| **Anika Patel** | AI/LLM | A | A | = | "No AI regressions. Content safety filter on /api/ask deployed. Medical disclaimers maintained. The OG image system uses Pillow (no AI) — correct engineering choice." |
| **Henning Brandt** | Statistics | A | A | = | "No statistical regressions. The signal doctrine (v3.9.34–36) adds evidence badges and N=1 caveats across observatory pages. Statistical rigour remains strong." |
| **Sarah Chen** | Product | A- | A | ↑ | "The product has arrived. 47 pages of editorial health content, reader engagement, progress tracking, weekly recaps. The Discord strategy is smart. April 1 launch timing is correct. The product gap from R17 is closing." |
| **Raj Srinivasan** | Startup/CTO | B+ | B+ | = | "The ratio has improved — there's now a real product with real distribution strategy. But the operational debt from the sprint needs to be addressed in the first week post-launch, not the first month." |
| **Viktor Sorokin** | Adversarial | B+ | B+ | = | "WAF closes the biggest attack vector. But 8 new API endpoints (/api/labs, /api/changes-since, /api/observatory_week, etc.) added with no endpoint-specific rate rules. The WAF global rate limit (1000/5min) is generous for an abuse scenario." |
| **Dana Torres** | FinOps | A | A | = | "~$19/month including WAF ($6) is still remarkable. The OG image Lambda runs once daily — negligible cost. Food delivery Lambda is S3-triggered — near-zero invocations. No cost concerns." |
| **Ava Moreau** | UX | A- | A | ↑ | "The design system is cohesive across 47 pages. Observatory pages have a consistent editorial pattern. Reader engagement (freshness indicators, progress bars, sparklines) is well-executed. Dark/light mode works." |
| **Jordan Kim** | Growth | B+ | A- | ↑ | "Reader engagement infrastructure is now genuinely strong. Freshness indicators, progress bars, weekly recaps, subscribe CTAs, Discord strategy — the growth engine is built and ready to fire on April 1." |

**Composite Grade: B+** (weighted: Architecture, Security, SRE, and Code Quality carry 60% weight; these moved down enough to pull the composite despite Product and Growth improving)

---

## Dimension Grades (10 dimensions)

| # | Dimension | R17 | R18 | Δ | Primary Evidence |
|---|-----------|-----|-----|---|-----------------|
| 1 | Architecture | A- | B+ | ↓ | CLI-created Lambdas outside CDK, stale lambda_map, 47-page manual deploy |
| 2 | Security | B+ | A- | ↑ | WAF deployed, separate AI key, privacy page, challenge filtering |
| 3 | Reliability | A- | B+ | ↓ | New resources without alarms, no freshness check for food delivery |
| 4 | Observability | A- | B | ↓ | 8+ new API endpoints with no dashboards, og-image Lambda unmonitored |
| 5 | Cost | A | A | = | ~$19/month including WAF, excellent for scope |
| 6 | Code Quality | A | A- | ↓ | Documentation drift: 3 Lambda counts, 3 tool counts, stale INTELLIGENCE_LAYER |
| 7 | Data Quality | A | A | = | Food delivery clean, protocols migrated, no regressions |
| 8 | AI Rigour | A | A | = | Content filter deployed, disclaimers maintained, signal doctrine |
| 9 | Operability | B+ | B | ↓ | Docs materially wrong about system state, new operator would be misled |
| 10 | Product Readiness | B+ | A- | ↑ | 47-page product, reader engagement, Discord strategy, April 1 launch |

---

## R17 Finding Disposition

| R17 ID | Finding | R18 Status | Evidence |
|--------|---------|------------|----------|
| R17-F01 | Public AI endpoints lack persistent rate limiting | **RESOLVED** | WAF WebACL `life-platform-amj-waf` deployed with SubscribeRateLimit (60/5min) and GlobalRateLimit (1000/5min). Verified via `setup_waf.sh` run in conversation history. |
| R17-F02 | In-memory rate limiting resets on cold start | **RESOLVED** | WAF at CloudFront edge provides persistent rate limiting independent of Lambda lifecycle. In-memory remains as secondary defence. |
| R17-F03 | No WAF on public-facing CloudFront distributions | **RESOLVED** | WAF WebACL attached to `E3S424OXQZ8NBE` (averagejoematt.com). Verified. |
| R17-F04 | Subscriber email verification has no rate limit | **RESOLVED** | WAF SubscribeRateLimit rule covers `/api/subscribe*` at 60/5min per IP. |
| R17-F05 | Cross-region DynamoDB reads (us-east-1 → us-west-2) | **PERSISTING** | Site-api still in us-east-1. Was tagged as 60-day item. Now higher urgency with 8+ new API endpoints making cross-region reads. |
| R17-F06 | No observability on public API endpoints | **PARTIALLY RESOLVED** | `AskEndpointErrors` CloudWatch alarm added (v4.3.0). But no full dashboard, no latency percentiles, no per-endpoint metrics for the 8+ new routes. |
| R17-F07 | CORS headers not evidenced | **PERSISTING** | No evidence of CORS configuration. Low priority for same-origin site. |
| R17-F08 | google_calendar in config.py SOURCES | **UNKNOWN** | Not verified in this review — requires source code check. |
| R17-F09 | MCP Lambda memory discrepancy in docs | **WORSENED** | ARCHITECTURE.md serve layer says "95 tools" while header says "110 tools." INFRASTRUCTURE.md says "105 tools." Three different numbers in two documents. |
| R17-F10 | Site API hardcoded model strings | **UNKNOWN** | Not verified — requires source code check. |
| R17-F11 | No privacy policy on public website | **RESOLVED** | `/privacy/` directory exists in site/. |
| R17-F12 | PITR restore drill not executed | **PERSISTING** | Carried forward since R13. Still no evidence of drill execution. |
| R17-F13 | 95 MCP tools — context window pressure | **WORSENED** | Tools grew from 95 to 110. SIMP-1 Phase 2 (target ≤80) not executed. Moving in the wrong direction. |
| R14-F02 | INTELLIGENCE_LAYER.md staleness | **PERSISTING** | Header shows v3.7.68. Current platform is v4.3.0. Over 50 versions behind. |

**Summary:** 4 RESOLVED, 2 PARTIALLY RESOLVED, 2 WORSENED, 3 PERSISTING, 3 UNKNOWN

---

## New Findings

### R18-F01: Severe Documentation Drift — Multiple Conflicting Counts
**Severity:** High | **Category:** Operability / Maintainability | **Type:** NEW
**Observed:**
- Lambda count: ARCHITECTURE.md header says "61 Lambdas," INFRASTRUCTURE.md says "52 Lambdas," lambda_map.json has 50 entries (46 deployed). Actual count unknown without AWS CLI audit.
- MCP tools: ARCHITECTURE.md header says "110 tools," serve layer section says "95 tools," INFRASTRUCTURE.md says "105 tools." Three different numbers.
- Website pages: ARCHITECTURE.md says "12 pages," site/ directory contains 47+ subdirectories.
- CDK stacks: ARCHITECTURE.md header says "7 CDK stacks," body says "8 stacks deployed."
- Data sources: ARCHITECTURE.md says "nineteen sources" in overview, header says "26 data sources." Body lists fewer.
**Why it matters:** An operator reading the docs would have a fundamentally wrong mental model of what's running. This is the single biggest operability risk — not because the system is broken, but because the map no longer matches the territory.
**Recommended:** Authoritative `aws lambda list-functions` + `grep` audit, reconcile all docs to single source of truth, add CI lint that checks header counts against lambda_map.json.
**Effort:** M | **Confidence:** High

### R18-F02: CLI-Created Lambdas Outside CDK Management
**Severity:** High | **Category:** Architecture / IaC Drift | **Type:** NEW
**Observed:** At least 3 Lambdas created via AWS CLI in the v4.3.0 session and not managed by CDK:
- `food-delivery-ingestion` — S3-triggered CSV ingestion (from handover)
- `og-image-generator` — EventBridge cron for OG PNG generation (changelog says "Add OG image Lambda to CDK operational stack" but this was in the same session, unclear if fully wired)
- `challenge-generator` — in lambda_map but CDK stack membership unverified
**Why it matters:** CLI-created Lambdas don't get CDK's IAM role management, EventBridge rule management, alarm creation, or layer attachment. They drift silently. The Mar 12 Todoist incident (CDK drift) and the Mar 11 Brittany email incident (stale layer) were both caused by this pattern.
**Recommended:** Run `npx cdk diff` to identify all Lambdas not in CDK stacks. Adopt into appropriate stacks within 2 weeks.
**Effort:** M | **Confidence:** High

### R18-F03: lambda_map.json Missing New Entries
**Severity:** Medium | **Category:** CI/CD Integrity | **Type:** NEW
**Observed:** lambda_map.json `_updated` field shows "2026-03-22 v3.8.7" — 6 days and 20+ versions stale. Missing at minimum: `og-image-generator`, `email-subscriber`. May be missing other recently created Lambdas. The CI/CD pipeline uses lambda_map.json for change detection — Lambdas not in this file are invisible to the pipeline.
**Why it matters:** Code changes to unmapped Lambda source files will not trigger CI/CD deployment. The pipeline thinks nothing changed.
**Recommended:** Audit all Lambda source files in `lambdas/` against lambda_map.json entries. Add missing entries. Add CI check that flags `lambdas/*.py` files not present in lambda_map.
**Effort:** S | **Confidence:** High

### R18-F04: New Resources Without Monitoring
**Severity:** Medium | **Category:** Observability | **Type:** NEW
**Observed:**
- `og-image-generator` Lambda has no CloudWatch error alarm
- `food-delivery-ingestion` Lambda has no freshness check in `freshness_checker_lambda.py`
- 8+ new API endpoints (`/api/labs`, `/api/changes-since`, `/api/observatory_week`, `/api/subscriber_count`, `/api/benchmark_trends`, `/api/meal_responses`, `/api/experiment_suggest`, `/api/challenges`) have no per-endpoint error metrics or latency tracking
- `challenge-generator` Lambda monitoring status unknown
**Why it matters:** These resources can fail silently. The platform's operational maturity at R17 was built on "every Lambda has an alarm" — that contract is now broken.
**Recommended:** Extend CloudWatch alarms to all new Lambdas. Add site-api per-route metrics (even if just CloudWatch custom metrics from within the Lambda).
**Effort:** S | **Confidence:** High

### R18-F05: 47-Page Site With Manual S3 Sync Deployment
**Severity:** Medium | **Category:** Operability / Reliability | **Type:** NEW
**Observed:** The website has grown from 12 to 47+ pages with shared JS utilities (`engagement.js`, `site_constants.js`, `components.js`), a design system (`tokens.css`, `base.css`), and dynamic API integrations. All deployment is via manual `aws s3 sync` commands. No build step, no minification, no content hash on CSS/JS filenames (cache was reduced from 1 year to 1 day as mitigation, per v4.3.0 changelog).
**Why it matters:** A 47-page site with shared dependencies is beyond the comfortable limit of "just sync the files." A CSS change could cache-bust inconsistently. The ADR-034 component system helps but is partially implemented. At this scale, a lightweight build step (even just a shell script that validates, syncs, and invalidates) would prevent class-of-error issues.
**Recommended:** Create `deploy/deploy_site.sh` that: validates HTML (link checker), syncs to S3, invalidates CloudFront, and logs the deploy. Not a full SSG — just a single canonical entry point.
**Effort:** S | **Confidence:** Medium

### R18-F06: WAF Rules Are Global, Not Endpoint-Specific for New API Routes
**Severity:** Medium | **Category:** Security | **Type:** NEW
**Observed:** WAF has 2 rules: SubscribeRateLimit (60/5min on `/api/subscribe*`) and GlobalRateLimit (1000/5min all paths). The 8 new API endpoints — particularly `/api/ask` (AI-powered) and `/api/board_ask` (6-persona AI) — have no endpoint-specific WAF rules. The global 1000/5min limit allows substantial API abuse before triggering.
**Why it matters:** An attacker targeting `/api/ask` specifically can make 1000 AI-powered requests per 5 minutes per IP before WAF blocks them. At Haiku pricing, that's ~$0.50/hour per IP — manageable, but the in-memory Lambda rate limits (3 anon/20 subscriber per hour) are the real defence and they still reset on cold start.
**Recommended:** Add WAF rate-based rule for `/api/ask*` at 20/5min per IP (aligns with subscriber limit). Add `/api/board_ask*` at 10/5min. Cost: $0 incremental (rules already within WebACL).
**Effort:** S | **Confidence:** High

### R18-F07: SIMP-1 Phase 2 Moving in Wrong Direction (95 → 110 Tools)
**Severity:** Medium | **Category:** AI / Product | **Type:** REGRESSION from R17-F13
**Observed:** R17 flagged 95 tools with SIMP-1 Phase 2 targeting ≤80. Tools have since grown to 110 (per ARCHITECTURE.md header). The food delivery MCP tool alone added 5 views. No tools were retired.
**Why it matters:** 110 tools in Claude's context window degrades tool selection accuracy and increases MCP Lambda cold start time. Each new tool adds ~50-100 tokens of schema to every MCP request.
**Recommended:** Execute SIMP-1 Phase 2 within 2 weeks of launch. Target: identify 30 tools for retirement or consolidation. The food delivery tool's 5 views could be a single tool with a `view` parameter.
**Effort:** L | **Confidence:** Medium

### R18-F08: INTELLIGENCE_LAYER.md 50+ Versions Behind
**Severity:** Medium | **Category:** Documentation | **Type:** PERSISTING (R14-F02, 5th consecutive review)
**Observed:** INTELLIGENCE_LAYER.md header shows v3.7.68. Platform is at v4.3.0. This document describes the IC architecture, compute pipeline, and prompt standards — it's one of the most important architectural references. It has been flagged as stale since Review #14.
**Why it matters:** A new engineer reading INTELLIGENCE_LAYER.md would miss IC-29, IC-30, the signal doctrine, challenge system integration, food delivery modifiers, and other recent IC work.
**Recommended:** This has persisted for 5 reviews. Either update it or mark it explicitly as "frozen at v3.7.68 — see CHANGELOG for subsequent IC changes." The latter is honest and takes 2 minutes.
**Effort:** S (for the honest label) / L (for full update) | **Confidence:** High

### R18-F09: Cross-Region Split Now Serving 8+ Additional API Routes
**Severity:** High | **Category:** Architecture / Performance | **Type:** WORSENED from R17-F05
**Observed:** In R17, the cross-region concern was for ~5 API routes. The site-api now serves 13+ routes — all making cross-region DynamoDB reads from us-east-1 to us-west-2. New data-heavy routes like `/api/labs` (74 biomarkers), `/api/observatory_week` (7-day domain summaries with sparklines), and `/api/changes-since` (delta computation) make multiple DDB queries per request, each incurring ~60ms cross-region latency.
**Why it matters:** A `/api/observatory_week` call that makes 3 DDB queries now costs 180ms in pure network overhead. User-facing latency on observatory pages is visibly affected. The operational split (us-east-1 logs vs us-west-2 data) makes debugging harder.
**Recommended:** Elevate the us-west-2 migration to Sprint 1 post-launch. This is no longer a nice-to-have — it's affecting user experience.
**Effort:** M | **Confidence:** High

---

## What the System Does Well (Maintained Strengths)

### 1. Architectural Coherence Under Pressure (Priya)
Despite shipping 58+ versions in 8 days, the three-layer Ingest→Store→Serve pattern was maintained. New data sources (food delivery) followed the established pattern: S3 trigger → Lambda → DynamoDB normalisation. New compute (OG images) followed the cron → Lambda → S3 output pattern. The ADR-034 content consistency architecture was a genuine architectural decision under sprint pressure, not tech debt — it shows the builder is thinking about sustainability even while sprinting.

### 2. Security Posture Improvement (Yael)
The R17 critical findings — WAF, persistent rate limiting, privacy policy, separate AI API key — were all addressed. The `public: false` challenge filtering (both server-side and client-side) shows security thinking applied to new features, not just infrastructure. The `isBlocked` keyword filter on the mind page vice streak rendering shows content-level privacy awareness.

### 3. Data Engineering Discipline (Omar)
Food delivery integration: 1,598 transactions spanning 2011-2026, clean PK/SK pattern, dollar amounts stripped from public API responses (privacy), delivery index (0-10 scale) as the public metric with August 2025 calibrated as 10.0. This is a textbook data integration — well-normalised, privacy-aware, with clear domain modelling.

### 4. Cost Discipline (Dana)
~$19/month including WAF for: 47-page editorial website, 50+ Lambdas, 26 data sources, 110 MCP tools, AI Q&A endpoints, subscriber management, dynamic OG images, 4 CloudFront distributions, 10 secrets, 49+ alarms. The OG image Lambda using Pillow instead of an AI image generation API was the right call — $0 incremental for data-driven social cards.

### 5. Product Execution (Sarah, Ava, Jordan)
The pre-launch offsite (4 parts, 34 decisions, ~548 recommendations) was a disciplined product development process. Reader engagement phases (1-4) were well-sequenced: freshness indicators → progress tracking → weekly recaps → living pulse feed. The observatory design pattern (editorial hero, staggered pull-quotes, evidence badges) is consistent and professional across 5 health domains. The Discord community strategy is distribution-aware.

---

## Top 10 Risks

| # | Risk | Severity | Likelihood | Trend |
|---|------|----------|-----------|-------|
| 1 | Documentation materially wrong about system state | High | **Certain** | NEW — immediate |
| 2 | CLI-created Lambdas drifting from CDK management | High | High | NEW |
| 3 | Cross-region latency degrading UX on 13+ API routes | High | High | ↑ WORSE |
| 4 | New resources failing silently (no alarms) | Medium | High | NEW |
| 5 | 110 MCP tools degrading Claude's selection accuracy | Medium | Medium | ↑ WORSE |
| 6 | WAF global rate limit too generous for /api/ask abuse | Medium | Medium | NEW |
| 7 | PITR untested — disaster recovery theoretical | Medium | Low | = SAME |
| 8 | lambda_map stale — CI/CD pipeline blind to new Lambdas | Medium | High | NEW |
| 9 | 47-page manual S3 deploy with no validation step | Medium | Medium | NEW |
| 10 | INTELLIGENCE_LAYER.md misleading — 50 versions stale | Medium | High | ↑ WORSE |

---

## Top 10 Highest-ROI Improvements

| # | Improvement | Effort | Impact | When |
|---|------------|--------|--------|------|
| 1 | **Documentation audit** — reconcile all counts with `aws lambda list-functions`, update ARCH/INFRA/INT_LAYER headers | M | High | Launch week |
| 2 | **CDK adoption** — bring food-delivery + og-image-generator + challenge-generator into CDK stacks | M | High | Launch week |
| 3 | **lambda_map.json update** — add all missing entries, add CI lint for orphan .py files | S | High | Day 1 post-launch |
| 4 | **New resource alarms** — error alarms for og-image-generator, food-delivery; freshness for food-delivery | S | Medium | Day 1 post-launch |
| 5 | **WAF endpoint rules** — add /api/ask (20/5min) and /api/board_ask (10/5min) rate rules | S | Medium | Launch week |
| 6 | **INTELLIGENCE_LAYER.md label** — add honest "frozen at v3.7.68" header if full update deferred | S | Medium | Immediate |
| 7 | **Site deploy script** — `deploy/deploy_site.sh` with validation + sync + invalidation | S | Medium | Week 2 |
| 8 | **SIMP-1 Phase 2 kickoff** — identify 30 tools for retirement/consolidation, execute within 2 weeks | L | Medium | Week 2-3 |
| 9 | **Cross-region migration planning** — scope moving site-api to us-west-2, target Week 3 | M | High | Week 3 |
| 10 | **PITR drill** — execute once, document results, close this 6-review-old finding | S | Medium | Week 2 |

---

## 30-60-90 Day Roadmap

### 30 Days (Launch + Stabilisation)
1. **April 1: Launch.** Run LAUNCH_DAY.md checklist. Monitor for 48 hours.
2. Documentation audit — single session, reconcile ARCHITECTURE.md, INFRASTRUCTURE.md, INTELLIGENCE_LAYER.md to match reality
3. CDK adoption of CLI-created Lambdas (food-delivery, og-image-generator, challenge-generator)
4. Update lambda_map.json, add CI orphan-file lint
5. New resource alarms (og-image-generator, food-delivery, challenge-generator)
6. WAF endpoint-specific rules for /api/ask and /api/board_ask
7. PITR restore drill (carried since R13 — 6 reviews)
8. Connection challenges updated with real names (from handover action items)
9. Discord community launch (April 2)
10. DIST-1 (first external distribution push)

### 60 Days
11. SIMP-1 Phase 2 — MCP tools 110 → ≤80
12. Move site-api to us-west-2 (R17-F05 / R18-F09)
13. ADR-025 cleanup
14. Site deploy script (`deploy/deploy_site.sh`)
15. INTELLIGENCE_LAYER.md full update
16. IC-4 / IC-5 activation (data-gated to ~April 18)

### 90 Days
17. Content consistency migration (ADR-034) — convert remaining pages to component system
18. Architecture Review #19
19. CSS/JS content hashing or build step evaluation
20. API observability dashboard (per-route latency, error rates)

---

## Board Decisions (R18 Session)


... [TRUNCATED — 40 lines omitted, 290 total]


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

**Root docs (56 files):** ARCHITECTURE.md, BOARDS.md, CHANGELOG.md, CHANGELOG_ARCHIVE.md, CLAUDE_CODE_BRIEF_2026-03-28.md, COST_TRACKER.md, DATA_FLOW_DIAGRAM.md, DECISIONS.md, DISCORD_INTEGRATION_SPEC.md, DISCOVERIES_EVOLUTION_SPEC.md, EXPERIMENTS_EVOLUTION_SPEC.md, FN-01_FIRST_PERSON_BUILD.md, FOOD_DELIVERY_SPEC.md, HANDOVER_LATEST.md, HOME_EVOLUTION_SPEC.md, IMPL_SUBSCRIBER_EMAIL_REDESIGN.md, INCIDENT_LOG.md, INFRASTRUCTURE.md, INTELLIGENCE_LAYER.md, LAUNCH_DAY.md, MCP_TOOL_CATALOG.md, MCP_TOOL_TIERING_DESIGN.md, MEASUREMENTS_IMPLEMENTATION_SPEC.md, OFFSITE_BUILD_PLAN.md, OFFSITE_BUILD_PLAN_2026-03-27.md, OFFSITE_BUILD_PLAN_PART3.md, OFFSITE_BUILD_PLAN_PART4.md, OFFSITE_FEATURE_LIST.md, OFFSITE_FEATURE_LIST_PART3.md, OFFSITE_FEATURE_LIST_PART4.md, OFFSITE_PART3_PROMPT.md, OFFSITE_PART4_PROMPT.md, OFFSITE_PRIORITY_SPEC.md, ONBOARDING.md, PLATFORM_GUIDE.md, PROJECT_PLAN.md, PROJECT_PLAN_ARCHIVE.md, PULSE_REDESIGN_SPEC.md, R18_REMEDIATION_PROMPT.md, REVIEW_METHODOLOGY.md, REVIEW_RUNBOOK.md, RUNBOOK.md, SCHEMA.md, SIMP1_PLAN.md, SLOs.md, SPRINT_PLAN.md, STATUS_PAGE_SPEC.md, STORY_ABOUT_REVIEW_SPEC.md, V2_PAGE_DESIGN_BRIEFS.md, VISUAL_ASSET_BRIEF.md, VISUAL_DECISIONS.md, WEBSITE_REDESIGN_SPEC.md, WEBSITE_ROADMAP.md, WEBSITE_STRATEGY.md, reader-engagement-implementation-plan.md, sec3_input_validation_assessment.md


**docs/archive/ (18 files):** AUDIT_PROD2_MULTI_USER.md, AVATAR_DESIGN_STRATEGY.md, BOARD_DERIVED_METRICS_PLAN.md, CHANGELOG_v341.md, DATA_DICTIONARY_archived_v3.7.32.md, DERIVED_METRICS_PLAN.md, DESIGN_PROD1_CDK.md, DESIGN_SIMP2_INGESTION.md, FEATURES_archived_v3.7.32.md, NOTION_ENRICHMENT_SPEC.md, NOTION_JOURNAL_SPEC.md, SCHEMA_LABS_ADDITION.md, SCOPING_LARGE_OPUS.md, SPEC_CHARACTER_SHEET.md, USER_GUIDE_archived_v3.7.32.md, avatar-design-strategy.md, data-source-audit-2026-02-24.md, wednesday-chronicle-design.md


**docs/audits/ (2 files):** AUDIT_2026-03-21_website.md, IAM_AUDIT_2026-03-08.md


**docs/briefs/ (2 files):** BRIEF_2026-03-26_arena_lab_v2.md, BRIEF_2026-03-26_design_brief.md


**docs/content/ (3 files):** ELENA_PREQUEL_BRIEF.md, STORY_DRAFTS_v1.md, STORY_INTERVIEW_FULL.md


**docs/design/ (1 files):** MULTI_USER_ISOLATION.md


**docs/rca/ (2 files):** PIR-2026-02-28-ingestion-outage.md, RCA_2026-02-24_apple_health_pipeline.md


**docs/reviews/ (29 files):** BOARD_SPRINT_REVIEW_2026-03-16.md, BOARD_SUMMIT_2026-03-16.md, BOARD_SUMMIT_2_2026-03-17.md, BOARD_SUMMIT_2_2026-03-17_POINTER.md, IMPLEMENTATION_PLAN_WR4.md, REVIEW_2026-03-08.md, REVIEW_2026-03-08_v2.md, REVIEW_2026-03-09.md, REVIEW_2026-03-09_full.md, REVIEW_2026-03-10.md, REVIEW_2026-03-10_full.md, REVIEW_2026-03-10_v6.md, REVIEW_2026-03-11_v7.md, REVIEW_2026-03-14_v13.md, REVIEW_2026-03-15_v14.md, REVIEW_2026-03-15_v15.md, REVIEW_2026-03-15_v16.md, REVIEW_2026-03-20_v17.md, REVIEW_2026-03-26_website_v4.md, REVIEW_2026-03-28_v18.md, REVIEW_BUNDLE_2026-03-10.md, REVIEW_BUNDLE_2026-03-14.md, REVIEW_BUNDLE_2026-03-15.md, REVIEW_BUNDLE_2026-03-29.md, SIMP1_PHASE2_PLAN.md, WEBSITE_PANEL_REVIEW_2026-03-20.md, joint-board-email-review-2026-03-29.md, mcp_architecture_review_2026-03-11.md, platform-review-2026-03-05.md



---


*Bundle generated 2026-03-29 by deploy/generate_review_bundle.py*
