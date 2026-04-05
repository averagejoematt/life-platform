# averagejoematt.com — Website Strategy & Execution Plan

> **Source**: CEO Audit (March 21, 2026) + Board Summit #3 + WEBSITE_ROADMAP.md
> **Purpose**: Single coherent strategy from vision to task-level, replacing all prior fragmented plans
> **Status**: Draft for alignment — ready to sprint against once approved

---

## The Core Diagnosis

Your audit identified 40+ issues across 20+ pages. But they all trace back to **three root problems**:

**1. No throughline.** The site is a collection of data pages, not a story. A visitor landing on `/sleep/` sees numbers. They don't know why those numbers matter, how they connect to your character score, what experiment is testing them, or what you discovered. Every page is an island. Your own words: *"HOW DO WE THREAD THE NEEDLE OF THIS ENTIRE EXPERIMENT SO IT ALL TIES TOGETHER — NOT JUST ONE EXTERNAL BIG CIRCLE JERK OF THIS IS SO COOL — BUT THEM CONNECTING THE STORY THEMSELVES."*

**2. No information architecture.** 20+ pages with flat navigation. You — the creator — discovered pages you didn't know existed. If you can't find them, visitors certainly can't. Pages overlap (progress/results/benchmarks/achievements), contradict each other (different weight numbers), and repeat the same provocative hooks ("ONE PERSON. 19 DATA SOURCES.") without awareness of where the visitor has already been.

**3. Stale and hollow data.** The site promises a living, intelligent system. But weight is null, streaks are dashes, day-on-journey is blank, data sources counts are hardcoded, and single-topic pages (sleep, glucose, supplements) show almost nothing. The promise-to-delivery gap is the fastest way to lose credibility.

---

## The Vision: What This Site Needs to Become

**averagejoematt.com is a documentary, not a dashboard.**

The site's job is to let a stranger walk into your experiment at any point and understand three things within 60 seconds:

1. **What's happening right now** — Matt is on Day X of an experiment. Here's his current state, honest and unfiltered.
2. **How it all connects** — The character score isn't arbitrary. It's computed from habits, which are informed by protocols, which are tested by experiments, which produce discoveries, which update the character. It's a closed loop.
3. **What the platform actually does** — Not "19 data sources and 95 tools." Show me one example where the AI detected something a human wouldn't have caught. One discovery that changed behavior. That's worth more than any architecture diagram.

**The throughline is: Data → Insight → Action → Results → Repeat.**

Every page should be positioned somewhere on that loop. Every page should link forward and backward along that loop. A visitor on any page should be able to answer: "Where am I in the story?"

---

## The New Information Architecture

Your instinct about categories was correct. Here's the restructured sitemap organized into five sections, each with a clear purpose. This replaces the current flat list of 20+ disconnected pages.

### Section 1: THE STORY (Why should I care?)
*First-time visitor entry point. Emotional, narrative-driven. Minimal data.*

| Page | Purpose | Current Status |
|------|---------|----------------|
| `/` (Home) | The hook: who Matt is, what he's doing, how he's doing today | Live — needs data fixes |
| `/story/` | Origin narrative — the why | Live — needs prose (Matthew) |
| `/about/` | Matt as a human, not a data subject | Live — strip data widgets |

### Section 2: THE DATA (What's actually happening?)
*The live experiment. Numbers, trends, honest snapshots. For return visitors checking in.*

| Page | Purpose | Current Status |
|------|---------|----------------|
| `/live/` | The dashboard — multi-metric live view, not just weight | Live — needs major expansion |
| `/character/` | The score — 7-pillar system with avatar and badges | Live — needs intro, avatar, badges |
| `/habits/` | The inputs — heatmap, tiers, streaks, adherence | **New** (data ready) |
| `/accountability/` | The daily snapshot — how Matt's doing *today*, nudge mechanism | Live — needs complete rethink |

### Section 3: THE SCIENCE (How does this work?)
*For the curious. Methods, protocols, experiments, discoveries. This is what differentiates from a fitness blog.*

| Page | Purpose | Current Status |
|------|---------|----------------|
| `/protocols/` | What Matt does daily — habits, supplements, routines with the *why* | Live — needs habit tiers, supplement detail |
| `/experiments/` | Active N=1 experiments — what's being tested right now | Live — needs active use |
| `/discoveries/` | Confirmed findings — what the data proved | Live — needs placeholder if empty |
| `/sleep/` | Deep-dive: sleep environment, architecture, optimization | Live — needs narrative + depth |
| `/glucose/` | Deep-dive: CGM intelligence, meal responses, trends | Live — needs narrative + depth |
| `/supplements/` | Deep-dive: stack with genome rationale, evidence links | Live — needs supplement data |
| `/benchmarks/` | Centenarian decathlon — interactive calculator | Live — needs interactivity |

### Section 4: THE BUILD (How is this made?)
*For builders, CTOs, engineers. Pure tech showcase. This is the "how I built it" section.*

| Page | Purpose | Current Status |
|------|---------|----------------|
| `/platform/` | Architecture overview — the impressive diagram, tech stack, data flow | Live — needs focus |
| `/intelligence/` | The AI brain — 14+ IC features with live examples | Live — needs dynamic content |
| `/board/` | The advisory boards — personal + technical + web | Live — needs persona updates |
| `/cost/` | Running costs breakdown | Live — move under platform |
| `/methodology/` | Statistical rigor, N=1 framework, limitations | Live — static, fine |
| `/tools/` | Interactive platform tools | Live |

### Section 5: FOLLOW (How do I stay connected?)
*Engagement and subscription.*

| Page | Purpose | Current Status |
|------|---------|----------------|
| `/chronicle/` | **Renamed from /journal/** — Elena Voss's investigative series | Live — rename + fix nav |
| `/subscribe/` | Email signup with working confirmation | Live — fix confirmation flow |
| `/ask/` | AI Q&A | Live — fix back-nav UX |

### Pages to REMOVE or MERGE

| Current Page | Action | Rationale |
|-------------|--------|-----------|
| `/progress/` | **Merge into `/live/`** | Overlaps with live data view; live should show multi-metric progress |
| `/results/` | **Merge into `/live/`** | Same as progress — all "how am I doing" data belongs in one place |
| `/achievements/` | **Merge into `/character/`** | Badges and achievements are part of the character system, not standalone |
| `/start/` | **Remove** | It's a sitemap. The new nav structure makes it redundant |
| `/data/` | **Move under `/platform/`** | Technical docs for builders, not a standalone page |
| `/privacy/` | **Keep but fix email** | Setup matt@averagejoematt.com or update to correct address |

**Net effect**: From ~25 discoverable pages → 20 pages organized into 5 clear sections. Each section has 3-6 pages. Each page has a distinct job.

---

## The Navigation Overhaul

### Desktop Top Nav (5 sections)
```
[Logo] The Story ▾  The Data ▾  The Science ▾  The Build ▾  Follow ▾  [Subscribe →]
```

Each dropdown reveals 3-6 pages in that section. One line per page with a short descriptor.

### Mobile Bottom Nav (unchanged, but update icons)
```
Home · Live · Score · Chronicle · More
```

"Journal" becomes "Chronicle." "Ask" moves to hamburger since it's lower-frequency.

### Mobile Hamburger (grouped by section)
The 5 sections with all pages listed, matching the footer structure.

### Footer (5-column, matching sections)
```
THE STORY     THE DATA       THE SCIENCE      THE BUILD        FOLLOW
Home          Live           Protocols        Platform         Chronicle
Story         Character      Experiments      Intelligence     Subscribe
About         Habits         Discoveries      Board            Ask
              Accountability Sleep            Cost             RSS
                             Glucose          Methodology      Privacy
                             Supplements      Tools
                             Benchmarks
```

### Contextual CTAs (David Perell's "Reading Path")
Every page ends with a contextual link to the next logical page in the story loop:

- `/story/` → "See where I am today →" → `/live/`
- `/live/` → "How the score is computed →" → `/character/`
- `/character/` → "The habits that feed the score →" → `/habits/`
- `/habits/` → "What I'm actively testing →" → `/experiments/`
- `/experiments/` → "What the data has proven →" → `/discoveries/`
- `/discoveries/` → "How the AI works →" → `/intelligence/`
- `/intelligence/` → "Ask the data yourself →" → `/ask/`

---

## Data Integrity Sweep (Do This First)

Before building any new pages or restructuring nav, fix the foundation. Every broken number undermines the site's entire premise.

### Critical Data Fixes

| # | Issue | Root Cause | Fix |
|---|-------|-----------|-----|
| D1 | weight_lbs is null in public_stats.json | daily_brief_lambda.py data pipeline bug | Debug Lambda, fix weight population logic |
| D2 | "0.00% to goal" on marquee | Depends on weight_lbs being null | Resolves with D1; also validate goal calc |
| D3 | Streak shows dash instead of "0" | Null handling — dash when no data | Change to explicit "0" with tooltip "No active streak" |
| D4 | Day on Journey is blank | Missing calculation in stats pipeline | Compute from journey_start_date (known) |
| D5 | "19 data sources" hardcoded | Text string in HTML | Pull from public_stats.json `data_source_count` |
| D6 | "95 intelligence tools" hardcoded on /story/ | Text string in HTML | Pull from public_stats.json or remove specific number |
| D7 | "Signal / Human Systems" in marquee | Unclear branding | Replace with clear tagline or remove |
| D8 | Weight comparison card shows 30-day gain vs journey loss | Ambiguous time framing | Show both: "30-day: +11.8 lbs" AND "Journey total: -X lbs" with clear labels |
| D9 | Recovery 89 means nothing to viewer | No context for Whoop metrics | Add range context: "89/100 (Good — 7-day avg: X)" |
| D10 | Day 1 baseline values hardcoded | Static numbers in HTML | Pull from DynamoDB baseline partition or public_stats |

### Parameterization Principle
**Every number displayed on the site must come from public_stats.json or an API call. Zero hardcoded metrics.** This is the audit's most repeated finding and it's correct. Build this rule into the new page template.

---

## Execution Phases

### Phase 0: Foundation (Sprint 9 — This Week)
*Fix what's broken before building anything new. 1-2 sessions.*

**Tasks:**
1. **D1-D10**: Fix all data pipeline issues in daily_brief_lambda.py and public_stats.json
2. **Parameterize homepage**: Replace all hardcoded numbers with dynamic values
3. **Fix subscribe confirmation**: Debug the subscriber Lambda flow — emails must arrive
4. **Fix /journal/ nav date**: Wrong date in header, yellow color mismatch
5. **Fix /ask/ back-navigation**: Add breadcrumb or "New question" button
6. **Remove "subscribe for more" from /ask/**: Not offering it yet
7. **R17-02**: Privacy page — fix email address (setup matt@averagejoematt.com forwarding or update to correct address)

**Validation**: Visit every live page. Every number should be real. Every link should work. Every form should respond.

### Phase 1: Information Architecture (Sprint 10)
*Restructure the site into sections. 2-3 sessions.*

**Tasks:**
1. **Implement dropdown nav**: 5-section desktop nav with dropdowns (The Story / The Data / The Science / The Build / Follow)
2. **Update mobile nav**: Rename Journal → Chronicle in bottom nav
3. **Update hamburger + footer**: Group all pages into 5 sections
4. **Rename /journal/ → /chronicle/**: Update all references, redirects, nav, sitemap
5. **Merge /progress/ and /results/ content into /live/**: Consolidate all "how am I doing" data into a single multi-metric page
6. **Merge /achievements/ into /character/**: Badge wall becomes a section within the character page
7. **Remove /start/**: Redirect to home
8. **Contextual CTAs**: Add "reading path" links at the bottom of every page
9. **Update sitemap.xml and robots.txt**

**Validation**: A first-time visitor should be able to navigate from any page to any other page within 2 clicks.

### Phase 2: Content Depth (Sprints 11-13)
*Make each page worth visiting. Data ready, needs frontend. 4-6 sessions.*

**Tier A — Highest Impact, Data Exists:**

1. **`/live/` expansion**: Multi-metric dashboard (not just weight). Habits, exercise types, state of mind, journal themes. This is the page that proves the system is real.
2. **`/habits/` (new page)**: GitHub-contribution heatmap, tier breakdown (T0-T3), streak data, keystone spotlight. Apply content filter for blocked vices. Endpoint: `/api/habits`
3. **`/character/` enhancement**: Add intro narrative explaining the concept (not just metrics → human wellbeing experiment). Add avatar system. Integrate achievement badges. Fix scoring lockstep issue (pillars shouldn't all move together with no differentiated data).
4. **`/accountability/` rethink**: This is the "how is Matt doing TODAY" page. Show character state (avatar mood), active streaks, recent failures honestly, flatline detection. The "sick days for 2 weeks" scenario you described — this page should surface that and make it visible.

**Tier B — Deep Dives, Needs Narrative + API Work:**

5. **`/supplements/` rebuild**: Full stack with dosage, timing, adherence %, genome rationale per supplement, evidence links to journals, cost breakdown. Endpoint: `/api/supplements`
6. **`/sleep/` rebuild**: Eight Sleep × Whoop cross-reference, temperature bands, circadian consistency, architecture trends. Written as if Dr. Matthew Walker (the sleep scientist) reviewed it. Endpoint: `/api/sleep_environment`
7. **`/glucose/` rebuild**: CGM dashboard — time-in-range gauge, variability, best/worst foods by grade, meal-level detail. Endpoint: `/api/glucose`
8. **`/benchmarks/` interactive**: Centenarian decathlon with personal records. Visitors can enter their own numbers. Show "Not possible yet" honestly for things you can't currently do. Endpoint: `/api/benchmarks`

**Tier C — Tech Showcase:**

9. **`/platform/` focus**: Strip non-tech content. Add high-level architecture diagram. Organize as: What it's built on → Data flow → Intelligence layer → Tool structure → Costs. What would impress a CTO.
10. **`/intelligence/` dynamic**: Wire to live IC feature list. Show one real example of each intelligence feature catching something.
11. **`/board/` updates**: Replace Huberman and Attia with alternative public-facing experts (keep their science perspective in private prompts). Consider showing Technical and Web boards as expandable sections.

### Phase 3: The Chronicle & Journal Mechanism (Sprint 14)
*Fix the content engine. 1-2 sessions.*

**Tasks:**
1. **Rebrand journal → chronicle**: This is Elena Voss investigating Matthew's journey. "The Measured Life" by an AI journalist. Not personal notes.
2. **Fix Wednesday auto-publish**: Debug the chronicle Lambda workflow. Why did it miss this week?
3. **Add preview/approval flow**: Chronicle drafts go to Matthew first via email. He approves or requests changes before publish.
4. **Write this week's entry**: The restart interview — why 2 weeks of sick days, what happened, what's the plan. This is exactly the kind of raw content that makes the chronicle compelling.
5. **Archive page**: `/chronicle/archive/` with all entries listed chronologically, thesis lines telling the story.

### Phase 4: Engagement & Gamification (Sprints 15-16)
*Make people come back. 2-3 sessions.*

1. **"Since Your Last Visit" indicators**: localStorage tracking, dot badges on nav items
2. **Daily brief as mobile homepage anchor**: Return visitors see today's brief first
3. **Achievement badges system**: Design badge set (streak, tier, vice, experiment, data badges). Earned vs pending creates aspiration.
4. **Experiments activation**: Start actually using experiments so visitors can see active tests. Add future upvote/downvote concept to backlog (needs auth — defer).

### Phase 5: Commercialization Prep (Sprints 17+)
*Deferred until 1,000 subscribers. Document in roadmap but don't build.*

- Premium newsletter tier
- Prompt pack product
- `/for-builders/` landing page
- Community membership

---

## Board Member Replacements

For the public `/board/` page, replace:

| Current | Issue | Replacement Candidate | Rationale |
|---------|-------|----------------------|-----------|
| Andrew Huberman | Infidelity controversy | **Dr. Andy Galpin** | Exercise physiology expertise. Clean public reputation. Practical protocols focus. |
| Peter Attia | Epstein ties | **Dr. Rhonda Patrick** (already on board) or **Dr. Layne Norton** | Longevity/nutrition science. Evidence-based. Norton especially strong on debunking and statistical rigor. |

**Implementation**: Update `s3://matthew-life-platform/config/board_of_directors.json`. Keep Huberman and Attia's *scientific perspectives* in the system prompt for internal use — just remove their names and likenesses from any public-facing surface.

---

## What the Board / Strategy Added Beyond Your Audit

Your audit was the primary input — roughly 90% of the strategy traces directly back to something you identified. But there are ideas in this strategy and the Board Summit #3 roadmap that you did NOT raise. Here's an honest accounting of what's new:

### New Conceptual Frameworks (not in your audit)

1. **"Documentary, not dashboard" framing** — You said "thread the needle" and "them connecting the story themselves." The strategy crystallized this into a specific mental model: the site is a documentary that a stranger walks into mid-episode, not a dashboard for data consumers. This reframes every design decision.

2. **"Data → Insight → Action → Results → Repeat" loop** — You talked about throughline. The strategy made it a specific closed loop with every page positioned somewhere on it. This is the structural principle behind the reading path CTAs and the page merge decisions.

3. **The Throughline Test** — Two validation questions that every page must pass. You didn't propose a test — you described the problem. The test is the board's answer to "how do we know when we've fixed it?"

4. **The "would a visitor lose anything if I removed this page?" test** — Your audit asked whether pages overlap. This test is the decision framework for merge/remove choices.

5. **Parameterization as a hard universal rule** — You flagged 5-6 individual hardcoded numbers. The strategy elevated this to a principle: "Every number displayed on the site must come from public_stats.json or an API call. Zero hardcoded metrics." This prevents the problem from recurring.

6. **Phase sequencing rationale** — You listed what's broken. The strategy argues for a specific order: fix data first (because broken numbers undermine everything), then IA (because new pages into broken nav is wasted work), then content, then engagement. You didn't propose an order; the board did.

### New Feature Ideas from Board Summit #3 (not in your audit)

7. **David Perell's "Reading Path" / Contextual CTAs** — The idea that every page ends with a specific link to the next logical page in the story. You asked for throughline; this is the concrete implementation. Came from the Web Board (David Perell persona specifically).

8. **Character Avatar System** — SVG-based character that visually evolves as pillar tiers improve. Level 1 = silhouette, pillar improvements add visual elements (glow for sleep mastery, muscle for movement). You asked for "show my avatar and the journey it goes on" and "achievement badges" — the 35-element composable SVG system and the tier-unlocked visual progression were the board's specific design answer.

9. **"Since Your Last Visit" localStorage indicators** — Dot badges on nav items when content has updated since last visit. Creates return-visit habit. Not in your audit.

10. **Daily Brief as mobile homepage anchor** — For return visitors, mobile homepage leads with today's brief excerpt instead of the hero section. The daily hook. Not in your audit.

11. **Commercialization ladder** — Free → Premium ($10/mo) → Course ($99-299) → Community ($29/mo) → Advisory ($500+/hr). You didn't discuss monetization in your audit. The board mapped this for future reference (deferred to post-1,000 subscribers).

12. **Prompt Pack as a product** — Selling the Board of Directors persona system, coaching prompts, and scoring framework as a standalone product ($49-99). Board idea, not yours.

13. **Open-source template** — Stripped platform skeleton (DynamoDB schema, Lambda skeleton, MCP bridge, 5 core integrations) as a Supabase-model open-source project. Board idea.

14. **Specific board replacement candidates** — You said replace Huberman and Attia. The strategy proposed Andy Galpin and Layne Norton as specific names. That's additive.

15. **The 5-section naming taxonomy** — You said "results, methods, tech, about me" as rough examples. The strategy formalized these as "The Story / The Data / The Science / The Build / Follow" with specific page assignments. The names and groupings are new.

16. **Specific merge decisions** — You asked "do we need all of progress/results/benchmarks/discoveries?" The strategy made the specific calls: progress + results → /live/, achievements → /character/, benchmarks and discoveries kept separate. You posed the question; the board made the decisions.

### What the Board Did NOT Add

To be fully transparent: the board did **not** come up with a single idea that contradicts your audit. There were no "actually Matthew is wrong about X" moments. Your instincts were consistently correct — the board's job was to systematize and sequence what you already saw, not to overrule it.

The most valuable board contribution wasn't any single feature idea. It was the **structural diagnosis** — naming the three root problems (throughline, IA, stale data) so that 40+ individual issues become actionable as a cohesive plan rather than a bug list.

---

## The Throughline Test

After all phases, every page should pass this test:

**Can a visitor answer these three questions from any page?**

1. Where am I in Matt's story? *(Section headers in nav make this obvious)*
2. How does this connect to the bigger picture? *(Contextual CTAs link forward/backward)*
3. Is this real, current data? *(Every number dynamic, every page has "last updated" timestamp)*

**Can Matt answer this question about every page?**

"Why does this page exist as a separate page, and what would a visitor lose if I removed it?"

If the answer is "nothing" — merge or remove it.

---

## Task Summary — Ordered Backlog

> Note: Tasks 42-49 were added after audit gap analysis (v1.1)

| # | Task | Phase | Effort | Dependencies |
|---|------|-------|--------|-------------|
| 1 | Fix public_stats.json weight_lbs null | P0 | S | daily_brief_lambda.py |
| 2 | Parameterize all hardcoded numbers on homepage | P0 | S | Task 1 |
| 3 | Fix streak display (show 0, not dash) | P0 | XS | public_stats.json |
| 4 | Fix Day on Journey calculation | P0 | XS | public_stats.json |
| 5 | Fix subscribe confirmation email flow | P0 | S | subscriber Lambda |
| 6 | Fix /journal/ nav date + color | P0 | XS | — |
| 7 | Fix /ask/ back-navigation UX | P0 | XS | — |
| 8 | Remove "subscribe for more" from /ask/ | P0 | XS | — |
| 9 | Fix privacy page email address | P0 | S | AWS SES or text update |
| 10 | Recovery metric context (add range/label) | P0 | XS | — |
| 11 | Weight comparison: show journey total + 30-day | P0 | S | Task 1 |
| 12 | Replace "Signal / Human Systems" with clear tagline | P0 | XS | — |
| 13 | Implement 5-section dropdown nav (desktop) | P1 | M | — |
| 14 | Update mobile bottom nav (Journal → Chronicle) | P1 | S | — |
| 15 | Update hamburger + footer (5 sections) | P1 | M | Task 13 |
| 16 | Rename /journal/ → /chronicle/ with redirects | P1 | S | — |
| 17 | Merge /progress/ + /results/ into /live/ | P1 | M | — |
| 18 | Merge /achievements/ into /character/ | P1 | S | — |
| 19 | Remove /start/ with redirect | P1 | XS | — |
| 20 | Add contextual CTAs ("reading path") to all pages | P1 | M | — |
| 21 | Update sitemap.xml | P1 | XS | Tasks 16-19 |
| 22 | Expand /live/ to multi-metric dashboard | P2A | L | API work |
| 23 | Build /habits/ page (heatmap + tiers + streaks) | P2A | M | `/api/habits` endpoint |
| 24 | Enhance /character/ (intro, avatar, badges, scoring fix) | P2A | L | Design work |
| 25 | Rethink /accountability/ (daily snapshot + nudge) | P2A | M | — |
| 26 | Rebuild /supplements/ (full stack + genome + evidence) | P2B | M | `/api/supplements` endpoint |
| 27 | Rebuild /sleep/ (narrative + data depth) | P2B | M | `/api/sleep_environment` endpoint |
| 28 | Rebuild /glucose/ (CGM intelligence) | P2B | M | `/api/glucose` endpoint |
| 29 | Make /benchmarks/ interactive (personal records + visitor calc) | P2B | M | `/api/benchmarks` endpoint |
| 30 | Focus /platform/ (strip non-tech, add architecture diagram) | P2C | M | — |
| 31 | Wire /intelligence/ to live IC features | P2C | M | `/api/intelligence` endpoint |
| 32 | Update /board/ (replace personas, consider showing all boards) | P2C | S | board_of_directors.json |
| 33 | Rebrand journal → chronicle (all references) | P3 | S | Task 16 |
| 34 | Fix Wednesday auto-publish Lambda | P3 | M | Debug chronicle workflow |
| 35 | Add chronicle preview/approval email flow | P3 | M | SES + Lambda |
| 36 | Write restart interview chronicle entry | P3 | S | Matthew + Elena Voss prompt |
| 37 | Build /chronicle/archive/ page | P3 | S | — |
| 38 | "Since Your Last Visit" localStorage indicators | P4 | M | — |
| 39 | Daily brief as mobile homepage | P4 | S | — |
| 40 | Achievement badge design + implementation | P4 | L | Character system |
| 41 | Start using experiments actively | P4 | S | Matthew decision |

### Tasks Added from Audit Gap Analysis (Items 42-49)

*These were partially addressed or missed entirely in v1. Now explicit.*

| # | Task | Phase | Effort | Source |
|---|------|-------|--------|--------|
| 42 | **Verify bottom nav is actually working** — Sprint 8 shipped a fix but audit says it still fails. Test on real device, identify specific failure mode, fix. | P0 | S | Audit: site-wide #3 |
| 43 | **Add "longest streak since started" + streak definition** to homepage/marquee — not just current streak showing 0, but historical best and what constitutes a streak | P0 | S | Audit: homepage |
| 44 | **Verify HRV/heart rate graph on homepage is real data** — if decorative, either wire to Whoop API or remove. Fake data graphs on a site about radical transparency is a credibility killer. | P0 | S | Audit: homepage |
| 45 | **Verify all journal post subpages use current nav** — audit says individual blog posts have old/outdated menu. Check all `/journal/posts/week-XX/` pages, re-run nav patch if needed. | P0 | XS | Audit: journal |
| 46 | **Audit cost page accuracy** — is the data hardcoded or dynamically sourced? If hardcoded, add to parameterization sweep (Task 2). Add specific task to verify every number on `/cost/`. | P0 | S | Audit: cost page |
| 47 | **Discoveries empty-state placeholder** — if no confirmed discoveries yet, show: "X days of data collected. This page unlocks after Y more days of analysis." Don't show a blank page. | P2B | XS | Audit: discoveries |
| 48 | **Supplements: distinguish evidence confidence levels** — for each supplement, label whether it's "genome-justified," "well-sourced scientific consensus," or "N=1 personal experiment." User should see at a glance which are evidence-backed vs. speculative. | P2B | S | Audit: supplements |
| 49 | **Explore /tools/ page expansion** — audit noted "I like this, wonder what else we can use here." Brainstorm additional interactive tools (macro calculator? sleep optimizer? habit correlation explorer?) and add 2-3 highest-impact ones. | P2C | M | Audit: tools page |

**Total estimated effort**: ~85-110 hours across 15+ sessions

---

## What This Strategy Does NOT Include

- **Light mode / theme toggle**: Deferred. The dark biopunk aesthetic is the brand. Revisit when audience data shows demand.
- **Login / authentication**: No user accounts. Everything remains public-read.
- **Commercialization builds**: No premium tier, no course platform, no community. Document the ideas but don't build until 1,000 subscribers.
- **AI image generation for avatar**: Use hand-designed SVG states. No generative AI imagery on the site.
- **Google Calendar integration**: Correctly deferred per data governance concern.

---

*This strategy is designed to be executed sequentially. Phase 0 is the foundation — nothing else matters if the data is broken. Phase 1 is the structure — no point building new pages into a broken IA. Phases 2-4 are content and engagement — the stuff that actually makes the site worth visiting. Phase 5 is monetization — only after there's an audience.*

*The single most important thing this site needs is not a new page or a new feature. It's a **throughline**. Every page connecting to every other page. A visitor on any page understanding where they are in the story. That's the job.*
