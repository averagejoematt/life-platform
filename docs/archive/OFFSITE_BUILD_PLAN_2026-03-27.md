# PRE-LAUNCH OFFSITE — BUILD PLAN (PART 1 of 2)
## March 27, 2026 · 5 Days to April 1 Go-Live
### Joint Session: Health Board + Product Board + Cold Reviewers

---

## SESSION STATUS

**Part 1 completed:** Decisions 1–11 (March 27, 2026)
**Part 2 pending:** Remaining pages + prioritization + implementation planning

### PAGES REVIEWED (Part 1)
- [x] Navigation / IA (Decision 1)
- [x] Ticker / Marquee (Decision 2)
- [x] Today / The Pulse — `/live/` (Decision 3)
- [x] Character / The Score — `/character/` (Decision 4)
- [x] Habits / The Operating System — `/habits/` (Decision 5)
- [x] Accountability — `/accountability/` (Decision 6)
- [x] Milestones / Achievements — `/achievements/` (Decision 7)
- [x] Sleep Observatory — `/sleep/` (Decision 8)
- [x] Glucose Observatory — `/glucose/` (Decision 9)
- [x] Nutrition Observatory — `/nutrition/` (Decision 10)
- [x] Training Observatory — `/training/` (Decision 11)

### PAGES REMAINING (Part 2)
- [ ] Inner Life / Mind — `/mind/`
- [ ] Benchmarks — `/benchmarks/`
- [ ] Data Explorer — `/explorer/`
- [ ] Stack — `/stack/`
- [ ] Protocols — `/protocols/`
- [ ] Supplements — `/supplements/`
- [ ] Experiments — `/experiments/`
- [ ] Challenges — `/challenges/`
- [ ] Discoveries — `/discoveries/`
- [ ] Platform — `/platform/`
- [ ] The AI / Intelligence — `/intelligence/`
- [ ] AI Board — `/board/`
- [ ] Cost — `/cost/`
- [ ] Methodology — `/methodology/`
- [ ] Tools — `/tools/`
- [ ] For Builders — `/builders/`
- [ ] Chronicle — `/chronicle/`
- [ ] Weekly Snapshots — `/weekly/`
- [ ] Subscribe — `/subscribe/`
- [ ] Ask the Data — `/ask/`
- [ ] Home page (re-review in light of all decisions)
- [ ] Story page — `/story/`
- [ ] About / Mission — `/about/`
- [ ] **Cross-cutting:** Final prioritization, April 1 vs post-launch sort, implementation sequencing

---

## DECISION LOG

### DECISION 1: Navigation Restructure — 6-Section IA ✅ APPROVED (27-0)

**Current state:** 5 sections, ~30 sub-pages, "The Data" carrying 12 items in one dropdown.

**Approved new structure:**

| # | Section | Sub-pages | Notes |
|---|---------|-----------|-------|
| 1 | **The Story** | Home · My Story · The Mission · Milestones | Emotional entry point (milestones moved here per Decision 7) |
| 2 | **The Evidence** | *Observatories:* Sleep · Glucose · Nutrition · Training · Inner Life | Deep editorial data pages |
|   | | *Analysis:* Benchmarks · Data Explorer | |
| 3 | **The Pulse** | Today · The Score *(was: Character)* · Habits · Accountability | Real-time personal tracking (Milestones moved to Story per Decision 7) |
| 4 | **The Practice** | Stack · Protocols · Supplements · Experiments · Challenges · Discoveries | What I do and what I've tested |
| 5 | **The Platform** | How It Works · The AI · AI Board · Methodology · Cost · Tools · For Builders | Technical/curious visitors |
| 6 | **The Chronicle** | Chronicle Archive · Weekly Snapshots · Ask the Data · Subscribe | Serialized narrative + engagement |

**Mobile bottom nav (5 slots):** Story | Evidence | Pulse | Chronicle | ☰ More
- "More" opens full menu with The Practice and The Platform

**Naming decisions:**
- "The Build" → renamed to **"The Platform"** (unanimous)
- "Dashboard" section → named **"The Pulse"** (unanimous)
- "Character" nav label → renamed to **"The Score"** (page title stays "Character Sheet") (unanimous)
- "Chronicle" → **kept as-is**, add subtitle/descriptor in dropdown (unanimous)
- "Inner Life" → **kept as-is** (unanimous)

**Conditions / follow-ups:**
- Methodology must be cross-linked from each observatory page footer (Rhonda Patrick / Lena Johansson condition)
- "Ask the Data" may appear under both The Pulse and The Chronicle (Ava Moreau concern, Raj compromise)
- "For Builders" must have real content by April 1 or be removed from nav (Kenji flag)

**Implementation scope:**
- [ ] Update `components.js` SECTIONS array (6 sections, new labels, new groupings)
- [ ] Update mobile bottom nav (5 items + More pattern)
- [ ] Update `nav.js` BADGE_MAP for new section ownership
- [ ] Update `nav.js` READING_PATHS for new flow
- [ ] Update overlay menu section headings
- [ ] Test all dropdown rendering on desktop + mobile
- [ ] CloudFront invalidation for JS assets

---

### DECISION 2: Ticker/Marquee Enhancements ✅ APPROVED (8 recommendations)

**Current state:** Homepage-only horizontal scrolling ticker with 6 items: DAY N · WEIGHT · HRV · RECOVERY · STREAK · JOURNEY %. All values populated from `public_stats.json`. No directional indicators, no links, no editorial content.

**Approved recommendations:**

| # | Recommendation | Priority | Support |
|---|---------------|----------|---------|
| 2a | **Add directional arrows** (↗↘→) to all metrics — derive from trend data already in public_stats | Must-have | Unanimous |
| 2b | **Add sleep score** as a ticker item (e.g., "SLEEP B+" or "LAST NIGHT 7.2H · 92%") | Must-have | Strong (Huberman, Tom, Derek, Rachel) |
| 2c | **Add Chronicle latest title** as a clickable ticker item (e.g., "LATEST: WEEK 7 — THE WEEK EVERYTHING CLICKED →") | Should-have | Strong (Sofia, Jordan, Ava) |
| 2d | **Add freshness date** to weight display (e.g., "287.7 LBS · MAR 27") | Should-have | Moderate (Rachel, Priya) |
| 2e | **Reframe streak when < 5 days** — show T0 habit completion % instead of "0D STREAK" to avoid demotivating early reads | Should-have | Moderate (Maya, Derek) |
| 2f | **Preserve terminal aesthetic** — keep monospaced, all-caps, staccato rhythm. No full sentences. | Guardrail | Unanimous (Tyrell) |
| 2g | **Protect "DAY N" as the lead item** — it's the narrative anchor that says "this is a story in progress" | Guardrail | Unanimous (Margaret) |
| 2h | **Consider making ticker global** (all pages, not just homepage) — no consensus, revisit post-launch | Parking lot | Split (Tyrell: home-only, Jordan: everywhere) |

**Design guardrails (2f + 2g):** The ticker's Bloomberg-terminal aesthetic is part of the brand identity. Additions must be data-forward, uppercase, monospaced. No conversational sentences. "DAY N" always leads.

**Implementation scope:**
- [ ] Add trend arrows to Weight, HRV, Recovery, Streak — logic: compare to 7-day avg from `public_stats.trends`
- [ ] Add Sleep item to ticker (pull from `public_stats.vitals.sleep_score` or `sleep_efficiency`)
- [ ] Add Chronicle title item — pull from `public_stats.chronicle_latest.title`, uppercase, link to latest post
- [ ] Add date suffix to weight display (already partially implemented with staleness logic — extend to ticker)
- [ ] Streak reframe logic: if streak < 5, show "T0: {pct}%" instead of "{n}D STREAK"
- [ ] Duplicate all new items in the ticker's second copy (infinite scroll pattern)
- [ ] Test ticker scroll speed — more items means longer cycle, may need speed adjustment
- [ ] **Post-launch:** Evaluate global ticker (2h) based on user feedback

---

### DECISION 3: Today / The Pulse Page (`/live/`) Deep Review ✅ LOGGED

**Current state:** 3-layer architecture (Headline → Glyph Strip → Detail Cards) + Journey section. Single `/api/pulse` fetch. 8 glyphs: Scale, Water, Movement, Lift, Recovery, Sleep, Journal, Mind. AI-generated single-sentence narrative.

**Approved recommendations:**

| # | Recommendation | Category | Effort | Priority |
|---|---------------|----------|--------|----------|
| 3a | **Expand narrative to 2-3 sentences** with editorial voice — not a report, a briefing with personality | Content | Low | Must-have |
| 3b | **Add sparkline reference lines** (7-day avg baseline) + hover/tap states showing actual values | Data viz | Low-Med | Must-have |
| 3c | **Expandable detail cards** — tap/click to reveal full breakdown (sleep: REM/deep/efficiency; recovery: HRV+RHR+resp rate) | UX | Medium | Should-have |
| 3d | **Add weight trend line to Journey section** — visual arc Day 1 → present, projected goal date, rate of loss | Data viz | Medium | Must-have |
| 3e | **"Since yesterday" delta line** — acknowledge return visitors with what changed since last visit | Engagement | Medium | Should-have |
| 3f | **Share button / "Copy today's pulse"** — enable daily social sharing (tweet-sized summary) | Growth | Low | Should-have |
| 3g | **Improve Journal + Mind card treatment** — show emotion tags, themes, word context instead of bare Open/Closed and number | Content | Medium | Should-have |
| 3h | **Visual hierarchy in detail cards** — most notable signal (red, or biggest change) gets elevated treatment | Design | Low-Med | Nice-to-have |
| 3i | **Time-of-day awareness** in narrative ("Morning read: recovery data in, workout pending" vs "End of day: full picture") | Content | Low | Nice-to-have |
| 3j | **Loading skeletons** replacing "Fetching today's signal…" text with skeleton cards | Polish | Low | Nice-to-have |
| 3k | **Fix Yesterday/Tomorrow disabled state** — tooltip "Available after Day 1", active styling when applicable | Polish | Low | Must-have |
| 3l | **Throughline link update** — change /story/ to latest Chronicle for daily-to-narrative connection | Content | Low | Must-have |
| 3m | **Consider 9th glyph: Readiness/Form** (TSB-based) — distinct from Lift and Movement, shows accumulated fitness state | Feature | Medium | Parking lot |
| 3n | **6-month scaling plan**: sparklines → interactive mini-charts, Journey → full weight trend viz with milestones | Architecture | High | Parking lot |

**Key themes from discussion:**
- Top of page (day number, pulsing dot, narrative) is among the best design on the site — protect it
- Below the glyph strip the page goes flat — needs visual hierarchy and depth
- Journal + Mind glyphs are the most differentiated data and deserve richer treatment
- Page is optimized for snapshot but weak on context — sparklines, deltas, and trend lines fix this
- Journey section is a placeholder that needs to become the emotional payoff at 6 months
- Daily return visit mechanics (since-yesterday, share, streak acknowledgment) are missing

**Implementation scope:**
- [ ] Pulse Lambda: expand narrative prompt to 2-3 sentences with Board voice
- [ ] Pulse Lambda: add time-of-day context to narrative generation
- [ ] Frontend: sparkline reference lines + hover states
- [ ] Frontend: expandable card click interaction
- [ ] Frontend: Journey section weight trend chart
- [ ] Frontend: "Since yesterday" delta bar
- [ ] Frontend: share/copy button with pre-formatted pulse summary
- [ ] Frontend: Journal card → show themes array; Mind card → show label + context
- [ ] Frontend: loading skeletons
- [ ] Frontend: fix prev/next nav disabled state + tooltip
- [ ] Content: update throughline link from /story/ to /chronicle/
- [ ] Post-launch: Readiness glyph (3m), 6-month chart scaling (3n)

### DECISION 4: Character / The Score Page (`/character/`) Deep Review ✅ LOGGED

**Current state:** 1,920-line RPG-style character sheet. Trading card hero with tier theming (Foundation→Elite), 7-pillar scoring, radar chart, pillar sparklines, visual timeline, pillar heatmap, 5 achievement badge groups, methodology section, level-up notification CTA. All data from `/api/character` endpoint.

**Approved recommendations:**

| # | Recommendation | Category | Effort | Priority |
|---|---------------|----------|--------|----------|
| 4a | **Add plain-language subtitles** to gaming terms — "Foundation · Level 2" gets "Early stage: building baseline habits" beneath it. XP, tier, level all get one-line translations | UX | Low | Must-have |
| 4b | **Shareable trading card** — "Share my card" button generates social-friendly image of the trading card for Twitter/Instagram sharing | Growth | Medium | Must-have |
| 4c | **Move Level-Up Notification CTA higher** — from page bottom to immediately below trading card hero where energy is highest | Growth | Low | Must-have |
| 4d | **Collapse locked badges by default** — lead with earned badges prominently, show "X more to unlock" with expand option. Prevents Day 1 wall-of-failure | UX/Psych | Low | Must-have |
| 4e | **Add composite score history chart** — line chart showing score trajectory over time. Critical for 6-month transformation arc | Data viz | Medium | Should-have |
| 4f | **Add one narrative moment** — journal pull-quote or personal "why the game metaphor" in The Game section. Breaks mechanical tone | Content | Low | Should-have |
| 4g | **Style pillar cards as RPG stat blocks** — carry gaming visual metaphor below the hero instead of reverting to generic cards | Design | Medium | Should-have |
| 4h | **Acknowledge Mind/Social scoring uncertainty** — brief note that these pillars use qualitative data with more uncertainty than biometric pillars | Credibility | Low | Should-have |
| 4i | **Expandable "The math" section** — collapsible deep-dive with actual XP curve formula, weighting details for the technical audience | Content | Low | Nice-to-have |
| 4j | **Visual energy continuity** — design density drops below the hero. Increase visual quality in radar/pillar/timeline sections to match trading card energy | Design | Medium | Nice-to-have |
| 4k | **Structural clarity** — consider clearer visual separation between Identity (card), Metrics (scores), Achievements (badges) as three modes | IA | Medium | Parking lot |

**Key themes from discussion:**
- The trading card hero is the single most differentiated, shareable visual on the entire site — protect and amplify it
- The gaming metaphor is the site's secret weapon but needs accessibility bridges for non-gamers (Tom)
- Below the hero, visual energy drops and the page becomes mechanical — needs narrative warmth and design continuity
- At launch (Day 1), the badges section is mostly locked — needs inversion to lead with accomplishment
- The Level-Up CTA is brilliant but buried — move it to where impulse is highest
- Mind/Social pillar scoring needs transparency about qualitative data sources
- A score history chart becomes the page's most powerful element at 6 months

**Implementation scope:**
- [ ] Frontend: plain-language subtitle spans under all gaming terms
- [ ] Frontend: share card button → generate OG-image-style trading card (canvas or server-side)
- [ ] Frontend: move levelup-cta section above intro-brief
- [ ] Frontend: badges — collapse locked groups, show earned count + "X more" toggle
- [ ] Frontend: composite score line chart (requires score_history in API or public_stats)
- [ ] Content: add 2-3 sentence personal "why" to The Game intro + one pull-quote from journal
- [ ] Content: add uncertainty note to Mind/Social in methodology
- [ ] Frontend: collapsible "The math" in methodology
- [ ] Post-launch: RPG stat block styling for pillar cards (4g), visual density pass (4j), structural separation (4k)

### DECISION 5: Habits / The Operating System (`/habits/`) Deep Review ✅ LOGGED

**Current state:** 1,172-line page titled "The Operating System." 37 behavioral habits across 3 tiers (T0 Foundation: 7 non-negotiables, T1 System: ~15 by purpose group, T2 Horizon: aspirational/locked). Discipline Gates (vice tracking with streak counters). Daily Pipeline (visual day flow). Habit Intelligence section (heatmap, keystone correlations, day-of-week pattern, decision fatigue index). Data from `/api/habit_registry` + `/api/habit_streaks`.

**Approved recommendations:**

| # | Recommendation | Category | Effort | Priority |
|---|---------------|----------|--------|----------|
| 5a | **Elevate Daily Pipeline** — move higher or make it the hero. Add one-line science rationale per node (circadian biology). Add share button. Most human, most shareable section | Content/Design | Medium | Must-have |
| 5b | **Elevate Habit Intelligence** — move heatmap, correlations, day-of-week analysis higher on the page. Analysis beats the habit list for returning visitors | IA | Low | Must-have |
| 5c | **Add narrative warmth** — one journal pull-quote or personal "why" about the hardest habit or the one that surprised him. Break the mechanical tone | Content | Low | Must-have |
| 5d | **Reframe Discipline Gates language** — add "Streaks reset but progress doesn't" compassionate framing. Reduce punitive relapse language | Content/Psych | Low | Must-have |
| 5e | **Differentiate zone visual identity** — Zone 1 heavy/anchored, Zone 2 flowing/interconnected, Zone 3 light/aspirational/transparent. Currently all zones look identical | Design | Medium | Should-have |
| 5f | **Fix T1 sparkline bug** — currently showing duplicated T0 data for all T1 habits instead of per-habit completion data. Misleading sparklines | Bug | Medium | Must-have |
| 5g | **Honest evidence badges** — audit all T0 "strong" ratings. Mark personal protocols as "personal protocol." Badge credibility requires honesty about weak evidence | Credibility | Low | Should-have |
| 5h | **Domain filter** — cross-tier filtering: "show me all sleep habits" across T0/T1/T2. Lisa Park's request | Feature | Medium | Nice-to-have |
| 5i | **Purpose group descriptions visible by default** — don't hide the best micro-copy ("Protecting the master variable") behind collapsed accordions | UX | Low | Should-have |
| 5j | **Science rationale in Daily Pipeline nodes** — each step gets a one-liner on why it's sequenced there (e.g., "Morning light sets the cortisol pulse") | Content | Low | Should-have |
| 5k | **6-month architecture shift** — habit list becomes static reference, intelligence/analysis becomes centerpiece. Plan page architecture for that transition | Architecture | Medium | Parking lot |
| 5l | **Entry ramp for newcomers** — "Start here: the 7 that matter" callout at the top before full system unfolds. Derek and Tom both felt overwhelmed | UX | Low | Should-have |

**Key themes from discussion:**
- The page is technically impressive but emotionally cold — most mechanical page on the site. Zero narrative voice
- Daily Pipeline is the hidden gem — most human, most shareable, maps to circadian biology. Currently buried mid-page
- Habit Intelligence (heatmap, correlations) is more interesting than the habit list itself — should be higher
- The Discipline Gates vice framing is psychologically punitive (Conti). "Streak broken" language needs compassion
- T1 sparkline bug means individual habit sparklines are all showing the same T0 data (Kenji)
- Evidence badges are a credibility asset but only if honest — not every T0 habit has "strong" evidence
- Newcomers (Derek, Tom) felt overwhelmed — needs an entry ramp before the full system unfolds
- At 6 months, the static habit list becomes less interesting and the analysis becomes the draw

**Implementation scope:**
- [ ] Frontend: restructure page order — Pipeline and Intelligence higher, Zone listings lower
- [ ] Frontend: add per-node science tooltips/subtitles to Daily Pipeline
- [ ] Frontend: add share button to Daily Pipeline section
- [ ] Frontend: fix T1 sparklines to use per-habit completion data from API
- [ ] Frontend: visual differentiation per zone (CSS tier theming)
- [ ] Frontend: purpose group descriptions visible by default (remove collapsed state)
- [ ] Frontend: "Start here" callout above Zone 1
- [ ] Content: add one journal pull-quote or personal "why" narrative element
- [ ] Content: add compassionate relapse framing to Discipline Gates
- [ ] Content: audit evidence badge ratings for honesty
- [ ] Post-launch: domain filter (5h), 6-month architecture shift (5k)

### DECISION 6: Accountability Page (`/accountability/`) Deep Review ✅ LOGGED

**Current state:** 1,110-line page. State hero (experiment health status), 3-number snapshot (T0 streak, T0%, journey), 90-day T0 compliance arc chart, 30-day compliance calendar, nudge system (4 anonymous reaction buttons → daily brief), subscribe CTA, public commitment blockquote. Data from habit_streaks API + site API nudge endpoints.

**Core diagnosis (unanimous):** Page has an identity crisis — 80% dashboard (duplicating Pulse/Habits data) and 20% social contract (nudge system + public commitment). Should be the reverse. The unique and powerful assets: the public commitment framing, the nudge system as a reader feedback loop, and the compliance calendar *when framed as evidence of promises kept*. The redundant assets: state hero, 3-number snapshot, and 90-day arc overlap heavily with Pulse and Habits pages.

**Approved recommendations:**

| # | Recommendation | Category | Effort | Priority |
|---|---------------|----------|--------|----------|
| 6a | **Restructure as a social contract page** — new arc: Commitment → Evidence → Your Turn. Not a dashboard | IA/Content | Medium | Must-have |
| 6b | **Lead with public commitment quote** — "Accountability without witnesses is just intention" becomes the hero, not buried at bottom | Content | Low | Must-have |
| 6c | **Elevate nudge system to centerpiece** — show aggregate distribution, social proof ("X nudges this week"), connect nudges to Chronicle responses | Feature | Medium | Must-have |
| 6d | **Reframe data sections as evidence** — "Compliance Calendar" → "Did I keep my word?" · "90-day arc" → "The unedited record." Same data, accountability language | Content | Low | Must-have |
| 6e | **De-duplicate dashboard data** — remove/simplify state hero and 3-number snapshot (duplicate Pulse). Link out instead | IA | Low | Should-have |
| 6f | **Add witness/community counter** — "X people are following this experiment" / "You're one of Y witnesses." Anonymous but creates belonging | Feature | Low-Med | Should-have |
| 6g | **Add comparative context** — "Average habit program adherence: 18 days. Matthew: X days." Benchmarks add credibility | Content | Low | Should-have |
| 6h | **Visual warmth and differentiation** — this page should feel distinct from dashboards. Warmer tones, possibly personal photography, handwritten elements | Design | Medium | Should-have |
| 6i | **Reader reflection option** — beyond nudge reactions, let visitors share their own experience. Transforms judgment into solidarity | Feature | Medium | Nice-to-have |
| 6j | **Nudge → Chronicle feedback loop** — show how nudges influenced the weekly narrative. Closes the engagement loop | Content | Medium | Nice-to-have |
| 6k | **Social proof in nudge feed** — "last nudge: 2 hours ago" / "X nudges this week" signals active community vs ghost town | Feature | Low | Should-have |

**Proposed new page arc (Raj + Maya + Elena consensus):**
1. **Hero: The Commitment** — public commitment blockquote as the opening. "I made this promise. Here's whether I kept it."
2. **The Evidence** — compliance calendar + 90-day arc, reframed with accountability language ("The unedited record")
3. **Your Turn** — nudge system, expanded with social proof, aggregate distribution, witness counter
4. **The Loop** — how nudges connect to the Chronicle and Matthew's response. Community, not broadcast.
5. **Subscribe** — "Get accountability updates" stays

**Implementation scope:**
- [ ] Content: restructure page section order (commitment → evidence → nudges → loop → subscribe)
- [ ] Content: move public commitment quote to hero position
- [ ] Content: rewrite all eyebrows/headings with accountability framing
- [ ] Frontend: expand nudge system — aggregate distribution viz, social proof counter
- [ ] Frontend: simplify/remove state hero and 3-number snapshot (link to Pulse/Habits)
- [ ] Frontend: add witness counter (derive from nudge unique IPs or subscriber count)
- [ ] Frontend: add comparative adherence benchmarks
- [ ] Design: visual warmth pass — differentiate from dashboard aesthetic
- [ ] Post-launch: reader reflection feature (6i), nudge→Chronicle feedback loop (6j)

### DECISION 7: Milestones / Achievements Page (`/achievements/`) Deep Review ✅ LOGGED

**Current state:** 533-line badge gallery page. Progress ring (X of Y unlocked), summary strip (streak, days, level, weight), 6 badge categories (Streaks, Levels, Weight, Data, Experiments, Challenges). Each badge: SVG icon with ring, name, description, earned date or unlock hint. Single `/api/achievements` fetch. Significant duplication with Character page's Achievement Badges section (same data, same rendering).

**Placement decision: Move to The Story section.** Room consensus — badges are completed chapters, not running data. They're discrete, permanent, narrative milestones. They belong with the story, not the data dashboard.

**Approved recommendations:**

| # | Recommendation | Category | Effort | Priority |
|---|---------------|----------|--------|----------|
| 7a | **Move to The Story nav section** — badges are completed chapters, not continuous data. Narrative page. | IA | Low | Must-have |
| 7b | **De-duplicate from Character page** — Character gets compact badge summary + "See all milestones →" link. This page becomes canonical badge destination | IA | Low | Must-have |
| 7c | **Add narrative vignettes to earned badges** — 2-3 sentences per badge about what the moment meant. Link to relevant Chronicle/journal entry. "A door into a moment, not a medal on a shelf" (Tom) | Content | Medium | Must-have |
| 7d | **Add chronological timeline view** — toggle between "by category" (current) and "by date" (story arc). The timeline tells the transformation narrative | Feature | Medium | Should-have |
| 7e | **Add share button per earned badge** — generate shareable card with badge art, date, one-liner. Badge-earned = peak share moment | Growth | Medium | Should-have |
| 7f | **Add "progress toward" for locked badges** — "You're 4 lbs from Sub-260" with mini progress bar instead of just padlock icon | UX | Medium | Should-have |
| 7g | **Add clinical context to weight badges** — "Sub-280: below obesity threshold" · "10% loss: metabolic marker improvement threshold" | Content | Low | Should-have |
| 7h | **Move credibility line to subtitle position** — "Computed from real data. No self-reporting. The numbers confirm it." From bottom disclaimer to unmissable subtitle | Content | Low | Must-have |
| 7i | **Fix progress ring framing** — show earned count as positive absolute ("4 earned") not % of expanding total ("4 of 22" can feel like falling behind) | UX/Psych | Low | Should-have |
| 7j | **Badge-earned email notifications** — "Matthew just unlocked Sub-260. Read the story." Highest-open-rate trigger | Growth | Medium | Nice-to-have |
| 7k | **Enrich badge data model** — add `clinical_context`, `narrative_link`, `vignette`, `progress_current` fields to badge config | Architecture | Low | Should-have |

**Key themes from discussion:**
- The page duplicates the Character page's badge section almost exactly — needs canonical ownership here, compact summary there
- Badges are *story beats*, not data points — they belong under The Story, not The Data/Pulse
- The biggest missed opportunity: earned badges are disconnected from narrative. Each should be "a door into a moment" (Tom) with vignettes linking to Chronicle entries
- Locked badges should show progress-toward, not just a padlock — "You're 4 lbs away" is motivating, "Locked" is a dead end
- Weight badges should carry clinical significance context (Attia, Rachel) — bridges personal achievement and medical meaning
- Chronological timeline view tells the transformation story better than category buckets (Conti)
- Share mechanics and email triggers make badge-earned moments into growth engines (Sofia, Jordan)

**Updated Decision 1 impact:** The Story section in the new nav now includes: Home · My Story · The Mission · **Milestones**

**Implementation scope:**
- [ ] Nav: add Milestones to The Story section in `components.js`
- [ ] Character page: replace full badge gallery with compact summary + link
- [ ] Content: write vignettes for each earned badge (can start with template, grow over time)
- [ ] Frontend: badge detail expand/modal with vignette, date, data snapshot, Chronicle link
- [ ] Frontend: "by date" timeline toggle alongside "by category"
- [ ] Frontend: share card generator per earned badge
- [ ] Frontend: progress-toward bars for locked badges
- [ ] Frontend: reframe progress ring (absolute earned count, not %)
- [ ] Content: add clinical context strings to weight badges
- [ ] Content: move disclaimer copy to page subtitle
- [ ] API/Config: enrich badge data model with new fields
- [ ] Post-launch: badge-earned email trigger (7j)

### DECISION 8: Sleep Observatory (`/sleep/`) Deep Review ✅ LOGGED

**Current state:** 1,165-line observatory page. Narrative intro ("The thing I thought I was good at"), 2-column hero with 4 gauge rings (duration, sleep score, deep %, recovery), 3 staggered pull-quotes with N=1 evidence badges, sleep stage editorial (3-column: deep/REM/HRV), temperature discovery card, 30-day trend chart (canvas-rendered), 4 N=1 sleep rules, cross-links to Training + Character, narrative section with 5 protocols, methodology section. Data from `/api/sleep_detail`. **Pre-dates the current editorial design pattern** established on Nutrition, Training, and Inner Life observatories.

**Core diagnosis:** The content is strong — the narrative intro is the best on any observatory, the pull-quotes are compelling, the N=1 rules are genuinely useful. But the page is a generation behind the newer observatories visually and structurally. It needs the editorial alignment pass to match Nutrition/Training/Inner Life, plus several significant data additions.

**Approved recommendations:**

| # | Recommendation | Category | Effort | Priority |
|---|---------------|----------|--------|----------|
| 8a | **Align to current editorial design pattern** — apply Nutrition/Training/Inner Life standard: staggered pull-quotes, monospace headers with trailing dashes, 3-column editorial spreads, left-accent rule cards | Design | Med-High | Must-have |
| 8b | **Merge two hero sections** — narrative intro becomes sole hero, gauge rings sit directly below as data payoff. Remove duplicate "master lever" title | IA | Low | Must-have |
| 8c | **Add sleep consistency / social jetlag metric** — bedtime variance weekday vs weekend with narrative context | Data | Medium | Must-have |
| 8d | **Add sleep efficiency metric** — actual sleep ÷ time in bed, displayed prominently | Data | Low | Must-have |
| 8e | **Add sleep architecture trend chart** — stacked area (deep/REM/light) over 30 days instead of static average only | Data viz | Medium | Should-have |
| 8f | **Weave narrative through data sections** — 1-2 contextual sentences per data section interpreting the numbers, not just displaying. Follow Inner Life pattern | Content | Medium | Must-have |
| 8g | **Elevate N=1 Rules** — move higher on page or tease early. Practical payoff visitors came for (Derek) | IA | Low | Should-have |
| 8h | **Add protocol adherence loop** — each protocol shows adherence %, outcome with/without adherence. Rules become proven interventions not aspirations | Data | Medium | Should-have |
| 8i | **Dynamic pull-quotes** — automatically surface most significant correlations with evidence badges as data accumulates. Evergreen content engine | Feature | Med-High | Nice-to-have |
| 8j | **Add cross-domain findings** — sleep → next-day recovery, training quality, mood/cognitive state. The insight that differentiates from a Whoop dashboard | Data | Medium | Should-have |
| 8k | **Measurement agreement note** — explain what it means when Eight Sleep and Whoop scores diverge. Which to trust and why | Credibility | Low | Should-have |
| 8l | **Chart interactivity** — hover states for individual nights, click for breakdown, 90d/all-time time windows | Data viz | Medium | Nice-to-have |
| 8m | **Frame three differentiators prominently** — cross-device triangulation, cross-domain correlation, accumulated N=1 rules. Make clear this isn't a Whoop screenshot | Content | Low | Should-have |

**Key themes from discussion:**
- The narrative intro ("The thing I thought I was good at") is the best editorial title on any observatory — protect it (Margaret)
- The page pre-dates the current editorial design pattern and needs an alignment pass to match newer observatories
- Significant data gaps: sleep consistency/social jetlag, sleep efficiency, sleep onset latency, architecture trends, cross-domain findings
- The narrative and data are bookended (story at top + bottom, pure dashboard in middle) rather than interlaced as on newer pages
- N=1 Rules are the most practical content but buried at the bottom
- Protocols should close the loop with adherence data — transforms aspirational rules into proven interventions
- The page needs to clearly frame why it's different from a Whoop or Eight Sleep dashboard (Raj)
- Sleep → mental state correlation is missing and important (Conti)

**Implementation scope:**
- [ ] Design: full editorial alignment pass — apply observatory.css pattern from Nutrition/Training/Inner Life
- [ ] Frontend: merge hero sections (narrative intro as hero, gauges as data payoff below)
- [ ] API/Frontend: add sleep consistency metric (bedtime variance, social jetlag calculation)
- [ ] API/Frontend: add sleep efficiency display
- [ ] Frontend: stacked area chart for sleep architecture trends (deep/REM/light over 30d)
- [ ] Content: weave narrative sentences into each data section
- [ ] Frontend: restructure page order — tease/move N=1 rules higher
- [ ] API/Frontend: protocol adherence stats per rule (adherence %, outcome delta)
- [ ] Content: add cross-domain findings section (sleep → recovery, training, mood)
- [ ] Content: measurement agreement note in methodology
- [ ] Content: frame three differentiators in hero or intro
- [ ] Post-launch: dynamic pull-quotes (8i), chart interactivity (8l)

### DECISION 9: Glucose Observatory (`/glucose/`) Deep Review ✅ LOGGED

**Current state:** 1,193-line observatory page. Same generation as Sleep — pre-dates editorial design pattern. Narrative intro ("The number that quieted the anxiety"), 2-column hero with 4 gauge rings (TIR, avg glucose, variability SD, optimal %), 3 pull-quotes with N=1 badges, 3-column TIR editorial, **hardcoded 5-meal response table**, 30-day trend chart, 4 N=1 rules, cross-links, narrative + protocols, methodology. Data from `/api/glucose`. Meal data is static HTML, not API-driven.

**Core diagnosis:** The narrative intro is among the best on the site. The meal response table is the single most differentiated content — but it's static, hardcoded, and understyled. Same editorial alignment gap as Sleep. The page's 6-month potential is enormous if the meal table becomes dynamic.

**Approved recommendations:**

| # | Recommendation | Category | Effort | Priority |
|---|---------------|----------|--------|----------|
| 9a | **Align to current editorial design pattern** — same pass as Sleep (Decision 8a) | Design | Med-High | Must-have |
| 9b | **Merge two hero sections** — narrative intro as sole hero, gauges below. Same fix as Sleep | IA | Low | Must-have |
| 9c | **Make meal response table dynamic** — API-driven from CGM × MacroFactor cross-reference. Sortable, filterable, growing over time. THE killer feature (Attia, Rachel, Tom, Maya unanimous) | Feature | High | Must-have |
| 9d | **Elevate meal table design** — from plain HTML `<table>` to editorial card layout with color-coded spike severity, mini glucose curves per meal, share buttons | Design | Medium | Must-have |
| 9e | **Add daily glucose curve visualization** — actual 288-reading day plot with meal events overlaid. Good day vs bad day comparison | Data viz | Medium | Should-have |
| 9f | **Add cross-domain visualizations** — same meal with good vs bad sleep; with vs without post-meal walk; glucose × stress level | Data | Medium | Should-have |
| 9g | **Add nocturnal glucose patterns** — dawn phenomenon, overnight stability, sleep architecture × nighttime glucose | Data | Medium | Should-have |
| 9h | **Add inline definitions/tooltips** — TIR, SD, optimal vs standard range. Bridge vocabulary gap between accessible narrative and clinical data | UX | Low | Must-have |
| 9i | **Connect genomics to glucose** — note on FADS2/MTHFR variants affecting individual glucose metabolism. Genomics × CGM = most scientifically sophisticated content on site | Content | Low | Should-have |
| 9j | **Dynamic pull-quotes** — auto-surface most striking meal comparisons from accumulating data. Content engine | Feature | Med-High | Nice-to-have |
| 9k | **Weave narrative through data** — continue fear→data→understanding→peace arc through data sections, not just bookends | Content | Medium | Must-have |
| 9l | **Expand psychological thread** — 2-3 sentences on health anxiety and monitoring as resolution. Resonates deeply with metabolic-fear audience | Content | Low | Should-have |
| 9m | **Build `/api/meal_responses` endpoint** — backend for dynamic meal table. CGM × MacroFactor cross-reference per logged meal | Architecture | High | Must-have (6-month) |

**Key themes from discussion:**
- The meal response table is the single most differentiated, shareable, and commercially valuable content on the site — and it's a static 5-row HTML table. Making it dynamic and growing is THE priority
- "Protein shake: +6. Pizza: +55." — the most shareable data point on any page (Sofia). Needs share mechanics
- CGM × MacroFactor cross-reference is a unique data asset no other consumer platform has (Attia)
- CGM × genomics connection would be the most scientifically sophisticated content on the site (Rhonda Patrick)
- The narrative intro's emotional arc (fear→data→understanding→peace) should continue through the data, not stop at the hero
- Cross-domain findings (glucose × sleep, glucose × exercise, glucose × stress) are the insights that differentiate from a Dexcom dashboard
- Nocturnal glucose patterns are completely missing (Lisa Park)
- Derek (pre-diabetic) found the page emotionally impactful but hit a vocabulary gap in the data sections
- Tom wants more meals — "like a restaurant review, but for your body." Dynamic meal table = return-visit engine

**Implementation scope:**
- [ ] Design: full editorial alignment pass (same as Sleep — Decision 8a)
- [ ] Frontend: merge hero sections
- [ ] Backend: build `/api/meal_responses` endpoint (CGM × MacroFactor cross-reference)
- [ ] Frontend: dynamic meal response table/explorer — sortable, filterable, growing
- [ ] Frontend: meal card design with spike color coding + mini glucose curves
- [ ] Frontend: add inline tooltips/definitions for clinical terms
- [ ] Frontend: daily glucose curve visualization (288 readings + meal overlays)
- [ ] Content: weave narrative through data sections
- [ ] Content: expand psychological thread on health anxiety
- [ ] Content: genomics × glucose connection note
- [ ] Post-launch: cross-domain visualizations (9f), nocturnal patterns (9g), dynamic pull-quotes (9j)

### DECISION 10: Nutrition Observatory (`/nutrition/`) Deep Review + "The Kitchen" Concept ✅ LOGGED

**Current state:** 1,141-line observatory page. Same generation as Sleep/Glucose — pre-dates editorial design pattern. No narrative intro (the ONLY observatory without one). Hero with 4 gauges (daily avg cal, protein hit %, days logged, avg deficit), 3 pull-quotes (one duplicated from Glucose), macro editorial (3-col: protein/carbs/fat), protein adherence card, 30-day trend chart, 4 N=1 rules, cross-links, narrative + protocols, methodology. Data from `/api/nutrition_overview`. **Missing:** actual meals/food, protein distribution, micronutrients, TDEE adaptation, hydration, psychological dimension.

**Core diagnosis:** The page is all macros and no food. For the domain most readers relate to (eating), it's the most clinical and least human page on the site. Missing its narrative intro, missing actual meals, missing the emotional relationship with food. The data infrastructure is strong but the content layer needs transformation.

**Approved recommendations:**

| # | Recommendation | Category | Effort | Priority |
|---|---------------|----------|--------|----------|
| 10a | **Add narrative intro** — the only observatory without one. Find the personal truth. "Every diet I've ever done worked until it didn't" energy | Content | Low | Must-have |
| 10b | **Add Top Meals section** — most frequently logged meals with macro profile, glucose response grade, protein-per-calorie ranking. "People eat meals, not grams" | Feature | Medium | Must-have |
| 10c | **Add protein distribution visualization** — per-meal breakdown showing leucine threshold met/missed at each meal slot, not just daily total | Data | Medium | Must-have |
| 10d | **Add micronutrient section** — key gaps relative to genomics: choline (550mg+ PEMT target), vitamin D, omega-3, folate. SNPs → dietary data | Data/Content | Medium | Should-have |
| 10e | **Add TDEE adaptation tracking** — MacroFactor adaptive TDEE over time. Early warning for metabolic adaptation/stall | Data | Medium | Should-have |
| 10f | **Fix pull-quote duplication** — Pull-Quote #2 identical to Glucose page. Each observatory needs unique findings | Content | Low | Must-have |
| 10g | **Align to editorial design pattern** — same pass as Sleep and Glucose | Design | Med-High | Must-have |
| 10h | **Add behavioral trigger analysis** — cross-reference nutrition misses with sleep, stress, travel, weekday/weekend patterns | Data | Medium | Should-have |
| 10i | **Add psychological dimension** — acknowledge emotional relationship with food. "The part they don't put in a macro tracker" (Conti) | Content | Low | Should-have |
| 10j | **Hydration data** — water intake tracking, correlation with energy/recovery | Data | Low | Nice-to-have |
| 10k | **Food visuals** — category icons or eventually photos next to top meals. Nutrition is the one domain where images add warmth | Design | Low | Nice-to-have |

**"THE KITCHEN" — New Serialized Concept ✅ APPROVED (unanimous enthusiasm)**

| Phase | Scope | Timeline | Status |
|-------|-------|----------|--------|
| Phase 1 | Teaser landing page at `/kitchen/` — describes concept, captures subscribers. "Weekly AI-generated meal prep based on what's working." | April 1 or Month 1 | New |
| Phase 2 | Public meal database — most common meals, top by protein/cal, glucose grades, prep rotations | Month 1-2 | Roadmap |
| Phase 3 | Serialized weekly email "The Kitchen" — AI meal prep, recipes, shopping lists from real data. Second subscription channel | Month 2-3 | Roadmap |

**Key quotes:**
- Sofia: "The Chronicle is the heart. The Kitchen is the hands."
- Raj: "This is the second subscription that has larger reach potential than the first."
- Jordan: "This is eventually a product."
- Tom: "What does 180g of protein look like in a day? How many chicken breasts?"
- Margaret: "This page needs its opening line."
- Conti: "For a man who reached 302 pounds, food is not just fuel — it's coping."

**Implementation scope:**
- [ ] Content: write narrative intro for nutrition (find the personal food truth)
- [ ] Design: editorial alignment pass (same as Sleep/Glucose)
- [ ] Backend: build top meals endpoint from MacroFactor data (most frequent, macro profile, glucose grade)
- [ ] Frontend: Top Meals section with food names, macro bars, glucose response grades
- [ ] Frontend: protein distribution per-meal visualization (breakfast/lunch/dinner/snacks)
- [ ] Frontend: fix duplicated pull-quote (replace with unique nutrition finding)
- [ ] Content: add psychological dimension section
- [ ] API: micronutrient summary endpoint (key gaps vs genomic targets)
- [ ] API: TDEE trend over time from MacroFactor adaptive algorithm
- [ ] Content: The Kitchen teaser landing page (April 1 stretch goal)
- [ ] Post-launch: behavioral trigger cross-analysis (10h), hydration (10j), food visuals (10k)
- [ ] Post-launch: The Kitchen Phase 2 (meal database) and Phase 3 (weekly email)

### DECISION 11: Training Observatory (`/training/`) Deep Review ✅ LOGGED

**Current state:** 964-line observatory page. Has the editorial design pattern CSS (unlike Sleep/Glucose) but is structurally thinner. No narrative intro. Hero with 4 gauges (Z2 avg, workouts 30d, avg strain, strength sessions), 3 pull-quotes, Zone 2 + volume 3-column editorial, activity mix chips, 12-week volume bar chart, 4 N=1 rules, cross-links (nutrition × deficit, sleep × morning workouts), narrative ("centenarian decathlon"), methodology. Data from `/api/training_overview`. Banister CTL/ATL/TSB model exists in backend API but is NOT visualized on the page. Centenarian benchmark data exists in `get_centenarian_benchmarks` but not shown. HR recovery data exists in `get_hr_recovery_trend` but not shown.

**Zone 2 data source confirmation:** Garmin HR stream → Strava → platform. Zone 2 = 60-70% max HR (114-133 bpm). Calculated via TRIMP (HR × time). Whoop HR zones as secondary source. No Strava Premium required.

**Core diagnosis:** The page has the best conceptual framework on the site ("Training for 80, not for 30" / centenarian decathlon) but shows the *least interesting* data from its own API. CTL/ATL/TSB, centenarian benchmarks, HR recovery, and progressive overload data all exist in the backend but don't appear on the page. Needs to reflect the full movement spectrum (cardio + lifting + outdoor + sport), not bias toward any single modality.

**Approved recommendations:**

| # | Recommendation | Category | Effort | Priority |
|---|---------------|----------|--------|----------|
| 11a | **Add narrative intro** — the boom-bust fitness cycle. "I've been the marathon guy and the couch guy. This page is about breaking the cycle." | Content | Low | Must-have |
| 11b | **Add centenarian decathlon benchmark dashboard** — visual progress bars: current lifts vs Attia's centenarian targets. Use existing `get_centenarian_benchmarks` data. Organizing framework for the page | Feature | Medium | Must-have |
| 11c | **Add fitness-fatigue chart (CTL/ATL/TSB)** — Banister model data exists in API. Visualize the fitness curve, fatigue spikes, form status. Most technically impressive training viz | Data viz | Medium | Must-have |
| 11d | **Add HR recovery trend** — strongest exercise-derived mortality predictor. Data in `get_hr_recovery_trend`. Current HRR, trend, clinical classification | Data | Medium | Should-have |
| 11e | **Add Zone 2 efficiency by activity type** — which activities deliver most Z2 minutes/hour? Dynamic ranking (Huberman) | Data | Medium | Should-have |
| 11f | **Add strength progressive overload tracking** — 1RM trends, volume load progression. "Am I maintaining strength while losing fat?" Hevy data exists | Data | Medium | Should-have |
| 11g | **Add activity balance visualization** — donut/pie weekly split: cardio types, strength, rest. Is the mix healthy? | Data viz | Low | Should-have |
| 11h | **Replace basic gauge metrics** — swap counts (workouts, sessions) for intelligence (form status, injury risk, fitness trend) | UX | Medium | Should-have |
| 11i | **Add inline definitions** — Zone 2, ACWR, strain, TSB, 80/20 polarization. Bridge vocabulary gap | UX | Low | Must-have |
| 11j | **Verify Zone 2 pipeline** — confirm Garmin HR → Strava → platform TRIMP calculation is active and accurate before launch | Technical | Low | Must-have |
| 11k | **Reflect full movement spectrum** — running, hiking, rucking, walking, cycling, sport, lifting. Page should not feel biased toward any single modality | Content/IA | Medium | Must-have |

**Key themes from discussion:**
- The centenarian decathlon is the single most compelling fitness concept on the site — should be the organizing framework, not a paragraph (Attia, Lena, Sofia)
- The backend has world-class training intelligence (Banister model, ACWR, HR recovery, centenarian benchmarks) and the page shows almost none of it
- The page needs to feel like it covers Matthew's full movement life — running, hiking, rucking, cycling, soccer, lifting — not just one modality
- Tom and Derek want the concept (train for 85) but hit a vocabulary wall (Zone 2, ACWR, TSB)
- Strength tracking is thin — needs progressive overload, 1RM trends, not just session counts (Norton)
- HR recovery is missing entirely and is the strongest exercise-derived mortality predictor (Rachel)
- The fitness-fatigue chart would be the most technically impressive visualization on the site (Sarah Chen, Kenji)

**Implementation scope:**
- [ ] Content: write narrative intro (boom-bust fitness cycle story)
- [ ] Frontend: centenarian benchmark dashboard (progress bars, current vs targets)
- [ ] Frontend: CTL/ATL/TSB fitness-fatigue chart from existing API data
- [ ] Frontend: HR recovery trend section from `get_hr_recovery_trend`
- [ ] Frontend: Zone 2 efficiency by activity type (dynamic ranking)
- [ ] Frontend: strength progressive overload section from Hevy data
- [ ] Frontend: activity balance donut/pie chart
- [ ] Frontend: replace gauge metrics with intelligence metrics
- [ ] Content: inline definitions for all technical terms
- [ ] Technical: verify Garmin → Strava → platform Zone 2 pipeline accuracy
- [ ] Content: ensure page language/sections cover full activity spectrum
- [ ] Post-launch: chart interactivity, periodization phase display

### DECISION 12: _(pending — next page)_

---

## OPEN QUESTIONS / PARKING LOT

- Labs/Bloodwork page (BL-02) — Rachel requested, not scoped for April 1 but flagged as priority
- "For Builders" page content — needs real content or removal before launch

---

## NET-NEW PAGES IDENTIFIED

| Page | Priority | Status | Source |
|------|----------|--------|--------|
| Labs / Bloodwork | Post-launch | BL-02 backlog | Rachel (cold reviewer) |
| For Builders (content) | April 1 if nav stays | BL-01 backlog | Kenji (cold reviewer) |
| **The Kitchen** (teaser landing) | April 1 stretch / Month 1 | Decision 10 | Sofia, Jordan, Raj, Tom, Derek — unanimous |
| **The Kitchen** (meal database) | Month 1-2 | Decision 10 roadmap | Product Board |
| **The Kitchen** (weekly email) | Month 2-3 | Decision 10 roadmap | Product Board |

---

### DECISION 11: Training Observatory (`/training/`) Deep Review ✅ LOGGED

**Current state:** 964-line observatory page. Same generation as Sleep/Glucose/Nutrition. Hero with 4 gauges (Zone 2 avg, workouts 30d, avg strain, strength sessions). Zone 2 editorial 3-col, activity mix chips, 12-week trend chart, 3 pull-quotes, 4 N=1 rules, cross-links, narrative ("Training for the centenarian decathlon") with 5 protocols. Data from `/api/training_overview`. **Critical gap:** Banister CTL/ATL/TSB model + ACWR computed nightly but NOT on the page. Centenarian benchmarks referenced but not shown. Strength limited to session count — no 1RM, no progressive overload charts.

**Zone 2 data source confirmed:** Garmin HR zones via Strava free tier. No Strava Premium needed.

**Approved recommendations:**

| # | Recommendation | Category | Effort | Priority |
|---|---------------|----------|--------|----------|
| 11a | **Add CTL/ATL/TSB visualization** — Banister fitness-fatigue model. THE differentiator from Strava | Data viz | Medium | Must-have |
| 11b | **Add centenarian benchmark tracker** — current 1RM vs Attia targets. Progress bars per compound lift | Data viz | Medium | Must-have |
| 11c | **Add narrative intro** — Matthew's relationship with exercise. Passion vs consistency tension | Content | Low | Must-have |
| 11d | **Add compound lift progress charts** — squat/deadlift/bench/OHP 1RM over time. Equal editorial weight to Zone 2 | Data viz | Medium | Must-have |
| 11e | **Add ACWR injury risk indicator** — traffic light with plain-language explanation | Data viz | Low | Should-have |
| 11f | **Activity diversity visualization** — Attia-pillar radar: Zone 2, strength, stability, Zone 5, sport coverage | Data viz | Medium | Should-have |
| 11g | **Add HR recovery trend** — strongest exercise-derived mortality predictor. Platform has the tool | Data viz | Medium | Should-have |
| 11h | **Time-of-day training distribution** — when does Matthew train? Protocol insight | Data | Low | Nice-to-have |
| 11i | **GPS route traces** — minimalist Strava GPS thumbnails. Unique visual richness | Design | Medium | Nice-to-have |
| 11j | **Real-world capability milestones** — first 5K, first 20-mile ride, first soccer match | Content | Low | Should-have |
| 11k | **Editorial alignment pass** — apply current observatory design pattern | Design | Med-High | Must-have |
| 11l | **Zone 2 data source transparency note** — Garmin HR zones, no Strava Premium needed | Content | Low | Should-have |
| 11m | **Plain-language Banister translations** — "Fitness base is building" not "CTL: 5.06" | UX | Low | Must-have (with 11a) |

**Key diagnosis:** Backend has F1 telemetry, page shows a speedometer. Strength massively undersold vs Zone 2. No narrative intro. Activity diversity missing. Centenarian benchmarks are the most motivating framing but invisible.

### DECISION 12: _(pending — next page)_

---

_This document is updated live throughout the offsite. Each decision gets a numbered entry with vote count, implementation tasks, and conditions._
