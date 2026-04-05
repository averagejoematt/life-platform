# Observatory Pages v2 — Full Design & Feature Specification

> **Version:** 2.0 (2026-03-30)
> **Authors:** Product Board of Directors (full convene)
> **Audience:** Claude Code implementation
> **Status:** PENDING Matthew review → handover to Claude Code
> **Supersedes:** OBSERVATORY_UPGRADE_SPEC.md (v1.0, 2026-03-29) — which covered Training/Nutrition only. This spec adds Inner Mind overhaul + new Physical page + deeper design direction for all four.

---

## Product Board Opening Statements

**Mara Chen (UX Lead):** "The core problem across all three existing pages is the same: they're structured as articles, not observatories. Someone visits once, reads top-to-bottom, and leaves. We need to flip the information hierarchy — data and visualizations first, narrative context second. The reader should see something *changing* every time they visit."

**Raj Mehta (Product Strategy):** "The engagement metric that matters is return visits. Right now these pages have zero pull-back mechanisms. If someone comes back in a week, they see the same page with slightly different numbers buried in the same prose. We need above-the-fold data that visibly changes, charts that tell a story over time, and AI analysis that updates with each data cycle."

**Tyrell Washington (Web Design):** "The editorial design system is genuinely world-class — the gauge rings, pull-quotes with evidence badges, monospace headers with trailing em-dashes. We don't throw any of that out. But the current pages front-load narrative and bury data. I want every page to open with a visual data punch within 3 seconds, then weave narrative around and between the data sections. Think Bloomberg Terminal meets The New Yorker."

**Sofia Herrera (CMO):** "The shareable moment on each page needs to be a chart or visualization, not a paragraph. Nobody screenshots a pull-quote. They screenshot a striking chart with an insight annotation. Every page needs at least 2-3 'screenshot moments.'"

**Dr. Lena Johansson (Science Advisor):** "The Inner Mind page is the most important overhaul. The science of mental wellbeing measurement is genuinely novel territory for a public-facing personal health site. If we get this right — showing how journaling themes, mood tracking, social connection metrics, and behavioral data can be combined with AI analysis — it's unlike anything else on the internet."

**Jordan Kim (Growth):** "Pages that are data-rich and updating keep readers longer AND get shared more. The current pages average maybe 90 seconds of scroll time. We should be targeting 3-5 minutes per page. That means multiple interactive charts, AI commentary sections, and content depth that rewards scrolling."

**Ava Moreau (Content Strategy):** "Each page needs a resident AI expert voice — not just data, but interpretation. The Nutrition page should have 'Dr. Webb's Analysis' sections. Training should have 'Coach's Notes.' Mind should have 'Dr. Conti's Observations.' These create a reason to come back — the expert has a new take every time the data updates."

**James Okafor (CTO):** "Everything proposed here is buildable with existing data. I've audited the MCP tools and DynamoDB partitions — the data exists for 90%+ of what follows. The API extensions are incremental, not architectural changes."

---

## Design Principles (All Pages)

### 1. Data First, Narrative Second
Every page opens with visual data within the first viewport. Narrative text wraps around and between data sections, not before them. The hero section keeps its editorial gauges (these are excellent) but any long prose intro moves below the first data section.

### 2. Every Visit Shows Something New
Above-the-fold numbers and charts must reflect the most recent data pull. Date stamps ("Last updated: March 30, 2026") visible on every major section. Trend arrows (↑↓→) on every metric that has a 30-day comparison.

### 3. AI Expert Voice Per Page
Each page gets a named AI expert from the Personal Board who provides rotating analysis. This is not static — it regenerates with each data cycle (weekly at minimum). Styled as a distinct callout block with the expert's name and a brief, opinionated interpretation of the current data.

### 4. Chart-Dense, Scroll-Rewarding
Target: minimum 3 interactive/dynamic charts per page. Charts should be the visual anchors — large enough to be the primary content, not decorative sidebars. Every chart gets an insight annotation (one sentence explaining what the viewer should notice).

### 5. Screenshot Moments
At least 2 sections per page designed explicitly for social sharing — visually striking, self-contained, branded (the AMJ dark aesthetic + accent color). Think: a 30-day calorie chart with macro distribution bars. A mood-over-time heatmap. A weekly training volume breakdown by modality.

### 6. Cross-Observatory Links
Each observatory page links to at least 2 others with data-backed context ("Your training volume correlates with your sleep quality — see the Sleep Observatory"). These are not just nav links — they show the actual correlation data point.

---

## Page 1: Inner Mind Observatory — FULL OVERHAUL

### Current State Assessment

**What exists today (12 sections):**
1. Hero with 4 gauges (mood score, willpower, journal entries, state-of-mind logs)
2. Confessional narrative (long prose about avoiding this pillar)
3. Causal hierarchy callout
4. Five promises
5. Vice streak portfolio
6. State-of-mind bar charts (hidden until data)
7. Social connection intentions
8. Causal relationships section
9. Clinical naming section
10. Journal excerpt section
11. Intelligence detection (future/empty)
12. Future vision section

**The Board's diagnosis:** This page is ~70% prose, ~20% static data, ~10% dynamic data. It reads like a confessional essay that was published once and never updated. The vice streaks are the only truly dynamic element. The "five promises," "clinical naming," and "what this page will become" sections are all static text that will be identical every visit. For a page the Board has unanimously called the platform's biggest differentiator, it massively underdelivers on showing what AI + data + personal science can actually do for mental wellbeing.

### The New Vision

**"The Inner Mind Observatory isn't a blog post about feelings. It's the world's first public-facing AI-augmented mental health data dashboard — showing in real time how journaling, mood tracking, meditation, social connection, and behavioral patterns combine to create a measurable picture of inner life."**

### Hero Section — KEEP + ENHANCE

**Keep:** 2-column hero grid, animated gauge rings, violet accent color
**Enhance:**
- Gauge 1: **Overall Mind Score** (composite of mood, journal consistency, vice streaks, connection) — currently "mood score", rename to reflect breadth
- Gauge 2: **Journal Streak** (consecutive days with entries) — replaces "willpower" which is abstract
- Gauge 3: **Meditation Minutes** (30-day total from Apple Health breathwork/mindful_minutes) — NEW data, currently uncaptured on this page
- Gauge 4: **Social Connection Hours** (30-day from Habitify/manual tracking) — replaces generic "state-of-mind logs"

**Sub-headline change:** From "The pillar I avoided building" → "Measuring what most people never measure" (the avoidance story can be a brief narrative below, but the hero should be aspirational, not confessional)

### Section Architecture — NEW ORDER

The page should be restructured into this order, following the "data first" principle:

#### Section 1: Journal Intelligence Dashboard (NEW — THE FLAGSHIP SECTION)
**Position:** Immediately below hero. This is the centerpiece.
**Rationale (Lena):** "This is where you prove that journaling + AI produces genuine insight. No other site shows this."

**Components:**

**1a. Journal Theme Heatmap (30 days)**
A calendar-style heatmap (similar to GitHub contributions) where each day is colored by dominant journal theme. Color-coding by theme category: personal growth (violet), relationships (blue), health/body (green), work/ambition (amber), anxiety/stress (red), gratitude (teal).

- Data source: Notion journal entries → `tools_journal.py` already has theme extraction
- API requirement: New endpoint or section in mind overview: `journal_themes: [{ date, themes[], dominant_theme, word_count, sentiment_score }]`
- Clicking a day shows that day's theme summary (not the journal entry itself — privacy boundary)

**1b. Top Themes — Rolling 30 Days**
Horizontal bar chart showing the 5-8 most frequent journal themes, with percentage of entries mentioning each.

- Shows theme frequency AND trend (was this theme more or less present vs prior 30 days)
- Example: "Self-compassion: 42% of entries (↑ from 28%)" — "Work stress: 31% (↓ from 45%)"

**1c. Sentiment Trend Line (90 days)**
A line chart showing rolling 7-day average sentiment score from journal entries. Annotated with significant events (started new habit, broke vice streak, etc.)

- Data source: Journal entry sentiment analysis from `tools_journal.py`
- Annotation overlay: Major events from timeline/chronicle

**1d. Word Cloud or Topic Clusters**
Visual representation of what Matt is writing about. Updated weekly. Not the hackneyed random-word-cloud — a structured cluster diagram showing related themes connected by lines, with circle size proportional to frequency.

#### Section 2: State of Mind Tracker (UPGRADE FROM HIDDEN)
**Current:** Hidden section that shows bars only when mood data exists
**New:** Always visible, prominent section

**Components:**

**2a. Daily State-of-Mind Sparkline (30 days)**
A sparkline chart showing the state-of-mind rating (1-10 or whatever scale) for each of the last 30 days. Missing days shown as gaps (the gap IS the data — it shows when tracking lapsed).

**2b. State Distribution**
Donut or horizontal bar showing distribution of states: e.g., "Good: 45%, Neutral: 30%, Low: 15%, Untracked: 10%"

**2c. Time-of-Day Mood Pattern**
If state-of-mind logs have timestamps: morning vs afternoon vs evening mood averages. Shows circadian mood patterns.

- Data source: `tools_health.py` mood/state data, Habitify check-ins
- API requirement: `state_of_mind_overview: { daily_scores[], distribution{}, time_of_day_pattern{}, streak, longest_streak }`

#### Section 3: Vice Streak Portfolio (KEEP — this is excellent)
**No design changes.** The vice cards with streak counters, "why" text, and broken/active states are the best section on the current page. Keep them exactly as-is.

**One addition:** Below the grid, add a **Vice Streak Timeline** — a horizontal timeline showing when each vice was broken over the past 90 days, giving a visual history of relapses and recovery periods.

#### Section 4: Meditation & Breathwork Observatory (NEW)
**Rationale:** Apple Health captures breathwork_minutes and mindful_minutes. This data surfaces NOWHERE on the site currently.

**Components:**

**4a. Monthly Calendar with Session Markers**
Calendar grid (current month) with circles on days where meditation/breathwork occurred. Size proportional to duration.

**4b. Metrics Row**
3-column editorial spread:
- Sessions this month / avg duration / total minutes
- Trend vs prior month
- Longest consecutive streak

**4c. Breathwork × HRV Correlation**
Scatter plot or paired-line chart: breathwork session days vs that day's HRV reading (from Whoop). With Henning Brandt confidence annotation ("Preliminary — N=X observations. r=0.XX")

- Data source: `apple_health` partition (breathwork_minutes, mindful_minutes) + `whoop` partition (HRV)
- API: Extend mind overview with `meditation: { sessions[], monthly_total, streak, hrv_correlation{} }`

#### Section 5: Social Connection Dashboard (OVERHAUL)
**Current:** Static list of "people I'm trying to reconnect with" with progress bars
**Problem:** This is a static intention list, not a data observatory. It never changes unless manually updated.

**New design:**

**5a. Connection Score (composite)**
Single metric: how socially connected has Matt been in the last 30 days? Based on: meaningful conversations logged, social events attended, outreach attempts made, connection quality ratings.

**5b. Social Activity Timeline**
Timeline cards showing recent social interactions — not names (privacy), but categories: "Family call — 45 min", "Friend meetup — 2 hrs", "Team social — 1 hr". Shows frequency and depth.

**5c. Loneliness vs Connection Trend**
If mood/state data captures connection quality: a 30-day trend showing the interplay between social activity frequency and reported wellbeing.

**5d. Connection Goals Progress**
Keep the intention cards from current design, but make them measurable: "Call [person] weekly — 3/4 weeks this month ✓"

- Data source: Habitify connection habits, manual logs, `tools_social.py`
- API: `social_connection_overview: { score, activity_timeline[], trend[], goal_progress[] }`

#### Section 6: AI Psychiatrist's Analysis (NEW — THE DIFFERENTIATOR)
**Rationale (Ava, Sofia):** "This is the section that makes people come back. An AI expert reading the journal themes, mood patterns, vice streaks, and social data — and offering a weekly interpretive summary."

**Design:** Full-width card with left violet accent border. Named voice: "Dr. Conti's Observations"

**Content (auto-generated weekly from data):**
- 2-3 paragraph analysis of recent inner life patterns
- Identifies themes: "Journal entries this week show increased focus on self-compassion, coinciding with the 14-day alcohol-free streak. Mood scores are trending upward for the first time in 3 weeks."
- Flags concerns: "Social connection hours dropped 40% this week. Research consistently shows that isolation is the #1 predictor of poor mental health outcomes."
- Suggests experiments: "Consider: does morning journaling produce different mood outcomes than evening journaling? You have enough data to test this."

**Evidence badge:** "Generated from 30 days of journal entries, mood logs, and behavioral data"

- API: New endpoint `mind_ai_analysis` — Lambda generates analysis from combined data sources, cached weekly
- This is the single most important new section on the entire platform

#### Section 7: Causal Relationships (KEEP + ENHANCE)
**Keep:** The directional arrows showing how inner life drives other domains
**Enhance:**
- Make the correlations dynamic (pull actual r-values from data)
- Add new pathways: Journaling → Mood, Meditation → HRV, Social Connection → Mood, Vice Streaks → Self-Reported Wellbeing
- Each arrow should have a confidence badge (Henning Brandt standard)

#### Section 8: Experiments in Mental Wellbeing (NEW)
**Rationale (Raj):** "The experiments page exists but nobody goes there. Put active mental health experiments directly on this page."

**Content:**
- Currently running experiments related to mind pillar
- Format: experiment card with hypothesis, start date, current status, preliminary findings
- E.g., "Experiment: Does 10-minute morning meditation improve afternoon mood scores?"

#### Section 9: The Science of What We're Measuring (REPLACES "Clinical Naming" + "Five Promises" + "What This Page Will Become")
**Rationale (Mara):** "The current static sections are crutches. Replace them with a single 'How this works' accordion that explains the methodology without taking up permanent scroll real estate."

**Design:** Collapsible accordion sections:
- What "inner life" metrics mean and why they matter
- The science behind journaling as data (citing research)
- How the AI analysis works (transparency)
- Data sources feeding this page
- Measurement limitations and what we can't track

#### Section 10: Narrative Close (KEEP but shorten)
**Keep** the editorial narrative section but reduce from the current confessional essay to 2-3 paragraphs max. The story of avoiding this pillar is good — but it's currently the page opener, and it should be the closer. Readers who've scrolled through all the data now get the emotional context.

#### Section 11: Cross-Observatory Links (KEEP)
With enhanced data: "Sleep quality r=0.34 with mood — See Sleep Observatory →"

#### Section 12: Methodology (KEEP)
Standard observatory footer.

### Sections REMOVED
- **Five Promises** → these were placeholder content. If they become measurable goals, they go in Section 5 (goals progress). Otherwise, cut.
- **"What this page will become"** → the page now IS what it was supposed to become. Cut.
- **"Intelligence detection (future/empty)"** → replaced by Section 6 (AI Analysis) which actually works.
- **Confessional narrative as page opener** → moved to Section 10 as closer, shortened.
- **Causal hierarchy callout** → absorbed into Section 7 with real data.

---

## Page 2: Nutrition Observatory — TARGETED UPGRADES

### Current State Assessment

The Nutrition page is the most complete observatory. It already has 18+ sections covering macros, protein, meals, eating patterns, behavioral triggers, hydration, and more. Matthew's critique is correct — it has the data infrastructure but doesn't fully exploit it visually or analytically.

### What's KEEPING (no changes)
- Hero section with gauges (calories, protein, deficit, fiber)
- Narrative intro pull-quote
- Daily average macro breakdown
- Protein adherence section
- Per-meal protein distribution
- Pull-quotes with evidence badges
- Top meals section
- Protein source breakdown
- Weekday vs weekend analysis
- Eating window section
- Caloric periodization
- TDEE adaptation tracking
- Behavioral trigger analysis
- Micronutrient gaps (to be enhanced)
- Hydration section (to be enhanced)
- N=1 nutrition rules
- Cross-links
- Methodology

### NEW SECTIONS & ENHANCEMENTS

#### Enhancement A: 30-Day Calorie & Macro Distribution Chart (MAJOR NEW CHART)
**Matthew specifically requested this.**

**Design:** Full-width chart section positioned immediately after the hero gauges (before any prose).

**Chart 1: Stacked Bar Chart — 30 Days of Calories with Macro Breakdown**
- X-axis: 30 days
- Y-axis: Calories
- Each bar is stacked: protein (green), carbs (amber), fat (rose)
- Horizontal target line at calorie goal
- Days above target in muted red background, below in muted green
- Hover tooltip: exact cal/pro/carb/fat for that day

**Chart 2 (paired): Macro Ratio Donut**
- Side-by-side with the bar chart
- Shows 30-day average macro split as a donut: protein %, carbs %, fat %
- Center text: total average calories

**Insight annotation:** Auto-generated one-liner: "Protein has been 31% of total calories over 30 days — above the 25% target. Carb intake tends to spike on weekends (avg +47g Sat/Sun vs weekday)."

- Data source: MacroFactor daily records — `calories_kcal`, `protein_g`, `carbs_g`, `fat_g`. All in DDB.
- API: Extend `nutrition_overview` to include `daily_macros_30d: [{ date, cal, pro, carb, fat }]`
- This is the #1 visual upgrade for Nutrition

#### Enhancement B: AI Nutritionist Analysis (NEW)
**Named voice: "Dr. Webb's Analysis"**

Same pattern as Mind page's AI expert — weekly auto-generated analysis:
- Current dietary adherence assessment
- Notable patterns (weekend overshoot, protein consistency)
- Specific food recommendations based on gaps
- One scientific insight tied to current data

**Design:** Full-width amber-accented card with evidence badge. 2-3 paragraphs.

- API: New endpoint `nutrition_ai_analysis` — Lambda generates from combined MacroFactor + food delivery + CGM data

#### Enhancement C: Common Ingredients & Recipe Intelligence (NEW)
**Matthew requested this specifically: "showing common meals, recipes, the ingredients I use the most"**

**Design:** Two sub-sections

**C1. Top 15 Ingredients (30 days)**
Grid of ingredient cards (5 per row, 3 rows):
- Ingredient name
- Frequency (appeared in X meals)
- Primary macro contribution (e.g., "Chicken Breast → 48g protein/day avg")
- Trend badge (more/less than prior 30 days)

**C2. Signature Meals**
The top 5 most frequently logged complete meals, each shown as a card:
- Meal name / description
- Full macro breakdown (cal/pro/carb/fat)
- CGM grade if glucose data available
- Time of day typically eaten
- Frequency badge: "Eaten 18 times in 30 days"

- Data source: MacroFactor `food_log[]` — aggregate by `food_name`, deduplicate, rank
- API: Extend `handle_frequent_meals()` to return ingredient-level breakdown + complete-meal patterns

#### Enhancement D: Calorie Trend with Moving Average (UPGRADE)
**Current:** 30-day calorie trend chart exists but is basic
**New:** Enhance with:
- 7-day moving average overlay line (smooths noise, shows real trend)
- Color-coded zones: deficit (green background), maintenance (neutral), surplus (red background)
- Annotated events: "Started new cut", "Holiday weekend", "Sick days" from timeline data
- Toggle between 30/60/90-day views

#### Enhancement E: Restaurant & Takeout Insights (MAKE VISIBLE)
**Current:** Section exists but `display:none` — likely waiting for data pipeline
**Action:** Unhide and populate with food_delivery data:
- Orders this month + trend
- Average delivery spend
- DoorDash/UberEats breakdown
- "Delivery days" vs "home cooking days" calorie comparison
- Food delivery index (0-10, already computed)

#### Enhancement F: Hydration Deep-Dive (UPGRADE)
**Current:** Basic hydration section
**New additions:**
- 30-day daily water intake sparkline chart
- Average vs target with percentage
- Training day vs rest day hydration comparison
- Weekend vs weekday hydration gap

#### Enhancement G: Macro Deep-Dives (MAKE VISIBLE)
**Current:** Section exists but `display:none`
**Action:** Unhide with carbs/fats/fiber individual tracking:
- Each macro gets: 30-day average, target, adherence %, trend sparkline
- Fiber gets special callout (longevity-linked nutrient)
- Formatted as 3-column editorial spread

#### Enhancement H: Kitchen Teaser Enhancement
**Current:** Link to /kitchen/ page
**Upgrade:** Show 2-3 rotating recent recipes/meals directly on nutrition page as preview cards, linking to kitchen for full recipes

### Visual Priority Order for Nutrition
1. **30-Day Calorie + Macro Stacked Bar** (Enhancement A) — this is the hero chart
2. **AI Nutritionist Analysis** (Enhancement B) — the pull-back reason
3. **Common Ingredients Grid** (Enhancement C) — the most relatable content
4. **Enhanced Calorie Trend** (Enhancement D) — trend storytelling
5. **Restaurant Insights** (Enhancement E) — real-world honesty
6. **Hydration Deep-Dive** (Enhancement F)
7. **Macro Deep-Dives** (Enhancement G)

---

## Page 3: Training Observatory — TARGETED UPGRADES

### Current State Assessment

Training already has 17+ sections and substantial depth (Banister model, ACWR, centenarian benchmarks, 1RM tracking). Matthew's critique: it lacks visual engagement for the casual reader, especially around daily exercise breakdowns and resistance training detail.

### What's KEEPING (no changes)
- Hero gauges (Zone 2, workouts, strain, strength)
- Editorial narrative pull-quotes
- Training volume breakdown
- Activity breakdown (30 days) — but enhancing
- Walking & steps section
- Breathwork section
- Weekly movement section
- Banister fitness-fatigue model
- ACWR section
- 12-week training volume chart
- Centenarian decade targets
- 1RM progress sparklines
- Strength deep-dive (hidden — needs unhiding)
- Training balance radar
- HR recovery trend
- When I train (time of day)
- Recent routes
- Capability milestones
- Training hypotheses
- Narrative close
- Methodology

### NEW SECTIONS & ENHANCEMENTS

#### Enhancement A: Daily Exercise Minutes Bar Chart (MAJOR NEW CHART)
**Matthew specifically requested this: "a graph of each amount of exercise each day in minutes, but a bar chart that breaks down how many minutes in the gym, vs walking, vs stretching etc."**

**Design:** Full-width stacked bar chart, positioned immediately after hero gauges.

**Chart: 30-Day Exercise Minutes by Modality**
- X-axis: 30 days
- Y-axis: Minutes
- Each bar stacked by modality with distinct colors:
  - Strength training (crimson)
  - Walking (sky blue)
  - Cycling (amber)
  - Stretching/Mobility (teal)
  - Soccer (orange)
  - Hiking (forest green)
  - Breathwork (violet)
  - Other (gray)
- Zero-activity days shown as empty columns (the gap IS the data)
- Horizontal reference line: "60 min/day target"
- Hover tooltip: exact breakdown per modality for that day

**Insight annotation:** Auto-generated: "Average 72 minutes/day of total movement. Strength training accounts for 35% of active time. Walking is the most consistent modality (28/30 days)."

- Data source: Strava (`sport_type` + `duration_minutes`), Garmin (daily summary), Apple Health (breathwork/flexibility)
- API: Extend `training_overview` with `daily_modality_minutes_30d: [{ date, strength_min, walking_min, cycling_min, stretching_min, soccer_min, hiking_min, breathwork_min, other_min, total_min }]`

**This is the #1 visual upgrade for Training.**

#### Enhancement B: Daily Step Count Chart (NEW)
**Matthew requested: "step counts over days"**

**Design:** Area chart or bar chart below the walking section.

**Chart: 30-Day Daily Step Count**
- X-axis: 30 days
- Y-axis: Steps
- 7-day moving average overlay line
- Horizontal lines: 7,500 steps (minimum health threshold), 10,000 steps (common target)
- Color coding: days below 7,500 in muted red
- Weekend vs weekday visual distinction (lighter bars for weekends)

- Data source: Garmin `steps` field — already in DDB as `garmin` partition
- API: Include `daily_steps_30d: [{ date, steps, is_weekend }]` in training overview

#### Enhancement C: AI Training Coach Analysis (NEW)
**Named voice: "Coach's Notes — Dr. Sarah Chen"**

Weekly auto-generated analysis:
- Current training load assessment (overreaching? undertrained? optimal?)
- Modality balance critique
- PPL program adherence and volume progression
- Injury risk flags from ACWR data
- Recovery adequacy based on Whoop recovery + sleep data
- One specific suggestion for the coming week

**Design:** Full-width crimson-accented card. 2-3 paragraphs. Evidence badge: "Based on Strava, Hevy, Whoop, and Garmin data from the past 7 days"

- API: New endpoint `training_ai_analysis` — Lambda-generated weekly

#### Enhancement D: Resistance Training Deep-Dive (UNHIDE + EXPAND)
**Current:** `#t-strength-dive` section exists but `display:none`
**Matthew requested: "more analysis about my resistance training, how that is going"**

**Unhide and populate with:**

**D1. Current Program Badge**
"Currently running: Jeff Nippard's Push/Pull/Legs" — with program start date and weeks completed.
- Data source: Config value or derived from Hevy workout names

**D2. Weekly Volume Load Trend (12 weeks)**
Line chart: total volume (sets × reps × weight) per week.
- Shows progressive overload trajectory
- Annotated with deload weeks or missed weeks

**D3. Muscle Group Balance**
Horizontal bar chart: Push / Pull / Legs / Core volume distribution (last 30 days)
- Shows imbalances: if Pull is 15% and Push is 40%, that's flagged
- Data source: Hevy exercise names mapped to muscle groups (via config)

**D4. Exercise Variety & Frequency**
Grid of most-used exercises (top 12):
- Exercise name
- Times performed (30d)
- Max weight / recent 1RM estimate
- Volume trend arrow

**D5. Session Duration Distribution**
Small histogram: how long are gym sessions? (30-45 min / 45-60 / 60-75 / 75-90 / 90+)

- Data source: Hevy data — exercise_name, sets, reps, weight, workout_date, timestamps
- API: New endpoint `strength_deep_dive` or extend training overview with `strength: { program, volume_trend[], muscle_balance{}, top_exercises[], session_duration_distribution[] }`

#### Enhancement E: Activity Deep-Dive Cards (UPGRADE from chips)
**Current:** Simple chips showing activity type + count
**New:** Each modality gets an expandable card:

**Card design:**
- Left-accent border in modality color
- Modality name + sessions (30d) + total minutes + avg HR
- Trend arrow vs prior 30d
- One-line narrative: "Walking: your most consistent modality — 28 of 30 days"
- Tap/click expands to show: distance, elevation, pace trend, best session

#### Enhancement F: Weekly Physical Volume Heatmap (UPGRADE)
**Current:** Basic "this week's movement" section
**New:** 7-day stacked bar (Mon–Sun) with modality color breakdown + total active minutes per day. More visual than the current table format.

### Visual Priority Order for Training
1. **Daily Exercise Minutes Stacked Bar** (Enhancement A) — hero chart
2. **Daily Step Count Chart** (Enhancement B) — universal metric
3. **AI Coach Analysis** (Enhancement C) — pull-back reason
4. **Resistance Training Deep-Dive** (Enhancement D) — PPL detail
5. **Activity Deep-Dive Cards** (Enhancement E) — modality depth
6. **Weekly Volume Heatmap** (Enhancement F)

---

## Page 4: Physical Observatory — NEW PAGE

### Board Position

**Raj:** "This is a natural sibling page. Training covers what you DO. Physical covers what you ARE — body composition, weight trajectory, measurements, DEXA data. Absolutely should exist."

**Mara:** "This fills a gap in the information architecture. Weight is currently scattered across homepage, live page, and sort-of training. Give it a proper home."

**Sofia:** "Body transformation progress is the most shareable content category in all of health/fitness. This page could be the highest-traffic page on the site."

**Lena:** "Clinically, body composition tracking is more meaningful than weight alone. DEXA gives visceral fat, lean mass, bone density — metrics that actually predict health outcomes. If we present this with proper scientific framing, it's genuinely useful."

**Tyrell:** "This page should feel like a clinical dashboard. Clean, precise, slightly medical in tone. Less editorial warmth than the other observatories — more lab report meets data visualization."

### URL & Navigation
- URL: `/physical/` (under The Data section in nav)
- Accent color: Steel blue (`--p-blue: #60a5fa`) — distinct from training's crimson
- Icon: Body/scale icon from existing icon set

### Page Structure

#### Hero Section
**Title:** "The body as data" or "What the mirror can't measure"
**Sub:** "Weight, composition, measurements, and the metrics that actually predict longevity — tracked with DEXA precision."

**Hero gauges (4 rings):**
1. Current weight (lbs)
2. Body fat % (from DEXA or estimate)
3. Lean mass (lbs, from DEXA)
4. Days since last DEXA

#### Section 1: Weight Trajectory (THE FLAGSHIP SECTION)
**The single most important chart on this page.**

**Chart: Weight Over Time (full journey)**
- X-axis: Full journey timeline (Day 1 to present)
- Y-axis: Weight in lbs
- Daily weigh-in data points with 7-day moving average line
- Horizontal reference lines: start weight, current weight, goal weight
- Phase annotations: "Phase 1: Cut", "Sick days", "Holiday", "Restart"
- Toggle between: 30 days / 90 days / Full journey

**Below chart — Key Metrics Row:**
- Starting weight → Current weight → Goal weight
- Total lost / remaining
- Rate of change (lbs/week, 4-week rolling average)
- Estimated goal date at current rate

- Data source: MacroFactor weight entries — already in DDB
- API: `weight_trajectory: { daily_weights[], moving_avg[], phases[], start_weight, current_weight, goal_weight, rate_per_week }`

#### Section 2: DEXA Body Composition (NEW — BASELINE + PROGRESS)
**Matthew mentioned: "could tap into things like my DEXA notables starting from the DEXA baseline of today March 30th"**

**Design:** Clinical-style data table with visual accents

**DEXA Baseline Card (March 30, 2026):**
- Total body fat %
- Visceral fat area/rating
- Lean mass total
- Bone mineral density
- Regional breakdown: arms, trunk, legs (table or body diagram)

**Progress Tracking (every 4 weeks):**
- Timeline showing DEXA scans with key metrics at each point
- Delta columns: fat %, lean mass, visceral fat change
- Goal vs actual trajectories

**Longevity Context (Dr. Victor Reyes voice):**
"Visceral fat below X cm² is associated with lowest all-cause mortality risk. Current: Y cm². Target: Z cm²."

- Data source: Manual DEXA uploads → new DDB partition `dexa` or config file
- API: `dexa_scans: [{ date, body_fat_pct, visceral_fat, lean_mass, bone_density, regional{} }]`

#### Section 3: Tape Measurements Log (NEW)
**Matthew mentioned: "every 4 weeks when I upload new tape measurements"**

**Design:** Body measurement tracker

**Measurements tracked:**
- Waist circumference (the #1 health-predictive measurement)
- Chest, shoulders, arms (bicep), thighs, hips, neck
- Waist-to-hip ratio (calculated)

**Visualization:**
- Line chart per measurement over time (sparklines)
- Table showing most recent vs baseline vs prior measurement
- Trend arrows per measurement

**Update cadence:** Monthly (manual upload)
- Data source: Manual entry → DDB `measurements` partition or S3 config
- API: `measurements_log: [{ date, waist, chest, shoulders, arms, thighs, hips, neck }]`

#### Section 4: Weight vs Training Volume Correlation (NEW)
**Cross-observatory data section**

**Chart:** Dual-axis chart
- Left axis: Weight (line)
- Right axis: Training minutes (bars)
- Shows relationship between training activity and weight change

#### Section 5: Weight vs Caloric Intake Overlay (NEW)
**Cross-observatory data section**

**Chart:** Dual-axis chart
- Left axis: Weight (line, 7-day average)
- Right axis: Daily calorie intake (bars, with deficit/surplus color coding)
- Shows energy balance → weight change relationship

#### Section 6: AI Body Composition Analysis (NEW)
**Named voice: "Dr. Victor Reyes's Assessment"**

Monthly auto-generated analysis:
- Current body composition trajectory assessment
- Fat loss rate evaluation (too fast? optimal? stalled?)
- Lean mass preservation assessment
- Metabolic adaptation indicators (TDEE trend from MacroFactor)
- Recommendations for next phase

#### Section 7: Milestone Markers (NEW)
- Weight milestones achieved (Sub-280, Sub-260, etc.)
- Measurement milestones
- DEXA improvement milestones
- Visual: badge/achievement style, same as character page achievements

#### Section 8: Methodology
Standard observatory footer: how data is collected, update frequency, measurement protocols.

---

## Implementation Priorities — Board Consensus

### Phase 1: High-Impact Visual Upgrades (Target: 2-3 sessions)
*These are the items that transform the pages from "articles" to "observatories"*

| # | Item | Page | Board Vote | Data Ready? |
|---|------|------|-----------|-------------|
| 1 | 30-Day Calorie + Macro Stacked Bar Chart | Nutrition | 8/8 | ✅ MacroFactor daily |
| 2 | Daily Exercise Minutes by Modality Bar Chart | Training | 8/8 | ✅ Strava + Garmin |
| 3 | Journal Theme Heatmap + Top Themes | Mind | 8/8 | ✅ Notion journal |
| 4 | Daily Step Count Chart | Training | 7/8 | ✅ Garmin steps |
| 5 | Weight Trajectory Chart (full journey) | Physical | 8/8 | ✅ MacroFactor weight |
| 6 | State of Mind Sparkline + Distribution | Mind | 7/8 | ⚠️ Needs consistent logging |
| 7 | Meditation Calendar + Metrics | Mind | 7/8 | ✅ Apple Health |
| 8 | Sentiment Trend Line (90-day) | Mind | 6/8 | ✅ Journal data |

### Phase 2: AI Expert Voices (Target: 1-2 sessions)
*The retention mechanism — gives people a reason to come back*

| # | Item | Page | Expert | Update Cadence |
|---|------|------|--------|----------------|
| 9 | AI Psychiatrist Analysis | Mind | Dr. Conti | Weekly |
| 10 | AI Nutritionist Analysis | Nutrition | Dr. Webb | Weekly |
| 11 | AI Training Coach Analysis | Training | Dr. Sarah Chen | Weekly |
| 12 | AI Body Composition Analysis | Physical | Dr. Victor Reyes | Monthly |

### Phase 3: Data-Dense Sections (Target: 2-3 sessions)
*Depth content that rewards scrolling*

| # | Item | Page |
|---|------|------|
| 13 | Resistance Training Deep-Dive (unhide + expand) | Training |
| 14 | Common Ingredients Grid + Signature Meals | Nutrition |
| 15 | Social Connection Dashboard overhaul | Mind |
| 16 | Vice Streak Timeline | Mind |
| 17 | Activity Deep-Dive Cards (modality expansion) | Training |
| 18 | DEXA Baseline + Progress Tracker | Physical |
| 19 | Tape Measurements Log | Physical |
| 20 | Restaurant & Takeout Insights (unhide) | Nutrition |
| 21 | Macro Deep-Dives — carbs, fats, fiber (unhide) | Nutrition |

### Phase 4: Cross-Observatory & Polish (Target: 1-2 sessions)
| # | Item | Page |
|---|------|------|
| 22 | Weight vs Training Volume correlation | Physical |
| 23 | Weight vs Caloric Intake overlay | Physical |
| 24 | Breathwork × HRV Correlation | Mind |
| 25 | Calorie Trend with moving average + annotations | Nutrition |
| 26 | Hydration deep-dive upgrade | Nutrition |
| 27 | Enhanced cross-observatory links with real correlations | All |
| 28 | Experiment cards on Mind page | Mind |
| 29 | Milestone badges on Physical page | Physical |
| 30 | Mind page structure reorder (data first, narrative last) | Mind |

---

## API Endpoints Required — Summary

### New Endpoints
| Endpoint | Page | Data Sources | Priority |
|----------|------|-------------|----------|
| `GET /api/mind_overview` | Mind | Journal, mood, meditation, social, vices | P1 |
| `GET /api/mind_ai_analysis` | Mind | Combined mind data | P2 |
| `GET /api/nutrition_ai_analysis` | Nutrition | MacroFactor, food delivery, CGM | P2 |
| `GET /api/training_ai_analysis` | Training | Strava, Hevy, Whoop, Garmin | P2 |
| `GET /api/physical_overview` | Physical | MacroFactor (weight), DEXA, measurements | P1 |
| `GET /api/body_composition_analysis` | Physical | DEXA, weight, measurements | P2 |
| `GET /api/strength_deep_dive` | Training | Hevy | P3 |

### Endpoint Extensions (existing endpoints, new fields)
| Endpoint | New Fields | Priority |
|----------|-----------|----------|
| `nutrition_overview` | `daily_macros_30d[]`, ingredient frequency, macro deep-dive data | P1 |
| `training_overview` | `daily_modality_minutes_30d[]`, `daily_steps_30d[]` | P1 |
| `mind_overview` (or new) | `journal_themes[]`, `sentiment_trend[]`, `state_of_mind[]`, `meditation{}`, `social_connection{}` | P1 |

---

## Design System Notes for Claude Code

### Color System
- **Mind:** Violet (`--m-violet: #a78bfa`) — KEEP
- **Nutrition:** Amber (`--n-amber: #f59e0b`) — KEEP
- **Training:** Crimson (`--t-red: #ef4444`) — KEEP
- **Physical:** Steel blue (`--p-blue: #60a5fa`) — NEW

### Chart Implementation
- Use Chart.js (already available in the stack via CDN)
- All charts must: support dark theme, use CSS variable colors, be responsive, include hover tooltips
- Stacked bar charts: use `type: 'bar'` with `stacked: true` on both axes
- Line charts with moving averages: compute on client-side from raw data array
- Loading states: show monospace "LOADING..." animation per existing pattern

### AI Analysis Card Pattern
Reusable component across all 4 pages:
```
┌─────────────────────────────────────────┐
│ ▌ [Expert Name]'s Analysis              │
│ ▌                                        │
│ ▌ [2-3 paragraphs of weekly analysis]   │
│ ▌                                        │
│ ▌ ⊕ Evidence: [data sources, date range] │
└─────────────────────────────────────────┘
```
Left accent border in page's accent color. Expert name in mono, analysis in serif, evidence badge in mono small.

### Section Header Pattern (existing — reuse)
```
SECTION NAME ——————————————————————————
```
Monospace, uppercase, letter-spaced, trailing em-dashes. Already implemented as `.m-section-header`, `.n-section-header`, `.t-section-header`.

### Progressive Data Loading
Each section loads its data independently via `fetch()`. Show sections immediately with loading state. As each API call returns, populate. Don't block the page on any single endpoint.

### Mobile Considerations (Mara's requirement)
- Charts must be touch-scrollable on mobile
- Stacked bars should be rotatable to horizontal on narrow screens
- Activity deep-dive cards should be full-width stacked on mobile
- AI analysis cards: full-width, no columns

---

## Board Dissent / Minority Opinions

**Viktor Sorokin (Adversarial Reviewer, Tech Board):** "The AI analysis sections are the right idea but the wrong execution if they're Lambda-generated on every page load. These should be cached weekly. Don't run a $0.05 LLM call every time someone visits."
→ **Resolution:** All AI analysis endpoints are Lambda-backed with DynamoDB caching (weekly TTL). Page loads read from cache. Regeneration triggered by weekly cron.

**James Okafor (CTO):** "The Physical page introduces a new DDB partition for DEXA and measurements. We need to decide: does this go in the existing `life-platform` table or a new one?"
→ **Resolution:** Same table, new partitions (`DEXA#USER` and `MEASUREMENTS#USER`). Follows existing single-table design.

**Tyrell:** "The Mind page topic clusters visualization is technically challenging. A simple top-themes bar chart achieves 80% of the value."
→ **Resolution:** Phase 1 ships the bar chart. Topic clusters are Phase 4 polish if time permits.

**Mara:** "I'm concerned about the Physical page being too weight-focused. It could feel like a diet tracker."
→ **Resolution:** The page leads with body COMPOSITION, not just weight. DEXA data, lean mass, and longevity-contextualized metrics prevent the "diet app" feel. Sofia's framing: "This is about what your body is made of, not what it weighs."

---

## Success Metrics (Jordan's Framework)

| Metric | Current (estimated) | Target | Measurement |
|--------|-------------------|--------|-------------|
| Avg time on page (Mind) | ~60 seconds | 3+ minutes | Analytics |
| Avg time on page (Nutrition) | ~90 seconds | 4+ minutes | Analytics |
| Avg time on page (Training) | ~90 seconds | 4+ minutes | Analytics |
| Return visits (any observatory) | ~5% weekly | 15%+ weekly | Analytics |
| Screenshot/share events | Unknown | 2+ per week (inferred from referral traffic) | Referral tracking |
| Scroll depth > 75% | ~20% | 50%+ | Scroll tracking |

---

## Final Board Statement

**Raj (closing):** "This spec transforms four pages from 'interesting one-time reads' into 'living data dashboards with expert analysis.' The charts give people something new to see every visit. The AI voices give them someone to hear from. The cross-observatory links create a web they explore rather than a list they scroll through. If we execute this, these pages become the reason people subscribe — because they want to see what happens next."

**Throughline test:** After this spec ships, can a visitor on the Mind page answer "Where am I in Matt's story?" Yes — they're seeing the inner life data that drives everything else, with a psychiatrist's AI interpretation and links to how it affects sleep, training, and nutrition. That's the throughline.

---

*This spec is designed for handover to Claude Code. Each section includes: what to build, where the data comes from, what the API needs, and how it should look. Phase 1 focuses on the visual chart upgrades that have the highest impact. Phase 2 adds the AI expert voices. Phase 3 fills in data depth. Phase 4 polishes and cross-links.*
