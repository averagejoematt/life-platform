# The Ledger — Design Spec & Implementation Plan
## Feature: Achievement-Linked Charitable Giving + Snake Fund Discovery Page
**Status:** Pre-Implementation Review  
**Version:** 0.2 — expanded to include achievement badges + charity-grouped view  
**Date:** 2026-03-30  
**Platform Version Target:** v4.6.0

---

## 1. Concept Summary

Every meaningful thing that happens on the platform — an achievement earned, a challenge passed, a challenge failed, an experiment concluded — carries a financial stake that flows to the real world.

**Successes** → donation to a cause Matthew cares about  
**Failures** → donation to a cause Matthew doesn't care about (the snakes)

The page that tracks all of this is called **The Ledger**. It's accessible only via a footer link labeled **Snake Fund**. It has two views of the same data: a badge wall (what happened) and a charity ledger (where the money went).

---

## 2. Trigger Types

Three types of platform events can generate a ledger entry:

| Trigger Type | Success outcome | Failure outcome | Notes |
|---|---|---|---|
| **Achievement badge** | Bounty → earned cause | N/A | Achievements can only be *earned*, not failed. Weight milestones, streaks, etc. |
| **Challenge** | Bounty → earned cause | Punishment → reluctant cause | Pass/fail binary with a clear end date |
| **Experiment** | Bounty → earned cause | Punishment → reluctant cause | hypothesis_confirmed = true → bounty; false/abandoned → punishment |

Achievement badges are the only trigger type that can only generate bounties, never punishments. You can't "fail" hitting 280 lbs — you either hit it or you haven't yet.

---

## 3. Data Model

### 3.1 Three sources of ledger triggers

Each source type needs optional stake fields added (Option C — hybrid with global defaults):

**Achievement badges** — `config/achievement_badges.json` (existing S3 config)

Add optional fields per badge definition:
```json
{
  "id": "weight_280",
  "name": "280 Club",
  "category": "weight",
  "unlock_criteria": "weight_lbs <= 280",
  "bounty_usd": 50,
  "cause_id": "food_bank_seattle"
}
```
If `bounty_usd` absent → uses global default from `config/ledger.json`.  
If `cause_id` absent → uses `active_earned_cause` from `config/ledger.json`.  
No `punishment_usd` field — achievements cannot fail.

**Challenges** — `USER#matthew#SOURCE#challenges`, SK `CHALLENGE#<id>`

Add optional fields to DynamoDB record:
```
bounty_usd        number   (optional — falls back to global default)
punishment_usd    number   (optional — falls back to global default)
cause_id          string   (optional — falls back to active_earned_cause)
```
Punishment cause is always the global `active_reluctant_cause_id` — no per-challenge override.

**Experiments** — `USER#matthew#SOURCE#experiments`, SK `EXP#<id>`

Same three optional fields as challenges. Same fallback logic.

---

### 3.2 DynamoDB Partition: `SOURCE#ledger`

**PK:** `USER#matthew#SOURCE#ledger`

#### Transaction records

```
SK: LEDGER#<ISO-timestamp>

Fields:
  ledger_id         string    ISO timestamp (SK suffix)
  date              string    YYYY-MM-DD
  type              string    "bounty" | "punishment"
  amount_usd        number    Dollar amount
  cause_id          string    FK to earned_causes or reluctant_causes in ledger.json
  cause_name        string    Denormalized display name
  source_type       string    "achievement" | "challenge" | "experiment"
  source_id         string    ID of the trigger record
  source_name       string    Human-readable name ("280 Club", "30-Day Walk Challenge")
  source_badge_icon string    Emoji or icon key for badge display
  outcome           string    "earned" | "passed" | "failed" | "abandoned"
  notes             string    Optional context
  logged_at         string    ISO timestamp
```

#### Running totals record (updated on each transaction)

```
SK: TOTALS#current

Fields:
  total_donated_usd         number    All-time total
  total_bounties_usd        number    Earned through success
  total_punishments_usd     number    Earned through failure
  bounty_count              number    Success count
  punishment_count          number    Failure count
  by_cause                  map       { cause_id: { amount_usd, count, transactions: [...] } }
  last_updated              string    ISO timestamp
```

The `by_cause` map is the key addition — it enables the charity-grouped view without querying all transaction records. Each cause entry includes a `transactions` list of `{ date, source_name, source_type, amount_usd, outcome }` for display on the charity badge.

---

### 3.3 S3 Config: `config/ledger.json`

```json
{
  "settings": {
    "default_bounty_usd": 50,
    "default_punishment_usd": 75,
    "show_amounts_on_source_badges": false,
    "active_earned_cause": "food_bank_seattle",
    "active_reluctant_cause_id": "snake_sanctuary"
  },
  "earned_causes": [
    {
      "id": "food_bank_seattle",
      "name": "Northwest Harvest",
      "short_description": "Pacific NW food bank",
      "url": "https://www.northwestharvest.org",
      "category": "food_security",
      "badge_color": "teal",
      "logo_s3_key": "assets/ledger/logos/northwest_harvest.png",
      "why_i_care": "Food insecurity in my backyard."
    }
  ],
  "reluctant_causes": [
    {
      "id": "snake_sanctuary",
      "name": "American Reptile Rescue",
      "short_description": "Snake and reptile sanctuary",
      "url": "https://example.org",
      "badge_color": "gray",
      "joke_note": "I have funded this organization more than I care to admit.",
      "is_active": true,
      "logo_s3_key": "assets/ledger/logos/snake.png"
    }
  ]
}
```

---

## 4. Stake Resolution Logic (MCP tool behavior)

When `log_ledger_entry` is called:

```
1. Accept: source_type, source_id, outcome, optional notes
2. Fetch the source record from DynamoDB (challenge / experiment)
   OR fetch the badge definition from achievement_badges.json (achievement)
3. Resolve bounty_usd:
   - If record has bounty_usd → use it
   - Else → use settings.default_bounty_usd from ledger.json
4. Resolve punishment_usd (challenges/experiments only):
   - If record has punishment_usd → use it
   - Else → use settings.default_punishment_usd from ledger.json
5. Resolve cause_id:
   - If outcome is failure → always use active_reluctant_cause_id (no override)
   - If outcome is success/earned:
     - If record has cause_id → use it
     - Else → use settings.active_earned_cause from ledger.json
6. Write transaction record to SOURCE#ledger
7. Update TOTALS#current (atomic update to by_cause map + running totals)
```

Matthew never specifies amounts when logging an outcome. He just says:
`log_ledger_entry("challenge", "30_day_walk", "passed")` — everything else resolves automatically.

---

## 5. Page Design: The Ledger (`/ledger/index.html`)

### 5.1 Page Structure Overview

```
─────────────────────────────────────────────────────────
  PAGE HEADER
  "The Ledger"
  "A record of what I owe the world — and what I
   reluctantly owe the snakes."

  SUMMARY STRIP (4 stats):
  [ $XXX earned for good causes ]  [ $XXX to causes I don't love ]
  [ XX achievements/challenges/experiments ]  [ XX charities helped ]
─────────────────────────────────────────────────────────
  VIEW TOGGLE: [ By Event ]  [ By Charity ]
─────────────────────────────────────────────────────────
  VIEW A — "By Event" (default)
  
  Two columns:
  LEFT: "Things I fought for"        RIGHT: "Things that fought me"
  
  Badge wall — every earned entry    Badge wall — every failed entry
  (achievements, passed challenges,  (failed/abandoned challenges
   completed experiments)             and experiments)
  
─────────────────────────────────────────────────────────
  VIEW B — "By Charity"
  
  LEFT: "Causes I fought for"        RIGHT: "Causes I reluctantly helped"
  
  Per-cause card:                    Per-cause card:
  - Charity badge + name             - Charity badge + name (muted)
  - Running total donated            - Running total donated
  - Which events contributed         - joke_note in italic mono
  - (sub-badges per event)           - (sub-badges per failure)
─────────────────────────────────────────────────────────
  TRANSACTION LOG (collapsed, expandable)
  Full chronological list
─────────────────────────────────────────────────────────
  FOOTER NOTE (small, italic)
  "Donations are real. The snake thing is real."
─────────────────────────────────────────────────────────
```

---

### 5.2 View A: By Event — Badge Design

Each event generates one badge card. The badge treatment differs by source type:

#### Achievement badges (bounty only)

```
┌──────────────────────────────┐
│  🏆  [achievement icon]      │  ← full color (platform badge palette)
│  280 Club                    │
│  10 lbs lost from start      │
│                              │
│  → Northwest Harvest  $50    │  ← cause label, small, linked
│  Earned · Mar 15, 2026       │
└──────────────────────────────┘
```

- Full color — uses same badge design language as Milestones page
- Shows cause name + amount as a subtle sub-label (NOT prominent)
- `Earned` evidence badge
- Links to achievement in Milestones page

#### Challenge / experiment — passed (bounty)

```
┌──────────────────────────────┐
│  ✓  30-Day Walking Challenge │  ← accent/green treatment
│  30 days · 10k steps/day     │
│                              │
│  → Northwest Harvest  $50    │
│  Completed · Feb 28, 2026    │
└──────────────────────────────┘
```

#### Challenge / experiment — failed (punishment)

```
┌──────────────────────────────┐
│  ✗  Glucose Experiment #3    │  ← muted, cool-toned
│  Abandoned day 14 of 30      │
│                              │
│  → Snake Fund  $75           │  ← dry, slightly smaller
│  Failed · Jan 10, 2026       │
└──────────────────────────────┘
```

- Muted / desaturated palette
- Snake Fund label instead of cause name (until reader discovers there's a real page for it)

---

### 5.3 View B: By Charity — Charity Card Design

#### Earned cause card (left column)

```
┌─────────────────────────────────────────────┐
│  [LOGO]  Northwest Harvest                  │
│          Pacific NW food bank               │
│                                             │
│  $150 donated across 3 entries              │  ← running total prominent
│                                             │
│  Contributions:                             │
│  ┌────────┐  ┌────────┐  ┌────────┐        │
│  │ 280    │  │30-Day  │  │ Week 4 │        │  ← sub-badges
│  │ Club   │  │ Walk   │  │ Protein│        │
│  │  $50   │  │  $50   │  │  $50   │        │
│  └────────┘  └────────┘  └────────┘        │
│                                             │
│  Earned · N=1 · Matthew believes in this   │
└─────────────────────────────────────────────┘
```

- Full color, warm
- Cause logo or generated badge
- Running total is the headline number
- Sub-badges link back to source (Milestones page, Experiments page, etc.)
- `why_i_care` quote from config renders as evidence badge

#### Reluctant cause card (right column)

```
┌─────────────────────────────────────────────┐
│  [LOGO]  American Reptile Rescue            │
│          Snake and reptile sanctuary        │
│                                             │
│  $125 donated across 2 failures             │  ← "failures" label, dry
│                                             │
│  *I have funded this organization more      │
│   than I care to admit.*                    │  ← joke_note, italic mono
│                                             │
│  Via:                                       │
│  ┌──────────────┐  ┌──────────────┐        │
│  │ Glucose      │  │ Sleep Proto  │        │  ← sub-badges, muted
│  │ Experiment   │  │ Challenge    │        │
│  │    $75       │  │    $75       │        │
│  └──────────────┘  └──────────────┘        │
│                                             │
│  Despite myself · N=2 · The snakes persist │
└─────────────────────────────────────────────┘
```

- Muted palette — desaturated badge colors
- Subtle snake icon (SVG) in column header only — not per card
- `joke_note` renders in small italic monospace — this is where the personality lives
- Sub-badges labeled "Via:" not "Contributions:" — drier
- Evidence badge: `Despite myself · N=X`

---

### 5.4 Visual Design System Alignment

| Element | Treatment |
|---|---|
| Page background | Platform standard (dark mode default) |
| Section headers | Monospace with trailing dash lines (platform standard) |
| Summary strip | Platform summary strip pattern (consistent with Milestones, Achievements) |
| Earned cause cards | Warm accent border `var(--accent)` — full color badge palette |
| Reluctant cause cards | `var(--border)` — muted, desaturated palette |
| Sub-badges (by charity view) | Compact badge chips — same as Milestones badge mini treatment |
| Achievement badges (by event view) | Full badge from Milestones design language |
| View toggle | Tab-style toggle (consistent with platform tab patterns) |
| Mobile | Single column — earned first, horizontal rule, reluctant below |

---

## 6. API Design

### 6.1 `GET /api/ledger`

**Lambda:** `life-platform-site-api`  
**Cache TTL:** 3600s

**Response schema:**
```json
{
  "totals": {
    "total_donated_usd": 275,
    "total_bounties_usd": 150,
    "total_punishments_usd": 125,
    "bounty_count": 3,
    "punishment_count": 2,
    "cause_count": 2
  },
  "by_event": {
    "earned": [
      {
        "ledger_id": "2026-03-15T...",
        "date": "2026-03-15",
        "source_type": "achievement",
        "source_id": "weight_280",
        "source_name": "280 Club",
        "source_badge_icon": "🏆",
        "outcome": "earned",
        "amount_usd": 50,
        "cause_id": "food_bank_seattle",
        "cause_name": "Northwest Harvest"
      }
    ],
    "reluctant": [
      {
        "ledger_id": "2026-01-10T...",
        "date": "2026-01-10",
        "source_type": "experiment",
        "source_id": "glucose_exp_3",
        "source_name": "Glucose Experiment #3",
        "source_badge_icon": "🔬",
        "outcome": "abandoned",
        "amount_usd": 75,
        "cause_id": "snake_sanctuary",
        "cause_name": "American Reptile Rescue"
      }
    ]
  },
  "by_cause": {
    "earned_causes": [
      {
        "id": "food_bank_seattle",
        "name": "Northwest Harvest",
        "short_description": "Pacific NW food bank",
        "url": "https://...",
        "badge_color": "teal",
        "why_i_care": "Food insecurity in my backyard.",
        "total_usd": 150,
        "count": 3,
        "transactions": [
          {
            "date": "2026-03-15",
            "source_name": "280 Club",
            "source_type": "achievement",
            "source_badge_icon": "🏆",
            "amount_usd": 50
          }
        ]
      }
    ],
    "reluctant_causes": [
      {
        "id": "snake_sanctuary",
        "name": "American Reptile Rescue",
        "joke_note": "I have funded this organization more than I care to admit.",
        "is_active": true,
        "total_usd": 125,
        "count": 2,
        "transactions": [...]
      }
    ]
  }
}
```

The response serves both views from a single call — the page JS renders View A from `by_event` and View B from `by_cause`. No second fetch needed.

---

### 6.2 MCP Tool: `log_ledger_entry`

**Module:** `mcp/tools_lifestyle.py` or new `mcp/tools_ledger.py`

**Inputs:**
```
source_type    string  required   "achievement" | "challenge" | "experiment"
source_id      string  required   ID of the trigger record
outcome        string  required   "earned" | "passed" | "failed" | "abandoned"
date           string  optional   YYYY-MM-DD (defaults to today)
notes          string  optional   Free text context
```

**Outputs:** Confirmation message with resolved values:
```
✅ Ledger entry logged
   Type: bounty
   Source: 280 Club (achievement)
   Outcome: earned
   Amount: $50 → Northwest Harvest
   All-time total: $150 to earned causes / $75 to reluctant causes
```

**Resolution steps (internal):**
1. Fetch source record (or badge config for achievements)
2. Resolve `bounty_usd` / `punishment_usd` from record → fallback to config defaults
3. Resolve `cause_id` from record → fallback to active cause in config
4. Write `LEDGER#<ISO>` transaction record
5. Atomic update to `TOTALS#current` — increment global counts + update `by_cause` map

---

### 6.3 Achievement-specific: auto-detect vs manual

Achievement badges are the most natural fit for auto-detection (the system already knows when 280 lbs is hit). However, to keep Phase 0 simple, **logging is manual in v1**. When Matthew hits 280 lbs and the Milestones page awards the badge, he runs:

```
log_ledger_entry("achievement", "weight_280", "earned")
```

This is one line. Auto-detection (Lambda watching achievement unlocks and writing ledger entries) is a Phase 2 enhancement once the manual flow is proven.

---

## 7. Implementation Plan

### Phase 0 — Config & Data Infrastructure (~1 session)

1. Create `config/ledger.json` in S3 with Matthew's initial causes + reluctant causes
2. Add optional `bounty_usd`, `cause_id` fields to `config/achievement_badges.json` for the badges Matthew wants ledger-linked
3. Add `log_ledger_entry` MCP tool to `mcp/tools_lifestyle.py`
4. Test: run `pytest tests/test_mcp_registry.py` — new tool must appear
5. Run `log_ledger_entry` from Claude Desktop for 1–2 past events to seed initial data
6. Verify `TOTALS#current` record updates correctly

**Deploy:** MCP zip deploy, S3 config upload

---

### Phase 1 — API Endpoint (~0.5 sessions)

1. Add `handle_ledger()` to `site_api_lambda.py`
2. Route: `GET /api/ledger` — reads `TOTALS#current` + `LEDGER#` records + merges with S3 config metadata
3. Returns unified `by_event` + `by_cause` structure in one response
4. CloudFront cache: TTL 3600s
5. Deploy via `deploy/deploy_lambda.sh life-platform-site-api`

**Test:** `curl https://averagejoematt.com/api/ledger` returns valid JSON with both views

---

### Phase 2 — The Ledger Page (~1.5 sessions)

1. Create `site/ledger/index.html`
2. Summary strip (4 stats)
3. View toggle — `[By Event]` / `[By Charity]`
4. View A: two-column badge wall (earned left, reluctant right)
5. View B: two-column charity cards (earned left, reluctant right) with sub-badges
6. Transaction log (collapsed by default, expandable)
7. Footer note
8. Apply platform design system tokens throughout
9. Add cause logos to `site/assets/images/ledger/`
10. Add footer link to `components.js` — label `Snake Fund`, href `/ledger/`, no special treatment

**S3 sync:** `/site/ledger/*`, `/site/assets/images/ledger/*`, `/site/assets/js/components.js`  
**CloudFront invalidation:** `/ledger/*`, `/assets/js/components.js`

---

### Phase 3 — Challenge & Experiment Card Linkage (~0.5 sessions)

1. Add `ledger_linked: true` display field to challenge/experiment cards where applicable
2. On linked cards: small note *"This carries a stake."* linking to `/ledger/`
3. No dollar amounts shown on source cards — amounts only visible on The Ledger page itself

---

### Phase 4 — Achievement Badge Linkage (~0.5 sessions)

1. Update Milestones page badge rendering: if `badge.bounty_usd` is set (from config), show small indicator on earned badge — e.g. a subtle `→` icon that links to `/ledger/`
2. Still no dollar amount on the badge itself
3. The Ledger page is where amounts are visible

---

### Phase 5 — Auto-detection for Achievements (future, post-proven manual flow)

1. Lambda (or addition to existing `character-sheet-compute` / achievements logic) detects newly unlocked achievement badges
2. On new unlock: auto-writes ledger entry without manual MCP call
3. Only add this once manual flow has been used for 60+ days and the mechanic is proven

---

## 8. Files Touched / Created

| File | Action | Phase |
|---|---|---|
| `config/ledger.json` (S3) | Create | 0 |
| `config/achievement_badges.json` (S3) | Add `bounty_usd`, `cause_id` fields to selected badges | 0 |
| `mcp/tools_lifestyle.py` | Add `log_ledger_entry` | 0 |
| `tests/test_mcp_registry.py` | Auto-validates via existing test suite | 0 |
| `lambdas/site_api_lambda.py` | Add `handle_ledger()`, register `/api/ledger` route | 1 |
| `site/ledger/index.html` | Create | 2 |
| `site/assets/images/ledger/` | Create (cause logos) | 2 |
| `site/assets/js/components.js` | Add Snake Fund footer link | 2 |
| Challenge DynamoDB records | Optional: add `bounty_usd`, `punishment_usd`, `cause_id` to specific records | 3 |
| Experiment DynamoDB records | Optional: same | 3 |
| `site/achievements/index.html` | Add subtle ledger indicator on linked badges | 4 |
| `site/experiments/index.html` | Add subtle "carries a stake" note | 3 |

---

## 9. Pre-Build Decisions Required from Matthew

| # | Decision | Options |
|---|---|---|
| 1 | **Initial earned causes list** | Which 2–4 causes to start? One per domain (food security, health, etc.) or all one type? |
| 2 | **Inaugural snake** | First reluctant cause — the founding snake |
| 3 | **Which achievement badges get ledger-linked in v1?** | All weight milestones? Streaks too? Or just weight for now? |
| 4 | **Default cause assignment for achievements** | All weight milestones → same cause, or per-badge? |
| 5 | **Retroactive seeding** | Seed 0–5 past events to have something on page at launch, or start fresh? |
| 6 | **Show amounts in By Charity view?** | Totals per cause = yes (recommended). Per-transaction amounts = yes/no? |
| 7 | **View A or View B as the default when you land on the page?** | By Event (badge wall) or By Charity? Recommendation: By Event — it's the more immediate hook |
| 8 | **Ledger-link experiments retroactively?** | Mark past failed/completed experiments as ledger-linked, or only forward from here? |

---

## 10. Scope Boundaries (What This Is NOT)

- **Not automated donation processing** — Matthew makes real donations manually; The Ledger is accountability tracking only
- **Not a charity promotion page** — it's a personal accountability record
- **Not prominent** — footer link only, no nav, no badge amounts on source cards
- **Not a real-time trigger system in v1** — all logging is manual via MCP tool (auto-detection is Phase 5)

---

## 11. Effort Estimate

| Phase | Sessions | Complexity |
|---|---|---|
| Phase 0: Config + MCP tool | 1 | Low |
| Phase 1: API endpoint | 0.5 | Low |
| Phase 2: Ledger page (both views) | 1.5–2 | Medium |
| Phase 3: Challenge/experiment linkage | 0.5 | Low |
| Phase 4: Achievement badge indicator | 0.5 | Low |
| Phase 5: Auto-detection (future) | 1 | Medium |
| **Total (Phases 0–4)** | **~4–4.5 sessions** | |

---

## 12. The Two-View Mental Model (Summary)

```
THE LEDGER
│
├── VIEW A: By Event (the badge wall)
│   │
│   ├── LEFT: "Things I fought for"
│   │   ├── 280 Club (achievement) → Northwest Harvest $50
│   │   ├── 30-Day Walk (challenge, passed) → Northwest Harvest $50
│   │   └── Glucose Exp #4 (experiment, confirmed) → Northwest Harvest $50
│   │
│   └── RIGHT: "Things that fought me"
│       ├── Glucose Exp #3 (experiment, abandoned) → Snake Fund $75
│       └── Sleep Protocol (challenge, failed) → Snake Fund $75
│
└── VIEW B: By Charity (the ledger totals)
    │
    ├── LEFT: Earned causes
    │   └── Northwest Harvest
    │       $150 total · 3 events
    │       [280 Club]  [30-Day Walk]  [Glucose #4]
    │
    └── RIGHT: Reluctant causes
        └── American Reptile Rescue
            $150 total · 2 failures
            "I have funded this org more than I care to admit."
            [Glucose #3]  [Sleep Protocol]
```

---

*"The snakes are still waiting."*  
*— Ava Moreau*
