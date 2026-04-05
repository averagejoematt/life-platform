# DPR-1 Implementation Brief
## Design & Engineering Specification for Claude Code

**Source:** Deep Page Review DPR-1 (April 4, 2026)  
**Approved by:** Product Board (unanimous) · Technical Board (architecture review) · Personal Board (mission alignment)  
**Scope:** 13 pages across The Pulse + The Data sections  
**Target version:** v5.0.0

---

## Mission Alignment Statement

> Every change in this brief serves one of three purposes:
> 1. **Serve Matthew** — make the data more actionable for his health transformation
> 2. **Serve the reader** — make the experience honest, compelling, and worth returning to
> 3. **Serve the throughline** — connect every page to the story of Data → Insight → Action → Results → Repeat
>
> If a change doesn't serve at least one of these, it doesn't ship.

---

## How to Use This Brief

Each work item is a self-contained task. Work them in phase order. Within each phase, items are independent and can be done in any sequence. Each item includes:

- **What** — the change
- **Why** — which DPR-1 finding drove it, and which board member identified it
- **Where** — exact files to modify
- **How** — technical approach and design specification
- **Acceptance** — how to verify it's correct
- **Effort** — XS (<15 min), S (<1 hr), M (1-3 hrs), L (3+ hrs)

---

# PHASE 1: CRITICAL FIXES

*Data integrity and credibility issues that undermine the site's premise of radical transparency. Fix these before anything else.*

---

### DPR-1.01 — Fix Pulse Narrative Generator

**What:** The Pulse page narrative reads "No signal yet" even when the API returns data for weight, recovery, sleep, and water. The narrative engine must synthesize available signals into a real sentence.

**Why:** DPR-1 Issue #1 (Critical). Identified by Ava Moreau (Content) and Raj Mehta (Product). A page called "The Pulse" that says "no signal" when data exists is the most visible failure on the site. A subscriber checking daily sees the same dead sentence every morning.

**Where:**
- `lambdas/site_api_lambda.py` — the `/api/pulse` endpoint that generates `narrative` and `status` fields
- OR `lambdas/daily_brief_lambda.py` → `site_stats_refresh_lambda.py` if the narrative is pre-computed and written to `public_stats.json`
- Investigate which Lambda populates `pulse.narrative` and `pulse.status` — the fix goes there

**How:**

The narrative generator should follow this logic:

```
IF weight data exists:
  start with "Day {N}. {weight} lbs — {delta} from start."
IF sleep data exists:
  append sleep context: "Sleep: {hours}h" + quality signal if available
IF recovery data exists AND recovery < 50%:
  append warning: "Recovery {pct}% — consider a lighter day."
IF recovery > 70%:
  append positive: "Recovery strong at {pct}%."
IF journal written today:
  append "Journal logged."
IF no journal:
  append "No journal entry yet."

STATUS logic:
  IF all T0 habits complete AND recovery > 50%: status = "strong"
  IF 2+ signals amber/red OR recovery < 40%: status = "mixed"  
  IF majority gray (truly no data): status = "quiet"
```

**Product Board (Mara Chen):** The narrative must read as a natural sentence, not a concatenation of fields. It should feel like a daily brief headline, not a data dump.

**Technical Board (Priya Nakamura):** Check whether the narrative is generated at API call time or pre-computed. If pre-computed by the daily brief Lambda, the fix is in the compute layer. If generated on the fly by site-api, the fix is in the API handler. The compute layer is preferred — it means the narrative is ready at first page load with no client-side generation delay.

**Acceptance:**
- With weight=296.5, sleep=5.5h, recovery=33%: narrative reads something like "Day 4. 296.5 lbs, down 10.5 from start. Sleep short at 5.5 hours. Recovery low at 33% — rest day suggested."
- With no data at all: narrative reads "No data reported today. Signals populate as wearables sync."
- Status reflects the actual signal mix, not a default

**Effort:** M

---

### DPR-1.02 — Fix Pulse State Classification Engine

**What:** The glyph state classification marks signals with real data as "gray" (which should mean "no data"). Recovery 33% is gray. Sleep 5.5 hrs is gray. Water 1.3L is gray. These should be red, amber, and amber respectively.

**Why:** DPR-1 Issue #2, #11, #12 (Critical + Medium). Identified by James Okafor (CTO) and Dr. Lena Johansson (Science). Gray = "no data." When real data displays as gray, visitors think the system is broken. Recovery at 33% being gray is clinically dangerous — it masks a genuine health signal.

**Where:**
- `lambdas/site_api_lambda.py` — the `/api/pulse` endpoint, specifically the logic that sets `glyph.state` for each signal
- OR `lambdas/daily_metrics_compute_lambda.py` if glyph states are pre-computed

**How:**

Replace the current state classification with explicit threshold logic:

```python
STATE_THRESHOLDS = {
    'scale': {
        'green': lambda v: v.get('delta_1d', 0) <= 0,  # lost or maintained
        'amber': lambda v: 0 < v.get('delta_1d', 0) <= 2,  # small gain
        'red':   lambda v: v.get('delta_1d', 0) > 2,  # significant gain
    },
    'water': {
        'green': lambda v: (v.get('liters', 0) / 3.0) >= 0.8,  # 80%+ of target
        'amber': lambda v: 0.3 <= (v.get('liters', 0) / 3.0) < 0.8,
        'red':   lambda v: (v.get('liters', 0) / 3.0) < 0.3,
    },
    'recovery': {
        'green': lambda v: v.get('recovery_pct', 0) >= 67,
        'amber': lambda v: 34 <= v.get('recovery_pct', 0) < 67,
        'red':   lambda v: v.get('recovery_pct', 0) < 34,
    },
    'sleep': {
        'green': lambda v: v.get('hours', 0) >= 7.0,
        'amber': lambda v: 6.0 <= v.get('hours', 0) < 7.0,
        'red':   lambda v: v.get('hours', 0) < 6.0,
    },
    'movement': {
        'green': lambda v: v.get('steps', 0) >= 8000 or v.get('zone2_week_min', 0) >= 100,
        'amber': lambda v: v.get('steps', 0) >= 4000 or v.get('zone2_week_min', 0) >= 50,
        'red':   lambda v: True,  # below amber
    },
    'lift': {
        'green': lambda v: v.get('trained_today', False),
        'gray':  lambda v: not v.get('trained_today', False),  # rest day is not bad
    },
    'journal': {
        'green': lambda v: v.get('written_today', False),
        'gray':  lambda v: not v.get('written_today', False),
    },
    'mind': {
        'green': lambda v: v.get('score', 0) >= 4,
        'amber': lambda v: 2 <= v.get('score', 0) < 4,
        'red':   lambda v: 0 < v.get('score', 0) < 2,
        'gray':  lambda v: v.get('score', 0) == 0 or v.get('score') is None,
    },
}

# RULE: gray = genuinely no data (value is None/null/absent)
# If a value exists, it MUST be green, amber, or red — never gray
def classify_state(key, glyph_data):
    if not glyph_data or glyph_data.get('value') is None:
        return 'gray'
    thresholds = STATE_THRESHOLDS.get(key, {})
    for state in ['green', 'amber', 'red']:
        fn = thresholds.get(state)
        if fn and fn(glyph_data):
            return state
    return 'gray'  # truly no data
```

**Personal Board (Dr. Lena Johansson):** The thresholds above are clinically reasonable. Recovery < 34% is genuinely concerning (Whoop red zone). Sleep < 6h is below minimum effective dose. These are not arbitrary cutoffs.

**Technical Board (Marcus Webb):** This should be implemented server-side in the compute layer, not client-side. The state should be authoritative in the API response. The frontend should never override it.

**Acceptance:**
- Recovery 33% → red state, red ring, red detail card border
- Sleep 5.5h → red state
- Water 1.3L → amber state
- Weight with -10.5 lb delta → green state
- Journal not written → gray (this is correct — it's truly not done yet)
- Lift on rest day → gray (also correct)

**Effort:** S

---

### DPR-1.03 — Fix Training Step Count Data Contradiction

**What:** The Training page hero shows "11,356 avg daily steps" but Coach Sarah Chen's analysis says "1,632 steps per day on average." One of these numbers is wrong. This is a credibility-destroying inconsistency on a site about data integrity.

**Why:** DPR-1 Issue #3 (Critical). Identified by James Okafor (CTO) and Viktor Sorokin (Skeptic).

**Where:**
- `lambdas/site_api_lambda.py` — the `/api/training` endpoint that returns step count data
- `lambdas/ai_expert_analyzer_lambda.py` or whichever Lambda generates Coach Chen's analysis — check what step data it receives
- `site/training/index.html` — verify which field the hero reads for step count

**How:**
1. Read the `/api/training` response and identify the field used for avg daily steps in the hero
2. Read the data that Coach Chen's analysis Lambda receives
3. Trace both to their DynamoDB source
4. One is likely reading from a different time window or source (e.g., one reads Garmin all-time, the other reads Apple Health last 7 days)
5. Fix whichever is wrong. The truth should come from a single, authoritative source for a single time window

**Technical Board (Omar Khalil):** This is a data architecture issue. Steps come from multiple sources (Garmin, Apple Health, Strava). If the hero reads one source and the AI analysis reads another, they'll diverge. Establish a canonical steps field in the daily metrics compute: `daily_steps_canonical` that merges all sources with deduplication.

**Acceptance:**
- Hero step count and Coach Chen's analysis reference the same number
- The number is sourced from a clearly documented canonical field

**Effort:** S-M (investigation + fix)

---

### DPR-1.04 — Fix/Replace Elena Voss Training Quote

**What:** The Elena Voss Chronicle quote on the Training page reads: *"Eight modalities in thirty days."* The actual data shows 1 modality (walking) with 3 sessions. This is the single most damaging credibility gap on the site.

**Why:** DPR-1 Issue #4 (High). Identified by Viktor Sorokin. *"This is the credibility gap that would make a journalist write a very different kind of story about this platform."*

**Where:**
- `site/training/index.html` — the Elena Voss pullquote element
- Consider: `lambdas/site_stats_refresh_lambda.py` or `lambdas/site_api_lambda.py` if quotes can be made dynamic

**How:**

Two options (choose one):

**Option A (Quick fix):** Replace the hardcoded quote with one that matches current reality:
```html
"Three walks in four days. Not impressive by any metric. But the system is counting, and that matters more than the mileage."
```

**Option B (Better — dynamic quotes):** Make Elena Voss observatory quotes dynamic. The `site_stats_refresh_lambda.py` already generates `public_stats.json`. Add a `chronicle_quotes` section keyed by page, refreshed weekly by the chronicle Lambda. Each observatory page reads its quote from the API rather than hardcoding it.

**Product Board (Ava Moreau):** Option B is strongly preferred. Every Elena Voss quote on every observatory page should be generated from current data, not hardcoded. Hardcoded quotes will always drift from reality. This is a pattern fix, not a one-page fix.

**Personal Board (Elena Voss):** The quote should reflect what the data actually says. If the data says three walks, the quote should say something about three walks. The power of the Chronicle voice is that it's honest — never aspirational. A quote that contradicts visible data makes the entire editorial layer feel fraudulent.

**Acceptance:**
- The displayed quote is consistent with the data shown on the same page
- If using Option B: verify all observatory pages pull quotes from API, not hardcoded HTML

**Effort:** S (Option A) / M (Option B — but covers all pages)

---

### DPR-1.05 — Fix "1 people" Grammar + Nudge Empty States

**What:** Accountability page shows "1 people are following this experiment" (should be "1 person") and all nudge statistics show "—" dashes, making the feature look non-functional.

**Why:** DPR-1 Issues #6, #17 (High + Low). Identified by Tyrell Washington (Design) and Mara Chen (UX).

**Where:**
- `site/accountability/index.html` — the witness counter element and nudge display logic

**How:**

1. **Grammar fix:** In the JS that populates the witness counter, add pluralization:
```javascript
const count = data.subscriber_count || 0;
const word = count === 1 ? 'person is' : 'people are';
el.innerHTML = `<span>${count}</span> ${word} following this experiment`;
```

2. **Empty nudge states:** Replace "—" with contextual prompts when no nudges exist:
```javascript
// Instead of showing "—" for all nudge counts:
if (totalNudges === 0) {
  weekCountEl.textContent = 'Be the first →';
  totalCountEl.textContent = 'None yet';
  lastTimeEl.textContent = 'Waiting for you';
}
```

**Acceptance:**
- "1 person is following" (singular) vs "5 people are following" (plural)
- When no nudges exist: encouraging prompts instead of dashes

**Effort:** XS

---

### DPR-1.06 — Fix Habits Page Data Inconsistencies

**What:** Three inconsistencies: (a) Habit count shows 62 in hero but meta description says 37; (b) Journal pull-quote attributed to "Day 47" on a Day 4 platform; (c) Day of Week chart claims "last 90 days" with only 3 days of data.

**Why:** DPR-1 Issues #7, #8, #14 (High + Medium). Identified by Viktor Sorokin (Skeptic) and Dr. Henning Brandt (Stats).

**Where:**
- `site/habits/index.html` — meta description, journal pull-quote, DOW chart label
- Possibly `lambdas/site_api_lambda.py` → `/api/habits` for the habit count

**How:**

1. **Habit count:** Determine the true number. If 62 includes T2 locked habits, the meta description should say "62 habits across 3 tiers" not "37." If 37 is T0+T1 only, clarify in the hero: "37 active habits (25 more unlock at 90% completion)." Reconcile across hero stat, meta description, OG tags, and any references in site_constants.js.

2. **Journal pull-quote:** Add context to make it honest:
```html
"The hardest habit wasn't the workout. It was the journal. Writing down what I was thinking meant I couldn't pretend I wasn't thinking it."
<cite>// from a previous attempt — the lesson that brought journaling into this system</cite>
```

3. **DOW chart label:** Replace static "last 90 days" with dynamic text:
```javascript
const label = daysTracked < 28 
  ? `${daysTracked} days tracked — patterns emerge after 4+ weeks`
  : `Last 90 days`;
```

**Technical Board (Henning Brandt):** Any chart or statistic that claims a time window must match the actual data volume. Displaying "last 90 days" with 3 data points is statistically misleading. Show the actual N and note when confidence is low.

**Acceptance:**
- Habit count is consistent everywhere (hero, meta, OG)
- Pull-quote is clearly labeled as historical
- DOW chart shows actual data volume and confidence level

**Effort:** S

---

### DPR-1.07 — Add Labs Data Staleness Warning

**What:** Labs page shows data from April 17, 2025 — 352 days old — with no indication this is stale. On a site about live data, year-old numbers without a freshness warning damage credibility.

**Why:** DPR-1 Issue #5 (High). Identified by the Return Visitor lens.

**Where:**
- `site/labs/index.html` — add a banner element below the hero

**How:**

Add a staleness banner that computes days since last draw:

```html
<div class="labs-staleness" id="labs-staleness" style="display:none">
  <span class="labs-staleness__icon">⚠</span>
  <span class="labs-staleness__text">
    Last blood draw: <strong id="labs-last-date">—</strong> · 
    <strong id="labs-days-ago">—</strong> days ago
  </span>
  <span class="labs-staleness__cta">Next draw recommended within 90 days of last</span>
</div>
```

Style it with the observatory amber warning pattern:
```css
.labs-staleness {
  margin: 0 var(--page-padding);
  padding: var(--space-3) var(--space-5);
  background: rgba(var(--amber-rgb, 245,158,11), 0.06);
  border: 1px solid rgba(var(--amber-rgb, 245,158,11), 0.15);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  letter-spacing: var(--ls-tag);
}
```

**Acceptance:**
- Banner shows "Last blood draw: Apr 17, 2025 · 352 days ago"
- Banner only appears when last draw is > 90 days old
- After a new draw, banner disappears or shows days since most recent

**Effort:** XS

---

### DPR-1.08 — Add Goal Date Confidence Caveat (Physical)

**What:** Physical page shows "EST. GOAL DATE: 2026-06-02" based on 13.5 lbs/week extrapolation from 4 days of data. This rate is not sustainable and the projection is misleading.

**Why:** DPR-1 Issue #9 (Medium). Identified by Dr. Lena Johansson (Domain Expert) and Viktor Sorokin (Skeptic).

**Where:**
- `site/physical/index.html` — the goal date display element
- OR `lambdas/site_api_lambda.py` → the endpoint that returns the projection

**How:**

Add a confidence indicator next to the goal date. When data < 28 days:

```html
<div class="projection-caveat">
  <span class="projection-caveat__icon">⚡</span>
  Projection based on <strong>4 days</strong> — stabilizes after 4 weeks.
  Current rate (13.3 lbs/wk) is early-phase water weight loss, not sustained fat loss.
</div>
```

After 28 days, the caveat softens or disappears. After 90 days, show confidence interval.

**Personal Board (Dr. Victor Reyes):** Initial weight loss at Matthew's starting weight (307 lbs) is primarily water and glycogen depletion. Projecting this rate forward is clinically irresponsible. A sustainable fat loss rate at this weight is 2-3 lbs/week. The projection should use the 2 lb/week rate for long-range estimates until 28+ days of data establish the actual trend.

**Acceptance:**
- Goal date includes data confidence note when N < 28 days
- Rate is labeled as "early phase" or "initial" when < 14 days

**Effort:** XS

---

# PHASE 2: DESIGN & POLISH

*Visual, UX, and content improvements that elevate the experience from "functional" to "professional."*

---

### DPR-1.09 — Fix Character Trading Card Pillar Name Truncation

**What:** The 7-column pillar grid in the trading card truncates names to "MOVEM," "NUTRI," "METAB," "CONSI," "RELAT" — these are not readable abbreviations.

**Why:** DPR-1 Issue #13 (Medium). Identified by Tyrell Washington (Design).

**Where:**
- `site/character/index.html` — the `tc-pillars` grid and the JS that populates pillar names

**How:**

**Option A (Tyrell's preference):** Use 3-letter abbreviations that are real words or standard:
```
SLP · MOV · NUT · MET · MND · SOC · CON
```

**Option B:** Use emoji-only in the grid (emoji is already present) and move the name to a tooltip:
```html
<div class="tc-pillar" title="Movement">
  <div class="tc-pillar__icon">🏋️</div>
  <div class="tc-pillar__level">2</div>
  ...
</div>
```

**Product Board (Tyrell Washington):** Option A is cleaner. Three-letter abbreviations are standard in dashboard design. The key constraint is that the grid must remain 7 columns on desktop — never wrapping.

**Acceptance:**
- All 7 pillar names are readable 3-letter abbreviations or emoji-only
- Grid never wraps or overflows on desktop or tablet

**Effort:** XS

---

### DPR-1.10 — Add First-Time Visitor Context to Pulse Page

**What:** A stranger landing on the Pulse page has no explanation of what the 8 glyphs mean, what the colors represent, or what "The Pulse" is. The page assumes knowledge.

**Why:** DPR-1 Issue #16 (Medium). Identified by the First-Time Stranger lens.

**Where:**
- `site/live/index.html` — add a single contextual line below the glyph strip

**How:**

Add a one-line explainer between the glyph strip and detail cards:

```html
<div class="pulse-context" id="pulse-context">
  <span class="pulse-context__text">
    8 daily health signals from wearables and manual logs.
    <span class="pulse-context__legend">
      <span class="pulse-context__dot pulse-context__dot--green"></span> on track
      <span class="pulse-context__dot pulse-context__dot--amber"></span> watch
      <span class="pulse-context__dot pulse-context__dot--red"></span> attention needed
      <span class="pulse-context__dot pulse-context__dot--gray"></span> no data yet
    </span>
  </span>
</div>
```

Style: monospace, `text-2xs`, `text-faint`, centered. Should feel like a system status legend, not a paragraph.

**Product Board (Mara Chen):** This should be dismissible. Show it by default, but if a visitor has been before (localStorage flag), hide it. We don't want return visitors seeing the explainer every day.

**Acceptance:**
- First-time visitors see a one-line explainer with color legend
- Return visitors (localStorage flag) don't see it
- The explainer doesn't add visual clutter or break the page flow

**Effort:** XS

---

### DPR-1.11 — Character Heatmap Early-Data State

**What:** The pillar heatmap on the Character page shows a single-row grid that looks like a rendering bug. With less than 4 weeks of data, show a data-collecting state instead.

**Why:** DPR-1 Issue #15 (Medium). Identified by Henning Brandt (Stats) and Mara Chen (UX).

**Where:**
- `site/character/index.html` — the `renderHeatmap()` function and `heatmap-section`

**How:**

In `renderHeatmap()`, add an early-data gate:

```javascript
if (pillarHistory.length < 4) {
  section.innerHTML = `
    <div class="eyebrow">Pillar history</div>
    <h2 class="text-h3" style="color:var(--text)">Weekly pillar heatmap</h2>
    <div class="heatmap-collecting">
      <div class="heatmap-collecting__preview">
        ${renderMiniPreview(pillarHistory)} <!-- show what we have, small -->
      </div>
      <p class="heatmap-collecting__note">
        ${pillarHistory.length} of 4 weeks collected. 
        The heatmap reveals pillar independence — which domains move together 
        and which operate on their own rhythm.
      </p>
    </div>`;
  section.style.display = '';
  return;
}
```

**Acceptance:**
- < 4 weeks: shows a collecting state with progress indicator and preview
- ≥ 4 weeks: shows full heatmap as currently designed

**Effort:** S

---

### DPR-1.12 — Collapse Empty Training Sections

**What:** The Training page has 4 full centenarian target sections all showing "—", 4 1RM progress charts saying "Awaiting data", and empty sections for Recent Routes and Capability Milestones. This makes the page feel like vaporware.

**Why:** DPR-1 Issue #20 (Low) but contributes to Issue #4's credibility gap. Identified by Mara Chen (UX) and Viktor Sorokin.

**Where:**
- `site/training/index.html` — the centenarian targets, 1RM charts, routes, and milestones sections

**How:**

Wrap empty sections in a conditional display:

```javascript
// In the hydration function:
const hasStrengthData = lifts.some(l => l.current_1rm > 0);

if (!hasStrengthData) {
  document.getElementById('centenarian-section').innerHTML = `
    <div class="awaiting-compact">
      <div class="awaiting-compact__icon">🏋️</div>
      <div class="awaiting-compact__text">
        <strong>Centenarian Benchmarks</strong> — 
        Deadlift, squat, bench, and OHP targets auto-populate after first logged strength session in Hevy.
      </div>
    </div>`;
}
```

**Design spec (Tyrell Washington):** The collapsed state should be a single-line card with left accent border, matching the observatory section header style. Never show 4 full empty sections when one compact placeholder serves the same purpose.

```css
.awaiting-compact {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-6);
  border: 1px solid var(--border);
  border-left: 3px solid var(--border);
  background: var(--surface);
  font-size: var(--text-sm);
  color: var(--text-muted);
}
.awaiting-compact__icon { font-size: 20px; flex-shrink: 0; }
```

Apply this same pattern to: Advanced Training Metrics, Recent Routes, Capability Milestones, and any other section with zero data.

**Acceptance:**
- Sections with no data show a single compact placeholder
- Sections with data show full expanded view
- Transition is automatic when first data arrives

**Effort:** S

---

### DPR-1.13 — Surface Dr. Webb's Key Recommendation (Nutrition)

**What:** Dr. Webb's coaching analysis contains the most actionable recommendation on the entire site — "track only dinner, every day, for seven consecutive days" — but it's buried in the third paragraph of a multi-paragraph analysis block.

**Why:** DPR-1 Issue #18 (Low) but identified as a pattern to replicate. Identified by Raj Mehta (Product).

**Where:**
- `site/nutrition/index.html` — the Dr. Webb analysis section
- `lambdas/ai_expert_analyzer_lambda.py` — the Lambda that generates the analysis

**How:**

**Option A (Frontend only):** After the Dr. Webb analysis block, add a "Key Recommendation" callout box that extracts the actionable line:

```html
<div class="coaching-key-rec">
  <div class="coaching-key-rec__label">This week's focus</div>
  <div class="coaching-key-rec__text" id="webb-key-rec">
    Track only dinner, every day, for seven consecutive days.
  </div>
  <div class="coaching-key-rec__rationale">
    Building a seven-day streak on a single meal establishes the habit 
    foundation before layering complexity back in.
  </div>
</div>
```

**Option B (Better — backend):** Modify the AI analyzer Lambda to output a structured field `key_recommendation` alongside the full analysis. The frontend renders this in a callout box above the full analysis.

```python
# In the AI prompt for board member analysis:
"After your full analysis, output a section labeled KEY RECOMMENDATION 
 containing exactly one specific behavioral suggestion for the coming week. 
 Maximum 2 sentences."
```

**Product Board (Raj Mehta):** Option B should be applied to ALL observatory AI coaching sections — not just Nutrition. Every Dr. Webb, Coach Chen, Dr. Reyes, Dr. Conti, and Dr. Brandt analysis should have a `key_recommendation` field rendered as a prominent callout. This is the "product" — the one thing a visitor takes away from each page.

**Design spec (Tyrell Washington):**
```css
.coaching-key-rec {
  border: 1px solid var(--accent);
  border-left: 4px solid var(--accent);
  background: linear-gradient(135deg, rgba(0,229,160,0.04), transparent 60%);
  padding: var(--space-5) var(--space-6);
  margin-bottom: var(--space-6);
}
.coaching-key-rec__label {
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  letter-spacing: var(--ls-tag);
  text-transform: uppercase;
  color: var(--accent);
  margin-bottom: var(--space-2);
}
.coaching-key-rec__text {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  color: var(--text);
  line-height: 1.3;
  margin-bottom: var(--space-2);
}
.coaching-key-rec__rationale {
  font-size: var(--text-xs);
  color: var(--text-muted);
  line-height: var(--lh-body);
}
```

This pattern should use the page's own color theme (amber for Nutrition, crimson for Training, violet for Mind, blue for Sleep, etc.).

**Acceptance:**
- Each observatory page with an AI coaching analysis shows a "This week's focus" callout above the full analysis
- The callout contains exactly one actionable recommendation
- Design uses page-specific accent color

**Effort:** M (if applying to all 5 coaching pages) / S (Nutrition only)

---

# PHASE 3: ADDITIVE FEATURES

*New capabilities that create return-visitor hooks and deepen the experience.*

---

### DPR-1.14 — Populate "Since Yesterday" Deltas on Pulse Page

**What:** The Pulse page has code for a "Since yesterday" delta line (`renderDelta`) but it's not populated. Adding day-over-day deltas for weight, sleep, and recovery creates the primary return-visitor hook.

**Why:** DPR-1 Issue #4 from the Pulse page roadmap. Identified by the Return Visitor lens.

**Where:**
- `lambdas/site_api_lambda.py` or `lambdas/site_stats_refresh_lambda.py` — add `delta_1d` fields to the pulse API response for scale, recovery, sleep
- `site/live/index.html` — the `renderDelta` function already exists; just needs data

**How:**

In the pulse API compute:
```python
# For each glyph with yesterday's data available:
glyph['delta_1d'] = today_value - yesterday_value
# Also add to pulse.since_yesterday array:
pulse['since_yesterday'] = []
if scale_delta: pulse['since_yesterday'].append(f"Weight {'↑' if d > 0 else '↓'}{abs(d):.1f} lbs")
if recovery_delta: pulse['since_yesterday'].append(f"Recovery {'↑' if d > 0 else '↓'}{abs(d)}%")
if sleep_delta: pulse['since_yesterday'].append(f"Sleep {'↑' if d > 0 else '↓'}{abs(d):.1f}h")
```

**Acceptance:**
- Below the narrative, a line reads: "Since yesterday: Weight ↓1.2 lbs · Recovery ↑8% · Sleep ↓0.5h"
- Deltas are color-coded: improvements green, regressions red
- If no yesterday data exists (Day 1), line is hidden

**Effort:** S

---

### DPR-1.15 — Add "Notable Signal" Banner to Pulse Page

**What:** When a signal is clinically notable (recovery < 40%, sleep < 6h, weight spike > 3 lbs), surface a prominent banner at the top of the detail section with an actionable recommendation.

**Why:** DPR-1 Pulse page roadmap item #5. Identified by Dr. Lena Johansson and the Serves Matthew lens.

**Where:**
- `site/live/index.html` — add a banner element above the detail grid
- `lambdas/site_api_lambda.py` — add a `notable_signals` array to the pulse response

**How:**

Backend:
```python
notable = []
if recovery_pct and recovery_pct < 40:
    notable.append({
        'signal': 'recovery',
        'message': f'Recovery is low at {recovery_pct}%. Consider a rest day or light movement only.',
        'severity': 'warning'
    })
if sleep_hours and sleep_hours < 6:
    notable.append({
        'signal': 'sleep',
        'message': f'Sleep was {sleep_hours:.1f}h — below the 7h minimum. Prioritize an early bedtime tonight.',
        'severity': 'warning'
    })
pulse['notable_signals'] = notable
```

Frontend:
```html
<div class="notable-banner" id="notable-banner" style="display:none">
  <span class="notable-banner__icon">⚠</span>
  <span class="notable-banner__text" id="notable-text"></span>
</div>
```

**Design spec (Tyrell Washington):**
```css
.notable-banner {
  max-width: var(--content-width);
  margin: 0 auto var(--space-4);
  padding: var(--space-3) var(--space-5);
  background: rgba(255, 82, 82, 0.06);
  border: 1px solid rgba(255, 82, 82, 0.2);
  border-left: 3px solid var(--c-red-status);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
```

**Acceptance:**
- Recovery 33% triggers a banner: "⚠ Recovery is low at 33%. Consider a rest day or light movement only."
- Banner appears above the detail cards
- When no signals are notable, banner is hidden

**Effort:** S

---

### DPR-1.16 — Add Day-Over-Day Composite Delta to Character Trading Card

**What:** The Character trading card shows "Score: 45" but doesn't show whether that went up or down from yesterday. Adding a delta arrow creates a daily check-in hook.

**Why:** DPR-1 Character page roadmap item #4. Identified by the Return Visitor lens.

**Where:**
- `site/character/index.html` — the composite score display in the trading card
- `lambdas/site_api_lambda.py` → `/api/character` — add `composite_delta_1d` field

**How:**

In the trading card score display, add a delta indicator:

```javascript
// After setting composite score:
const delta = data.composite_delta_1d;
if (delta !== null && delta !== undefined) {
  const arrow = delta > 0 ? '↑' : delta < 0 ? '↓' : '→';
  const cls = delta > 0 ? 'delta-up' : delta < 0 ? 'delta-down' : 'delta-flat';
  scoreEl.insertAdjacentHTML('afterend', 
    `<div class="tc-composite__delta ${cls}">${arrow}${Math.abs(delta).toFixed(1)} from yesterday</div>`
  );
}
```

**Acceptance:**
- Trading card shows "45 ↓2.1 from yesterday" or "45 ↑1.3 from yesterday"
- Green for improvement, red for decline, neutral for <0.5 change

**Effort:** S

---

### DPR-1.17 — Add CGM Sensor Day Indicator (Glucose)

**What:** No indication of how long the current CGM sensor has been worn. Adding "Sensor: Day 4 of 15" contextualizes the data volume.

**Why:** DPR-1 Glucose page roadmap item #1. Identified by the Data lens.

**Where:**
- `site/glucose/index.html` — add to the freshness indicator area
- `lambdas/site_api_lambda.py` → `/api/glucose` — add sensor day count if available from Dexcom data

**How:**

If sensor start date is available in the CGM data:
```javascript
const sensorDay = data.sensor_day || null;
const sensorMax = 15; // Stelo cycle
if (sensorDay) {
  freshnessEl.insertAdjacentHTML('beforeend', 
    `<span class="sensor-day">Sensor: Day ${sensorDay} of ${sensorMax}</span>`
  );
}
```

**Acceptance:**
- Glucose page shows sensor wear day near the freshness indicator
- Value updates daily

**Effort:** XS

---

### DPR-1.18 — Add Plain-Language Correlation Interpretations (Explorer)

**What:** The Data Explorer shows correlations like "HRV × Recovery (r=+0.86)" which requires statistical literacy. Add a plain-language interpretation alongside each.

**Why:** DPR-1 Explorer page roadmap item #1. Identified by the First-Time Stranger lens.

**Where:**
- `site/explorer/index.html` — the correlation card rendering logic
- OR `lambdas/weekly_correlation_compute_lambda.py` — generate plain-language interpretations during compute

**How:**

Add an interpretation map for common metric pairs:

```javascript
const INTERPRETATIONS = {
  'heart_rate_variability__recovery_score': {
    pos: 'On days when HRV is higher, recovery is almost always better too',
    neg: 'Higher HRV days tend to show lower recovery (unusual — investigate)'
  },
  'sleep_score__recovery_score': {
    pos: 'Better sleep nights reliably predict better recovery the next day',
    neg: 'Higher sleep scores correlate with lower recovery (unexpected)'
  },
  'resting_heart_rate__recovery_score': {
    pos: 'Higher resting HR days show better recovery (unusual)',
    neg: 'Lower resting heart rate is associated with better recovery'
  },
  // ... add more as correlations surface
};

// Fallback for pairs without specific interpretation:
function genericInterpretation(metricA, metricB, r) {
  const dir = r > 0 ? 'higher' : 'lower';
  const also = r > 0 ? 'higher' : 'lower';
  return `Days with ${dir} ${metricA} tend to also show ${also} ${metricB}`;
}
```

Render below each correlation card:
```html
<div class="corr-card__interpretation">
  On days when HRV is higher, recovery is almost always better too
</div>
```

**Acceptance:**
- Every correlation card includes a plain-language sentence
- Language is appropriate for non-technical visitors
- N=1 caveat remains visible

**Effort:** S

---

### DPR-1.19 — Add "Discovery of the Week" to Explorer

**What:** Highlight one new or notable correlation each week as a return-visitor hook and potential newsletter/social share.

**Why:** DPR-1 Addiction Feature #9. Identified by Jordan Kim (Growth).

**Where:**
- `lambdas/weekly_correlation_compute_lambda.py` — select the most notable new correlation each week
- `site/explorer/index.html` — add a "Discovery of the Week" hero card
- `lambdas/site_stats_refresh_lambda.py` — write the selected discovery to `public_stats.json` for cross-page reference

**How:**

In the weekly correlation compute:
```python
# After computing all correlations, select the discovery of the week:
# Priority: new FDR-significant pair > largest r change > strongest new signal
discovery = select_weekly_discovery(new_correlations, changed_correlations)
# Write to public_stats: { 'discovery_of_week': { 'metric_a': ..., 'metric_b': ..., 'r': ..., 'interpretation': ... }}
```

On the Explorer page, render as a prominent hero card above the correlation list:

```html
<div class="dotw-card">
  <div class="dotw-card__label">Discovery of the Week</div>
  <div class="dotw-card__finding" id="dotw-finding">
    Sleep duration now significantly predicts next-day recovery (r=0.40, FDR ✓)
  </div>
  <div class="dotw-card__interpretation" id="dotw-interp">
    This is a new finding — it just crossed the significance threshold this week.
  </div>
  <div class="dotw-card__date" id="dotw-date">Week of April 1, 2026</div>
</div>
```

**Product Board (Jordan Kim):** This is the most shareable unit of content the platform produces. The discovery of the week should also appear in the weekly email digest and have its own OG image for social sharing.

**Acceptance:**
- Explorer page shows a weekly discovery card
- Discovery updates every Sunday (after weekly correlation compute)
- Previous discoveries are visible as an archive below

**Effort:** M

---

### DPR-1.20 — "Since Your Last Visit" Nav Indicators

**What:** Dot badges on nav items when content has updated since the visitor's last visit. Creates a return-visit habit.

**Why:** DPR-1 Addiction Feature #10 and Website Strategy Phase 4 item #38. Identified by Jordan Kim (Growth) and the Return Visitor lens.

**Where:**
- `site/assets/js/nav.js` — the shared navigation component
- `lambdas/site_stats_refresh_lambda.py` — add `page_last_updated` timestamps per section to `public_stats.json`

**How:**

1. **Backend:** In `site_stats_refresh_lambda.py`, add a `page_freshness` object:
```python
page_freshness = {
    'pulse': last_pulse_update_iso,
    'character': last_character_update_iso,
    'sleep': last_sleep_data_iso,
    'glucose': last_glucose_data_iso,
    'nutrition': last_nutrition_data_iso,
    'training': last_training_data_iso,
    'chronicle': last_chronicle_publish_iso,
    # ... etc
}
write_to_public_stats('page_freshness', page_freshness)
```

2. **Frontend:** In `nav.js`, on page load:
```javascript
// Read last visit timestamp from localStorage
const lastVisit = JSON.parse(localStorage.getItem('amj_last_visits') || '{}');

// Fetch page freshness from public_stats.json
fetch('/api/vitals') // or wherever page_freshness lives
  .then(r => r.json())
  .then(data => {
    const freshness = data.page_freshness || {};
    Object.entries(freshness).forEach(([page, updated]) => {
      const lastSeen = lastVisit[page] || '1970-01-01';
      if (updated > lastSeen) {
        // Add dot badge to nav item
        const navItem = document.querySelector(`[data-nav="${page}"]`);
        if (navItem) navItem.classList.add('has-update');
      }
    });
  });

// On page view, record visit time
const currentPage = window.location.pathname.replace(/\//g, '') || 'home';
lastVisit[currentPage] = new Date().toISOString();
localStorage.setItem('amj_last_visits', JSON.stringify(lastVisit));
```

3. **CSS:** Small dot badge on nav items:
```css
.has-update::after {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  position: absolute;
  top: 4px;
  right: -2px;
}
```

**Technical Board (Priya Nakamura):** Using localStorage for visit tracking is appropriate — no server-side session needed, no privacy concerns. The `page_freshness` data should be part of the existing `public_stats.json` refresh cycle, not a new API call.

**Product Board (Mara Chen):** The dots should be subtle — a 6px green circle, not a flashing badge. They should disappear when the visitor navigates to that page. The goal is gentle pull, not notification fatigue.

**Acceptance:**
- After not visiting for 24+ hours, nav items with new data show a small green dot
- Clicking the page clears its dot
- Dots only appear for pages with genuinely new data (new data timestamp > last visit timestamp)

**Effort:** M

---

# PHASE 4: LABS OBSERVATORY REDESIGN

*The weakest page gets the observatory treatment.*

---

### DPR-1.21 — Labs Observatory Design Overhaul

**What:** The Labs page is the only Data section page that doesn't follow the observatory editorial pattern. It's a raw data table with no AI coaching, no gauges, no pull-quotes, no narrative sections. Bring it to parity.

**Why:** DPR-1 Issue #10 (Medium). Identified by Tyrell Washington (Design) and the Product Board.

**Where:**
- `site/labs/index.html` — full redesign
- `lambdas/site_api_lambda.py` → `/api/labs` — may need to add computed fields
- `lambdas/ai_expert_analyzer_lambda.py` — add Dr. Okafor analysis for labs data

**How:**

Apply the established observatory pattern:

1. **Hero with gauges:** 4 gauge rings showing % in range, flagged count, draws completed, and days since last draw
2. **"This Week in Labs" summary:** Not applicable (labs are periodic), replace with "Latest Draw Summary" — date, key findings, flagged count
3. **AI coaching analysis:** Dr. James Okafor interprets the flagged values in context of Matthew's current nutrition, training, and supplement protocols. Example: "ApoB at 107 with LDL-P at 1787 in the context of a high-protein deficit suggests..." This analysis should be generated by the AI analyzer Lambda.
4. **Pull-quotes with evidence badges:** At least 2 — one from Matthew about getting labs at the starting line, one from the analysis
5. **"What I'm Doing About It" section:** For each flagged marker, link to the relevant protocol, supplement, or behavior change. Close the action loop.
6. **Trend charts:** When 2+ draws exist for a biomarker, show trend sparklines
7. **Section headers:** Use monospace em-dash pattern matching other observatories

**Design spec (Tyrell Washington):** Use a clinical teal or steel-blue color theme (distinct from Sleep's blue, Glucose's teal). The page should feel like a high-end lab report, not a spreadsheet.

**Product Board (Raj Mehta):** The "What I'm Doing About It" section is the most important addition. Without it, flagged values are just scary numbers. With it, they become evidence of a plan. This is where the Labs page connects to the Supplements, Protocols, and Nutrition pages — completing the throughline loop.

**Acceptance:**
- Labs page has hero gauges, AI coaching analysis, pull-quotes, and action plan sections
- Design follows observatory pattern with its own color theme
- Flagged markers link to relevant protocol/supplement pages
- Data staleness banner from DPR-1.07 is integrated into the new design

**Effort:** L

---

# IMPLEMENTATION NOTES

## Deploy Order

Phases 1-2-3 can be deployed independently. Within each phase, items are independent.

**Recommended deploy sequence:**
1. DPR-1.02 (state classification) — quick win, biggest visual impact
2. DPR-1.01 (narrative generator) — requires investigation first
3. DPR-1.05 (grammar + nudge states) — 5-minute fix
4. DPR-1.06 (habits inconsistencies) — 5-minute fixes
5. DPR-1.07 (labs staleness) — 5-minute fix
6. DPR-1.03 (training step data) — requires investigation
7. DPR-1.04 (Elena Voss quote) — quick fix or pattern-level change
8. Remaining Phase 2 items
9. Phase 3 features
10. Phase 4 (Labs redesign) — standalone project

## Files Most Frequently Modified

| File | Items |
|------|-------|
| `site/live/index.html` | DPR-1.01, .02, .10, .14, .15 |
| `lambdas/site_api_lambda.py` | DPR-1.01, .02, .03, .14, .15, .16 |
| `site/character/index.html` | DPR-1.09, .11, .16 |
| `site/training/index.html` | DPR-1.03, .04, .12 |
| `site/habits/index.html` | DPR-1.06 |
| `site/accountability/index.html` | DPR-1.05 |
| `site/nutrition/index.html` | DPR-1.13 |
| `site/labs/index.html` | DPR-1.07, .21 |
| `site/glucose/index.html` | DPR-1.17 |
| `site/explorer/index.html` | DPR-1.18, .19 |
| `site/assets/js/nav.js` | DPR-1.20 |
| `lambdas/ai_expert_analyzer_lambda.py` | DPR-1.13 (key_rec pattern) |
| `lambdas/site_stats_refresh_lambda.py` | DPR-1.04 (dynamic quotes), .19, .20 |

## Design System Compliance

All new elements must use:
- **Typography:** `var(--font-display)` for headlines, `var(--font-mono)` for labels/tags, `var(--font-serif)` for pull-quotes
- **Spacing:** `var(--space-N)` tokens only — no hardcoded px values
- **Colors:** Observatory page accent colors (sleep=blue, glucose=teal, nutrition=amber, training=crimson, mind=violet, labs=tbd)
- **Components:** Monospace section headers with em-dash trail, pull-quotes with evidence badges, gauge rings for hero metrics, left-accent bordered cards
- **Mobile:** All new elements must work at 390px viewport. Test with Playwright mobile captures.

## Henning Brandt Statistical Standards

Any chart, metric, or statistical claim must:
- Show actual N when N < 30
- Display confidence caveat when N < 14
- Never claim a time window larger than the actual data (no "last 90 days" with 3 data points)
- Use correlative, not causal, framing
- Include N=1 disclaimer on any cross-domain finding

---

*Brief prepared April 4, 2026. Product Board, Technical Board, and Personal Board consensus.*
