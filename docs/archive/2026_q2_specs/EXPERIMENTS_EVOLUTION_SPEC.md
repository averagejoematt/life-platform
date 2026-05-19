# EXPERIMENTS PAGE EVOLUTION — Implementation Spec

## "The Lab" → A Living Experiment Library

### Generated: March 24, 2026 | Product Board Session
### Author: Product Board (all 8 members) + Matthew

> **Vision**: Transform the Experiments page from a static lab notebook into a living experiment
> library with lifecycle management, community voting, evidence tiers, and achievement integration.
> Retain the scientific rigor and design quality of the current page while adding depth and stickiness.

---

## 1. CONCEPT OVERVIEW

### What changes

| Aspect | Current State | Evolution |
|--------|--------------|-----------|
| **Content** | 4 active supplement experiments | 50+ experiment ideas across all pillars |
| **Lifecycle** | Active → Completed/Abandoned | Backlog → Promoted → Active → Graded → Achievement |
| **Reader role** | Passive observer | Voter, follower, co-experimenter |
| **Data model** | DynamoDB EXP# records only | EXP# (active/completed) + S3 library config |
| **Page zones** | Header → Spotlight → Cards | Mission Control → Library Grid → The Record |
| **Pillar coverage** | Supplements only | Sleep, Movement, Nutrition, Mental, Social, Discipline, Supplements |

### What stays

- The H/P/D (Hypothesis/Protocol/Data) explainer — this is identity
- The N=1 methodology section — scientific credibility
- The pipeline nav (Protocols → Experiments → Discoveries)
- Card-level detail for active and completed experiments (hypothesis, metrics, outcome, delta chips)
- Filter system (All / Active / Completed / Abandoned)
- The "dark biopunk data terminal" aesthetic
- All existing CSS token usage

### Throughline connections

```
Protocols page → links "related experiments" from library
Library card   → "Promote" lifecycle → Active experiment
Active result  → Completed experiment → Discovery page
Completed exp  → Achievement badge unlock → Milestones page
Library vote   → Newsletter hook → Email subscriber capture
```

---

## 2. PAGE ARCHITECTURE — Three Zones

### Zone 1: Mission Control (top)

**Purpose**: Show what's running RIGHT NOW. The reason visitors come back.

**Layout**: 1–3 active experiment cards in a prominent hero section. Each card shows:

- Experiment name + hypothesis (one-liner)
- **Progress ring** — circular SVG, Day X of Y, fill animates on load
- **Compliance streak** — row of dots: ● (done) ○ (remaining) for daily-action experiments
- Duration tier badge: `7-DAY SPRINT` / `30-DAY TRIAL` / `60-DAY DEEP DIVE`
- Evidence tier indicator: `MEASURABLE` (has biomarker endpoint) or `BEHAVIORAL` (compliance-only)
- Primary metric + live delta vs baseline (if measurable)
- Tags (pillar chips)

**Visual treatment**: 
- Active card border uses animated gradient pulse (existing `--accent` green)
- Progress ring: SVG `<circle>` with stroke-dashoffset animation
- Streak dots: 8px circles, filled = `--accent`, unfilled = `--surface-raised`
- If zero active experiments, show a CTA: "Next experiment launching soon — vote below"

**Data source**: Existing `/api/experiments` endpoint (filter status=active)

### Zone 2: The Library (middle)

**Purpose**: The 50+ experiment ideas, browsable by pillar. The sticky part — visitors browse like a Netflix queue.

**Layout**: Pillar-grouped grid with collapsible sections.

**Section headers** (one per pillar):
```
┌─────────────────────────────────────────────────────────────┐
│ ◆ SLEEP & RECOVERY                          8 experiments   │
│   2 completed · 1 active · 5 in backlog                     │
└─────────────────────────────────────────────────────────────┘
```

**Library card (compact tile)** — each experiment idea:
```
┌────────────────────────────────────────┐
│  ☾  Post-Dinner Walk                   │
│  10 min walk after largest meal        │
│                                        │
│  ●●● Strong evidence                  │
│  ⏱ 30 days suggested                  │
│  📊 Fasting glucose, sleep score       │
│                                        │
│  [BACKLOG]           ▲ 24 votes        │
└────────────────────────────────────────┘
```

Each tile shows:
- **Icon**: Pillar-specific (moon for sleep, footprints for movement, etc. — CSS/SVG, no emoji in prod)
- **Name** + one-line description
- **Evidence rating**: ●●● Strong (multiple RCTs) / ●● Moderate (observational) / ● Emerging (preclinical/anecdotal)
- **Suggested duration**: 7 / 14 / 30 / 60 days
- **Metrics affected**: which data sources would track the outcome
- **Status badge**: `BACKLOG` (gray) / `PROMOTED` (amber pulse) / `ACTIVE` (green pulse) / `COMPLETED ✓` / `PARTIAL ~` / `FAILED ✗`
- **Vote count** + vote button (anonymous, cookie-rate-limited)
- **Research backing**: one-liner citation or "based on [Author, Year]"

**Lifecycle indicators on tiles**:
- **Backlog**: Muted/desaturated card. Full content visible but the card reads as "available."
- **Promoted** (Matthew committed, not yet started): Amber border pulse. "Starting [date]" label.
- **Active**: Green border pulse + "Day X" counter. Card links to Mission Control spotlight.
- **Completed**: Full-color card with grade badge (✓ / ~ / ✗) and one-line result.
- **Failed/Abandoned**: Desaturated card with "Shelved" label. Data preserved. Not hidden — failure is content.

**Filtering & sorting**:
- Pillar filter buttons across top (All / Sleep / Movement / Nutrition / Mental / Social / Discipline / Supplements)
- Sort: "Most voted" / "Recently active" / "Newest ideas"
- Search/filter by keyword (client-side, library is small enough)

**Grid layout**:
- Desktop: 3-column grid within each pillar section
- Tablet: 2-column
- Mobile: single column, pillar sections as accordion

### Zone 3: The Record (bottom)

**Purpose**: Completed and graded experiments with full detail. This is the existing card system, enhanced.

**Retains**: Current `exp-card` design with H/P/D detail, delta chips, mechanism/finding rows.

**Additions**:
- **Grade badge** on each card: `✓ COMPLETED` (green) / `~ PARTIAL` (amber) / `✗ FAILED` (muted)
  - Completed: Ran full duration, hypothesis evaluated
  - Partial: Did >50% of planned duration, some data collected
  - Failed: Abandoned early or compliance <50%
- **Achievement link**: If completing this experiment unlocked a milestone badge, show it inline
- **"What I'd do differently"** field — post-mortem reflection (optional, 1-2 sentences)
- **Duration actually completed** vs planned (e.g., "21 of 30 days")
- **Repeat indicator**: If this experiment was run more than once, show iteration count

**Filter buttons**: All / Completed / Partial / Failed (enhances existing All/Active/Completed/Abandoned)

---

## 3. EXPERIMENT LIBRARY — Seed Data

### S3 Config: `config/experiment_library.json`

This is the source of truth for the 50+ experiment ideas. Matthew curates this. Each entry:

```json
{
  "id": "post-dinner-walk",
  "name": "Post-Dinner Walk",
  "description": "Walk for 10 minutes after your largest meal each day",
  "pillar": "movement",
  "evidence_tier": "strong",
  "evidence_summary": "Multiple studies show post-meal walking reduces glucose spikes by 30-50%",
  "evidence_citation": "Buffey et al., Sports Medicine 2022",
  "suggested_duration_days": 30,
  "duration_tier": "30-day trial",
  "difficulty": "easy",
  "metrics_measurable": ["fasting_glucose", "cgm_spikes", "sleep_score"],
  "metrics_behavioral": ["compliance"],
  "experiment_type": "measurable",
  "hypothesis_template": "Walking 10 minutes after dinner for {duration} days will reduce post-meal glucose spikes by ≥20% vs baseline.",
  "protocol_template": "Walk for a minimum of 10 minutes within 30 minutes of finishing the largest meal. Track via Garmin/Strava. Measure glucose response via CGM on walk days vs non-walk baseline.",
  "why_it_matters": "The post-dinner walk is the most underrated intervention in metabolic health. Ten minutes. No gear. No app. Just gravity and glucose.",
  "tags": ["movement", "glucose", "metabolic", "beginner"],
  "related_protocols": ["metabolic-health"],
  "status": "backlog",
  "votes": 0,
  "promoted_date": null,
  "completed_runs": []
}
```

### Pillar categories and seed experiments

**SLEEP & RECOVERY** (8 ideas):
1. No screens 60 min before bed — Behavioral — ●● Moderate — 30 days
2. Fixed wake time ±15 min — Measurable (HRV, sleep score) — ●●● Strong — 30 days
3. Cold bedroom (65°F / Eight Sleep setting) — Measurable (deep sleep %) — ●●● Strong — 14 days
4. Morning sunlight within 30 min of waking — Measurable (sleep onset) — ●● Moderate — 30 days
5. Magnesium glycinate before bed — Measurable (deep sleep %) — ●● Moderate — 30 days
6. No caffeine after 12pm — Measurable (sleep latency, HRV) — ●●● Strong — 30 days
7. Consistent bedtime routine (same 3 steps) — Behavioral — ● Emerging — 30 days
8. Breathwork before sleep (4-7-8 pattern) — Measurable (HRV, sleep latency) — ●● Moderate — 14 days

**MOVEMENT & EXERCISE** (8 ideas):
1. Post-dinner walk 10 min — Measurable (glucose, sleep) — ●●● Strong — 30 days
2. Morning mobility routine (10 min) — Behavioral — ●● Moderate — 30 days
3. Zone 2 cardio 3x/week minimum — Measurable (RHR, HRV, VO2 trend) — ●●● Strong — 60 days
4. Daily step count ≥8,000 — Measurable (recovery, weight) — ●●● Strong — 30 days
5. Cold shower every morning (2 min) — Measurable (HRV, cortisol proxy) — ●● Moderate — 30 days
6. Grip strength training 3x/week — Measurable (grip test) — ●●● Strong — 60 days
7. Stretching before bed (10 min) — Measurable (sleep quality) — ● Emerging — 14 days
8. Active recovery day protocol (walk + mobility + sauna) — Behavioral — ●● Moderate — 30 days

**NUTRITION & METABOLIC** (8 ideas):
1. 40g protein at breakfast — Measurable (satiety, lean mass) — ●●● Strong — 30 days
2. 16:8 intermittent fasting — Measurable (glucose, weight) — ●●● Strong — 30 days
3. No alcohol for 30 days — Measurable (HRV, sleep, weight, glucose) — ●●● Strong — 30 days
4. Fiber target ≥30g/day — Measurable (glucose variability) — ●●● Strong — 30 days
5. Pre-meal vinegar (1 tbsp ACV) — Measurable (post-meal glucose) — ●● Moderate — 14 days
6. Vegetable volume loading (2 cups per meal) — Measurable (satiety, weight) — ●● Moderate — 30 days
7. Meal timing: largest meal at lunch — Measurable (glucose, sleep) — ●● Moderate — 30 days
8. Hydration target (bodyweight/2 in oz) — Behavioral — ● Emerging — 14 days

**SUPPLEMENTS & COMPOUNDS** (8 ideas — 4 already active):
1. ✅ Tongkat Ali — Recovery (ACTIVE, Day 44)
2. ✅ NMN — NAD+ (ACTIVE, Day 44)
3. ✅ Creatine — Strength (ACTIVE, Day 39)
4. ✅ Berberine — Glucose (ACTIVE, Day 44)
5. Ashwagandha — Cortisol/stress — Measurable (HRV, sleep) — ●●● Strong — 60 days
6. Omega-3 high-dose (3g EPA+DHA) — Measurable (inflammation markers, HRV) — ●●● Strong — 60 days
7. Vitamin D optimization (5000 IU) — Measurable (blood levels, mood) — ●●● Strong — 90 days
8. L-theanine for focus — Measurable (subjective + HRV) — ●● Moderate — 14 days

**MENTAL & COGNITIVE** (7 ideas):
1. Journaling before bed — Behavioral — ●● Moderate — 30 days
2. Reading 10 pages per day — Behavioral — ● Emerging — 30 days
3. Meditation 10 min daily (guided) — Measurable (HRV, stress) — ●●● Strong — 30 days
4. Gratitude log (3 items/day) — Behavioral — ●● Moderate — 30 days
5. No news/social media before 10am — Behavioral — ● Emerging — 14 days
6. Deep work block (2 hrs uninterrupted) — Behavioral — ●● Moderate — 30 days
7. Learning something new 15 min/day — Behavioral — ● Emerging — 30 days

**SOCIAL & CONNECTION** (6 ideas):
1. Date night per week — Behavioral — ●● Moderate — 60 days
2. Call a friend/family member weekly — Behavioral — ●● Moderate — 30 days
3. One meaningful conversation per day — Behavioral — ● Emerging — 30 days
4. Digital-free dinner (no phones at table) — Behavioral — ● Emerging — 14 days
5. Weekly letter/message to someone I appreciate — Behavioral — ● Emerging — 30 days
6. Community event once per month — Behavioral — ● Emerging — 90 days

**DISCIPLINE & HABITS** (7 ideas):
1. Make bed immediately on waking — Behavioral — ● Emerging — 30 days
2. Evening shutdown routine (same 5 steps) — Behavioral — ●● Moderate — 30 days
3. Single-tasking blocks (no tab switching) — Behavioral — ●● Moderate — 14 days
4. Vice elimination sprint (one vice, 30 days) — Measurable (vice streak) — ●● Moderate — 30 days
5. Breathing exercise 5 min (box breathing) — Measurable (HRV) — ●●● Strong — 14 days
6. Cold exposure + breathwork combo — Measurable (HRV, recovery) — ●● Moderate — 30 days
7. Track everything for 7 days (full compliance) — Behavioral — ● Emerging — 7 days

**Total: 52 experiment ideas** (4 already active as DynamoDB experiments)

---

## 4. DATA MODEL

### Existing: DynamoDB EXP# records (no changes needed)

```
pk: USER#{user_id}#SOURCE#experiments
sk: EXP#{slug}_{start_date}
```

Fields already in schema: name, hypothesis, start_date, end_date, status, tags, outcome,
primary_metric, baseline_value, result_value, metrics_tracked, planned_duration_days,
mechanism, key_finding, protocol, evidence_tier, hypothesis_confirmed.

**New fields to add to DynamoDB records** (when promoting from library):
- `library_id` — links back to the experiment_library.json entry
- `grade` — `completed` / `partial` / `failed` (replaces raw status for grading)
- `compliance_pct` — percentage of days the action was performed (0-100)
- `duration_tier` — `7-day sprint` / `30-day trial` / `60-day deep dive`
- `experiment_type` — `measurable` / `behavioral`
- `reflection` — "what I'd do differently" post-mortem (optional)
- `iteration` — which run of this experiment (1, 2, 3...)
- `achievement_unlocked` — badge ID if completing this unlocked an achievement

### New: S3 Library Config

**Path**: `s3://matthew-life-platform/config/experiment_library.json`

Array of experiment idea objects (schema shown in Section 3). This file is:
- Read by the site API Lambda at `/api/experiment_library`
- Editable by Matthew via Claude sessions (add/remove/reorder ideas)
- Cached by CloudFront (1 hour TTL)
- Not in DynamoDB — these are templates/ideas, not tracked experiments

### New: DynamoDB vote records

```
pk: USER#{user_id}#SOURCE#experiment_votes
sk: VOTE#{experiment_library_id}
```

Fields: `library_id`, `vote_count` (atomic counter), `last_voted` (timestamp).

Rate limiting: one vote per cookie per experiment per 24 hours (enforced client-side + API-side).

---

## 5. API ENDPOINTS

### Existing (no changes):

- `GET /api/experiments` — returns active/completed/abandoned experiments (DynamoDB)
- Already returns: evidence_tier, mechanism, key_finding, protocol fields

### New endpoints:

#### `GET /api/experiment_library`

Returns the full experiment library from S3 config, merged with vote counts from DynamoDB
and status from active experiments.

```json
{
  "pillars": [
    {
      "id": "sleep",
      "label": "Sleep & Recovery",
      "icon": "moon",
      "experiments": [
        {
          "id": "no-screens-before-bed",
          "name": "No Screens Before Bed",
          "description": "No screens 60 minutes before bed",
          "evidence_tier": "moderate",
          "evidence_summary": "Blue light suppresses melatonin...",
          "suggested_duration_days": 30,
          "duration_tier": "30-day trial",
          "difficulty": "medium",
          "experiment_type": "behavioral",
          "metrics_measurable": [],
          "metrics_behavioral": ["compliance"],
          "status": "backlog",
          "votes": 12,
          "why_it_matters": "...",
          "active_experiment_id": null,
          "completed_runs": [],
          "tags": ["sleep", "screens", "melatonin"]
        }
      ],
      "stats": { "total": 8, "active": 1, "completed": 2, "backlog": 5 }
    }
  ],
  "total_experiments": 52,
  "total_votes": 347
}
```

**Implementation**: Read `config/experiment_library.json` from S3 → merge vote counts from
DynamoDB scan → merge status from active experiments (match by `library_id` field) → group
by pillar → return.

**Cache**: 900s (15 min) — votes update, but not urgently.

#### `POST /api/experiment_vote`

Increment vote for a library experiment.

**Request**: `{ "library_id": "post-dinner-walk" }`
**Response**: `{ "library_id": "post-dinner-walk", "new_count": 25 }`

**Rate limiting**: Check `X-Forwarded-For` header + library_id. Store
`pk=VOTES, sk=IP#{ip}#LIB#{library_id}` with TTL of 86400. If exists, return 429.

**DynamoDB**: Atomic increment on vote record using `ADD vote_count :one`.

---

## 6. VISUAL DESIGN SPEC

### Design principles (Tyrell Washington)

- **Retain the biopunk terminal aesthetic** — dark surfaces, monospace accents, green signal color
- **The library grid should feel like a control panel**, not a blog post — compact tiles, information-dense
- **Active experiments are the visual hero** — progress rings, pulse animations, live counters
- **Evidence tiers use the existing dot pattern** from The Standards (●●● / ●● / ●)
- **Pillar colors** — each pillar gets a subtle tint for its section header, but cards stay neutral. No rainbow.

### Mission Control — active experiment card

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ┌──────────┐                                                           │
│ │          │  Tongkat Ali — Recovery Optimization         30-DAY TRIAL │
│ │  ●●●●●○  │  Hypothesis: 400mg daily will improve recovery ≥5pts     │
│ │  Day 44  │                                                           │
│ │  of 84   │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━░░░░░░░░░  52%      │
│ └──────────┘                                                           │
│                                                                        │
│  ● recovery_score  ● testosterone  ● cortisol    MEASURABLE  │ supps │ │
│                                                                        │
│  Baseline: 58 avg recovery  →  Current: 63 avg  →  Δ +5 pts ▲        │
└─────────────────────────────────────────────────────────────────────────┘
```

- Progress ring: SVG circle (80×80), `stroke-dasharray` based on % complete
- Compliance dots: inline flex, 8px circles, last 14 days visible (scrollable for longer)
- Duration tier badge: top-right corner, small pill
- Evidence tier badge: bottom-left, uses existing `metric-chip` styling
- Live delta: uses existing `exp-delta` positive/negative/neutral classes

### Library tile

```
┌────────────────────────────────┐
│  ☾                    ●●● STR │    <- pillar icon + evidence dots
│                               │
│  Post-Dinner Walk             │    <- name (font-display)
│  10 min after largest meal    │    <- description (font-mono, xs, muted)
│                               │
│  30 days · Easy               │    <- duration + difficulty
│  glucose · sleep              │    <- affected metrics (chips)
│                               │
│  ┌──────────┐   ▲ 24 votes   │    <- status badge + vote count
│  │ BACKLOG  │   [Vote]        │    <- vote button
│  └──────────┘                 │
└────────────────────────────────┘
```

- Card size: ~280px wide in 3-col grid
- Backlog: `border: 1px solid var(--border)`, card at full opacity but muted text
- Promoted: `border: 1px solid var(--c-amber-400)`, amber pulse animation
- Active: `border: 1px solid var(--accent)`, green pulse, links to Mission Control
- Completed: Grade badge overlay (✓ green, ~ amber, ✗ muted)
- Vote button: small, minimal — icon only (▲) with count. Filled when voted.

### Pillar section headers

Collapsible. Click to expand/collapse the grid below.

```css
.pillar-header {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-8);
  border: 1px solid var(--border);
  background: var(--surface);
  cursor: pointer;
}
.pillar-header__icon { /* SVG icon per pillar */ }
.pillar-header__name { font-family: var(--font-display); }
.pillar-header__stats { font-family: var(--font-mono); font-size: var(--text-2xs); }
```

### Status badge evolution

```css
.lib-status--backlog   { color: var(--text-muted); border-color: var(--border); }
.lib-status--promoted  { color: var(--c-amber-400); border-color: var(--c-amber-300);
                         animation: pulse-amber 2s ease-in-out infinite; }
.lib-status--active    { color: var(--accent); border-color: var(--accent-dim);
                         animation: pulse-green 2s ease-in-out infinite; }
.lib-status--completed { color: #2EA98F; border-color: rgba(46,169,143,0.3); }
.lib-status--partial   { color: var(--c-amber-400); border-color: var(--c-amber-300); }
.lib-status--failed    { color: var(--text-muted); border-color: var(--border);
                         opacity: 0.7; }
```

### Grade badges (The Record zone)

```
✓ COMPLETED    — green badge, solid border, full card color
~ PARTIAL      — amber badge, dashed border, slightly muted card  
✗ FAILED       — gray badge, dotted border, desaturated card (but NOT hidden)
```

---

## 7. COMMUNITY FEATURES

### Voting system

- **Anonymous**: No login required. Cookie-based dedup (1 vote per experiment per 24hrs).
- **Display**: Vote count shown on each library tile. Sorted by "Most Voted" as default.
- **Visibility**: Top 3 most-voted experiments get a "Community Pick 🔥" badge.
- **Matthew's commitment**: When Matthew promotes a community-voted experiment, the card shows
  "Community requested · 47 votes."

### Per-experiment follow

- "Get notified when this experiment completes" — one-click email subscribe per experiment.
- Uses existing SES infrastructure. Stores interest in DynamoDB:
  ```
  pk: SUBSCRIBERS
  sk: INTEREST#{email}#EXP#{library_id}
  ```
- When experiment completes, trigger targeted email to interested subscribers.
- **Phase 2** — not in initial build. Design the UI hook now (button placement), wire later.

### "Try It With Me" prompt

- On every active experiment card: "I'm running this now. Try it yourself — no app needed."
- On completed experiments: "Here's the protocol. Run your own 7-day version."
- **No infrastructure needed** — this is copy/CTA only. Links to protocol description.

---

## 8. ACHIEVEMENT INTEGRATION

### New achievement badges (add to `handle_achievements` in site_api_lambda.py):

```python
# Experiment achievements
badge("exp_3_completed", "Lab Rat", "science",
      "Completed 3 experiments", len(completed_exps) >= 3,
      unlock_hint="Complete 3 tracked experiments"),

badge("exp_5_completed", "Research Fellow", "science",
      "Completed 5 experiments", len(completed_exps) >= 5,
      unlock_hint="Complete 5 tracked experiments"),

badge("exp_10_completed", "Principal Investigator", "science",
      "Completed 10 experiments", len(completed_exps) >= 10,
      unlock_hint="Complete 10 tracked experiments"),

badge("exp_streak_3", "Hot Streak", "science",
      "3 consecutive completed experiments (no fails)", has_3_streak,
      unlock_hint="Complete 3 experiments in a row without abandoning"),

badge("exp_all_pillars", "Renaissance Man", "science",
      "Completed experiment in every pillar", all_pillars_covered,
      unlock_hint="Complete at least one experiment in each of the 7 pillars"),
```

### Experiment → Achievement flow

When an experiment completes:
1. `end_experiment` MCP tool records outcome + grade
2. Next `/api/achievements` call detects new completed count
3. If threshold crossed, badge unlocks with `earned_date`
4. Experiments page shows the badge inline on the completed card
5. Milestones page shows new badge in gallery

---

## 9. MCP TOOL CHANGES

### Existing tools (minor enhancements):

**`create_experiment`** — add optional params:
- `library_id` — link to experiment_library.json entry
- `duration_tier` — "7-day sprint" / "30-day trial" / "60-day deep dive"
- `experiment_type` — "measurable" / "behavioral"
- `planned_duration_days` — already exists, ensure it's populated from library suggestion

**`end_experiment`** — add optional params:
- `grade` — "completed" / "partial" / "failed" (default: infer from status + compliance)
- `compliance_pct` — 0-100
- `reflection` — "what I'd do differently"

**`list_experiments`** — add to response:
- `library_id`, `grade`, `compliance_pct`, `duration_tier`, `experiment_type`, `iteration`

### No new MCP tools needed for Phase 1
Library management is via S3 config file edits in Claude sessions. Voting is public API only.

---

## 10. IMPLEMENTATION TASKS

### Phase 1: Library Config + API (backend)

| ID | Task | Files | Estimate |
|----|------|-------|----------|
| EL-1 | Create `config/experiment_library.json` with 52 experiments | S3 config | 30 min |
| EL-2 | Add `handle_experiment_library()` endpoint to site_api_lambda.py | site_api_lambda.py | 45 min |
| EL-3 | Add `handle_experiment_vote()` POST endpoint | site_api_lambda.py | 30 min |
| EL-4 | Add vote DynamoDB records with TTL rate limiting | site_api_lambda.py | 20 min |
| EL-5 | Deploy site API Lambda | deploy script | 10 min |

### Phase 2: Frontend — Mission Control zone

| ID | Task | Files | Estimate |
|----|------|-------|----------|
| EL-6 | Redesign active experiment spotlight → progress ring + streak dots | experiments/index.html | 60 min |
| EL-7 | Add duration tier badges + evidence tier indicators | experiments/index.html | 20 min |
| EL-8 | Add live baseline delta display on active cards | experiments/index.html | 30 min |
| EL-9 | Handle 0-active state with CTA to library | experiments/index.html | 10 min |

### Phase 3: Frontend — Library zone

| ID | Task | Files | Estimate |
|----|------|-------|----------|
| EL-10 | Build pillar section headers (collapsible) | experiments/index.html | 30 min |
| EL-11 | Build library tile component (compact card) | experiments/index.html | 45 min |
| EL-12 | Implement vote button with cookie dedup + optimistic UI | experiments/index.html | 30 min |
| EL-13 | Pillar filter buttons + sort controls | experiments/index.html | 20 min |
| EL-14 | Status badge system (backlog/promoted/active/completed/failed) | experiments/index.html | 20 min |
| EL-15 | Responsive grid (3-col → 2-col → 1-col accordion) | experiments/index.html | 20 min |

### Phase 4: Frontend — Record zone enhancements

| ID | Task | Files | Estimate |
|----|------|-------|----------|
| EL-16 | Add grade badges (✓ / ~ / ✗) to completed experiment cards | experiments/index.html | 20 min |
| EL-17 | Add "what I'd do differently" reflection field | experiments/index.html | 10 min |
| EL-18 | Add achievement badge inline display | experiments/index.html | 15 min |
| EL-19 | Add compliance % bar on completed/partial cards | experiments/index.html | 15 min |
| EL-20 | Enhanced filter: All / Completed / Partial / Failed | experiments/index.html | 10 min |

### Phase 5: Achievement integration + polish

| ID | Task | Files | Estimate |
|----|------|-------|----------|
| EL-21 | Add 5 new experiment achievement badges to site API | site_api_lambda.py | 20 min |
| EL-22 | Update MCP create_experiment with library_id + tier fields | tools_lifestyle.py | 20 min |
| EL-23 | Update MCP end_experiment with grade + compliance fields | tools_lifestyle.py | 15 min |
| EL-24 | S3 deploy + CloudFront invalidation | deploy | 10 min |
| EL-25 | Update WEBSITE_REDESIGN_SPEC.md | docs | 10 min |
| EL-26 | Changelog + handover + git push | docs | 10 min |

### Phase 6: Future / Community (not in initial build)

| ID | Task | Notes |
|----|------|-------|
| EL-F1 | Per-experiment email subscribe | UI hook in Phase 3, wiring later |
| EL-F2 | Individual experiment pages (`/experiments/{slug}/`) | SEO play, one page per completed experiment |
| EL-F3 | Shareable og:image auto-generation per experiment | Needs Lambda@Edge or pre-compute |
| EL-F4 | "Try It With Me" co-experiment announcements | Newsletter integration |
| EL-F5 | Experiment repeat/iteration tracking | Run same experiment again with compare |

---

## 11. IMPLEMENTATION ORDER

**Recommended build sequence** (single session or split across 2):

```
Session A (Backend + Mission Control):
  EL-1 → EL-2 → EL-3 → EL-4 → EL-5 → EL-6 → EL-7 → EL-8 → EL-9

Session B (Library + Record + Polish):
  EL-10 → EL-11 → EL-12 → EL-13 → EL-14 → EL-15 →
  EL-16 → EL-17 → EL-18 → EL-19 → EL-20 →
  EL-21 → EL-22 → EL-23 → EL-24 → EL-25 → EL-26
```

**Total estimated effort**: ~8-10 hours of Claude session work.

---

## 12. PRODUCT BOARD SIGN-OFF

| Member | Verdict | Key condition |
|--------|---------|---------------|
| Mara Chen | ✓ Ship it | Library must collapse by default on mobile |
| James Okafor | ✓ Ship it | S3 config approach avoids DynamoDB schema bloat |
| Sofia Herrera | ✓ Ship it | Each completed experiment must be screenshot-shareable |
| Dr. Lena Johansson | ✓ Ship it | Evidence tiers MUST be visible — no burying the ratings |
| Raj Mehta | ✓ Ship it | Voting system is the retention unlock — don't defer it |
| Tyrell Washington | ✓ Ship it | Progress rings are the hero visual — nail the SVG |
| Jordan Kim | ✓ Ship it | Vote button must be frictionless (no modal, no login) |
| Ava Moreau | ✓ Ship it | Library "why it matters" copy is content pipeline fuel |

**Throughline check**: Can a visitor connect from any page to any other page through this? ✓ Yes — Library links to Protocols, Active links to Live Cockpit, Completed links to Discoveries + Milestones, Voting links to Subscribe.

---

*This spec lives at: `docs/EXPERIMENTS_EVOLUTION_SPEC.md`*
*Implementation tracked in: `docs/WEBSITE_REDESIGN_SPEC.md` (append to Phase 5)*
