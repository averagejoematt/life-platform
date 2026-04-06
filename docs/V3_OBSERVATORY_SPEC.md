# V3 Observatory Design & Technical Specification

**Version:** 1.0
**Date:** 2026-04-05
**Author:** Product Board + Personal Board + Technical Board consensus
**Status:** Approved — ready for implementation
**Ticket:** PB-09

---

## Executive Summary

The observatory pages (Sleep, Glucose, Nutrition, Training, Physical, Mind) are redesigned from editorial-first "magazine" layouts to **coach-led dashboards** that serve returning weekly readers as the primary audience. The Habits page receives a lighter restructuring. The AI expert prompts are expanded to produce richer, more varied analyses that anchor each page's returning-reader value.

**Decision:** Approach B ("Coach-Led") for Sleep, Glucose, Nutrition, Training, Physical. Approach C ("Progressive Reveal") for Mind/Inner Life. V3-lite for Habits.

**Boards voting:** Product Board 5-2-1, Personal Board 12-0. Combined 17 votes for B. Unanimous Conti Amendment for Mind page exception.

---

## 1. V3 Page Anatomy — Standard Observatory (Sleep, Glucose, Nutrition, Training, Physical)

Every standard observatory page follows this exact section order. **No exceptions.** The returning reader builds spatial memory: "Coach is always section 2. Trends are always section 3."

### Section 1: Status Bar
**Purpose:** The numbers that matter, with directional context.
**Position:** Immediately below nav, no editorial above it.
**Layout:** 4-column grid on desktop, 2x2 grid on mobile.

Each metric cell contains:
- Metric label (11px uppercase, muted color)
- Current value (28px, prominent)
- Directional delta (12px, color-coded: green=improving, amber=watch, red=attention)
- Context line (12px muted — e.g., "5-night avg: 74" or "Target: >20%")

**Metrics per page:**

| Page | Metric 1 | Metric 2 | Metric 3 | Metric 4 |
|------|----------|----------|----------|----------|
| Sleep | Last night (hrs) | Sleep score | Deep sleep % | Recovery % |
| Glucose | Time in range % | Avg glucose | Std deviation | Optimal range % |
| Nutrition | Daily avg cal | Protein avg (g) | Protein hit rate % | Days logged |
| Training | Zone 2 min/wk | Sessions (30d) | Avg strain | Daily steps avg |
| Physical | Current weight | Total lost | Weekly rate | Body fat % |

**Delta calculations:** Compare current 7-day period vs prior 7-day period. Show as "+2.8h" or "-0.2h" with color coding.

**Status indicators:** Top-right corner shows "Updated Xh ago" with a live/stale dot (green if <24h, amber if 24-48h, red if >48h).

### Section 2: Coach Analysis
**Purpose:** The reason a reader returns every week. Fresh interpretation of this week's data.
**Position:** Immediately below status bar. This is the most important content on the page.

**Layout:**
- Coach avatar (32px circle with initials) + name + title + generation date
- 2-3 paragraphs of prose analysis (~180-250 words)
- **"This week's action" callout box** — visually distinct (left blue border, dark background), containing the KEY RECOMMENDATION extracted from the AI analysis
- Source attribution line (12px muted — "Based on X data sources")

**Coach assignments per page:**

| Page | Coach | Initials |
|------|-------|----------|
| Sleep | Dr. Lisa Park | LP |
| Glucose | Dr. Rhonda Patrick | RP |
| Nutrition | Dr. Layne Webb (display as "Dr. Marcus Webb") | MW |
| Training | Dr. Sarah Chen | SC |
| Physical | Dr. Victor Reyes | VR |

**Elena Voss quote:** Rendered as a compact blockquote with left border below the coach analysis. One line from the ELENA QUOTE field. Links to the Chronicle.

**Subscribe CTA:** Place a compact subscribe prompt immediately after the coach analysis — "Want this analysis weekly? Subscribe →". This is the peak-engagement moment for conversion.

**Data source:** `/api/ai_analysis?expert={page_key}` — returns `analysis`, `key_recommendation`, `elena_quote`, `generated_at`.

### Section 3: Trends
**Purpose:** The visual progression story.
**Position:** Below coach analysis.

**Layout:**
- Time-range toggle row (7d / 30d / 90d buttons, right-aligned)
- Side-by-side chart pair on desktop (stacked on mobile)
- Chart 1: The page's primary trend (architecture for sleep, calorie trend for nutrition, etc.)
- Chart 2: The page's secondary signal (score trend, protein trend, etc.)
- Chart legends below each chart

**Charts per page:**

| Page | Chart 1 | Chart 2 |
|------|---------|---------| 
| Sleep | Architecture stacked area (deep/REM/light) | Score trend (Eight Sleep + Whoop dual line) |
| Glucose | 30-day glucose trend line | Time-in-range bar chart |
| Nutrition | Calorie + protein trend (dual axis) | Protein adherence bar |
| Training | Daily exercise minutes (bar) | 12-week training volume (stacked) |
| Physical | Weight trajectory (daily + 7d avg + goal) | Weight vs calorie overlay |

### Section 4: This Week's Detail
**Purpose:** Deeper data for readers who want more than the headline numbers.
**Position:** Below trends.

**Layout:** 3-column card grid on desktop, stacked on mobile. Each card has:
- Label (11px uppercase)
- Value (18px, color-coded if applicable)
- Context line (12px muted)

**Content varies by page** — this section contains the domain-specific breakdowns:
- Sleep: bedtime consistency (weekday/weekend/social jetlag), efficiency, HRV
- Glucose: optimal range %, meal response table (top 5), nocturnal patterns
- Nutrition: per-meal protein distribution, top meals list, weekday vs weekend
- Training: activity breakdown, walking/steps, this week's movement grid
- Physical: DEXA composition summary, tape measurements summary, blood pressure

### Section 5: Cross-Domain
**Purpose:** Connections to other observatories. What makes this platform different from single-tracker apps.
**Position:** Below this week's detail.

**Layout:** 2-3 compact link cards showing cross-domain relationships:
- Title (e.g., "Sleep → Recovery")
- One-sentence finding
- Link arrow to the relevant observatory

### Section 6: Depth (Collapsed by Default)
**Purpose:** First-time visitor content, methodology, hypotheses, editorial.
**Position:** Bottom of page, above footer.

**Layout:** Collapsible sections using `<details>` elements with specific labels (per Dr. Patrick's amendment). Each section is a card-style container.

**Sections (labeled specifically, not generically):**

| Label | Content |
|-------|---------|
| "About this observatory" | Hero editorial text, Matthew's reflections, the story behind this page |
| "Hypotheses under test (N)" | All hypothesis cards with status badges |
| "Genomic context" | Genome-related findings (where applicable — Glucose, Nutrition) |
| "Cross-domain findings" | Detailed cross-domain analysis prose |
| "Measurement protocol" | Device descriptions, methodology notes, N=1 disclaimers |

**What explicitly moves OUT of the main scroll:**
- Hero editorial copy (e.g., "The thing I thought I was good at") → "About this observatory"
- Matthew's pull-quote reflections → "About this observatory"
- Elena Voss chronicle excerpts (long ones) → Chronicle link only; one short quote stays in Section 2
- Inline educational definitions (what is HRV, what is TIR) → Tooltip or "Measurement protocol"
- Numbered protocol lists (e.g., "01: Target 8 hours...") → "Measurement protocol"

---

## 2. V3 Page Anatomy — Mind/Inner Life (Approach C Exception)

The Mind page preserves one layer of narrative context per the Conti Amendment, because on this page the editorial content IS the therapeutic work made visible.

### Differences from Standard Observatory:
1. **Section 0 (above Status Bar):** Retain the page headline ("The pillar I avoided building") and the first two paragraphs of Matthew's reflection. This is NOT collapsed. It is part of the page identity.
2. **Section 2 (Coach Analysis):** Dr. Conti's analysis sits in a **two-column layout** with "This week" stats on the right (journal entries, mood readings, vice streak count, resist rate).
3. **Section 4 (This Week's Detail):** Includes the vice streak portfolio, connection depth cards, and mood valence — these are the Mind page's equivalent of "metrics."
4. **Section 5:** The "five promises" section stays visible (not collapsed) — it's Matthew's public therapeutic commitment.
5. **Depth section** includes: journal intelligence, cognitive pattern frameworks, the "what this page will become" roadmap.

---

## 3. V3-Lite: Habits Page

The Habits page gets a lighter restructuring:

### Changes:
1. **Move editorial intro** ("The Operating System" + two paragraphs) into a collapsible "About this system" section
2. **Promote status bar to top:** T0 streak (days), avg completion %, days tracked, active habits count
3. **T0 habits section stays visible** — these are the non-negotiables, always shown
4. **Discipline Gates stays visible** — vice streaks are high-engagement
5. **T1 and T2 tiers collapse by default** — expandable on click
6. **Daily Pipeline diagram:** Stays but moves below T0 habits (currently above)
7. **Habit Intelligence section stays** — heatmap and patterns are returning-reader content

### No Changes:
- The page's functional structure (tiers, groups, streaks) is correct
- Just reorganize: status first, editorial collapsed, tiers progressively disclosed

---

## 4. Minor Adjustments: Labs Page

1. **Move Dr. Okafor's analysis to position 2** (immediately after the biomarker summary bar)
2. **Fix AI interpretation bug:** The Labs expert gathers data with `_query_source("labs", "2019-01-01", today)` spanning all-time, but the prompt says "experiment days 1-N." The labs prompt needs a special override:

```python
# In build_prompt(), add labs-specific context:
if expert_key == "labs":
    context_override = f"""
IMPORTANT: Lab data spans Matthew's full history, not just the current experiment.
The data shows {data.get('total_draws', 0)} total blood draws, with the most recent on {data.get('draw_date', 'unknown')}.
Do NOT describe this as "draws during the experiment" — these are periodic lab draws over time.
"""
```

---

## 5. AI Expert Prompt Enhancements

With the coach analysis promoted to position 2 (the most visible content on the page), the prompts need to be richer, more varied, and more engaging for returning readers.

### 5.1 Enhanced Prompt Template

Replace the current `build_prompt()` with a versioned, richer prompt:

```python
def build_prompt_v3(expert_key, data, days_in_experiment=None, week_number=None):
    p = EXPERT_PERSONAS[expert_key]
    prior_summary = data.pop("_prior_analysis_summary", "")
    prior_recommendation = data.pop("_prior_recommendation", "")
    data_json = json.dumps(data, indent=2, default=str)

    week_num = week_number or max(1, (days_in_experiment or 1) // 7)

    # Rotating analytical lens — prevents repetitive framing
    lenses = [
        "Focus on the most surprising or counterintuitive finding in this data.",
        "Focus on what changed since last week and whether the direction matters.",
        "Focus on what the data does NOT show — the gaps, the missing signal, the dog that didn't bark.",
        "Focus on one specific number and explain why it matters more than it appears.",
        "Focus on the interaction between two metrics that tells a story neither tells alone.",
        "Focus on whether Matthew's current trajectory is sustainable for 3 more months.",
        "Focus on what a clinician would flag if this were a patient chart review.",
    ]
    lens = lenses[(week_num - 1) % len(lenses)]

    prior_block = ""
    if prior_summary:
        prior_block = f"""
Your PREVIOUS analysis said: "{prior_summary[:300]}..."
Your PREVIOUS recommendation was: "{prior_recommendation[:200]}..."

CRITICAL: Do NOT repeat the same observation, angle, or recommendation. Find a genuinely
different insight. If you previously discussed deep sleep percentage, discuss something else
this week — consistency, efficiency, HRV trend, or a cross-domain connection. The reader
has already read your last analysis and will notice repetition immediately.
"""

    labs_context = ""
    if expert_key == "labs":
        labs_context = f"""
IMPORTANT: Lab data spans Matthew's full history, not just the current experiment.
The data shows {data.get('total_draws', 0)} total blood draws, with the most recent
on {data.get('draw_date', 'unknown')}. Do NOT describe this as "draws during the
experiment" — these are periodic lab draws over time.
"""

    return f"""You are {p['name']}, {p['title']}.

Your communication style: {p['style']}.
Your analytical focus: {p['focus']}.

You are writing your weekly analysis for Matthew's public health experiment (averagejoematt.com).
This is Week {week_num} of the experiment (started {EXPERIMENT_START}, now day {days_in_experiment}).
Your analysis is the CENTERPIECE of the observatory page — it appears at position 2,
immediately after the key metrics. Returning readers come back specifically to read
what you have to say this week. This is a weekly appointment, not a generic report.

ANALYTICAL LENS FOR THIS WEEK: {lens}
{labs_context}

Here is Matthew's current data:
{data_json}

{prior_block}

Write a 2-3 paragraph analysis (200-300 words). Requirements:

STRUCTURE:
- Paragraph 1: Open with ONE specific, concrete observation. Lead with the number
  that caught your attention. Use "What strikes me most..." or "The figure I keep
  returning to..." or "The pattern worth naming..." — vary your opening each week.
- Paragraph 2: Interpret the pattern. What does it mean clinically/practically?
  Connect to another domain if relevant (sleep affects glucose, training affects
  recovery, etc.). Use your expertise to say something a dashboard cannot.
- Paragraph 3: One specific, actionable suggestion for the coming week. Be concrete
  enough that Matthew can do it tomorrow. Not "sleep more" but "try anchoring sleep
  onset to within a 30-minute window each night."

VOICE:
- First person as yourself. You are a real expert having a weekly conversation.
- Reference specific numbers naturally — don't list them, weave them into insight.
- Be honest. If the data is concerning, say so. If it's encouraging, explain why
  without being sycophantic. If it's too early to draw conclusions, say that.
- Write as if Matthew and 500 subscribers are reading this on Wednesday morning
  with their coffee. Be worth their time.
- Do NOT use bullet points, headers, or formatting. Flowing prose only.
- Vary sentence length. Mix short declarative sentences with longer analytical ones.

FRESHNESS REQUIREMENTS:
- Never open with "Looking at the data..." or "This week's data shows..." — these
  are the equivalent of "Dear Sir/Madam" in a letter. Be specific immediately.
- Each weekly analysis should feel like a different chapter, not a form letter.
- If you find yourself writing a sentence that could appear in any week's analysis,
  delete it and write something specific to THIS week.

After your analysis, on separate lines write exactly:
KEY RECOMMENDATION: [One specific behavioral action for this week. 1-2 sentences max. Concrete enough to act on tomorrow.]
ELENA QUOTE: [One sentence in Elena Voss's voice — third person, clinical precision with literary warmth. She notices patterns, not outcomes. Example: "Five nights of data and his body is already telling a quieter story than the hours suggest." Never aspirational. Just noticing.]
{"JOURNALING PROMPT: [A single reflective question for Matthew — something he can sit with before writing. Make it specific to what the data revealed this week.]" if expert_key == "mind" else ""}

Write only the analysis — no preamble, no "Here is my analysis:", just paragraphs followed by the tagged lines."""
```

### 5.2 Enhanced Data Gathering

Several experts currently receive thin data. Enrich the data payloads:

**Sleep expert — add:**
```python
# Add sleep onset times for consistency analysis
sleep_starts = [w.get("sleep_start") for w in whoop_items if w.get("sleep_start")]
# Add Eight Sleep bed temperature data
bed_temps = [float(e.get("bed_temp_f", 0)) for e in eight_items if e.get("bed_temp_f")]
# Add REM percentage
rem_pcts = [float(e.get("rem_pct", 0)) for e in eight_items if e.get("rem_pct")]

data.update({
    "avg_rem_pct": avg(rem_pcts),
    "avg_bed_temp_f": avg(bed_temps),
    "sleep_onset_times": sleep_starts[-7:],  # Last 7 nights
    "sleep_onset_variability_min": _calculate_onset_variability(sleep_starts),
})
```

**Training expert — add:**
```python
# Add recovery scores for load management context
whoop_items = _query_source("whoop", d30, today)
recovery_vals = [float(w["recovery_score"]) for w in whoop_items if w.get("recovery_score")]
# Add modality breakdown
modalities = {}
for a in activities:
    t = a.get("type", "unknown")
    modalities[t] = modalities.get(t, 0) + 1

data.update({
    "avg_recovery": avg(recovery_vals),
    "rest_days": days_in_experiment - len(set(a.get("sk", "")[:15] for a in activities)),
    "modality_breakdown": modalities,
})
```

**Nutrition expert — add:**
```python
# Add meal timing data
meal_times = [i.get("meal_time") for i in items if i.get("meal_time")]
# Add fiber data
fiber_vals = [float(i.get("fiber_g", 0)) for i in items if i.get("fiber_g")]

data.update({
    "avg_fiber_g": avg(fiber_vals),
    "eating_window_hours": _calculate_eating_window(items),
    "zero_calorie_days": sum(1 for i in items if float(i.get("calories", 0)) == 0),
    "logged_but_empty_days": sum(1 for i in items
        if i.get("calories") is not None and float(i.get("calories", 0)) == 0),
})
```

### 5.3 Prior Analysis Tracking Enhancement

Currently only stores the first 300 chars of the prior analysis. Enhance to also store the prior recommendation:

```python
# In generate_and_cache(), before building prompt:
if prior:
    data["_prior_analysis_summary"] = str(prior.get("analysis", ""))[:300]
    data["_prior_recommendation"] = str(prior.get("key_recommendation", ""))[:200]
```

### 5.4 Week Number Calculation

Add week number to the prompt for rotating lens and store in DynamoDB for tracking:

```python
week_number = max(1, days_in_experiment // 7 + 1)
prompt = build_prompt_v3(expert_key, data, days_in_experiment, week_number)

# In the DynamoDB item write:
item["week_number"] = week_number
```

### 5.5 Increase max_tokens

```python
AI_MAX_TOKENS = 1200  # Was 1000 — V3 prompts produce ~300 words + tagged lines
```

---

## 6. Shared Observatory Template Architecture

### 6.1 Template Strategy

Given the current architecture (static HTML files in S3, no server-side templating), the pragmatic approach is:

1. Create a shared `observatory-v3.js` module in `site/assets/js/` that renders all V3 sections
2. Each observatory page's HTML becomes a thin shell that:
   - Includes shared CSS via `observatory-v3.css`
   - Includes the shared JS module
   - Defines a page config object
   - Calls named functions from the module

```javascript
// site/assets/js/observatory-v3.js — export named functions (per Elena Reyes, Tech Board)
function renderStatusBar(container, metrics, apiEndpoints) { ... }
function renderCoachAnalysis(container, expertKey, coachMeta) { ... }
function renderTrends(container, chartConfigs) { ... }
function renderWeekDetail(container, detailCards) { ... }
function renderCrossDomain(container, links) { ... }
function renderDepth(container, sections) { ... }
```

### 6.2 CSS Architecture

Create `site/assets/css/observatory-v3.css` with the shared design system:

```
.obs-status-grid        — 4-column metric grid
.obs-status-cell        — individual metric cell
.obs-delta-up           — green delta indicator
.obs-delta-down         — red delta indicator
.obs-delta-flat         — amber delta indicator
.obs-coach-card         — coach analysis container
.obs-coach-action       — "this week's action" callout (left blue border)
.obs-coach-avatar       — circular avatar with initials
.obs-coach-meta         — name + title + date line
.obs-elena-quote        — compact blockquote with left border
.obs-trend-row          — side-by-side chart container
.obs-time-toggle        — 7d/30d/90d button group
.obs-detail-grid        — 3-column detail cards
.obs-detail-card        — individual detail card
.obs-cross-link         — cross-domain link card
.obs-depth-section      — collapsible <details> styling
.obs-depth-grid         — 2x2 grid for collapsed sections (desktop)
.obs-subscribe-inline   — compact subscribe CTA after coach analysis
```

Mobile breakpoint at 768px: grids collapse to single column, charts stack vertically.

### 6.3 Page-Specific Configuration

Each observatory HTML file defines its config:

```javascript
// sleep/index.html
const SLEEP_CONFIG = {
  expertKey: 'sleep',
  pageTitle: 'Sleep Observatory',
  coach: { name: 'Dr. Lisa Park', initials: 'LP', title: 'Sleep & circadian specialist' },
  metrics: [
    { key: 'sleep_duration', label: 'Last night', unit: 'hrs', source: 'whoop' },
    { key: 'sleep_score', label: 'Sleep score', unit: '', source: 'eightsleep' },
    { key: 'deep_pct', label: 'Deep sleep', unit: '%', source: 'eightsleep', target: 20 },
    { key: 'recovery_score', label: 'Recovery', unit: '%', source: 'whoop', threshold: 50 },
  ],
  charts: {
    primary: { type: 'stacked-area', datasets: ['deep', 'rem', 'light'], label: 'Architecture' },
    secondary: { type: 'dual-line', datasets: ['eightsleep_score', 'whoop_quality'], label: 'Score trend' },
  },
  detailCards: [
    { label: 'Weekday bed', key: 'weekday_bedtime' },
    { label: 'Weekend bed', key: 'weekend_bedtime' },
    { label: 'Social jetlag', key: 'social_jetlag' },
  ],
  crossDomain: [
    { title: 'Sleep → Recovery', finding: 'Sleep score above 85 predicts recovery above 70%', link: '/training/' },
    { title: 'Sleep → Glucose', finding: 'Poor sleep elevates next-morning fasting glucose', link: '/glucose/' },
  ],
  depthSections: [
    { label: 'About this observatory', id: 'about' },
    { label: 'Hypotheses under test', id: 'hypotheses' },
    { label: 'Cross-domain findings', id: 'cross-domain-detail' },
    { label: 'Measurement protocol', id: 'protocol' },
  ],
};
```

---

## 7. API Changes Required

### 7.1 Observatory Status Endpoint — DEFERRED

Per Viktor (Tech Board): Build V3 with existing API endpoints first. Each page continues to make its individual API calls. Consolidation into a single `/api/observatory_status` endpoint is a follow-up optimization if performance warrants it.

### 7.2 Enhanced `/api/ai_analysis` Response

Add `week_number` and `days_in_experiment` to the response. In `site_api_lambda.py`:

```python
if ai_item.get("week_number"):
    resp_data["week_number"] = int(ai_item["week_number"])
if ai_item.get("days_in_experiment"):
    resp_data["days_in_experiment"] = int(ai_item.get("days_in_experiment", 0))
```

---

## 8. Implementation Plan

### Phase 1: Foundation (Estimated: 1 session)
1. Create `site/assets/js/observatory-v3.js` shared module
2. Create `site/assets/css/observatory-v3.css` shared stylesheet
3. Update `ai_expert_analyzer_lambda.py`:
   - Replace `build_prompt()` with `build_prompt_v3()`
   - Add enhanced data gathering for sleep, training, nutrition experts
   - Add labs-specific context override
   - Increase `max_tokens` to 1200
   - Store `week_number` in DynamoDB item
   - Store `prior_recommendation` for anti-repetition
4. Update `site_api_lambda.py`: Add `week_number` to ai_analysis response
5. Deploy Lambda updates
6. Manually invoke AI analyzer for all 8 experts to generate V3 analyses

### Phase 2: Observatory Pages (Estimated: 2-3 sessions)
Rebuild each page in order of data richness:
1. **Sleep** — richest data, best test case for the V3 pattern
2. **Physical** — shortest page, quickest to convert
3. **Training** — moderate complexity
4. **Nutrition** — complex detail section (meal tables, protein distribution)
5. **Glucose** — meal response table needs careful treatment
6. **Mind** — Approach C variant, requires custom handling

For each page:
- Preserve all existing `<script>` blocks that fetch and render charts
- Replace HTML structure with V3 template sections
- Move editorial content to collapsible depth sections
- Test that all API calls still resolve and charts render
- Verify mobile responsive behavior at 390px

### Phase 3: Habits + Labs (Estimated: 1 session)
1. Habits: Reorganize — status bar top, editorial collapsed, T1/T2 collapsed
2. Labs: Move Dr. Okafor's analysis to position 2

### Phase 4: AI Regeneration & Verification
1. Re-invoke `ai_expert_analyzer_lambda` for all experts if Phase 1 invocations are stale
2. Run Playwright capture script (`captures/capture.mjs`)
3. Upload captures for Product Board V3 review
4. Verify mobile rendering on all 8 modified pages
5. Verify all collapsed sections contain relocated content (no deletions)

---

## 9. Technical Board Sign-Off

### Architecture Review

**Priya (Cloud Architect):** The shared JS module approach is correct for static S3 hosting. A single `observatory-v3.js` with per-page configs avoids server-side templating while reducing the maintenance surface from 6 bespoke HTML files to 1 shared module + 6 thin shells. Approved.

**Marcus (AWS):** No new Lambda needed. All changes are to existing `ai_expert_analyzer_lambda.py` and `site_api_lambda.py`. Deploy via standard `deploy_lambda.sh`. Approved.

**Elena (Staff Engineer):** The `observatory-v3.js` module should export named functions, not a singleton object. This makes individual sections testable and allows pages to opt out of sections they don't need (Mind page skipping standard Section 0). Approved with amendment.

**Jin (SRE):** AI prompt changes increase token usage by ~20-30% per expert invocation. At 8 experts × weekly = negligible cost impact ($0.02-0.04/week increase). Increase `max_tokens` from 1000 to 1200. Approved.

**Omar (Data Architect):** Enhanced data gathering (sleep onset times, modality breakdown, fiber, eating window) requires no schema changes — all fields already exist in DynamoDB. Just additional queries in `gather_data_for_expert()`. Approved.

**Viktor (Adversarial Reviewer):** Defer `/api/observatory_status` consolidation endpoint. Build V3 with existing endpoints. Don't over-engineer. Approved with amendment.

**Anika (AI/LLM Systems):** The rotating analytical lens is a good anti-repetition mechanism. Combined with prior_summary + prior_recommendation, this should produce meaningfully different analyses each week. One risk: the lens might force unnatural framing if the data genuinely calls for the same observation two weeks running. Recommendation: the lens is a *suggestion*, not a constraint — add "If the data strongly warrants revisiting a prior observation, acknowledge you're returning to it and explain why." Approved with amendment.

**Board verdict:** Approved. Three amendments incorporated:
1. Named function exports (Elena)
2. Deferred observatory_status endpoint (Viktor)
3. Lens as suggestion not constraint (Anika)

---

## 10. Content Preservation Checklist

For each page conversion, verify NO content is deleted — only relocated:

- [ ] Hero editorial text → "About this observatory" collapsible
- [ ] Matthew's pull-quote reflections → "About this observatory" collapsible
- [ ] Elena Voss chronicle excerpts (long) → "About this observatory" collapsible
- [ ] Hypothesis cards → "Hypotheses under test (N)" collapsible
- [ ] Measurement protocol → "Measurement protocol" collapsible
- [ ] Educational definitions → Tooltips or "Measurement protocol"
- [ ] Numbered protocol lists → "Measurement protocol" collapsible
- [ ] Cross-domain detailed findings → "Cross-domain findings" collapsible
- [ ] Genomic context → "Genomic context" collapsible (Glucose, Nutrition pages)
- [ ] Coach analysis → PROMOTED to Section 2 (not just preserved — moved UP)
- [ ] Charts and trends → PROMOTED to Section 3
- [ ] Subscribe CTA → Moved to after Section 2 (coach analysis) for maximum conversion

---

## 11. Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `site/assets/js/observatory-v3.js` | CREATE | Shared observatory rendering module (named function exports) |
| `site/assets/css/observatory-v3.css` | CREATE | Shared V3 stylesheet |
| `site/sleep/index.html` | MODIFY | V3 restructure — Approach B |
| `site/glucose/index.html` | MODIFY | V3 restructure — Approach B |
| `site/nutrition/index.html` | MODIFY | V3 restructure — Approach B |
| `site/training/index.html` | MODIFY | V3 restructure — Approach B |
| `site/physical/index.html` | MODIFY | V3 restructure — Approach B |
| `site/mind/index.html` | MODIFY | V3 restructure — Approach C (Conti Amendment) |
| `site/habits/index.html` | MODIFY | V3-lite restructure |
| `site/labs/index.html` | MODIFY | Move coach analysis up, fix AI context |
| `lambdas/ai_expert_analyzer_lambda.py` | MODIFY | V3 prompt, enhanced data gathering, max_tokens 1200, week_number tracking |
| `lambdas/site_api_lambda.py` | MODIFY | Add week_number to ai_analysis response |
| `docs/CHANGELOG.md` | UPDATE | Document V3 changes |
| `docs/ARCHITECTURE.md` | UPDATE | Note V3 observatory pattern |

---

## 12. Success Criteria

After V3 deployment, run Playwright captures and verify:

1. **Every observatory page:** Status metrics visible within the first 200px of scroll
2. **Every observatory page:** Coach analysis fully visible within 600px of scroll (desktop)
3. **Every observatory page:** "This week's action" callout box present and populated
4. **Every observatory page:** Charts render with data (not blank)
5. **Every observatory page:** All collapsed sections expandable and contain the relocated content
6. **Mind page:** Narrative introduction visible (not collapsed)
7. **Habits page:** T0 streak and completion rate visible at top
8. **Labs page:** Dr. Okafor's analysis at position 2
9. **All AI analyses:** No repetition from prior week (verify prior_block working)
10. **Mobile (390px):** All grids collapse cleanly, no horizontal overflow

---

## 13. Pages NOT Modified (Confirmed No Change)

| Page | Rationale |
|------|-----------|
| Live (Today) | Already dashboard-first. Correct pattern. |
| Character (The Score) | Gamification layout works. No editorial bloat. |
| Accountability | Purpose-built for engagement. Nudge system intact. |
| Benchmarks | Unique interactive self-assessment. Don't touch. |
| Data Explorer | Pure tool. Correct pattern. |
