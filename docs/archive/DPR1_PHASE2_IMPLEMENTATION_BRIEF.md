# DPR-1 Phase 2 Implementation Brief
## The Practice + The Platform + The Chronicle + Utility

**Source:** DPR-1 Phase 2 Review (April 4, 2026)  
**Scope:** 26 pages across 4 sections  
**Target version:** v5.0.0 (combined with Phase 1 brief)  
**Note:** Supplements, Challenges, and Experiment Library empty-content issues were caused by a data pipeline bug being fixed separately. Those items are excluded from this brief.

---

## Mission Alignment

> Same as Phase 1: every change serves Matthew's health transformation, the reader's experience, or the throughline. If it doesn't serve at least one, it doesn't ship.

---

# PHASE 1: CRITICAL FIXES

---

### DPR-2.01 — Fix Intelligence Page "[object Object]" Rendering Bug

**What:** The Character Engine section (#4 of 14) on the Intelligence page displays: *"Level — . Pillars: 0: [object Object], 1: [object Object], 2: [object Object]..."* — a JavaScript object serialization error visible on the live page.

**Why:** Critical. On the page that showcases the intelligence layer's sophistication, a raw JS error looks amateurish.

**Where:**
- `site/intelligence/index.html` — the Character Engine rendering block (system #4)

**How:**

Find the rendering code for system #4 and fix the object serialization:

```javascript
// WRONG (current):
el.textContent = `Level ${data.level}. Pillars: ${data.pillars}`;

// RIGHT:
const pillarText = data.pillars.map(p => `${p.name}: ${p.raw_score}/100`).join(' · ');
el.textContent = `Level ${data.level}. ${pillarText}`;
```

Or better — render as a mini pillar bar visualization matching the Character page pattern.

**Acceptance:**
- Character Engine section shows formatted level + pillar scores, no [object Object]
- Data matches what the Character page displays

**Effort:** XS

---

### DPR-2.02 — Fix "1 people" Grammar on Subscribe Page

**What:** Subscribe page shows "Join 1 people following the experiment" — same pluralization bug as Accountability page.

**Why:** High. Appears on the most important conversion page.

**Where:**
- `site/subscribe/index.html` — the subscriber count display element

**How:** Same fix as DPR-1.05:
```javascript
const count = data.subscriber_count || 0;
const word = count === 1 ? 'person' : 'people';
el.textContent = `Join ${count} ${word} following the experiment`;
```

**Acceptance:** Singular/plural correct at all counts

**Effort:** XS

---

### DPR-2.03 — Fix Recap Weight Delta Framing

**What:** The Recap page shows "WEIGHT 296.0 lbs +6.2 lbs (30d)" — the "+6.2" implies weight gain over 30 days, which contradicts the -11 lbs journey narrative. The 30-day window likely includes pre-experiment data when weight was lower.

**Why:** High. Weight delta on a weight loss platform showing a positive number confuses and alarms visitors.

**Where:**
- `site/recap/index.html` or `lambdas/site_api_lambda.py` → the recap data endpoint

**How:**

Change the delta framing from "30d" to "journey start":

```javascript
// Instead of: +6.2 lbs (30d) — which includes pre-experiment data
// Show: -11.0 lbs (from start) — which tells the real story

const delta = currentWeight - startWeight; // 296 - 307 = -11
const sign = delta < 0 ? '' : '+';
el.textContent = `${sign}${delta.toFixed(1)} lbs (from start)`;
```

If a 30-day delta is also shown, it should use the experiment start date as the floor — never show a delta from before the experiment began.

**Acceptance:**
- Weight delta shows loss from journey start, not a misleading 30-day window
- No positive weight delta appears when overall journey is a loss

**Effort:** S

---

### DPR-2.04 — Fix Data Source Count Inconsistency (Stack Page)

**What:** Stack page hero shows "DATA SOURCES: 19" but the platform, methodology, and all other pages show 26. Hardcoded number.

**Why:** High. The Stack page is "the complete operating system" — wrong number undermines positioning.

**Where:**
- `site/stack/index.html` — the hero stat for data sources

**How:** Replace with dynamic value:
```html
<div class="os-hero-stat__val" data-const="platform.data_sources">26</div>
```

**Acceptance:** Data source count matches across all pages

**Effort:** XS

---

# PHASE 2: DESIGN & POLISH

---

### DPR-2.05 — Reconcile Cost Claims ($19 vs $25.67)

**What:** Cost page claims "~$19/month" but Status page shows "Projected: $25.67 — 171% of budget."

**Where:**
- `site/cost/index.html` — the hero cost figure

**How:** Update to reflect realistic variability:
```
$11–25/month · Varies by Claude API usage. Typical: ~$15. High-usage: ~$25.
```

**Acceptance:** Cost page and Status page tell a consistent story

**Effort:** XS

---

### DPR-2.06 — Add Sample Response to Ask Page

**What:** Ask the Data page shows suggested questions but no example answer. The Board page demonstrates its feature with a full sample response — Ask should too.

**Where:**
- `site/ask/index.html`

**How:**

Add a collapsible "See an example" section:

```html
<details class="ask-example">
  <summary>See what an answer looks like</summary>
  <div class="ask-example__q">How's my sleep trending?</div>
  <div class="ask-example__a">
    Your 7-day average sleep is 6.6 hours (down from 7.6 last week). 
    Deep sleep percentage is 22.7% — above the 20% threshold. Your biggest 
    issue is efficiency: 63.5%, meaning 37% of time in bed isn't sleep. 
    Bedtime consistency has a 1.25-hour weekend drift.
  </div>
</details>
```

**Product Board (Sofia Herrera):** Pick a cross-domain question like "What's my biggest risk right now?" to demonstrate the AI's most impressive capability.

**Acceptance:**
- Example response visible below input, collapsible
- Demonstrates cross-domain insight

**Effort:** S

---

### DPR-2.07 — Improve Community Page

**What:** The Community page is the weakest page on the site — three generic descriptions and a Discord link. For a platform that measures social connection as a health pillar, this is conspicuously thin.

**Where:**
- `site/community/index.html`

**How:**

1. **Matthew's personal CTA:** Paragraph connecting to the Mind page's social isolation observations and Murthy's research
2. **Current state:** Show member count and last activity timestamp
3. **Specific examples:** "This week's discussion: whether resting heart rate or HRV is a better recovery predictor"
4. **Platform connection:** "Community members can submit experiment suggestions, vote on what I test next"

**Design spec:** Match the Accountability page's warm amber aesthetic.

**Acceptance:**
- Page has Matthew's personal voice
- At least one specific, current content example
- Visual warmth matching accountability design

**Effort:** S

---

### DPR-2.08 — Collapse Empty Discovery Details

**What:** Discovery timeline entries show titles like "Nutrition Pattern — 2026-04-03" but no expandable detail or summary.

**Where:**
- `site/discoveries/index.html` — the discovery timeline rendering
- `lambdas/site_api_lambda.py` → the discoveries endpoint

**How:**

For each discovery entry, show a 1-2 sentence summary:

```javascript
if (discovery.summary) {
  html += `<div class="disc-summary">${discovery.summary}</div>`;
} else if (discovery.finding) {
  html += `<div class="disc-summary">${discovery.finding}</div>`;
}
```

Entries without content should show "Analysis in progress" rather than a bare title.

**Acceptance:**
- Each discovery entry has at least a summary sentence
- Entries without content show processing state

**Effort:** S

---

### DPR-2.09 — Hide Kitchen from Navigation Until Ready

**What:** Kitchen page is a "coming soon" placeholder visible in navigation.

**Where:**
- `site/assets/js/nav.js` or `site/assets/js/components.js` — nav/footer link lists

**How:** Remove Kitchen from footer and nav. Keep `/kitchen/` accessible via direct URL. Nutrition page reference becomes subtle.

**Acceptance:** Kitchen not discoverable through navigation; still loads via direct URL

**Effort:** XS

---

### DPR-2.10 — Port Start Page Narrative Logic to Pulse Page

**What:** The Start page shows a fully functioning narrative: *"Day 4. 296.5 lbs — down 10.5 from start. Sleep: 5.5h — short night. Recovery low at 33% — rest day suggested."* This is exactly what the Pulse page should say but doesn't (it shows "No signal yet"). The Start page already has the working implementation.

**Why:** This means the narrative generation logic already exists — it just isn't connected to the Pulse page. **This may resolve DPR-1.01 entirely.**

**Where:**
- `site/start/index.html` — find the JS or API call that generates the narrative pulse feed
- `site/live/index.html` — the `p-narrative` element showing "No signal yet"
- `lambdas/site_api_lambda.py` — compare the `/api/pulse` response vs whatever the Start page uses

**How:**

Investigate which endpoint the Start page reads from. If it's a different endpoint or a different field in `public_stats.json`, route the same data to the Pulse page. The Start page's implementation is the reference.

**Acceptance:**
- Pulse page narrative matches Start page narrative quality
- Both pages read from the same data source

**Effort:** S

---

# PHASE 3: ADDITIVE FEATURES

---

### DPR-2.11 — Dynamic Elena Voss Observatory Quotes (Pattern Fix)

**What:** DPR-1.04 identified the Training page's stale Elena Voss quote ("Eight modalities in thirty days") as a critical credibility issue. This is a pattern problem — hardcoded Elena quotes on multiple observatory pages will all eventually drift from reality.

**Where:**
- All observatory pages: `sleep/`, `glucose/`, `nutrition/`, `training/`, `physical/`, `mind/`, `labs/`
- `lambdas/site_stats_refresh_lambda.py` — add a `chronicle_quotes` section to `public_stats.json`
- `lambdas/wednesday_chronicle_lambda.py` — generate page-specific quotes during chronicle creation

**How:**

1. In the Wednesday chronicle Lambda, generate one short Elena Voss observation per observatory domain based on current data:

```python
domain_quotes = {}
for domain in ['sleep', 'glucose', 'nutrition', 'training', 'physical', 'mind', 'labs']:
    quote = generate_elena_quote(domain, current_data[domain])
    domain_quotes[domain] = {
        'text': quote,
        'date': today_iso,
        'badge': 'CHRONICLE · ELENA VOSS'
    }
```

2. Each observatory page reads its Elena quote from the API rather than hardcoding

3. Fallback: generic line like *"The numbers tell the story. This week's chronicle has the interpretation."*

**Personal Board (Margaret Calloway):** Quotes should follow a consistent editorial pattern: observation + implication. Example: "Three walks this week. Not a training log — a floor he's building." Never aspirational. Just noticing.

**Acceptance:**
- All observatory Elena quotes refresh weekly from current data
- No quote contradicts data visible on the same page
- Fallback exists when no dynamic quote available

**Effort:** M (covers all 7 observatory pages)

---

### DPR-2.12 — Consider Merging Recap into Weekly Snapshots

**What:** Chronicle section has three pages covering the same week. Recap may be redundant — its content could be added to Weekly Snapshots as a summary section.

**Where:**
- `site/recap/index.html` → `site/weekly/index.html`

**How:**

Add "Week at a Glance" summary to top of Weekly Snapshots (vital signs, domain highlights, looking ahead). Redirect `/recap/` to `/weekly/`.

**Product Board (Mara Chen):** Two views is the right number: Elena's narrative (Chronicle) + data view (Weekly Snapshots with summary).

**Acceptance:**
- Weekly Snapshots includes summary section at top
- `/recap/` redirects to `/weekly/`

**Effort:** M

---

# PHASE 4: PLATFORM SECTION POLISH (LOW PRIORITY)

---

### DPR-2.13 — Fix Tool Count Inconsistencies Across Platform Pages

**What:** Various pages reference different tool/Lambda/source counts. Status says "116 tools," Builders says "116 tools," Platform says "121 tools."

**Where:**
- `site/status/index.html`, `site/builders/index.html`, `site/platform/index.html`
- `site/assets/js/site_constants.js`

**How:** Replace all hardcoded platform stats with `data-const` attributes reading from `site_constants.js`. Run grep across `site/` for hardcoded numbers (19, 26, 62, 95, 103, 116, 121) and replace with dynamic references.

**Acceptance:**
- All platform counts consistent across every page
- Single source of truth in `site_constants.js`

**Effort:** S

---

# IMPLEMENTATION NOTES

## Deploy Order

1. **DPR-2.01** (Intelligence [object Object]) — XS, immediate visual fix
2. **DPR-2.02** (Subscribe "1 people") — XS
3. **DPR-2.04** (Stack "19 data sources") — XS
4. **DPR-2.05** (Cost inconsistency) — XS
5. **DPR-2.09** (Hide Kitchen from nav) — XS
6. **DPR-2.03** (Recap weight delta) — S
7. **DPR-2.10** (Port Start narrative to Pulse) — S, may resolve DPR-1.01
8. **DPR-2.06** (Ask sample response) — S
9. **DPR-2.07** (Community page) — S
10. **DPR-2.08** (Discovery details) — S
11. **DPR-2.11** (Dynamic Elena quotes) — M, pattern fix
12. **DPR-2.12** (Merge Recap) — M
13. **DPR-2.13** (Count parameterization) — S

## Files Most Frequently Modified

| File | Items |
|------|-------|
| `site/intelligence/index.html` | DPR-2.01 |
| `site/subscribe/index.html` | DPR-2.02 |
| `site/recap/index.html` | DPR-2.03, DPR-2.12 |
| `site/stack/index.html` | DPR-2.04 |
| `site/cost/index.html` | DPR-2.05 |
| `site/ask/index.html` | DPR-2.06 |
| `site/community/index.html` | DPR-2.07 |
| `site/discoveries/index.html` | DPR-2.08 |
| `site/live/index.html` | DPR-2.10 |
| `site/weekly/index.html` | DPR-2.12 |
| `lambdas/site_api_lambda.py` | DPR-2.03, .10 |
| `lambdas/site_stats_refresh_lambda.py` | DPR-2.11, .13 |
| `lambdas/wednesday_chronicle_lambda.py` | DPR-2.11 |
| `site/assets/js/site_constants.js` | DPR-2.13 |
| Multiple observatory pages | DPR-2.11 (dynamic Elena quotes) |

## Relationship to Phase 1 Brief

- **DPR-2.10** (porting Start page narrative to Pulse) likely resolves **DPR-1.01** from Phase 1. Start there rather than building from scratch.
- **DPR-2.11** (dynamic Elena quotes) is the pattern-level fix for **DPR-1.04** (Training stale quote). Implementing DPR-2.11 makes DPR-1.04 unnecessary as a standalone fix.
- **DPR-2.13** (count parameterization) extends **DPR-1.06's** principle to all platform pages.

## Combined Priority Stack (Both Briefs)

**XS fixes first (30 minutes total):**
DPR-2.01, DPR-2.02, DPR-2.04, DPR-2.05, DPR-2.09, DPR-1.05, DPR-1.06, DPR-1.07, DPR-1.08, DPR-1.09

**S fixes next (2-3 hours):**
DPR-2.10 → may resolve DPR-1.01, DPR-1.02 (state classification), DPR-2.03, DPR-2.06, DPR-2.07, DPR-2.08, DPR-1.10, DPR-1.14, DPR-1.15

**M features (4-6 hours):**
DPR-2.11, DPR-1.13, DPR-1.19, DPR-1.20, DPR-2.12

**L projects (standalone sessions):**
DPR-1.21 (Labs observatory redesign)

---

*Brief prepared April 4, 2026. All three boards consulted. Supplements/Challenges/Experiment Library items excluded — data pipeline bug being fixed separately.*
