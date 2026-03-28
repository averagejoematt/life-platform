# PRE-LAUNCH OFFSITE — COMPLETE FEATURE LIST
## All Recommendations from Decisions 1–15 · March 27, 2026
### Target: April 1 Go-Live (All items pre-April 1 unless marked Post-launch)

---

## HOW TO USE THIS DOCUMENT

Every recommendation from the offsite board meeting is listed below as an executable feature. Each has:
- **ID**: Decision#-Letter (e.g., 1a, 12c)
- **Category**: Content / Design / Feature / IA / UX / Bug / Growth / Architecture / Technical / Credibility
- **Effort**: Low / Medium / High
- **File(s)**: The primary files to modify
- **Tasks**: Checkbox items for Claude Code execution

Work through by page. Each decision maps to one page/component.

---

## DECISION 1: Navigation Restructure — 6-Section IA
**Files:** `site/assets/js/components.js`, `site/assets/js/nav.js`

### 1a. Update SECTIONS array to 6 sections
- **Effort:** Medium
- [ ] Replace SECTIONS array in `components.js` with new 6-section structure:
  - The Story: Home · My Story · The Mission · Milestones
  - The Evidence: Sleep · Glucose · Nutrition · Training · Inner Life · Benchmarks · Data Explorer
  - The Pulse: Today · The Score · Habits · Accountability
  - The Practice: Stack · Protocols · Supplements · Experiments · Challenges · Discoveries
  - The Platform: How It Works · The AI · AI Board · Methodology · Cost · Tools · For Builders
  - The Chronicle: Chronicle Archive · Weekly Snapshots · Ask the Data · Subscribe
- [ ] Update all section labels and groupings

### 1b. Update mobile bottom nav (5 items + More)
- **Effort:** Low
- [ ] Mobile bottom nav slots: Story | Evidence | Pulse | Chronicle | ☰ More
- [ ] "More" opens full menu with The Practice and The Platform

### 1c. Update BADGE_MAP for new section ownership
- **Effort:** Low
- [ ] Update `nav.js` BADGE_MAP to reflect new section groupings

### 1d. Update READING_PATHS for new flow
- **Effort:** Low
- [ ] Update `nav.js` READING_PATHS for new nav structure

### 1e. Update overlay menu section headings
- **Effort:** Low
- [ ] Update overlay menu to show 6 section headings with new names

### 1f. Test all dropdown rendering
- **Effort:** Low
- [ ] Test desktop dropdown rendering
- [ ] Test mobile dropdown/overlay rendering
- [ ] CloudFront invalidation for JS assets

---

## DECISION 2: Ticker/Marquee Enhancements
**Files:** `site/index.html` (ticker markup), `site/assets/js/components.js` (ticker logic), `lambdas/site_api/` (public_stats)

### 2a. Add directional arrows to all metrics
- **Effort:** Low
- [ ] Compare current value to 7-day avg from `public_stats.trends`
- [ ] Render ↗ ↘ → arrows next to Weight, HRV, Recovery, Streak

### 2b. Add sleep score ticker item
- **Effort:** Low
- [ ] Pull from `public_stats.vitals.sleep_score` or `sleep_efficiency`
- [ ] Format: "SLEEP B+" or "LAST NIGHT 7.2H · 92%"

### 2c. Add Chronicle latest title as clickable ticker item
- **Effort:** Low
- [ ] Pull from `public_stats.chronicle_latest.title`
- [ ] Format: uppercase, link to latest post
- [ ] Example: "LATEST: WEEK 7 — THE WEEK EVERYTHING CLICKED →"

### 2d. Add freshness date to weight display
- **Effort:** Low
- [ ] Format: "287.7 LBS · MAR 27"

### 2e. Reframe streak when < 5 days
- **Effort:** Low
- [ ] If streak < 5, show "T0: {pct}%" instead of "{n}D STREAK"

### 2f. Preserve terminal aesthetic (GUARDRAIL)
- [ ] Keep monospaced, all-caps, staccato rhythm. No full sentences.

### 2g. Protect "DAY N" as lead item (GUARDRAIL)
- [ ] DAY N always leads the ticker

### 2h. Duplicate all new items in ticker's second copy
- **Effort:** Low
- [ ] Update infinite scroll pattern with new ticker items
- [ ] Test ticker scroll speed — more items may need speed adjustment

---

## DECISION 3: Today / The Pulse (`/live/`)
**Files:** `site/live/index.html`, `lambdas/daily_brief/` (narrative expansion)

### 3a. Expand narrative to 2-3 sentences
- **Effort:** Low
- [ ] Update Pulse Lambda narrative prompt to generate 2-3 sentences with editorial voice

### 3b. Add sparkline reference lines + hover states
- **Effort:** Low-Med
- [ ] Add 7-day avg baseline reference line to each sparkline
- [ ] Add hover/tap states showing actual values

### 3c. Expandable detail cards
- **Effort:** Medium
- [ ] Tap/click reveals full breakdown per glyph
- [ ] Sleep: REM/deep/efficiency; Recovery: HRV+RHR+resp rate

### 3d. Add weight trend line to Journey section
- **Effort:** Medium
- [ ] Visual arc Day 1 → present
- [ ] Projected goal date and rate of loss

### 3e. "Since yesterday" delta line
- **Effort:** Medium
- [ ] Show what changed since last visit for return visitors

### 3f. Share button / "Copy today's pulse"
- **Effort:** Low
- [ ] Tweet-sized summary generation
- [ ] Copy-to-clipboard functionality

### 3g. Improve Journal + Mind card treatment
- **Effort:** Medium
- [ ] Show emotion tags, themes, word context instead of bare Open/Closed

### 3h. Visual hierarchy in detail cards
- **Effort:** Low-Med
- [ ] Most notable signal (red, or biggest change) gets elevated treatment

### 3i. Time-of-day awareness in narrative
- **Effort:** Low
- [ ] "Morning read: recovery data in, workout pending" vs "End of day: full picture"

### 3j. Loading skeletons
- **Effort:** Low
- [ ] Replace "Fetching today's signal…" with skeleton card animations

### 3k. Fix Yesterday/Tomorrow disabled state
- **Effort:** Low
- [ ] Tooltip "Available after Day 1", active styling when applicable

### 3l. Throughline link update
- **Effort:** Low
- [ ] Change /story/ to latest Chronicle for daily-to-narrative connection

---

## DECISION 4: Character / The Score (`/character/`)
**Files:** `site/character/index.html`

### 4a. Add plain-language subtitles to gaming terms
- **Effort:** Low
- [ ] "Foundation · Level 2" gets "Early stage: building baseline habits" beneath it
- [ ] XP, tier, level all get one-line translations

### 4b. Shareable trading card
- **Effort:** Medium
- [ ] "Share my card" button
- [ ] Generate social-friendly image (canvas or server-side)

### 4c. Move Level-Up Notification CTA higher
- **Effort:** Low
- [ ] Move from page bottom to immediately below trading card hero

### 4d. Collapse locked badges by default
- **Effort:** Low
- [ ] Lead with earned badges prominently
- [ ] Show "X more to unlock" with expand option

### 4e. Add composite score history chart
- **Effort:** Medium
- [ ] Line chart showing score trajectory over time
- [ ] Requires score_history in API or public_stats

### 4f. Add one narrative moment
- **Effort:** Low
- [ ] Journal pull-quote or personal "why the game metaphor" in The Game section

### 4g. Style pillar cards as RPG stat blocks
- **Effort:** Medium
- [ ] Carry gaming visual metaphor below the hero

### 4h. Acknowledge Mind/Social scoring uncertainty
- **Effort:** Low
- [ ] Brief note about qualitative data sources

### 4i. Expandable "The math" section
- **Effort:** Low
- [ ] Collapsible deep-dive with XP curve formula, weighting details

### 4j. Visual energy continuity
- **Effort:** Medium
- [ ] Increase visual quality in radar/pillar/timeline sections to match trading card hero

### 4k. Structural clarity between Identity/Metrics/Achievements
- **Effort:** Medium
- [ ] Clearer visual separation between the three modes

---

## DECISION 5: Habits / The Operating System (`/habits/`)
**Files:** `site/habits/index.html`

### 5a. Elevate Daily Pipeline
- **Effort:** Medium
- [ ] Move higher or make it the hero
- [ ] Add one-line science rationale per node
- [ ] Add share button

### 5b. Elevate Habit Intelligence
- **Effort:** Low
- [ ] Move heatmap, correlations, day-of-week analysis higher on the page

### 5c. Add narrative warmth
- **Effort:** Low
- [ ] One journal pull-quote or personal "why" about the hardest habit

### 5d. Reframe Discipline Gates language
- **Effort:** Low
- [ ] Add "Streaks reset but progress doesn't" compassionate framing

### 5e. Differentiate zone visual identity
- **Effort:** Medium
- [ ] Zone 1 heavy/anchored, Zone 2 flowing, Zone 3 light/aspirational

### 5f. Fix T1 sparkline bug
- **Effort:** Medium
- [ ] Currently showing duplicated T0 data for T1 habits
- [ ] Fix to use per-habit completion data from API

### 5g. Honest evidence badges
- **Effort:** Low
- [ ] Audit all T0 "strong" ratings
- [ ] Mark personal protocols as "personal protocol"

### 5h. Domain filter
- **Effort:** Medium
- [ ] Cross-tier filtering: "show me all sleep habits" across T0/T1/T2

### 5i. Purpose group descriptions visible by default
- **Effort:** Low
- [ ] Remove collapsed accordions — show micro-copy by default

### 5j. Science rationale in Daily Pipeline nodes
- **Effort:** Low
- [ ] Each step gets a one-liner on why it's sequenced there

### 5k. "Start here" entry ramp for newcomers
- **Effort:** Low
- [ ] "Start here: the 7 that matter" callout before full system unfolds

---

## DECISION 6: Accountability (`/accountability/`)
**Files:** `site/accountability/index.html`

### 6a. Restructure as social contract page
- **Effort:** Medium
- [ ] New arc: Commitment → Evidence → Your Turn
- [ ] Not a dashboard

### 6b. Lead with public commitment quote
- **Effort:** Low
- [ ] Move public commitment to hero position

### 6c. Elevate nudge system to centerpiece
- **Effort:** Medium
- [ ] Show aggregate distribution
- [ ] Social proof ("X nudges this week")
- [ ] Connect nudges to Chronicle responses

### 6d. Reframe data sections as evidence
- **Effort:** Low
- [ ] "Compliance Calendar" → "Did I keep my word?"
- [ ] "90-day arc" → "The unedited record"

### 6e. De-duplicate dashboard data
- **Effort:** Low
- [ ] Remove/simplify state hero and 3-number snapshot
- [ ] Link to Pulse instead

### 6f. Add witness/community counter
- **Effort:** Low-Med
- [ ] "X people are following this experiment"
- [ ] Derive from nudge unique IPs or subscriber count

### 6g. Add comparative context
- **Effort:** Low
- [ ] "Average habit program adherence: 18 days. Matthew: X days."

### 6h. Visual warmth and differentiation
- **Effort:** Medium
- [ ] Page should feel distinct from dashboards — warmer tones

### 6i. Reader reflection option
- **Effort:** Medium
- [ ] Beyond nudge reactions, let visitors share their own experience

### 6j. Nudge → Chronicle feedback loop
- **Effort:** Medium
- [ ] Show how nudges influenced the weekly narrative

### 6k. Social proof in nudge feed
- **Effort:** Low
- [ ] "last nudge: 2 hours ago" / "X nudges this week"

---

## DECISION 7: Milestones / Achievements (`/achievements/`)
**Files:** `site/achievements/index.html`, `site/character/index.html` (de-dup), `site/assets/js/components.js` (nav)

### 7a. Move to The Story nav section
- **Effort:** Low
- [ ] Add Milestones to The Story section in `components.js`

### 7b. De-duplicate from Character page
- **Effort:** Low
- [ ] Character gets compact badge summary + "See all milestones →" link
- [ ] This page becomes canonical badge destination

### 7c. Add narrative vignettes to earned badges
- **Effort:** Medium
- [ ] 2-3 sentences per badge about what the moment meant
- [ ] Link to relevant Chronicle/journal entry

### 7d. Add chronological timeline view
- **Effort:** Medium
- [ ] Toggle between "by category" and "by date"

### 7e. Add share button per earned badge
- **Effort:** Medium
- [ ] Generate shareable card with badge art, date, one-liner

### 7f. Add "progress toward" for locked badges
- **Effort:** Medium
- [ ] "You're 4 lbs from Sub-260" with mini progress bar

### 7g. Add clinical context to weight badges
- **Effort:** Low
- [ ] "Sub-280: below obesity threshold" etc.

### 7h. Move credibility line to subtitle position
- **Effort:** Low
- [ ] "Computed from real data. No self-reporting." becomes unmissable subtitle

### 7i. Fix progress ring framing
- **Effort:** Low
- [ ] Show earned count as positive absolute ("4 earned") not %

### 7j. Badge-earned email notifications
- **Effort:** Medium
- [ ] "Matthew just unlocked Sub-260. Read the story."

### 7k. Enrich badge data model
- **Effort:** Low
- [ ] Add `clinical_context`, `narrative_link`, `vignette`, `progress_current` fields

---

## DECISION 8: Sleep Observatory (`/sleep/`)
**Files:** `site/sleep/index.html`

### 8a. Align to current editorial design pattern
- **Effort:** Med-High
- [ ] Apply Nutrition/Training/Inner Life standard
- [ ] Staggered pull-quotes, monospace headers with trailing dashes
- [ ] 3-column editorial spreads, left-accent rule cards

### 8b. Merge two hero sections
- **Effort:** Low
- [ ] Narrative intro becomes sole hero
- [ ] Gauge rings sit directly below as data payoff

### 8c. Add sleep consistency / social jetlag metric
- **Effort:** Medium
- [ ] Bedtime variance weekday vs weekend with narrative context

### 8d. Add sleep efficiency metric
- **Effort:** Low
- [ ] Actual sleep ÷ time in bed, displayed prominently

### 8e. Add sleep architecture trend chart
- **Effort:** Medium
- [ ] Stacked area (deep/REM/light) over 30 days

### 8f. Weave narrative through data sections
- **Effort:** Medium
- [ ] 1-2 contextual sentences per data section interpreting the numbers

### 8g. Elevate N=1 Rules
- **Effort:** Low
- [ ] Move higher on page or tease early

### 8h. Add protocol adherence loop
- **Effort:** Medium
- [ ] Each protocol shows adherence %, outcome with/without adherence

### 8i. Dynamic pull-quotes
- **Effort:** Med-High
- [ ] Auto-surface most significant correlations as data accumulates

### 8j. Add cross-domain findings
- **Effort:** Medium
- [ ] Sleep → next-day recovery, training quality, mood/cognitive state

### 8k. Measurement agreement note
- **Effort:** Low
- [ ] Explain when Eight Sleep and Whoop scores diverge

### 8l. Chart interactivity
- **Effort:** Medium
- [ ] Hover states, click for breakdown, 90d/all-time time windows

### 8m. Frame three differentiators prominently
- **Effort:** Low
- [ ] Cross-device triangulation, cross-domain correlation, accumulated N=1 rules

---

## DECISION 9: Glucose Observatory (`/glucose/`)
**Files:** `site/glucose/index.html`, `lambdas/site_api/` (meal_responses endpoint)

### 9a. Align to current editorial design pattern
- **Effort:** Med-High
- [ ] Same pass as Sleep (Decision 8a)

### 9b. Merge two hero sections
- **Effort:** Low
- [ ] Narrative intro as sole hero, gauges below

### 9c. Make meal response table dynamic (KILLER FEATURE)
- **Effort:** High
- [ ] API-driven from CGM × MacroFactor cross-reference
- [ ] Sortable, filterable, growing over time

### 9d. Elevate meal table design
- **Effort:** Medium
- [ ] From plain HTML table to editorial card layout
- [ ] Color-coded spike severity, mini glucose curves per meal, share buttons

### 9e. Add daily glucose curve visualization
- **Effort:** Medium
- [ ] Actual 288-reading day plot with meal events overlaid
- [ ] Good day vs bad day comparison

### 9f. Add cross-domain visualizations
- **Effort:** Medium
- [ ] Same meal with good vs bad sleep
- [ ] With vs without post-meal walk
- [ ] Glucose × stress level

### 9g. Add nocturnal glucose patterns
- **Effort:** Medium
- [ ] Dawn phenomenon, overnight stability, sleep architecture × nighttime glucose

### 9h. Add inline definitions/tooltips
- **Effort:** Low
- [ ] TIR, SD, optimal vs standard range

### 9i. Connect genomics to glucose
- **Effort:** Low
- [ ] FADS2/MTHFR variants affecting individual glucose metabolism

### 9j. Dynamic pull-quotes
- **Effort:** Med-High
- [ ] Auto-surface most striking meal comparisons

### 9k. Weave narrative through data
- **Effort:** Medium
- [ ] Continue fear→data→understanding→peace arc through data sections

### 9l. Expand psychological thread
- **Effort:** Low
- [ ] 2-3 sentences on health anxiety and monitoring as resolution

### 9m. Build `/api/meal_responses` endpoint
- **Effort:** High
- [ ] CGM × MacroFactor cross-reference per logged meal

---

## DECISION 10: Nutrition Observatory (`/nutrition/`)
**Files:** `site/nutrition/index.html`, `lambdas/site_api/` (top meals, TDEE endpoints)

### 10a. Add narrative intro
- **Effort:** Low
- [ ] The only observatory without one
- [ ] "Every diet I've ever done worked until it didn't" energy

### 10b. Add Top Meals section
- **Effort:** Medium
- [ ] Most frequently logged meals with macro profile, glucose response grade
- [ ] Protein-per-calorie ranking

### 10c. Add protein distribution visualization
- **Effort:** Medium
- [ ] Per-meal breakdown showing leucine threshold met/missed

### 10d. Add micronutrient section
- **Effort:** Medium
- [ ] Key gaps relative to genomics: choline (550mg+), vitamin D, omega-3, folate

### 10e. Add TDEE adaptation tracking
- **Effort:** Medium
- [ ] MacroFactor adaptive TDEE over time

### 10f. Fix pull-quote duplication
- **Effort:** Low
- [ ] Pull-Quote #2 identical to Glucose page — replace with unique finding

### 10g. Align to editorial design pattern
- **Effort:** Med-High
- [ ] Same pass as Sleep and Glucose

### 10h. Add behavioral trigger analysis
- **Effort:** Medium
- [ ] Cross-reference nutrition misses with sleep, stress, travel

### 10i. Add psychological dimension
- **Effort:** Low
- [ ] Emotional relationship with food acknowledgment

### 10j. Hydration data
- **Effort:** Low
- [ ] Water intake tracking, correlation with energy/recovery

### 10k. Food visuals
- **Effort:** Low
- [ ] Category icons or photos next to top meals

### 10-kitchen. The Kitchen teaser landing page
- **Effort:** Medium
- [ ] Teaser at `/kitchen/` — describes concept, captures subscribers

---

## DECISION 11: Training Observatory (`/training/`)
**Files:** `site/training/index.html`

### 11a. Add CTL/ATL/TSB visualization
- **Effort:** Medium
- [ ] Banister fitness-fatigue model from existing API data

### 11b. Add centenarian benchmark tracker
- **Effort:** Medium
- [ ] Current 1RM vs Attia targets with progress bars

### 11c. Add narrative intro
- **Effort:** Low
- [ ] Matthew's relationship with exercise — boom-bust cycle

### 11d. Add compound lift progress charts
- **Effort:** Medium
- [ ] Squat/deadlift/bench/OHP 1RM over time

### 11e. Add ACWR injury risk indicator
- **Effort:** Low
- [ ] Traffic light with plain-language explanation

### 11f. Activity diversity visualization
- **Effort:** Medium
- [ ] Attia-pillar radar: Zone 2, strength, stability, Zone 5, sport

### 11g. Add HR recovery trend
- **Effort:** Medium
- [ ] Strongest exercise-derived mortality predictor from `get_hr_recovery_trend`

### 11h. Time-of-day training distribution
- **Effort:** Low
- [ ] When does Matthew train? Protocol insight

### 11i. GPS route traces
- **Effort:** Medium
- [ ] Minimalist Strava GPS thumbnails

### 11j. Real-world capability milestones
- **Effort:** Low
- [ ] First 5K, first 20-mile ride, first soccer match

### 11k. Editorial alignment pass
- **Effort:** Med-High
- [ ] Apply current observatory design pattern

### 11l. Zone 2 data source transparency note
- **Effort:** Low
- [ ] Garmin HR zones, no Strava Premium needed

### 11m. Plain-language Banister translations
- **Effort:** Low
- [ ] "Fitness base is building" not "CTL: 5.06"

---

## DECISION 12: Inner Life Observatory (`/mind/`)
**Files:** `site/mind/index.html`

### 12a. Expand narrative intro — site's most personal writing
- **Effort:** Low-Med
- [ ] 3-4 paragraph confessional: what he was avoiding, what it cost, what this represents
- [ ] First person, no hedging — Matthew's most vulnerable writing on the site

### 12b. Restructure page arc: Vulnerability → Commitment → Evidence → Intelligence
- **Effort:** Medium
- [ ] Lead with narrative
- [ ] Then the five commitments (elevated from bottom)
- [ ] Then current data (even sparse)
- [ ] Then intelligence layer preview

### 12c. Reframe data sparsity as the story
- **Effort:** Low
- [ ] Replace "Building this measurement" with honest framing
- [ ] "The data gap IS the data. One journal entry. Zero logged connections."

### 12d. Add cross-domain causal connections
- **Effort:** Medium
- [ ] Sleep → mood, training → anxiety, cortisol → rumination
- [ ] HRV/respiratory rate as physiological correlates of inner state
- [ ] Show causal arrows explicitly

### 12e. Redesign social connection section
- **Effort:** Medium
- [ ] From empty bar chart to intention-first format
- [ ] Who Matthew is trying to reconnect with (anonymized)
- [ ] Murthy threshold as target
- [ ] Data fills in as effort evidence

### 12f. Elevate the five commitments
- **Effort:** Low
- [ ] Move numbered intent items from page bottom to after narrative intro
- [ ] Reframe as personal promises, not measurement protocol

### 12g. Add intelligence layer preview
- **Effort:** Medium
- [ ] Empty frameworks: cognitive pattern radar (CBT), mood-energy divergence axes, sentiment trajectory
- [ ] "This is what the platform will detect as data accumulates"

### 12h. Differentiate visual language from other observatories
- **Effort:** Medium
- [ ] More intimate feel — journal-texture, softer grid, more white space
- [ ] Different typography weight — not a data dashboard

### 12i. Name clinical reality honestly
- **Effort:** Low
- [ ] Anxiety, social withdrawal, imposter syndrome are mental health patterns
- [ ] Connect to evidence-based frameworks (CBT, ACT, PERMA) without pathologizing

### 12j. Add "What this page will become" section
- **Effort:** Low
- [ ] 6-month vision: cognitive pattern tracking, burnout early warning, social trends
- [ ] Gives reader reason to return

### 12k. Make vice streaks feel warmer
- **Effort:** Low
- [ ] One sentence per streak category connecting to the *why*

### 12l. Add journal excerpt section (when data permits)
- **Effort:** Medium
- [ ] AI-surfaced themes, emotional weather, growth signals

### 12m. State the causal hierarchy explicitly
- **Effort:** Low
- [ ] "This pillar doesn't sit alongside the others. It determines the trajectory of all of them."

### 12n. Protect the title (GUARDRAIL)
- [ ] "The pillar I avoided building" — do not change

### 12o. Journal-prompted annotations (POST-LAUNCH)
- **Effort:** High
- [ ] When journal has high emotional content, surface prompted card on page

### 12p. Reader reflection mechanism (POST-LAUNCH)
- **Effort:** High
- [ ] Anonymous structured reflections from visitors

---

## DECISION 13: Benchmarks / The Standards (`/benchmarks/`)
**Files:** `site/benchmarks/index.html`

### 13a. Elevate self-check to page hero
- **Effort:** Medium
- [ ] Reader confronts themselves first — 6 questions, instant letter grades
- [ ] "Before you look at anyone else's numbers — where do you stand?"

### 13b. Add one narrative moment
- **Effort:** Low
- [ ] 2-3 sentences: which benchmark scares him, drives him, where he's failing

### 13c. Add "math of decline" context per physical benchmark
- **Effort:** Low
- [ ] Why 2× bodyweight at 40? 3-8% strength loss per decade after 30
- [ ] The target is the *reserve* that keeps you independent at 85

### 13d. Domain-specific cross-links to observatories
- **Effort:** Low
- [ ] Each domain gets "See the full evidence →" link to its observatory

### 13e. Add importance gradient
- **Effort:** Medium
- [ ] Distinguish "survival benchmarks" (VO2, sleep, social) from "quality benchmarks" (books, gratitude)
- [ ] Visual hierarchy, not alphabetical

### 13f. Shareable self-check results
- **Effort:** Medium
- [ ] "Share your scores" button generates social card with 6 letter grades
- [ ] Privacy-safe (reader data, never stored)

### 13g. Per-benchmark deep-link anchors
- **Effort:** Low
- [ ] Each of 27 benchmarks individually linkable
- [ ] `/benchmarks/#grip-strength` etc.

### 13h. Cognitive-physical crossover note
- **Effort:** Low
- [ ] Strongest cognitive reserve builders are cardiovascular exercise and sleep quality

### 13i. Visual consistency pass on domain headers
- **Effort:** Medium
- [ ] Standardize quality across all 6 domain visuals
- [ ] Dunbar rings set the standard

### 13j. Add "Day 1 vs Now" column
- **Effort:** Medium
- [ ] Three-point: start → current → target
- [ ] Makes the journey visible, not just the gap

### 13k. Separate research layer from personal data layer
- **Effort:** Medium
- [ ] Each card clearly delineates "the research says" from "Matthew's current"
- [ ] Tab, toggle, or visual separation

### 13l. Resolve "Tracking soon" benchmarks
- **Effort:** Low
- [ ] Books, Learning Hours, Gratitude, Generosity, New Skills — 5 with no data
- [ ] Track them or remove them for launch — no placeholders on credibility page

### 13m. Individual benchmark micro-pages (POST-LAUNCH)
- **Effort:** High
- [ ] Each of 27 becomes SEO-optimized page with full context

### 13n. Reader benchmark tracking (POST-LAUNCH)
- **Effort:** High
- [ ] Readers save self-check scores and track over time

---

## DECISION 14: Data Explorer (`/explorer/`)
**Files:** `site/explorer/index.html`

### 14a. Expand curated findings to hero section
- **Effort:** Medium
- [ ] 3-5 editorial features with plain-language titles
- [ ] "Sleep before 10pm predicts 15% higher HRV"
- [ ] r-value as supporting evidence + "so what" sentence

### 14b. Elevate lagged (predictive) correlations
- **Effort:** Low-Med
- [ ] Dedicated section: "What today predicts about tomorrow"
- [ ] Not a filter chip — a headline

### 14c. Default filter to FDR Significant
- **Effort:** Low
- [ ] Change default from "All Pairs" to "FDR Significant"
- [ ] "All Pairs" becomes power-user option

### 14d. Add one narrative anchor
- **Effort:** Low
- [ ] 2-3 sentences: finding that surprised him, changed behavior, still investigating

### 14e. Add "Pick Two Metrics" query mode
- **Effort:** Medium
- [ ] Two dropdowns, compare button, see correlation with interpretation

### 14f. Visual hierarchy by statistical significance
- **Effort:** Medium
- [ ] Strong FDR-significant = larger, more prominent cards
- [ ] Negligible = smaller, muted

### 14g. Close the loop to action
- **Effort:** Medium
- [ ] Each significant correlation links to relevant observatory page
- [ ] "Sleep × HRV" → Sleep Observatory

### 14h. Cross-domain differentiator callout
- **Effort:** Low
- [ ] Explicitly call out that cross-domain findings are what single-tracker apps cannot show

### 14i. Elevate Submit a Finding
- **Effort:** Low
- [ ] From buried form to visible CTA within flow
- [ ] "See a pattern we missed? Tell us."

### 14j. Plan for scale (POST-LAUNCH)
- **Effort:** Medium
- [ ] AI-surfaced curation as pair count grows

### 14k. Consider renaming
- **Effort:** Low
- [ ] "The Connections" / "What Predicts What" / "Cross-Domain Intelligence"

### 14l. Scatter plot visualization (POST-LAUNCH)
- **Effort:** Medium
- [ ] Click a pair, see actual data points plotted with regression line

---

## DECISION 15: Discoveries (`/discoveries/`)
**Files:** `site/discoveries/index.html`, `lambdas/site_api/` (journey_timeline)

### 15a. Narrow scope to scientific discoveries
- **Effort:** Low
- [ ] Remove Weight milestones and Level Ups from this page
- [ ] Keep: AI Findings, Counterintuitive Surprises, Experiment results, Discoveries
- [ ] Weight → Milestones page, Level Ups → Character page

### 15b. Add executive summary at top
- **Effort:** Medium
- [ ] "In N days, platform surfaced X findings, Y investigated, Z changed behavior"
- [ ] Updates dynamically as data accumulates

### 15c. Lead with Surprises
- **Effort:** Low
- [ ] Counterintuitive findings get visual prominence and top position

### 15d. Pre-seed for launch
- **Effort:** Low
- [ ] Day 1 events: baseline measurements, hypothesis set, first experiments
- [ ] Don't ship empty

### 15e. Elevate DISC-7 annotation loop
- **Effort:** Medium
- [ ] Finding → Action → Outcome visually prominent
- [ ] Every finding prompts: "What did I do about this?"

### 15f. Add discovery lifecycle status
- **Effort:** Medium
- [ ] Observed → Investigating → Confirmed → Integrated (or Refuted)
- [ ] Status badge per finding

### 15g. Add time-based chapter groupings
- **Effort:** Medium
- [ ] Monthly or phase-based breaks with summary sentences
- [ ] "Weeks 1-4: Baseline phase — establishing measurement."

### 15h. Add inner life discoveries
- **Effort:** Medium
- [ ] Journal breakthroughs, cognitive pattern shifts, connection milestones
- [ ] Inner Life is the center — discovery timeline must reflect it

### 15i. Clarify relationship to Data Explorer
- **Effort:** Low
- [ ] Cross-link: Explorer surfaces correlation → Discoveries shows what was done
- [ ] "Spotted in the Explorer on March 15 → Became a Discovery on March 22"

### 15j. Add Hypotheses section
- **Effort:** Medium
- [ ] Forward-looking: "Here's what I'm currently testing"
- [ ] Pulls from active experiments + hypothesis engine

### 15k. Add share mechanics per discovery
- **Effort:** Medium
- [ ] Share card per confirmed discovery or counterintuitive finding

### 15l. Rename consideration
- **Effort:** Low
- [ ] "The Lab" / "The Lab Notebook" / "What I've Learned"

### 15m. Add proof-of-concept aggregate metric
- **Effort:** Medium
- [ ] "X% of AI findings led to behavioral change. Y% of experiments produced outcome."

---

## SUMMARY STATISTICS

| Metric | Count |
|--------|-------|
| Total decisions | 15 |
| Total recommendations | 168 |
| Content tasks | ~45 |
| Frontend/Design tasks | ~65 |
| Feature/API tasks | ~35 |
| IA/UX tasks | ~23 |
| Post-launch items | ~8 |
| Guardrails | 4 |

---

## PAGES REMAINING FOR PART 2 CONTINUATION

- [ ] Stack (`/stack/`)
- [ ] Protocols (`/protocols/`)
- [ ] Supplements (`/supplements/`)
- [ ] Experiments (`/experiments/`)
- [ ] Challenges (`/challenges/`)
- [ ] Platform (`/platform/`)
- [ ] The AI / Intelligence (`/intelligence/`)
- [ ] AI Board (`/board/`)
- [ ] Cost (`/cost/`)
- [ ] Methodology (`/methodology/`)
- [ ] Tools (`/tools/`)
- [ ] For Builders (`/builders/`)
- [ ] Chronicle (`/chronicle/`)
- [ ] Weekly Snapshots (`/weekly/`)
- [ ] Subscribe (`/subscribe/`)
- [ ] Ask the Data (`/ask/`)
- [ ] Home page (re-review)
- [ ] Story page (`/story/`)
- [ ] About / Mission (`/about/`)
- [ ] Final prioritization + implementation sequencing

---

_This document is the source of truth for all offsite recommendations. Updated after each session._
