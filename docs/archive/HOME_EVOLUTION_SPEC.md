# HOME PAGE EVOLUTION — Implementation Spec

## Product Board Session: March 25, 2026 | v3.9.17 baseline

> **Source**: Product Board full session — Mara (UX), Sofia (CMO), Lena (Science), Raj (Product), Tyrell (Design), Jordan (Growth), Ava (Content), James (CTO)
> **Usage**: Claude Code works through tasks by priority. Each task is a standalone unit.

---

## TASK SUMMARY

| ID | Task | Board Member | Priority | Est. Complexity |
|----|------|-------------|----------|-----------------|
| HP-01 | Remove duplicate CHARACTER card | Mara, James | P0 | Trivial |
| HP-02 | Delete dead CSS (old grid hero) | Tyrell, James | P0 | Trivial |
| HP-03 | Restore hero subscribe input | Jordan, Sofia | P0 | Small |
| HP-04 | Add proper H1 tag | Jordan | P0 | Trivial |
| HP-05 | Fix OG tags — current state, not goal | Sofia | P0 | Small |
| HP-06 | Dynamic Discoveries section | Ava, James | P1 | Medium |
| HP-07 | Label p=0.08 finding appropriately | Lena | P0 | Trivial |
| HP-08 | Fix hardcoded rgba colors for light mode | Tyrell | P1 | Small |
| HP-09 | Consolidate sections (7→5) | Mara, Raj | P2 | Medium |
| HP-10 | Replace emoji icons with SVG glyphs | Tyrell | P2 | Medium |
| HP-11 | Heartbeat animation repositioning | Tyrell, Mara | P2 | Small |
| HP-12 | Elena Voss hero one-liner | Ava | P2 | Small |
| HP-13 | Share card (PULSE-D1) + dynamic OG image | Sofia, James | P2 | Large |
| HP-14 | Recent Chronicle entry cards | Jordan | P2 | Medium |
| HP-15 | SEO: retitle + target keywords | Jordan | P1 | Small |
| BL-01 | "For Builders" page | Raj, Jordan, Sofia | P2 | Large |
| BL-02 | Bloodwork/Labs page | Lena | P2 | Large |
| BL-06 | Monthly Retrospective page | Raj | P3 | Large |
| BL-05 | Segmented Subscriptions | Jordan | P3 | Large |
| GR-01 | Fix subscribe conversion path | Jordan | P1 | Medium |
| GR-02 | Share mechanics on Discoveries + Chronicle | Jordan | P2 | Medium |

---

## PHASE 0: QUICK FIXES (P0) — Single Sprint

### HP-01: Remove duplicate CHARACTER card
**Board**: Mara (UX trust-killer), James (copy-paste artifact)
**File**: `site/index.html`
**What**: The feature discovery cards grid has CHARACTER listed twice — once linking to `/character/` with RPG copy, and again linking to `/character/` with badges copy. Remove the second instance (the one with 🏆 emoji, ~6 lines).
**Find**: The second `<a href="/character/"` block in the feature cards section (the one with `🏆` and text "7-pillar scoring system. Level, tier, milestone badges earned from real data.")
**Action**: Delete the entire `<a>` block (6 lines).
**Acceptance**: Feature card grid has 7 unique cards, no duplicate hrefs.

---

### HP-02: Delete dead CSS (old grid hero)
**Board**: Tyrell (dead weight), James (source confusion)
**File**: `site/index.html`
**What**: The first `<style>` block after the `<link>` tags defines a grid-based `.hero` layout (`grid-template-columns: 1fr 1fr`) that is completely overridden by the BS-02 flexbox `.hero`. Also includes `.hero-left`, `.hero-right`, `.vitals-grid`, `.journey-section`, `.journey-row`, `.hero-name`, `.hero-body`, `.hero-actions`, `.hero-subscribe`, `.subscribe-row`, `.subscribe-input`, and related responsive rules. All dead.
**Action**: Remove the entire first `<style>` block (from `.hero { min-height: 100vh; display: grid;` through the closing `</style>` just before the `<!-- BS-02: Transformation story hero styles -->` comment). ~100 lines.
**Keep**: The `.about-section`, `.sources-grid`, `.source-pill` styles — these are still used. If they're in the same block, extract them before deleting.
**Acceptance**: Page renders identically. No style changes visible. Source is ~100 lines lighter.

---

### HP-03: Restore hero subscribe input
**Board**: Jordan (funnel leak), Sofia (friction)
**File**: `site/index.html`
**What**: The JS references `hero-email` and `hero-subscribe-btn` but these elements don't exist in the HTML — they were removed during a refactor. The CSS classes `.subscribe-row`, `.subscribe-input` exist but have no matching markup.
**Action**: Add a subscribe form inside the hero section, between the "Start here" CTA and the dual-path CTAs:
```html
<!-- Hero subscribe -->
<div class="hero-subscribe" style="max-width:500px;opacity:0;animation:fadeUp 0.6s ease forwards 0.58s;">
  <div class="hero-subscribe-label">Get the weekly signal</div>
  <div class="subscribe-row">
    <input type="email" id="hero-email" class="subscribe-input" placeholder="your@email.com" autocomplete="email">
    <button id="hero-subscribe-btn" class="btn btn--primary" style="font-size:var(--text-xs);white-space:nowrap;padding:var(--space-3) var(--space-5);">Subscribe</button>
  </div>
  <div id="subscribe-msg" class="hero-subscribe-note"></div>
</div>
```
**Verify**: The existing JS subscribe handler at the bottom of the page already wires up `hero-subscribe-btn` click and `hero-email` keydown. Confirm it fires on click.
**Acceptance**: Email input visible in hero. Submit triggers `/api/subscribe` POST. Success/error messages display.

---

### HP-04: Add proper H1 tag
**Board**: Jordan (SEO — Google sees no H1)
**File**: `site/index.html`
**What**: The page has no `<h1>` element. The hero label is a `<p class="hero-label">` and the weight counter uses plain `<span>` elements.
**Action**: Wrap the hero narrative paragraph concept in an H1, or add a visually-hidden H1 for SEO:
```html
<h1 style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;">
  Matthew Walker — Quantified Self Health Experiment: 302 to 185 lbs with AI and 19 Data Sources
</h1>
```
Place immediately after `<section class="hero" id="experiment">`.
**Acceptance**: `document.querySelector('h1')` returns an element. Google can index a meaningful H1.

---

### HP-05: Fix OG tags — current state, not goal
**Board**: Sofia (promise gap — OG says "302 → 185" but he's at ~288)
**File**: `site/index.html`
**What**: The `<meta property="og:description">` says "302 → 185. 19 data sources. 95 AI tools. Every number public." — implies the journey is complete. Same for `twitter:description`.
**Action**: Update to reflect the active journey:
```html
<meta property="og:description" content="One person. 19 data sources. An AI operating system for the body. Tracking a 302→185 lb transformation — every number public, every failure included.">
<meta name="twitter:description" content="One person. 19 data sources. Tracking a 302→185 lb transformation with AI — every number public.">
```
**Note**: When HP-13 (share card) ships, the `og:image` should point to the dynamic share card URL instead of the static `og-image.png`.
**Acceptance**: OG description conveys "in progress", not "completed".

---

### HP-07: Label p=0.08 finding appropriately
**Board**: Lena (doesn't meet significance threshold)
**File**: `site/index.html`
**What**: The "Zone 2 → HRV trend" discovery card shows `r = 0.31 · p = 0.08 · 4 weeks`. At α = 0.05 this is not statistically significant.
**Action**: Either:
- **(A) Label it**: Change the stats line to: `r = 0.31 · p = 0.08 (trending) · 4 weeks` and add subtle styling to indicate it's suggestive but not confirmed.
- **(B) Replace it**: Swap with a significant finding from the intelligence layer. This is the better option if HP-06 (dynamic discoveries) ships soon.
**Recommendation**: Do (A) now as a quick fix, then (B) becomes automatic when HP-06 ships.
**Acceptance**: No non-significant finding is presented alongside significant ones without differentiation.

---

## PHASE 1: HIGH-IMPACT IMPROVEMENTS (P1)

### HP-06: Dynamic Discoveries section
**Board**: Ava (hardcoded = stale), James (endpoint already exists)
**File**: `site/index.html`, `lambdas/site_api_lambda.py`
**What**: The Discoveries section on the home page has three hardcoded correlation cards. These should pull dynamically from the intelligence layer.
**Backend**:
- Add `?featured=true&limit=3` support to the existing `/api/correlations` endpoint in `site_api_lambda.py`
- Featured correlations = top 3 by absolute r-value where `p < 0.05` and `is_featured=true` (or just top 3 significant ones)
- Response shape: `{ correlations: [{ metric_a, metric_b, r, p, n, description, direction }] }`
**Frontend**:
- Replace the hardcoded `<div>` grid in the `#discoveries` section with a JS loader
- Fetch `/api/correlations?featured=true&limit=3` on page load
- Render cards dynamically with the same visual structure
- Show skeleton loading state while fetching
- Fallback: if fetch fails, show the current hardcoded cards (keep as `<noscript>` or hidden fallback)
**Acceptance**: Discoveries section shows live data. Cards update when the correlation engine runs. p-values and r-values are current.

---

### HP-15: SEO — retitle and target keywords
**Board**: Jordan (nobody googles "Matthew Walker data sources")
**File**: `site/index.html`
**What**: Current `<title>` is "Matthew Walker — 19 Data Sources, Real Results". Not searchable.
**Action**:
```html
<title>Quantified Self Weight Loss Experiment — AI Health Tracking with 19 Data Sources | averagejoematt.com</title>
```
Also update `og:title` and `twitter:title`:
```html
<meta property="og:title" content="Quantified Self Experiment — AI-Powered Health Tracking with Real Data">
<meta name="twitter:title" content="Quantified Self Experiment — AI Health Tracking, Every Number Public">
```
**Target keywords**: "quantified self", "AI health tracking", "n=1 health experiment", "weight loss data tracking"
**Acceptance**: Title contains target keywords. OG title is compelling for social sharing.

---

### GR-01: Fix subscribe conversion path (full funnel)
**Board**: Jordan (two paths, one broken)
**Files**: `site/index.html`, `site/assets/js/components.js`
**What**: Multiple subscribe friction points identified.
**Sub-tasks**:

**GR-01a**: Hero subscribe input (covered by HP-03 above)

**GR-01b**: Mid-page sticky subscribe bar
- After user scrolls past the hero, show a slim sticky bar at the bottom:
```html
<div id="sticky-subscribe" style="display:none;position:fixed;bottom:0;left:0;right:0;z-index:100;
  background:var(--surface);border-top:1px solid var(--border);padding:var(--space-3) var(--page-padding);
  display:flex;align-items:center;justify-content:center;gap:var(--space-3);">
  <span style="font-family:var(--font-mono);font-size:var(--text-xs);color:var(--text-muted);">Get the Weekly Signal</span>
  <input type="email" id="sticky-email" class="subscribe-input" placeholder="your@email.com" style="max-width:240px;padding:var(--space-2) var(--space-3);">
  <button id="sticky-subscribe-btn" class="btn btn--primary" style="font-size:var(--text-2xs);padding:var(--space-2) var(--space-4);">Subscribe</button>
</div>
```
- JS: Show when user scrolls past hero section. Hide if already subscribed (check localStorage flag). Wire to same `/api/subscribe` endpoint.
- Dismiss with ✕ button, remember dismissal in localStorage for 7 days.

**GR-01c**: Verify `amj-subscribe` component in components.js renders correctly on home page
- Check that the `<div id="amj-subscribe"></div>` placeholder actually gets populated
- Confirm the component has a working email input and submit button

**Acceptance**: Three subscribe touchpoints: hero, sticky bar, footer component. All wire to `/api/subscribe`.

---

### HP-08: Fix hardcoded rgba colors for light mode
**Board**: Tyrell (hero radial-gradient won't adapt)
**File**: `site/index.html`
**What**: The BS-02 hero has `rgba(46, 169, 143, 0.06)` hardcoded in `.hero::before`. Other hardcoded colors include the heartbeat canvas JS (`#00e5a0`, `#c8843a`, `#ff5252`), stat chip backgrounds, and the "Start here" CTA (`rgba(240,180,41,0.06)`).
**Action**:
- Replace `.hero::before` gradient with CSS variable: `rgba(var(--accent-rgb), 0.06)` (add `--accent-rgb: 46, 169, 143;` to tokens.css if not present, with light-mode override)
- Replace "Start here" CTA hardcoded colors with `rgba(var(--amber-rgb), 0.06)` / `rgba(var(--amber-rgb), 0.15)`
- Heartbeat canvas colors: read from CSS custom properties via `getComputedStyle`
**Acceptance**: Toggle dark/light mode. All colors adapt. No hardcoded rgb values in hero section.

---

## PHASE 2: EVOLUTIONS (P2)

### HP-09: Consolidate sections (7→5)
**Board**: Mara (12-scroll journey on mobile), Raj (cognitive overload)
**File**: `site/index.html`
**What**: Current section flow: Hero → Signals/Brief → What's New → Discoveries → Day 1 vs Today → Quote → Feature Cards → About/Stack → Subscribe. That's 8+ sections.
**Proposed consolidation**:

| Current | → New |
|---------|-------|
| Hero | **Hero** (keep, streamline — see HP-11, HP-12) |
| Signals/Brief (4-quad + AI brief) | **Live Dashboard** (keep as-is, it's strong) |
| What's New + Discoveries | **Merge → "What the Data Found"** — one section with the "What's New" bar as a header, then 3 discovery cards below |
| Day 1 vs Today | **Keep** — move higher, between hero and dashboard |
| Quote | **Remove as standalone section** — embed quote in "About" or hero |
| Feature Cards | **Replace → "3 Moments"** — Raj's recommendation: one curated highlight from Body, Data, and Story domains instead of 8 cards |
| About/Stack | **Keep** (it's the "why" anchor) |

**Net**: Hero → Day 1 vs Today → Live Dashboard → What the Data Found → 3 Moments → About/Stack → Subscribe
**Acceptance**: Mobile scroll depth reduced by ~30%. Each section has a distinct purpose with no redundancy.

---

### HP-10: Replace emoji icons with SVG glyphs
**Board**: Tyrell (emoji conflicts with terminal aesthetic)
**File**: `site/index.html`, potentially `site/assets/icons/` or inline SVGs
**What**: Feature cards use 📊🧙📐🔬🤖🏆🩸🌙 as category icons. The Pulse page already has 8 symbolic SVG glyphs (Scale, Water, Movement, Lift, Recovery, Sleep, Journal, Mind). Extend this design system.
**Action**:
- Create or extract SVG icon set matching the Pulse glyph style: minimal line-art, monochrome, accent-colored on hover
- Map: Habits→📊 replace with heatmap/calendar icon, Character→🧙 replace with shield/level icon, Benchmarks→📐 replace with target icon, Discoveries→🔬 replace with lightbulb/signal icon, Intelligence→🤖 replace with circuit/brain icon, Glucose→🩸 replace with waveform icon, Sleep→🌙 replace with moon/wave icon
- Inline SVGs or reference from `/assets/icons/`
**Acceptance**: No emoji in feature cards. Icons match Pulse glyph visual language. Consistent with dark/light mode.

---

### HP-11: Heartbeat animation repositioning
**Board**: Tyrell (doesn't serve design hierarchy), Mara (visual noise between CTAs)
**File**: `site/index.html`
**What**: The heartbeat canvas sits between stat chips and chronicle teaser — mid-hero, adding noise without new information (HRV/RHR/Recovery already shown elsewhere).
**Options**:
- **(A) Background element**: Move canvas behind the weight counter as a subtle ambient background. Reduce opacity to 30%. Remove the text labels below it.
- **(B) Remove entirely**: The Pulse page now owns the biometric visualization story. The home page doesn't need it.
**Recommendation**: (A) for wow-factor on first visit, but if it complicates the section consolidation (HP-09), go with (B).
**Acceptance**: Heartbeat animation either enhances hero as background ambiance or is cleanly removed with no dead JS.

---

### HP-12: Elena Voss hero one-liner
**Board**: Ava (Elena should be the voice of the home page)
**Files**: `site/index.html`, `lambdas/site_writer.py` (or `public_stats.json`)
**What**: Add a rotating Elena Voss observation to the hero. Something like: *"Week 5: He missed three days and came back anyway. That's the story."*
**Backend**:
- Add `elena_hero_line` field to `public_stats.json` (written by daily brief or weekly digest)
- Content: one sentence, Elena's journalist voice, updated weekly when Chronicle publishes
**Frontend**:
- Display below the progress bar, above stat chips
- Styled as a pull-quote: italic serif, subtle amber border-left, Elena attribution
- Hidden if field is null/empty (graceful degradation)
**Acceptance**: Elena's voice appears on the home page. Updates automatically with each Chronicle publish.

---

### HP-13: Share card (PULSE-D1) + dynamic OG image
**Board**: Sofia (screenshottable moment), James (Lambda + SVG → PNG)
**Files**: New `lambdas/share_card_lambda.py`, `site/index.html` (OG tag update)
**What**: A daily-updated PNG card showing today's date, weight, streak, character level, and an Elena one-liner. Serves as:
1. The social share image when someone shares a link
2. The OG image for all pages (or at least the home page)
3. A "share this" button target on the home page
**Backend**:
- New Lambda: reads `public_stats.json` from S3, renders SVG template, converts to PNG via `sharp` or `Pillow`
- Endpoint: `/api/share_card.png` (or S3 static path `site/share_card.png` updated daily)
- CloudFront cache: 1 hour
**Frontend**:
- Update `og:image` to point to the dynamic card URL
- Add "Share" button on home page that opens share sheet with card URL
**Acceptance**: Share card updates daily. OG image reflects current state. Sharing a link to averagejoematt.com shows today's numbers in the preview.

---

### HP-14: Recent Chronicle entry cards on home page
**Board**: Jordan (home page doesn't link to individual entries)
**Files**: `site/index.html`, `lambdas/site_api_lambda.py` (or `public_stats.json`)
**What**: Show the 3 most recent Chronicle entries as clickable cards on the home page, between the Discoveries section and the About section.
**Backend**: Add `chronicle_recent: [{title, week_num, date, url, excerpt}]` to `public_stats.json` (3 entries)
**Frontend**: Render as a 3-column card grid with week number, title, one-line excerpt, and link
**Acceptance**: Three Chronicle entries visible. Links go to individual week pages. Updates automatically as new Chronicles publish.

---

## PHASE 3: NEW PAGES — BACKLOG (Board-Ranked)

### BL-01: "For Builders" Page [BACKLOG-1]
**Board**: Raj (#1 pick), Jordan (HN wedge), Sofia (highest-value demographic)
**Priority**: P2 — highest-impact backlog item
**URL**: `/builders/` (or `/for-builders/`)
**Concept**: How a non-engineer built an AI health platform with Claude. Patterns, anti-patterns, architecture decisions, cost breakdown. The page that gets shared in tech Slack channels and on Hacker News.
**Sections**:
1. **The Setup**: "I'm a senior director, not an engineer. Here's what I built anyway."
2. **Architecture at a Glance**: Simplified version of the platform page diagram — Lambda count, DynamoDB single-table, S3, cost
3. **The AI Partnership**: How Claude Code sessions work, the board of directors pattern, prompt engineering, MCP tools
4. **Patterns That Work**: Compute→Store→Read, pre-compute pipelines, shared Lambda layers, ADR-driven decisions
5. **What Failed**: Honest list of mistakes — manual deploys before CI/CD, stale data bugs, secret management incidents
6. **The Numbers**: Time invested, AWS cost, lines of code, commits, tools built
7. **Start Building**: CTA to subscribe for builder-focused updates; link to platform page for deep dive
**Dependencies**: None — can be built from existing docs and Matthew's narrative
**Files**: New `site/builders/index.html`, content from `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/COST_TRACKER.md`
**Estimated effort**: Large (full page build, needs Matthew's voice for narrative sections)

---

### BL-02: Bloodwork/Labs Page [BACKLOG-2]
**Board**: Lena (most medically defensible content)
**Priority**: P2
**URL**: `/labs/` (or `/bloodwork/`)
**Concept**: Biomarker tracking over time with optimal ranges (not just "normal"), linked to protocols and supplements. Most credible page on the site.
**Sections**:
1. **Latest Panel**: Most recent blood draw results, date, key markers
2. **Trends Over Time**: Charts showing biomarker trajectories (lipids, metabolic, hormonal, inflammation)
3. **Optimal vs Normal**: Side-by-side showing lab "normal" range vs longevity-optimal range (Attia/Patrick framework)
4. **Protocol Links**: Each biomarker links to the supplement or protocol targeting it
5. **Genome Context**: Where relevant, link SNP data to biomarker interpretation
**Dependencies**: `get_labs` and `search_biomarker` MCP tools already exist. Need `/api/labs` endpoint in site_api_lambda.
**Files**: New `site/labs/index.html`, new route in `lambdas/site_api_lambda.py`
**Estimated effort**: Large (new API endpoint + full page build + data formatting)

---

### BL-06: Monthly Retrospective [BACKLOG-6]
**Board**: Raj (onboarding ramp for new visitors)
**Priority**: P3
**URL**: `/monthly/` (or `/monthly/YYYY-MM/`)
**Concept**: One page per month showing the arc: weight trajectory, character score progression, experiments completed, key discoveries, habit adherence summary. How a new visitor catches up without reading 20+ weekly entries.
**Dependencies**: Weekly Snapshot infrastructure already exists. Monthly is an aggregation layer.
**Estimated effort**: Large (new Lambda for monthly aggregation + page template + archive view)

---

### BL-05: Segmented Subscriptions [BACKLOG-5]
**Board**: Jordan (wait until 200+ subscribers)
**Priority**: P3 — do NOT build yet
**Gate**: Only implement after reaching 200 confirmed subscribers
**Concept**: Let visitors pick which updates they want: sleep findings only, experiment alerts, weekly chronicle, builder updates, everything.
**Estimated effort**: Large (subscriber management overhaul, multiple SES templates, preference UI)

---

## GROWTH STRATEGY TASKS

### GR-02: Share mechanics on Discoveries + Chronicle
**Board**: Jordan (begging for share buttons)
**Files**: `site/index.html` (Discoveries section), `site/chronicle/` templates
**What**: Add per-card share buttons on Discovery correlation cards and per-entry share buttons on Chronicle posts.
**Implementation**:
- Small share icon on each discovery card → opens share sheet with pre-formatted text: "Sleep onset after 11pm correlates with -12% next-day recovery. From @averagejoematt's N=1 experiment: [link]"
- Each Chronicle entry gets a share button with: "Week X of The Measured Life: '[title]' by Elena Voss — [link]"
- Share targets: Copy link, Twitter/X, LinkedIn
**Acceptance**: Every discovery and chronicle entry has a one-click share path.

---

## IMPLEMENTATION ORDER

```
Sprint A (P0 — quick fixes, 1 session):
  HP-01 → HP-02 → HP-04 → HP-07 → HP-05 → HP-03
  Deploy: sync_site_to_s3.sh → invalidate CloudFront

Sprint B (P1 — high impact, 1-2 sessions):
  HP-15 → HP-08 → GR-01 → HP-06
  Deploy: site_api_lambda + sync_site_to_s3.sh

Sprint C (P2 — evolutions, 2-3 sessions):
  HP-09 → HP-10 → HP-11 → HP-12 → HP-14 → HP-13 → GR-02
  Deploy: site_writer + daily_brief + shared layer + site_api + sync site

Sprint D (P2 — backlog pages, 2-3 sessions each):
  BL-01 (For Builders) → BL-02 (Bloodwork/Labs)

Sprint E (P3 — future):
  BL-06 (Monthly Retro) → BL-05 (Segmented Subs, gated on 200 subscribers)
```

---

## DEPLOY PATTERN (for reference)

```bash
# Site HTML changes only:
bash deploy/sync_site_to_s3.sh
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/*" --no-cli-pager

# site_api_lambda changes:
bash deploy/deploy_lambda.sh life-platform-site-api lambdas/site_api_lambda.py

# site_writer changes (shared layer):
bash deploy/p3_build_shared_utils_layer.sh
bash deploy/p3_attach_shared_utils_layer.sh "arn:aws:lambda:us-west-2:205930651321:layer:life-platform-shared-utils:12"
# (update layer version number as needed)

# daily_brief changes:
bash deploy/deploy_lambda.sh daily-brief lambdas/daily_brief_lambda.py
```
