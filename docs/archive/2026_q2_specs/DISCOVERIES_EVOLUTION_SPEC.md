# Discoveries Page Evolution Spec

## Product Board Review — March 25, 2026

> **Source**: Full Product Board review of `/discoveries/` page
> **Board**: Mara Chen, James Okafor, Sofia Herrera, Dr. Lena Johansson, Raj Mehta, Tyrell Washington, Jordan Kim, Ava Moreau
> **Usage**: Claude Code works through tasks by priority. Each tier is a standalone session.

---

## Current State

The Discoveries page (`site/discoveries/index.html`) calls `/api/correlations` which reads from the `SOURCE#weekly_correlations` DynamoDB partition. The correlation engine (`weekly_correlation_compute_lambda.py`) runs every Sunday at 11:30 AM PT, computing 23 Pearson pairs (20 cross-sectional + 3 lagged) over a 90-day rolling window with Benjamini-Hochberg FDR correction.

**What works well:**
- Progressive disclosure: featured → spotlight → archive table
- Empty state with progress bar is excellent
- Statistical methodology explainer box
- Pipeline nav (Protocols → Experiments → Discoveries)
- N=1 disclaimer is appropriately honest

**What's broken or missing:**
- Counterintuitive section is 100% hardcoded HTML (no API backing)
- No confidence threshold on featured card (promotes noise when signals are weak)
- No temporal metadata (first detected, weeks confirmed, trend direction)
- No behavioral response field ("what did I do about this?")
- No connection to experiments or chronicle entries
- Mobile hides wrong column (variable names hidden, strength kept)
- No SEO indexable content (all JS-rendered)
- No discovery-specific email CTA

---

## TIER 1 — Fix What's Broken

**Effort**: 1-2 sessions | **Priority**: Do first

### DISC-1: Wire counterintuitive section to real data ✨

**Problem**: Three hardcoded `<div class="ci-card">` elements that never change. On a page titled "What the AI has actually found," static content is a credibility breach.

**Solution A (recommended)**: Add an `expected_direction` map to the correlation compute Lambda. When the observed direction differs from expected, flag the pair as counterintuitive.

**Changes to `weekly_correlation_compute_lambda.py`:**

```python
# Add after CORRELATION_PAIRS definition (~line 400)
# Domain knowledge: expected direction for each pair.
# When observed direction differs, the finding is counterintuitive.
EXPECTED_DIRECTIONS = {
    "hrv_vs_recovery":              "positive",   # higher HRV → better recovery
    "sleep_duration_vs_recovery":   "positive",   # more sleep → better recovery
    "sleep_score_vs_recovery":      "positive",   # better sleep → better recovery
    "hrv_vs_sleep_score":           "positive",   # higher HRV → better sleep
    "rhr_vs_recovery":              "negative",   # lower RHR → better recovery
    "tsb_vs_recovery":              "positive",   # positive TSB → better recovery
    "strain_vs_hrv":                "negative",   # more strain → lower HRV (same day)
    "training_load_vs_hrv":         "negative",   # more training → lower HRV
    "training_mins_vs_recovery":    "negative",   # more training → lower recovery (same day)
    "protein_vs_recovery":          "positive",   # more protein → better recovery
    "calories_vs_hrv":              "positive",   # adequate calories → higher HRV
    "carbs_vs_hrv":                 "positive",   # adequate carbs → higher HRV
    "steps_vs_recovery":            "positive",   # more steps → better recovery
    "steps_vs_hrv":                 "positive",   # more steps → higher HRV
    "steps_vs_sleep":               "positive",   # more steps → better sleep
    "habit_pct_vs_day_grade":       "positive",   # better habits → better day
    "habit_pct_vs_recovery":        "positive",   # better habits → better recovery
    "tier0_streak_vs_day_grade":    "positive",   # longer streak → better day
    "calories_vs_day_grade":        "positive",   # adequate calories → better day
    "readiness_vs_day_grade":       "positive",   # higher readiness → better day
    "hrv_predicts_next_day_load":   "positive",   # higher HRV → more training next day
    "recovery_predicts_next_day_load": "positive", # better recovery → more training next day
    "load_predicts_next_day_recovery": "negative", # more load → lower recovery next day
}
```

**In `compute_correlations()`, add after the `results[label]` dict is built (~line 456):**

```python
    expected = EXPECTED_DIRECTIONS.get(label)
    observed = results[label].get("direction")
    results[label]["expected_direction"] = expected
    results[label]["counterintuitive"] = (
        expected is not None
        and observed is not None
        and expected != observed
        and abs(results[label].get("pearson_r") or 0) >= 0.2  # only flag if signal is meaningful
    )
```

**Changes to `site_api_lambda.py` `handle_correlations()`:**

Add to the `public_pairs` dict (~line 1375):

```python
    "counterintuitive":    p.get("counterintuitive", False),
    "expected_direction":  p.get("expected_direction", ""),
```

**Changes to `site/discoveries/index.html`:**

Replace the hardcoded `ci-grid` with dynamic rendering:

```javascript
// In loadDiscoveries(), after archive table rendering:
const counterintuitive = pairs.filter(p => p.counterintuitive);
const ciGrid = document.getElementById('ci-grid');
if (counterintuitive.length > 0) {
  ciGrid.innerHTML = counterintuitive.slice(0, 3).map(p => `
    <div class="ci-card">
      <div class="ci-card__surprise">// Counterintuitive</div>
      <div class="ci-card__finding">${pairToEnglish(p)}</div>
      <div class="ci-card__expected">Expected: ${p.expected_direction} relationship</div>
      <div class="ci-card__actual">Observed: r=${rSign(p.r)}${p.r.toFixed(2)} (${p.r > 0 ? 'positive' : 'negative'}, n=${p.n})</div>
    </div>`).join('');
} else {
  // Show "no surprises yet" state
  ciGrid.innerHTML = `
    <div style="grid-column:1/-1;border:1px solid var(--border-subtle);padding:var(--space-8);text-align:center;">
      <div style="font-family:var(--font-mono);font-size:var(--text-xs);color:var(--text-faint)">
        No counterintuitive findings this week — all correlations match expected directions.
        <br>Check back after Sunday's engine run.
      </div>
    </div>`;
}
```

**Files changed**: `weekly_correlation_compute_lambda.py`, `site_api_lambda.py`, `site/discoveries/index.html`
**Deploy**: Lambda deploy (both compute + site-api) + S3 sync

---

### DISC-2: Add confidence threshold to featured card

**Problem**: The featured card shows the strongest |r| pair regardless of significance. At r=0.12 with n=30, that's noise being promoted as insight.

**Changes to `site/discoveries/index.html`:**

Replace the featured card rendering logic:

```javascript
// Featured card: strongest SIGNIFICANT pair, or "no strong signal" if none qualify
const significantPairs = pairs.filter(p => p.fdr_significant || (p.p < 0.05 && Math.abs(p.r) >= 0.3));
const top = significantPairs.length > 0 ? significantPairs[0] : null;

if (top) {
  document.getElementById('featured-card').innerHTML = `
    <div class="featured-card__finding">
      ${(top.label_a || top.field_a)} <span>${top.r > 0 ? '↑ positively' : '↓ negatively'} predicts</span> ${(top.label_b || top.field_b)}
    </div>
    <!-- ... rest of existing template ... -->`;
} else {
  document.getElementById('featured-card').innerHTML = `
    <div style="border:1px solid var(--border-subtle);border-left:4px solid var(--accent-dim);padding:var(--space-8);">
      <div style="font-family:var(--font-display);font-size:var(--text-h2);color:var(--text);margin-bottom:var(--space-4)">
        No strong signal this week
      </div>
      <p style="font-size:var(--text-sm);color:var(--text-muted);max-width:560px;line-height:var(--lh-body);">
        The engine tested ${pairs.length} pairs but none cleared the significance threshold (FDR-corrected p < 0.05 with |r| ≥ 0.3).
        That's not a failure — it's honest science. Noise isn't signal.
      </p>
    </div>`;
}
```

**Files changed**: `site/discoveries/index.html`

---

### DISC-3: Add temporal metadata (first_detected, weeks_confirmed)

**Problem**: No way to know when a finding first appeared or how long it's persisted. A finding that's held for 8 weeks is dramatically more credible than one that just appeared.

**Changes to `weekly_correlation_compute_lambda.py`:**

In `store_correlations()`, before writing the new item, read the previous week's correlations to compute temporal metadata:

```python
def store_correlations(week_key, correlations, start_date, end_date, computed_at):
    """Write correlation results with temporal tracking."""

    # Read ALL previous weeks to build temporal history
    pk = USER_PREFIX + "weekly_correlations"
    history_resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk),
        ScanIndexForward=False,
        Limit=52,  # up to 1 year of history
    )
    history_items = history_resp.get("Items", [])

    # Build first_detected and weeks_present per pair label
    temporal = {}
    for label in correlations:
        first_seen = week_key
        weeks_present = 0
        was_fdr = False
        for old_item in reversed(history_items):  # oldest first
            old_corrs = old_item.get("correlations", {})
            if label in old_corrs:
                old_week = old_item.get("week", old_item["sk"].replace("WEEK#", ""))
                if first_seen == week_key:
                    first_seen = old_week
                old_r = float(old_corrs[label].get("pearson_r", 0) or 0)
                curr_r = float(correlations[label].get("pearson_r", 0) or 0)
                # Same direction and both non-trivial
                if (old_r > 0) == (curr_r > 0) and abs(old_r) >= 0.15:
                    weeks_present += 1
                    if old_corrs[label].get("fdr_significant"):
                        was_fdr = True

        temporal[label] = {
            "first_detected": first_seen,
            "weeks_confirmed": weeks_present,
            "ever_fdr_significant": was_fdr or correlations[label].get("fdr_significant", False),
        }

    # Merge temporal metadata into correlations before storing
    for label, data in correlations.items():
        data.update({
            "first_detected":      temporal[label]["first_detected"],
            "weeks_confirmed":     Decimal(str(temporal[label]["weeks_confirmed"])),
            "ever_fdr_significant": temporal[label]["ever_fdr_significant"],
        })

    # ... rest of existing store logic ...
```

**Changes to `site_api_lambda.py`:**

Add to `public_pairs` dict:

```python
    "first_detected":     p.get("first_detected", ""),
    "weeks_confirmed":    int(p.get("weeks_confirmed", 0)),
```

**Changes to `site/discoveries/index.html`:**

Add to featured card and spotlight card templates:

```javascript
// In featured card, after the data spans:
${top.weeks_confirmed > 1 ? `<span class="featured-card__datum">Confirmed: <strong>${top.weeks_confirmed} weeks</strong></span>` : ''}
${top.first_detected ? `<span class="featured-card__datum">First detected: <strong>${top.first_detected}</strong></span>` : ''}

// In spotlight card, add to meta line:
${p.weeks_confirmed > 1 ? ` · confirmed ${p.weeks_confirmed} weeks` : ' · new this week'}

// In archive table, add a "Tenure" column:
<th>Tenure</th>
// ... and in rows:
<td class="td-stat">${p.weeks_confirmed > 0 ? p.weeks_confirmed + 'w' : 'new'}</td>
```

**Files changed**: `weekly_correlation_compute_lambda.py`, `site_api_lambda.py`, `site/discoveries/index.html`

---

### DISC-4: Fix mobile column visibility

**Problem**: On mobile (<768px), the archive table hides `td-stat` (variable names) but keeps `n / Strength`. On a data page, losing the metric pair names is worse than losing the sample size.

**Fix in `site/discoveries/index.html` CSS:**

```css
/* Replace existing mobile rule */
@media (max-width: 768px) {
  .stats-strip { grid-template-columns: 1fr 1fr; }
  .spotlight-grid { grid-template-columns: 1fr; }
  .ci-grid { grid-template-columns: 1fr; }
  /* Hide strength/n column, keep variable names */
  .archive-table .td-strength { display: none; }
}
```

Also requires adding a `.td-strength` class to the 4th column (`n / Strength`) cells instead of using the generic `.td-stat` class. The 3rd column (Variables) keeps `.td-stat` but should NOT be hidden.

**Files changed**: `site/discoveries/index.html`

---

### DISC-5: Strengthen the N=1 disclaimer (Dr. Lena)

**Problem**: Disclaimer says findings "changed my behavior" but doesn't add the medical safety note.

**Fix**: Add one sentence to the existing disclaimer:

```html
These findings changed my behavior — they may not apply to you.
This is observation, not prescription.
<strong>These findings have not been externally validated and should not be used to make medical decisions.</strong>
```

Also add the actual analysis window dates. In JS, after loading data:

```javascript
// Add analysis window dates below the stats strip
if (c.start_date && c.end_date) {
  // ... render: "Analysis window: Feb 9 – May 10, 2026"
}
```

This requires adding `start_date` and `end_date` to the API response (they're already stored in the DDB item but not surfaced by `handle_correlations()`).

**Files changed**: `site/discoveries/index.html`, `site_api_lambda.py` (add `start_date`/`end_date` to response)

---

## TIER 2 — Make It a Destination

**Effort**: 2-3 sessions | **Priority**: After Tier 1

### DISC-6: Discovery timeline (historical view)

**Concept**: Instead of showing only the current week, let visitors see how findings have evolved. A finding that went from r=0.30 to r=0.52 over 8 weeks is a narrative. A finding that appeared strong in week 4 but faded by week 8 is also a narrative.

**Implementation approach**:

1. **New API parameter**: `/api/correlations?history=true&pair=hrv_vs_recovery` returns the r-value for a specific pair across all stored weeks.

2. **New API endpoint**: `/api/correlation_history?pair=hrv_vs_recovery` (cleaner, dedicated):

```python
def handle_correlation_history(event: dict = None) -> dict:
    """GET /api/correlation_history?pair=<label>
    Returns weekly r-values for a specific pair over all stored weeks.
    """
    params = (event or {}).get("queryStringParameters") or {}
    pair_label = params.get("pair", "")
    if not pair_label:
        return _error(400, "Missing required parameter: pair")

    pk = f"{USER_PREFIX}weekly_correlations"
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk),
        ScanIndexForward=True,  # chronological
    )
    items = _decimal_to_float(resp.get("Items", []))

    timeline = []
    for item in items:
        week = item.get("week", item["sk"].replace("WEEK#", ""))
        corrs = item.get("correlations", {})
        if pair_label in corrs:
            p = corrs[pair_label]
            timeline.append({
                "week": week,
                "r": round(float(p.get("pearson_r", 0)), 3),
                "n": int(p.get("n_days", 0)),
                "fdr_significant": p.get("fdr_significant", False),
                "strength": p.get("interpretation", "weak"),
            })

    return _ok({
        "pair": pair_label,
        "timeline": timeline,
        "weeks_tracked": len(timeline),
    }, cache_seconds=3600)
```

3. **UI**: Clickable sparkline on each spotlight card and archive row. Clicking expands to a mini chart (Chart.js line chart) showing r-value over time with FDR threshold line.

**Files changed**: `site_api_lambda.py` (new endpoint), `site/discoveries/index.html` (sparkline + expand interaction)

---

### DISC-7: Behavioral response field

**Concept**: Each featured finding should show what behavioral change it triggered. "After this discovery, I shifted bedtime from ~11:45 to 10:45."

**Implementation**:

1. **New S3 config file**: `config/discovery_annotations.json`:

```json
{
  "hrv_vs_recovery": {
    "behavioral_response": "Confirmed that HRV is the single best predictor of my recovery score. Now using HRV trend as the primary morning decision signal for training intensity.",
    "linked_experiment": null,
    "linked_chronicle": null
  },
  "sleep_duration_vs_recovery": {
    "behavioral_response": "Set a hard bedtime alarm at 10:15 PM. Sleep consistency protocol added as a Tier 0 habit.",
    "linked_experiment": "EXP-003",
    "linked_chronicle": "week-05"
  }
}
```

2. **API**: `handle_correlations()` reads this config and merges annotations into the response. Annotation fields are optional — pairs without annotations simply don't show the behavioral response section.

3. **UI**: Below the featured card and spotlight cards, a new section:

```html
<div class="behavioral-response">
  <span class="behavioral-response__label">// What I did about it</span>
  <p class="behavioral-response__text">...</p>
  <a href="/experiments/#EXP-003">See the experiment →</a>
</div>
```

**Files changed**: New `config/discovery_annotations.json` (S3), `site_api_lambda.py`, `site/discoveries/index.html`

---

### DISC-8: Bidirectional links (Discoveries ↔ Experiments ↔ Chronicle)

**Concept**: When a discovery triggers an experiment, both pages link to each other. When Elena writes about a finding, the discovery page links to the Chronicle entry.

**Implementation**: Uses the same `discovery_annotations.json` config from DISC-7. The `linked_experiment` and `linked_chronicle` fields create the connections:

- On Discoveries page: "This finding led to [Experiment: Early Bedtime Protocol →]"
- On Experiments page: "Triggered by [Discovery: sleep duration → recovery →]"
- On Chronicle: "See the data: [Discovery: sleep duration → recovery →]"

**Dependency**: DISC-7 must be done first (shares the same config file).

**Files changed**: `site/discoveries/index.html`, `site/experiments/index.html`, chronicle template

---

## TIER 3 — Growth & Content Engine

**Effort**: 2-3 sessions | **Priority**: After Tier 2

### DISC-9: SEO pre-rendering

**Problem**: The entire page is JS-rendered. Google won't index any findings. Zero organic search potential.

**Solution**: Add a `<noscript>` block with the top 5-10 findings as static HTML, generated at build time (or by a Lambda that writes to S3 weekly after the correlation engine runs).

**Implementation approach** (lightweight, no SSR framework):

1. After `weekly_correlation_compute_lambda.py` stores correlations, trigger a new Lambda (`discoveries_static_render_lambda.py`) via EventBridge.

2. This Lambda reads the latest correlations, generates a static HTML fragment with proper `<h2>` headings and descriptive text for each finding, and writes it to `s3://matthew-life-platform/site/discoveries/_seo_fragment.html`.

3. The `index.html` includes this fragment inside `<noscript>` tags (or better, as the initial HTML that JS then enhances).

**Alternative (simpler)**: Add `<meta name="description">` content dynamically in the site-api by serving the discoveries page through a Lambda that injects top findings into the HTML before serving. More complex but better SEO.

**Files changed**: New Lambda or build script, `site/discoveries/index.html`

---

### DISC-10: Discovery-specific email CTA

**Concept**: Replace the generic subscribe banner with: "Get notified when new discoveries drop. Every Sunday the engine runs — be the first to know what the data found."

**Implementation**: Add a parameter to the subscribe form that tags the subscriber as interested in discoveries. This can later power segmented emails (BACKLOG-5: Choose Your Signal).

```html
<div class="disc-subscribe">
  <div class="section-eyebrow">// Stay in the loop</div>
  <h3>Get notified when new discoveries drop</h3>
  <p>Every Sunday, the correlation engine processes 23 metric pairs over 90 days of data.
     Be the first to know what the data found.</p>
  <form>
    <input type="email" placeholder="your@email.com">
    <input type="hidden" name="interest" value="discoveries">
    <button type="submit">Notify me →</button>
  </form>
</div>
```

**Files changed**: `site/discoveries/index.html`, `lambdas/subscriber_lambda.py` (accept interest tag)

---

### DISC-11: Auto-generate Chronicle drafts from new findings

**Concept** (Ava Moreau): When the Sunday engine produces a new FDR-significant finding, automatically generate a Chronicle draft for Elena Voss. This is the "content engine that runs without Matthew."

**Pipeline**: `weekly_correlation_compute` → EventBridge → `chronicle_draft_lambda` → DynamoDB draft → email to Matthew for approval → publish

**Implementation**:

1. At the end of `weekly_correlation_compute_lambda.py`, compare this week's FDR-significant pairs against last week's. If any are new (not FDR-significant last week), emit an EventBridge event: `{"detail-type": "new_fdr_discovery", "detail": {"pair": "...", "r": ..., "n": ...}}`.

2. New Lambda `chronicle_auto_draft_lambda.py` receives the event, generates an Elena Voss-style draft using Claude API, stores it in DynamoDB as a chronicle draft with `status: "pending_approval"`.

3. Existing chronicle approval flow (CHRON-4) handles Matthew's review.

**Dependency**: CHRON-3 and CHRON-4 should be working first.

**Files changed**: `weekly_correlation_compute_lambda.py` (EventBridge emit), new `chronicle_auto_draft_lambda.py`, EventBridge rule

---

### DISC-12: Social share cards

**Concept**: Each finding can generate a shareable card image. "My AI found that bedtime before 11pm predicts 12% higher HRV (r=0.52, 45 days). averagejoematt.com/discoveries"

**Implementation**: An on-demand Lambda that generates a PNG card via SVG → sharp/canvas. URL: `/api/share_card?pair=hrv_vs_recovery`. Open Graph meta tags on the discoveries page point to the latest featured finding's card.

**This is lower priority** — do after DISC-9 (SEO) since share cards matter more with an audience.

**Files changed**: New Lambda, OG meta tags on discoveries page

---

## Implementation Order

```
Session 1: DISC-1 (counterintuitive wiring) + DISC-2 (confidence threshold)
           → Deploy both Lambdas + S3 sync
           → Validate: page shows real counterintuitive findings or honest empty state

Session 2: DISC-3 (temporal metadata) + DISC-4 (mobile fix) + DISC-5 (disclaimer)
           → Deploy compute Lambda + site-api + S3 sync
           → Validate: featured card shows "confirmed 8 weeks" / "new this week"

Session 3: DISC-6 (timeline) + DISC-7 (behavioral response)
           → New API endpoint + S3 config + UI expansion
           → Validate: clicking a finding shows r-value over time + behavioral note

Session 4: DISC-8 (bidirectional links)
           → Config wiring + cross-page link rendering
           → Validate: Discoveries → Experiments → back works

Session 5: DISC-9 (SEO) + DISC-10 (email CTA)
           → Static render + subscribe enhancement
           → Validate: Google can index findings + subscribers tagged by interest

Session 6: DISC-11 (auto-chronicle) + DISC-12 (share cards)
           → EventBridge + new Lambdas
           → Validate: new finding triggers draft + share card renders
```

---

## Data Model Changes Summary

### `weekly_correlation_compute_lambda.py`

| Field | Type | New? | Description |
|-------|------|------|-------------|
| `expected_direction` | string | ✅ | Domain knowledge: "positive" or "negative" |
| `counterintuitive` | bool | ✅ | True when observed ≠ expected and |r| ≥ 0.2 |
| `first_detected` | string | ✅ | ISO week when this pair first appeared with consistent direction |
| `weeks_confirmed` | int | ✅ | Number of weeks this finding has held with same direction |
| `ever_fdr_significant` | bool | ✅ | Has this pair ever passed FDR in any week? |

### `site_api_lambda.py` — `/api/correlations` response

All fields above surfaced in the public response. Plus:
- `start_date` and `end_date` added to top-level response (already stored in DDB, just not surfaced)

### New endpoint: `/api/correlation_history?pair=<label>`

Returns weekly r-values over time for sparkline/timeline rendering.

### New S3 config: `config/discovery_annotations.json`

Matthew-authored annotations: behavioral response, linked experiment, linked chronicle entry per pair.

---

## Validation Checklist (per session)

- [ ] All dynamic sections render with real API data
- [ ] Empty/insufficient data states render gracefully
- [ ] Counterintuitive section shows only verified data or honest empty state
- [ ] Featured card never promotes weak/insignificant findings
- [ ] Mobile layout tested on 375px viewport
- [ ] N=1 disclaimer includes medical safety note
- [ ] No hardcoded data remains on the page
- [ ] Pipeline nav links all work
- [ ] Data Explorer link works
