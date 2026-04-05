# Life Platform — Website Roadmap

> Comprehensive feature roadmap for averagejoematt.com
> Source: Unified Board Summit #3 (2026-03-21) — Technical Board + Personal Board + Web Board (30+ personas)
> For sprint-level tracking, see SPRINT_PLAN.md. For version history, see CHANGELOG.md.
> Last updated: 2026-03-21 (v3.8.0)

---

## Current State (v3.8.0)

**15 live pages** at averagejoematt.com. 30 HTML files total (including journal posts, templates, subpages).

### Navigation Architecture (updated v3.8.9)

5-section dropdown nav. Each parent is a dropdown button; children are the actual pages.

| Parent | Children |
|--------|----------|
| **THE STORY** | My Story, The Mission |
| **THE DATA** | Live, Character Sheet, Habits, Progress, Sleep, Glucose, Supplements, Benchmarks |
| **THE SCIENCE** | Protocols, Experiments, Discoveries |
| **THE BUILD** | Platform, Intelligence, AI Board, Cost, Methodology, Tools |
| **FOLLOW** | Weekly Journal, Subscribe, Ask the Data |

| Tier | Location | Notes |
|------|----------|-------|
| Top nav (desktop) | Fixed header | 5 dropdown parents + Subscribe → CTA |
| Hamburger (mobile) | Top-right ☰ | Full-page overlay mirroring the 5 sections |
| Footer (all) | Page bottom | Links to major pages across all 5 sections |

### Content Safety Filter (shipped v3.8.0)

- S3 config: `config/content_filter.json` — defines blocked vices and keywords
- Lambda: `_load_content_filter()`, `_scrub_blocked_terms()`, `_is_blocked_vice()`
- System prompt: `/api/ask` instructs Claude to never mention blocked terms
- Response scrubbing: both `/api/ask` and `/api/board_ask` pass through filter

### Design System

- **Aesthetic**: Dark biopunk terminal — `#080c0a` bg, `#22c55e` accent, Space Mono
- **Token system**: `tokens.css` with CSS custom properties for all colors, spacing, typography
- **Theme switching**: Architecture designed (data-theme selectors), not yet implemented
- **Rollback**: `deploy/rollback_site.sh` + git tags (`site-v3.8.0`)

---

## Live Pages Inventory

| # | Path | Purpose | Data Sources | API Endpoints | Status |
|---|------|---------|-------------|---------------|--------|
| 1 | `/` | Homepage — hero, ticker, sparklines, brief, discoveries, comparison card | Whoop, Withings, public_stats.json | /api/vitals, /api/journey | ✅ Live |
| 2 | `/story/` | Origin narrative — 5 chapters | Matthew's prose | — | ✅ Structure · ⬜ Content (Matthew) |
| 3 | `/live/` | Transformation timeline — interactive weight chart + life events | Withings, experiments, character | /api/timeline | ✅ Live |
| 4 | `/journal/` | Weekly Signal newsletter + chronicle index | Notion journal | — | ✅ Live |
| 5 | `/journal/sample/` | Newsletter preview (The Weekly Signal mock) | — | — | ✅ Live |
| 6 | `/journal/posts/week-XX/` | Individual chronicle installments (weeks 0-3) | Notion journal | — | ✅ Live |
| 7 | `/platform/` | Architecture — data flow, cost, tool spotlight | Architecture docs | — | ✅ Live |
| 8 | `/platform/reviews/` | Public architecture review (R17) | Review docs | — | ✅ Live |
| 9 | `/character/` | Character Sheet — 7-pillar radar chart, scoring methodology | Character sheet compute | /api/character, /api/character_stats | ✅ Live |
| 10 | `/ask/` | AI Q&A — ask the platform's data | All 19 sources via Claude | /api/ask | ✅ Live |
| 11 | `/board/` | "What Would My Board Say?" — 6 AI personas | Board config | /api/board_ask | ✅ Live |
| 12 | `/explorer/` | Correlation explorer — 23-pair Pearson matrix | weekly_correlations | /api/correlations | ✅ Live |
| 13 | `/experiments/` | N=1 experiment archive | experiments partition | /api/experiments | ✅ Live |
| 14 | `/biology/` | Genome risk dashboard — 110 SNPs | genome partition | /api/genome_risks | ✅ Live (noindex) |
| 15 | `/protocols/` | Current health protocols with compliance | Protocol docs | — | ✅ Live |
| 16 | `/about/` | Bio, professional context, media kit, talk topics | — | — | ✅ Live |
| 17 | `/subscribe/` | Email list landing page | — | — | ✅ Live |
| 18 | `/data/` | Open data page — schema, methodology, fetch examples | — | — | ✅ Live |
| 19 | `/privacy/` | Privacy policy | — | — | ✅ Live |

---

## Proposed New Pages (Priority Order)

### Phase 1 — High-Impact, Data Already Exists (Sprint 9-10)

These pages have MCP tools already returning structured data. The work is purely frontend presentation.

#### `/habits/` — The Habit Observatory
**Champion**: Coach Maya Rodriguez
**MCP tools**: `get_habits` (6 views: dashboard, adherence, streaks, tiers, stacks, keystones), `get_habit_registry` (65 habits, full metadata)
**Content**:
- GitHub-contribution-style heatmap — 65 habits × 365 days, color-coded by group
- Tier 0 perfect-day streak counter (the non-negotiable metric)
- Keystone habit spotlight — which single habit most correlates with overall score
- Synergy stacks — visual display of habit clusters (morning_stack, recovery_stack, etc.)
- Per-group adherence bars (9 groups: Data, Discipline, Growth, Hygiene, Nutrition, Performance, Recovery, Supplements, Wellbeing)
- Knowing-doing gap: decision fatigue signal plotted over time
**Content filter**: Apply `_is_blocked_vice()` to exclude "No porn" and "No marijuana" from all displays
**API needed**: New `/api/habits` endpoint (or client-side fetch from existing public_stats)
**Effort**: M (4-6h)
**Shareable asset**: The heatmap is the single most shareable visual on the site

#### `/achievements/` — Badge & Milestone Gallery
**Champion**: Sarah Chen (Product) + Ava Moreau (UX)
**MCP tools**: `get_rewards`, `get_vice_streaks`, `get_character` (history view), `get_habits` (streaks)
**Content**:
- **Streak badges**: 7-day, 30-day, 90-day, 365-day across categories
- **Tier badges**: "Sleep Discipline", "Movement Mastery" when pillars hit tier thresholds
- **Vice badges**: "30 Days Clean", "90 Days Clean" with compounding value
- **Experiment badges**: "First Experiment", "Hypothesis Confirmed", "N=1 Scientist (10 experiments)"
- **Data badges**: "100 Journal Entries", "1000 Habit Logs", "365 Days Tracked"
- **Milestone badges**: "First 10 lbs Lost", "Sub-270", "Sub-250"
- Earned vs pending badges (pending creates aspiration)
**Content filter**: Exclude badges related to blocked vices
**API needed**: New `/api/achievements` endpoint (compute from existing data)
**Effort**: M (4-6h)

#### `/supplements/` — The Supplement Protocol Page
**Champion**: Dr. Rhonda Patrick
**MCP tools**: `get_supplement_log`, `get_genome_insights` (cross_reference='nutrition')
**Content**:
- Current stack with dosage, timing, adherence %
- Genome rationale for each supplement (e.g., "Omega-3: FADS2 rs1535 poor ALA conversion, adherence 94%")
- Link to experiment data if supplement has an N=1
- Cost per month breakdown
**Effort**: S (2-3h)

#### `/benchmarks/` — Centenarian Decathlon Dashboard
**Champion**: Dr. Peter Attia
**MCP tools**: `get_centenarian_benchmarks`
**Content**:
- 4 lift gauges: deadlift, squat, bench, overhead press — current % of target
- Bodyweight-relative calculations with Attia's framework explained
- **Interactive element**: visitors enter their OWN numbers and see their score
- "You need to be THIS strong now to still be functional at 85"
**Effort**: M (4-6h) — the interactive calculator is the key differentiator

#### `/journal/archive/` — The Full Chronicle Archive
**Champion**: Elena Voss
**MCP tools**: `get_journal_entries`, `search_journal`
**Content**:
- Chronological list of all chronicle installments
- Each entry: date, thesis line, word count
- Thesis lines alone tell the story: "Week 3: The Scale Lies", "Week 7: The Night the Data Spoke"
**Effort**: S (2-3h)

#### Character Avatar System (enhancement to `/character/`)
**Champion**: Sarah Chen + Ava Moreau
**MCP tools**: `get_character` (sheet view)
**Content**:
- SVG-based character that visually evolves with pillar tiers
- Level 1: simple silhouette
- Pillar improvements add visual elements: glow for Sleep mastery, muscle for Movement, connections for Relationships
- 5 tiers × 7 pillars = 35 visual elements that compose
- At Level 100: fully realized avatar
**Implementation**: Hand-designed SVG states, conditionally rendered based on pillar tiers. No AI image generation.
**Effort**: L (7-10h)

### Phase 2 — Deep Intelligence Pages (Sprint 11-13)

#### `/glucose/` — CGM Intelligence Page
**Champion**: Dr. Peter Attia
**MCP tools**: `get_cgm` (dashboard, fasting), `get_glucose_meal_response`
**Content**:
- Time-in-range gauge (target >90%)
- Variability metrics (SD target <20)
- Best/worst foods ranked by glucose response letter grade
- Meal-level detail: pre-meal baseline → peak → spike magnitude → grade
- Methodology: Levels-style postprandial scoring
**Effort**: M (4-6h)

#### `/sleep/` — Sleep Environment Intelligence
**Champion**: Dr. Andrew Huberman
**MCP tools**: `get_sleep_environment_analysis`, Whoop sleep data
**Content**:
- Eight Sleep × Whoop cross-reference: optimal bed temp bands
- Temperature optimization discovery with actual data
- Circadian consistency patterns (weekday vs weekend)
- Sleep architecture trends (REM%, deep%)
- Sleep onset correlation with next-day recovery
**Effort**: M (4-6h)

#### `/intelligence/` — The AI Brain Page
**Champion**: Ethan Mollick + Anika Patel
**MCP tools**: `get_hypotheses`, `get_decisions`, `get_adaptive_mode`, `get_decision_fatigue_signal`, `get_metabolic_adaptation`, all IC features
**Content**:
- 14+ intelligence layer features explained with live examples
- Hypothesis that moved from "pending" to "confirmed" with actual data
- Metabolic adaptation detector catching a stall before it happened
- Decision fatigue signal with the threshold where habits break down
- Adaptive mode history (flourishing vs struggling)
**Effort**: L (7-10h)

#### `/progress/` — Visual Transformation Timeline
**Champion**: Ava Moreau
**MCP tools**: `get_longitudinal_summary`, `get_character` (history), `get_health` (trajectory)
**Content**:
- Multi-axis timeline: all 7 pillars evolving simultaneously
- Interactive: click any date → see full snapshot from that day
- Hover weight line → see what daily brief said that morning
- Character level milestones overlaid on timeline
**Effort**: L (7-10h)

#### `/accountability/` — The Public Contract
**Champion**: Dr. Vivek Murthy
**MCP tools**: `get_habits` (tiers), `get_vice_streaks`, `get_character` (sheet)
**Content**:
- Matthew's stated commitments alongside live compliance data
- "14 of 14 days protein target hit"
- "7-day T0 habit streak: intact"
- "Vice portfolio: $47.2 value"
- Radical transparency as accountability mechanism
**Content filter**: Exclude blocked vices from all displays
**Effort**: S (2-3h)

#### `/methodology/` — Statistical Rigor Page
**Champion**: Dr. Henning Brandt
**MCP tools**: None (static content)
**Content**:
- BH FDR correction methodology
- N=1 framework and limitations
- Correlation vs causation framing
- Sample sizes, confidence intervals, data quality notes
- "The value isn't that my results apply to you — it's that the methodology might inspire your own experiment"
**Effort**: S (2-3h)

### Phase 3 — Engagement & Gamification

#### "Since Your Last Visit" Badges
- Track visits via localStorage
- Show subtle dot indicator on bottom nav icons when content updated
- Journal dot when new chronicle publishes
- Score dot when character level changes

#### Contextual Page-Bottom CTAs (David Perell's "Reading Path")
- `/story/` ends with "See today's data →" → `/live/`
- `/live/` ends with "Read the latest chronicle →" → `/journal/`
- `/journal/` ends with "Explore the correlations →" → `/explorer/`
- `/explorer/` ends with "Ask the data anything →" → `/ask/`
- Creates sequential flow on top of random-access nav

#### Daily Brief as Mobile Homepage Anchor
- On mobile, homepage leads with today's brief excerpt (not hero)
- The daily hook for return visitors

### Phase 4 — Commercialization Infrastructure (Post 1,000 Subscribers)

#### `/premium/` — Tier Comparison Page
- Free vs premium newsletter comparison
- Deep weekly analysis, raw data access, AMA

#### `/for-builders/` — "Build Your Own AI Health OS" Landing Page
- SEO entry point for "AI health platform" searches
- Links to course, architecture docs, /platform/

#### Prompt Pack Product ($49-99)
- Board of Directors persona system
- Chain-of-thought coaching prompts
- Attention-weighted prompt budgeting (IC-23)
- Scoring framework documentation

#### Open-Source Template
- Stripped platform skeleton: DynamoDB schema, Lambda skeleton, MCP bridge, 5 core integrations
- Supabase model: free core + commercial "full version"

#### Community Membership ($29/mo)
- Shared accountability, buddy matching
- Group N=1 experiments with platform methodology
- Members run own experiments

---

## Design System Notes

### Current (Dark Biopunk Terminal)
```css
:root {
  --bg: #080c0a;
  --surface: #0e1510;
  --text: #e8f0e8;
  --accent: #22c55e;  /* Signal green */
  --font-display: 'Bebas Neue';
  --font-mono: 'Space Mono';
  --font-serif: 'Lora';
}
```

### Theme System (designed, not yet implemented)
- Add `[data-theme="light"]` block to `tokens.css` overriding all semantic tokens
- Toggle via sun/moon icon in nav
- Persist to localStorage
- Zero-deploy visual switching

### Versioning
- Git tags: `site-vX.Y.Z` on every deploy
- Rollback: `bash deploy/rollback_site.sh site-v3.8.0`

---

## Content Filter System

### Config: `s3://matthew-life-platform/config/content_filter.json`
```json
{
  "blocked_vices": ["No porn", "No marijuana"],
  "blocked_vice_keywords": ["porn", "pornography", "marijuana", "cannabis", "weed", "thc"]
}
```

### Integration Points
1. **site_api_lambda.py** — `_load_content_filter()`, `_scrub_blocked_terms()`, `_is_blocked_vice()`
2. **System prompt** — `/api/ask` explicitly instructs "NEVER mention" blocked terms
3. **Future pages** — Any page displaying vice/habit data must call `_is_blocked_vice(name)` before rendering
4. **Email Lambdas** — TODO: integrate into daily_brief_lambda, weekly_digest_lambda, chronicle Lambda

### Adding New Blocked Terms
1. Edit `seeds/content_filter.json`
2. Upload: `aws s3 cp seeds/content_filter.json s3://matthew-life-platform/config/content_filter.json`
3. Lambda picks up changes on next cold start (or within ~15 min warm container refresh)

---

## API Endpoints Available

### Existing (site_api_lambda.py, us-east-1)
| Endpoint | Method | Cache | Returns |
|----------|--------|-------|---------|
| `/api/vitals` | GET | 300s | Weight, HRV, recovery, RHR, sleep, 30d trends |
| `/api/journey` | GET | 3600s | Weight trajectory, progress %, projected goal date |
| `/api/character` | GET | 900s | Character level, pillar scores, tier |
| `/api/character_stats` | GET | 3600s | Pillar detail with levels and tiers |
| `/api/weight_progress` | GET | 3600s | 180d weight readings |
| `/api/habit_streaks` | GET | 3600s | T0 streak and completion % |
| `/api/experiments` | GET | 3600s | Experiment list with status |
| `/api/timeline` | GET | 3600s | Weight + life events + experiments + level-ups |
| `/api/correlations` | GET | 3600s | Weekly Pearson matrix (23 pairs) |
| `/api/genome_risks` | GET | 86400s | SNPs by category with risk levels |
| `/api/current_challenge` | GET | 3600s | Weekly challenge from S3 config |
| `/api/status` | GET | 60s | Health check |
| `/api/ask` | POST | no-store | AI Q&A (3 anon/20 sub q/hr) |
| `/api/board_ask` | POST | no-store | Board persona responses (5/hr) |
| `/api/verify_subscriber` | GET | no-store | Subscriber token verification |

### Needed for New Pages
| Page | Endpoint Needed | Data Source | Notes |
|------|----------------|-------------|-------|
| `/habits/` | `/api/habits` | habit_scores + habit_registry DDB | Aggregate heatmap + streaks + groups |
| `/achievements/` | `/api/achievements` | rewards + streaks + character history | Compute badges from existing data |
| `/supplements/` | `/api/supplements` | supplement_log + genome DDB | Stack with adherence + genome rationale |
| `/benchmarks/` | `/api/benchmarks` | centenarian_benchmarks compute | Already exists as MCP tool |
| `/glucose/` | `/api/glucose` | CGM + macrofactor DDB | Meal grades + time-in-range |
| `/sleep/` | `/api/sleep_environment` | eightsleep + whoop DDB | Temp bands + architecture |
| `/intelligence/` | `/api/intelligence` | hypotheses + decisions DDB | IC feature showcase |
| `/accountability/` | `/api/accountability` | habits + vices + character | Live compliance data |

---

## Implementation Notes for Claude Code

### File Structure
```
site/
  index.html                    # Homepage
  assets/
    css/tokens.css              # Design tokens (single source of truth for colors/spacing)
    css/base.css                # Base styles + Sprint 8 mobile nav CSS
    js/nav.js                   # Shared navigation component
    fonts/                      # Self-hosted Bebas Neue, Space Mono, Lora
    images/                     # OG images, icons
    config/                     # (local copy of S3 configs)
  [page]/index.html             # Each page is a directory with index.html
  sitemap.xml                   # Must be updated when adding pages
  robots.txt
  rss.xml
```

### Page Template Pattern
Every page follows this structure:
1. `<head>` with tokens.css + base.css + OG meta tags
2. `<nav class="nav">` — top nav (auto-patched by deploy_sprint8_nav.py)
3. `<!-- Mobile overlay menu -->` — hamburger overlay
4. Page content sections with `class="reveal"` for scroll animations
5. `<!-- Mobile bottom nav -->` — persistent bottom bar
6. `<footer class="footer-v2">` — grouped footer
7. `<script src="/assets/js/nav.js"></script>`
8. Page-specific `<script>` for data fetching

### Deploy Pattern
```bash
# After any site changes:
aws s3 sync site/ s3://matthew-life-platform/site/ --delete
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/*"

# After Lambda changes (site-api is in us-east-1):
zip -j /tmp/site_api_deploy.zip lambdas/site_api_lambda.py
aws lambda update-function-code --function-name life-platform-site-api \
  --zip-file fileb:///tmp/site_api_deploy.zip --region us-east-1 --no-cli-pager

# Tag every deploy:
git tag site-vX.Y.Z
```

### Content Filter Integration (REQUIRED for all new pages)
Any page displaying vice, habit, or temptation data MUST:
1. Load content filter from S3 (or hardcode the blocked list client-side)
2. Filter out blocked vices before rendering
3. Never display "No porn" or "No marijuana" in any context
4. The `/api/` response scrubbing handles AI-generated content; static pages need client-side filtering

### Adding a New Page Checklist
1. Create `site/[page]/index.html` following template pattern
2. Add to `site/sitemap.xml`
3. Add to nav overlay in `deploy/deploy_sprint8_nav.py` OVERLAY_HTML
4. Add to footer in `deploy/deploy_sprint8_nav.py` FOOTER_HTML
5. Run `python3 deploy/deploy_sprint8_nav.py` to patch all pages
6. If API endpoint needed: add handler to `lambdas/site_api_lambda.py`, add route to ROUTES dict
7. Deploy: S3 sync + CloudFront invalidate + Lambda (if changed)
8. Update `docs/WEBSITE_ROADMAP.md` status

---

## Sprint 6 Tier 0 Remaining (Pre-Distribution)

These items from R17 hardening are still pending and should be done before adding new pages:

| ID | Item | Status |
|----|------|--------|
| R17-02 | Privacy policy page (content review) | ⬜ |
| R17-04 | Separate Anthropic API key for site-api | ⬜ |
| R17-07 | Remove google_calendar from config.py | ⬜ |

---

*Board Summit #3: March 21, 2026 | 30+ personas (Technical Board + Personal Board + Web Board)*
*Champions listed are advisory — Matthew Walker is the implementer*
