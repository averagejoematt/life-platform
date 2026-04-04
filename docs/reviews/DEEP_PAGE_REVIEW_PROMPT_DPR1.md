# Deep Page Review Prompt — DPR-1

Paste this into a fresh Opus chat session:

---

Life Platform — Deep Page-by-Page Product Review.

Read these files from my filesystem:
1. `docs/BOARDS.md` — all three board compositions
2. `docs/WEBSITE_STRATEGY.md` — strategic plan, throughline thesis, and information architecture
3. `handovers/HANDOVER_LATEST.md` — current platform state
4. `docs/reviews/PRODUCT_REVIEW_PROMPT_PR1.md` — the strategic product review prompt (for context on grading standards and board personas — you are conducting the companion deep review, not repeating the strategic one)

This review is the **deep companion** to the strategic Product Review (PR-1). Where PR-1 evaluates the platform holistically — throughline, audience fit, commercialization — this review goes **inside every single page** and evaluates it element by element, widget by widget, paragraph by paragraph.

Think of PR-1 as the board-level strategy deck. Think of this as the **product manager's annotated wireframe review** — the document that tells the design team and engineering team exactly what to fix, move, add, or kill on every page, and why.

---

## SCOPE SELECTION

**Before starting, ask me which scope I want:**

> Which sections should I review?
>
> **A) Full Suite** — All 6 sections + utility pages (~45 pages). This is the complete review.
> **B) The Story** — Home, My Story, The Mission, Milestones, Field Notes, First Person (6 pages)
> **C) The Data** — Sleep, Glucose, Nutrition, Training, Physical, Inner Life, Labs, Benchmarks, Data Explorer (9 pages — the observatory pages)
> **D) The Pulse** — Today, The Score, Habits, Accountability (4 pages)
> **E) The Practice** — The Stack, Protocols, Supplements, Experiments, Challenges, Discoveries (6 pages)
> **F) The Platform** — How It Works, The AI, AI Board, Methodology, Cost, Tools, For Builders (7 pages)
> **G) The Chronicle** — Chronicle, Weekly Snapshots, Weekly Recap, Ask the Data, Subscribe (5 pages)
> **H) Utility** — Status, Privacy, Community, Start, 404, Kitchen, Ledger, Elena (8 pages)

Wait for my selection before proceeding. If I say "all" or "full suite," do every section in order with a commit point between each section.

---

## WHO REVIEWS EACH PAGE

Every page gets evaluated through **7 lenses**. Not every lens writes a full paragraph — some may have nothing to say on a given page. But every lens must be considered.

### Lens 1: Product Board (primary)
The 8 Product Board members evaluate from their domain. Not all 8 speak on every page — only those whose domain is relevant. Always in character, always citing specific elements.

| Member | When they speak |
|--------|----------------|
| **Mara Chen** (UX) | Every page — navigation, layout, information hierarchy, mobile, cognitive load |
| **Tyrell Washington** (Design) | Every page — visual consistency, typography, spacing, color, brand identity, dark/light mode |
| **Raj Mehta** (Product) | Every page — does this page earn its existence? What's the metric it moves? |
| **Ava Moreau** (Content) | Pages with editorial content — is the writing good? Is there filler? Is the voice consistent? |
| **Jordan Kim** (Growth) | Pages with CTAs, subscribe hooks, share mechanics — is this page doing distribution work? |
| **Sofia Herrera** (CMO) | Landing pages, story pages, share-worthy pages — would someone screenshot this? |
| **Dr. Lena Johansson** (Science) | Observatory pages, protocols, supplements, labs — is this scientifically defensible? |
| **James Okafor** (CTO) | Pages with live data, API-driven content, interactive elements — is this technically sound? |

### Lens 2: Domain Expert Panel (on relevant pages)
| Expert | Pages they review |
|--------|------------------|
| **Dr. Rhonda Patrick** | Nutrition, Supplements, Labs, Glucose — nutrigenomics and evidence quality |
| **Dr. Layne Norton** | Nutrition, Training, Physical — macro methodology, body composition claims |
| **Dr. Paul Conti** | Inner Life (Mind), First Person, Field Notes — psychological depth and safety |
| **Dr. Vivek Murthy** | Accountability, Community — social connection framing |
| **Elena Voss** | Chronicle, Weekly Snapshots, Recap — editorial voice and narrative consistency |

### Lens 3: The Return Visitor
Someone who has visited 10+ times. What's new? What's stale? Is there a reason to come back to this specific page this week? Would they bookmark it?

### Lens 4: The First-Time Stranger
Someone who just landed on this page from a search result or social share. Do they understand what this is within 10 seconds? Can they navigate to context? Would they stay or bounce?

### Lens 5: Matthew (Platform Owner)
Does this page serve Matthew's actual health transformation? Is the data actionable for him? Does the AI coaching text say something useful or is it generic motivation? Would this page change his behavior tomorrow?

### Lens 6: The Skeptic (Viktor Sorokin)
Is this page necessary? Is it honest? Is there anything that looks impressive but is actually hollow? Would a thoughtful critic call this out?

### Lens 7: The Commercialization Eye (Raj Srinivasan)
If this platform were a product, would this page contribute to someone paying for it? Does it demonstrate value? Does it create "I want this for myself" desire?

---

## HOW TO REVIEW EACH PAGE

For every page, use `web_fetch` to load the live URL at `https://averagejoematt.com/[path]/`. Read the actual HTML content. Do not rely on documentation about what a page contains — verify by visiting it.

For each page, produce this structured analysis:

### [Page Name] — `averagejoematt.com/[path]/`

**Page Grade: [A/B/C/D/F]**

**① Content Audit**
- What does the page actually say? Is the text substantive or filler?
- Is the AI-generated coaching/insight text (if present) genuinely useful or generic platitudes? Quote the specific text and evaluate it.
- Are health claims appropriately caveated? Would Dr. Lena or Dr. Rhonda flag anything?
- Is there content that should exist on this page but doesn't?
- Is there content that exists but belongs on a different page?

**② Visual & Layout Audit**
- What's the visual hierarchy? Where does the eye go first?
- Are widgets and charts placed logically? Does the layout tell a story from top to bottom?
- Is there visual clutter — too many cards, badges, or decorative elements competing for attention?
- How does the design compare to the observatory pattern (2-column hero, gauge rings, pull-quotes, editorial spreads)? Is this page consistent with the design system or an outlier?
- Dark mode evaluation: are colors readable? Are charts legible?
- Tyrell's verdict on whether this page could appear in a design portfolio.

**③ Data & Widgets Audit**
- What data is displayed? Is it current (check timestamps, "last updated" indicators)?
- Are numbers dynamic (from API) or do they look hardcoded?
- Do charts/graphs have sufficient data to be meaningful? A chart with 3 data points is worse than no chart.
- Are metrics contextualized? (Raw numbers like "HRV: 29" mean nothing without range/trend/baseline context)
- Is the right data on this page? Is there data that should be here but isn't?
- Are there widgets that add visual noise without informational value?

**④ Graphs & Analysis Audit**
- For each chart/graph on the page: What does it show? Does it tell a meaningful story? Could a non-expert understand it?
- Are axis labels clear? Are scales appropriate? Are trends actually visible?
- Is the analysis presented alongside the graph useful? Or is it just describing what the viewer can already see?
- What analysis is MISSING? What would an expert want to see that isn't here?
- Henning Brandt's statistical lens: are any visual claims misleading due to small N, truncated axes, or cherry-picked windows?

**⑤ Return Visitor Value**
- If someone visited this page last week, what's different today? Is there a visible "what changed" signal?
- Would a subscriber bookmark this page and check it weekly? Why or why not?
- What would make this page a "must-check" for returning visitors?
- Freshness indicators: are they present? Are they working?

**⑥ First-Time Visitor Experience**
- If this is the only page someone sees, do they understand the platform?
- Is there enough context, or does the page assume knowledge from other pages?
- What's the most likely next click from this page? Is that click path obvious?
- Where would a stranger bounce? What would confuse them?

**⑦ Serves Matthew**
- Does the data/content on this page help Matthew make a health decision?
- Is the AI coaching text (if any) specific to Matthew's situation, or could it apply to anyone?
- If Matthew looked at this page at 7am, would it change what he does today?
- What should this page show Matthew that it currently doesn't?

**⑧ Multi-Lens Verdict**

| Lens | Grade | Key Observation |
|------|-------|-----------------|
| Product Board (composite) | | |
| Domain Expert | | |
| Return Visitor | | |
| First-Time Stranger | | |
| Serves Matthew | | |
| Skeptic (Viktor) | | |
| Commercialization | | |

**⑨ Page-Specific Roadmap**
Ordered list of changes for this page, each tagged:
- 🔴 **Fix** — broken or wrong, fix immediately
- 🟡 **Improve** — works but could be significantly better
- 🟢 **Add** — new feature/content that would elevate the page
- ⚪ **Consider** — idea worth exploring, not urgent
- 🗑️ **Remove** — element that should be deleted

Each item should note: what to change, why, which lens identified it, effort (S/M/L).

---

## SECTION-LEVEL ANALYSIS

After reviewing all pages in a section, write a **section-level synthesis**:

1. **Section Grade** (A/B/C/D/F)
2. **Strongest page** in the section and why
3. **Weakest page** in the section and why
4. **Section throughline**: do the pages in this section tell a coherent story when navigated in sequence?
5. **Cross-page consistency**: are design patterns, data freshness, voice, and navigation consistent across pages in this section?
6. **Missing page**: is there a page this section needs that doesn't exist?
7. **Redundant page**: is there a page in this section that should be merged or killed?

---

## SITE PAGES BY SECTION

### THE STORY (narrative entry points)
| Page | URL | Purpose |
|------|-----|---------|
| Home | `/` | The hook — who Matthew is, what this is, current state |
| My Story | `/story/` | Origin narrative — the why |
| The Mission | `/mission/` | What Matthew is trying to accomplish |
| Milestones | `/achievements/` | Journey milestones and achievements |
| Field Notes | `/field-notes/` | Weekly AI Lab Notes — present/lookback/focus |
| First Person | `/first-person/` | Matthew's voice, unfiltered |

### THE DATA (observatory pages — the science showcase)
| Page | URL | Purpose |
|------|-----|---------|
| Sleep | `/sleep/` | Sleep architecture, environment, optimization |
| Glucose | `/glucose/` | CGM intelligence, time-in-range, meal responses |
| Nutrition | `/nutrition/` | Macros, eating patterns, food delivery behavioral data |
| Training | `/training/` | Exercise modalities, training load, Banister model |
| Physical | `/physical/` | Body composition, walking, breathwork, strength |
| Inner Life | `/mind/` | Mood, psychological patterns, vice streaks, journaling |
| Labs | `/labs/` | Bloodwork biomarkers, clinical results |
| Benchmarks | `/benchmarks/` | Centenarian decathlon targets, strength standards |
| Data Explorer | `/explorer/` | Interactive data exploration tool |

### THE PULSE (real-time state — "how is Matthew doing right now?")
| Page | URL | Purpose |
|------|-----|---------|
| Today | `/live/` | Live dashboard — current vitals, today's status |
| The Score | `/character/` | Character sheet — 7-pillar composite score |
| Habits | `/habits/` | Habit heatmap, tiers, streaks, adherence |
| Accountability | `/accountability/` | Partner-facing accountability view |

### THE PRACTICE (what Matthew actually does)
| Page | URL | Purpose |
|------|-----|---------|
| The Stack | `/stack/` | Complete health stack overview |
| Protocols | `/protocols/` | Active health protocols with evidence links |
| Supplements | `/supplements/` | Supplement registry with genome rationale |
| Experiments | `/experiments/` | Active N=1 experiments |
| Challenges | `/challenges/` | Gamified behavioral challenges |
| Discoveries | `/discoveries/` | Confirmed findings from data analysis |

### THE PLATFORM (how it's built — for builders and the curious)
| Page | URL | Purpose |
|------|-----|---------|
| How It Works | `/platform/` | Architecture and data flow overview |
| The AI | `/intelligence/` | Intelligence Compounding system |
| AI Board | `/board/` | Board of Directors personas and methodology |
| Methodology | `/methodology/` | Statistical rigor, N=1 framework, limitations |
| Cost | `/cost/` | AWS cost breakdown and efficiency |
| Tools | `/tools/` | Interactive platform tools |
| For Builders | `/builders/` | The meta-story — building with AI as a non-engineer |

### THE CHRONICLE (editorial content engine)
| Page | URL | Purpose |
|------|-----|---------|
| Chronicle | `/chronicle/` | Elena Voss investigative series — "The Measured Life" |
| Weekly Snapshots | `/weekly/` | Automated weekly data summaries |
| Weekly Recap | `/recap/` | Curated weekly highlights |
| Ask the Data | `/ask/` | AI Q&A — ask questions about Matthew's data |
| Subscribe | `/subscribe/` | Email subscription funnel |

### UTILITY & OVERFLOW
| Page | URL | Purpose |
|------|-----|---------|
| Status | `/status/` | System health dashboard |
| Privacy | `/privacy/` | Privacy policy |
| Community | `/community/` | Discord community CTA |
| Start | `/start/` | Visitor routing / start here |
| Kitchen | `/kitchen/` | Food/recipe content |
| Ledger | `/ledger/` | Charitable giving ledger |
| Elena | `/elena/` | Elena Voss persona page |
| 404 | `/404` | Error page |

---

## CLOSING ANALYSIS (after all selected sections are reviewed)

### Cross-Site Throughline Report

After reviewing all pages, evaluate the site as a connected experience:

1. **Narrative coherence score (1-10):** If you read every page in nav order, does a story emerge? Or is it a collection of disconnected dashboards?

2. **The 3-click test:** From any page, can a visitor reach the 3 most important pages (Home, Character Score, Subscribe) within 3 clicks? Test from 5 random pages.

3. **Voice consistency:** Is the editorial voice the same across all pages? Are there pages where the tone shifts jarringly (e.g., from editorial storytelling to raw technical documentation)?

4. **Design system adherence:** Which pages follow the observatory design pattern (2-column hero, gauge rings, pull-quotes, evidence badges) and which are outliers? Should the outliers conform or is variety appropriate?

5. **Data freshness map:** For every page that displays data, when was it last refreshed? Create a freshness heatmap — which pages are live/daily, which are weekly, which are stale?

6. **The "addiction" audit:** Which pages create a reason to return? Which are visit-once-and-done? For each visit-once page, what would transform it into a regular check-in?

7. **The subscription funnel:** Trace the path from "stranger arrives" to "subscriber confirmed." How many pages is the CTA visible on? Is the value proposition clear? What's the friction?

### Composite Grades

| # | Dimension | Grade | Key Evidence |
|---|-----------|-------|-------------|
| 1 | Content depth & substance | | |
| 2 | Visual design consistency | | |
| 3 | Data integrity & freshness | | |
| 4 | Widget/chart usefulness | | |
| 5 | Return visitor value | | |
| 6 | First-time visitor clarity | | |
| 7 | Serves Matthew's health goals | | |
| 8 | Reader/subscriber value | | |
| 9 | Throughline & narrative flow | | |
| 10 | Mobile experience | | |
| 11 | Scientific credibility | | |
| 12 | Engagement & "stickiness" | | |
| 13 | Commercialization readiness | | |

### Top 20 Cross-Site Issues
Ranked by impact. Each with: issue, severity, affected pages, recommended fix, effort, which lens identified it.

### Top 10 "Addiction" Features
Ideas that would make readers bookmark pages and check back regularly — the positive engagement hooks that create habitual return visits. For each: what it is, which page(s) it applies to, why it works psychologically, effort to build.

### Section-by-Section Roadmap Summary
For each section reviewed, the top 3 priorities distilled from the page-level roadmaps.

### The Hard Questions (from Viktor + Raj)
Five uncomfortable observations about what the site reveals about Matthew's priorities, where the building may be outpacing the doing, and what a brutally honest friend would say after spending an hour on the site.

### Final Page-Level Summary Table

| Page | Grade | Top Issue | #1 Fix | Return Value |
|------|-------|-----------|--------|-------------|
| (every page reviewed) | | | | (Would a subscriber revisit? Y/N/Maybe) |

---

## PROCESS RULES

1. **Visit every page live.** Use `web_fetch` on `https://averagejoematt.com/[path]/`. Do not evaluate pages from documentation — see what a real visitor sees.

2. **Quote specific text.** When evaluating AI coaching text, pull-quotes, or editorial content — quote the actual words on the page and evaluate them. "The content is good" is not useful. "The pull-quote says 'Recovery is trending upward' but HRV has been flat for 2 weeks — this is a credibility gap" is useful.

3. **Screenshot-level specificity.** Describe what you see as if annotating a screenshot. "Below the hero section, there's a 3-column spread with gauge rings. The left gauge shows weight at 287 with no trend arrow. The middle gauge shows..." This level of detail is what makes the review actionable.

4. **Grade honestly against professional standards.** An A page is one that a paid design/content agency would be proud to show in their portfolio. A B page is solid but has clear improvement opportunities. A C page has structural problems. Grade against what a Stripe, Notion, or Whoop page would look like — not against "impressive for one person."

5. **Every page roadmap must be actionable.** Not "improve the design." Instead: "Replace the 4-column metric grid with a 2-column editorial layout matching the Nutrition observatory pattern. Move the AI coaching card above the fold. Add a 7-day sparkline to each metric. Remove the empty 'Coming Soon' placeholder."

6. **Do not truncate.** Every page gets the full 9-point analysis. Every section gets the synthesis. The closing analysis covers all cross-site dimensions. This is the complete product record.

---
