# V3.1 Observatory Polish — Design & Technical Specification

**Version:** 3.1
**Date:** 2026-04-05
**Author:** Product Board post-implementation review + reader panel feedback
**Parent spec:** `docs/V3_OBSERVATORY_SPEC.md`
**Status:** Ready for implementation
**Ticket:** PB-09.1

---

## Context

V3 was implemented successfully. The core structure — status bar → coach analysis → trends → detail → depth — is correct and working across all 8 target pages. This V3.1 spec addresses 7 findings from the Product Board's post-implementation review and simulated reader panel testing.

**Priority tiers:**
- **P0 (must-do):** Items 1-2 — these are the highest-leverage changes for returning readers
- **P1 (should-do):** Items 3-4, 7 — quick wins that improve clarity
- **P2 (nice-to-have):** Items 5-6 — visual polish

---

## Item 1: Week-over-Week Deltas on Status Bar Metrics

**Priority:** P0 — highest-leverage single change for returning readers
**Problem:** Status bar metrics show current values and static context lines, but no directional indicators showing whether numbers improved or declined vs the prior period. Returning readers can't answer "am I improving?" at a glance.

### Design Specification

Each metric cell in the status bar gains a **delta line** between the current value and the context line:

```
┌─────────────────────┐
│ LAST NIGHT           │  ← label (11px uppercase, muted)
│ 8.2 hrs              │  ← value (28px)
│ +2.8h ↑              │  ← NEW: delta (12px, color-coded)
│ 6 nights tracked     │  ← context (12px, muted)
└─────────────────────┘
```

**Delta display rules:**
- **Green + ↑** when the metric improved (higher sleep, lower resting HR, higher protein hit rate)
- **Red + ↓** when the metric declined
- **Amber + →** when flat (change < 2% of value)
- **Gray "—"** when insufficient prior data for comparison (< 2 weeks of data)
- Format: `+2.8h ↑` or `-0.2h ↓` or `→ flat` or `— insufficient data`

**Comparison period:** Current 7-day average vs prior 7-day average. If fewer than 7 days exist in either period, use whatever days are available but append "(early data)" to the delta.

**Polarity per metric** (which direction is "good"):

| Metric | Up = Good? | Notes |
|--------|-----------|-------|
| Sleep duration | ✅ Yes | More sleep is better (up to ~9h) |
| Sleep score | ✅ Yes | Higher score = better |
| Deep sleep % | ✅ Yes | Target >20% |
| Recovery % | ✅ Yes | Higher = better recovered |
| Time in range % | ✅ Yes | Higher = better glucose control |
| Avg glucose | ❌ No | Lower is generally better (within range) |
| Glucose SD | ❌ No | Lower variability = better |
| Optimal range % | ✅ Yes | Higher = better |
| Daily avg cal | ⚠️ Context | In deficit: lower may be good; use amber/neutral |
| Protein avg | ✅ Yes | Higher toward target is better |
| Protein hit rate | ✅ Yes | Higher = better |
| Days logged | ✅ Yes | More logging = better |
| Zone 2 min/wk | ✅ Yes | Target 150 min |
| Sessions | ✅ Yes | More consistent = better |
| Avg strain | ⚠️ Context | Too high is bad, too low is bad; use amber/neutral |
| Daily steps | ✅ Yes | Target 10k |
| Current weight | ❌ No | In weight loss phase: lower is progress |
| Total lost | ✅ Yes | More lost = progress |
| Weekly rate | ⚠️ Context | Target 1-2 lbs/wk; >3 is too aggressive |
| Body fat % | ❌ No | Lower is better |

### Technical Implementation

**Where:** Each observatory page's status bar rendering code. If using the shared `observatory-v3.js` module, add delta calculation to `renderStatusBar()`.

**Data source:** The status bar already fetches current values from various API endpoints. For deltas, the JS needs to either:
- (a) Fetch the same endpoint with a date range parameter covering the prior 7 days and compute the delta client-side, OR
- (b) Use the existing data that's already being fetched for trend charts (which already contains 30 days of data) and compute current-7d vs prior-7d from that array

Option (b) is preferred — no new API calls needed. The trend chart data is already on the page; the status bar just needs to read from it.

**Example implementation pattern:**
```javascript
function computeDelta(dataArray, valueKey, daysBack = 7) {
  // dataArray is the 30-day trend data already fetched for charts
  const now = new Date();
  const current = dataArray.filter(d => daysBetween(d.date, now) <= daysBack);
  const prior = dataArray.filter(d => daysBetween(d.date, now) > daysBack && daysBetween(d.date, now) <= daysBack * 2);
  
  if (current.length < 2 || prior.length < 2) return { delta: null, label: '— insufficient data' };
  
  const currentAvg = average(current.map(d => d[valueKey]));
  const priorAvg = average(prior.map(d => d[valueKey]));
  const delta = currentAvg - priorAvg;
  
  return { delta, currentAvg, priorAvg };
}

function renderDelta(delta, polarity, unit) {
  // polarity: 'higher_better', 'lower_better', or 'neutral'
  if (delta === null) return '<span class="obs-delta-none">— insufficient data</span>';
  
  const sign = delta > 0 ? '+' : '';
  const arrow = delta > 0 ? '↑' : delta < 0 ? '↓' : '→';
  const isGood = polarity === 'higher_better' ? delta > 0 :
                 polarity === 'lower_better' ? delta < 0 : null;
  const colorClass = isGood === true ? 'obs-delta-up' :
                     isGood === false ? 'obs-delta-down' : 'obs-delta-flat';
  
  return `<span class="${colorClass}">${sign}${delta.toFixed(1)}${unit} ${arrow}</span>`;
}
```

**CSS additions to `observatory-v3.css`:**
```css
.obs-delta-up { color: var(--green, #3fb950); font-size: 12px; }
.obs-delta-down { color: var(--red, #f85149); font-size: 12px; }
.obs-delta-flat { color: var(--amber, #d29922); font-size: 12px; }
.obs-delta-none { color: var(--muted, #484f58); font-size: 12px; font-style: italic; }
```

---

## Item 2: Complete Depth-Section Collapse on Nutrition + Training

**Priority:** P0 — these pages are still partially V2 below the fold
**Problem:** The V3 treatment was applied to the top of Nutrition and Training (status bar + coach + subscribe CTA), but significant V2 content remains inline below the trends section. These pages are still 3,000-5,000 words longer than they should be.

### Nutrition Page — Content to Collapse

The following content currently sits inline and should move into collapsible `<details>` sections:

| Current inline content | Move to collapsed section |
|----------------------|--------------------------|
| Matthew's personal narrative ("Food and I have had a complicated relationship...") | "About this observatory" |
| "I've lost 100 lbs before..." reflection paragraph | "About this observatory" |
| Matthew pull-quote #4 ("The hardest part of tracking...") | "About this observatory" |
| Matthew block-quote ("The plan is to log everything...") | "About this observatory" |
| Hypothesis cards (H-01 through H-04) inline | "Hypotheses under test (4)" |
| Micronutrient Gaps section (choline, vitamin D, omega-3, folate) | "Genomic context & micronutrients" |
| Behavioral Trigger Analysis (sleep deprivation, travel, stress) | "Behavioral triggers" |
| Macro Deep-Dives (carbs, fats, fiber detail) | "Macro deep-dives" |
| Hydration section | "Hydration tracking" |
| TDEE Adaptation Tracking section | Can stay inline — it's data, not editorial |
| Nutrition protocol numbered list ("01: 180g protein...") | "Nutrition protocol" |
| Measurement protocol (MacroFactor, protein target, CGM cross-ref) | "Measurement protocol" |

**What STAYS inline on Nutrition (after coach + trends):**
- 30-day calorie & macro summary bar (1,227 avg cal/day)
- Daily average breakdown (protein/carbs/fat cards)
- Protein adherence section (bar + per-meal distribution)
- Top meals table (most frequently logged)
- Protein source breakdown (bar chart)
- Weekday vs weekend comparison
- Eating window
- Caloric periodization (training vs rest days)
- "What I Actually Eat" recent meals
- 30-day calorie & protein trend chart
- TDEE adaptation tracking
- Cross-domain connections cards

### Training Page — Content to Collapse

| Current inline content | Move to collapsed section |
|----------------------|--------------------------|
| Matthew's reflection ("When I'm in it, I'm all in...") | "About this observatory" |
| Hypothesis card H-01 inline (Zone 2 volume) | "Hypotheses under test (4)" |
| Pull-quote #2 (Rucking Zone 2 yield) | "About this observatory" |
| Pull-quote #3 (Back-to-back strain) | "About this observatory" |
| Elena Voss chronicle quote (inline, full block) | Remove — already have Elena quote in coach section |
| Running — Coming Soon placeholder | "Coming soon" or remove entirely |
| Advanced Training Metrics placeholder | "Advanced metrics (coming soon)" |
| Centenarian Benchmarks placeholder | Keep as teaser card but shorten |
| 1RM Progress placeholder | Keep as teaser card but shorten |
| Training Balance — Attia Pillars (all zeros) | "Training balance framework" |
| When I Train (hour distribution, empty) | "Session timing analysis" |
| Recent Routes (empty) | "GPS routes" |
| Capability Milestones (empty) | "Milestones" |
| Training hypotheses list (H-01 through H-04) | "Hypotheses under test (4)" |
| Full training protocol numbered list | "Training protocol" |
| Measurement protocol | "Measurement protocol" |

**What STAYS inline on Training (after coach + trends):**
- Training volume breakdown (Zone 2, total min, weekly sessions)
- Activity breakdown cards (Walk stats)
- Walking & steps section
- Daily steps chart
- Breathwork summary
- This week's movement grid
- 12-week training volume chart
- Cross-domain connections cards

### Implementation Notes

- For each block of content being collapsed, wrap it in a `<details>` element
- Use consistent class: `<details class="obs-depth-section">`
- Use specific summary labels (not "Deep Dive")
- Preserve ALL content — nothing is deleted, only collapsed
- The `<details>` sections should be grouped at the bottom of the page in a "DEEP DIVE" zone, or distributed inline near related content as individual collapsibles — **group them at the bottom** per the V3 spec Section 6 pattern
- Any duplicate Elena Voss quotes (the ones that were already in V2 AND the new one in the coach section) — remove the V2 duplicate, keep only the coach section version

---

## Item 3: Add One-Line Page Subtitle

**Priority:** P1
**Problem:** First-time visitors who land on an observatory page have no immediate context about what the experiment is. They see numbers and a coach analysis but don't know this is a 12-month N=1 public health experiment.

### Design Specification

Add a single subtitle line between the observatory nav bar and the status bar:

```
SLEEP OBSERVATORY                                          Day 5 · Updated 0h ago
Tracking one person's sleep data across a 12-month health experiment.
┌──────────┬──────────┬──────────┬──────────┐
│ 8.2 hrs  │ 82       │ 25%      │ 44%      │
```

**Subtitles per page:**

| Page | Subtitle |
|------|----------|
| Sleep | Tracking one person's sleep architecture across a 12-month health experiment. |
| Glucose | Continuous glucose monitoring across a 12-month body composition experiment. |
| Nutrition | Every calorie logged. Every macro tracked. A 12-month nutrition record. |
| Training | Training for longevity, not aesthetics. A 12-month movement record. |
| Physical | 307 lbs on Day 1. Tracking the trajectory across 12 months. |
| Mind | The pillar most health platforms don't measure. A 12-month inner record. |

**Styling:** 13px, muted color (`var(--text-faint)` or equivalent), single line, no bold. Should be subtle — context for newcomers, invisible to returning readers.

### Technical Implementation

Add a `<p>` element with class `obs-subtitle` between the observatory nav and the status grid on each page. One line of HTML per page.

```css
.obs-subtitle {
  font-size: 13px;
  color: var(--text-faint, #484f58);
  margin: 0 0 16px 0;
  letter-spacing: 0.01em;
}
```

---

## Item 4: Specific Depth Section Labels

**Priority:** P1
**Problem:** Some pages use generic "Deep Dive" headers on collapsed sections. The V3 spec requires specific labels so readers know what's inside without clicking.

### Required Labels Per Page

**Sleep:**
- "About this observatory" (hero editorial, Matthew's reflections)
- "Hypotheses under test (4)" (with count)
- "Measurement protocol" (Whoop, Eight Sleep, methodology)

**Glucose:**
- "About this observatory"
- "Hypotheses under test (4)"
- "Genomic context" (FADS2, MTHFR variants)
- "Measurement protocol" (Dexcom Stelo, TIR methodology)

**Nutrition:**
- "About this observatory"
- "Hypotheses under test (4)"
- "Genomic context & micronutrients" (PEMT, VDR, FADS1, MTHFR)
- "Behavioral triggers" (sleep deprivation, travel, stress patterns)
- "Macro deep-dives" (carbs, fats, fiber detail)
- "Nutrition protocol"
- "Measurement protocol"

**Training:**
- "About this observatory"
- "Hypotheses under test (4)"
- "Training balance framework" (Attia 5 pillars)
- "Advanced metrics (populates at week 4+)"
- "Training protocol"
- "Measurement protocol"

**Physical:**
- "About this observatory"
- "Measurement protocol"

**Mind:**
- "What this page will become" (the month 1-6 roadmap)
- "Cognitive pattern frameworks" (CBT, ACT, PERMA)
- "Measurement protocol"
- Note: Mind page keeps editorial intro and five promises VISIBLE per Conti Amendment

### Technical Implementation

Replace any `<summary>` text that says "Deep Dive" or uses generic labels. Each `<details>` element gets its specific label. If hypotheses have a count, include it in the label dynamically:

```html
<details class="obs-depth-section">
  <summary>Hypotheses under test (4)</summary>
  <!-- hypothesis cards -->
</details>
```

---

## Item 5: Visual Section Dividers

**Priority:** P2
**Problem:** The transition between Status → Coach → Trends → Detail zones blends together. Readers don't feel the page as distinct scannable sections.

### Design Specification

Add subtle horizontal rules between major sections. Not heavy borders — just enough visual breathing room.

```css
.obs-section-divider {
  border: none;
  border-top: 1px solid var(--border-subtle, #21262d);
  margin: 32px 0;
}
```

**Place dividers between:**
1. Status bar ↔ Coach analysis
2. Coach analysis (including Elena quote + subscribe CTA) ↔ Trends
3. Trends ↔ This week's detail
4. This week's detail ↔ Cross-domain
5. Cross-domain ↔ Depth sections

Also add slightly more vertical padding above each section header label (e.g., "TRENDS", "THIS WEEK'S DETAIL", "CROSS-DOMAIN FINDINGS") — increase from current spacing to `margin-top: 40px`.

---

## Item 6: Depth Section Teasers

**Priority:** P2
**Problem:** Collapsed depth sections give no hint of what's inside. A reader interested in genomic context doesn't know it's there unless they click every section.

### Design Specification

Add a one-line preview below each collapsed `<summary>`:

```html
<details class="obs-depth-section">
  <summary>
    Genomic context
    <span class="obs-depth-teaser">FADS2, MTHFR variants and their effect on glucose response</span>
  </summary>
  <!-- full content -->
</details>
```

**Styling:**
```css
.obs-depth-teaser {
  display: block;
  font-size: 11px;
  color: var(--text-faint, #484f58);
  font-weight: 400;
  margin-top: 2px;
  letter-spacing: 0;
  text-transform: none;
}
```

**Teasers per section (examples):**

| Section | Teaser |
|---------|--------|
| About this observatory | The story behind this page and Matthew's reflections |
| Hypotheses under test (4) | Screen-off timing, bed temperature, alcohol impact, bedtime consistency |
| Genomic context | FADS2, MTHFR variants — why population averages don't apply |
| Measurement protocol | Whoop 4.0, Eight Sleep Pod, Apple Health — how data is collected |
| Behavioral triggers | Sleep deprivation, travel, stress — when nutrition falls apart |
| Training balance framework | Attia's 5 pillars: Zone 2, strength, stability, Zone 5, sport |

---

## Item 7: Mind Page Elena Quote Formatting Fix

**Priority:** P1
**Problem:** The Elena Voss quote on the Mind page has the JOURNALING PROMPT appended to it, creating a single run-on block. These are two separate content types that should render separately.

### Current (broken):
```
"Six days in, and his writing touches everything with the same careful pressure — the 
signature, she's learned, of someone who hasn't yet decided what they came here to say." 
JOURNALING PROMPT: What is the one thing you've been thinking about this week that you 
haven't written down yet — and what made it feel like the wrong thing to put on the page?"
```

### Required (fixed):

The Elena quote renders in the standard `obs-elena-quote` block. The journaling prompt renders in its own distinct block below it:

```html
<!-- Elena quote — same as all other pages -->
<blockquote class="obs-elena-quote">
  "Six days in, and his writing touches everything with the same careful pressure..."
  <cite>Elena Voss · Chronicle →</cite>
</blockquote>

<!-- Journaling prompt — Mind page only -->
<div class="obs-journaling-prompt">
  <span class="obs-journaling-label">THIS WEEK'S JOURNALING PROMPT</span>
  <p>What is the one thing you've been thinking about this week that you 
  haven't written down yet — and what made it feel like the wrong thing 
  to put on the page?</p>
</div>
```

**Styling:**
```css
.obs-journaling-prompt {
  background: var(--surface-raised, #161b22);
  border-left: 3px solid var(--purple, #8b5cf6);
  padding: 12px 16px;
  border-radius: 0 8px 8px 0;
  margin-top: 12px;
}

.obs-journaling-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: var(--purple, #8b5cf6);
  display: block;
  margin-bottom: 4px;
}

.obs-journaling-prompt p {
  font-size: 14px;
  color: var(--text-primary, #e6edf3);
  font-style: italic;
  margin: 0;
  line-height: 1.6;
}
```

### Technical Root Cause

This is likely a parsing issue in the JavaScript that renders the coach analysis. The `/api/ai_analysis?expert=mind` endpoint returns separate fields:
- `elena_quote` — should contain ONLY the Elena quote
- `journaling_prompt` — should contain ONLY the journaling prompt

If the Elena quote field contains both (i.e., the Lambda's text splitting failed to separate them), the fix is in `ai_expert_analyzer_lambda.py`'s parsing logic. Check the order of splits — the code currently splits on `ELENA QUOTE:` first, then `JOURNALING PROMPT:`. If the JOURNALING PROMPT appears inside the Elena quote text, the split order may be wrong.

**Fix in Lambda (if needed):**
```python
# Split in reverse order of appearance in the prompt output:
# Analysis text comes first, then KEY RECOMMENDATION, then JOURNALING PROMPT, then ELENA QUOTE
# Split from bottom up to avoid capturing later sections in earlier ones

if "ELENA QUOTE:" in analysis_text:
    parts = analysis_text.rsplit("ELENA QUOTE:", 1)
    analysis_text = parts[0].rstrip()
    elena_quote = parts[1].strip().strip('"').strip('\u201c').strip('\u201d')

if "JOURNALING PROMPT:" in analysis_text:
    parts = analysis_text.rsplit("JOURNALING PROMPT:", 1)
    analysis_text = parts[0].rstrip()
    journaling_prompt = parts[1].strip()

if "KEY RECOMMENDATION:" in analysis_text:
    parts = analysis_text.rsplit("KEY RECOMMENDATION:", 1)
    analysis_text = parts[0].rstrip()
    key_recommendation = parts[1].strip()
```

**Also check:** If the `elena_quote` already contains "JOURNALING PROMPT:" text, strip it:
```python
if "JOURNALING PROMPT:" in elena_quote:
    elena_quote = elena_quote.split("JOURNALING PROMPT:")[0].strip().strip('"')
```

**Fix in page rendering JS (Mind page):**
The Mind page's coach analysis renderer should check for both `data.elena_quote` and `data.journaling_prompt` and render them as separate blocks. If `journaling_prompt` exists, render the purple-bordered prompt box below the Elena quote.

---

## Files to Modify

| File | Items | Changes |
|------|-------|---------|
| `site/assets/js/observatory-v3.js` | 1, 5, 6 | Add delta rendering to status bar, section dividers, depth teasers |
| `site/assets/css/observatory-v3.css` | 1, 3, 5, 6, 7 | Delta colors, subtitle, dividers, teasers, journaling prompt styles |
| `site/sleep/index.html` | 1, 3, 4, 5 | Deltas, subtitle, specific labels, dividers |
| `site/glucose/index.html` | 1, 3, 4, 5 | Same |
| `site/nutrition/index.html` | 1, 2, 3, 4, 5, 6 | Deltas, subtitle, labels, dividers, PLUS complete depth-section collapse |
| `site/training/index.html` | 1, 2, 3, 4, 5, 6 | Same as nutrition — complete depth-section collapse |
| `site/physical/index.html` | 1, 3, 4, 5 | Deltas, subtitle, labels, dividers |
| `site/mind/index.html` | 1, 3, 4, 5, 7 | Deltas, subtitle, labels, dividers, Elena/journaling prompt fix |
| `lambdas/ai_expert_analyzer_lambda.py` | 7 | Fix Elena quote / journaling prompt parsing order (if root cause is Lambda) |
| `lambdas/site_api_lambda.py` | 7 | Ensure `journaling_prompt` field is returned in ai_analysis response |

---

## Implementation Order

1. **Start with Item 1 (deltas)** — this touches the shared JS module and all pages, so do it first
2. **Item 2 (Nutrition + Training collapse)** — the biggest content surgery, do second
3. **Items 3 + 4 (subtitle + labels)** — quick text changes across all pages, batch together
4. **Item 7 (Mind Elena fix)** — may need Lambda fix, do separately
5. **Items 5 + 6 (dividers + teasers)** — CSS polish, do last

Estimated effort: 1-2 Claude Code sessions.

---

## Verification

After implementation, run Playwright captures and check:

1. [ ] Every status bar metric shows a delta indicator (or "— insufficient data" for early metrics)
2. [ ] Nutrition page is significantly shorter — editorial, hypotheses, micronutrients, behavioral triggers all collapsed
3. [ ] Training page is significantly shorter — editorial, hypotheses, empty placeholders, protocol all collapsed
4. [ ] Every page has a one-line subtitle below the observatory title
5. [ ] No collapsed section uses generic "Deep Dive" label
6. [ ] Mind page Elena quote and journaling prompt render as separate blocks
7. [ ] Visual dividers visible between major sections
8. [ ] No content was deleted — everything that was inline is now in a collapsed section
9. [ ] Mobile (390px) — deltas render cleanly, don't overflow metric cells
