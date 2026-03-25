# PULSE REDESIGN SPEC — `/live/` ("Today")

## averagejoematt.com — The Pulse: A Living Daily State

### Generated: March 25, 2026
### Status: Approved concept — ready for implementation

> **Source**: Product Board review session (March 25, 2026) — all 8 personas.
> Mara Chen (UX), James Okafor (CTO), Sofia Herrera (CMO), Dr. Lena Johansson (Longevity),
> Raj Mehta (Product), Tyrell Washington (Design), Jordan Kim (Growth), Ava Moreau (Content).
> **Supersedes**: LIVE-1, LIVE-2, LIVE-3 tasks in WEBSITE_REDESIGN_SPEC.md (cockpit layout).
> **Preserves**: All cockpit CSS/JS can remain as fallback; this spec layers on top.

---

## The Problem

The current Live page tries to do two jobs at once:

1. **The Pulse** — Am I having a good day or a bad day? Glanceable, emotional, instant.
2. **The Journey Dashboard** — How much weight have I lost total? Retrospective, achievement-oriented.

By doing both, it does neither well. 14 tiles of equal visual weight create a flat data grid. When data is stale (no logging for days/weeks), the page shows 14 dashes and "loading…" — it looks broken, not honest. And there's no visual language that lets a visitor read Matt's state in 2 seconds.

Matthew's own words: *"It seems a bit conflated between trying to be a dashboard of the program vs a realtime view that is more meant to give information of NOW. We are doing both and so doing neither great."*

---

## The Vision

**The Live page becomes "The Pulse" — a living daily state that communicates how Matt is doing through symbolism, color, and emotion, not just numbers.**

Core principles:
- **Symbolic, not literal.** Icons are metaphors (ember for inner fire, winding path for movement), not clip art (no literal dumbbells or footprints).
- **Color is the first language.** Green = good. Amber = mixed. Gray = no data. A visitor reads the color strip in 1 second before reading any text.
- **Gaps are data too.** A row of gray glyphs on a quiet day isn't broken — it's honest. "Two signals reporting. The rest is silence — and that's data too."
- **Mental health is equal.** Journal and state-of-mind glyphs sit alongside physical metrics. This isn't just a fitness tracker — it's a whole-person experiment.
- **Progressive disclosure.** Pulse headline → Glyph strip → Detail cards. Three layers, each deeper than the last.
- **Elena's voice.** The daily narrative is written in the Elena Voss journalist-narrator voice. Not a health app notification. Not a coach. A journalist following the story.

---

## Information Architecture: Three Layers

```
┌─────────────────────────────────────────────────────────┐
│  LAYER 1: THE PULSE HEADLINE                            │
│  Day 487 · Strong · "Weight dropped again. System       │
│  is humming."                                           │
│  (One color. One word. One sentence. 2-second read.)    │
├─────────────────────────────────────────────────────────┤
│  LAYER 2: THE GLYPH STRIP                               │
│  ○ Scale  ○ Water  ○ Move  ○ Lift  ○ Recovery           │
│  ○ Sleep  ○ Journal  ○ Mind                              │
│  (8 symbolic icons. Color-only status. No numbers.      │
│  Tap any glyph to expand its detail card below.)        │
├─────────────────────────────────────────────────────────┤
│  LAYER 3: DETAIL CARDS (on tap/click)                    │
│  Expanded detail for the selected glyph. Shows the      │
│  actual numbers, context, 7-day trend, and narrative.   │
│  Only one card open at a time, or show all on desktop.  │
└─────────────────────────────────────────────────────────┘
│                                                          │
│  SEPARATED: JOURNEY DASHBOARD (below fold or own page)  │
│  Weight timeline chart, total lost, journey progress,   │
│  life events. Important but different job.               │
└─────────────────────────────────────────────────────────┘
```

---

## Layer 1: The Pulse Headline

### Elements
- **Day counter** (large, prominent): "487" with "days" beneath. Left-aligned anchor. This number communicates commitment and duration — it should be the first thing you read.
- **Pulse dot**: Breathing animation. Color matches overall daily state.
- **Status word**: One of three — **Strong**, **Mixed**, or **Quiet**. Color-coded.
- **Narrative sentence**: 1-2 sentences in Elena Voss's voice. AI-generated daily by the brief pipeline. Pre-rendered into static HTML for SEO (Jordan Kim requirement).
- **Date**: "Tuesday, March 25, 2026" — grounds the visitor in time.
- **Navigation arrows**: "← Day 486" / "Day 488 →" to walk through daily states.

### Status Logic
| Status | Criteria | Color | Dot behavior |
|--------|----------|-------|-------------|
| **Strong** | ≥6 of 8 glyphs green | `#00e5a0` (accent green) | Steady slow breathe |
| **Mixed** | 3-5 glyphs green, or any red signals | `#f5a623` (amber) | Slightly faster breathe |
| **Quiet** | ≤2 glyphs reporting (rest gray) | `#3a5a48` (muted sage) | Very slow, barely visible |

### Narrative Generation Rules
- Written by the daily brief pipeline, stored in `public_stats.json` as `pulse_narrative`.
- Voice: Elena Voss — observational journalist, not a coach or health app. She reports on Matt's day like a war correspondent reports from the field.
- Strong day example: *"Weight dropped again this morning. Sleep was deep. Zone 2 on track. The system is humming."*
- Mixed day example: *"Slept under six hours. Recovery flagged amber. But he still hit the gym and logged his journal. Grit showing through the static."*
- Quiet day example: *"Two signals reporting. The rest is silence — and that's data too."*
- If no narrative available, show: *"Today's signal generates at 11 AM PT."*

---

## Layer 2: The Glyph Strip

### The 8 Signals

Each glyph is a symbolic SVG icon inside a responsive circular container. Color alone communicates status. No value labels on the glyph itself — labels are for Layer 3.

| # | Signal | Icon metaphor | Green | Amber | Red | Gray |
|---|--------|---------------|-------|-------|-----|------|
| 1 | **Scale** | Mountain descent — going down = descending toward the valley (goal). Going up = climbing back the wrong way. Flat = plateau ridgeline. | Lost weight | Gained ≤0.5 lbs | Gained >0.5 lbs | No weigh-in today |
| 2 | **Water** | Droplet that fills from bottom to top. Three internal level marks at 1L/2L/3L. Full droplet = target hit. | 3L hit | 2L+ | <1L | Not tracked |
| 3 | **Movement** | Winding path extending from a dot. Longer path = more movement. Path curves organically, not straight. Represents any intentional movement (walk, Zone 2, hike). | Steps ≥8k OR Zone 2 session | Steps 5-8k | Steps <5k, no activity | Not tracked |
| 4 | **Lift** | Rising pillar/column being built. Each training day adds a block. Rest day shows the column standing — still strong, just paused. Stack height reflects weekly volume. | Lifted today | Rest day (pillar stands) | 3+ rest days in a row | Not tracked |
| 5 | **Recovery** | Heartbeat/pulse line — the classic EKG wave. Amplitude and rhythm change with recovery score. Strong recovery = tall clean peaks. Low = shallow irregular. | Recovery ≥67% | Recovery 33-66% | Recovery <33% | No Whoop data |
| 6 | **Sleep** | Crescent moon with stars. Full bright moon + visible stars = deep restorative sleep. Dim moon + no stars = poor. Elegant, not cartoonish. | ≥7h, score ≥80 | 6-7h or score 60-80 | <6h or score <60 | Not tracked |
| 7 | **Journal** | Open book with visible written lines and an active pen. When not written: book is CLOSED (not just faded). Closed vs open is a stronger visual signal than opacity change. | Entry written today | — | — | Book closed, no entry |
| 8 | **Mind** | Flame/ember. Burns bright on good days (tall flame, warm glow). Dims to glowing coals on low days. Dark/cold when not tracked. The most human signal — inner fire. | Mood ≥4/5 | Mood 3/5 | Mood ≤2/5 | Not tracked |

### Glyph Container Behavior (Tyrell requirement)
The circular container ring itself responds to state:
- **Green**: Solid crisp ring, full opacity.
- **Amber**: Ring becomes slightly irregular/wavering (subtle SVG path distortion or dashed with longer segments).
- **Red**: Ring pulses subtly or uses a broken/gap pattern.
- **Gray**: Ring becomes dashed with wide gaps — incomplete, waiting for data.

### Interaction
- **Hover** (desktop): Glyph lifts slightly (`translateY(-2px)`), label appears below showing the key value.
- **Tap/click**: Opens that glyph's detail card in Layer 3. Only one card open at a time on mobile. Desktop can show all or selected.
- **No-data glyphs**: Tapping a gray glyph shows a gentle message: "No data yet today. This signal updates when [source] syncs."

---

## Layer 3: Detail Cards

Each glyph expands to a detail card containing:

| Element | Description |
|---------|-------------|
| **Metric name** | e.g., "Recovery" |
| **Primary value** | The headline number: "82%" |
| **Context** | What the number means: "Good — 7-day avg: 76%" |
| **Sub-metrics** | Supporting data: "HRV 54ms · RHR 58bpm" |
| **7-day sparkline** | Tiny inline trend line showing direction (pure CSS or inline SVG, not a full chart lib) |
| **Staleness label** | If data >24h old: "as of Mar 23" |

### Detail Card Definitions

**Scale**
- Primary: current weight in lbs
- Context: "-0.4 from yesterday" or "+0.2 from yesterday"
- Sub: "Journey: 302 → [current] → 185 · [X] lbs lost ([Y]%)"
- Sparkline: 7-day weight trend

**Water**
- Primary: "2.5 / 3L"
- Context: progress bar or fill level
- Sub: "7-day avg: 2.8L"
- Sparkline: 7-day hydration

**Movement**
- Primary: step count or "Zone 2: 42 min"
- Context: "8,240 steps" or activity type
- Sub: "Zone 2 this week: 87 / 150 min ([X]%)"
- Sparkline: 7-day steps or Zone 2 accumulation

**Lift**
- Primary: workout type — "Push day" / "Legs" / "Rest"
- Context: "Strain: 14.2 / 21"
- Sub: "This week: 3 sessions · [volume summary]"
- Sparkline: 7-day strain

**Recovery**
- Primary: recovery %
- Context: status label ("Optimal" / "Moderate" / "Needs rest")
- Sub: "HRV [X]ms · RHR [X]bpm · Resp [X]"
- Sparkline: 7-day recovery trend

**Sleep**
- Primary: hours slept
- Context: "Score: 84%"
- Sub: "Deep: 1.4h · REM: 1.8h · Consistency: [X]%"
- Sparkline: 7-day sleep duration

**Journal**
- Primary: "Written" or "Not yet"
- Context: streak count — "12-day streak" or "Last entry: Mar 22"
- Sub: theme/emotion tags from today's entry if available
- Sparkline: 14-day write/no-write binary strip (filled/empty dots)

**Mind**
- Primary: mood score X/5
- Context: mood label ("Good" / "Average" / "Low")
- Sub: state-of-mind notes if logged
- Sparkline: 7-day mood trend

---

## Journey Dashboard Separation

The weight timeline chart, journey progress percentage, total lbs lost, life events, and experiment bands currently on the Live page are **moved below the fold** under a clear section divider.

### Implementation Options (choose during build)

**Option A — Scroll section**: Keep on same page but below a prominent `<hr>` and section header: "The Journey So Far". Clearly separated from the Pulse. Lazy-loaded (chart only renders when scrolled into view).

**Option B — Separate page**: Move to `/story/` or `/journey/` as a dedicated historical view. The Pulse links to it: "View full journey timeline →".

**Recommendation**: Option A for launch (less routing work), with an anchor link from the Pulse headline area. Revisit after launch based on scroll depth analytics.

### What moves to the Journey section
- Weight timeline SVG chart (the full `render()` function)
- "302 → [current] → 185" header with meta stats (days, lbs lost, data points)
- Life events list
- Challenge bar (current weekly challenge)
- Legend

### What stays in the Pulse
- Everything in Layers 1-3

---

## API Changes

### New: `/api/pulse` — Composite Endpoint

A single endpoint returning everything the Pulse page needs in one call. Pre-computed by the daily pipeline and cached.

```json
{
  "pulse": {
    "day_number": 487,
    "date": "2026-03-25",
    "status": "strong",
    "status_color": "#00e5a0",
    "narrative": "Weight dropped again. Sleep was deep. The system is humming.",
    "signals_reporting": 7,
    "signals_total": 8,
    "glyphs": {
      "scale": {
        "state": "green",
        "direction": "down",
        "value": 278.4,
        "delta": -0.4,
        "delta_label": "-0.4 from yesterday",
        "journey_summary": "23.6 lbs lost (20.2%)",
        "sparkline_7d": [279.2, 279.0, 278.8, 279.1, 278.6, 278.8, 278.4],
        "as_of": "2026-03-25"
      },
      "water": {
        "state": "green",
        "liters": 3.0,
        "target": 3.0,
        "label": "3 / 3L",
        "sparkline_7d": [2.5, 3.0, 2.8, 3.0, 3.0, 2.2, 3.0],
        "as_of": "2026-03-25"
      },
      "movement": {
        "state": "green",
        "steps": 8240,
        "zone2_today_min": 0,
        "zone2_week_min": 87,
        "zone2_target": 150,
        "activity_type": null,
        "sparkline_7d": [7200, 9100, 6500, 8800, 10200, 5400, 8240],
        "as_of": "2026-03-25"
      },
      "lift": {
        "state": "green",
        "trained_today": true,
        "workout_type": "Push day",
        "strain": 14.2,
        "sessions_this_week": 3,
        "rest_day_streak": 0,
        "as_of": "2026-03-25"
      },
      "recovery": {
        "state": "green",
        "recovery_pct": 82,
        "status_label": "Optimal",
        "hrv_ms": 54,
        "rhr_bpm": 58,
        "resp_rate": 15.2,
        "sparkline_7d": [76, 71, 84, 68, 79, 88, 82],
        "as_of": "2026-03-25"
      },
      "sleep": {
        "state": "green",
        "hours": 7.2,
        "score": 84,
        "deep_hours": 1.4,
        "rem_hours": 1.8,
        "consistency_pct": 88,
        "sparkline_7d": [6.8, 7.5, 6.2, 7.0, 7.4, 6.9, 7.2],
        "as_of": "2026-03-25"
      },
      "journal": {
        "state": "green",
        "written_today": true,
        "streak_days": 12,
        "last_entry_date": "2026-03-25",
        "themes": ["focus", "energy"],
        "binary_14d": [1,1,1,1,0,1,1,1,1,1,0,0,1,1],
        "as_of": "2026-03-25"
      },
      "mind": {
        "state": "green",
        "score": 4,
        "max_score": 5,
        "label": "Good",
        "notes": null,
        "sparkline_7d": [3, 4, 3, 4, 5, 4, 4],
        "as_of": "2026-03-25"
      }
    },
    "generated_at": "2026-03-25T11:05:00Z"
  }
}
```

### Implementation Path

**Option A — Pre-compute (recommended)**:
- Daily brief Lambda computes the pulse object at ~11 AM PT (same time as daily brief).
- Writes to S3: `public/pulse.json` (alongside `public_stats.json`).
- CloudFront serves it with 300s TTL (same as vitals).
- The `/api/pulse` route in `site_api_lambda.py` reads from S3, not DynamoDB.
- Zero additional DynamoDB reads vs today (data already fetched by daily brief).

**Option B — Live compute**:
- New `handle_pulse()` in `site_api_lambda.py` aggregates from DynamoDB on each call.
- More real-time but higher cost and latency.
- Reserve for later if "live within 5 minutes" becomes a requirement.

### Existing Endpoints Retained
The current cockpit endpoints (`/api/vitals`, `/api/habit_streaks`, `/api/character`, `/api/glucose`, `/api/journey`) remain unchanged for backward compatibility and for other pages that use them. The Pulse page switches to `/api/pulse` (or `pulse.json`) as its sole data source.

---

## Historical Navigation

### `/api/pulse?date=2026-03-24`

Returns the pulse state for any previous date. Implementation:

- The daily brief Lambda already runs daily. Extend it to write each day's pulse object to DynamoDB: `PK=PULSE, SK=2026-03-25`.
- `/api/pulse?date=YYYY-MM-DD` reads the historical record.
- `/api/pulse` (no param) reads today's pre-computed S3 file.
- Enables "← Day 486 / Day 488 →" navigation on the page.
- Also enables the Weekly Snapshot page to pull 7 daily pulse objects per week.

### Permalink Support
`averagejoematt.com/live?date=2026-03-25` renders that day's pulse. OG meta tags dynamically reflect the date and status: "Day 487: Strong — March 25, 2026". This is the shareable URL (Sofia requirement).

---

## Share Card Generation

### Concept
A "Share today" button in the Pulse headline generates a 1200×630 social card image containing:
- Day number (large)
- Status word + color
- 8 glyph icons in their current color state
- The narrative one-liner
- averagejoematt.com branding

### Implementation Options

**Option A — Client-side canvas**: JS renders the card to a `<canvas>`, exports as PNG, triggers download or share sheet. No server needed. Works offline.

**Option B — Server-side OG image**: A Lambda generates the OG image dynamically for each date. Any URL like `/live?date=2026-03-25` automatically has correct OG tags and image. Better for link previews on Twitter/Slack/iMessage but requires a rendering Lambda (e.g., Puppeteer on Lambda or SVG-to-PNG via sharp).

**Recommendation**: Option A for MVP (zero infrastructure), with Option B queued for when social sharing becomes a measurable growth channel.

---

## SEO: Pre-rendered Narrative

The daily pipeline writes the pulse narrative and status directly into the static HTML of `/live/index.html` via a deploy-time or SSR-equivalent step.

### Approach
- Daily brief Lambda writes `pulse.json` to S3.
- A post-brief Lambda (or EventBridge-triggered step) reads `pulse.json` and writes a `<noscript>` block and `<meta>` description into the page's HTML in S3/CloudFront.
- Google sees: `<meta name="description" content="Day 487: Strong — Weight dropped again. Sleep was deep.">` in the raw HTML.
- This also populates OG tags dynamically for social link previews.

### Minimal Version
If the full SSR pipeline is too complex for MVP, at minimum:
- The `public_stats.json` file (already generated daily) includes the pulse narrative.
- The page's `<noscript>` block contains a static "Visit averagejoematt.com/live for today's pulse" message.
- OG meta tags reference a static default image until share card generation is built.

---

## Voice and Tone: Elena Voss Narrative Rules

All pulse narratives follow these guidelines:

1. **Third-person observational**: "He hit the gym despite 5 hours of sleep." Not "You hit the gym" or "I hit the gym."
2. **Short and punchy**: Max 2 sentences. No semicolons. No subordinate clauses longer than 8 words.
3. **Specific over generic**: "Weight dropped 0.4 lbs" not "Making progress." Include one concrete number.
4. **Honest about bad days**: "Recovery flagged red. He trained anyway — the data will judge whether that was courage or stubbornness." Never spin a bad day as secretly good.
5. **Quiet days are poetic, not apologetic**: "Two signals in. The rest is silence." Never "Sorry, no data today."
6. **No exclamation marks. Ever.**

---

## Implementation Tasks

### Phase A: API + Data Pipeline [Effort: M, ~3-4 hours]

| # | Task | Effort | Notes |
|---|------|--------|-------|
| PULSE-A1 | Add pulse computation to daily brief Lambda | M | Compute status, glyph states, narrative at brief generation time |
| PULSE-A2 | Write `pulse.json` to S3 `public/` prefix | S | Same pattern as `public_stats.json` |
| PULSE-A3 | Write daily pulse to DynamoDB (`PK=PULSE, SK=YYYY-MM-DD`) | S | Enables historical navigation |
| PULSE-A4 | Add `/api/pulse` route to `site_api_lambda.py` | S | Reads from S3 for today, DynamoDB for `?date=` param |
| PULSE-A5 | Add `/api/pulse` to CloudFront cache behaviors | XS | 300s TTL, same as vitals |

### Phase B: Glyph Design + Page Structure [Effort: L, ~6-8 hours]

| # | Task | Effort | Notes |
|---|------|--------|-------|
| PULSE-B1 | Design 8 SVG glyph icons (symbolic, not literal) | L | Mountain, droplet, path, pillar, heartbeat, moon, book, flame. Each needs 4 color states (green/amber/red/gray) + container ring variants. This is the creative centerpiece. |
| PULSE-B2 | Build Layer 1: Pulse headline (day counter, status word, narrative, date, nav arrows) | M | New HTML structure replacing cockpit status bar |
| PULSE-B3 | Build Layer 2: Glyph strip (8 icons in horizontal row, responsive) | M | Flexbox row, wraps on mobile. Color-only, no labels. |
| PULSE-B4 | Build Layer 3: Detail cards (tap-to-expand, contextual for each glyph) | M | 8 card templates. Sparklines as inline SVG. One open at a time on mobile. |
| PULSE-B5 | Wire all three layers to `/api/pulse` response | M | Single fetch, populate all elements. Progressive reveal as data loads. |
| PULSE-B6 | Implement historical navigation (← → arrows, URL param handling) | M | Fetch `/api/pulse?date=` for non-today dates. Update URL without page reload. |

### Phase C: Journey Dashboard Separation [Effort: M, ~2-3 hours]

| # | Task | Effort | Notes |
|---|------|--------|-------|
| PULSE-C1 | Move weight timeline chart below fold under "The Journey So Far" section divider | S | Clear visual break between Pulse and Journey |
| PULSE-C2 | Add lazy-loading to chart (IntersectionObserver) | S | Chart only renders when scrolled into view |
| PULSE-C3 | Add anchor link from Pulse area: "View full journey ↓" | XS | Links to `#journey` section |
| PULSE-C4 | Remove journey progress tile from glyph area (lives in Scale detail card now) | XS | Journey % moves to Scale detail sub-metrics |

### Phase D: Polish + Growth Features [Effort: M, ~3-4 hours]

| # | Task | Effort | Notes |
|---|------|--------|-------|
| PULSE-D1 | Loading states: skeleton shimmer on glyphs during fetch | S | Gray pulsing placeholder, not static dashes |
| PULSE-D2 | Animations: glyph icons fade/scale in on load, detail cards slide open | S | CSS transitions, no JS animation libraries |
| PULSE-D3 | Mobile responsiveness: glyph strip wraps to 2 rows of 4, detail cards full-width | S | Test on iPhone SE, iPhone 14, iPad |
| PULSE-D4 | Pre-render pulse narrative into HTML for SEO (noscript block + meta description) | M | Post-brief Lambda or build-time injection |
| PULSE-D5 | Share card: client-side canvas export of daily pulse state | M | 1200×630 PNG with day #, status, glyph colors, narrative |
| PULSE-D6 | OG meta tags: dynamic per-date descriptions | S | Update meta tags via JS on historical navigation |
| PULSE-D7 | "Strong/Mixed/Quiet" vocabulary integration with Weekly Snapshot page | S | Weekly Snapshot shows daily status distribution: "4 Strong, 2 Mixed, 1 Quiet" |

---

## Phasing and Priority

### Sprint 1: Foundation [PULSE-A1 through A5]
Get the data flowing. The `/api/pulse` endpoint is the prerequisite for everything else. Can be tested against the current page before any frontend ships.

**Validation**: `curl https://averagejoematt.com/api/pulse` returns valid JSON with all 8 glyph states.

### Sprint 2: The Redesign [PULSE-B1 through B6, PULSE-C1 through C4]
The visual transformation. This is the big sprint — new HTML structure, glyph SVGs, detail cards, journey separation. Ship as a single coordinated deploy.

**Validation**: Visit `/live/` and confirm:
- Layer 1 shows day number, status word, narrative, and date
- Layer 2 shows 8 glyphs with correct colors matching data state
- Tapping a glyph opens its detail card with real data
- Scrolling past the Pulse reaches the Journey section
- Historical navigation (← →) loads previous days
- Mobile layout is clean at 375px width

### Sprint 3: Growth [PULSE-D1 through D7]
Polish, SEO, shareability. These are enhancements that make the page performant and shareable, not functional blockers.

**Validation**: Share a link to `/live?date=2026-03-25` in Slack/Twitter — preview card shows day number and status. Google Search Console shows the daily narrative indexed.

---

## Total Estimated Effort

| Phase | Tasks | Effort |
|-------|-------|--------|
| A: API + Pipeline | 5 tasks | M (~3-4 hours) |
| B: Glyph Design + Page | 6 tasks | L (~6-8 hours) |
| C: Journey Separation | 4 tasks | M (~2-3 hours) |
| D: Polish + Growth | 7 tasks | M (~3-4 hours) |
| **Total** | **22 tasks** | **~15-19 hours across 4-5 sessions** |

---

## Design Reference: Glyph Icon Sketches

### 1. Scale (Mountain Descent)
```
    /\          ← peak (start weight: 302)
   /  \
  /    \
 /      \___   ← current position on the slope
              \
               · ← valley (goal: 185)
```
- Down day: path highlighted descending toward valley (green)
- Up day: path highlighted ascending back toward peak (amber/red)
- No data: mountain outline only, dashed (gray)

### 2. Water (Filling Droplet)
```
     .
    / \
   /   \
  |  ≈  |    ← water level rises with intake
  |  ≈  |
   \   /
    \_/
```
- Internal fill rises from 0L (empty) to 3L (full)
- Three subtle level marks inside at 1L, 2L, 3L
- Full: droplet fully colored. Partial: partially filled. Empty: outline only.

### 3. Movement (Winding Path)
```
  ·
   \
    ·—·
       \
        ·—·—·   ← longer path = more movement
```
- Path extends further on high-activity days
- Organic curves, not straight lines
- Gray: just the starting dot, no path

### 4. Lift (Rising Pillar)
```
  ┌──┐
  │  │ ← block added per training day
  ├──┤
  │  │
  ├──┤
  │  │
  └──┘
```
- 3-4 blocks visible representing weekly sessions
- Rest day: pillar stands, no new block, still green-ish (strength holds)
- Extended rest: pillar fades (amber after 3+ days)

### 5. Recovery (Pulse Line)
```
       _
  ____/ \    /\_____
          \/
```
- Strong recovery: tall clean peaks, regular rhythm
- Low recovery: shallow, irregular
- No data: flat line

### 6. Sleep (Crescent Moon)
```
     *
   ☽    *
     *
```
- Deep sleep: bright moon, multiple stars
- Poor sleep: dim moon, no stars
- No data: faint circle outline

### 7. Journal (Open/Closed Book)
```
  Written:          Not written:
  ┌──┬──┐           ┌──────┐
  │≡ │  │ ✎         │      │
  │≡ │  │           │      │
  │≡ │  │           └──────┘
  └──┴──┘
```
- Open book with spine, written lines on left page, pen active
- Closed book: single rectangle, no detail

### 8. Mind (Flame/Ember)
```
  Good:     Low:      Off:
    )
   (        .          .
   ()       ()
   ()       ()
```
- Tall flame with inner flicker on good days
- Dim coals/embers on low days
- Cold dark circle when not tracked

---

## Integration Points

### Weekly Snapshot (NEW-2)
The Weekly Snapshot page consumes 7 daily pulse objects to render its weekly view. Each day shows its glyph strip in miniature. The week summary uses Strong/Mixed/Quiet vocabulary: "This week: 4 Strong, 2 Mixed, 1 Quiet."

### Homepage
The homepage "What's New Pulse" section (HOME-5) can pull from `/api/pulse` to show today's glyph strip as a teaser widget with a "See full pulse →" CTA.

### Accountability Page
The accountability page can embed the glyph strip as a compact status bar showing Matt's current state to accountability partners.

### Brittany Weekly Email
The weekly email to Brittany can include a visual representation of the week's daily pulse states — 7 rows of colored dots.

### Tom's Buddy Page
`buddy.averagejoematt.com` can display today's pulse status as a compact widget.

---

## Files Affected

### New Files
- `site/live/index.html` — rewritten (preserves journey chart section)
- `site/assets/css/pulse.css` — new stylesheet for Pulse components
- `site/assets/js/pulse.js` — glyph rendering, detail card expansion, historical nav
- `site/assets/svg/glyphs/` — 8 SVG glyph files (or inline in JS)

### Modified Files
- `lambdas/daily_brief_lambda.py` — add pulse computation + S3 write + DynamoDB write
- `lambdas/site_api_lambda.py` — add `handle_pulse()` route
- `cdk/compute_stack.py` — add CloudFront cache behavior for `/api/pulse`
- `site/assets/js/components.js` — pulse widget component for embedding on other pages

### Config Files
- S3: `public/pulse.json` — daily pre-computed pulse state (new)
- DynamoDB: `PK=PULSE, SK=YYYY-MM-DD` — historical pulse records (new partition)

---

## Open Questions for Matthew

1. **Water tracking source**: Is hydration currently tracked in any data source (Apple Health, manual log, Habitify)? If not, this glyph starts as perpetually gray until a source is added. Could track via Habitify habit or a simple manual log tool.

2. **Movement vs Steps**: Steps come from Apple Health / Garmin. Should the Movement glyph factor in *only* step count, or should it also light up green for a Zone 2 session even if steps were low? (Board recommends: any intentional movement = green.)

3. **Mind/mood source**: Currently tracked via state-of-mind log. Is this logged daily or sporadically? If sporadic, this glyph will often be gray — which is fine and honest, but worth noting.

4. **Journal tracking**: Does Habitify have a "journaled today" habit, or should this glyph check for a Notion journal entry with today's date?

5. **Historical backfill**: Should the pipeline backfill pulse records for past dates (using existing DynamoDB data), or only start from deployment day forward? Backfill would immediately enable historical navigation across the full journey.

---

*This spec is designed to be executed in 3 sprints across 4-5 sessions. Sprint 1 (API) can be completed independently as a data-layer foundation. Sprint 2 (redesign) is the visual transformation. Sprint 3 (polish) adds growth features. The most important deliverable is not any single task — it's the glyph strip. Those 8 icons are the new visual language of the entire site.*
