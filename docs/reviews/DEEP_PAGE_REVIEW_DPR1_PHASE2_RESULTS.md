# Deep Page Review — DPR-1 Phase 2
## The Practice + The Platform + The Chronicle + Utility

**Date:** April 4, 2026 · **Platform:** v4.9.0  
**Pages reviewed:** 26 (6 Practice + 7 Platform + 5 Chronicle + 8 Utility)  
**Data source:** Playwright captures of live site (desktop 1440px)  
**Note:** Supplements, Challenges, and Experiment Library pages were captured during a known data pipeline bug that prevented content from rendering. Grades for those pages reflect the structure, copy, and design that IS visible; the empty content areas are a bug being fixed separately, not a design or content gap.

---

# SECTION: THE PRACTICE

*What Matthew actually does — protocols, supplements, experiments, challenges, discoveries.*

---

## The Stack — `averagejoematt.com/stack/`

**Page Grade: B+**

The lifecycle visualization (Challenges → Experiments → Protocols → Stack → Discoveries) is a signature concept that no other health platform has. It makes the entire Practice section coherent — every page has a role in the pipeline.

The hero stats show "19" data sources — but the platform page and every other reference says 26. This is the same class of hardcoded-number bug from the original audit.

The domain groupings (Sleep & Recovery, Movement & Training, Nutrition & Metabolic, Mind & Growth, Discipline & Vice Gates) with linked protocols, habits, and supplements create genuine cross-page threading. The "Go Deeper" section at the bottom acts as a hub linking to all Practice sub-pages.

**Key issues:** Data source count inconsistency (19 vs 26). The lifecycle counter shows "52 experiments" but the experiments page has 4 running and 0 completed — the 52 is the library size, not experiments run. Clarifying this label ("52 in library") would prevent confusion.

---

## Protocols — `averagejoematt.com/protocols/`

**Page Grade: A-**

The strongest Practice page. Six protocols, each with: description, key metrics, origin, mechanism, signal status, evidence links, linked habits, and linked supplements. The "Is This Working?" snapshot card at top provides instant status across all 6.

The writing is specific and personal: *"Right now, at the start of this, the protocol list is short. That's honest. Ask me again in six months."*

Every protocol has adherence showing "—" which is consistent with Day 4. The signal statuses (Positive/Pending) are appropriately differentiated. Evidence citations (Walker 2017, Seiler & Kjerland 2006, Zeevi et al. 2015, de Cabo & Mattson 2019) are specific and linked.

The pull-quote — *"The protocols aren't the interesting part. The interesting part is whether they survive contact with real data"* — is excellent editorial content.

**Key issue:** 30-day adherence is "—" for all 6 protocols. As data accumulates, this section becomes the most valuable longitudinal view on the site.

---

## Supplements — `averagejoematt.com/supplements/`

**Page Grade: B** *(structure grade — content was not rendering due to data pipeline bug)*

The hero copy is strong — personal, honest about methodology, with a clear "no affiliate links" disclaimer. The Daily Timing section (AM/Pre-Training/PM stacks) is useful and well-organized. The AG1 discontinuation with rationale is excellent content — explaining why something left the stack is as valuable as explaining what's in it.

The evidence rating system (Strong/Moderate/Emerging) and tier hierarchy (Essential/Supporting/Experimental) described in the hero are the right framework. The promise of genome-linked supplementation decisions (connecting to the Nutrition page's PEMT, VDR, FADS1, MTHFR data) is a genuine differentiator.

The main supplement cards were not rendering during capture due to a data pipeline bug being fixed separately. The structure, copy, and design scaffolding are sound.

**Product Board (Dr. Lena Johansson):** Once the content renders, verify that each supplement card clearly distinguishes evidence tiers. This matches the Henning Brandt evidence badge system from the Methodology page.

**Product Board (Raj Mehta):** The AG1 discontinuation pattern ("why I stopped") should exist for every paused supplement. That's the kind of honest content that builds trust.

---

## Experiments — `averagejoematt.com/experiments/`

**Page Grade: B+**

The 4 active experiments are well-structured: each has a hypothesis, progress bar (3 of 30 days), primary metric, pillar tags, and duration. The methodology section explaining N=1 limitations is honest and well-written.

The experiment library (52 candidates) was not loading during capture due to a data pipeline bug being fixed separately. The voting mechanism, launch roadmap, and monitored sources (PubMed, Huberman Lab, The Drive, Examine.com) are well-conceived features.

The "Suggest an Experiment" submission form and the H/P/D framework (Hypothesis/Protocol/Data) are good structural elements. The clear distinction between Experiments (science) and Challenges (action) is well-articulated.

The Record section ("No experiments match this filter") will naturally be empty until experiments complete — this is Day 4 of 30-day experiments. Appropriate.

---

## Challenges — `averagejoematt.com/challenges/`

**Page Grade: B-** *(structure grade — challenge data was not rendering due to pipeline bug)*

The concept copy is genuinely good: *"Challenges are my sandbox. No hypothesis required... Date nights. Acts of service. A week without complaining."* The distinction from experiments is clear. The Brittany co-creation framing is warm and humanizing.

The filter UI (duration, difficulty) and board recommends section are well-designed interactive elements. The "Experiments vs Challenges — How It Works" explainer correctly positions challenges as action-oriented complements to the more rigorous experiment framework.

Challenge data was not rendering during capture due to a data pipeline bug being fixed separately. The page structure and design are sound.

---

## Discoveries — `averagejoematt.com/discoveries/`

**Page Grade: B-**

The timeline is the most interesting element — it shows real entries: Day 1 milestone, 4 experiment launches, and several Inner Life discoveries (Nutrition Patterns, Journal Breakthroughs, Coaching Insights, Weekly Patterns) dating back to late March. These appear to be auto-generated from platform data.

The brutally honest metric: *"In 3 days, the platform surfaced 0 findings. 0 were investigated. 0 changed behavior."* and *"0% of AI findings led to behavioral change."* This is the kind of radical transparency that makes the platform credible — though 3 days isn't enough time to expect behavioral change from AI findings. Consider adding a "Day 4 — behavioral change tracking begins at Day 30" context note.

The "What I'm Currently Testing" section duplicates the Experiments page content. The "Inner Life Discoveries" section shows entries but they're title-only ("Nutrition Pattern — 2026-04-03") without expandable detail.

**Key issue:** Discovery entries are title-only without content. The duplication with Experiments page feels redundant. Consider making Discoveries a pure output page (confirmed findings + behavioral changes only).

---

## THE PRACTICE — Section Synthesis

**Section Grade: B+**

**Strongest page:** Protocols (A-). Clear structure, evidence-linked, honest about early state.

**Weakest page:** Discoveries (B-). Title-only entries and duplication with Experiments.

**Section throughline:** The lifecycle model (Challenges → Experiments → Protocols → Stack → Discoveries) is the best conceptual framework on the site. The Pipeline — with every stage represented by a page and connected to the others — creates a unique story about how health interventions evolve from idea to validated practice. As data pipeline bugs are resolved and all pages render their content, this section will be the platform's most distinctive offering.

**Missing page:** None — the 6 pages cover the practice comprehensively.

**Redundant content:** Discoveries duplicates active experiments. Consider making Discoveries a pure output page (confirmed findings + behavioral changes only) rather than also showing what's being tested.

---

# SECTION: THE PLATFORM

*How it's built — for builders and the curious.*

---

## How It Works — `averagejoematt.com/platform/`

**Page Grade: A**

This is the best technical showcase page on the site and possibly the most impressive single page for the builder audience. The architecture diagram is clear, comprehensive, and visually compelling. The three-zone structure (Pipeline, Guarantees, Surfaces) creates a logical progression.

The system design section shows every layer: 26 data sources → 13 ingest Lambdas → DynamoDB + S3 → 5 compute Lambdas → MCP/Email/Web outputs. All with real counts and real names.

The security posture section is thorough: least-privilege IAM, OIDC federation, OAuth 2.1, KMS encryption, PITR, read-only site API. The architecture review history showing 19 reviews with grades (R17 A- → R18 B+ → R19 A) adds credibility.

The finops summary ($19/month, $0.13 per data source, 0 idle cost, 0 engineers) is the most shareable stat on the site.

The "Tool Spotlight" section shows `get_sleep_environment_analysis` with a real finding ("Lowering bed temp by 2°F added +18 min deep sleep per night") — strong content that demonstrates the AI intelligence layer with a concrete example.

---

## The AI — `averagejoematt.com/intelligence/`

**Page Grade: B+**

All 14 intelligence systems are listed with descriptions and live data examples. The daily pipeline walkthrough (what Claude reads → what Claude outputs) is excellent educational content. The sample daily brief loading from the API is a strong proof-of-concept.

**Critical rendering bug:** System #4 (Character Engine) displays: *"Level — . Pillars: 0: [object Object], 1: [object Object]..."* — a JavaScript object serialization error. This is visible on the live page and looks broken.

The illustrative examples vs live data distinction is clear — systems marked "LIVE FROM TODAY'S DATA" show real numbers while "ILLUSTRATIVE EXAMPLE" shows representative patterns. This is honest labeling.

The Keystone Habit Detector (#10) shows a genuine finding: *"Weight logging → +8.3 pts average daily grade on days it's completed."* This is the kind of cross-domain insight that justifies the platform's existence.

---

## AI Board — `averagejoematt.com/board/`

**Page Grade: A-**

The interactive board Q&A is the most engaging feature in The Platform section. The sample response to "Should I prioritize sleep or exercise?" shows all 6 advisors giving distinct, in-character responses with genuine disagreement (Dr. Webb dissents from the sleep-first consensus). The Chair's synthesis resolves the tension clearly.

The advisor selection UI (checkboxes, select all/clear, suggested questions) is well-designed. The "5 free questions remaining" gate creates subscriber conversion pressure. The "How to Ask the Right Question" guide is genuinely useful.

**Technical Board tab** is present but the capture shows only the Health Board. The Technical Board (12 personas) should be equally accessible.

---

## Methodology — `averagejoematt.com/methodology/`

**Page Grade: A**

The strongest scientific credibility page on the site. The case study walkthrough — from raw correlation (r=+0.58 sleep × HRV) through hypothesis generation through 21-day observation (77% vs 25% hit rate) to protocol change — is the best single demonstration of the platform's value proposition.

The honest limitations section (sample size of one, correlation ≠ causation, observer effect, regression to the mean, Hawthorne effect, subject = engineer) is scientifically rigorous and builds trust through transparency.

The evidence badge system (Preliminary < 12, Emerging 12-29, Confirmed 30-59, Established 60+) based on the Henning Brandt standard is a well-designed credibility framework.

The closing section — *"The value isn't in the conclusions... The framework is portable"* — is the perfect articulation of the platform's thesis for external audiences.

---

## Cost — `averagejoematt.com/cost/`

**Page Grade: A**

Radical transparency executed well. Line-by-line AWS costs with explanations for why each is low. The architecture decisions section ("No always-on servers saves ~$40-80/mo vs EC2") contextualizes every choice.

The "What the $19 intelligence layer replaces" comparison ($60-150/mo health platform, $200+/hr data engineer, $300-500/mo concierge coaching) is the strongest commercial framing on the site.

Running total since launch (Feb: $8.20, Mar: $11.90) substantiates the $19 claim.

**One concern:** Status page shows "Projected: $25.67 — 171% of budget." This contradicts the $19 claim. Either the budget needs updating or the cost page needs a caveat about variable months.

---

## Tools — `averagejoematt.com/tools/`

**Page Grade: A-**

Seven interactive calculators, each showing Matthew's "Day 1" vs "Current" values alongside the visitor's inputs. This is the best "try it yourself" feature on the site after the Benchmarks Quick Check.

Tool #7 ("Start Your Own N=1 Experiment") is a 6-step getting-started guide that's the most actionable builder content outside the For Builders page.

Each calculator cites its methodology (Karvonen method, Morton et al. 2018, Rockport method) and includes appropriate disclaimers.

---

## For Builders — `averagejoematt.com/builders/`

**Page Grade: A**

The strongest page for the CTO/builder audience. The "What Claude Did vs What Matt Did" comparison table is the clearest articulation of the human-AI partnership model anywhere on the platform. The 8 architecture decisions ("CHOSE / AVOIDED" format with trade-offs) show genuine engineering judgment. The 8 lessons learned ("What Broke") are the kind of content that HN and technical Twitter would share.

The "Your First Weekend" guide (Saturday morning CDK init → Saturday afternoon second source + MCP → Sunday daily brief Lambda) is the highest-conversion content on the site for the builder persona.

**Key observation:** This page references "116 tools" on the status page but "121 tools" everywhere else. Minor inconsistency.

---

## THE PLATFORM — Section Synthesis

**Section Grade: A-**

**Strongest page:** Methodology (A). Portfolio-quality scientific credibility page.

**Weakest page:** None below B+. This is the strongest section on the site.

**Section throughline:** Platform → Intelligence → Board → Methodology → Cost → Tools → Builders creates a complete narrative: "Here's what it is → here's what the AI does → here's who advises → here's the scientific rigor → here's what it costs → try it yourself → build your own." This is the most coherent section navigation on the site.

---

# SECTION: THE CHRONICLE

*Editorial content engine — Elena Voss's domain.*

---

## Chronicle — `averagejoematt.com/chronicle/`

**Page Grade: A-**

The scrolling data ticker (WEIGHT 296.0 LBS ⬥ HRV 35 MS ⬥ RECOVERY 33% ⬥ STREAK 0D) is a striking design element that immediately establishes the data-journalism aesthetic.

4 prequel installments with strong titles: "Before the Numbers," "The Empty Journal," "The DoorDash Chronicle," "The Interview." The excerpts are compelling — *"a man who has built twenty-seven automated programs to monitor his sleep... who has not written a single journal entry since the day he started"* is exactly the kind of observational journalism that makes this concept work.

**"4 installments · 5,331 words"** — this meta-detail adds a sense of an emerging body of work.

---

## Weekly Snapshots — `averagejoematt.com/weekly/`

**Page Grade: B+**

Clean data companion to the Chronicle. Week 1 data displayed correctly. The week navigator creates an archival browsing experience. As weeks accumulate, this becomes a powerful longitudinal view.

---

## Weekly Recap — `averagejoematt.com/recap/`

**Page Grade: B-**

Condensed weekly summary with vital signs and domain highlights. The "Looking Ahead" section is a nice forward-looking element.

**Data issue:** Shows "WEIGHT 296.0 lbs +6.2 lbs (30d)" — this "+6.2" implies weight gain over 30 days, which contradicts the -11 lbs journey narrative. The 30-day window likely includes pre-experiment data when weight was lower. Also repeats the unsustainable -13.3 lbs/week projection from Physical.

---

## Ask the Data — `averagejoematt.com/ask/`

**Page Grade: B+**

Well-organized suggested questions. "5 questions remaining" gate creates subscriber conversion. Good disclaimers.

**Missing:** No example response shown. The Board page demonstrates its feature with a sample response — Ask should too.

---

## Subscribe — `averagejoematt.com/subscribe/`

**Page Grade: B**

Clear value proposition. **"Join 1 people following the experiment"** — same "1 people" grammar bug from the Accountability page.

---

## THE CHRONICLE — Section Synthesis

**Section Grade: B+**

**Strongest page:** Chronicle (A-). Elena Voss concept well-executed.

**Weakest page:** Recap (B-). Weight delta inconsistency and potential redundancy with Weekly Snapshots.

---

# SECTION: UTILITY

---

## Status — **A** | Privacy — **A** | Community — **C-** | Start — **B+** | Kitchen — **C** | Ledger — **B-** | Elena — **A-** | 404 — **B+**

**Status** is the most comprehensive system health page on a personal project. 43 components, honest stale warnings, operational sparklines. **Privacy** is exemplary plain-language policy. **Community** is the weakest page on the entire site — bare minimum for a platform that measures social connection as a pillar. **Start** is surprisingly strong and critically has a working narrative generator that the Pulse page lacks. **Kitchen** is a placeholder that should be hidden from nav. **Ledger** has a compelling concept but is theoretical at Day 4. **Elena** is excellent meta-content with beautiful closing line. **404** is on-brand.

---

# CROSS-SITE CLOSING ANALYSIS (All 4 Sections)

## Top 12 Issues (These Sections)

| # | Issue | Severity | Pages | Fix | Effort |
|---|-------|----------|-------|-----|--------|
| 1 | Intelligence page "[object Object]" rendering bug | Critical | Intelligence | Fix Character Engine data serialization in JS | XS |
| 2 | "1 people" grammar bug repeated | High | Subscribe | Fix pluralization (same fix as Accountability DPR-1.05) | XS |
| 3 | Recap "+6.2 lbs (30d)" contradicts weight loss narrative | High | Recap | Change 30d window to journey-start window, or add context | S |
| 4 | Stack shows "19 data sources" vs 26 everywhere else | High | Stack | Update to dynamic count from public_stats.json | XS |
| 5 | Community page is bare minimum | Medium | Community | Add member count, activity preview, or Matthew's personal CTA | S |
| 6 | Start page has working narrative but Pulse page doesn't | Medium | Start, Live | The Start page narrative logic should be the Pulse page narrative logic | S |
| 7 | Discovery entries are title-only without content | Medium | Discoveries | Add expandable detail or summary for each discovery entry | M |
| 8 | Cost page says $19 but Status shows $25.67 projected | Medium | Cost, Status | Reconcile — update cost page range or add "typical $11-25" framing | XS |
| 9 | Builders page says "116 tools" but elsewhere says 121 | Low | Builders, Status | Parameterize from public_stats.json | XS |
| 10 | Kitchen page visible in nav but is a placeholder | Low | Kitchen | Hide from nav until content exists | XS |
| 11 | Recap repeats unsustainable -13.3 lbs/week projection | Low | Recap | Same fix as Physical DPR-1.08 — confidence caveat | XS |
| 12 | Weekly Recap may be redundant with Weekly Snapshots | Low | Recap, Weekly | Consider merging into one page | M |

## Composite Grades (These Sections)

| Dimension | Grade | Evidence |
|-----------|-------|---------|
| Content depth | A- | Methodology, Builders, Elena, and Chronicle are exceptional. Practice pages have strong frameworks. |
| Design consistency | B+ | Platform section is cohesive. Practice pages follow a consistent card pattern. |
| Data integrity | B | "[object Object]" bug, 19 vs 26 sources, "+6.2 lbs" delta, 116 vs 121 tools |
| Return visitor value | B | Chronicle + Weekly Snapshots create weekly hooks. Most Platform pages are visit-once. |
| First-time visitor clarity | A- | Start page and Builders page are excellent entry points for their audiences. |
| Scientific credibility | A | Methodology page is portfolio-quality. Evidence badges, FDR correction, honest limitations. |
| Serves Matthew | B+ | Protocols and experiments will be valuable long-term. Lifecycle model drives behavior. |
| Commercialization | A- | Builders page alone could drive consulting leads. Cost transparency builds trust. |

## The Hard Questions (Viktor + Raj)

**Viktor:** *"The lifecycle model (Challenges → Experiments → Protocols → Stack → Discoveries) is the most original idea on this site. But on Day 4, the flywheel hasn't turned yet: 0 experiments completed, 0 discoveries from experiments, 6 protocols with no adherence data. The architecture is right. The question is whether Matthew will use the system he built — and whether 62 habits and 52 experiment candidates are setting up paralysis rather than progress."*

**Raj:** *"The Platform section is where Matthew is fooling himself most productively. These 7 pages are genuinely A-grade content — and they're the pages a CTO audience would share. The risk is that the Platform section becomes the product and the health transformation becomes the demo data. The $19/month cost page and the Builders guide are closer to a commercial product than anything in The Practice."*

---

## Final Summary Table (All 26 Pages)

| Page | Grade | Top Issue | Return? |
|------|-------|-----------|---------|
| Stack | B+ | "19 data sources" should be 26 | Maybe |
| Protocols | A- | Adherence all "—" (Day 4, expected) | Yes |
| Supplements | B | Hero and timing strong (content rendering bug being fixed) | Yes |
| Experiments | B+ | Active experiments well-structured | Yes |
| Challenges | B- | Good concept/copy (content rendering bug being fixed) | Yes |
| Discoveries | B- | Entries are title-only | Maybe |
| Platform | A | Minor — strong page | Yes (builders) |
| Intelligence | B+ | "[object Object]" rendering bug | Yes |
| Board | A- | Tech Board tab less accessible | Yes |
| Methodology | A | None — strongest science page | Yes (once) |
| Cost | A | $19 claim vs $25.67 projection | Yes (builders) |
| Tools | A- | None significant | Yes |
| Builders | A | "116 tools" inconsistency | Yes (builders) |
| Chronicle | A- | None significant | Yes (weekly) |
| Weekly | B+ | One week of data (expected) | Yes (weekly) |
| Recap | B- | "+6.2 lbs (30d)" contradicts narrative | Yes (weekly) |
| Ask | B+ | No sample response shown | Yes |
| Subscribe | B | "1 people" grammar | Yes |
| Status | A | None — excellent ops page | Yes (Matthew) |
| Privacy | A | None | No (visit-once) |
| Community | C- | Bare minimum content | No |
| Start | B+ | Has working narrative Pulse page lacks | Maybe |
| Kitchen | C | Placeholder only | No |
| Ledger | B- | Empty but well-conceptualized | No |
| Elena | A- | None | No (visit-once) |
| 404 | B+ | On-brand, functional | N/A |

---

*Review conducted April 4, 2026. Supplements, Challenges, and Experiment Library content were affected by a data pipeline bug during capture — grades reflect visible structure only. All other page content evaluated from Playwright desktop captures.*
