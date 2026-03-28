# PRE-LAUNCH OFFSITE — PART 4 FEATURE LIST
## All Recommendations from Decisions 25–34 + Meta-Discussions · March 27, 2026
### Target: April 1 Go-Live (All items pre-April 1 unless marked Post-launch)

---

## HOW TO USE THIS DOCUMENT

Every recommendation from Part 4 of the offsite board meeting is listed below as an executable feature. Each has:
- **ID**: Decision#-Letter (e.g., 25a, 30-NEW-1)
- **Category**: Content / Design / Feature / IA / UX / Bug / Growth / Architecture / Technical / Credibility / Safety / Legal
- **Effort**: Low / Medium / High
- **File(s)**: The primary files to modify
- **Tasks**: Checkbox items for Claude Code execution

This document appends to the Part 1-3 feature lists (Decisions 1–24, ~338 recommendations).

---

## DECISION 25: Story Page (`/story/`)
**Files:** `site/story/index.html`

### 25a. Fix CTA branding
- **Effort:** Low
- [ ] Change "// the weekly signal" to "// the measured life"
- [ ] Change "Get the data, every week" to "The Measured Life"
- [ ] Update all subscribe-related text to match Decision 22 naming

### 25b. Add social proof to CTA
- **Effort:** Low
- [ ] Add subscriber count display below subscribe form (same pattern as homepage hero)
- [ ] Fetch from `/api/subscriber_count`
- [ ] Show only if count > 50

### 25c. Add reading time
- **Effort:** Low
- [ ] Add "~10 min read" to story header area
- [ ] Position near the kicker/title

### 25d. Add share mechanic
- **Effort:** Low-Med
- [ ] Add page-level share button (copy link + Twitter/X share)
- [ ] Consider per-chapter share with anchor links

### 25e. Add breadcrumb
- **Effort:** Low
- [ ] Add breadcrumb: "The Story > The Story" or simply "The Story"

### 25f. Mobile milestone bar
- **Effort:** Low
- [ ] Add `@media (max-width: 768px)` → `grid-template-columns: repeat(2, 1fr)` for `.milestones`
- [ ] Test on 375px viewport

### 25g. Verify intersection cards
- **Effort:** Low
- [ ] Review 3 intersection cards — are these real events or hypothetical?
- [ ] If hypothetical: rewrite as "What the system is designed to catch" with forward-looking framing
- [ ] If real: add date/context to make them verifiable

### 25h. Empty states for waveform and timeline
- **Effort:** Low
- [ ] Waveform empty: "// the pattern emerges as data accumulates — check back after Week 4"
- [ ] Timeline empty: "// timeline populates as the experiment runs" (already exists — verify it's editorial, not technical)

### 25i. Professional support acknowledgment
- **Effort:** Low
- [ ] Add one sentence near Chapter 2 pull-quote area: "I work with a therapist alongside the data. The platform catches patterns; it doesn't replace professional support."
- [ ] Keep it natural, not clinical

### 25j–25s: See build plan for descriptions (Should-have / Nice-to-have / Post-launch)

---

## DECISION 26: Platform (`/platform/`)
**Files:** `site/platform/index.html`

### 26a. Add narrative intro
- **Effort:** Low
- [ ] Write 2-3 sentence intro connecting to Story page: "The question from the Story page — can a system catch what willpower can't? — led to this."
- [ ] Position above Zone 01 divider

### 26b. Lead with tweetable stats
- **Effort:** Low
- [ ] Move $13/month, 0 engineers, 19 data sources into the header area or immediately below
- [ ] These currently appear in Zone 02 (buried)

### 26c. Expand Tool of the Week
- **Effort:** Medium
- [ ] Show 3-5 tool results, not just 1
- [ ] Each shows: tool name, what it found, why it matters
- [ ] Rename section: "What the platform found" or "What the AI discovered"

### 26d. Add subscribe CTA
- **Effort:** Low
- [ ] Add `amj-subscribe` component OR inline subscribe form
- [ ] Branded "The Measured Life"

### 26e. Soften header subtitle
- **Effort:** Low
- [ ] From "A single-person health intelligence system, built entirely on AWS serverless"
- [ ] To something human: "One person's answer to: what if AI could see the full picture?"

### 26k. Architecture diagram mobile
- **Effort:** Low
- [ ] Add `overflow-x: auto` to SVG container
- [ ] Test on 375px

### 26n. Verify all stats via data-const
- **Effort:** Low
- [ ] Audit page for hardcoded numbers not bound to `data-const`
- [ ] Bind Lambda count, MCP tools, data sources, cost, review count/grade

### 26o. Hub grid updates
- **Effort:** Low
- [ ] Add Builders page link to the 6-card "Explore the Build" grid
- [ ] Verify all links match current nav structure

---

## DECISION 27: Intelligence (`/intelligence/`)
**Files:** `site/intelligence/index.html`

### 27a. Add narrative intro
- **Effort:** Low
- [ ] "I keep relapsing and I can't see why. The intelligence layer exists to catch what I can't."
- [ ] 2-3 sentences, connecting to Story page

### 27b. Elevate Sample Daily Brief
- **Effort:** Low
- [ ] Move Sample Daily Brief section ABOVE the pipeline section
- [ ] This becomes the hero content of the page

### 27c. Reorder page
- **Effort:** Medium
- [ ] New order: narrative intro → Sample Brief → "The 14 systems behind it" → pipeline details
- [ ] Pipeline details become "For the technically curious" at the bottom

### 27e. Label live vs illustrative examples
- **Effort:** Low
- [ ] Cards with API data: tag "// live from today's data"
- [ ] Cards with static examples: tag "// illustrative example"

### 27f. Add N=1 caveats
- **Effort:** Low
- [ ] Metabolic Adaptation Detector: add "preliminary pattern — requires 90+ days for validation"
- [ ] Biomarker Trajectory: clarify "optimal" = Attia ranges, not lab-reference normal
- [ ] Sleep Architecture: add confidence note on threshold

### 27i. Resolve overlap with Platform
- **Effort:** Medium
- [ ] Platform page: reduce intelligence section to a teaser: "See what the AI does → Intelligence"
- [ ] Remove 8 sample tools from Platform page (they duplicate this page)
- [ ] Add throughline link from Platform to Intelligence

### 27j. Fix reading path
- **Effort:** Low
- [ ] Update reading-path-v2 nav to match Build section page order
- [ ] Currently skips Board, Cost, Methodology, Tools

### 27k. Add subscribe CTA
- **Effort:** Low
- [ ] "Get the weekly version of what these systems produce → The Measured Life"

---

## DECISION 28: Cost (`/cost/`)
**Files:** `site/cost/index.html`, other pages with cost references

### 28a. CRITICAL: Reconcile cost numbers
- **Effort:** Medium
- [ ] Pull actual AWS bill for most recent complete month
- [ ] Update Cost page line items to match real numbers
- [ ] Update Platform page cost section to match
- [ ] Update About page cost row to match
- [ ] Update Story page data-moment to match
- [ ] Update Builders page to match
- [ ] All cost figures should reference one source — consider `site_constants.js` for cost values

### 28b. Add breadcrumb
- **Effort:** Low
- [ ] "The Build > Cost"

### 28c. Add reading path nav
- **Effort:** Low
- [ ] Add reading-path-v2 connecting to adjacent Build pages

### 28d. Add narrative intro
- **Effort:** Low
- [ ] "I publish the bill because the enterprise health world obscures costs. Meaningful health intelligence doesn't require a budget."

### 28e. Fix "Why so low?" mobile
- **Effort:** Low
- [ ] Remove `display: none` on `.td-why` at mobile breakpoint
- [ ] Instead: show as a row below each service on small screens, or condensed inline

### 28f. Add wearable cost acknowledgment
- **Effort:** Low
- [ ] Move from footnote to visible callout in competitive comparison area
- [ ] "Infrastructure: $13/month. Wearable subscriptions (Whoop, Eight Sleep, etc.): additional ~$50-80/month — these are health device costs, not platform costs."

---

## DECISION 29: Methodology (`/methodology/`)
**Files:** `site/methodology/index.html`

### 29a. CRITICAL: Fix "365+ Days Tracked"
- **Effort:** Low
- [ ] Change `<div class="method-stat__value">365+</div>` to `<div class="method-stat__value" data-const="journey.days_in">—</div>`
- [ ] Verify site_constants.js populates this correctly

### 29b. Reconcile source cards
- **Effort:** Low
- [ ] Add missing source cards: Strava, Todoist, Blood Pressure, Weather, Travel, DEXA
- [ ] OR: clarify that "19 sources" counts sub-sources differently and explain the mapping

### 29c. Label case study
- **Effort:** Low
- [ ] If from real backfill data: add "// from Matthew's actual data — February-March 2026"
- [ ] If illustrative: add "// illustrative example based on published sleep-HRV research"

### 29d. Add 6th limitation
- **Effort:** Low
- [ ] Add limitation 06: "**The subject is also the engineer.** Confirmation bias in data interpretation is mitigated by the Board of Directors framework, independent editorial review (Elena Voss), and FDR-corrected statistical methods — but cannot be fully eliminated."

### 29e. Add breadcrumb
- [ ] "The Build > Methodology"

### 29f. Add reading path nav
- [ ] Connect to adjacent Build pages

### 29g. Bind all stat strip values
- **Effort:** Low
- [ ] Subject: 1 (static, fine)
- [ ] Data Sources: add `data-const="platform.data_sources"`
- [ ] Daily Metrics: verify or bind
- [ ] Days Tracked: `data-const="journey.days_in"`

---

## DECISION 30: Board (`/board/`)
**Files:** `site/board/index.html`, `lambdas/site_api/` (board_ask endpoint), `config/board_of_directors.json`

### 30a. CRITICAL: Replace personas with BoD fictional advisors
- **Effort:** High
- [ ] Replace the 6-person BOARD_MEMBERS JS array with fictional advisors from BoD config:
  - Dr. Sarah Chen (Training) — inspired by Peter Attia's exercise-as-medicine
  - Dr. Marcus Webb (Nutrition) — inspired by Layne Norton's evidence-first approach
  - Dr. Lisa Park (Sleep) — inspired by Andrew Huberman's protocol-driven neuroscience
  - Dr. James Okafor (Longevity) — inspired by Peter Attia's decade-scale trajectory
  - Coach Maya Rodriguez (Behavioral) — inspired by James Clear + BJ Fogg + Goggins' directness
  - The Chair (Synthesis) — original, the integrating voice
- [ ] Each card shows: character name, domain, "Voice shaped by [inspiration]'s [philosophy]" line
- [ ] Update roster cards HTML to match

### 30b. CRITICAL: Remove real public figures as interactive chatbots
- [ ] Remove James Clear, David Goggins from interactive Q&A
- [ ] Remove "Dr. Elena Vasquez" (doesn't exist in BoD)
- [ ] All interactive personas must be from the BoD fictional advisor set

### 30d. Update /api/board_ask
- **Effort:** Medium
- [ ] Modify API to accept BoD member IDs (sarah_chen, marcus_webb, etc.)
- [ ] Use voice profiles from board_of_directors.json for prompt construction
- [ ] Ensure persona voice, principles, and domains match the config

### 30j. Rewrite demo response
- **Effort:** Medium
- [ ] Write new demo response for "Should I prioritize sleep or exercise?" using the 6 fictional personas
- [ ] Each response channels the "inspired by" energy without impersonating

### 30k. Update roster cards
- **Effort:** Medium
- [ ] Update the `.board-roster__grid` HTML to show real BoD members
- [ ] Include emoji, name, domain, focus description, and "inspired by" line

### 30-NEW-3. Tab management
- **Effort:** Low
- [ ] Remove "Product Board" tab (internal only)
- [ ] Verify if `/board/technical/` exists — if not, remove that tab too OR build a simpler version linking to Builders page

### 30-NEW-4. Write "inspired by" lines
- **Effort:** Low
- [ ] Draft one "Voice shaped by..." line per persona
- [ ] Store in board_of_directors.json as `inspiration` field
- [ ] Render on roster cards and in the selector grid

### 30g. Fix CTA branding
- [ ] "The Measured Life" not "the weekly signal"

### 30h. Add breadcrumb
### 30i. Add reading path nav

---

## DECISION 31: Tools (`/tools/`)
**Files:** `site/tools/index.html`

### 31a. Reframe page header
- **Effort:** Low
- [ ] From: "Tools anyone can use today"
- [ ] To: "These are the same calculations the platform runs on my data every day. Enter your numbers and see how they compare."

### 31b. CRITICAL: Fix Matthew badges on mobile
- **Effort:** Low
- [ ] Remove `display: none` from `.matthew-badge` at mobile breakpoint
- [ ] Show compact inline version: "Matthew: 58 bpm" below the tool title on mobile

### 31c. Fix N=1 checklist misnumbering
- **Effort:** Low
- [ ] Change `// Tool 04 — Getting Started` to `// Tool 07 — Getting Started`

### 31e. Add formula citations
- **Effort:** Low
- [ ] Zone 2: "Formula: Karvonen method (ACSM Guidelines, 11th ed.)"
- [ ] HRV: "Norms: HRV4Training population data, Whoop research"
- [ ] Protein: "Target: leucine threshold MPS research (Morton et al., 2018)"
- [ ] Add as small monospace text below each calculator

### 31f. VO2max uncertainty
- **Effort:** Low
- [ ] Add to VO2max results: "Estimated VO2max from walk/run tests has ±10-15% error. Lab testing (metabolic cart) is the gold standard."

### 31g. Clarify Matthew's VO2max
- **Effort:** Low
- [ ] If estimated: change "~42" to "~42 (estimated from Garmin)"
- [ ] If lab-tested: change to "42 (lab-tested)"

### 31j. Add breadcrumb
### 31k. Add reading path nav

---

## DECISION 32: About (`/about/`)
**Files:** `site/about/index.html`

### 32a. Fix subscribe CTA branding
- **Effort:** Low
- [ ] Change "// the weekly signal" to "// the measured life"
- [ ] Change heading text to match Decision 22

### 32b. Fix test coverage binding
- **Effort:** Low
- [ ] Currently: `<span data-const="platform.test_count">83</span>/<span data-const="platform.test_count">83</span>`
- [ ] Fix: either use two different bindings (passing_count / total_count) or reword to: "<span data-const='platform.test_count'>83</span> tests, all passing"

### 32c. Add breadcrumb
- [ ] "The Story > About"

### 32d. Expand links section
- **Effort:** Low
- [ ] Add 2-3 more cards: Inner Life, Subscribe/The Measured Life, Builders
- [ ] Or show the 5-6 top-level nav sections

---

## DECISION 33: Home Page Re-review (`/`)
**Files:** `site/index.html`

### 33a. Fix subscribe branding everywhere
- **Effort:** Low
- [ ] Hero subscribe label: "The Measured Life" not "Follow from Day 1"
- [ ] Sticky bar: branded consistently
- [ ] amj-subscribe component: verify branding

### 33b. Reduce subscribe touchpoints
- **Effort:** Low
- [ ] Keep: hero subscribe input + amj-subscribe component at bottom
- [ ] Sticky bar: make smarter — only show after significant scroll AND not subscribed, OR remove

### 33c. Curate "What's Inside" cards
- **Effort:** Low
- [ ] Add Inner Life (most differentiated page)
- [ ] Consider adding Training Observatory and/or Chronicle
- [ ] Adjust grid to 6 or 9 cards for clean alignment (currently 7 = uneven bottom row)

### 33d. Prequel banner auto-hide
- **Effort:** Low
- [ ] Add JS: if current date >= April 1 2026, hide prequel banner
- [ ] Or use a config flag in site_constants.js

### 33e. Verify /chronicle/sample/
- **Effort:** Low
- [ ] Check if this URL returns content
- [ ] If not: remove the "See a sample issue →" link from hero subscribe area

### 33f. Audit hardcoded stats → data-const
- **Effort:** Medium
- [ ] Audit every element in `site/index.html` that shows a number
- [ ] Bind all dynamic values to data-const or populate from public_stats.json
- [ ] Ticker values, hero stats, about section, feature card stats

---

## DECISION 34: Builders (`/builders/`)
**Files:** `site/builders/index.html`

### 34a. Fix builder's note
- **Effort:** Low
- [ ] Remove "built by a Senior Director in IT"
- [ ] Replace with: "Built by a non-engineer. Claude handled the code. I handled the architecture, product decisions, and every deploy."

### 34b. CRITICAL: Reconcile all hardcoded stats
- **Effort:** Medium
- [ ] Numbers strip: bind ALL values to data-const (19 data sources and $13 are currently hardcoded)
- [ ] Body text: add `<!-- SYNC: platform.lambdas -->` comments next to all hardcoded numbers in prose
- [ ] Cross-reference with Platform, Intelligence, Cost, About, Story pages
- [ ] Create a single truth document or site_constants.js values for: lambdas, mcp_tools, data_sources, monthly_cost, test_count, review_count, review_grade

### 34-CIO-1. Rewrite Lessons 01, 02, 03
- **Effort:** Medium
- [ ] **Lesson 01 (MCP registration):** Reframe as protocol-level learning. Remove "2 hours before I noticed." Focus: "MCP is a new protocol — the registry integrity pattern I built prevents deployment of unimplemented tools." Position as engineering discipline.
- [ ] **Lesson 02 (S3 sync):** Lead with architectural insight: "When static site files and Lambda-generated files coexist in the same S3 prefix, deployment creates a mixed-ownership problem." Remove the implication of running a destructive command carelessly. Focus on the bucket design pattern.
- [ ] **Lesson 03 (Manual deploys):** Reframe as deliberate velocity trade-off: "I chose manual deploys for velocity in weeks 1-2, accepting the risk for faster iteration. By week 3, the error rate made it clear that even for a solo project, CI/CD isn't optional. Architecture Review #13 formalized this as the top finding." Not an oversight — a conscious trade-off that hit its limit.

### 34-CIO-2. Rewrite Lesson 06
- **Effort:** Low
- [ ] Replace "accidentally deleted a secret / 3 days before I noticed" entirely
- [ ] New lesson: "**Secrets governance requires dependency mapping.** In any Lambda-based system, the relationship between secrets and their consumers isn't visible from the AWS console. ADR-014 established the governance pattern: document which Lambdas consume which secrets, enforce via automated cross-reference, and never bundle secrets unless consumed by the same Lambda set."
- [ ] Lead with the principle. No incident narrative.

### 34-CIO-3. Replace Lesson 08
- **Effort:** Low
- [ ] Remove "considered connecting employer tools" entirely
- [ ] New lesson: "**Personal data systems need explicit domain boundaries.** Health data, behavioral data, and productivity data each belong in separate partitions — even when all three are yours. Cross-contamination creates governance complexity that's trivial to prevent upfront and painful to untangle later. The platform enforces strict data domain boundaries: each source writes to its own partition, and no employer or third-party system is ever ingested."
- [ ] Positions Matthew as someone who designs governance into systems.

### 34-CIO-4. Rewrite builder's note
- [ ] Same as 34a — remove title, use non-engineer framing

### 34-CIO-5. Full CIO audit pass
- [ ] Before publishing: read every sentence on the page and ask "would a CTO/CIO/senior engineer read this and question my judgment?"
- [ ] Verify: no phrases suggesting monitoring gaps, careless commands, unnoticed outages, or basic governance oversights

### 34c. Add breadcrumb
### 34d. Add reading path nav

### 34e. Add builder-relevant CTA
- **Effort:** Low
- [ ] NOT "The Measured Life" health subscription
- [ ] Instead: "If you're building something similar, I'd love to hear about it" + email link
- [ ] Or: "Get build updates" as a separate engagement pathway

### 34f. Add narrative hook
- **Effort:** Low
- [ ] One sentence above section 01: "A non-engineer built this in 5 weeks. Here's the complete blueprint — every decision, every mistake, every lesson."

### 34g. Mobile-responsive "Your First Weekend"
- **Effort:** Low
- [ ] Add `@media (max-width: 768px)` → `grid-template-columns: 1fr` for the 3-column layout

### 34k. Verify data-const bindings
- [ ] Bind "19" data sources to data-const
- [ ] Bind "$13" to data-const
- [ ] Verify Lambda and MCP tool counts match site_constants.js

---

## META: MOBILE AUDIT (M-series)
**Files:** Various, `site/assets/css/base.css`, `site/assets/css/responsive.css`

### M-1. CRITICAL: Real-device QA
- [ ] Test on iPhone 14 (or similar)
- [ ] Test on mid-range Android
- [ ] Pages to test: Home, Story, Platform, Tools, Cost, Board
- [ ] Screenshot and log all issues

### M-2. Fix Tools Matthew badges (= 31b)

### M-3. Fix Cost "Why so low?" column (= 28e)

### M-4. Verify Home hero at 375px
- [ ] Weight counter readable?
- [ ] Subscribe input + button side-by-side or stacked?
- [ ] If crushed: stack vertically

### M-5. Verify Story milestone bar (= 25f)

### M-6. Stack subscribe inputs vertically ≤480px
- **Files:** All pages with subscribe forms (Home, Story, About, Subscribe, amj-subscribe component)
- [ ] Add `@media (max-width: 480px)` → flex-direction: column for subscribe input rows

---

## META: VISUAL DESIGN (VIS-series)
**Files:** `site/assets/css/tokens.css`, `site/assets/css/base.css`, various pages

### VIS-1. Fix subscribe button color
- **Effort:** Low
- [ ] All subscribe/conversion buttons: use `var(--cta)` (coral #ff6b6b) not `var(--c-amber-500)`
- [ ] The `--cta` token exists in tokens.css but subscribe buttons hardcode amber
- [ ] Files to update: Home, Story, About, Subscribe page, amj-subscribe component in components.js

### VIS-2. Align Sleep/Glucose observatories
- **Effort:** High
- [ ] Apply Nutrition/Training/Inner Life editorial pattern: animated SVG gauge rings, staggered pull-quotes with evidence badges, monospace headers with trailing dashes, 3-column editorial data spreads
- [ ] This is a significant design update for 2 pages

### VIS-3. Light mode toggle discoverability
- **Effort:** Low
- [ ] Verify theme toggle exists in nav
- [ ] Make it visible/accessible — currently may be hidden or non-obvious
- [ ] Consider: auto-light-mode on Story and Chronicle pages for long reading

### VIS-4. Bespoke OG images
- **Effort:** Medium
- [ ] Story: weight counter graphic (302 → current → 185)
- [ ] Chronicle: latest installment title card
- [ ] Cost: $13/month stat card
- [ ] Homepage: experiment thesis + weight counter

---

## META: AI SLOP DIFFERENTIATION (SLOP-series)
**Files:** `site/assets/css/tokens.css`, all pages with `//` labels

**ROLLBACK REQUIREMENT:** Matthew wants to be able to rollback all design changes. Implementation pattern:
- Create `tokens-v2.css` with new values alongside `tokens.css`
- Use a CSS custom property toggle or a `<body data-theme-version="v2">` class
- Document the rollback: remove the class or swap the import to revert

### SLOP-1. Change primary accent color
- **Effort:** Medium
- [ ] In tokens.css: create alternative accent color set (e.g., desaturated green #4a9e7a, or warm teal, or amber-gold)
- [ ] Implement as token override that can be toggled
- [ ] Test across all pages — accent color is used in ~200 places
- [ ] **Rollback:** swap tokens back to original green (#00e5a0)

### SLOP-2. Retire // comment labels
- **Effort:** Medium
- [ ] Find all `//` prefixed eyebrow labels across all pages
- [ ] Replace with clean eyebrow text (remove the `//` prefix)
- [ ] KEEP `//` only in: ticker, data-terminal contexts, code examples
- [ ] **Rollback:** re-add `// ` prefix to all eyebrow labels

---

## META: PRE-LAUNCH (PRE-series)
**Files:** Various

### PRE-1. Graceful degradation audit
- **Effort:** Medium
- [ ] Test every page with `public_stats.json` returning 404
- [ ] Fallback text must be editorial: "Data updates daily — check back soon" not "Loading from API…"
- [ ] Subscribe CTAs must work regardless of data load status

### PRE-3. Add 'last updated' timestamps
- **Effort:** Low
- [ ] All "Today" labels: show actual date when data is >24h old
- [ ] Pattern: "as of Mar 27" instead of "Today" when `weight_as_of` is >24h ago
- [ ] Apply to: ticker, hero, Day 1 vs Today, sparklines

### PRE-5. Fix dark mode body text contrast
- **Effort:** Low
- [ ] `--c-text-secondary: #7a9080` → lighten to `#8aaa90` or similar (target ≥4.5:1 on #080c0a)
- [ ] Verify: `#8aaa90` on `#080c0a` = ~4.6:1 ✅
- [ ] Test readability on all pages

### PRE-9. Verify sitemap.xml
- **Effort:** Low
- [ ] Check if `site/sitemap.xml` exists
- [ ] If not: generate one listing all 30+ page URLs
- [ ] Include Chronicle installment URLs

### PRE-10. Verify robots.txt
- **Effort:** Low
- [ ] Check if `site/robots.txt` exists
- [ ] Verify it allows all important pages
- [ ] Include sitemap reference

### PRE-13. Data publication review
- **Effort:** Low (decision, not code)
- [ ] Matthew makes conscious decision about: genome SNP identifiers, specific lab values, supplement adherence rates
- [ ] Document which categories are published at what granularity
- [ ] Consider: genome page shows "MTHFR variant present" vs "MTHFR C677T heterozygous"

---

## CROSS-CUTTING: SUBSCRIBE BRANDING (applies to all pages)
**Files:** All pages with subscribe forms + `site/assets/js/components.js`

### BRAND-1. Unified "The Measured Life" branding
- [ ] **components.js** `buildSubscribeCTA()`: update headline and body text
- [ ] **Home** (`site/index.html`): hero subscribe label, sticky bar
- [ ] **Story** (`site/story/index.html`): CTA section
- [ ] **About** (`site/about/index.html`): subscribe section
- [ ] **Board** (`site/board/index.html`): post-response CTA
- [ ] **Subscribe** (`site/subscribe/index.html`): verify already updated per Decision 22
- [ ] Search all HTML files for "weekly signal" and replace

### BRAND-2. Unified data-const audit
- [ ] Create master list of all referenceable stats
- [ ] Verify `site_constants.js` has: platform.lambdas, platform.mcp_tools, platform.data_sources, platform.monthly_cost, platform.test_count, platform.review_count, platform.review_grade, journey.days_in, journey.start_weight, journey.goal_weight
- [ ] Add any missing values
- [ ] Grep all HTML files for hardcoded numbers that should be bound

---

## PART 4 SUMMARY STATISTICS

| Metric | Count |
|--------|-------|
| Total decisions (Part 4) | 10 (Decisions 25–34) |
| Meta-discussions | 7 |
| Total recommendations (Part 4) | ~210 |
| Must-have items | ~85 |
| Should-have items | ~80 |
| Post-launch items | ~25 |
| Critical items | 8 |
| Guardrails | 1 |

### Running Total (Parts 1-4)
| Metric | Count |
|--------|-------|
| Total decisions | 34 |
| Total recommendations | ~548 |
| Pages reviewed | 30+ |

---

_This document is the Part 4 source of truth. Append to the Part 1-3 feature lists for the complete set._
