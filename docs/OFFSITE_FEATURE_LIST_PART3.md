# PRE-LAUNCH OFFSITE — PART 3 FEATURE LIST
## All Recommendations from Decisions 16–24 + Meta-Discussions · March 27, 2026
### Target: April 1 Go-Live (All items pre-April 1 unless marked Post-launch)

---

## HOW TO USE THIS DOCUMENT

Every recommendation from Part 3 of the offsite board meeting is listed below as an executable feature. Each has:
- **ID**: Decision#-Letter (e.g., 16a, 19-aa)
- **Category**: Content / Design / Feature / IA / UX / Bug / Growth / Architecture / Technical / Credibility / Safety / Operational
- **Effort**: Low / Medium / High
- **File(s)**: The primary files to modify
- **Tasks**: Checkbox items for Claude Code execution

This document appends to the Part 1-2 feature list (Decisions 1–15, 168 recommendations).

---

## META: THE PRACTICE SECTION HIERARCHY
**Files:** All Practice section pages, `site/assets/js/components.js`

### P-1. Add hierarchy explainer to Stack page
- **Effort:** Medium
- [ ] Write lifecycle diagram content: Challenge → Experiment → Protocol → Stack → Discovery
- [ ] Add live counts at each pipeline stage from APIs
- [ ] Position as first section on Stack page, above domain cards

### P-2. Add "what is a protocol?" definition to Protocols page
- **Effort:** Low
- [ ] Write one paragraph: what a protocol is, promotion criteria, review cadence, retirement criteria
- [ ] Add to narrative intro section of Protocols page

### P-3. Add lifecycle badges to Protocol cards
- **Effort:** Low
- [ ] Add "Origin:" field to each protocol — "Experiment #14" or "Published evidence (Attia, 2023)" or "Personal conviction"
- [ ] Render as badge in protocol card header

### P-4. Add lifecycle badges to Experiments
- **Effort:** Low
- [ ] Add "If graduated:" field — "Became Protocol: Zone 2 Cardio" or "Status: Inconclusive"
- [ ] Render on completed experiment cards in The Record

### P-5. Add pipeline visualization
- **Effort:** Medium
- [ ] Design visual: Challenge → Experiment → Protocol → Stack → Discovery
- [ ] Show live counts at each stage from APIs
- [ ] Position on Stack page (hero area)

### P-6. Cross-link every Practice page
- **Effort:** Low
- [ ] Each page header shows "You are here" in the lifecycle
- [ ] Protocols links to source experiments
- [ ] Experiments link to graduated protocols
- [ ] Stack links to everything

### P-7. Make Stack the section landing page
- **Effort:** Low
- [ ] Update `components.js` nav order: Stack → Protocols → Supplements → Experiments → Challenges → Discoveries
- [ ] Stack is first item in The Practice dropdown

### P-SHARED. Build shared pipeline nav component
- **Effort:** Medium
- **Files:** `site/assets/js/components.js` or new shared include
- [ ] Extract `.pipeline-nav` CSS from Protocols page
- [ ] Build JS component that renders on all 6 Practice pages
- [ ] Highlight current page with active state
- [ ] Show lifecycle arrows between stages
- [ ] Place below breadcrumb, above page content

---

## META: STRATEGIC ENGAGEMENT MODEL
**Files:** `site/subscribe/index.html`, various

### 22-S1. ONE subscription at launch (GUARDRAIL)
- [ ] Subscription product name: "The Measured Life"
- [ ] Single weekly email containing: Board data signal + Elena's narrative + anomaly highlights

### 22-S2. Mention future channels as coming attractions
- **Effort:** Low
- [ ] Add to subscribe page: "Coming soon: The Kitchen — weekly AI-generated meal prep from real data"

### 22-S5. Build "Ask Elena" submission mechanic
- **Effort:** Medium
- **Files:** `site/chronicle/index.html` or `site/ask/index.html`, `lambdas/site_api/`
- [ ] Text field + optional email + submit button
- [ ] Backend: write to DynamoDB `ask_elena` partition
- [ ] Scope disclaimer: "Questions about the experiment. Not personal health advice."
- [ ] Moderation: Matthew reviews queue, Elena incorporates selected submissions

### 22-S6. Add submission scope disclaimer
- **Effort:** Low
- [ ] "Questions about the experiment and the data. Elena cannot provide personal health advice."
- [ ] Display on submission form

---

## DECISION 16: Supplements / The Pharmacy (`/supplements/`)
**Files:** `site/supplements/index.html`, `lambdas/site_api/` (supplement data)

### 16a. Add narrative intro
- **Effort:** Low
- [ ] Write Matthew's supplement journey — "I used to take nothing. Then everything. Now what the data justifies."
- [ ] Position above the "What you get" stats

### 16b. Add adherence data to page
- **Effort:** Medium
- [ ] Fetch from supplement log API on page load
- [ ] Display per-supplement adherence % on each card
- [ ] Add overall stack adherence stat to hero

### 16c. Add daily timing timeline
- **Effort:** Medium
- [ ] Visual schedule: AM stack (with meal) → Pre-training → PM stack (before bed)
- [ ] Similar concept to Daily Pipeline on habits page
- [ ] Show which supplements go in each time slot

### 16d. Resolve phantom supplements
- **Effort:** Low
- [ ] Determine status of Lion's Mane, Cordyceps, Reishi — actively taking or not?
- [ ] If not taking: remove from registry or mark as "Paused" with date and reason
- [ ] If taking: start logging via `log_supplement`

### 16e. Close the loop on 2-3 supplements with lab data
- **Effort:** Medium
- [ ] Omega-3 → show TG/HDL ratio from lab draws
- [ ] Vitamin D → show 25-OH-D level from lab draws
- [ ] Creatine → show DEXA lean mass trend
- [ ] Populate "What I'm watching" fields with actual data, not just promises

### 16f. Make registry API-driven
- **Effort:** Medium
- [ ] Move SUPP_REGISTRY from hardcoded JS to S3 config or API endpoint
- [ ] Merge with live adherence data at render time
- [ ] Enable dose changes without editing HTML

### 16g. Add cost transparency
- **Effort:** Low
- [ ] Monthly cost per supplement in card
- [ ] Total monthly stack cost in hero stats

### 16h. Elevate genome section
- **Effort:** Medium
- [ ] Move "Why Genome-Informed?" section higher on page
- [ ] Cross-reference more than 3 SNPs — map all supplement-relevant variants
- [ ] Make genome badge on cards more prominent

### 16i. Add supplement tier hierarchy
- **Effort:** Low
- [ ] Visual labels: Tier 1 (essential: creatine, protein, omega-3, D3, electrolytes) / Tier 2 (supporting) / Tier 3 (experimental)
- [ ] Norton's point: not all supplements are equal

### 16j. Add stack evolution timeline
- **Effort:** Medium
- [ ] When each supplement was added/removed and why
- [ ] "Started creatine Day 1. Added sleep stack Week 3. Paused Reishi Week 6 — no signal."

### 16k. Cross-link to experiments
- **Effort:** Low
- [ ] Supplements that are N=1 experiments link to experiment entry
- [ ] "This supplement is an active experiment → see results"

### 16l. Add synergy visualization
- **Effort:** Medium
- [ ] Show how sleep stack, deficit protection stack, longevity stack work as systems
- [ ] Visual connections between supplements in same synergy group

### 16m. Share mechanics
- **Effort:** Low
- [ ] Share button for honest assessment section
- [ ] Share button for individual supplement cards
- [ ] Generate social card with supplement name + evidence rating + personal take

### 16n. Editorial design alignment
- **Effort:** Med-High
- [ ] Add pull-quotes between card groups
- [ ] Add monospace headers with trailing dashes
- [ ] Add narrative moments between sections

### 16o. Fix breadcrumb
- **Effort:** Low
- [ ] Change from "Method > The Pharmacy" to "The Practice > The Pharmacy"

### 16p. Clarify relationship to Stack page
- **Effort:** Low
- [ ] Stack links to Supplements as drilldown
- [ ] Supplements links back to Stack as context
- [ ] Avoid content duplication

### 16q. No "Considering" section (GUARDRAIL)
- [ ] Route genome-suggested-but-not-started supplements as 1-2 line note in Genome section
- [ ] Full "considering" list → Experiments page as upcoming hypotheses

### 16r. Add source links to "What the science says"
- **Effort:** Medium
- [ ] Extend science array entries from strings to objects: `{text, sources: [{title, url, stance: 'supports'|'challenges'}]}`
- [ ] 2 links max per supplement: 1 supporting, 1 challenging
- [ ] PubMed/Cochrane/ISSN only — no blogs
- [ ] Inline citation numbers, expandable reference panel
- [ ] Start with 5 strong-evidence supplements, backfill post-launch

---

## DECISION 17: Protocols (`/protocols/`)
**Files:** `site/protocols/index.html`, `lambdas/site_api/`

### 17a. Add narrative intro with protocol definition
- **Effort:** Low
- [ ] "A protocol is what I'm operating now. It earned its place through evidence."
- [ ] Include promotion criteria, review cadence (quarterly), retirement criteria

### 17b. Add origin/provenance per protocol card
- **Effort:** Low
- [ ] Add "Origin:" field: "Experiment #14 (proved out March 2026)" or "Published literature (Seiler 80/20)"
- [ ] Render as metadata row on each card

### 17c. Make outcome snapshot dynamic
- **Effort:** Medium
- [ ] Replace static HTML values with API-loaded data
- [ ] Use same endpoints as protocol cards for consistency

### 17d. Render pipeline nav
- **Effort:** Low
- [ ] Use shared P-SHARED component
- [ ] Highlight "Protocols" as active

### 17e. Define signal states
- **Effort:** Low
- [ ] Add legend: "Positive: data confirms working. Pending: insufficient data. No signal: not enough time."
- [ ] Position near top or as tooltip per card

### 17f. Add science rationale per protocol
- **Effort:** Low
- [ ] One line on mechanism: "Zone 2: builds mitochondrial density and fat oxidation capacity"

### 17g. Add protocol tier/weight
- **Effort:** Low
- [ ] Foundation protocols (sleep, Zone 2) vs measurement (CGM) vs intervention (IF)
- [ ] Visual hierarchy reflects importance

### 17h. Move vice tracking to Accountability
- **Effort:** Low
- [ ] Remove vice section from Protocols page
- [ ] Add cross-link: "See discipline streaks → Accountability"

### 17i. Add review cadence and retirement criteria
- **Effort:** Low
- [ ] "Reviewed every 90 days. Negative or absent signal for 90 days → paused or retired."

### 17j. Elevate one pull-quote
- **Effort:** Low
- [ ] Pick strongest "why I do this" from inside a card
- [ ] Pull out as page-level editorial element

### 17k. Add protocol history section
- **Effort:** Medium
- [ ] Timeline: "Sleep: started Week 1. Zone 2: started Week 2. IF: graduated from experiment Week 4."

### 17l. Fix breadcrumb
- **Effort:** Low
- [ ] "Method > Protocols" → "The Practice > Protocols"

### 17m. Cross-link to observatory pages
- **Effort:** Low
- [ ] Zone 2 → Training Observatory. Sleep → Sleep Observatory. Each protocol → its domain.

---

## DECISION 18: Stack (`/stack/`)
**Files:** `site/stack/index.html`

### 18a. Add narrative intro + system explanation
- **Effort:** Low
- [ ] "I run my health like a lab. Here's the system."
- [ ] Explain lifecycle: Challenge → Experiment → Protocol → Stack → Discovery

### 18b. Add lifecycle pipeline visualization
- **Effort:** Medium
- [ ] Visual diagram with live counts: "4 challenges · 3 experiments · 6 protocols · X discoveries"
- [ ] Position above domain cards

### 18c. Reorder page structure
- **Effort:** Low
- [ ] (1) Narrative intro → (2) Pipeline visualization → (3) Domain cards → (4) Reading order

### 18d. Reorder "Go Deeper" links
- **Effort:** Low
- [ ] Lifecycle order: Protocols → Supplements → Experiments → Challenges → Discoveries → Habits

### 18e. Add domain-level signal indicators
- **Effort:** Medium
- [ ] Prominent red/yellow/green per domain for at-a-glance scanning
- [ ] Currently only inherits from first protocol

### 18f. Add stack evolution timeline
- **Effort:** Medium
- [ ] "Week 1: 2 protocols. Week 4: added IF. Week 6: IF graduated to protocol."

### 18g. Add data source integration map
- **Effort:** Medium
- [ ] Visual showing 19 data sources flowing into the platform
- [ ] Teaser for Platform/How It Works page

### 18h. Clarify "Details →" interaction
- **Effort:** Low
- [ ] Label as "See on Protocols page →" or make inline expansion

### 18i. Add credibility statement
- **Effort:** Low
- [ ] "Tracked by 19 independent data sources. No self-reporting. Every claim verifiable."

### 18j. Refine hero subtitle
- **Effort:** Low
- [ ] From description to story: "The complete operating system for one human health transformation"

### 18k. Render pipeline nav
- **Effort:** Low
- [ ] Use shared P-SHARED component, highlight "Stack"

### 18l. Visual hierarchy by data richness
- **Effort:** Medium
- [ ] Domains with deep data look visually richer than sparse domains

### 18m. Add "what's new this week" callout
- **Effort:** Medium
- [ ] Surface most recent protocol change, experiment result, or challenge completion

### 18n. Fix breadcrumb
- **Effort:** Low
- [ ] "The Practice > The Stack"

---

## DECISION 19: Experiments / The Lab (`/experiments/`)
**Files:** `site/experiments/index.html`, `lambdas/site_api/`

### 19a. Add narrative intro
- **Effort:** Low
- [ ] "Why am I experimenting on myself?" — what N=1 reveals that population studies can't

### 19b. Start 1-2 experiments before launch
- **Effort:** Low (Operational)
- [ ] Use `create_experiment` MCP tool to formally start at least one experiment
- [ ] Pick foundational: sleep stack compliance, creatine timing, or top-voted library experiment

### 19c. Improve empty state copy
- **Effort:** Low
- [ ] Mission Control: "The lab opens April 1. Vote below to decide what runs first."
- [ ] Record: "No results yet. Every experiment — including failures — published here in full."

### 19d. Add lifecycle connection to Protocols
- **Effort:** Low
- [ ] "Experiments that prove out become Protocols → See what survived"

### 19e. Add "If successful, this becomes:" field
- **Effort:** Low-Med
- [ ] Per experiment: new Protocol, new Habit, Supplement addition, or Stack change
- [ ] Gives experiments stakes

### 19f. Add "launching next" card in Mission Control
- **Effort:** Medium
- [ ] When no experiments active, show top-voted as "Coming next" preview

### 19g. Add curated "Start here" shortlist
- **Effort:** Low
- [ ] 3 recommended experiments above the full 52-experiment library

### 19h. Elevate voting social proof
- **Effort:** Low
- [ ] Show vote count + follower count prominently: "47 votes · 12 following"

### 19i. Add launch timeline/roadmap
- **Effort:** Low
- [ ] "Top-voted experiments launch in batches. Next batch: Week 2."

### 19j. Strengthen methodology confidence
- **Effort:** Low
- [ ] Add positive framing: why N=1 with 19 dense data sources produces meaningful signal

### 19k. Link source citations
- **Effort:** Medium
- [ ] Podcast citations link to episode. Study citations link to PubMed.

### 19l. Distinguish evidence-validated vs genuinely unknown
- **Effort:** Low
- [ ] Split library: "Should work (strong evidence)" vs "Discovery zone (unknown)"

### 19m. Differentiate behavioral vs measurable UI
- **Effort:** Low
- [ ] Behavioral experiments: different card accent or icon vs measurable

### 19n. Verify library-to-MCP experiment pipeline
- **Effort:** Medium
- [ ] When library experiment "started" → creates MCP experiment
- [ ] When MCP experiment completes → library entry updates

### 19o. Render pipeline nav
- **Effort:** Low
- [ ] Shared component, highlight "Experiments"

### 19p. Fix breadcrumb
- **Effort:** Low
- [ ] "The Practice > Experiments"

### 19q. Add "Run your own" protocol export
- **Effort:** Low
- [ ] Pre-seed template so it's ready when first experiment completes

### 19r. Add "How the library grows" explainer
- **Effort:** Low
- [ ] "AI monitors journals + podcasts → Board reviews for safety/testability → enters library"
- [ ] Name specific sources: PubMed alerts, Huberman Lab, The Drive, etc.

### 19s. Add "Recently added" badges
- **Effort:** Low
- [ ] "New" badge with date added and source on recent library tiles

### 19t. No downvotes (GUARDRAIL)
- [ ] Keep voting aspirational and upvote-only

### 19u. Add "Suggest an experiment" form
- **Effort:** Medium
- [ ] One text field + optional source link + optional pillar tag
- [ ] Goes to Board review queue

### 19v. Add private "Flag for review" option
- **Effort:** Low
- [ ] For safety/methodology concerns → goes to Matthew/Board queue, not public

### 19w. Library tiles: inline expand on click
- **Effort:** Medium
- [ ] Tap to reveal full hypothesis, mechanism, source, expected metrics, vote CTA
- [ ] Don't navigate away — preserve scroll position

### 19x. Keep detail page as deep-link
- **Effort:** Low
- [ ] `/experiments/detail/?id=X` stays for sharing/SEO
- [ ] Primary interaction is inline, not navigation

### 19y. Add "What we'd learn" to library tiles
- **Effort:** Low-Med
- [ ] One line in plain language below description
- [ ] "Could reveal the optimal creatine timing during a caloric deficit"

### 19z. Add expected outcome with honest magnitude
- **Effort:** Low-Med
- [ ] "Expected: 5-15% reduction in glucose spike" tied to evidence tier
- [ ] Strong = confident range. Emerging = "genuinely unknown"

### 19-aa. Show monitored sources list
- **Effort:** Low
- [ ] Section listing every journal, podcast, newsletter monitored
- [ ] Each with name, type, URL, date added

### 19-ab. "Suggest a source" form
- **Effort:** Low
- [ ] Readers recommend journals/podcasts to add
- [ ] Also allow "flag a source" for quality concerns
- [ ] Goes to Board review

### 19-ac. Source provenance on library tiles
- **Effort:** Low
- [ ] Show when added + which source + clickable link to original

### 19-ad. Evidence tier color accent on tiles
- **Effort:** Low
- [ ] Left-border: green (strong), amber (moderate), muted (emerging)
- [ ] Same pattern as Supplement cards

### 19-ae. Pillar icon as visual anchor on tiles
- **Effort:** Low
- [ ] Prominent pillar icon (☾/◎/⚘/◈/etc.) per tile

### 19-af. Evidence ring mini-visual
- **Effort:** Low
- [ ] Small confidence ring reusing Supplements `ringSVG` pattern

### 19-ag. Differentiate measurable vs behavioral tiles
- **Effort:** Low
- [ ] Measurable: data/chart micro-icon. Behavioral: check/habit icon.

### 19-ah. Richer visual in expanded state
- **Effort:** Medium
- [ ] Mini experiment design diagram: Baseline → Intervention → Measurement

### 19-ai. "Suggest an experiment" low-friction form
- **Effort:** Medium
- [ ] One text field + optional source + optional pillar
- [ ] Board shapes idea into formal experiment design

### 19-aj. "Community Suggested" badge
- **Effort:** Low
- [ ] Library tiles from reader suggestions get visible badge
- [ ] Attribution without personal info

---

## DECISION 20: Challenges / The Arena (`/challenges/`)
**Files:** `site/challenges/index.html`

### 20a. Add narrative intro
- **Effort:** Low
- [ ] Arena energy: "What am I daring myself to do?"

### 20b. Start 1 challenge before launch
- **Effort:** Low (Operational)
- [ ] Activate one challenge so hero zone has live check-in on Day 1
- [ ] Pick: 7-day step challenge or 7-day journal challenge

### 20c. Elevate Experiments vs Challenges distinction
- **Effort:** Low
- [ ] Move from collapsed methodology at bottom to visible callout near top
- [ ] "Experiments are science. Challenges are action."

### 20d. Add duration and difficulty filters
- **Effort:** Low-Med
- [ ] Duration buttons: 7-day / 14-day / 30-day
- [ ] Difficulty buttons: Easy / Medium / Hard
- [ ] Add to existing category filter bar

### 20e. Add "Board Recommends" curated section
- **Effort:** Low
- [ ] Board's top 5-10 picks highlighted above the full grid
- [ ] Prevents social/mental challenges from being buried

### 20f. Add share mechanic per tile
- **Effort:** Medium
- [ ] Share button in detail modal
- [ ] Generate social card: icon + name + "I'm taking the X challenge"

### 20g. Add "I'm doing this too" counter
- **Effort:** Medium
- [ ] Anonymous participation counter: "8 people doing this now"
- [ ] API endpoint to track + display

### 20h. Add challenge-to-experiment graduation badge
- **Effort:** Low
- [ ] "→ Graduated to Experiment #X" on completed challenge tiles

### 20i. Add mechanism one-liner to detail modal
- **Effort:** Low
- [ ] WHY it works, not just what to do: "Walking increases BDNF, improves glucose disposal"

### 20j. Visual differentiation for tile states
- **Effort:** Medium
- [ ] "Hot" badge for high-voted
- [ ] "Board pick" highlight
- [ ] "Previously attempted" indicator
- [ ] "Graduated to experiment" badge

### 20k. Add expected metric impact
- **Effort:** Low
- [ ] "This challenge targets: sleep score, HRV"
- [ ] Visible on tile footer or in detail modal

### 20l. Render pipeline nav
- **Effort:** Low
- [ ] Shared component, highlight "Challenges"

### 20m. Fix breadcrumb
- **Effort:** Low
- [ ] "The Practice > Challenges"

### 20n. Fix hero eyebrow
- **Effort:** Low
- [ ] "The Science" → "The Practice"

### 20o. Enrich detail overlay
- **Effort:** Medium
- [ ] Add: metric impact, difficulty curve, whether Matthew has attempted, related experiments

### 20p. Reader challenge tracking (POST-LAUNCH)
- **Effort:** High
- [ ] Visitors start their own challenge, track check-ins, see completion record

---

## DECISION 21: Chronicle (`/chronicle/`)
**Files:** `site/chronicle/index.html`, `site/journal/posts.json`

### 21a. Latest installment as page hero
- **Effort:** Medium
- [ ] Newest dispatch gets hero treatment: big title, pull-quote, reading time, "Read →"

### 21b. Upgrade post list to editorial cards
- **Effort:** Medium
- [ ] Larger title typography
- [ ] Prominent stats line
- [ ] Content badges (Board Interview, Lab Results, etc.)
- [ ] Reading time indicator

### 21c. Add phase/season groupings
- **Effort:** Low
- [ ] "Prequels (Weeks −4 to −1)" → "Season 1: The First Month" → etc.
- [ ] Visual chapter breaks with phase headers

### 21d. Reorder for returning visitors
- **Effort:** Low
- [ ] Latest hero → archive list → series intro at bottom (or collapsible)

### 21e. Add content/theme badges
- **Effort:** Low
- [ ] "Board Interview" · "Lab Results" · "CGM Data" · "Journal Excerpt" · "Milestone" · "Setback"
- [ ] Add to `posts.json` per entry

### 21f. Per-installment OG images
- **Effort:** Medium
- [ ] Each post generates social card: week number, title, key stat

### 21g. Narrative progression indicator
- **Effort:** Medium
- [ ] Visual arc: progress bar or mini-timeline with milestones

### 21h. Cross-link Chronicle siblings
- **Effort:** Low
- [ ] "See the raw data → Weekly Snapshots"
- [ ] "Ask about any week → Ask the Data"
- [ ] "Never miss an installment → Subscribe"

### 21i. Explain Chronicle vs Weekly Snapshots
- **Effort:** Low
- [ ] "The Chronicle is Elena's narrative. The Weekly Snapshot is the raw data. Same week, two views."

### 21j. Fix URL pattern inconsistency
- **Effort:** Low
- [ ] Standardize: `week-minus-3` not `week-03` for prequel weeks
- [ ] Or adopt consistent slug pattern before more posts ship

### 21k. Use shared ticker component
- **Effort:** Low
- [ ] Replace copy-pasted ticker with shared component from homepage

### 21l. Add "binge read" entry point
- **Effort:** Low
- [ ] Prominent "Start from the beginning →" styled like starting a book

### 21m. Transformation timeline visualization (POST-LAUNCH)
- **Effort:** High
- [ ] Weight curve + milestone markers + each installment as data point

### 21n. Thematic tagging (POST-LAUNCH)
- **Effort:** Medium
- [ ] Themes: "loneliness," "food relationship," "data anxiety," "breakthrough"

### 21o. Fix breadcrumb
- **Effort:** Low
- [ ] "The Chronicle > Archive"

### 21p. Elevate title typography
- **Effort:** Low
- [ ] Larger, bolder titles — they ARE the visual

### 21q. Add "Previously on" connection
- **Effort:** Low
- [ ] Each card shows thread to next: "Previously: The Empty Journal → Next: The DoorDash Chronicle"

---

## DECISION 22: Subscribe (`/subscribe/`)
**Files:** `site/subscribe/index.html`, `lambdas/email-subscriber/`

### 22a. Resolve naming
- **Effort:** Low
- [ ] Subscription = "The Measured Life" (not "The Weekly Signal")
- [ ] Update all references: page title, hero, form, meta tags

### 22b. Reduce form to email only
- **Effort:** Low
- [ ] Remove "What brings you here?" from main form
- [ ] Keep "How'd you find this?" as single optional field
- [ ] Move motivation question to post-subscribe welcome email

### 22c. Add social proof
- **Effort:** Low
- [ ] Dynamic subscriber count: "Join X people following the experiment"
- [ ] Pull from subscriber count API or DynamoDB scan

### 22d. Build post-subscribe experience
- **Effort:** Medium
- [ ] Rich confirmation page with links to 4 prequels + Story page
- [ ] Automated welcome email: personal note from Matthew, prequel links, "what to expect"
- [ ] Optional single-question survey: "What brings you here?"

### 22e. Clarify content package
- **Effort:** Low
- [ ] Explicit: ONE email containing data signal + Elena's narrative + anomaly highlights
- [ ] Not three separate emails

### 22f. Add previous installment titles
- **Effort:** Low
- [ ] "Previous installments: Before the Numbers · The Empty Journal · The DoorDash Chronicle · The Interview"
- [ ] Each links to full piece

### 22g. Add email preview mock-up
- **Effort:** Medium
- [ ] Visual showing what the actual email looks like
- [ ] "This is what lands in your inbox every Wednesday"

### 22h. Elevate integrity promise
- **Effort:** Low
- [ ] "No affiliate links. No ads. No sponsorships. Just the experiment."
- [ ] From bullet to standalone visual element — banner or badge

### 22i. Name Board advisors
- **Effort:** Low
- [ ] "Analysis from Dr. Sarah Chen (sports science), Dr. Lisa Park (sleep)..." etc.
- [ ] Replace generic "6 advisors" with specific names

### 22j. Add timing/urgency
- **Effort:** Low
- [ ] "Week 1 ships after April 1" prominently displayed

### 22k. Cross-link Chronicle siblings
- **Effort:** Low
- [ ] "While you wait: explore the archive →" / "See weekly data →"

### 22l. Verify "See a sample issue" link
- **Effort:** Low-Med
- [ ] Does `/chronicle/sample/` exist? If not: build preview or remove link

### 22m. Add RSS visibility
- **Effort:** Low
- [ ] "Prefer RSS? Subscribe via feed →" with link to `/rss.xml`

### 22n. Fix breadcrumb
- **Effort:** Low
- [ ] "The Chronicle > Subscribe"

---

## DECISION 23: Weekly Snapshots (`/weekly/`)
**Files:** `site/weekly/index.html`, new Lambda, `lambdas/site_api/`

### 23a. Build weekly snapshot Lambda
- **Effort:** High
- [ ] Lambda runs every Sunday night
- [ ] Writes frozen snapshot to DynamoDB: weight avg, HRV avg, sleep avg, recovery avg, pillar scores, adherence rates, day grades, notable events
- [ ] One record per week, immutable

### 23b. Build `/api/weekly_snapshot?week=X` endpoint
- **Effort:** Medium
- [ ] Returns historical data for a specific week from DynamoDB
- [ ] Falls back to empty state if no record exists

### 23c. Add week-over-week deltas
- **Effort:** Low
- [ ] Every metric shows change: "287.7 lbs (−1.2)"
- [ ] Delta CSS classes already exist — populate them

### 23d. Add heatmap legend
- **Effort:** Low
- [ ] "Green: all core habits. Amber: partial. Red: missed/poor recovery. Gray: no data."

### 23e. Cross-link to Chronicle
- **Effort:** Low
- [ ] Weeks with Chronicle installments show "✍️ Read this week's Chronicle →"
- [ ] Chronicle links back: "See the raw numbers → Weekly Snapshot"

### 23f. Use weekly aggregates
- **Effort:** Medium
- [ ] Average sleep, HRV trend direction, total training minutes, calorie adherence %
- [ ] Weekly report card, not daily reading

### 23g. Improve summary narrative
- **Effort:** Medium
- [ ] From database report to Board-voice interpretation
- [ ] Synthesized paragraph, not just numbers

### 23h. Add protocol adherence section
- **Effort:** Medium
- [ ] Each of 6 protocols: "Zone 2: 3/4 sessions. Sleep: 6/7 nights."

### 23i. Surface sick/rest days in empty weeks
- **Effort:** Low
- [ ] If `manage_sick_days` has entries: "Sick days: March 5-6. Reason: flu."

### 23j. Calendar heatmap visualization (POST-LAUNCH)
- **Effort:** High
- [ ] GitHub contribution graph style — year of day-grade colors

### 23k. Fix eyebrow
- **Effort:** Low
- [ ] "The Data" → "The Chronicle"

### 23l. Fix breadcrumb
- **Effort:** Low
- [ ] "The Chronicle > Weekly Snapshots"

### 23m. Compare two weeks mode (POST-LAUNCH)
- **Effort:** Medium
- [ ] Select any two weeks, see side-by-side with deltas

### 23n. Shareable weekly card (POST-LAUNCH)
- **Effort:** Medium
- [ ] Social image: week number, key numbers, heatmap strip

---

## DECISION 24: Ask the Data (`/ask/`)
**Files:** `site/ask/index.html`, `lambdas/site_api/` (ask endpoint)

### 24a. Verify `/api/ask` endpoint (CRITICAL)
- **Effort:** Varies
- [ ] Test endpoint with real questions
- [ ] If not reliable: ship "Coming soon" state instead of broken chat
- [ ] If working: ensure response quality meets bar

### 24b. Add context sentence
- **Effort:** Low
- [ ] "This AI has access to 19 sources, X days of continuous data, 7 lab draws, 110 SNPs."

### 24c. Expand suggestion chips
- **Effort:** Low
- [ ] 12-15 suggestions organized by domain: Sleep, Nutrition, Training, Cross-domain
- [ ] Teach readers what's possible

### 24d. Upgrade subscriber gate
- **Effort:** Low-Med
- [ ] From plain email field to mini subscribe pitch
- [ ] "Subscribers get 20 questions/hour + The Measured Life weekly + anomaly alerts"
- [ ] Full value prop, not just limit unlock

### 24e. Increase anonymous limit to 5
- **Effort:** Low
- [ ] Change `MAX_QUESTIONS = 3` to `MAX_QUESTIONS = 5`
- [ ] Or: unlimited for launch week as promotional hook

### 24f. Add medical advice guardrails
- **Effort:** Low
- [ ] System prompt: when medical questions detected, include inline disclaimer
- [ ] "This data suggests X, but medical interpretation requires a clinician."

### 24g. Expand data strip
- **Effort:** Low
- [ ] "19 sources · X days · 7 lab draws · 110 SNPs · 37 habits"

### 24h. Add "Ask Elena" section
- **Effort:** Medium
- [ ] Below conversation thread
- [ ] "Questions for the AI get instant answers. Questions for Elena get narrative investigation."
- [ ] Text field + optional email + submit → DynamoDB queue

### 24i. Track questions as content intelligence (POST-LAUNCH)
- **Effort:** Medium
- [ ] What are visitors asking? Feed into Chronicle topics + experiment ideas

### 24j. Richer AI response formatting
- **Effort:** Medium
- [ ] Bold key numbers, show deltas, add "Sources queried:" footer

### 24k. Dynamic suggestion chips (POST-LAUNCH)
- **Effort:** Medium
- [ ] "Most asked this week" as social-proof suggestions

### 24l. Cross-link to Data Explorer and Chronicle
- **Effort:** Low
- [ ] "Want the full analysis? Data Explorer →"
- [ ] "Want the narrative? Chronicle →"

### 24m. Fix breadcrumb
- **Effort:** Low
- [ ] Appropriate section under new nav

### 24n. Consider nav placement
- **Effort:** Low
- [ ] Currently in The Chronicle. May fit better in The Evidence or The Platform.
- [ ] Resolve before launch

---

## PART 3 SUMMARY STATISTICS

| Metric | Count |
|--------|-------|
| Total decisions (Part 3) | 9 (Decisions 16–24) |
| Meta-discussions | 2 (Practice Hierarchy, Engagement Model) |
| Total recommendations (Part 3) | ~170 |
| Must-have items | ~65 |
| Should-have items | ~75 |
| Post-launch items | ~15 |
| Guardrails | 4 |
| Critical items | 1 (24a: verify /api/ask) |
| Operational items | 2 (19b, 20b: start experiment + challenge before launch) |
| Bug fixes | ~14 (breadcrumbs, eyebrows) |

### Running Total (Parts 1-3)
| Metric | Count |
|--------|-------|
| Total decisions | 24 |
| Total recommendations | ~338 |
| Pages reviewed | 20 of 30+ |

---

_This document is the Part 3 source of truth. Append to the Part 1-2 feature list for the complete set._
