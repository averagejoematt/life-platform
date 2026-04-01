# Content Audit — Placeholder vs Real vs API-Driven
**Date:** 2026-03-31 (pre-launch audit)
**Purpose:** Identify AI-generated placeholder text that needs Matthew's real input or API replacement before/after launch.

---

## How to Use This File

- **[PLACEHOLDER]** = AI-generated filler text. Needs Matthew to rewrite in his own voice, or remove.
- **[API-PENDING]** = Should be populated from live data after April 1. I've already added "coming soon" states where possible.
- **[MATTHEW-VERIFY]** = Plausibly real but may have been Claude-embellished. Matthew to confirm or rewrite.
- **[REAL]** = Confirmed authentic Matthew input. No action needed.
- **[FABRICATED]** = Invented narrative presented as real events. Must be removed or replaced.

---

## CRITICAL — Remove or Replace Before Launch

### Chronicle Posts (FABRICATED content presented as real weekly dispatches)

| File | Title | Issue |
|------|-------|-------|
| `site/chronicle/posts/week-02/index.html` | "The Empty Journal" | **FABRICATED** — 3,000-word Elena Voss narrative with invented dialogue ("It's not avoidance," Matthew says), fabricated emotional scenes. Mixes real facts (mother's death, weight history) with manufactured narrative. |
| `site/chronicle/posts/week-03/index.html` | "The DoorDash Chronicle" | **FABRICATED** — Invented story about Matthew getting sick, specific DoorDash orders (acai bowl, Thai, calzone) that never happened. Entirely pre-written by Claude. |
| `site/chronicle/posts/week-04/index.html` | (broken) | Circular redirect — page doesn't work. Remove or fix. |
| `site/chronicle/posts/week-01/index.html` | (redirect) | Redirects to /chronicle/ with "no longer available" message. Clean up. |
| `site/chronicle/sample/index.html` | Sample email | Hardcoded fake Week 1 numbers (286.1 lbs, 58 HRV, 72% recovery), fake board commentary from "Dr. Sarah Chen" and "Dr. Peter Attia". |
| `site/chronicle/archive/index.html` | Archive list | Hardcoded post titles/descriptions for weeks 00-04. Should be driven from posts.json. |

**Recommendation:** Delete week-01 through week-04 posts. Keep week-00 ("Before the Numbers") as the prologue — but Matthew should verify it. The real chronicle Lambda will generate actual weekly posts starting Week 1 (April 7).

### Chronicle Week-00 — "Before the Numbers" Prologue

`site/chronicle/posts/week-00/index.html`

**[MATTHEW-VERIFY]** — 3,000-word Elena Voss prologue. Contains real facts (age 37, weight 302, goal 185, girlfriend Brittany, board members) but written entirely by Claude as narrative journalism. It sets the scene for the experiment.

**Decision needed:** Keep as the official prologue, or rewrite? It's well-written and factually accurate, but Matthew didn't write it.

---

## PAGES WITH PLACEHOLDER PROSE — Matthew to Rewrite

### site/kitchen/index.html
**[PLACEHOLDER]** — Entire page is Claude-generated marketing copy:
- "CGM-scored meals," "Macro-optimized," "Built from your patterns"
- "Most meal plans are built from population averages. The Kitchen is built from your bloodstream."
- 5-step "How It Works" flow

**Recommendation:** Replace with simple "Coming Soon" state, or remove page from nav until real content exists.

### site/elena/index.html
**[MATTHEW-VERIFY]** — The three editorial rules and operational description of Elena:
- "Show the data honestly. If the numbers are bad, they're bad."
- "Ask the questions Matthew would avoid asking himself."
- "Never cheerleading."
- "Each week, she receives the full data export..."

**Decision needed:** Are these your actual editorial philosophy for Elena, or did Claude generate these as reasonable-sounding guidelines?

### site/character/index.html
**[PLACEHOLDER]** text to verify:
- "This isn't a weight tracker. It's an RPG for real life."
- "The game metaphor isn't a gimmick. It's the only framework that made health feel like something I was building, not something I was failing at."
- Tier descriptions (Foundation, Momentum, Discipline, Mastery)

**[REAL]** — The scoring architecture, pillar percentages, XP mechanics, and cross-pillar effects are confirmed real system design.

### site/habits/index.html
**[PLACEHOLDER]** text to verify:
- "Every protocol, every data point, every recovery metric traces back to whether these habits happened."
- "Not 65 checkboxes — a tiered behavioral architecture with purpose."
- Habit timing rationales (cortisol peak, blue light blocking)

**[REAL]** — The actual 7 T0 habits, 15 T1 habits, and tier activation thresholds are real system design.

### site/challenges/index.html
**[PLACEHOLDER]** text:
- "What am I daring myself to do? Challenges are short-term provocations..."
- "Challenges can graduate into experiments — if a 7-day step challenge reveals that 10,000 steps correlates with better sleep..."
- "Where do challenges come from? Five sources: journal mining, data signals, hypothesis graduates, science scans, and board recommendations."

### site/experiments/index.html
**[PLACEHOLDER]** text:
- "52 experiments across 7 pillars. Vote on what I test next."
- "AI monitors journals and podcasts for testable claims."

**[REAL]** — The methodology (Hypothesis, Protocol, Results, Graduation) and sourced monitoring list (PubMed, Huberman, Examine.com, etc.) are real.

### site/intelligence/index.html
**[PLACEHOLDER]** text:
- "14 systems running daily. This is what the AI actually does."
- "This platform isn't just data collection — it's an AI system that reasons about the data every morning."
- Sample Daily Brief dated March 25, 2026 with specific numbers

**[REAL]** — The 14 intelligence systems architecture, daily brief structure, and data inputs list are real system design.

### site/benchmarks/index.html
**[PLACEHOLDER]** framing text:
- "What does 'good' actually look like — according to the research?"
- "Before You Look at Anyone Else's Numbers — Where Do You Stand?"

**[REAL]** — Matthew's honest reflection: "The benchmark that scares me most is VO2 max... Where I'm failing? Social connection. I have the data, the discipline, the systems — but I've let friendships thin out while building all of this."

### site/supplements/index.html
**[PLACEHOLDER]** text:
- "Every supplement rated by evidence strength, justified by purpose, and tracked against real data."
- "No affiliate links. No sponsorships. No brand promotions. Just the data."

**[REAL]** — The actual supplement stacks (AM, Pre-Training, PM), evidence rating system, genome-informed framework, and discontinued supplements reasoning (AG1 rationale).

### site/discoveries/index.html
**[PLACEHOLDER]** text:
- "What I've discovered" section heading
- "AI-surfaced observations from weekly chronicles, coaching insights, and nutrition patterns."

Mostly API-driven content — will auto-populate.

### site/protocols/index.html
**[PLACEHOLDER]** text:
- "A protocol is what I'm operating now. It earned its place through evidence..."
- "Protocols are what I do consistently — the stable system."

### site/methodology/index.html
**[PLACEHOLDER]** framing:
- "One subject. Full data transparency. A reproducible framework for N=1 science..."

**[REAL]** — The methodology details (90-day rolling window, 23 metric pairs, Benjamini-Hochberg FDR, |r| > 0.4 threshold) and honest limitations list are real.

### site/cost/index.html
**[PLACEHOLDER]** opener:
- "I publish the bill because the enterprise health world obscures costs."

**[REAL]** — All cost architecture decisions, service-level breakdowns, and specific dollar figures are Matthew's real system.

---

## OBSERVATORY PAGES — Mostly Fine

These pages are primarily API-driven with editorial intros. The editorial text needs Matthew verification:

### site/mind/index.html
**[MATTHEW-VERIFY]:**
- "For most of my adult life, the relapses made sense..." (personal narrative)
- Vice streak explanations and reasoning
- "I'm not trying to return to who I was..."
- Future roadmap items (Month 1-2 through Month 4-6) — aspirational features

**[REAL]** — Pull-quote about stress tracking, identity framing

### site/nutrition/index.html
**[REAL]:**
- "Food and I have had a complicated relationship since my twenties..."
- "I've lost 100 lbs before without tracking a single calorie..."
- Protocol items (180g protein, 500-750 cal deficit)

**[PLACEHOLDER]** — Elena Voss quote: "He logs the bad days too..."

### site/training/index.html
**[REAL]:**
- "When I'm in it, I'm all in — 5am sessions, compound lifts, rucking mountains..."
- "Most programs optimize for aesthetics at 30. This one optimizes for carrying groceries..."

### site/physical/index.html
**[REAL]:** All content confirmed authentic.

### site/sleep/index.html
**[REAL]:**
- "Sleep was never something I thought I needed to fix. Matthew Walker's work made me pay closer attention..."
- Hypotheses #01-03 labeled "Under test" (honest about status)

**[PLACEHOLDER]** — "Bed temperature at 68F is the personal sweet spot..." (claim presented as verified finding)

### site/glucose/index.html
**[REAL]:**
- Health anxiety narrative: "Before the CGM, I carried a low-grade dread..."
- "The CGM didn't cure the anxiety. But it replaced speculation with observation..."

**[PLACEHOLDER]** — Pull-quotes labeled "Pending data" (correctly flagged)

---

## PAGES THAT ARE FINE (No Action Needed)

| Page | Status |
|------|--------|
| `site/story/index.html` | All 5 chapters confirmed Matthew's real writing |
| `site/about/index.html` | Mostly real, platform stats API-driven |
| `site/first-person/index.html` | "Coming Soon" — intentionally empty for Matthew's future writing |
| `site/community/index.html` | Real community vision |
| `site/builders/index.html` | All architecture decisions, lessons learned are real |
| `site/platform/index.html` | Real system description |
| `site/biology/index.html` | API-driven genome data |
| `site/labs/index.html` | API-driven biomarker data |
| `site/live/index.html` | API-driven daily dashboard |
| `site/explorer/index.html` | Already fixed — "Coming Soon" state |
| `site/field-notes/index.html` | Already fixed — "Coming Soon" state |
| `site/ledger/index.html` | API-driven, empty state handled |
| `site/privacy/index.html` | Legal/policy text |
| `site/status/index.html` | API-driven system status |
| `site/subscribe/index.html` | Functional form |
| `site/tools/index.html` | Interactive calculators |
| `site/progress/index.html` | API-driven |
| `site/data/index.html` | API-driven |
| `site/week/index.html` | API-driven |
| `site/weekly/index.html` | API-driven |
| `site/recap/index.html` | API-driven |
| `site/results/index.html` | API-driven |

---

## PRIORITY ORDER

1. **Delete/replace fabricated chronicle posts** (week-01 through week-04) — these present invented events as real
2. **Fix chronicle sample email** — remove hardcoded fake data
3. **Fix kitchen page** — replace with "coming soon" or remove from nav
4. **Matthew reviews [MATTHEW-VERIFY] items** — confirm or rewrite in his voice
5. **Matthew rewrites [PLACEHOLDER] editorial intros** — low priority, can happen post-launch
