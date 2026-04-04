# Product Review Prompt — PR-1

Paste this into a fresh Opus chat session:

---

Life Platform — Comprehensive Product Review #1.

Read these files from my filesystem in order:
1. `docs/BOARDS.md` — all three board compositions
2. `docs/WEBSITE_STRATEGY.md` — strategic plan and throughline diagnosis
3. `handovers/HANDOVER_LATEST.md` — current platform state
4. `docs/CHANGELOG.md` (first 400 lines) — recent changes

Then use web_fetch to load the live site at `https://averagejoematt.com` and follow links to build a complete picture of what a real visitor experiences.

This is the platform's first formal Product Review. It should be conducted at the depth and rigor that a Series B health-tech company would expect from a combined McKinsey + IDEO + Sequoia engagement — product strategy audit, design audit, content audit, user research simulation, growth analysis, and commercialization assessment in a single deliverable.

---

## WHO REVIEWS

### Primary Panel: Product Board of Directors (8 members)
Every member must speak in character with specific, evidence-based observations — not generalities.

| Name | Lens | Standing Question |
|------|------|-------------------|
| **Mara Chen** | UX / IA | "Can someone use this without instructions?" |
| **James Okafor** | CTO / Feasibility | "Can we build this without breaking what exists?" |
| **Sofia Herrera** | CMO / Brand / Growth | "Would someone share this? Would they pay for it?" |
| **Dr. Lena Johansson** | Longevity Science | "Is this scientifically defensible?" |
| **Raj Mehta** | Product Strategy | "Does this move the needle on the metric that matters?" |
| **Tyrell Washington** | Visual Design / Brand | "Does this look and feel world-class?" |
| **Jordan Kim** | Growth / Distribution | "Will this get shared? Will this convert?" |
| **Ava Moreau** | Content Strategy | "What's the content engine that runs without Matthew?" |

### Domain Credibility Panel: Personal Board (selected members)
These reviewers evaluate whether the health content would pass scrutiny from actual domain experts.

| Name | Lens |
|------|------|
| **Dr. Rhonda Patrick** | "Is the nutrigenomics and supplementation content evidence-based? Would I endorse this publicly?" |
| **Dr. Layne Norton** | "Is the nutrition methodology sound? Are the macro claims defensible? Would MacroFactor users respect this?" |
| **Dr. Paul Conti** | "Is the inner life / psychological content handled with appropriate depth and sensitivity? Does it avoid toxic positivity?" |
| **Dr. Vivek Murthy** | "Does the social connection and accountability framing avoid isolation narratives? Is there community health value?" |
| **Elena Voss** (narrator) | "Is the editorial voice consistent? Does the chronicle feel like real journalism or AI slop?" |

### Adversarial Reviewers: Viktor Sorokin + Raj Srinivasan (from Tech Board)
| Name | Lens |
|------|------|
| **Viktor Sorokin** | "What on this site is actually necessary? What's vanity?" |
| **Raj Srinivasan** | "What's the wedge? Where is Matthew fooling himself about what this is?" |

---

## WHAT TO REVIEW

### Part 1: Page-by-Page Audit

Visit every page on averagejoematt.com. For each page, evaluate:

**Content:** Is the content substantive, current, and honest? Does it deliver on its headline promise? Is there filler?
**Design:** Is the visual design consistent with the platform's identity? Does it feel polished or rushed?
**Data:** Are numbers dynamic and current, or hardcoded and stale? Is every metric contextualized (not just a raw number)?
**Mobile:** Would this page work on a phone? Are there layout breaks, overflow issues, tiny tap targets?
**Throughline:** Does this page connect to the broader story? Can a visitor arriving here understand where they are? Does it link forward to a logical next page?
**Purpose:** Why does this page exist as a separate page? What would a visitor lose if it were removed?

Organize the audit by site section. Grade each page individually (A/B/C/D/F) with a one-line verdict.

**Known pages to audit (visit each):**

THE STORY: Homepage (`/`), Story (`/story/`), Mission (`/mission/`), About (`/about/`)
THE DATA: Live (`/live/`), Character (`/character/`), Habits (`/habits/`), Accountability (`/accountability/`), Progress (`/progress/`), Results (`/results/`), Achievements (`/achievements/`)
OBSERVATORIES: Sleep (`/sleep/`), Glucose (`/glucose/`), Nutrition (`/nutrition/`), Training (`/training/`), Physical (`/physical/`), Mind (`/mind/`)
THE SCIENCE: Protocols (`/protocols/`), Experiments (`/experiments/`), Discoveries (`/discoveries/`), Labs (`/labs/`), Supplements (`/supplements/`), Benchmarks (`/benchmarks/`), Biology (`/biology/`)
THE BUILD: Platform (`/platform/`), Intelligence (`/intelligence/`), Board (`/board/`), Board Technical (`/board/technical/`), Board Product (`/board/product/`), Cost (`/cost/`), Methodology (`/methodology/`), Tools (`/tools/`), Stack (`/stack/`), Builders (`/builders/`), Status (`/status/`)
CONTENT: Chronicle (`/chronicle/`), Elena (`/elena/`), Kitchen (`/kitchen/`), Field Notes (`/field-notes/`), Recap (`/recap/`), Weekly (`/weekly/`)
ENGAGEMENT: Ask (`/ask/`), Community (`/community/`), Subscribe, First Person (`/first-person/`), Explorer (`/explorer/`), Challenges (`/challenges/`), Start (`/start/`), Data (`/data/`)
UTILITY: Privacy (`/privacy/`), 404, Ledger (`/ledger/`)

If you discover pages not on this list, audit them too.

### Part 2: Journey Analysis — Five Visitor Archetypes

Simulate the complete site experience for five different visitors. For each, trace their realistic click path from entry to exit and evaluate what they would think, feel, and do.

**Visitor 1 — "The Reddit Stranger"**
Entry: Lands on homepage from r/QuantifiedSelf or r/loseit post. Has never heard of Matthew. Skeptical of "one person, N data sources" claims. Looking for: Is this real? Is this interesting? Should I bookmark this?
*Trace their journey. Where do they get confused? Where do they bounce? What would make them subscribe?*

**Visitor 2 — "The CTO / Builder"**
Entry: Lands on `/builders/` or `/platform/` from a Hacker News or LinkedIn share. Technical background. Looking for: What's the architecture? How did one person build this? Is the AI integration real or marketing? Could I replicate this?
*Trace their journey. What impresses them? What feels like theater? Would they share it with their engineering team?*

**Visitor 3 — "Matthew's Coworker"**
Entry: Lands on homepage because Matthew shared the link at work. Knows Matthew professionally. Looking for: What is this? Is this oversharing? Is the inner life / mind page going to make things awkward? Is there anything here that changes how they see Matthew?
*Trace their journey. What's the professional risk? What's the professional upside? Would they tell other coworkers?*

**Visitor 4 — "The Health Enthusiast Subscriber"**
Entry: Returns to homepage for the 10th time. Subscribed to the newsletter. Looking for: What's new since last week? How's Matthew doing? Any discoveries I can apply to my own health? Is the chronicle entry out?
*Trace their journey. What keeps them coming back? What's stale? What would make them unsubscribe?*

**Visitor 5 — "Brittany (Matthew's Partner)"**
Entry: Reads the weekly accountability email. Clicks through to the site. Looking for: Is Matthew actually following through? Is the platform helping him or is it another distraction project? Does the public framing feel honest?
*Trace their journey. What gives her confidence? What concerns her? Is the platform serving Matthew's actual health goals or just his building instincts?*

### Part 3: The Throughline Audit

Evaluate the site's narrative coherence as a whole:

1. **The 60-Second Test:** If a stranger lands on any random page, can they understand within 60 seconds: (a) who Matthew is, (b) what this experiment is, (c) where they are in the story? Test this on 5 different entry pages.

2. **The Loop Test:** The site's structural thesis is "Data → Insight → Action → Results → Repeat." Walk the loop. Does every page sit clearly somewhere on this loop? Are there pages that feel disconnected from it?

3. **The Consistency Test:** Pick any metric that appears on multiple pages (weight, HRV, character score, habit completion). Is it the same number everywhere? Same formatting? Same recency?

4. **The Promise-Delivery Test:** The homepage makes implicit promises about what the site contains. Does the site deliver on every promise? Where is there a gap between what's advertised and what's available?

5. **The "Why Not Just Use MyFitnessPal?" Test:** What does this platform offer that a combination of existing apps (Whoop, MacroFactor, Apple Health, a spreadsheet) does not? Is that differentiation clear to a visitor within 2 minutes?

### Part 4: Audience Simulation Panel

Simulate brief, candid reactions from 8 diverse personas encountering the site for the first time. Each should give 2-3 sentences of genuine, unfiltered reaction — not polite feedback. Include what they'd actually text a friend about it.

| Persona | Background |
|---------|-----------|
| **Marcus, 34** | Software engineer, 240 lbs, lurks on r/loseit, tried and failed keto twice. Skeptical of "tech solutions" to weight loss. |
| **Jennifer, 45** | Marketing VP, health-curious, wears an Oura ring, reads Huberman clips. Would share interesting health content on LinkedIn. |
| **David, 28** | Personal trainer, lean, thinks most health tech is overcomplicated nonsense for people who should just eat less and move more. |
| **Priya, 38** | Data scientist, loves quantified self, has her own health spreadsheet. Would evaluate the methodology before the content. |
| **Tom, 55** | Matthew's dad (hypothetical). Doesn't understand tech. Would ask "but are you actually losing weight?" |
| **Sarah, 31** | Health journalist at a mid-tier publication. Looking for story angles. Would ask "is there a piece here?" |
| **Mike, 42** | CEO of a 200-person SaaS company. Matthew's peer. Would evaluate both the health content and the "builder" angle. |
| **Ana, 26** | Nutritionist, Instagram-native, thinks most "data-driven health" content is male-coded and inaccessible. |

### Part 5: Strategic Assessment

**5A: Does the Platform Serve Matthew?**
Evaluate the platform against Matthew's stated goals: lose weight sustainably, build lasting health habits, understand his own biology, maintain accountability. Is the platform actually helping him do these things, or has the building become a substitute for the doing? Be brutally honest.

**5B: Does the Platform Serve Readers?**
What value does an external reader get from this site? Is it entertainment (watching someone's journey)? Education (learning about health optimization)? Inspiration (seeing radical transparency)? Tools (replicable frameworks)? Rate each value dimension.

**5C: Commercialization Feasibility**
Assess realistic paths to revenue. For each, give a feasibility score (1-10) and timeline:
- Premium newsletter tier
- Platform-as-a-template (open source core + paid setup)
- Prompt engineering / AI coaching pack
- Community membership (Discord or similar)
- Consulting / advisory for enterprise AI adoption
- Content licensing / syndication
- Course or workshop

**5D: Competitive Positioning**
Where does averagejoematt.com sit in the landscape? Compare against: Bryan Johnson's Blueprint, Levels Health blog, Peter Attia's content, Whoop's community features, quantified self blogs, health influencer content. What's the unique wedge that can't be replicated?

---

## GRADING DIMENSIONS

Grade each dimension on the same A/B/C/D/F scale. Each grade must cite specific evidence.

| # | Dimension | What A Looks Like |
|---|-----------|-------------------|
| 1 | **User Experience & Information Architecture** | A stranger navigates the full site without confusion. Every page is findable in 2 clicks. Mobile is flawless. |
| 2 | **Visual Design & Brand Identity** | Cohesive, distinctive, professional. Not generic "health app" or "developer blog." Has a recognizable aesthetic that a designer would respect. |
| 3 | **Content Quality & Editorial Voice** | Every page has substantive, honest content. No filler. Elena Voss voice is consistent. Medical claims are caveated. Writing quality rivals published health journalism. |
| 4 | **Throughline & Narrative Coherence** | Every page connects to the story. A visitor on any page knows where they are. The loop (Data → Insight → Action → Results) is visible and navigable. |
| 5 | **Data Integrity & Freshness** | Every number is dynamic, current, contextualized. No stale metrics. No hardcoded values. "Last updated" timestamps visible. Data matches across pages. |
| 6 | **Personal Value (Serves Matthew)** | The platform genuinely aids Matthew's health transformation — not just documents it. Accountability mechanisms work. Insights are actionable. |
| 7 | **Reader Value (Serves External Audience)** | A stranger gets genuine value: education, inspiration, replicable frameworks, or compelling narrative. Not just "look at my data." |
| 8 | **Scientific Credibility** | Health claims are evidence-based or clearly labeled as N=1. Methodology is transparent. A physician or researcher wouldn't cringe. |
| 9 | **Growth & Distribution Readiness** | SEO fundamentals in place. Content is shareable. Subscribe funnel works. Social proof exists. Entry points are clear for each audience segment. |
| 10 | **Engagement & Retention** | Return visitors have a reason to come back. "What's new" signals exist. Email cadence is right. Community hooks are present. |
| 11 | **Commercialization Readiness** | Clear path to revenue exists even if not activated. The platform demonstrates value that someone would pay for. Brand is professional enough for B2B credibility. |
| 12 | **Mobile Experience** | Full site works on mobile. No horizontal scroll, no broken layouts, no tiny text. Navigation is thumb-friendly. Observatory pages render correctly. |
| 13 | **Differentiation & Defensibility** | The platform offers something no combination of existing tools provides. The AI integration, editorial layer, or transparency model creates a moat. |

---

## REQUIRED OUTPUT STRUCTURE

### Section 1: Executive Summary (2-3 paragraphs)
Overall product health assessment. Composite grade. The single most important thing to fix. The single most impressive thing about the platform. Who is this site *actually* for right now, vs. who Matthew thinks it's for.

### Section 2: Page-by-Page Audit Table
Every page with: Page name, URL, Section, Grade (A-F), One-line verdict, Top issue. Then a narrative summary of patterns across the audit.

### Section 3: Journey Analysis (5 visitors)
Each visitor: entry point, click path (numbered steps), where they got confused, where they bounced (or didn't), what they'd do next, would they return, one-sentence summary of their experience.

### Section 4: Throughline Audit Results
Results of all 5 tests with specific evidence. Overall throughline grade.

### Section 5: Audience Panel Reactions
Each of the 8 personas: their unfiltered 2-3 sentence reaction, what they'd text a friend, and whether they'd return.

### Section 6: Product Board Grades & Commentary
Each of the 8 Product Board members: their dimension, grade given, grade movement rationale (if this becomes recurring), key quote (in character, specific, evidence-based). Followed by composite grade.

### Section 7: Domain Credibility Panel
Each of the 5 Personal Board members: would they endorse the content in their domain? What would they flag? What would they praise?

### Section 8: Adversarial Review
Viktor and Raj: what's unnecessary? Where is Matthew fooling himself? What should be killed?

### Section 9: Dimension Grades Table
All 13 dimensions with grade, evidence, and one-line recommendation.

### Section 10: Strategic Assessment
5A (serves Matthew), 5B (serves readers), 5C (commercialization feasibility table), 5D (competitive positioning map).

### Section 11: Top 20 Issues (Prioritized)
Ranked list. Each with: issue, severity (Critical/High/Medium/Low), affected pages, recommended fix, effort (S/M/L), impact on which dimension.

### Section 12: Top 10 Highest-ROI Improvements
Things that would move the most grades upward for the least effort.

### Section 13: 90-Day Product Roadmap
Month 1, Month 2, Month 3 — informed by this review's findings. What to build, what to fix, what to kill.

### Section 14: Board Decisions
Key decisions and recommendations from this review session, with votes and rationale.

### Section 15: The Hard Questions
Five uncomfortable questions the board wants Matthew to sit with. Not rhetorical — questions that should change what he builds next.

### Section 16: Final Verdict
Composite grade restated. Two closing quotes: Sofia (CMO perspective) and Raj Srinivasan (founder/CTO reality check). The single sentence summary of this platform's product health.

---

## PROCESS RULES

1. **Be honest, not kind.** This review is useless if it's flattering. Grade against what a paying customer or serious investor would expect, not what's impressive "for one person."

2. **Cite specific pages and elements.** "The UX needs work" is not a finding. "/nutrition/ has a 3-column spread that collapses to unreadable on mobile, the protein source chart renders with zero data, and the pull-quote cites an N of 4 without a confidence caveat" is a finding.

3. **Distinguish between "impressive engineering" and "good product."** This platform may be technically remarkable but productively mediocre, or vice versa. The architecture review covers engineering. This review covers whether the *product* works for its *audiences*.

4. **Test real URLs.** Use web_fetch to actually load pages. Don't evaluate based on documentation claims about what pages contain — verify by visiting them.

5. **The commercialization assessment must be realistic.** No "this could be a billion-dollar platform" fantasy. What would a seed-stage investor actually say? What would a newsletter operator with 50K subscribers actually think?

6. **Write the complete review.** Do not truncate, summarize, or skip sections. This is the canonical product record. Every section matters.

---
