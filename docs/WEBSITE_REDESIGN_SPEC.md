# WEBSITE REDESIGN IMPLEMENTATION SPEC

## averagejoematt.com — Panel Audit Results → Actionable Tasks

### Generated: March 22, 2026 | Updated: March 23, 2026

> **Source**: Page-by-page expert panel review (Mara Chen/UX, James Okafor/CTO, Sofia Herrera/CMO, Dr. Lena Johansson/Longevity, Raj Mehta/Product, Tyrell Washington/Design)
> **Usage**: Claude Code works through tasks by priority. Each page section is a standalone session.

---

## COMPLETION STATUS

### Phase 0: Data Fixes — ✅ COMPLETE (v3.8.8)
G-3 ✅, G-4 ✅, G-5 ✅ (confirmed working), G-7 ⚠️ (SES issue identified), G-8 ⬜ (pending email confirmation), STORY-1 ✅, PLAT-1 ✅, PROTO-1 ✅, CHRON-1 ✅ (navs already current), CHRON-2 ✅ (Week 1 published as Elena Voss entry)

### Phase 1: High-Impact Redesigns — ✅ MOSTLY COMPLETE (v3.8.8–v3.9.3)
- LIVE-2 ✅ (cockpit redesign deployed)
- ACCT-1 ✅ + ACCT-2 ✅ + ACCT-3 ✅ (state hero + nudge system + compact snapshot)
- SUPP-1 ✅ + SUPP-2 ✅ + SUPP-3 ✅ + SUPP-4 ✅ (full data-driven overhaul)
- HAB-1 ✅ + HAB-2 ✅ + HAB-3 ✅ (vice streaks + WHY cards + keystone correlations)
- STORY-3 ✅ (journey timeline), STORY-4 ✅ (emotional waveform), STORY-5 ✅ (intersection cards)
- HOME-4 ✅ (brief_excerpt), HOME-5 ✅ (what's new pulse)
- CHAR-4 ✅ (heatmap section), CHAR-5 ✅ (badge CSS)
- CHRON-5 ✅ (intro reframe), CHRON-6 ✅ (Week 1 published)
- EXP-2 ✅ (experiment depth fields)
- PLAT-3 ✅ (3-zone restructure)
- BOARD-1 ✅ (Huberman/Attia → fictional advisors)

### Nav Restructure — ✅ COMPLETE (v3.8.9)
All 44 HTML files updated. 5-section dropdown: The Story | The Data | The Science | The Build | Follow.

### Remaining from original spec:
- G-7: Subscribe SES verification (investigation only)
- G-8: Privacy email (needs Matthew confirmation)
- G-6: Bottom mobile nav (needs testing)
- HOME-2: 4-quadrant vital signs (panel recommended, not yet built)
- HOME-3: Day 1 vs Today 4 dimensions (partially done — weight + habits + sleep + level added)
- CHAR-1: Thesis opener (not confirmed shipped)
- CHAR-2: Interactive radar chart (not confirmed)
- CHAR-3: Tier journey path (not confirmed)
- CHAR-6: Calibrating state for low-data pillars (not confirmed)
- PLAT-2: Hero architecture diagram (not confirmed)
- CHRON-3: Chronicle generation workflow fix
- CHRON-4: Email preview/approval workflow
- PROTO-2: Active experiment badges on protocol cards
- PROTO-3: Habit + supplement links on protocol cards
- PROTO-4: Pipeline visualization (Protocols → Experiments → Discoveries)
- EXP-1: Elevate methodology section
- HAB-4: Decision fatigue signal
- BOARD-2: Technical/Web Board sub-pages

---

## NEW PAGES — Approved by Matthew (March 23, 2026)

### NEW-1: Data Explorer [P1] ⭐ MATTHEW APPROVED
- **Concept**: Interactive tool where visitors pick any two metrics and see correlation scatter plot
- **Example**: "Show me bedtime vs next-day HRV" or "protein intake vs weight change"
- **Data**: Pull from intelligence layer correlation data + raw daily snapshots
- **Community feature**: "Submit a finding" — visitor discovers an interesting correlation → submits to Matthew for review → if validated, promote to Discovery or seed an Experiment
- **Implementation**: `/api/correlations` endpoint returns available metric pairs. JS renders scatter plot with d3 or Chart.js. POST `/api/submit_finding` stores visitor submissions for review.
- **Files**: New `site/explorer/index.html` (directory exists), `lambdas/site_api_lambda.py`
- **Why it matters**: Stickiest page on the site — every metric combination is a new discovery. Visitors spend 10 minutes instead of 30 seconds.

### NEW-2: Weekly Snapshot / Periodical Report [P1] ⭐ MATTHEW APPROVED
- **Concept**: Auto-generated weekly report card — one page per week, walkable archive
- **Format per week**: Key numbers (weight, sleep, habits, character), AI narrative summary, notable events, heatmap strip, comparison vs prior week
- **Archive view**: Grid of all weeks showing arc of the journey. Weeks with no data are visible as gray/empty — that IS the story. "The weeks I'm not logging, that's the report in itself."
- **Commentary**: Elena Voss one-liner per week, or AI-generated snapshot summary
- **Navigation**: Next/prev week arrows, jump to any week
- **Implementation**: New `/api/weekly_snapshot?week=YYYY-Wnn` endpoint. Static page at `/snapshots/` or `/weekly/`. Could reuse Chronicle infrastructure or be separate.
- **Files**: New `site/weekly/index.html`, `lambdas/site_api_lambda.py`
- **Why it matters**: Lets visitors walk the entire journey chronologically. The empty weeks tell the story as much as the full ones.

### NEW-3: Milestones / Achievement Gallery [P1] ⭐ MATTHEW APPROVED
- **Concept**: Gamification badge wall with faded/locked badges that become full-color once achieved
- **Badge categories**:
  - **Weight**: 10-lb milestone badges (290, 280, 270... down to 185). Faded until hit.
  - **Journaling**: 15 entries/month badge, 30 entries/month badge
  - **Running/Walking**: Distance milestones (first 5K, 10K, half marathon)
  - **Streaks**: 7-day, 14-day, 30-day, 60-day, 90-day, 180-day, 365-day
  - **Character**: Level milestones (Level 5, 10, 15...), tier promotions
  - **Experiments**: First experiment completed, 5 experiments, 10 experiments
  - **Vice streaks**: 30 days clean per vice, 90 days, 180 days
  - **Data**: 100 days tracked, 200 days, 365 days
- **Visual**: Grid of circular badges. Locked = gray/faded with outline. Earned = full color with glow + earned date. Progress bar on locked badges showing % to unlock.
- **Implementation**: Badge definitions in S3 config (`config/achievement_badges.json`). `/api/achievements` endpoint computes status from DynamoDB data. Page renders dynamically.
- **Files**: Enhance existing `site/achievements/index.html` or rebuild, `lambdas/site_api_lambda.py`
- **Why it matters**: Audience can see what's achievable and root for specific badges. Creates return visits ("did he hit 270 yet?").

### NEW-4: Dark Mode / Light Mode Toggle [P2] ⭐ MATTHEW APPROVED
- **Concept**: Toggle in nav bar, persist via localStorage, default to dark
- **Implementation**: CSS custom properties already in tokens.css — add `:root[data-theme="light"]` overrides. Toggle button in nav. JS reads/writes `data-theme` attribute + localStorage.
- **Files**: `site/assets/css/tokens.css`, all page nav HTML (or global nav.js)
- **Why it matters**: Accessibility + readability for Chronicle/long-form content

---

## NEW PAGES — Backlog (Panel Recommended, Not Yet Approved)

### BACKLOG-1: "For Builders" Page [P2]
- Philosophy page for the builder/tech audience: how to build with AI as a non-engineer, patterns that work, what fails
- The page that gets shared in tech Slack channels and on HN

### BACKLOG-2: Bloodwork/Labs Page [P2]
- Biomarker tracking over time, optimal ranges (not just "normal"), linked to protocols/supplements
- Most medically credible page on the site

### BACKLOG-3: Body Composition Page [P2]
- DEXA scan comparisons, body fat % vs lean mass trajectory, visceral fat
- The story weight alone can't tell

### BACKLOG-4: Longevity Scorecard [P2]
- Centenarian decathlon benchmarks made visual — grip strength, dead hang, get-up-and-go
- Already have data via `get_centenarian_benchmarks` MCP tool

### BACKLOG-5: Choose Your Signal (Segmented Subscriptions) [P3]
- Let visitors pick which updates they want: sleep only, experiment alerts, weekly chronicle, etc.
- Dramatically increases engagement by matching content to interest

### BACKLOG-6: Monthly Retrospective [P3]
- One page per month: weight arc, character score trajectory, experiments completed, key discoveries
- How a new visitor catches up without reading 20+ weekly entries

### BACKLOG-7: System Status Page [P3]
- Which data sources reporting, last sync times, Lambda health, compute pipeline status
- Already have `/api/status` — needs a visual front-end

### BACKLOG-8: API Documentation Page [P3]
- Show the 20+ endpoint schema for the builder audience
- Recruiting signal + collaboration invitation

### BACKLOG-9: Mobile App Experience [P3]
- Fix bottom nav, add swipe gestures, make Live cockpit feel like native health app
- Significant perception upgrade for mobile visitors

---

## BACKEND CHANGES SUMMARY (Updated)

### site_api_lambda.py — completed:
1. ✅ `handle_vitals()` — last known weight + `weight_as_of`
2. ✅ `handle_journey()` — fixed progress calculation
3. ✅ `handle_supplements()` — full metadata from S3 config
4. ✅ `handle_vice_streaks()` — public vice streak data (content-filtered)
5. ✅ `handle_nudge()` — POST endpoint for anonymous nudges
6. ✅ `handle_journey_timeline()` — timeline events
7. ✅ `handle_journey_waveform()` — emotional waveform data
8. ✅ `handle_habits()` — enhanced with registry metadata + keystone correlations

### site_api_lambda.py — still needed:
1. `handle_weekly_snapshot()` — weekly report data [NEW-2]
2. `handle_correlations_explorer()` — interactive metric pair explorer [NEW-1]
3. `handle_submit_finding()` — POST for visitor-submitted correlations [NEW-1]
4. `handle_achievements_full()` — badge gallery with progress [NEW-3]

### New S3 config files needed:
1. `config/achievement_badges.json` — badge definitions, unlock criteria, categories [NEW-3]

---

## IMPLEMENTATION ORDER (Updated)

### Phase 0: Data Fixes — ✅ COMPLETE
### Phase 1: Major Redesigns — ✅ MOSTLY COMPLETE
### Phase 2: Remaining Enhancements
HOME-2, CHAR-1-3+6, CHRON-3-4, PROTO-2-4, EXP-1, HAB-4, PLAT-2, G-7, G-8

### Phase 3: New Pages (Matthew-approved)
1. NEW-3 (Milestones/Achievement Gallery) — most visual, gamification hook
2. NEW-2 (Weekly Snapshot) — periodical walkback, the empty weeks ARE the story
3. NEW-1 (Data Explorer) — stickiest interactive page, community feature
4. NEW-4 (Dark/Light mode) — quick CSS win

### Phase 4: Backlog
BACKLOG-1 through BACKLOG-9 as time/priority allows

---

## THROUGHLINE MAP

```
HOME (hook) ──→ STORY (origin) ──→ LIVE COCKPIT (hub)
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
              CHARACTER          HABITS+VICES         SUPPLEMENTS
              (am I better?)     (what I do)          (what I take)
                    │                   │                   │
                    ▼                   ▼                   ▼
              PROTOCOLS ────→ EXPERIMENTS ────→ DISCOVERIES
              (the strategy)  (what I test)   (what I learned)
                    │                   │                   │
                    ▼                   ▼                   ▼
              DATA EXPLORER ←──── MILESTONES ────→ WEEKLY SNAPSHOTS
              (play with data)  (gamification)    (walk the journey)
                                        │
                                        ▼
                                 ACCOUNTABILITY
                                 (the social contract + nudges)
                                        │
                                        ▼
                                    CHRONICLE
                                 (the ongoing narrative)
```
