# READER ENGAGEMENT — FULL IMPLEMENTATION PLAN
## Phases 1–4: From Frozen Museum to Living Platform
### Product Board + Extended Expert Panel · April 30, 2026

**Version:** 1.0  
**Platform baseline:** v3.9.41+  
**Design system:** Signal dark (`#0D1117` bg, `#E6EDF3` text, domain accent colors)  
**Observatory pattern:** 2-column editorial hero, gauge rings, pull-quotes with evidence badges, monospace section headers with trailing dash lines, 3-column editorial data spreads, left-accent rule cards  

---

**Room:**

**Product Board (8):** Mara Chen (UX), James Okafor (CTO), Tyrell Washington (Design), Sofia Herrera (CMO), Raj Mehta (Product Strategy), Jordan Kim (Growth), Ava Moreau (Content Strategy), Dr. Lena Johansson (Longevity Science)

**UX/UI Consultants (4):**
- **Tobias van Schneider** — former Spotify Lead Designer. Visual identity, brand systems, dark-mode mastery. Known for: design that feels alive without being busy.
- **Janum Trivedi** — Apple alumni, interaction design, micro-animations. Known for: physics-based transitions that feel inevitable, not decorative.
- **Claudio Guglieri** — former Microsoft Design Director, editorial web design at scale. Known for: content-first layouts that make dense data feel spacious.
- **Rasmus Andersson** — creator of Inter font, interface typography. Known for: type systems that scale from 10px labels to 80px heroes.

**Growth & Content Consultants (3):**
- **Lenny Rachitsky** (returning) — product/growth, retention loops
- **Casey Newton** (returning) — one-person media, reader journeys
- **Sahil Lavingia** (returning) — build-in-public audience mechanics

**Data Visualization Consultant (1):**
- **Nadieh Bremer** — data visualization artist, former Adyen. Known for: data art that is simultaneously beautiful and informative. Created visualizations for Scientific American, Google, UNESCO.

---

# TABLE OF CONTENTS

1. [Design Principles (Cross-Phase)](#design-principles)
2. [Phase 1: Make It Breathe](#phase-1)
3. [Phase 2: Guide the Explorer](#phase-2)
4. [Phase 3: The Weekly Arc](#phase-3)
5. [Phase 4: The Living Feed](#phase-4)
6. [API Specifications](#api-specifications)
7. [Component Library](#component-library)
8. [Measurement Framework](#measurement-framework)

---

<a name="design-principles"></a>
# DESIGN PRINCIPLES — CROSS-PHASE

### Tobias van Schneider opens:

*"Before we touch a single component, let me set the aesthetic rules. This site already has one of the strongest visual identities I've seen on a personal project — dark substrate, amber accents, monospace typography, editorial layouts. The mistake would be to introduce new patterns that dilute that. Every feature we add must feel like it was ALWAYS part of the design system. No new colors. No new fonts. No new layout paradigms. We extend the existing vocabulary."*

### The Five Rules

**Rule 1 — Recency is communicated through luminance, not color.**
New data glows brighter. Stale data dims. A metric updated 2 hours ago uses `color: var(--text)` (full brightness). A metric updated 3 days ago uses `color: var(--text-muted)`. A metric updated 7+ days ago uses `color: var(--text-faint)`. This creates a visual "heat map of freshness" across the site without introducing any new colors.

```css
/* Freshness luminance scale — add to design tokens */
--fresh-0h:   var(--text);          /* Updated within hours */
--fresh-1d:   var(--text);          /* Updated within 24h */
--fresh-3d:   var(--text-muted);    /* 1–3 days old */
--fresh-7d:   var(--text-faint);    /* 3–7 days old */
--fresh-stale: rgba(230,237,243,0.3); /* 7+ days — whisper gray */
```

**Rule 2 — Movement is vertical, never horizontal.**
All "what changed" content scrolls vertically. No carousels. No horizontal scroll regions. No sliding panels. The eye moves down the page. Trend arrows (↑↓→) are the only horizontal motion.

**Rule 3 — Every new component earns its space by replacing something, not adding to scroll depth.**
The homepage is already long. Phase 1–4 features must replace static content, not stack on top of it.

**Rule 4 — Monospace is for system voice. Serif (Lora) is for narrative voice.**
Platform-generated content (timestamps, metrics, system labels) uses `var(--font-mono)`. Human-written content (Chronicle excerpts, story quotes, Elena's voice) uses `var(--font-display)` (Lora). This typographic split IS the brand.

**Rule 5 — The accent color tells you which domain you're in.**
Sleep = Blue `#60a5fa`. Glucose = Teal `#2dd4bf`. Training = Red `#ef4444`. Nutrition = Amber `#f59e0b`. Mind = Violet `#818cf8`. Homepage = Amber (primary brand accent). This is already established — enforce it rigorously in all new components.

---

### Janum Trivedi — Animation Principles

*"Every animation on this site should feel like gravity — inevitable, not surprising. Here are the three animations we'll use across all four phases:"*

**Fade-up on enter** (existing `reveal` class — keep as-is):
```css
.reveal { opacity: 0; transform: translateY(20px); transition: opacity 0.6s ease, transform 0.6s ease; }
.reveal.visible { opacity: 1; transform: translateY(0); }
```

**Number count-up** (for metrics that change):
```javascript
function countUp(el, target, duration = 800) {
  const start = parseFloat(el.textContent) || 0;
  const range = target - start;
  const startTime = performance.now();
  function step(now) {
    const progress = Math.min((now - startTime) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
    el.textContent = (start + range * eased).toFixed(1);
    if (progress < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}
```

**Trend arrow pulse** (for metrics that moved since last visit):
```css
@keyframes trend-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
.trend-arrow--active { animation: trend-pulse 2s ease-in-out 3; } /* Pulses 3x then stops */
```

*"That's it. Three animations. No springs, no bounces, no parallax. This is a data platform, not a toy."*

---

### Rasmus Andersson — Typography Scale for New Components

*"You have Bebas Neue for display, Space Mono for system, and Lora for narrative. Here's how the new components use them:"*

| Component Type | Font | Size | Weight | Tracking |
|---------------|------|------|--------|----------|
| "Since your last visit" header | Space Mono | `var(--text-2xs)` (11px) | 400 | `0.15em` |
| Delta values (±1.4 lbs) | Bebas Neue | `var(--text-h4)` (24px) | 400 | `0.02em` |
| Freshness timestamp | Space Mono | 10px | 400 | `0.12em` |
| "This week" summary body | System (body stack) | `var(--text-sm)` (14px) | 400 | normal |
| Platform insight quote | Lora | `var(--text-base)` (16px) | 400 italic | normal |
| Guided path label | Space Mono | `var(--text-2xs)` | 400 | `0.15em` |
| Progress bar step names | Space Mono | 10px | 400 | `0.1em` |
| Weekly Recap headline | Bebas Neue | `clamp(32px, 4vw, 48px)` | 400 | `0.02em` |
| Pulse feed card title | Space Mono | `var(--text-xs)` (12px) | 400 | `0.1em` |
| Pulse feed card body | System (body stack) | `var(--text-sm)` | 400 | normal |

---

### Nadieh Bremer — Data Visualization Principles

*"I've reviewed the observatory pages. The editorial layouts are beautiful. The gauge rings are effective. But there's a missing layer: sparklines. Small, inline, wordless charts that show trajectory at a glance. These are the heartbeat of a living data platform."*

**Sparkline specification (reusable across all phases):**

```
Width: 80–120px inline, 200px in cards
Height: 24px (inline), 40px (card)
Stroke: 1.5px, domain accent color
Fill: gradient from accent at 15% opacity → transparent
No axes, no labels, no gridlines
Last point: a 4px circle in accent color
If trend is up: slight glow on last point (box-shadow: 0 0 4px accent)
If trend is flat/down: no glow
```

*"These appear anywhere a number appears. Weight doesn't just say '271.2' — it says '271.2' with a tiny 30-day downward sparkline next to it. HRV doesn't just say '67ms' — it has a 14-day sparkline showing the climb. The sparkline IS the trend arrow, but richer."*

**Implementation: SVG inline, generated from `public_stats.json` data or new API endpoint.**

```javascript
function sparkline(data, { width = 100, height = 24, color = 'var(--accent)' } = {}) {
  const min = Math.min(...data), max = Math.max(...data);
  const range = max - min || 1;
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((v - min) / range) * (height - 4) - 2;
    return `${x},${y}`;
  }).join(' ');
  const last = points.split(' ').pop();
  const [lx, ly] = last.split(',');
  const fillPoints = `0,${height} ${points} ${width},${height}`;
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" class="sparkline">
    <defs><linearGradient id="sf" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${color}" stop-opacity="0.15"/>
      <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
    </linearGradient></defs>
    <polygon points="${fillPoints}" fill="url(#sf)"/>
    <polyline points="${points}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    <circle cx="${lx}" cy="${ly}" r="2.5" fill="${color}"/>
  </svg>`;
}
```

---

### Claudio Guglieri — Layout Principles for New Sections

*"The observatory pages use a consistent editorial grid: `max-width: var(--max-width)` centered, with `var(--page-padding)` on sides. New components must sit inside this same grid. No full-bleed elements. No edge-to-edge cards. Everything breathes within the established column."*

*"For new card-based components (Pulse feed, What's New, This Week summaries), I recommend a pattern I call the 'ruled list' — no card backgrounds, no shadows, just content separated by 1px border lines. This matches the existing observatory aesthetic (thin borders, no boxes). Cards are rows, not rectangles."*

```css
.ruled-list__item {
  padding: var(--space-6) 0;
  border-bottom: 1px solid var(--border);
}
.ruled-list__item:first-child {
  border-top: 1px solid var(--border);
}
```

*"This is cheaper to render, easier to scan, and doesn't compete with the editorial pull-quotes and gauge rings that are the real visual stars."*

---

# ═══════════════════════════════════════════════════════════════════════
<a name="phase-1"></a>
# PHASE 1: MAKE IT BREATHE
## Observatory Heartbeat + "Since Your Last Visit" + Reading-Order Links
### Timeline: 1–2 weeks · Effort: Medium · Priority: P0
# ═══════════════════════════════════════════════════════════════════════

## 1A. OBSERVATORY HEARTBEAT

### Objective
Transform every observatory page from a static reference into a living document by adding four layers: freshness indicator, "this week" summary card, trend arrows with sparklines, and a platform insight callout. No structural redesign — additive layers only.

---

### Component 1A-1: Freshness Indicator

**Placement:** Top-right of observatory hero section, aligned with the section eyebrow line.

**Visual spec (Tobias):**
```
┌─────────────────────────────────────────────────────────────────┐
│  // SLEEP OBSERVATORY                                           │
│                                          Last data: 4h ago  ●  │
│  [Hero content as-is]                    Updated daily          │
└─────────────────────────────────────────────────────────────────┘
```

The green dot (`●`) uses the existing `.pulse` animation from the nav. The timestamp uses `--font-mono` at 10px, `--text-faint`, `letter-spacing: 0.12em`.

**Freshness logic:**
- < 6 hours: "Last data: Xh ago" + green pulse dot
- 6–24 hours: "Last data: today" + static green dot
- 1–3 days: "Last data: X days ago" + amber static dot (`--c-amber-500`)
- 3+ days: "Last data: Mar 24" + no dot, text at `--fresh-stale`

**CSS:**
```css
.obs-freshness {
  position: absolute;
  top: var(--space-4);
  right: var(--page-padding);
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-faint);
}
.obs-freshness__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--c-green-status);
}
.obs-freshness__dot--live {
  animation: pulse 2s ease-in-out infinite;
}
.obs-freshness__dot--amber {
  background: var(--c-amber-500);
  animation: none;
}
.obs-freshness__label {
  line-height: 1;
}
.obs-freshness__sub {
  display: block;
  margin-top: 2px;
  color: var(--text-faint);
  opacity: 0.6;
}
```

**HTML pattern:**
```html
<div class="obs-freshness reveal">
  <div>
    <span class="obs-freshness__label">Last data: <span id="obs-fresh-time">—</span></span>
    <span class="obs-freshness__sub">Updated daily</span>
  </div>
  <span class="obs-freshness__dot obs-freshness__dot--live" id="obs-fresh-dot"></span>
</div>
```

**Data source:** Each observatory already fetches from its API endpoint (`/api/sleep_detail`, `/api/glucose`, etc.). Add `"last_updated": "2026-04-30T06:15:00Z"` to each API response. The frontend calculates the relative time.

**Implementation steps:**
1. Add `last_updated` field to all 5 site-api observatory endpoints
2. Add `.obs-freshness` CSS to each observatory's `<style>` block (or to `observatory.css` if consolidated)
3. Add HTML element to each observatory hero (inside the existing hero `<header>` tag, positioned absolute)
4. Add JS to calculate relative time and set dot color

**Pages affected:** Sleep, Glucose, Nutrition, Training, Mind (5 pages)

---

### Component 1A-2: "This Week" Summary Card

**Placement:** New section inserted AFTER the observatory hero and BEFORE the first deep-data section (typically the 3-column editorial spread). This replaces nothing — it inserts into the gap between hero and content.

**Visual spec (Claudio + Tyrell):**

Claudio: *"This should be the 'ruled list' pattern — no card background. A thin top border, the content, a thin bottom border. It's a data shelf, not a card."*

Tyrell: *"Use the domain accent color for the section header dash line. The metrics inside use the freshness luminance scale. And each metric gets a Nadieh sparkline."*

```
────────────────────── THIS WEEK IN SLEEP ──────────────────────

  Average Duration          Best Night              Worst Night
  7.2 hrs ↑                 Tue · 8.1h · 92%        Fri · 5.4h
  [sparkline 7d]            Deep 24% · REM 26%      Late meal flagged
  vs 6.8 last week

  ▸ NOTABLE: REM % has increased 3 consecutive weeks

─────────────────────────────────────────────────────────────────
```

**CSS:**
```css
.obs-thisweek {
  max-width: var(--max-width);
  margin: 0 auto;
  padding: var(--space-8) var(--page-padding);
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}
.obs-thisweek__header {
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  color: var(--text-faint);
  letter-spacing: 0.15em;
  text-transform: uppercase;
  margin-bottom: var(--space-6);
  display: flex;
  align-items: center;
  gap: 12px;
}
.obs-thisweek__header::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border);
}
.obs-thisweek__grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0;
}
.obs-thisweek__col {
  padding: 0 var(--space-4);
}
.obs-thisweek__col:not(:last-child) {
  border-right: 1px solid var(--border);
}
.obs-thisweek__col:first-child {
  padding-left: 0;
}
.obs-thisweek__col:last-child {
  padding-right: 0;
}
.obs-thisweek__value {
  font-family: var(--font-display);
  font-size: clamp(28px, 3vw, 36px);
  line-height: 1;
  margin-bottom: var(--space-1);
}
.obs-thisweek__label {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: var(--space-3);
}
.obs-thisweek__detail {
  font-size: var(--text-sm);
  color: var(--text-faint);
  line-height: 1.6;
}
.obs-thisweek__delta {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-faint);
  margin-top: var(--space-2);
}
.obs-thisweek__notable {
  grid-column: 1 / -1;
  margin-top: var(--space-6);
  padding-top: var(--space-4);
  border-top: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.08em;
  color: var(--text-muted);
}
.obs-thisweek__notable strong {
  color: var(--accent); /* domain accent */
}

/* Mobile: stack columns */
@media (max-width: 640px) {
  .obs-thisweek__grid {
    grid-template-columns: 1fr;
  }
  .obs-thisweek__col {
    padding: var(--space-4) 0;
    border-right: none !important;
  }
  .obs-thisweek__col:not(:last-child) {
    border-bottom: 1px solid var(--border);
  }
}
```

**Data source:** New API endpoint `/api/observatory_week?domain=sleep` (see API Specifications section). Returns 7-day summary for each domain.

**Per-observatory "This Week" content:**

| Observatory | Col 1 | Col 2 | Col 3 | Notable Pattern |
|-------------|-------|-------|-------|-----------------|
| Sleep | Avg Duration + trend + sparkline | Best Night (day, hours, efficiency) | Worst Night (day, hours, flag) | Streak/trend (e.g., REM climbing) |
| Glucose | Avg TIR % + sparkline | Best Meal Response (food, spike) | Worst Meal Response (food, spike) | Pattern (e.g., morning fasting improving) |
| Nutrition | Avg Calories + protein % | Best Adherence Day | Worst Adherence Day | Pattern (e.g., protein target hit 6/7 days) |
| Training | Total Sessions + Volume | Best Session (type, strain) | Rest/Recovery Days | Pattern (e.g., Zone 2 streak) |
| Mind | Avg Mood Score + sparkline | Best Day (mood, journal excerpt) | Lowest Day (mood, trigger) | Pattern (e.g., meditation streak → mood correlation) |

**Implementation steps:**
1. Create `/api/observatory_week` endpoint in site-api Lambda (5 domain handlers)
2. Build `obs-thisweek` CSS component
3. Build JS template that populates the 3-column grid from API response
4. Insert HTML anchor point in all 5 observatory pages (after hero, before first content section)
5. Add `reveal` class for fade-in animation

---

### Component 1A-3: Trend Arrows with Sparklines

**Placement:** Inline next to every major metric that already appears on observatory pages — inside hero gauge rings, inside 3-column editorial spreads, inside rule cards.

**Visual spec (Nadieh + Rasmus):**

Nadieh: *"The sparkline sits right-aligned next to the metric value. The trend arrow sits between the value and the sparkline. This creates a three-part reading: NUMBER → DIRECTION → SHAPE."*

```
  67ms  ↑↑  [sparkline]
  HRV (14-day)
```

Rasmus: *"The trend arrows use a simple system: single arrow = slow movement (<5% change over period). Double arrow = fast movement (>5%). Color follows the domain accent for positive movement, `--text-faint` for negative. No red — we don't want alarm colors on a health site."*

**Trend arrow system:**
```
↑    — improving, slow (<5% change)
↑↑   — improving, fast (>5% change)
→    — flat (<1% change)
↓    — declining, slow
↓↓   — declining, fast
```

**CSS:**
```css
.trend-indicator {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}
.trend-indicator__arrow {
  font-family: var(--font-mono);
  font-size: 14px;
  line-height: 1;
}
.trend-indicator__arrow--up { color: var(--accent); }
.trend-indicator__arrow--down { color: var(--text-faint); }
.trend-indicator__arrow--flat { color: var(--text-faint); opacity: 0.5; }
.trend-indicator__spark {
  display: inline-block;
  vertical-align: middle;
}
```

**Data source:** Extend `public_stats.json` to include `trends` object with 7d and 30d arrays for key metrics. This feeds both sparklines and arrow direction.

**New fields in `public_stats.json`:**
```json
{
  "trends": {
    "weight_30d": [285.2, 284.8, 284.1, ...],
    "hrv_14d": [58, 61, 59, 63, 67, ...],
    "sleep_hours_7d": [7.1, 6.8, 7.4, 7.2, ...],
    "recovery_7d": [72, 68, 75, 80, ...],
    "habit_completion_7d": [0.85, 0.71, 0.92, ...],
    "glucose_tir_7d": [88, 91, 85, 90, ...]
  }
}
```

**Implementation steps:**
1. Extend `write_public_stats()` in `site_writer.py` to include `trends` arrays
2. Update `daily_brief_lambda.py` to pass trend data
3. Build `sparkline()` JS function (from Nadieh's spec above)
4. Build `trend-indicator` CSS component
5. Retrofit into existing observatory metric displays (gauge ring labels, 3-column editorial numbers)

---

### Component 1A-4: Platform Insight Callout

**Placement:** Bottom of each observatory page, after the last content section, before the cross-links and footer. One per page.

**Visual spec (Ava + Tobias):**

Ava: *"This is Elena's voice — the AI narrator — surfacing one observation per page. It should feel like a marginal note, not a headline. Italic Lora. Quiet. The kind of thing you notice on your third visit."*

Tobias: *"A thin left-border accent line. No background. No card. Just text in space, with a monospace attribution line below it."*

```
│  "Sleep efficiency has been above 85% for 14 consecutive days.
│   This is Matthew's longest streak since tracking began."
│
│  — Platform observation · April 28, 2026
```

**CSS:**
```css
.obs-insight {
  max-width: var(--max-width);
  margin: 0 auto;
  padding: var(--space-10) var(--page-padding);
}
.obs-insight__body {
  border-left: 2px solid var(--accent);
  padding-left: var(--space-6);
  max-width: 640px;
}
.obs-insight__text {
  font-family: var(--font-display); /* Lora */
  font-size: var(--text-base);
  font-style: italic;
  color: var(--text-muted);
  line-height: var(--lh-body);
  margin-bottom: var(--space-3);
}
.obs-insight__attr {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-faint);
}
```

**Data source:** New field in observatory API responses: `"platform_insight": { "text": "...", "generated_at": "..." }`. Generated daily by the intelligence layer (can reuse existing anomaly/correlation detection to pick the most interesting observation per domain).

**Implementation steps:**
1. Add insight generation to daily-brief or a new lightweight Lambda that writes per-domain insights to S3
2. Add `platform_insight` field to site-api observatory endpoints
3. Build `obs-insight` CSS component
4. Add HTML to all 5 observatory pages
5. If no insight available, section is hidden (`display: none`) — never show stale or placeholder text

---

## 1B. "SINCE YOUR LAST VISIT" — HOMEPAGE CARD

### Objective
For returning visitors, replace the static top portion of the homepage (below the hero, above the features) with a personalized delta summary showing what changed since their last visit.

---

### Mara Chen — UX Flow:

*"First visit: no localStorage, show the homepage as-is. Second visit: localStorage has a timestamp, fetch deltas, show the card. The card is dismissible (×) and re-shows on the next visit with a new timestamp."*

### Visual Spec (Tobias + Claudio + Tyrell):

Tobias: *"This is the single most important new visual element. It needs to feel urgent without being alarming. I want it to feel like opening a newspaper — 'here's what happened while you were away.' The format is a ruled list of deltas, not a card with a background."*

Claudio: *"It replaces the 'Day 1 vs Today' section for returning visitors. First-timers see Day 1 vs Today (which is about the journey's arc). Returners see 'Since Your Last Visit' (which is about the recent chapter). Same screen real estate, different content, different purpose."*

```
═══════════════════════════════════════════════════════════════

  // SINCE YOUR LAST VISIT · 6 DAYS AGO                  [×]

  WEIGHT         HRV            SLEEP          CHARACTER
  274.2→272.8    62→67ms        6.8→7.2h       71→74
  −1.4 lbs       ↑↑ climbing    ↑ improving    +3 pts
  [sparkline]    [sparkline]    [sparkline]    [sparkline]

  ▸ NEW: Experiment completed — Cold Exposure (30 days)
  ▸ NEW: Chronicle published — "The Week Everything Clicked"

  [Read the full weekly update →]

═══════════════════════════════════════════════════════════════
```

**CSS:**
```css
.since-last-visit {
  max-width: var(--max-width);
  margin: 0 auto;
  padding: var(--space-8) var(--page-padding);
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  position: relative;
}
.since-last-visit__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-6);
}
.since-last-visit__title {
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--text-faint);
}
.since-last-visit__dismiss {
  font-family: var(--font-mono);
  font-size: 14px;
  color: var(--text-faint);
  cursor: pointer;
  background: none;
  border: none;
  padding: var(--space-2);
  opacity: 0.5;
  transition: opacity var(--dur-fast);
}
.since-last-visit__dismiss:hover { opacity: 1; }
.since-last-visit__grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0;
  margin-bottom: var(--space-6);
}
.since-last-visit__metric {
  padding: 0 var(--space-4);
}
.since-last-visit__metric:not(:last-child) {
  border-right: 1px solid var(--border);
}
.since-last-visit__metric:first-child { padding-left: 0; }
.since-last-visit__metric:last-child { padding-right: 0; }
.since-last-visit__metric-label {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-faint);
  margin-bottom: var(--space-2);
}
.since-last-visit__metric-delta {
  font-family: var(--font-display);
  font-size: clamp(20px, 2.5vw, 28px);
  line-height: 1;
  margin-bottom: var(--space-1);
}
.since-last-visit__metric-change {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: var(--space-2);
}
.since-last-visit__events {
  border-top: 1px solid var(--border);
  padding-top: var(--space-4);
}
.since-last-visit__event {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--text-muted);
  padding: var(--space-1) 0;
}
.since-last-visit__event strong {
  color: var(--c-amber-500);
}
.since-last-visit__cta {
  display: inline-block;
  margin-top: var(--space-4);
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--c-amber-500);
  text-decoration: none;
  transition: color var(--dur-fast);
}
.since-last-visit__cta:hover { color: var(--c-amber-400); }

/* Mobile: 2x2 grid */
@media (max-width: 640px) {
  .since-last-visit__grid {
    grid-template-columns: repeat(2, 1fr);
    row-gap: var(--space-4);
  }
  .since-last-visit__metric:nth-child(2) { border-right: none; }
  .since-last-visit__metric:nth-child(3) { padding-left: 0; border-top: 1px solid var(--border); padding-top: var(--space-4); }
  .since-last-visit__metric:nth-child(4) { border-top: 1px solid var(--border); padding-top: var(--space-4); }
}
```

**JavaScript logic:**
```javascript
const LAST_VISIT_KEY = 'amj_last_visit';
const VISIT_DATA_KEY = 'amj_last_visit_data';

async function initSinceLastVisit() {
  const lastTs = localStorage.getItem(LAST_VISIT_KEY);
  if (!lastTs) {
    // First visit — record timestamp, show "Day 1 vs Today"
    localStorage.setItem(LAST_VISIT_KEY, Date.now().toString());
    return;
  }

  const daysSince = Math.floor((Date.now() - parseInt(lastTs)) / 86400000);
  if (daysSince < 1) return; // Visited today, skip

  try {
    const resp = await fetch(`/api/changes-since?ts=${Math.floor(parseInt(lastTs) / 1000)}`);
    if (!resp.ok) return;
    const data = await resp.json();
    renderSinceLastVisit(data, daysSince);
    // Hide "Day 1 vs Today" section
    document.querySelector('.day1-vs-today')?.style.setProperty('display', 'none');
  } catch (e) {
    console.warn('Changes-since unavailable:', e);
  }

  // Update timestamp for next visit
  localStorage.setItem(LAST_VISIT_KEY, Date.now().toString());
}
```

**API endpoint:** `/api/changes-since?ts=EPOCH` — see API Specifications section.

**Implementation steps:**
1. Build `/api/changes-since` endpoint in site-api Lambda
2. Build `since-last-visit` CSS component
3. Build JS initialization + rendering logic
4. Add container `<div>` to homepage HTML (inside existing layout, between hero and Day 1 vs Today)
5. Conditional display logic: first visit = Day 1 vs Today; return visit = Since Last Visit
6. Dismiss button hides for current session (sessionStorage), re-shows on next visit

---

## 1C. READING-ORDER LINKS

### Objective
Add a contextual "Next →" link at the bottom of 5 key pages, creating a linear reading path for new visitors.

### Visual Spec (Casey Newton's principle + Tyrell):

Casey: *"One door at the end of each hallway. Not two options. Not a footer with 12 links. ONE next step."*

Tyrell: *"This goes in the space between the last content section and the footer. It's a full-width strip — left-aligned text, right-aligned arrow. Domain accent color for the arrow."*

```
─────────────────────────────────────────────────────────────
  ← The Story                              See the live data →
    /story/                                           /live/
─────────────────────────────────────────────────────────────
```

**The Reading Path (ordered):**

| Current Page | ← Previous | Next → | Contextual Label |
|-------------|-----------|--------|------------------|
| Home `/` | — | The Story → | "Read the story behind the numbers" |
| Story `/story/` | ← Home | See Today's Data → | "See where the numbers are right now" |
| Live `/live/` | ← The Story | Explore Sleep → | "Go deeper on one domain" |
| Sleep `/sleep/` | ← Live Data | See How It Connects → | "See how everything scores together" |
| Character `/character/` | ← Sleep | Get the Weekly Update → | "Get this in your inbox every Wednesday" |
| Subscribe `/subscribe/` | ← Character | — | — |

**CSS:**
```css
.reading-path {
  max-width: var(--max-width);
  margin: 0 auto;
  padding: var(--space-8) var(--page-padding);
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1px solid var(--border);
}
.reading-path__prev,
.reading-path__next {
  text-decoration: none;
  transition: color var(--dur-fast);
}
.reading-path__prev {
  text-align: left;
}
.reading-path__next {
  text-align: right;
}
.reading-path__label {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-faint);
  display: block;
  margin-bottom: var(--space-1);
}
.reading-path__title {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  letter-spacing: 0.06em;
  color: var(--c-amber-500);
}
.reading-path__prev:hover .reading-path__title,
.reading-path__next:hover .reading-path__title {
  color: var(--c-amber-400);
}
```

**Implementation steps:**
1. Build `reading-path` CSS component
2. Add HTML to 6 pages (Home, Story, Live, Sleep, Character, Subscribe)
3. For first-visit users only (no localStorage timestamp): the "Next →" link gets a subtle pulse animation to draw attention
4. Sleep can be dynamically swapped for whichever observatory has the most interesting recent data (Phase 2 adds this heuristic)

---

## PHASE 1 — BACKEND REQUIREMENTS

### New/Modified API Endpoints:

| Endpoint | Method | Lambda | Description |
|----------|--------|--------|-------------|
| `/api/changes-since?ts=EPOCH` | GET | site-api | Returns notable changes since timestamp |
| `/api/observatory_week?domain=sleep` | GET | site-api | Returns 7-day summary for one domain |
| Extend existing observatory endpoints | — | site-api | Add `last_updated` and `platform_insight` fields |
| Extend `public_stats.json` | — | daily-brief → site_writer | Add `trends` object with sparkline arrays |

### Modified Files:

| File | Changes |
|------|---------|
| `lambdas/site_api_lambda.py` | New routes: `/api/changes-since`, `/api/observatory_week` |
| `lambdas/daily_brief_lambda.py` | Pass trend arrays to `write_public_stats()` |
| Shared layer `site_writer.py` | Extend `write_public_stats()` to include `trends` |
| `site/sleep/index.html` | Add freshness indicator, this-week card, insight callout, reading path |
| `site/glucose/index.html` | Same |
| `site/nutrition/index.html` | Same |
| `site/training/index.html` | Same |
| `site/mind/index.html` | Same |
| `site/index.html` | Add since-last-visit card, reading path |
| `site/story/index.html` | Add reading path |
| `site/character/index.html` | Add reading path |

### Phase 1 Delivery Checklist:

- [ ] `public_stats.json` extended with `trends` arrays
- [ ] `/api/changes-since` endpoint operational
- [ ] `/api/observatory_week` endpoint operational (5 domains)
- [ ] Observatory endpoints return `last_updated` and `platform_insight`
- [ ] Freshness indicator on all 5 observatories
- [ ] "This Week" summary card on all 5 observatories
- [ ] Sparkline + trend arrow JS utility function
- [ ] Trend arrows retrofitted into existing observatory metrics
- [ ] Platform insight callout on all 5 observatories
- [ ] "Since Your Last Visit" card on homepage (conditional on localStorage)
- [ ] Reading-order links on 6 pages
- [ ] Mobile responsive testing (all new components)
- [ ] CloudFront invalidation for all modified pages

---

# ═══════════════════════════════════════════════════════════════════════
<a name="phase-2"></a>
# PHASE 2: GUIDE THE EXPLORER
## First-Visit Guided Path with Progress Bar
### Timeline: 2–3 weeks after Phase 1 · Effort: Medium · Priority: P1
# ═══════════════════════════════════════════════════════════════════════

## Objective
Give first-time visitors a 5-stop guided tour through the site that tells a complete story (who → proof → depth → synthesis → subscribe) without ever feeling like a tutorial.

---

### Mara Chen — UX Rules:

*"Three constraints: (1) The path must be dismissible at any point. (2) It must not obscure any content. (3) It must feel like a recommendation, not an instruction. No modals. No overlays. No 'step 1 of 5' language. This is a reading order suggestion, not an onboarding wizard."*

---

### Component 2A: Progress Indicator Bar

**Placement:** Fixed to the top of the viewport, below the navigation bar. Thin (36px tall). Visible only to first-time visitors (no localStorage timestamp). Dismissible.

**Visual spec (Janum + Tobias):**

Janum: *"The bar doesn't animate in — it's just there when you arrive. It should feel like a table of contents, not a loading bar. Each stop is a word. The current stop is highlighted. Completed stops have a subtle checkmark."*

Tobias: *"Dark background matching the nav (`#0D1117` with a bottom border). The stops are spaced evenly. The current stop uses amber. Completed stops use `--text-muted`. Future stops use `--text-faint`."*

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ✓ Story    ● Live     ○ Sleep     ○ Character     ○ Subscribe    [×]  │
└─────────────────────────────────────────────────────────────────────────┘
```

**CSS:**
```css
.guided-path {
  position: sticky;
  top: 56px; /* below nav height */
  z-index: 99;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
  padding: 0 var(--page-padding);
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-6);
  transition: opacity 0.3s ease, transform 0.3s ease;
}
.guided-path--hidden {
  opacity: 0;
  transform: translateY(-100%);
  pointer-events: none;
}
.guided-path__step {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-faint);
  text-decoration: none;
  transition: color var(--dur-fast);
}
.guided-path__step--completed {
  color: var(--text-muted);
}
.guided-path__step--current {
  color: var(--c-amber-500);
}
.guided-path__step--current::before {
  content: '●';
  font-size: 6px;
}
.guided-path__step--completed::before {
  content: '✓';
  font-size: 10px;
}
.guided-path__step--future::before {
  content: '○';
  font-size: 6px;
  opacity: 0.5;
}
.guided-path__dismiss {
  position: absolute;
  right: var(--page-padding);
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-faint);
  cursor: pointer;
  background: none;
  border: none;
  opacity: 0.4;
  transition: opacity var(--dur-fast);
}
.guided-path__dismiss:hover { opacity: 1; }

/* Mobile: smaller text, tighter spacing */
@media (max-width: 640px) {
  .guided-path {
    gap: var(--space-3);
    overflow-x: auto;
    justify-content: flex-start;
    -webkit-overflow-scrolling: touch;
  }
  .guided-path__step { white-space: nowrap; }
}
```

**JavaScript:**
```javascript
const GUIDED_PATH_KEY = 'amj_guided_path';
const GUIDED_DISMISSED_KEY = 'amj_guided_dismissed';

const PATH_STEPS = [
  { id: 'story', label: 'Story', path: '/story/' },
  { id: 'live', label: 'Live', path: '/live/' },
  { id: 'sleep', label: 'Sleep', path: '/sleep/' },
  { id: 'character', label: 'Character', path: '/character/' },
  { id: 'subscribe', label: 'Subscribe', path: '/subscribe/' },
];

function initGuidedPath() {
  // Don't show if returning visitor or dismissed
  if (localStorage.getItem('amj_last_visit') && localStorage.getItem(GUIDED_PATH_KEY)) return;
  if (sessionStorage.getItem(GUIDED_DISMISSED_KEY)) return;

  const completed = JSON.parse(localStorage.getItem(GUIDED_PATH_KEY) || '[]');
  const currentPath = window.location.pathname;

  // Mark current page as completed
  const currentStep = PATH_STEPS.find(s => currentPath.startsWith(s.path) || (s.path === '/story/' && currentPath === '/'));
  if (currentStep && !completed.includes(currentStep.id)) {
    completed.push(currentStep.id);
    localStorage.setItem(GUIDED_PATH_KEY, JSON.stringify(completed));
  }

  // Find next uncompleted step
  const nextStep = PATH_STEPS.find(s => !completed.includes(s.id));

  renderProgressBar(completed, currentStep?.id, nextStep);
}
```

---

### Component 2B: Contextual Observatory Selection

**The problem:** Step 3 of the guided path is "one observatory." But which one?

**Raj Mehta's heuristic:**

*"Pick the observatory with the most dramatic recent data. 'Dramatic' = largest percentage change in any headline metric over 7 days. If sleep hours jumped 15% this week, show Sleep. If glucose TIR dropped 10%, show Glucose. The point is to show the visitor the most INTERESTING page, not the most complete one."*

**Implementation:**
```javascript
async function pickBestObservatory() {
  try {
    const resp = await fetch('/site/public_stats.json');
    const stats = await resp.json();
    const domains = [
      { id: 'sleep', path: '/sleep/', metric: stats.trends?.sleep_hours_7d },
      { id: 'glucose', path: '/glucose/', metric: stats.trends?.glucose_tir_7d },
      { id: 'training', path: '/training/', metric: stats.trends?.recovery_7d },
      { id: 'nutrition', path: '/nutrition/', metric: stats.trends?.habit_completion_7d },
      { id: 'mind', path: '/mind/', metric: null }, // fallback
    ];

    let best = domains[0];
    let maxVolatility = 0;

    for (const d of domains) {
      if (!d.metric || d.metric.length < 3) continue;
      const recent = d.metric.slice(-3);
      const older = d.metric.slice(0, 3);
      const recentAvg = recent.reduce((a, b) => a + b, 0) / recent.length;
      const olderAvg = older.reduce((a, b) => a + b, 0) / older.length;
      const volatility = Math.abs((recentAvg - olderAvg) / (olderAvg || 1));
      if (volatility > maxVolatility) {
        maxVolatility = volatility;
        best = d;
      }
    }

    return best;
  } catch {
    return { id: 'sleep', path: '/sleep/' }; // Default fallback
  }
}
```

The guided path's Step 3 label dynamically shows the chosen observatory name. If Sleep is picked: `○ Sleep`. If Glucose: `○ Glucose`.

---

### Component 2C: End-of-Path Subscribe CTA

**Placement:** On the Character page (Step 4), for visitors who are on the guided path, an enhanced subscribe CTA appears at the bottom — larger, more prominent, with a completion message.

**Visual spec (Jordan Kim + Sofia):**

Jordan: *"This is the conversion moment. The visitor has seen the story, the live data, one deep domain, and the synthesis. They understand the product. The CTA should acknowledge the journey."*

Sofia: *"Something like: 'You've seen the data. Every Wednesday, it moves. Subscribe to see where it goes.' That's more compelling than 'Enter your email.'"*

```
═══════════════════════════════════════════════════════════════

  // YOU'VE SEEN THE FULL PICTURE

  Every Wednesday, the numbers move.
  Subscribe to see where this goes.

  [email input]  [Follow the journey →]

  3-minute read. 19 data sources. Every failure included.

═══════════════════════════════════════════════════════════════
```

**Implementation:** Conditional rendering. If `localStorage.getItem(GUIDED_PATH_KEY)` includes 'story', 'live', and the chosen observatory, show the enhanced CTA on the Character page. Otherwise show the standard subscribe component.

---

## Phase 2 Delivery Checklist:

- [ ] Guided path progress bar component (CSS + JS)
- [ ] Path state management in localStorage
- [ ] Dismissal logic (sessionStorage for current session, localStorage for permanent)
- [ ] Contextual observatory selection heuristic
- [ ] Dynamic Step 3 label based on selected observatory
- [ ] Enhanced subscribe CTA on Character page (conditional)
- [ ] Reading-order links update to reflect guided path's dynamic observatory
- [ ] Mobile responsive testing (progress bar horizontal scroll)
- [ ] First-visit vs. return-visit conditional rendering verified
- [ ] Path completion tracking (for analytics: how many complete all 5 steps?)

---

# ═══════════════════════════════════════════════════════════════════════
<a name="phase-3"></a>
# PHASE 3: THE WEEKLY ARC
## Email as Chapter, Site as Book
### Timeline: 3–4 weeks after Phase 2 · Effort: Medium-High · Priority: P1
# ═══════════════════════════════════════════════════════════════════════

## Objective
Transform the Wednesday Chronicle from a standalone email into a weekly chapter that drives readers back to a rich, time-boxed landing page. Create a shareable weekly recap that works as both a subscriber destination and a viral landing page for forwarded links.

---

### Packy McCormick — Content Architecture:

*"The email should make you hungry, not full. Three insights, one chart description (no chart in email — emails can't render them well anyway), and a 'see the full week' link. The site is where the meal is."*

### Nate Silver — The Forecast Model:

*"Each weekly recap should end with a forward-looking statement: 'Here's what the model expects next week.' It doesn't have to be right — it has to be interesting. If it's wrong, that becomes the NEXT week's opening: 'Last week I predicted X. Here's what actually happened.' That's serial storytelling with data."*

---

### Component 3A: Weekly Recap Page (`/recap/` or `/week/`)

**URL structure:** `/recap/` (latest) and `/recap/week-12/` (archived)

**Page layout (Claudio + Tyrell + Nadieh):**

Claudio: *"This page should feel like a Sunday newspaper front page — a clear headline, a few data panels, one narrative section, and a 'read more' section pointing to observatories."*

Tyrell: *"Use the established observatory design language — monospace headers with dash lines, 3-column data spreads, pull-quotes. But the accent color is amber (this is a cross-domain page, not a single observatory)."*

**Page structure (top to bottom):**

```
1. HEADER
   // THE WEEKLY RECAP · WEEK 12 · APR 21–27, 2026
   "Down 1.4 lbs. HRV climbing. Zone 2 streak broke."
   [Bebas Neue headline, max 60 chars]

2. VITAL SIGNS DELTA — 4-column grid
   Weight    HRV      Sleep    Character
   -1.4 lbs  +5ms     +0.4h    +3 pts
   [spark]   [spark]   [spark]  [spark]

3. THE WEEK'S STORY — 2-column editorial
   Left: 300-word narrative (Elena voice, Lora italic)
   Right: Key data callouts in monospace cards

4. DOMAIN HIGHLIGHTS — 3-column
   Best sleep night    Glucose win        Training volume
   + link to obs       + link to obs      + link to obs

5. THE PLATFORM NOTICED — 2–3 insight callouts
   (Same obs-insight component from Phase 1, but multiple)

6. LOOKING AHEAD — Forward forecast
   "Next week the model expects..." (Nate Silver's pattern)

7. SHARE + SUBSCRIBE
   [Share this week] [Get this every Wednesday →]

8. ARCHIVE LINK
   ← Week 11 · Week 13 →
   [See all recaps →]
```

**Data source:** New Lambda (`weekly-recap-generator`) runs Wednesday alongside Chronicle. Compiles 7-day deltas, picks highlights, generates narrative via Claude API, writes to S3 as both JSON (for the page) and HTML (for the archive).

**Key design decisions:**

- **Nadieh** designs the vital signs delta section: *"Each metric gets a 7-day sparkline with the start and end points labeled. The visual should tell the story without reading a word — four mini-charts, each showing a trajectory. Use filled area under the line with gradient from domain color to transparent. The last point gets a circle and the delta number appears below."*

- **Tobias** on the share card: *"The share button generates a 1200×630 OG image dynamically. Template: dark background, week number, headline, the four sparklines, and the AMJ wordmark. This is what shows up when someone shares the link on Twitter/Reddit/LinkedIn."*

**Share card generation (Lambda-based):**
```
┌──────────────────────────────────────────────┐
│  THE WEEKLY RECAP · WEEK 12                  │
│                                              │
│  Down 1.4 lbs. HRV climbing.                │
│  Zone 2 streak broke.                        │
│                                              │
│  WEIGHT ─── HRV ─── SLEEP ─── SCORE         │
│  [spark]    [spark]  [spark]   [spark]       │
│  −1.4       +5ms     +0.4h    +3             │
│                                              │
│  averagejoematt.com                    AMJ   │
└──────────────────────────────────────────────┘
```

**Implementation steps:**

1. **New Lambda: `weekly-recap-generator`**
   - Runs Wednesday at 6:00 AM (EventBridge rule)
   - Queries DynamoDB for 7-day deltas across all domains
   - Calls Claude API for 300-word narrative (Elena voice)
   - Generates forward forecast statement
   - Writes `recap_data.json` and `recap_week_XX.html` to S3
   - Generates OG image (using Pillow/PIL or headless Chrome screenshot)

2. **New page template: `site/recap/index.html`**
   - Fetches latest `recap_data.json` from S3
   - Client-side rendering (same pattern as existing observatory pages)
   - Archive listing at `/recap/archive/`

3. **Chronicle email modification:**
   - Truncate to ~500 words (currently ~800–1200)
   - Add "See the full week →" CTA linking to `/recap/week-XX/`
   - Add "Share this with someone →" CTA with pre-composed share URL

4. **OG meta tags per recap:**
   ```html
   <meta property="og:title" content="The Weekly Recap — Week 12 | AMJ">
   <meta property="og:description" content="Down 1.4 lbs. HRV climbing. Zone 2 streak broke.">
   <meta property="og:image" content="https://averagejoematt.com/recap/og/week-12.png">
   ```

5. **Recap archive page:**
   - Chronological list of all weekly recaps
   - Each entry: week number, date range, headline, vital sign deltas
   - This IS the "follow the journey" page — reading recaps in order tells the full story

---

### Component 3B: Email Restructure

**Current Chronicle flow:** Full 800-word email → link to Chronicle archive page

**New Chronicle flow:**

```
FROM: The Weekly Signal <signal@averagejoematt.com>
SUBJECT: Week 12 — Down 1.4 lbs. HRV climbing.

─────────────────────────────────────────────

THE WEEKLY SIGNAL · WEEK 12

Three things that moved this week:

1. WEIGHT: 274.2 → 272.8 (−1.4 lbs, 7-week streak)
   The trend line stays clean. 30 lbs down from 302.

2. HRV: 62 → 67ms (↑↑ climbing fast)
   This is the highest 7-day average since tracking began.
   The platform credits consistent Zone 2 training.

3. ZONE 2 STREAK: Broken at 8 weeks.
   Thursday was a rest day that turned into two.
   The data shows recovery benefited — so was it a loss?

See the full week → averagejoematt.com/recap/week-12/

─────────────────────────────────────────────

Know someone who'd want this?
Forward this email — they can subscribe at
averagejoematt.com/subscribe

─────────────────────────────────────────────
averagejoematt.com · Unsubscribe
```

**Key changes:**
- Email is 250 words max (down from 800)
- Three numbered insights (scannable in 90 seconds)
- One CTA to the full recap page
- Forward prompt at bottom (referral loop)
- No inline charts — save those for the recap page

---

## Phase 3 Delivery Checklist:

- [ ] Weekly Recap page template (`site/recap/index.html`)
- [ ] Recap data JSON schema defined
- [ ] `weekly-recap-generator` Lambda written, tested, deployed
- [ ] EventBridge rule: Wednesday 6:00 AM PST
- [ ] Elena narrative generation via Claude API
- [ ] Forward forecast statement generation
- [ ] OG share image generation (Pillow or headless Chrome)
- [ ] OG meta tags per recap page
- [ ] Recap archive page (`/recap/archive/`)
- [ ] Chronicle email truncated to 250 words
- [ ] "See the full week →" CTA in Chronicle email
- [ ] "Forward this" prompt in Chronicle email
- [ ] Non-subscriber landing experience on recap page (subscribe CTA prominent)
- [ ] Navigation update: add "Recap" or "This Week" to appropriate nav tier
- [ ] Mobile responsive testing
- [ ] CloudFront invalidation strategy for weekly recap pages

---

# ═══════════════════════════════════════════════════════════════════════
<a name="phase-4"></a>
# PHASE 4: THE LIVING FEED
## The Pulse — Homepage Activity Stream
### Timeline: 6–8 weeks after launch · Effort: High · Priority: P2
# ═══════════════════════════════════════════════════════════════════════

## Objective
Replace the static homepage sections below the hero with a curated, chronological feed of platform activity — auto-generated from existing pipelines. The feed shows "what's happening on this platform" and updates daily.

---

### Ali Abdaal — Content Design:

*"This feed IS the product for returning visitors. It needs to satisfy in 30 seconds — scroll, see 3–5 items of interest, feel updated, leave. Think of it like a well-curated Instagram stories bar — each item is one moment, with a link to go deeper."*

### Sahil Lavingia — Serial Storytelling:

*"Every item in the feed should read like a chapter title. Not 'Weight updated' but 'Crossed below 270 for the first time.' Not 'New journal entry' but 'On deciding to add a fourth training day.' The editorial framing turns data events into story beats."*

---

### Component 4A: The Pulse Feed

**Placement:** Homepage, replacing the current "What's Inside" feature cards section (7 cards) and the "What the Data Found" correlation cards. Those sections move to `/platform/` and `/explorer/` respectively — they're platform information, not story.

**Visual spec (Claudio + Tobias + Ava):**

Claudio: *"Ruled list. No cards. Each item is a row with a left-aligned domain accent pip (colored dot), a monospace timestamp, a headline, and a one-line description. Optionally a sparkline for data-movement items."*

Tobias: *"The feed should have a gentle gradient fade at the bottom — 'there's more below' — rather than abrupt pagination. Load 10 items initially, lazy-load more on scroll."*

Ava: *"Every feed item needs an editorial headline written by the system, not a raw data label. The headline is what makes this a story, not a dashboard."*

**Feed item types and editorial treatment:**

| Event Type | Domain | Example Headline | Detail Line | Link |
|-----------|--------|-----------------|-------------|------|
| Weight milestone | Body | "Crossed below 270 — Day 52" | "That's 32 lbs from 302. Velocity: 2.1 lbs/week." | /live/ |
| Anomaly detected | varies | "HRV dropped 22% — overtraining flagged" | "Platform recommends a rest day. Recovery score: 48%." | /training/ |
| Experiment update | Science | "Cold exposure — Day 18 of 30" | "Morning protocol. HRV response: +8% vs baseline." | /experiments/ |
| Chronicle published | Story | "The Week Everything Clicked" | "Week 11 recap. Weight, sleep, habits all trending up." | /recap/week-11/ |
| Habit streak | Behavior | "Zone 2 training: 9-week streak" | "234 cumulative minutes this week. Target: 150." | /training/ |
| Observatory insight | varies | "Sleep architecture shift detected" | "REM % increased 3 consecutive weeks. Deep % stable." | /sleep/ |
| Experiment completed | Science | "30-day cold exposure — results in" | "HRV +11% vs baseline. Subjective: high. Continuing." | /experiments/ |
| Character level-up | Synthesis | "Character Score: 71 → 74" | "Sleep pillar improved. Training held. Mind stable." | /character/ |
| Decision journal | Story | "Changed protein to 200g after DEXA" | "Body composition scan showed lean mass preservation." | /nutrition/ |
| Weekly recap | Story | "Week 12 Recap available" | "Down 1.4 lbs. HRV climbing. Zone 2 streak broke." | /recap/week-12/ |

**CSS:**
```css
.pulse {
  max-width: var(--max-width);
  margin: 0 auto;
  padding: var(--space-8) var(--page-padding);
}
.pulse__header {
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--text-faint);
  margin-bottom: var(--space-6);
  display: flex;
  align-items: center;
  gap: 12px;
}
.pulse__header::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border);
}
.pulse__item {
  display: grid;
  grid-template-columns: 6px 80px 1fr auto;
  gap: var(--space-4);
  align-items: start;
  padding: var(--space-5) 0;
  border-bottom: 1px solid var(--border);
  text-decoration: none;
  transition: background var(--dur-fast);
}
.pulse__item:first-child {
  border-top: 1px solid var(--border);
}
.pulse__item:hover {
  background: rgba(255,255,255,0.02);
}
.pulse__pip {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-top: 6px;
}
.pulse__pip--body    { background: var(--c-amber-500); }
.pulse__pip--sleep   { background: #60a5fa; }
.pulse__pip--glucose { background: #2dd4bf; }
.pulse__pip--training { background: #ef4444; }
.pulse__pip--mind    { background: #818cf8; }
.pulse__pip--story   { background: var(--c-amber-500); }
.pulse__pip--science { background: #a78bfa; }
.pulse__time {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.1em;
  color: var(--text-faint);
  margin-top: 2px;
}
.pulse__content {}
.pulse__headline {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  letter-spacing: 0.04em;
  color: var(--text);
  margin-bottom: var(--space-1);
}
.pulse__detail {
  font-size: var(--text-sm);
  color: var(--text-muted);
  line-height: 1.5;
}
.pulse__spark {
  margin-top: 2px;
}
.pulse__fade {
  height: 60px;
  background: linear-gradient(to bottom, transparent, var(--bg));
  pointer-events: none;
  margin-top: calc(-1 * var(--space-8));
  position: relative;
  z-index: 1;
}
.pulse__load-more {
  text-align: center;
  padding: var(--space-4) 0;
}
.pulse__load-more button {
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--c-amber-500);
  background: none;
  border: 1px solid var(--border);
  padding: var(--space-2) var(--space-6);
  cursor: pointer;
  transition: border-color var(--dur-fast), color var(--dur-fast);
}
.pulse__load-more button:hover {
  border-color: var(--c-amber-500);
}

/* Mobile: collapse to 2 columns (hide time, full-width content) */
@media (max-width: 640px) {
  .pulse__item {
    grid-template-columns: 6px 1fr;
  }
  .pulse__time { display: none; }
  .pulse__spark { display: none; }
}
```

**Backend architecture:**

### New Lambda: `pulse-generator`

**Trigger:** Daily at 7:00 AM (after daily-brief completes)  
**Function:** Scans all event sources, compiles editorial headlines, writes `pulse_feed.json` to S3

**Event sources (all existing — no new data collection):**

| Source | Event Types | How to Detect |
|--------|------------|--------------|
| `public_stats.json` | Weight milestones, vital sign changes | Compare today vs yesterday, flag thresholds |
| DynamoDB `life-platform` | Experiment status changes, habit streaks, character score changes | Query by date range |
| Chronicle Lambda | New weekly recap published | Check for new S3 object in recap path |
| Intelligence layer | Anomalies, correlations, insights | Query daily-insight-compute output |
| Journal entries | New journal entry | Query by date |

**Editorial headline generation:**

The `pulse-generator` Lambda uses a template system with Claude API fallback:

```python
HEADLINE_TEMPLATES = {
    'weight_milestone': "Crossed below {weight} — Day {day}",
    'weight_update': "Weight: {weight} lbs ({direction} {delta})",
    'hrv_anomaly': "HRV {direction} {pct}% — {interpretation}",
    'streak_milestone': "{habit}: {weeks}-week streak",
    'experiment_update': "{name} — Day {day} of {total}",
    'experiment_complete': "{name} — results in",
    'character_change': "Character Score: {old} → {new}",
    'chronicle_published': "Week {num} Recap available",
}

# For events that need richer editorial framing:
def generate_editorial_headline(event):
    if event['type'] in SIMPLE_TYPES:
        return HEADLINE_TEMPLATES[event['type']].format(**event['data'])
    # Complex events get Claude-generated headlines
    return call_claude_for_headline(event)
```

**`pulse_feed.json` schema:**
```json
{
  "_meta": {
    "generated_at": "2026-04-30T07:00:00Z",
    "total_items": 47,
    "page_size": 10
  },
  "items": [
    {
      "id": "evt_20260430_001",
      "type": "weight_milestone",
      "domain": "body",
      "timestamp": "2026-04-30T06:15:00Z",
      "headline": "Crossed below 270 — Day 52",
      "detail": "That's 32 lbs from 302. Velocity: 2.1 lbs/week.",
      "link": "/live/",
      "sparkline_data": [285, 283, 281, 279, 276, 274, 272, 270],
      "priority": 1
    }
  ]
}
```

**Frontend: Infinite scroll with lazy loading:**
```javascript
let pulseOffset = 0;
const PULSE_PAGE_SIZE = 10;

async function loadPulse(append = false) {
  const resp = await fetch('/site/pulse_feed.json');
  const feed = await resp.json();
  const items = feed.items.slice(pulseOffset, pulseOffset + PULSE_PAGE_SIZE);
  const container = document.querySelector('.pulse__list');

  if (!append) container.innerHTML = '';

  for (const item of items) {
    container.insertAdjacentHTML('beforeend', renderPulseItem(item));
  }

  pulseOffset += PULSE_PAGE_SIZE;

  // Show/hide load more
  const loadMore = document.querySelector('.pulse__load-more');
  if (pulseOffset >= feed.items.length) {
    loadMore.style.display = 'none';
  }
}
```

---

### Component 4B: Pulse Governance — When NOT to Show the Feed

**Raj Mehta's rule:**

*"A feed with 3 items is worse than no feed. The minimum viable Pulse requires 8–10 items spanning at least 3 domains. If we can't fill that, don't ship it."*

**Minimum thresholds before activating The Pulse:**
- At least 30 days of daily data accumulation
- At least 2 completed experiments
- At least 4 weekly recaps published
- At least 10 unique event types represented

**Fallback:** If thresholds aren't met, the homepage continues to show the current static sections (What's Inside, What the Data Found) until the feed has enough content.

---

## Phase 4 Delivery Checklist:

- [ ] `pulse-generator` Lambda written, tested, deployed
- [ ] EventBridge rule: daily at 7:00 AM PST
- [ ] Event source scanning for all 5 sources
- [ ] Editorial headline template system
- [ ] Claude API integration for complex event headlines
- [ ] `pulse_feed.json` schema and S3 output
- [ ] Pulse feed frontend component (CSS + JS)
- [ ] Infinite scroll / lazy load implementation
- [ ] Domain accent pip colors
- [ ] Sparkline integration in feed items
- [ ] Mobile responsive layout
- [ ] Homepage section replacement (remove What's Inside, What the Data Found)
- [ ] Move displaced content to /platform/ and /explorer/
- [ ] Minimum content threshold check before activation
- [ ] Gradient fade at feed bottom
- [ ] "Load more" button
- [ ] CloudFront invalidation

---

# ═══════════════════════════════════════════════════════════════════════
<a name="api-specifications"></a>
# API SPECIFICATIONS
# ═══════════════════════════════════════════════════════════════════════

## New Endpoints (site-api Lambda)

### GET `/api/changes-since?ts=EPOCH`

**Phase:** 1  
**Purpose:** Returns notable changes since a given timestamp for the "Since Your Last Visit" homepage card.

**Query params:**
- `ts` (required): Unix timestamp (seconds)

**Response:**
```json
{
  "since": "2026-04-24T00:00:00Z",
  "days_ago": 6,
  "deltas": {
    "weight": { "from": 274.2, "to": 272.8, "change": -1.4, "unit": "lbs", "sparkline": [...] },
    "hrv": { "from": 62, "to": 67, "change": 5, "unit": "ms", "trend": "climbing", "sparkline": [...] },
    "sleep": { "from": 6.8, "to": 7.2, "change": 0.4, "unit": "hrs", "trend": "improving", "sparkline": [...] },
    "character": { "from": 71, "to": 74, "change": 3, "unit": "pts", "sparkline": [...] }
  },
  "events": [
    { "type": "experiment_complete", "title": "Cold Exposure (30 days)", "link": "/experiments/", "date": "2026-04-26" },
    { "type": "chronicle", "title": "The Week Everything Clicked", "link": "/recap/week-11/", "date": "2026-04-23" }
  ]
}
```

**Data sources:** DynamoDB queries for weight/HRV/sleep/character history, filtered by date range. Event detection from experiment status changes, new Chronicle publications.

**Implementation notes:**
- Cap the lookback to 30 days max (even if ts is older)
- Return max 5 events (most notable)
- Sparkline arrays: 7 data points, latest first
- If no changes (visitor returned same day): return empty `deltas` and `events`

---

### GET `/api/observatory_week?domain=sleep`

**Phase:** 1  
**Purpose:** Returns 7-day summary for a specific health domain, powering the "This Week" summary cards on observatory pages.

**Query params:**
- `domain` (required): `sleep` | `glucose` | `nutrition` | `training` | `mind`

**Response (example for sleep):**
```json
{
  "domain": "sleep",
  "period": { "start": "2026-04-21", "end": "2026-04-27" },
  "summary": {
    "primary": { "label": "Average Duration", "value": 7.2, "unit": "hrs", "delta": 0.4, "delta_label": "vs 6.8 last week", "trend": "up", "sparkline": [6.5, 7.0, 8.1, 6.9, 7.4, 7.0, 5.4] },
    "highlight": { "label": "Best Night", "value": "Tue · 8.1h · 92%", "detail": "Deep 24% · REM 26%" },
    "lowlight": { "label": "Worst Night", "value": "Fri · 5.4h", "detail": "Late meal flagged" }
  },
  "notable": "REM % has increased 3 consecutive weeks",
  "last_updated": "2026-04-27T06:15:00Z"
}
```

**Domain-specific response shapes:**

Each domain returns `summary.primary` (quantitative with sparkline), `summary.highlight` (best moment), `summary.lowlight` (worst moment), and `notable` (pattern observation).

---

### Extended `public_stats.json`

**Phase:** 1  
**New fields added to existing payload:**

```json
{
  "_meta": { ... },
  "vitals": { ... },
  "journey": { ... },
  "training": { ... },
  "platform": { ... },
  "trends": {
    "weight_30d": [285.2, 284.8, 284.1, 283.5, 282.9, ...],
    "hrv_14d": [58, 61, 59, 63, 67, 65, 68, ...],
    "sleep_hours_7d": [7.1, 6.8, 7.4, 7.2, 6.9, 7.0, 5.4],
    "recovery_7d": [72, 68, 75, 80, 77, 82, 65],
    "habit_completion_7d": [0.85, 0.71, 0.92, 0.88, 0.95, 0.79, 0.62],
    "glucose_tir_7d": [88, 91, 85, 90, 87, 92, 84],
    "character_score_7d": [71, 71, 72, 73, 73, 74, 74]
  }
}
```

**Modification:** `site_writer.py` → `write_public_stats()` accepts new `trends` parameter. `daily_brief_lambda.py` compiles arrays from DynamoDB daily snapshots.

---

# ═══════════════════════════════════════════════════════════════════════
<a name="component-library"></a>
# COMPONENT LIBRARY — REUSABLE ACROSS ALL PHASES
# ═══════════════════════════════════════════════════════════════════════

| Component | Used In | Type | Description |
|-----------|---------|------|-------------|
| `sparkline()` | Phase 1, 2, 3, 4 | JS function | Inline SVG sparkline generator |
| `countUp()` | Phase 1, 3 | JS function | Animated number counter |
| `.trend-indicator` | Phase 1, 3, 4 | CSS class | Arrow + sparkline combo |
| `.obs-freshness` | Phase 1 | CSS class | Freshness timestamp + pulse dot |
| `.obs-thisweek` | Phase 1 | CSS class | 3-column weekly summary card |
| `.obs-insight` | Phase 1, 3 | CSS class | Left-border platform insight callout |
| `.since-last-visit` | Phase 1 | CSS class | Homepage delta card for returning visitors |
| `.reading-path` | Phase 1, 2 | CSS class | Prev/Next navigation strip |
| `.guided-path` | Phase 2 | CSS class | Sticky progress bar for first visitors |
| `.pulse__item` | Phase 4 | CSS class | Feed item row |
| `.ruled-list__item` | Phase 1, 4 | CSS class | Borderless list row pattern |

**All components use existing CSS custom properties — no new tokens introduced.**

---

# ═══════════════════════════════════════════════════════════════════════
<a name="measurement-framework"></a>
# MEASUREMENT FRAMEWORK
# ═══════════════════════════════════════════════════════════════════════

### Jordan Kim + Lenny Rachitsky — What to Measure:

| Metric | How | Baseline | Phase 1 Target | Phase 2 Target | Phase 3 Target |
|--------|-----|----------|----------------|----------------|----------------|
| Return visit rate (14-day) | localStorage timestamp tracking | ~10% (estimated) | 25% | 30% | 40% |
| Pages per session (new visitors) | JS event tracking | ~2.3 | 3.0 | 4.5 | 4.5 |
| Pages per session (returning) | JS event tracking | ~1.5 | 3.0 | 3.5 | 4.0 |
| Subscribe conversion (Explorer) | Subscribe events / visitors with 3+ pages | ~8% | 10% | 15% | 15% |
| Email click-through rate | SES tracking | ~25% | 25% | 30% | 45% |
| Email forward rate | Forward tracking pixel | 0% | 0% | 0% | 5% |
| Guided path completion | localStorage tracking | n/a | n/a | 30% | 30% |
| Weekly recap page views | CloudFront logs | n/a | n/a | n/a | 2x subscriber count |
| Pulse scroll depth | Intersection Observer | n/a | n/a | n/a | 60% view 5+ items |

**Tracking implementation:** Lightweight JS events written to `localStorage` + optional beacon to a CloudFront log-only endpoint. No third-party analytics. No cookies beyond the visit timestamp. This aligns with the privacy-first positioning.

```javascript
// Minimal page view tracking
function trackPageView() {
  const views = JSON.parse(localStorage.getItem('amj_views') || '[]');
  views.push({ path: window.location.pathname, ts: Date.now() });
  // Keep last 100 views
  if (views.length > 100) views.splice(0, views.length - 100);
  localStorage.setItem('amj_views', JSON.stringify(views));
}
```

---

# INFRASTRUCTURE SUMMARY

### New Lambdas (2):

| Lambda | Phase | Trigger | Region |
|--------|-------|---------|--------|
| `weekly-recap-generator` | 3 | EventBridge: Wednesday 6:00 AM | us-west-2 |
| `pulse-generator` | 4 | EventBridge: Daily 7:00 AM | us-west-2 |

### Modified Lambdas (2):

| Lambda | Phase | Changes |
|--------|-------|---------|
| `daily-brief` | 1 | Pass trend arrays to `write_public_stats()` |
| `wednesday-chronicle` | 3 | Truncate email, add recap CTA, add forward prompt |

### Modified Shared Layer:

| File | Phase | Changes |
|------|-------|---------|
| `site_writer.py` | 1 | Extend `write_public_stats()` to accept + write `trends` |

### New Site-API Routes (2):

| Route | Phase |
|-------|-------|
| `/api/changes-since` | 1 |
| `/api/observatory_week` | 1 |

### New S3 Objects:

| Key | Phase | Generated By |
|-----|-------|-------------|
| `site/recap/data/week-XX.json` | 3 | weekly-recap-generator |
| `site/recap/og/week-XX.png` | 3 | weekly-recap-generator |
| `site/pulse_feed.json` | 4 | pulse-generator |

### New HTML Pages:

| Path | Phase |
|------|-------|
| `site/recap/index.html` | 3 |
| `site/recap/archive/index.html` | 3 |

### Modified HTML Pages (Phase 1):

All 5 observatories, homepage, story, live, character, subscribe (10 pages total)

---

# ESTIMATED COST IMPACT

| Phase | New Lambdas | Estimated Monthly Invocations | Estimated Monthly Cost |
|-------|-------------|-------------------------------|----------------------|
| 1 | 0 (site-api extensions) | +~3,000 (new endpoints) | < $0.10 |
| 2 | 0 (frontend only) | 0 | $0.00 |
| 3 | 1 (weekly-recap-generator) | ~4/month | < $0.50 (including Claude API for narrative) |
| 4 | 1 (pulse-generator) | ~30/month | < $0.25 |

**Total incremental monthly cost: < $1.00**

All phases leverage existing infrastructure. No new DynamoDB tables. No new CloudFront distributions. No new S3 buckets.

---

# TIMELINE SUMMARY

```
PHASE 1 — "Make It Breathe"              Week 1–2
├── Observatory heartbeat (5 pages)       Week 1
├── Since Your Last Visit (homepage)      Week 1–2
├── Reading-order links (6 pages)         Week 1
└── API endpoints + public_stats update   Week 1

PHASE 2 — "Guide the Explorer"           Week 3–5
├── Progress bar component                Week 3
├── Path state management                 Week 3
├── Observatory selection heuristic       Week 4
├── Enhanced subscribe CTA                Week 4
└── Testing + polish                      Week 5

PHASE 3 — "The Weekly Arc"               Week 6–9
├── Weekly Recap page template            Week 6
├── weekly-recap-generator Lambda         Week 6–7
├── OG share image generation             Week 7
├── Chronicle email restructure           Week 8
├── Recap archive page                    Week 8
└── Testing + polish                      Week 9

PHASE 4 — "The Living Feed"              Week 10–14
├── pulse-generator Lambda                Week 10–11
├── Editorial headline system             Week 11
├── Pulse feed frontend component         Week 12
├── Homepage section replacement          Week 13
├── Content threshold gate                Week 13
└── Testing + polish                      Week 14
```

---

*Plan approved by unanimous Product Board vote. Expert panel signs off. Ready for execution.*

*"The museum is about to get a heartbeat."* — Tobias van Schneider
