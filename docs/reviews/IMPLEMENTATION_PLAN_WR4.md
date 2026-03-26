# Website Review #4 — Implementation Plan

**Created**: March 26, 2026  
**Source**: `docs/reviews/REVIEW_2026-03-26_website_v4.md`  
**Target**: All items complete before April 1, 2026 (Day 1)  
**Structure**: 5 sessions, 47 tasks, organized by workstream

---

## LEGEND

- 🔴 **BLOCKER** — Must ship before any public sharing
- 🟡 **HIGH** — Should ship before April 1
- 🟢 **MEDIUM** — Ship in first 2 weeks post-launch
- ⚪ **LOW** — Backlog / nice-to-have

---

## SESSION 1: STORY PAGE (highest priority — site's emotional core)

**Goal**: All 5 chapters live in HTML with editorial typography. The most important page on the site goes from empty to complete.

| # | Task | Priority | File(s) | Details | Source |
|---|------|----------|---------|---------|--------|
| 1.1 | Implement Chapter 1 "The Moment" | 🔴 | `site/story/index.html` | Remove `style="display:none"` from Ch1 div. Replace placeholder block with prose from `STORY_DRAFTS_v1.md` Chapter 01. | Ava, Mara, Persona C |
| 1.2 | Implement Chapter 2 prose | 🔴 | `site/story/index.html` | Replace placeholder block in Ch2 with prose from drafts. Keep or update pull quote to match interview material. | Ava |
| 1.3 | Implement Chapter 3 prose | 🔴 | `site/story/index.html` | Replace placeholder block in Ch3 with prose from drafts. Keep existing "I'm not a developer" opening + data-moment stats block. Append new content after. | Ava |
| 1.4 | Implement Chapter 4 "What the Data Has Shown" | 🔴 | `site/story/index.html` | Remove `style="display:none"` from Ch4 div. Replace placeholder with prose from drafts. This is the "platform didn't prevent relapse" chapter — most vulnerable, most powerful. | Ava, Lena, Personal Board |
| 1.5 | Implement Chapter 5 "Why Public" | 🔴 | `site/story/index.html` | Replace placeholder block in Ch5 with prose from drafts. Keep existing Elena Voss paragraph at the end. | Ava |
| 1.6 | Update pull quote (Ch2) | 🟡 | `site/story/index.html` | Replace generic "The problem wasn't motivation..." with a real quote from interview, or remove if nothing fits. | Ava |
| 1.7 | Story page editorial typography | 🟡 | `site/story/index.html` (inline CSS) | Per Tyrell: story page should feel like editorial journalism, not a dashboard. Increase `chapter-body` line-height, ensure serif font prominence, add breathing room between chapters. Reduce `story-chapter` margin-bottom if whitespace still excessive. | Tyrell |
| 1.8 | Re-enable placeholder CSS (dev-only) | ⚪ | `site/story/index.html` | Restore placeholder styling but add `display:none` by default so Matthew can toggle them for dev reference. Or just remove placeholder HTML entirely since drafts are implemented. | Cleanup |
| 1.9 | Privacy guardrail check | 🟡 | `docs/content/ELENA_PREQUEL_BRIEF.md` vs `site/story/index.html` | Cross-check implemented chapter content against the privacy guardrails in the prequel brief. Abstract: specific family illness details, relationship questioning, cancelled events, substance use, specific work events. | Personal Board |
| 1.10 | Add "Explore the data" throughline link | 🟡 | `site/story/index.html` | After Chapter 4, add a callout: "Explore the data yourself → /explorer/" and after Chapter 5: "Read this week's chronicle → /chronicle/". Per Raj's throughline recommendation. | Raj |

**Acceptance**: All 5 chapters visible with real prose. No placeholder blocks visible. Page reads as a cohesive personal narrative from top to bottom.

---

## SESSION 2: HOMEPAGE REDESIGN

**Goal**: Hero simplified from 11 elements to ~5. Fake discovery cards replaced. Clear entry path for both audiences.

### 2A: Hero Simplification

| # | Task | Priority | File(s) | Details | Source |
|---|------|----------|---------|---------|--------|
| 2.1 | Simplify hero to 5 core elements | 🔴 | `site/index.html` | Keep: (1) "The Measured Life Experiment" label, (2) headline + weight counter, (3) one-sentence narrative, (4) "Read the story" primary CTA, (5) subscribe input. Remove or move below fold: prequel banner, Elena one-liner, stat chips, dual-path CTAs, chronicle teaser, heartbeat canvas, "Start here" box. | Sofia, Mara, Persona E |
| 2.2 | Add "two-track" CTAs below fold | 🟡 | `site/index.html` | Below the simplified hero, keep the dual-path CTAs (human side / technical side) but as a below-fold section, not competing with the hero. | Mara |
| 2.3 | Move stat chips to /live/ page | 🟡 | `site/index.html` | Remove "Experiment Day / Current Streak / Data Sources" chips from homepage hero. These belong on the Pulse page, not the front door. | Sofia |
| 2.4 | Simplify ticker or remove | 🟡 | `site/index.html` | Options: (A) Replace biometric ticker with a single contextual line: "Day X · Weight Y · Z% to goal", (B) keep ticker but reduce to 3 items max, (C) hide ticker pre-April 1 since numbers are stale. | Mara |
| 2.5 | Prequel banner → auto-hide after April 1 | 🟡 | `site/index.html` | Logic exists (`AMJ_EXPERIMENT.isLive`) but verify it fires correctly. After April 1, the prequel framing should disappear automatically. | James |

### 2B: Discovery Cards (Integrity Fix)

| # | Task | Priority | File(s) | Details | Source |
|---|------|----------|---------|---------|--------|
| 2.6 | Remove fake discovery cards | 🔴 | `site/index.html` | Remove all 3 hardcoded `.disc-fallback` cards with fabricated r-values and p-values. Non-negotiable. | Lena, Sofia |
| 2.7 | Replace with narrative insight cards | 🔴 | `site/index.html` | Option B from content audit: 3 cards based on real interview insights: (1) "Supplements → Sleep architecture" — measurable shifts in deep sleep tracked to evening stack changes, (2) "CGM → Anxiety relief" — data showed he wasn't in the danger zone, changed relationship with fear, (3) "Platform → Didn't prevent relapse" — the system watched the spiral happen without intervening. Frame as personal observations, not statistical claims. No r-values, no p-values. | Lena, Ava, Persona A |
| 2.8 | Keep dynamic loader as enhancement | 🟢 | `site/index.html` | The JS that fetches `/api/correlations?featured=true` can remain — when real FDR-significant correlations exist, they'll replace the narrative cards. But the fallback MUST be honest. | James |
| 2.9 | Fix "Day 1 vs Today" empty states | 🟡 | `site/index.html` | When data shows "—" for weight/habits/sleep/level, show a message: "Data populates after Day 1 (April 1)" instead of dashes. Prevents the broken-dashboard look for first-time visitors. | Mara, Persona B |

### 2C: Homepage API Consolidation

| # | Task | Priority | File(s) | Details | Source |
|---|------|----------|---------|---------|--------|
| 2.10 | Audit homepage API calls | 🟡 | `site/index.html` | Document all fetch() calls on homepage: public_stats.json, /api/habit_streaks, /api/character_stats, /api/correlations, /api/journey_timeline, /api/journey_waveform, /api/current_challenge. Target: reduce to 1 (public_stats.json) for homepage. | James |
| 2.11 | Extend public_stats.json with missing fields | 🟢 | `lambdas/` (daily brief pipeline) | Add character_stats, habit_streaks, and featured correlations to the daily public_stats.json generation so homepage can consume them without separate API calls. | James |

**Acceptance**: Homepage loads with 1 fetch. Hero has ≤5 elements. No fabricated stats anywhere. Clear primary CTA visible within 3 seconds.

---

## SESSION 3: CHRONICLE + SUBSCRIBE FUNNEL

**Goal**: Chronicle page polished for launch. Subscriber funnel has a sample issue and clear value proposition.

### 3A: Chronicle Polish

| # | Task | Priority | File(s) | Details | Source |
|---|------|----------|---------|---------|--------|
| 3.1 | Fix week numbering display | 🟡 | `site/journal/posts.json` | Options: (A) Re-number remaining articles sequentially (Prologue, Week 1, Week 2, Prequel), (B) Keep negative numbering but add "Prequel Series" label to make gaps expected, (C) Add a note on the chronicle page: "The prequel chronicles count backward from Day 1." Board recommendation: Option C — the countdown-to-Day-1 numbering is actually a feature if explained. | Ava, Persona D |
| 3.2 | Add chronicle numbering explainer | 🟡 | `site/chronicle/index.html` | Add a small note below the series intro cards: "Prequel chronicles count backward from Day 1 (April 1). Week −4 was four weeks before launch. The series resets to Week 1 after Day 1." | Ava |
| 3.3 | Create Elena Voss bio/byline page | 🟡 | New: `site/elena/index.html` | Standalone page for the Elena Voss persona. Include: who she is (AI journalist), her editorial approach, how she accesses the data, link to the chronicle. The "About the reporter" card on /chronicle/ should link here, not to /about/. | Ava, Persona D |
| 3.4 | Fix chronicle "About the reporter" link | 🟡 | `site/chronicle/index.html` | Change `<a href="/about/" class="series-intro__start">About the project →</a>` to point to `/elena/` once created. | Ava |
| 3.5 | Per-article OG meta tags | 🟢 | `site/journal/posts/*/index.html` | Each chronicle article should have unique og:title and og:description pulled from the article's title and excerpt, not the generic site OG image. | Jordan, Persona D |
| 3.6 | Unify subscribe naming | 🟡 | `site/assets/js/components.js`, multiple pages | Audit all subscribe CTAs. Standardize name to "The Weekly Signal" everywhere. Remove "Follow the experiment" variant or make it the tagline under the name. | Jordan, Persona D |

### 3B: Subscribe Funnel

| # | Task | Priority | File(s) | Details | Source |
|---|------|----------|---------|---------|--------|
| 3.7 | Create /chronicle/sample/ page | 🔴 | New: `site/chronicle/sample/index.html` | A sample newsletter issue — either a real past chronicle entry reformatted as an email preview, or a purpose-built "here's what you'll get" page showing: (1) what a weekly signal looks like, (2) frequency (every Wednesday), (3) what data sources feed it, (4) sample excerpt. | Jordan |
| 3.8 | Update subscribe page content | 🟡 | `site/subscribe/index.html` | Add: "What you'll get" section (weekly chronicle by Elena Voss, every Wednesday). "What it looks like" link to /chronicle/sample/. "When it starts" — Week 1 ships after April 1 Day 1. | Jordan |
| 3.9 | Differentiate CTA messaging by context | 🟢 | `site/assets/js/components.js`, `site/index.html`, `site/story/index.html`, `site/chronicle/index.html` | Chronicle page CTA: "Follow Elena's weekly chronicle." Homepage CTA: "Follow the experiment from Day 1." Data pages CTA: "Get AI-powered insights weekly." Story page CTA: "Follow the journey." | Jordan, Sofia |
| 3.10 | Tone down sticky subscribe bar | 🟡 | `site/index.html` | With only 4 articles, the sticky bar is aggressive. Options: (A) disable until Week 2 post-launch, (B) show only after 60 seconds on page, (C) keep but soften copy. Recommendation: Option B. | Jordan |

**Acceptance**: /chronicle/sample/ exists. Subscribe messaging is consistent. Chronicle numbering makes sense to a new visitor. Elena has a standalone bio page.

---

## SESSION 4: ABOUT PAGE + BUILDERS + EXPERIMENTS + THROUGHLINE

**Goal**: Fix remaining content issues. Build the HN landing page. Add throughline connectors across the site.

### 4A: About Page Fixes

| # | Task | Priority | File(s) | Details | Source |
|---|------|----------|---------|---------|--------|
| 4.1 | Fix "production code" wording | 🔴 | `site/about/index.html` | Change "I've never shipped production code at work" to "I'd never written and deployed production application code at work — though I've shipped plenty of infrastructure changes, database updates, and network upgrades." (Per content audit, already drafted.) | Ava, Persona A |
| 4.2 | Soften press/speaking sections | 🟡 | `site/about/index.html` | These sections are premature with zero press coverage. Options: (A) remove entirely, (B) move below fold with a "Coming soon" framing, (C) keep but add "First interviews welcome" tone. Recommendation: Option C — keep, but reframe from "Book me" to "I'd love to talk about this." | Sofia |
| 4.3 | Add "Why not Apple Health?" paragraph | 🟢 | `site/about/index.html` or `site/platform/index.html` | Persona B's #1 missing item. One paragraph: "Why build this instead of using Apple Health + Whoop app?" Answer: Apple Health aggregates but doesn't analyze. No AI coaching layer. No public accountability. No cross-source correlation engine. No character sheet. The platform's value is the intelligence layer on top. | Raj, Persona B |

### 4B: Builders Page (HN Landing)

| # | Task | Priority | File(s) | Details | Source |
|---|------|----------|---------|---------|--------|
| 4.4 | Build /builders/ page content | 🟡 | `site/builders/index.html` | The HN-audience landing page. Needs: (1) "How I built this" technical narrative, (2) architecture diagram (reuse from /platform/), (3) cost breakdown, (4) "Build your own" section with key decisions, (5) link to GitHub (if public) or architecture review methodology, (6) Key stats: Lambda count, tools, data sources, cost, review grade. | James, Jordan, Persona A |
| 4.5 | Add GitHub link or rationale | 🟢 | `site/builders/index.html` | If repo is public: link it. If private: explain why and link the architecture review grades instead. Persona A specifically asked for code proof. | James, Persona A |
| 4.6 | Add "How I built this" walkthrough | 🟢 | New: `site/builders/` content or `site/blog/` | The single most shareable piece for the technical audience. Could be a long-form article or a dedicated page. Covers: first Lambda, first deploy, role of Claude, what a non-engineer brings, mistakes made. Source material exists in STORY_DRAFTS_v1.md Chapter 03. | Ava, Persona A |

### 4C: Experiments + Discoveries

| # | Task | Priority | File(s) | Details | Source |
|---|------|----------|---------|---------|--------|
| 4.7 | Add "experiments begin April 1" empty state | 🟡 | `site/experiments/index.html` | All seed experiments are abandoned. Page should show: "N=1 experiments begin on Day 1 (April 1, 2026). Each experiment tests one variable at a time with a minimum 14-day window. Check back after launch." | Lena |
| 4.8 | Add "discoveries populate over time" state | 🟡 | `site/discoveries/index.html` | Timeline will be sparse. Add honest framing: "Discoveries are real findings from the correlation engine and completed experiments. This page populates as data accumulates — the first meaningful signals typically appear after 4–6 weeks." | Lena, Raj |
| 4.9 | Verify journey_timeline shows clean data | 🟡 | `lambdas/site_api_lambda.py` | Abandoned experiments should NOT appear on the timeline (the site-api only renders `active` and `completed`). Verify this is correct after today's 4 experiment abandonments. | James |

### 4D: Throughline Connectors

| # | Task | Priority | File(s) | Details | Source |
|---|------|----------|---------|---------|--------|
| 4.10 | Homepage → Story throughline | 🟡 | `site/index.html` | "Read my story" should be the primary CTA (done in Session 2). Also: the "about" section at bottom should link to /story/ before /chronicle/. | Raj |
| 4.11 | Story → Chronicle throughline | 🟡 | `site/story/index.html` | After Chapter 5, add: "Follow the weekly chronicle → /chronicle/" card. Already partially exists in the story-nav div. | Raj |
| 4.12 | Chronicle → Data throughline | 🟡 | `site/chronicle/index.html` | Add a "See the data behind the chronicles" link to /live/ or /explorer/ in the series intro area. | Raj |
| 4.13 | Live/Pulse → Story throughline | 🟡 | `site/live/index.html` | In the journey section at the bottom, add: "Read the full story → /story/" link. | Raj |
| 4.14 | Platform → Chronicle throughline | 🟡 | `site/platform/index.html` | Add a callout: "The platform generates a weekly chronicle. Read the latest → /chronicle/" somewhere on the platform page. | Raj |
| 4.15 | Data pages → Journey callout | 🟢 | `site/sleep/`, `site/glucose/`, `site/nutrition/`, `site/training/` | Each data page gets a one-sentence "What this means for the journey" callout. E.g., on /sleep/: "Sleep is the foundation — Matthew's recovery scores track directly to sleep quality. See how it connects → /character/." | Raj |

**Acceptance**: About page wording fixed. /builders/ has real content. Experiments/discoveries show honest empty states. Every major page links to at least one other section.

---

## SESSION 5: TECHNICAL POLISH + FULL BOARD REVIEW

**Goal**: Remaining technical debt. Then convene all 3 boards for launch readiness verdict.

### 5A: Technical Items

| # | Task | Priority | File(s) | Details | Source |
|---|------|----------|---------|---------|--------|
| 5.1 | Platform page auto-update stats | 🟢 | `site/platform/index.html` | Lambda/tool counts should pull from public_stats.json or data-const attributes, not be hardcoded. Verify data-const wiring works. | James |
| 5.2 | Pulse page empty state fallbacks | 🟢 | `site/live/index.html` | When /api/pulse returns empty data, show: "Today's pulse loads after the first full day of data (April 1). Here's what it will look like:" with a mockup or explanation. | Mara, Persona B |
| 5.3 | CloudFront invalidation after deploys | 🟢 | CI/CD pipeline / deploy scripts | Verify that HTML changes trigger CF invalidation. Currently the CI/CD pipeline deploys Lambdas but site HTML is pushed via git → S3 sync. Confirm invalidation runs. | James (tech board) |
| 5.4 | Methodology page personal voice | 🟢 | `site/methodology/index.html` | Add a "Why rigor matters to me" personal intro. Per Tier 3 content audit. | Lena, Ava |
| 5.5 | Weekly Snapshot page prep | 🟢 | `site/weekly/index.html` | Ensure the page has a "Weekly snapshots begin after Day 1" message and the pipeline is ready to generate the first one. | Ava |

### 5B: Design Warmth (Story/Chronicle Pages)

| # | Task | Priority | File(s) | Details | Source |
|---|------|----------|---------|---------|--------|
| 5.6 | Chronicle article serif emphasis | 🟢 | `site/journal/posts/*/index.html` or shared chronicle CSS | Ensure chronicle article body text uses the serif font (var(--font-serif)) prominently, not monospace. Tyrell's note: story pages should feel like journalism. | Tyrell |
| 5.7 | Story page editorial spacing | 🟢 | `site/story/index.html` | After chapter content is implemented, review spacing between chapters. Should feel like reading a long-form article, not a series of dashboard panels. | Tyrell |

### 5C: Full Board Review (All 3 Boards)

| # | Task | Priority | File(s) | Details | Source |
|---|------|----------|---------|---------|--------|
| 5.8 | Personal Board review of story content | 🟡 | Review only | Does Ch4 ("platform didn't prevent relapse") frame the failure appropriately? Does the vulnerability level match Matthew's comfort? Privacy guardrails respected? | Personal Board |
| 5.9 | Technical Board review of architecture changes | 🟡 | Review only | Homepage API consolidation. CloudFront invalidation. Any new endpoints for /builders/ page. Experiments empty state handling. | Technical Board |
| 5.10 | Product Board final launch verdict | 🟡 | Review only | Re-score each page after all changes. Issue a launch / no-launch / conditional-launch verdict for April 1. | Product Board |

**Acceptance**: All 3 boards convene. Launch readiness verdict issued. Any remaining items categorized as "ship post-launch" or "blocker."

---

## SUMMARY: TASK COUNT BY PRIORITY

| Priority | Count | Must complete by |
|----------|-------|-----------------|
| 🔴 BLOCKER | 8 | Before ANY public sharing |
| 🟡 HIGH | 24 | Before April 1 |
| 🟢 MEDIUM | 12 | First 2 weeks post-launch |
| ⚪ LOW | 3 | Backlog |
| **Total** | **47** | |

## BLOCKER TASKS (the non-negotiable 8)

1. **1.1** — Implement Story Chapter 1
2. **1.2** — Implement Story Chapter 2 prose
3. **1.3** — Implement Story Chapter 3 prose
4. **1.4** — Implement Story Chapter 4
5. **1.5** — Implement Story Chapter 5
6. **2.6** — Remove fake homepage discovery cards
7. **2.7** — Replace with narrative insight cards
8. **3.7** — Create /chronicle/sample/ page
9. **4.1** — Fix about page "production code" wording

(9 items — 4.1 is a trivial fix that can ship with any session)

## SESSION-BY-SESSION SCHEDULE

| Session | Target Date | Tasks | Est. Scope |
|---------|------------|-------|------------|
| Session 1 | Mar 27 | 1.1–1.10 (Story) | 10 tasks, heavy content |
| Session 2 | Mar 28 | 2.1–2.11 (Homepage) | 11 tasks, heavy HTML |
| Session 3 | Mar 29 | 3.1–3.10 (Chronicle + Subscribe) | 10 tasks, new pages |
| Session 4 | Mar 30 | 4.1–4.15 (About + Builders + Throughline) | 15 tasks, mixed |
| Session 5 | Mar 31 | 5.1–5.10 (Polish + Board Review) | 10 tasks, review |
| **April 1** | | **Day 1 — Launch** | |

---

## DEPENDENCIES & SEQUENCING

- Session 1 (Story) has **zero dependencies** — can start immediately
- Session 2 (Homepage) depends on Session 1 only for the throughline links from homepage → story
- Session 3 (Chronicle) is independent — can run in parallel with Session 2
- Session 4 (About/Builders/Throughline) depends on Sessions 1-2 for throughline targets existing
- Session 5 (Board Review) depends on Sessions 1-4 being complete

**Critical path**: Session 1 → Session 2 → Session 5. Sessions 3 and 4 can overlap.

---

## NEW FILES TO CREATE

| File | Session | Purpose |
|------|---------|---------|
| `site/elena/index.html` | 3 | Elena Voss bio/byline page |
| `site/chronicle/sample/index.html` | 3 | Sample newsletter issue for subscriber conversion |

## EXISTING FILES MODIFIED (major changes)

| File | Session(s) | Nature of Change |
|------|-----------|-----------------|
| `site/story/index.html` | 1 | All 5 chapters implemented with real prose |
| `site/index.html` | 2 | Hero simplified, discovery cards replaced, API calls reduced |
| `site/chronicle/index.html` | 3 | Numbering explainer, reporter link fix |
| `site/journal/posts.json` | 3 | Numbering adjustments |
| `site/assets/js/components.js` | 3 | Subscribe CTA messaging unified |
| `site/about/index.html` | 4 | Wording fix, press section softened |
| `site/builders/index.html` | 4 | Full content build |
| `site/experiments/index.html` | 4 | "Begins April 1" empty state |
| `site/discoveries/index.html` | 4 | "Populates over time" framing |
| `site/platform/index.html` | 4, 5 | Throughline + auto-updating stats |
| `site/live/index.html` | 4, 5 | Throughline + empty state |

---

*Implementation plan authored from Website Review #4 findings. All tasks traced to specific board member recommendations and audience persona feedback.*
