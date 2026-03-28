# PRE-LAUNCH OFFSITE — BUILD PLAN (PART 3)
## March 27, 2026 · 5 Days to April 1 Go-Live
### Joint Session: Health Board + Product Board + Cold Reviewers

---

## SESSION STATUS

**Part 1 completed:** Decisions 1–11
**Part 2 completed:** Decisions 12–15
**Part 3 completed:** Decisions 16–24 + Meta-discussions (P-series, S-series)
**Part 4 pending:** Remaining pages + final prioritization

### PAGES REVIEWED (Part 3)
- [x] Supplements / The Pharmacy — `/supplements/` (Decision 16)
- [x] Protocols — `/protocols/` (Decision 17)
- [x] Stack — `/stack/` (Decision 18)
- [x] Experiments / The Lab — `/experiments/` (Decision 19)
- [x] Challenges / The Arena — `/challenges/` (Decision 20)
- [x] Chronicle — `/chronicle/` (Decision 21)
- [x] Subscribe — `/subscribe/` (Decision 22)
- [x] Weekly Snapshots — `/weekly/` (Decision 23)
- [x] Ask the Data — `/ask/` (Decision 24)

### META-DISCUSSIONS RESOLVED (Part 3)
- [x] The Practice Section Hierarchy (P-series, 7 recommendations)
- [x] Strategic Engagement Model (S-series, 9 recommendations)

### PAGES REMAINING (Part 4)
- [ ] Platform / How It Works — `/platform/`
- [ ] The AI / Intelligence — `/intelligence/`
- [ ] AI Board — `/board/`
- [ ] Cost — `/cost/`
- [ ] Methodology — `/methodology/`
- [ ] Tools — `/tools/`
- [ ] For Builders — `/builders/`
- [ ] Home page (re-review in light of all decisions)
- [ ] Story page — `/story/` (rewritten in v3.9.41)
- [ ] About / Mission — `/about/` (restructured in v3.9.41)
- [ ] **Cross-cutting:** Final prioritization, April 1 vs post-launch sort, implementation sequencing

---

## META-DECISION: The Practice Section Hierarchy ✅ APPROVED

**Problem:** Six pages in The Practice section (Stack, Protocols, Supplements, Experiments, Challenges, Discoveries) presented as equal siblings but are actually a lifecycle. Visitor confusion about what is what, where to start, how things relate.

**Approved lifecycle definition:**

| Concept | Definition | Analogy | Role |
|---------|-----------|---------|------|
| Challenge | Time-bounded provocation. A dare. | "The dare" | Engagement layer |
| Experiment | Formal hypothesis test. ≥14 days. Defined criteria. | "The controlled test" | Testing ground |
| Protocol | Evidence-validated intervention. Runs continuously. Reviewed quarterly. | "The validated intervention" | Operating layer |
| Supplement | Specific input. Evidence-rated. Part of protocol stack. | "The pharmacy" | Input detail |
| Stack | Complete current state. All protocols + supplements + habits + sources. | "The lab's current configuration" | Overview / index |
| Discovery | What the process produced. Finding → Action → Outcome. | "The published result" | Output / learning |

**Lifecycle flow:** Challenge/Experiment → (evidence) → Protocol → (part of) Stack. Discoveries are the output at every stage.

**Approved recommendations (P-series):**

| # | Recommendation | Category | Effort | Priority |
|---|---------------|----------|--------|----------|
| P-1 | Add hierarchy explainer to Stack page — lifecycle diagram with live counts | IA/Content | Medium | Must-have |
| P-2 | Add "what is a protocol?" definition to Protocols page | Content | Low | Must-have |
| P-3 | Add lifecycle badges to Protocol cards — "Origin: Experiment #14" | Feature/Content | Low | Should-have |
| P-4 | Add lifecycle badges to Experiments — "Status: Graduated → Protocol" | Feature/Content | Low | Should-have |
| P-5 | Add pipeline visualization — Challenge → Experiment → Protocol → Stack → Discovery | Design/Feature | Medium | Should-have |
| P-6 | Cross-link every Practice page with "You are here" orientation | IA | Low | Must-have |
| P-7 | Make Stack the section landing page, reorder nav to lifecycle sequence | IA | Low | Must-have |

---

## META-DECISION: Strategic Engagement Model ✅ APPROVED

**Approved model:**

- **Launch with ONE subscription: "The Measured Life"** — weekly, containing data signal + Elena's narrative + anomaly highlights
- **The Kitchen becomes Channel 2** at Month 2-3 per Decision 10 roadmap
- **Engagement hierarchy:** Email (trigger) → Vote/Follow (low effort) → Nudge/React (5 seconds) → Submit ideas (high engagement)
- **Do NOT build reader streaks/habits at launch**

**Approved recommendations (S-series):**

| # | Recommendation | Category | Effort | Priority |
|---|---------------|----------|--------|----------|
| 22-S1 | Launch with ONE subscription — "The Measured Life" | Strategy/Guardrail | — | Guardrail |
| 22-S2 | Mention future channels as coming attractions on subscribe page | Content/Growth | Low | Should-have |
| 22-S3 | Plan The Kitchen as Channel 2 at Month 2-3 | Strategy | — | Post-launch |
| 22-S4 | Define engagement hierarchy — no reader streaks/habits at launch | Strategy/Guardrail | — | Guardrail |
| 22-S5 | Build "Ask Elena" submission mechanic — moderated queue | Feature | Medium | Should-have |
| 22-S6 | Add submission scope disclaimer — not personal health advice | Content/Legal | Low | Must-have (if S5) |
| 22-S7 | "Your question was featured" notification | Feature/Growth | Low | Post-launch |
| 22-S8 | Post-launch: prediction mechanic for experiments | Feature/Growth | Medium | Post-launch |
| 22-S9 | Post-launch: segment based on engagement data after 500+ subs | Strategy | — | Post-launch |

---

## DECISION 16: Supplements / The Pharmacy (`/supplements/`) ✅ LOGGED

**Current state:** 600+ line page, 21 supplements in 5 purpose groups, hardcoded JS registry, evidence rating system (Strong/Moderate/Emerging), genome section (3 SNPs), "Supplements I'm Questioning" honest assessment (6 flagged). No-affiliate-links integrity banner.

**Data layer:** 18 supplements tracked, 29% adherence across 31 days. Lion's Mane, Cordyceps, Reishi show zero tracking entries.

**Core diagnosis:** The honest assessment section is the crown jewel. The closed loop (supplement → lab validation) is promised but not delivered. 29% adherence is the human story. Page is static/hardcoded when it should be API-driven.

**Approved recommendations:**

| # | Recommendation | Category | Effort | Priority |
|---|---------------|----------|--------|----------|
| 16a | Add narrative intro — supplement journey story | Content | Low | Must-have |
| 16b | Add adherence data to page — live % from supplement log | Data/Feature | Medium | Must-have |
| 16c | Add daily timing timeline — AM/Pre-training/PM visual schedule | Feature/Design | Medium | Must-have |
| 16d | Resolve phantom supplements — Lion's Mane/Cordyceps/Reishi: track or remove | Content/Credibility | Low | Must-have |
| 16e | Close the loop on 2-3 supplements with lab data | Data/Content | Medium | Must-have |
| 16f | Make registry API-driven — move from hardcoded JS to config/API | Architecture | Medium | Should-have |
| 16g | Add cost transparency — monthly cost per supplement + total | Content | Low | Should-have |
| 16h | Elevate genome section — move higher, expand SNP cross-references | Content/Design | Medium | Should-have |
| 16i | Add supplement tier hierarchy — essential vs supporting vs experimental | Design/Content | Low | Should-have |
| 16j | Add stack evolution timeline | Feature/Content | Medium | Should-have |
| 16k | Cross-link to experiments | IA | Low | Should-have |
| 16l | Add synergy visualization for stacks-within-stack | Design | Medium | Nice-to-have |
| 16m | Share mechanics — honest assessment + individual cards | Growth | Low | Should-have |
| 16n | Editorial design alignment pass | Design | Med-High | Should-have |
| 16o | Fix breadcrumb to "The Practice > The Pharmacy" | Bug | Low | Must-have |
| 16p | Clarify relationship to Stack page | IA | Low | Must-have |
| 16q | Don't add "Considering" section — route to Experiments as upcoming hypotheses | Guardrail | — | Guardrail |
| 16r | Add source links to "What the science says" — 2 per supplement (supporting + challenging), PubMed/Cochrane only, inline citations | Content/Credibility | Medium | Should-have |

**Key themes:** Honest assessment is crown jewel. Close the data loops. Own the adherence story. 21 supplements needs a hierarchy. Genome connection undersold.

---

## DECISION 17: Protocols (`/protocols/`) ✅ LOGGED

**Current state:** API-driven, 6 protocols with adherence/signal data, outcome snapshot (static), vice tracking section, through-line to Pulse. Pipeline nav CSS exists but HTML not rendered.

**Core diagnosis:** No definition of what a protocol IS. No lifecycle connection. Outcome snapshot is static while cards load live data. Vice tracking belongs on Accountability page.

**Approved recommendations:**

| # | Recommendation | Category | Effort | Priority |
|---|---------------|----------|--------|----------|
| 17a | Add narrative intro with protocol definition + promotion/review criteria | Content | Low | Must-have |
| 17b | Add origin/provenance per protocol card — experiment source or literature | Feature/Content | Low | Must-have |
| 17c | Make outcome snapshot dynamic from API | Feature | Medium | Must-have |
| 17d | Render the pipeline nav — shared Practice section component | Feature | Low | Must-have |
| 17e | Define signal states explicitly — Positive/Pending/None legend | Content/UX | Low | Must-have |
| 17f | Add science rationale per protocol — one line on mechanism | Content | Low | Should-have |
| 17g | Add protocol tier/weight — foundation vs measurement vs intervention | Design/Content | Low | Should-have |
| 17h | Move vice tracking to Accountability page | IA | Low | Should-have |
| 17i | Add review cadence and retirement criteria | Content | Low | Should-have |
| 17j | Elevate one pull-quote to page level | Design/Content | Low | Should-have |
| 17k | Add protocol history section — retired/graduated protocols | Feature/Content | Medium | Should-have |
| 17l | Fix breadcrumb to "The Practice > Protocols" | Bug | Low | Must-have |
| 17m | Cross-link to observatory pages per protocol | IA | Low | Should-have |

**Key themes:** Lifecycle definition IS the unique value. Pipeline nav solves section confusion. Origin/provenance closes the loop. Vice tracking doesn't belong here.

---

## DECISION 18: Stack (`/stack/`) ✅ LOGGED

**Current state:** API-driven overview, 4 endpoints, collapsible domain cards, "Go Deeper" reading order section. No narrative intro, no system explanation, no lifecycle visualization.

**Core diagnosis:** An index card catalog that should be a system explanation page. Currently jumps straight to domain cards with no context.

**Approved recommendations:**

| # | Recommendation | Category | Effort | Priority |
|---|---------------|----------|--------|----------|
| 18a | Add narrative intro + system explanation — "I run my health like a lab" | Content | Low | Must-have |
| 18b | Add lifecycle pipeline visualization with live counts | Design/Feature | Medium | Must-have |
| 18c | Reorder: intro → pipeline → domains → reading order | IA | Low | Must-have |
| 18d | Reorder "Go Deeper" links to lifecycle sequence | IA | Low | Must-have |
| 18e | Add domain-level signal indicators (red/yellow/green) | Design/Feature | Medium | Should-have |
| 18f | Add stack evolution timeline | Feature/Content | Medium | Should-have |
| 18g | Add data source integration map | Design | Medium | Should-have |
| 18h | Clarify "Details →" interaction pattern | UX | Low | Should-have |
| 18i | Add credibility/integrity statement | Content | Low | Should-have |
| 18j | Refine hero subtitle — story, not description | Content | Low | Must-have |
| 18k | Render pipeline nav — shared component | Feature | Low | Must-have |
| 18l | Visual hierarchy by data richness per domain | Design | Medium | Nice-to-have |
| 18m | Add "what's new this week" callout | Feature/Content | Medium | Should-have |
| 18n | Fix breadcrumb to "The Practice > The Stack" | Bug | Low | Must-have |

**Key themes:** Section landing page must explain the system. Pipeline visualization is the unique contribution. Temporal dimension missing. "Stack" needs disambiguation.

---

## DECISION 19: Experiments / The Lab (`/experiments/`) ✅ LOGGED

**Current state:** Three-zone page (Mission Control, Library, Record). 52-experiment library with community voting, follow mechanics, evidence tiers, podcast source attribution. H/P/D explainer. Zero experiments formally tracked.

**Data layer:** `list_experiments` returns 0. Library has 52 seeded. Both Mission Control and Record render empty.

**Core diagnosis:** Most feature-rich page in The Practice section. Launches 66% empty. Voting mechanic is strongest engagement feature on the site.

**Approved recommendations:**

| # | Recommendation | Category | Effort | Priority |
|---|---------------|----------|--------|----------|
| 19a | Add narrative intro — "Why am I experimenting on myself?" | Content | Low | Must-have |
| 19b | Start 1-2 experiments before launch | Operational | Low | Must-have |
| 19c | Improve empty state copy — editorial, promise-forward | Content | Low | Must-have |
| 19d | Add lifecycle connection to Protocols | Content/IA | Low | Must-have |
| 19e | Add "If successful, this becomes:" field per experiment | Feature/Content | Low-Med | Must-have |
| 19f | Add "launching next" card in Mission Control for top-voted | Feature/Design | Medium | Should-have |
| 19g | Add curated "Start here" shortlist — 3 recommended experiments | Content/IA | Low | Should-have |
| 19h | Elevate voting social proof — vote + follower counts | Feature/Growth | Low | Should-have |
| 19i | Add launch timeline/roadmap | Content/Feature | Low | Should-have |
| 19j | Strengthen methodology confidence — positive N=1 framing | Content | Low | Should-have |
| 19k | Link source citations to original podcast/paper | Content/Credibility | Medium | Should-have |
| 19l | Distinguish evidence-validated vs genuinely unknown sections | IA/Content | Low | Should-have |
| 19m | Differentiate behavioral vs measurable experiment UI | Design/UX | Low | Should-have |
| 19n | Verify library-to-MCP experiment connection pipeline | Architecture | Medium | Should-have |
| 19o | Render pipeline nav | Feature | Low | Must-have |
| 19p | Fix breadcrumb to "The Practice > Experiments" | Bug | Low | Must-have |
| 19q | Add "Run your own" protocol export for completed experiments | Feature | Low | Should-have |
| 19r | Add "How the library grows" explainer — AI scans journals/podcasts → Board reviews | Content | Low | Must-have |
| 19s | Add "Recently added" badges/section for new experiments | Feature/Design | Low | Should-have |
| 19t | No downvotes — keep upvote-only (GUARDRAIL) | Guardrail | — | Guardrail |
| 19u | Add "Suggest an experiment" form — low friction, Board review queue | Feature/Growth | Medium | Should-have |
| 19v | Add private "Flag for review" option for safety concerns | Feature/Safety | Low | Should-have |
| 19w | Library tiles: inline expand on click — don't navigate away | UX/Feature | Medium | Must-have |
| 19x | Keep detail page as deep-link for sharing/SEO | IA | Low | Should-have |
| 19y | Add "What we'd learn" plain-language benefit to library tiles | Content/UX | Low-Med | Must-have |
| 19z | Add expected outcome with honest magnitude tied to evidence tier | Content | Low-Med | Should-have |
| 19-aa | Show monitored sources list — journals, podcasts, newsletters with URLs | Content/Credibility | Low | Must-have |
| 19-ab | "Suggest a source" form — readers recommend journals/podcasts to monitor | Feature/Growth | Low | Should-have |
| 19-ac | Source provenance on library tiles — when added, which source, clickable link | Content/IA | Low | Must-have |
| 19-ad | Add evidence tier color accent to library tiles | Design | Low | Must-have |
| 19-ae | Add pillar icon as visual anchor on tiles | Design | Low | Must-have |
| 19-af | Add evidence ring mini-visual — reuse Supplements pattern | Design | Low | Should-have |
| 19-ag | Differentiate measurable vs behavioral tiles visually | Design | Low | Should-have |
| 19-ah | Richer visual in expanded state — experiment design diagram | Design | Medium | Nice-to-have |
| 19-ai | "Suggest an experiment" with low-friction form + Board review | Feature/Growth | Medium | Should-have |
| 19-aj | "Community Suggested" badge on approved reader submissions | Feature/Growth | Low | Should-have |

**Key themes:** Page launches 66% empty — start experiments before Day 1. Voting is the strongest engagement mechanic. Living library story (AI scans → Board reviews). No downvotes. Inline expand for browsing. Show the payoff on tiles.

---

## DECISION 20: Challenges / The Arena (`/challenges/`) ✅ LOGGED

**Current state:** Gamified challenge page with amber theming. Hero zone with active challenge + daily check-in. Tile grid (66 challenges), category filters, detail overlay modal, community voting, follow/notify, XP integration, Board recommender quotes.

**Data layer:** 66 challenges seeded in catalog. Zero active/completed in dynamic system.

**Core diagnosis:** Best engagement design on the site. Daily check-in mechanic is genuinely addictive. Launches empty like Experiments. Most accessible entry point to The Practice section.

**Approved recommendations:**

| # | Recommendation | Category | Effort | Priority |
|---|---------------|----------|--------|----------|
| 20a | Add narrative intro — arena energy | Content | Low | Must-have |
| 20b | Start 1 challenge before launch | Operational | Low | Must-have |
| 20c | Elevate Experiments vs Challenges distinction near top of page | Content/IA | Low | Must-have |
| 20d | Add duration and difficulty filters | Feature/UX | Low-Med | Must-have |
| 20e | Add "Board Recommends" curated section above grid | IA/Design | Low | Must-have |
| 20f | Add share mechanic per tile | Growth | Medium | Should-have |
| 20g | Add "I'm doing this too" participation counter | Feature/Growth | Medium | Should-have |
| 20h | Add challenge-to-experiment graduation badge | Feature/IA | Low | Should-have |
| 20i | Add mechanism one-liner to detail modal | Content | Low | Should-have |
| 20j | Visual differentiation for tile states (hot, Board pick, attempted, graduated) | Design | Medium | Should-have |
| 20k | Add expected metric impact to tile/detail | Content/UX | Low | Should-have |
| 20l | Render pipeline nav | Feature | Low | Must-have |
| 20m | Fix breadcrumb to "The Practice > Challenges" | Bug | Low | Must-have |
| 20n | Fix hero eyebrow from "The Science" to "The Practice" | Bug | Low | Must-have |
| 20o | Enrich detail overlay — metric impact, difficulty curve, history | Feature/Content | Medium | Should-have |
| 20p | Post-launch: reader challenge tracking | Feature | High | Post-launch |

**Key themes:** Most accessible entry point in The Practice. Launches empty — start one challenge. Board Recommends prevents social/mental challenges from being buried. Participation counter transforms spectators into participants.

---

## DECISION 21: Chronicle (`/chronicle/`) ✅ LOGGED

**Current state:** Serialized narrative hub. Two-column post list, series intro (The Series + The Reporter), standalone ticker, 4 prequel installments published. Clean editorial bones.

**Core diagnosis:** The writing quality exceeds the page design. The Chronicle is the heart of the site — it deserves premium editorial treatment, not blog-index formatting.

**Approved recommendations:**

| # | Recommendation | Category | Effort | Priority |
|---|---------------|----------|--------|----------|
| 21a | Latest installment as page hero — big title, pull-quote, reading time | Design/IA | Medium | Must-have |
| 21b | Upgrade post list to editorial cards with richer treatment | Design | Medium | Must-have |
| 21c | Add phase/season groupings — "Prequels" → "Season 1" → etc. | IA/Design | Low | Must-have |
| 21d | Reorder for returning visitors — latest hero → archive → series intro | IA | Low | Must-have |
| 21e | Add content/theme badges per installment (Board Interview, Lab Results, etc.) | Content/Design | Low | Should-have |
| 21f | Per-installment OG images | Growth | Medium | Should-have |
| 21g | Add narrative progression indicator / mini-timeline | Design/Feature | Medium | Should-have |
| 21h | Cross-link Chronicle siblings (Weekly Snapshots, Ask the Data, Subscribe) | IA | Low | Must-have |
| 21i | Explain Chronicle vs Weekly Snapshots in one line | Content | Low | Must-have |
| 21j | Fix URL pattern inconsistency (week-03 → week-minus-3) | Architecture | Low | Must-have |
| 21k | Use shared ticker component | Architecture | Low | Should-have |
| 21l | Add "binge read" entry point | UX/Content | Low | Should-have |
| 21m | Post-launch: transformation timeline visualization | Design/Feature | High | Post-launch |
| 21n | Post-launch: thematic tagging | Feature/Content | Medium | Post-launch |
| 21o | Fix breadcrumb to "The Chronicle > Archive" | Bug | Low | Must-have |
| 21p | Elevate title typography — titles ARE the visual | Design | Low | Should-have |
| 21q | Add "Previously on" connection between installments | Content/Design | Low | Nice-to-have |

**Key themes:** The Chronicle is the heart of the site. Writing quality exceeds page design. Latest installment should be the hero. Phase/season groupings essential for scale. Elena Voss conceit is the most original creative decision.

---

## DECISION 22: Subscribe (`/subscribe/`) ✅ LOGGED

**Current state:** Two-column layout. "The Weekly Signal" branding. What-you-get card (4 items). Form with email + 2 optional fields. Double opt-in. Confirmation/unsubscribe handling. Functional.

**Core diagnosis:** Naming confusion (Weekly Signal vs Measured Life vs Wednesday Chronicle). Post-subscribe is a dead end. Form has too many fields. Subscriber gate on Ask the Data is a better conversion point than this page.

**Approved recommendations:**

| # | Recommendation | Category | Effort | Priority |
|---|---------------|----------|--------|----------|
| 22a | Resolve naming: subscription = "The Measured Life" | Content/Brand | Low | Must-have |
| 22b | Reduce form to email only + one optional attribution field | UX/Growth | Low | Must-have |
| 22c | Add social proof — dynamic subscriber count | Growth | Low | Must-have |
| 22d | Build post-subscribe experience — confirmation page + welcome email + survey | Growth/Feature | Medium | Must-have |
| 22e | Clarify content package — ONE email with data + narrative + alerts | Content/UX | Low | Must-have |
| 22f | Add previous installment titles as pitch element | Content/Growth | Low | Must-have |
| 22g | Add email preview mock-up | Design/Growth | Medium | Should-have |
| 22h | Elevate integrity promise to standalone visual element | Design/Content | Low | Should-have |
| 22i | Name the Board advisors specifically | Content | Low | Should-have |
| 22j | Add timing/urgency — "Week 1 ships after April 1" | Content/Growth | Low | Must-have |
| 22k | Cross-link Chronicle siblings | IA | Low | Should-have |
| 22l | Verify "See a sample issue" link — build or remove | Bug/Content | Low-Med | Must-have |
| 22m | Add RSS visibility | Feature | Low | Nice-to-have |
| 22n | Fix breadcrumb to "The Chronicle > Subscribe" | Bug | Low | Must-have |

**Key themes:** Naming confusion is the biggest conversion killer. Post-subscribe experience is a dead end. Form friction is the easiest growth win. The titles are the pitch. Integrity promise is the differentiator.

---

## DECISION 23: Weekly Snapshots (`/weekly/`) ✅ LOGGED

**Current state:** Week-by-week data browser. Week nav, key numbers grid (4 metrics), 7-day heatmap strip, character pillar scores, auto-generated summary, archive grid. Pulls from `/api/snapshot` and `/api/journey_waveform`.

**Critical technical issue:** Week navigation exists but every week shows CURRENT data — API doesn't pass date ranges. Page is architecturally broken for its stated purpose.

**Core diagnosis:** The concept is excellent (walk the journey week by week) but the data layer doesn't exist. Weekly snapshot Lambda is the critical missing piece.

**Approved recommendations:**

| # | Recommendation | Category | Effort | Priority |
|---|---------------|----------|--------|----------|
| 23a | Build weekly snapshot Lambda — runs Sunday, writes frozen snapshot to DynamoDB | Architecture | High | Must-have |
| 23b | Build `/api/weekly_snapshot?week=X` endpoint for historical data | Architecture | Medium | Must-have |
| 23c | Add week-over-week deltas — "287.7 lbs (−1.2)" | Feature | Low | Must-have |
| 23d | Add heatmap legend | UX | Low | Must-have |
| 23e | Cross-link to Chronicle — each week shows link to Elena's installment | IA | Low | Must-have |
| 23f | Use weekly aggregates, not point-in-time values | Content/Feature | Medium | Must-have |
| 23g | Improve summary narrative from database report to Board-voice interpretation | Content/Feature | Medium | Should-have |
| 23h | Add protocol adherence section per week | Feature | Medium | Should-have |
| 23i | Surface sick/rest days in empty weeks | Feature | Low | Should-have |
| 23j | Post-launch: calendar heatmap visualization (GitHub contribution graph) | Design/Feature | High | Post-launch |
| 23k | Fix eyebrow to "The Chronicle" | Bug | Low | Must-have |
| 23l | Fix breadcrumb to "The Chronicle > Weekly Snapshots" | Bug | Low | Must-have |
| 23m | Post-launch: "Compare two weeks" mode | Feature | Medium | Post-launch |
| 23n | Post-launch: shareable weekly card | Growth | Medium | Post-launch |

**Key themes:** Page is architecturally broken — shows current data for all weeks. Weekly snapshot Lambda is the must-have. Week-over-week deltas are the entire point. This is the DATA companion to the Chronicle.

---

## DECISION 24: Ask the Data (`/ask/`) ✅ LOGGED

**Current state:** AI conversational interface. 6 suggestion chips, text input, conversation thread, rate limiting (3 anonymous / 20 subscriber), subscriber gate with email verification, data strip, N=1 disclaimer.

**Core diagnosis:** Most technically ambitious page on the site. The subscriber gate is the best conversion funnel. Everything depends on `/api/ask` working reliably. If it doesn't, ship "Coming soon" instead.

**Approved recommendations:**

| # | Recommendation | Category | Effort | Priority |
|---|---------------|----------|--------|----------|
| 24a | Verify `/api/ask` endpoint works — if not, ship "Coming soon" state | Technical | Varies | **Critical** |
| 24b | Add context sentence — "19 sources, X days, 7 lab draws, 110 SNPs" | Content | Low | Must-have |
| 24c | Expand and categorize suggestion chips — 12-15, organized by domain | UX/Content | Low | Must-have |
| 24d | Upgrade subscriber gate to full value-prop pitch | Growth/Design | Low-Med | Must-have |
| 24e | Increase anonymous limit from 3 to 5 | UX/Growth | Low | Should-have |
| 24f | Add medical advice guardrails to AI prompt | Safety/Content | Low | Must-have |
| 24g | Expand data strip to show full data depth | Content/Design | Low | Should-have |
| 24h | Add "Ask Elena" section below conversation | Feature | Medium | Should-have |
| 24i | Track submitted questions as content intelligence | Architecture | Medium | Post-launch |
| 24j | Richer AI response formatting — bold numbers, deltas, sources footer | Design/Feature | Medium | Should-have |
| 24k | Post-launch: dynamic suggestion chips (most asked this week) | Feature/Growth | Medium | Post-launch |
| 24l | Cross-link to Data Explorer and Chronicle | IA | Low | Should-have |
| 24m | Fix breadcrumb | Bug | Low | Must-have |
| 24n | Consider nav placement — Chronicle vs Evidence vs Platform | IA | Low | Should-have |

**Key themes:** Most technically ambitious page. Subscriber gate is best conversion funnel. Answer quality is everything. Medical advice guardrails non-negotiable. Two modes of inquiry (AI + Elena) captures the site's philosophy.

---

## PART 3 SUMMARY STATISTICS

| Metric | Count |
|--------|-------|
| Decisions logged | 9 (Decisions 16–24) |
| Meta-discussions | 2 (Practice Hierarchy, Engagement Model) |
| Total recommendations | ~170 (Part 3 only) |
| Guardrails | 4 (16q no considering section, 19t no downvotes, 22-S1 one subscription, 22-S4 no reader streaks) |
| Critical items | 1 (24a: verify /api/ask) |
| Operational items | 2 (19b: start experiments, 20b: start challenge) |
| Architecture items | 3 (16f API-driven supplements, 23a weekly snapshot Lambda, 23b weekly snapshot API) |
| Cross-cutting components | 1 (shared pipeline nav across all Practice pages) |

### Shared Components Identified
1. **Pipeline nav** — renders on all 6 Practice pages: Stack · Protocols · Supplements · Experiments · Challenges · Discoveries
2. **Shared ticker** — used on homepage and Chronicle, should be single component
3. **N=1 disclaimer** — identical text on Protocols, Supplements, Experiments, Challenges — shared component

---

_Part 3 completed. Part 4 covers The Platform section (7 pages), re-reviews (Home, Story, About), and final prioritization/sequencing._
