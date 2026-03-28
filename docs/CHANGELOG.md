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

### Spec Documents Committed (commit 32a3035)

| Doc | Path |
|---|---|
| Status Page Spec | `docs/STATUS_PAGE_SPEC.md` |
| Story/About Review | `docs/STORY_ABOUT_REVIEW_SPEC.md` |
| Food Delivery Spec | `docs/FOOD_DELIVERY_SPEC.md` |

### Challenges Catalog — 83 challenges total
- 17 new entries with custom `icon_svg` fields added
- Two embargoed (public: false): `no-weed-30`, `no-porn-30`
- Synced to S3 + committed

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

### Meta-Discussions Resolved
- Build Section Consolidation: all 7 pages stay standalone. Builders candidate for top-level nav.
- Board Persona Compromise: fictional names + "inspired by" attribution pattern approved
- Mobile Audit (M-series): 11 recs — real-device QA critical, Tools badges + Cost column fixes
- Visual Design (VIS-series): 12 recs — subscribe button color, Sleep/Glucose observatory alignment, OG images
- AI Slop Differentiation (SLOP-series): 5 recs — change accent color + retire // labels (with rollback)
- General Feedback (GEN-series): 8 post-launch ideas — "Your Day 1" page, reader observation pipeline, "start here" reading order
- Pre-Launch Questions (PRE-series): 16 recs — graceful degradation, WCAG contrast fix, sitemap, privacy review

### Critical Items for April 1 (12)
28a cost reconciliation, 29a days tracked, 30a/30b board personas, 31b mobile badges, 34b stat reconciliation, SLOP-1 accent color, PRE-1 degradation audit, PRE-5 contrast fix, M-1 device QA, PRE-9 sitemap, PRE-13 data privacy review

### Guardrails Set (cumulative: 5)
16q no Considering section, 19t no downvotes, 22-S1 one subscription, 22-S4 no reader streaks, 30c real-experts editorial only

---

## v3.9.41 — 2026-03-27: Pre-Launch Content Review (Product Board Editorial Session)

Full editorial review across Home, Story, and About pages with Product Board content panel. Matthew provided page-by-page feedback; board aligned and added catches.

### Home Page
- Hero tagline: "For real this time" → "One person. Nineteen data sources. Every week, publicly."
- Hero narrative broadened beyond weight (apps/podcasts/reels framing)
- "Why I'm doing this in public" rewritten (disappearing pattern, honesty)
- "Senior Director" removed, ticker updated, meta/OG/title tags updated
- Fixed 4 duplicate bugs (subscribe line, sample link, social proof script, redirect)

### Story Page (All 5 Chapters Rewritten)
- Ch 1: "Multiple times", gym/diet leads, slide rewritten (gentleman's agreement), "disappointment" not "disgust", promise elaboration (covenant, trust)
- Ch 2: De-doxxed, added athletics + isolation trigger, limbic system/purpose framing
- Ch 3: Product journey focus (AI therapy → data idea → spiral), removed "Senior Director"/"terrifying"
- Ch 4: Simplified to forward-looking (10yr logs, stock-ticker pattern, mind data gap)
- Ch 5: Cheerleader passage removed, replaced with disappearing pattern + honesty
- Waveform moved between Ch 1 and Ch 2, renamed "The Pattern"

### About Page
- "Senior Director" removed throughout (meta, header, bio, sidebar)
- Press/media section → warm "If You Want to Connect" section
- Media kit/speaking/bios/talk topics removed entirely (60 lines)
- Sidebar: "Day job: Sr. Director" → "Background: IT Career"

### Bug Fixes
- Duplicate dark mode toggle in nav.js removed (components.js is source of truth)
- Stray `</div>` tags removed from story + about pages

---

## v3.9.40 — 2026-03-27: Nav Spacer Architecture + Catalog Fix + UX Cleanup

Tech Board–approved nav spacer architecture (5-1-1 vote), Product Board–approved hierarchy tab removal (7-0 vote). Fixed challenge catalog format bug that broke all 65 tiles. Swept Arena/Lab naming to Challenges/Experiments everywhere. Centered home page comparison. Fixed dropdown headings. 37-file nav-height sweep.

### Architecture (Tech Board Approved — 5-1-1)
- **Nav spacer pattern**: components.js injects `.nav-spacer` div after nav — single source of truth for fixed-nav clearance
- `.nav-spacer` CSS class in base.css (height: var(--nav-height))
- `deploy/nav_spacer_sweep.sh` — automated 3-pattern sweep across all 37 page files

### UX (Product Board Approved — 7-0)
- **Hierarchy tab bar removed** from all method pages — breadcrumb + main nav sufficient for wayfinding

### Fixes
- **Challenge catalog format**: v3.9.39 expansion rewrote JSON as flat list instead of `{categories, challenges}` dict — API crashed, only DynamoDB active records showed. Rebuilt with proper wrapper — all 65 tiles restored
- **S3 path mismatch**: challenge catalog + experiment library uploaded to `config/` but Lambda reads `site/config/` — fixed
- **Name consistency**: "The Arena" → "Challenges" and "The Lab" → "Experiments" in breadcrumbs, `<title>`, `<h1>`, OG tags, pipeline navs

---

## v3.9.39 — 2026-03-27: Pre-Launch Sweep — Nav Fixes, Mobile Scroll, Catalog Expansion

Consolidated all undone items from 10+ sessions into action plan. Fixed nav naming (Arena→Challenges), mobile menu scroll bug, verified subscribe flow, built baseline capture script, expanded challenge catalog 34→66 and experiment library 58→71.

---

## v3.9.38 — 2026-03-26: Visual Asset System — 65 SVGs + 3-Page Integration

Product Board visual strategy session → creative direction document → 65 SVG assets generated → wired into milestones, live, and character pages → deployed to CloudFront.

---

## v3.9.37 — 2026-03-26: Product Board Pre-Launch Punch List (23 items)

All 23 items from the Product Board pre-launch review, preparing for April 1 go-live.

---

## v3.9.36 — 2026-03-26: Signal Doctrine Tier 2

5-section nav restructure, observatory pillar accent colors, home sparklines, Podcast Intelligence Phase 2 Lambda.

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

