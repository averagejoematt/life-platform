# Notion Journal — Template Design Spec

> Expert panel review for Life Platform journal integration.
> Created: 2026-02-24 | For: Phase 1 foundation before Lambda build

---

## Expert Panel

| Role | Perspective |
|------|-------------|
| **Sleep Scientist** (Walker) | Subjective sleep quality, pre-sleep state, chronotype alignment |
| **Sports Scientist** (Galpin) | Training readiness, RPE capture, soreness mapping, recovery signals |
| **Nutritionist** (Layne Norton) | Hunger/satiety signals, cravings, meal quality beyond macros |
| **Psychologist** (Huberman) | Stress, focus, mood, motivation, cognitive load, gratitude |
| **Longevity Physician** (Attia) | Symptom tracking, medication/supplement notes, subjective vitality |
| **Behavioral Scientist** (BJ Fogg) | Habit friction, identity reinforcement, minimum viable entries |

---

## Design Principles

1. **Complement, don't duplicate.** Eight Sleep tracks sleep objectively. Strava tracks workouts. MacroFactor tracks food. The journal captures what sensors can't: the *why*, the *how it felt*, and the *context*.
2. **Low friction or it dies.** Morning entry: <2 min. Evening entry: <3 min. If it feels like homework, adherence drops to zero within 2 weeks (Fogg).
3. **Structured enough for Haiku extraction, freeform enough for insight.** Use Notion selects/multi-selects for quantifiable fields, free text for context.
4. **Progressive disclosure.** Required fields are minimal. Optional fields are available but never guilt-inducing.

---

## Template 1: Morning Check-In ☀️

**When:** Within 30 min of waking (before daily brief arrives at 8:15 AM)
**Time to complete:** 60-90 seconds
**Purpose:** Capture pre-day baseline state before cognitive load accumulates

### Fields

| Field | Type | Values / Notes | Required | Expert Rationale |
|-------|------|----------------|----------|-----------------|
| **Date** | Date | Auto-filled | ✅ | — |
| **Template** | Select | `Morning` | ✅ | Enables filtering |
| **Subjective Sleep Quality** | Select | 1-5 (Terrible → Excellent) | ✅ | Walker: subjective and objective sleep diverge meaningfully. Captures perception vs Eight Sleep reality. |
| **Morning Energy** | Select | 1-5 (Depleted → Wired) | ✅ | Attia: subjective vitality is an early warning system. Persistent low energy with "good" sleep scores → investigate. |
| **Morning Mood** | Select | 1-5 (Low → Great) | ✅ | Huberman: baseline mood before daily stressors. Tracks if sleep quality actually translates to next-day affect. |
| **Physical State** | Multi-select | `Fresh`, `Sore`, `Stiff`, `Pain`, `Fatigued`, `Energized` | ❌ | Galpin: subjective readiness complements HRV. "Sore + high HRV" = train. "Fresh + low HRV" = systemic stress. |
| **Body Region** | Multi-select | `Lower Back`, `Knees`, `Shoulders`, `Neck`, `Hips`, `General` | ❌ | Galpin: tracks injury patterns over time. Correlate with Hevy exercise selection. |
| **Today's Intention** | Text | 1 sentence max | ❌ | Fogg: identity-based framing. "I'm someone who..." or a single focus. Not a to-do list. |
| **Notes** | Text | Free text | ❌ | Catch-all for dreams, overnight events, woke up at 3am, etc. |

### Panel Notes
- **Walker:** "Subjective sleep quality diverges from objective measures in clinically meaningful ways. Someone who sleeps 8 hours but wakes feeling unrested may have undiagnosed issues. Track both."
- **Fogg:** "Three taps and a sentence. That's the maximum. If you require the text fields, you'll abandon this within a week."
- **Galpin:** "Physical state + body region is the cheapest injury prevention system. Two weeks of 'Sore → Knees' before a run block = actionable."

---

## Template 2: Evening Reflection 🌙

**When:** 30-60 min before bed (after final Habitify check-in)
**Time to complete:** 2-3 minutes
**Purpose:** Close the loop on the day. Capture stress, wins, and context that explains tomorrow's metrics.

### Fields

| Field | Type | Values / Notes | Required | Expert Rationale |
|-------|------|----------------|----------|-----------------|
| **Date** | Date | Auto-filled | ✅ | — |
| **Template** | Select | `Evening` | ✅ | Enables filtering |
| **Day Rating** | Select | 1-5 (Rough → Excellent) | ✅ | Huberman: overall day valence. Simple but powerful longitudinal signal. |
| **Stress Level** | Select | 1-5 (Calm → Overwhelmed) | ✅ | Huberman: evening stress is the #1 predictor of poor sleep onset. Direct correlation target. |
| **Stress Source** | Multi-select | `Work`, `Family`, `Health`, `Financial`, `Social`, `None` | ❌ | Attia: categorizing stress enables pattern detection. "Every Sunday = Financial stress" is actionable. |
| **Energy End-of-Day** | Select | 1-5 (Empty → Surplus) | ❌ | Attia: morning-to-evening energy delta reveals recovery capacity and metabolic health. |
| **Workout RPE** | Select | 1-10 | ❌ | Galpin: rate of perceived exertion. If RPE 8 but Strava HR says Zone 2, you're overtrained. If RPE 3 but HR was high, you're adapting. |
| **Hunger/Cravings** | Multi-select | `Controlled`, `Hungry all day`, `Sugar cravings`, `Late-night snacking`, `Low appetite` | ❌ | Norton: cravings pattern + MacroFactor deficit data = are you cutting too aggressively? |
| **Win of the Day** | Text | 1 sentence | ❌ | Fogg: celebrating small wins is the #1 habit reinforcement mechanism. |
| **What Drained Me** | Text | 1 sentence | ❌ | Huberman: identifying energy drains enables boundary-setting. |
| **Notable Events** | Text | Free text | ❌ | Context for anomalies. Travel, illness, life events, social, alcohol, arguments. |
| **Tomorrow Focus** | Text | 1 sentence | ❌ | Fogg: pre-commitment reduces morning decision fatigue. |

### Panel Notes
- **Huberman:** "Stress level before bed is the single most actionable journal field. If you track nothing else in the evening, track this. It predicts sleep onset latency, REM suppression, and next-day HRV."
- **Norton:** "Hunger/cravings in a deficit is information, not weakness. If cravings spike on days with <130g protein, that's a MacroFactor lever, not a willpower problem."
- **Fogg:** "Win of the Day is non-negotiable. You're rewiring identity. 'I did a hard thing today' compounds faster than any supplement."

---

## Template 3: Ad-Hoc — Stressor Deep-Dive 🔴

**When:** During or immediately after a significant stress event
**Time to complete:** 2-3 minutes
**Purpose:** Capture acute stress context that would otherwise be lost by evening

### Fields

| Field | Type | Values / Notes | Required |
|-------|------|----------------|----------|
| **Date** | Date | Auto-filled | ✅ |
| **Template** | Select | `Stressor` | ✅ |
| **Stress Intensity** | Select | 1-10 | ✅ |
| **Category** | Select | `Work`, `Family`, `Health`, `Financial`, `Social`, `Existential` | ✅ |
| **What Happened** | Text | Brief description | ✅ |
| **Physical Response** | Multi-select | `Heart racing`, `Tension`, `Shallow breathing`, `Stomach`, `Headache`, `None` | ❌ |
| **What I Did** | Text | How you responded / coped | ❌ |
| **Resolution** | Select | `Resolved`, `Ongoing`, `Escalated`, `Accepted` | ❌ |

### Panel Rationale
- **Huberman:** Real-time stress capture is 10x more accurate than evening recall. The amygdala rewrites memory.
- **Attia:** Physical symptoms during stress events are early cardiovascular warning signals worth longitudinal tracking.

---

## Template 4: Ad-Hoc — Health Event 🏥

**When:** Illness onset, injury, unusual symptom, medication change
**Time to complete:** 1-2 minutes
**Purpose:** Timestamp health events for correlation with metrics shifts

### Fields

| Field | Type | Values / Notes | Required |
|-------|------|----------------|----------|
| **Date** | Date | Auto-filled | ✅ |
| **Template** | Select | `Health Event` | ✅ |
| **Type** | Select | `Illness`, `Injury`, `Symptom`, `Medication Change`, `Supplement Change` | ✅ |
| **Description** | Text | What's going on | ✅ |
| **Severity** | Select | `Mild`, `Moderate`, `Severe` | ❌ |
| **Duration** | Select | `Hours`, `Days`, `Ongoing` | ❌ |
| **Impact on Training** | Select | `None`, `Modified`, `Skipped`, `Full Rest` | ❌ |

### Panel Rationale
- **Attia:** "When your HRV craters for 5 days and you can't explain it, it's because you didn't log that scratchy throat on day 1."
- **Galpin:** "Training modification during illness/injury is the difference between a 3-day setback and a 3-week one."

---

## Template 5: Ad-Hoc — Weekly Reflection 📝

**When:** Sunday evening (could align with weekly digest delivery)
**Time to complete:** 3-5 minutes
**Purpose:** Zoom out. Pattern recognition that daily entries miss.

### Fields

| Field | Type | Values / Notes | Required |
|-------|------|----------------|----------|
| **Date** | Date | Sunday date | ✅ |
| **Template** | Select | `Weekly Reflection` | ✅ |
| **Week Rating** | Select | 1-5 | ✅ |
| **Biggest Win** | Text | | ✅ |
| **Biggest Challenge** | Text | | ✅ |
| **What Would I Change** | Text | | ❌ |
| **Emerging Pattern** | Text | What am I noticing across the week? | ❌ |
| **Next Week Priority** | Text | | ❌ |

### Panel Rationale
- **Fogg:** "Weekly reflection is where behavior change actually happens. Daily is data collection. Weekly is pattern recognition."
- **Huberman:** "The brain consolidates learning through narrative. Writing 'what I'd change' literally rewires the prefrontal cortex."

---

## Notion Database Structure

### Single Database, Multiple Templates

Use **one** Notion database with a `Template` select property to distinguish entry types. This keeps the API integration simple (one database ID, one query endpoint) while supporting filtered views.

### Notion Views (for Matthew's daily use)
1. **Morning View** — filtered to `Template = Morning`, sorted by date desc
2. **Evening View** — filtered to `Template = Evening`, sorted by date desc
3. **Timeline** — all entries, calendar view
4. **Stress Log** — filtered to `Template = Stressor`, sorted by date desc
5. **Health Events** — filtered to `Template = Health Event`

### DynamoDB Storage Pattern

```
PK: USER#matthew#SOURCE#notion
SK: DATE#2026-02-24#journal#morning    (morning entry)
SK: DATE#2026-02-24#journal#evening    (evening entry)
SK: DATE#2026-02-24#journal#stressor#1 (ad-hoc, numbered)
SK: DATE#2026-02-24#journal#health#1   (ad-hoc, numbered)
SK: DATE#2026-02-24#journal#weekly     (weekly reflection)
```

Multiple entries per day via SK suffix. Raw text preserved; Haiku-extracted fields added as top-level attributes post-enrichment.

### Haiku Extraction Target Fields
From raw text across all templates, extract and normalize:
- `mood` (1-5, normalized from various inputs)
- `energy` (1-5)
- `stress` (1-5)
- `themes` (array of strings: "work pressure", "family time", "training momentum")
- `notable_events` (array of strings)
- `physical_complaints` (array of strings)
- `sentiment` (positive / neutral / negative)

---

## Implementation Phases

### Phase 1: Notion Setup + Auth + Lambda (1.5 hr)
- Create Notion database with all properties defined above
- Create internal Notion integration, store API key in Secrets Manager
- Build `notion_lambda.py` — query DB, store in DynamoDB
- EventBridge schedule: 6:00 AM PT daily
- Deploy script

### Phase 2: Haiku Enrichment (1.5 hr)
- Enrich raw entries with structured extraction
- Store extracted fields alongside raw in DynamoDB
- Handle multi-entry days (morning + evening + ad-hoc)

### Phase 3: MCP Tools (1-2 hr)
- `get_journal_entries` — date range, template filter
- `search_journal` — keyword/theme search
- `get_mood_trend` — mood/energy/stress over time

### Phase 4: Brief Integration (30 min)
- Daily brief: yesterday's mood + stress + themes
- Weekly digest: mood trend, recurring themes, stress patterns

---

## Open Questions for Matthew

1. **Notion workspace:** Do you already have one, or creating fresh?
2. **Mobile entry:** Notion mobile app for quick morning/evening? Or would a Siri Shortcut/widget be better?
3. **Weekly reflection timing:** Sunday evening before or after the weekly digest email?
4. **Template priority:** Start with morning + evening only, add ad-hocs in Phase 2?
