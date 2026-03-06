# Notion Journal — Expanded Expert Panel Review & Haiku Enrichment Design

> Phase 2 design doc. Builds on NOTION_JOURNAL_SPEC.md (Phase 1 templates).
> Created: 2026-02-24 | For: Haiku enrichment prompt design + template refinements

---

## Expanded Expert Panel

### Original Panel (Phase 1 — template design)
| Role | Perspective |
|------|-------------|
| **Sleep Scientist** (Walker) | Subjective sleep quality, pre-sleep state |
| **Sports Scientist** (Galpin) | Training readiness, RPE, soreness |
| **Nutritionist** (Norton) | Hunger/satiety signals, cravings |
| **Psychologist** (Huberman) | Stress, focus, mood, motivation |
| **Longevity Physician** (Attia) | Symptom tracking, subjective vitality |
| **Behavioral Scientist** (Fogg) | Habit friction, minimum viable entries |

### New Panel Members (Phase 2 — enrichment & deeper insight)
| Role | Perspective |
|------|-------------|
| **Tim Ferriss** | Fear-setting, "what would this look like if it were easy?", deconstructing what works, 5-minute journal (gratitude + daily wins), 80/20 of journaling ROI |
| **Sam Harris** | Mindfulness quality, equanimity under stress, awareness vs autopilot, relationship between meditation and emotional regulation |
| **Jocko Willink** | Extreme ownership, accountability, discipline tracking, "did I do what I said I would?", avoiding comfort-seeking |
| **Martin Seligman** (Positive Psychology) | PERMA model: Positive emotion, Engagement, Relationships, Meaning, Accomplishment. Learned helplessness vs learned optimism patterns |
| **Mihaly Csikszentmihalyi** (Flow) | Flow state frequency, challenge/skill balance, intrinsic motivation, deep work quality |
| **Sonja Lyubomirsky** (Happiness Research) | Gratitude practice, social connection quality, acts of kindness, hedonic adaptation awareness |
| **Ray Dalio** (Principles) | Decision quality tracking, radical transparency with self, pain + reflection = progress |
| **Judith Beck** (CBT) | Cognitive distortions in journal text, automatic negative thoughts, reframing quality |
| **Steven Hayes** (ACT) | Values alignment, psychological flexibility, willingness to experience discomfort for values |
| **Cal Newport** (Deep Work) | Deep work hours, attention residue, digital distraction patterns |
| **Johann Hari** (Connection) | Social connection as health lever, loneliness signals, quality of human interaction |
| **Dan Buettner** (Blue Zones) | Purpose (ikigai), social belonging, natural movement, stress-reduction rituals |

---

## The Key Insight: Two-Layer Architecture

The templates capture **structured signals** (mood 1-5, stress 1-5, RPE). These are reliable, fast to enter, and easy to trend.

But the **free text fields** (Notes, Notable Events, Win of the Day, What Drained Me, Today's Intention, What Happened) contain the *real* intelligence — the WHY behind the numbers. A mood of 2 means nothing without context. "Mood 2 because I snapped at Sarah over something trivial and then couldn't focus all afternoon" is actionable.

**Haiku's job is to bridge the gap**: extract structured, queryable intelligence from unstructured journal text that the human would never tag manually.

---

## Panel Consensus: Template Refinements

After reviewing the Phase 1 templates, the expanded panel recommends **4 additions** to the Notion database. These are high-signal, low-friction fields that the original panel missed:

### Morning Check-In — Add:
| Field | Type | Values | Expert | Rationale |
|-------|------|--------|--------|-----------|
| **Gratitude** | Text | 1 sentence | Ferriss, Lyubomirsky, Seligman | "Single most evidence-based positive psychology intervention. One sentence, not three — compliance beats completeness." (Ferriss: "The 5-minute journal's ROI comes from gratitude, not goals.") |

### Evening Reflection — Add:
| Field | Type | Values | Expert | Rationale |
|-------|------|--------|--------|-----------|
| **Social Connection** | Select | 1-5 (Isolated → Deeply Connected) | Hari, Buettner, Lyubomirsky | "Social connection is as predictive of mortality as smoking 15 cigarettes a day. Track it like you track HRV." (Buettner: every Blue Zone centenarian has daily social rituals.) |
| **Deep Work Hours** | Select | 0, 1, 2, 3, 4+ | Newport, Csikszentmihalyi | "Knowledge workers average 2.5 hours of deep work per day. Most don't know their number. Awareness alone increases it." (Newport) Track flow-state proxy. |
| **One Thing I'm Avoiding** | Text | 1 sentence | Ferriss, Jocko, Hayes | "The thing you're avoiding is usually the thing you most need to do. Making it visible is half the battle." (Jocko: "Discipline equals freedom — but first you have to see where you're choosing comfort.") (Ferriss: fear-setting lite.) |

### Why NOT more fields:
- **Fogg:** "You added 4 fields. That's the absolute maximum before you start losing the evening entry. If Matthew skips even one evening this week, remove a field."
- **Ferriss:** "I'd rather have 100% compliance on 10 fields than 60% compliance on 20. The data you don't collect is worthless."
- **Jocko:** "Simple. Effective. Execute."

---

## Haiku Enrichment: What to Extract

This is where the panel gets excited. The free text fields contain signal that no structured dropdown can capture. Haiku reads the raw_text and extracts:

### Tier 1: Core Extractions (every entry)

| Field | Type | Description | Expert Rationale |
|-------|------|-------------|-----------------|
| `mood_score` | number (1-5) | Normalized mood from all signals | Huberman: "Aggregate across morning mood, day rating, and text sentiment for a single longitudinal signal." |
| `energy_score` | number (1-5) | Normalized energy | Attia: "Morning energy + EOD energy + text context = true vitality signal." |
| `stress_score` | number (1-5) | Normalized stress | Huberman: "The number they circle is how they want to feel. The text is how they actually feel." |
| `sentiment` | string | positive / neutral / negative / mixed | Beck: "Global sentiment tracking catches downward spirals before the person notices." |
| `emotions` | list of strings | Granular emotions detected | Seligman: "Emotional granularity predicts emotional regulation. 'Anxious' and 'frustrated' require different interventions." |
| `themes` | list of strings | Recurring life themes | Ferriss: "Patterns in your journal are the 80/20 of self-knowledge." |

### Tier 2: Behavioral & Psychological Signals

| Field | Type | Description | Expert Rationale |
|-------|------|-------------|-----------------|
| `cognitive_patterns` | list of strings | Detected thinking patterns | Beck: "Catastrophizing, black-and-white thinking, 'should' statements, rumination, mind-reading, personalization. If the journal shows 3+ catastrophizing entries in a week, that's clinical signal." |
| `growth_signals` | list of strings | Evidence of growth mindset, learning, reframing | Seligman: "Learned optimism vs learned helplessness. Track which explanatory style dominates." |
| `avoidance_flags` | list of strings | Things being avoided or procrastinated | Ferriss/Jocko: "The avoided thing is the high-leverage thing. Surface it." |
| `ownership_score` | number (1-5) | Internal vs external locus of control in text | Jocko: "When the journal says 'they made me' vs 'I chose to' — that's the difference between victim and owner." |
| `social_quality` | string | alone / surface / meaningful / deep | Hari/Buettner: "Not just 'did you see people' but 'did you connect?'" |
| `flow_indicators` | boolean | Evidence of flow/deep engagement | Csikszentmihalyi: "Mentions of losing track of time, being absorbed, challenge meeting skill." |
| `values_lived` | list of strings | Core values evidenced in today's actions | Hayes: "The gap between stated values and lived values is where suffering lives." |
| `gratitude_items` | list of strings | Specific things expressed gratitude for | Lyubomirsky: "Gratitude journaling works — but only if you're specific. 'My family' doesn't count. 'The way my daughter laughed at dinner' does." |

### Tier 3: Health & Behavior Cross-Reference Flags

| Field | Type | Description | Expert Rationale |
|-------|------|-------------|-----------------|
| `alcohol_mention` | boolean | Alcohol consumption mentioned | Walker: "Correlate with Eight Sleep REM suppression. The journal captures what MacroFactor misses — the 'just 2 glasses' that crushed deep sleep." |
| `sleep_disruption_context` | string | Why sleep was bad (if mentioned) | Walker: "The 'why' behind a 62 sleep score is worth more than the score itself." |
| `pain_or_injury_mention` | list of strings | Body areas or pain mentioned in free text | Galpin: "Catches complaints that don't make it into the structured Physical State field." |
| `supplement_or_med_mention` | list of strings | Supplements/medications mentioned | Attia: "Tracks real-world adherence and side effects better than any pill tracker." |
| `exercise_context` | string | How the workout felt beyond RPE | Galpin: "RPE 7 with 'felt strong, could have kept going' vs RPE 7 with 'barely survived' — completely different signals." |

---

## Haiku Prompt Design

### Design Principles (Panel Consensus)

1. **Harris:** "The prompt should not project emotions onto the text. Extract what's there, not what you expect."
2. **Beck:** "Use clinical precision. 'Catastrophizing' has a specific CBT definition. Don't dilute it."
3. **Ferriss:** "80/20 the extraction. Get 6 things right every time rather than 20 things sometimes."
4. **Fogg:** "The extraction should make the person feel *seen*, not surveilled."

### Prompt Structure

```
You are an expert behavioral analyst reviewing a personal journal entry. Extract structured insights from the text below. Be precise — only flag what's clearly present, never infer what isn't there.

JOURNAL ENTRY:
{raw_text}

CONTEXT (if available):
- Date: {date}
- Template: {template}
- Structured scores already captured: mood={morning_mood or day_rating}, stress={stress_level}, energy={morning_energy or energy_eod}

Extract the following as JSON. Use null for anything not clearly present in the text:

{
  "mood_score": <1-5, synthesized from all mood signals in text and structured data. 1=very low, 5=very high>,
  "energy_score": <1-5, synthesized from all energy signals>,
  "stress_score": <1-5, synthesized from all stress signals. 1=calm, 5=overwhelmed>,
  "sentiment": <"positive" | "neutral" | "negative" | "mixed">,
  "emotions": [<specific emotions detected, e.g. "anxious", "grateful", "frustrated", "hopeful", "content", "overwhelmed", "proud", "lonely", "energized", "resigned". Use precise emotional vocabulary, not just synonyms for happy/sad>],
  "themes": [<life themes present, e.g. "work pressure", "family connection", "physical achievement", "creative expression", "financial stress", "health anxiety", "social isolation", "personal growth", "relationship tension". Max 4 themes>],
  "cognitive_patterns": [<ONLY include if clearly evident. Use clinical terms: "catastrophizing", "black-and-white thinking", "should statements", "rumination", "overgeneralization", "personalization", "mind-reading", "fortune-telling", "discounting positives", "emotional reasoning". Also include positive patterns: "reframing", "growth mindset", "self-compassion", "perspective-taking">],
  "growth_signals": [<evidence of learning, reframing, or growth. e.g. "recognized pattern", "tried new approach", "accepted uncertainty", "showed self-compassion". null if none>],
  "avoidance_flags": [<things being avoided, procrastinated, or feared. e.g. "difficult conversation with manager", "financial review", "doctor appointment". null if none>],
  "ownership_score": <1-5. 1=fully external attribution ("they made me", "it happened to me"), 5=fully internal ("I chose", "I could have"). null if no ownership signals>,
  "social_quality": <"alone" | "surface" | "meaningful" | "deep" | null. Based on social interactions described>,
  "flow_indicators": <true if evidence of deep engagement/flow state, false otherwise>,
  "values_lived": [<core values evidenced in actions described. e.g. "discipline", "family", "health", "creativity", "courage", "kindness", "growth", "integrity". Max 3>],
  "gratitude_items": [<specific gratitude expressed. Must be concrete, not abstract. null if none>],
  "alcohol_mention": <true/false>,
  "sleep_disruption_context": <brief reason if poor sleep mentioned, null otherwise>,
  "pain_mentions": [<body areas or pain types mentioned. null if none>],
  "exercise_context": <brief subjective workout assessment if mentioned, null otherwise>,
  "notable_quote": <most insightful or revealing sentence from the entry, verbatim. The one sentence that best captures the person's state. null if entry is too brief>
}

Rules:
- Be conservative. Only extract what's clearly present.
- emotions: prefer precise terms over vague ones. "Apprehensive" over "bad".
- cognitive_patterns: these are clinical CBT terms. Only flag if the pattern is clearly demonstrated.
- themes: max 4, ordered by prominence.
- ownership_score: only rate if there's clear attribution language.
- values_lived: infer from actions described, not stated intentions.
- Respond with ONLY the JSON object. No preamble, no explanation.
```

### Why This Prompt Works (Panel Notes)

- **Beck:** "The cognitive_patterns field uses precise CBT terminology. 'Catastrophizing' is not 'being worried' — it's specifically assuming the worst possible outcome. The instruction to only flag when clearly demonstrated prevents over-detection."
- **Harris:** "The 'be conservative' instruction is critical. An AI that tells you you're catastrophizing when you're just concerned will destroy trust in 3 entries."
- **Ferriss:** "The notable_quote field is my favorite. It's the 'what would I highlight?' of the journal. Over time, these quotes become a personal wisdom library."
- **Seligman:** "ownership_score is essentially tracking explanatory style — the core of learned optimism. If this trends down over time, it's an early depression signal."
- **Jocko:** "avoidance_flags. That's the one. Surface what you're running from. That's the whole game."
- **Dalio:** "Pain + reflection = progress. The journal is the pain; Haiku enrichment is the reflection. The tools surface the progress."

---

## DynamoDB Schema Additions

All enriched fields are added to the existing journal item (same PK/SK). Prefixed with `enriched_` to distinguish from raw entry data.

```
# Added to existing journal items after enrichment
enriched_at: ISO timestamp
enriched_mood: Decimal (1-5)
enriched_energy: Decimal (1-5)  
enriched_stress: Decimal (1-5)
enriched_sentiment: string
enriched_emotions: list of strings
enriched_themes: list of strings
enriched_cognitive_patterns: list of strings (may be empty)
enriched_growth_signals: list of strings (may be empty)
enriched_avoidance_flags: list of strings (may be empty)
enriched_ownership: Decimal (1-5, nullable)
enriched_social_quality: string (nullable)
enriched_flow: boolean
enriched_values_lived: list of strings
enriched_gratitude: list of strings (may be empty)
enriched_alcohol: boolean
enriched_sleep_context: string (nullable)
enriched_pain: list of strings (may be empty)
enriched_exercise_context: string (nullable)
enriched_notable_quote: string (nullable)
```

---

## MCP Tools Design (Phase 3)

### Tool 1: `get_journal_entries`
**Purpose:** Retrieve journal entries for a date range with optional template filter.
**Use for:** "Show me my journal from last week", "What did I write this morning?"
**Parameters:** start_date, end_date, template (optional), include_enriched (default true)

### Tool 2: `search_journal`  
**Purpose:** Full-text search across all journal entries.
**Use for:** "When did I mention back pain?", "Find entries about work stress"
**Parameters:** query (keyword), start_date, end_date (optional)
**Implementation:** Scan notion items, search raw_text + enriched fields for keyword matches.

### Tool 3: `get_mood_trend`
**Purpose:** Mood/energy/stress scores over time with enriched signals.
**Use for:** "How has my mood been this month?", "Stress trend over the last 30 days"
**Parameters:** start_date, end_date, metric (mood|energy|stress|all)
**Returns:** Daily scores, 7-day rolling average, trend direction, recurring themes at peaks/valleys.

### Tool 4: `get_journal_insights`
**Purpose:** Cross-entry pattern analysis. The "so what?" tool.
**Use for:** "What patterns do you see in my journal?", "What am I consistently avoiding?"
**Parameters:** start_date, end_date (default: 30 days)
**Returns:**
- Top recurring themes (ranked by frequency)
- Dominant emotions (distribution)
- Cognitive pattern frequency (are you catastrophizing more or less?)
- Most common avoidance flags
- Ownership trend (trending internal or external?)
- Values alignment score (are lived values consistent?)
- Social connection trend
- Flow frequency
- Correlation hints: "High stress days tend to follow nights with alcohol mentions"

### Tool 5: `get_journal_correlations`
**Purpose:** Correlate journal signals with wearable data.
**Use for:** "Does my subjective sleep quality match Eight Sleep?", "Do high-stress days affect my HRV?"
**Parameters:** start_date, end_date, signal (stress|mood|energy|sleep_quality)
**Returns:**
- Subjective vs objective comparison (journal mood vs Whoop recovery, journal stress vs Garmin stress)
- Pearson correlations
- Notable divergences ("You rated sleep 2/5 but Eight Sleep scored 85 — possible sleep state misperception")

### Tool Design Notes (Panel)

- **Attia:** "get_journal_correlations is the killer tool. Subjective-objective divergence is where the clinical insights live. A person who consistently rates their sleep poorly despite good objective scores may have sleep anxiety."
- **Ferriss:** "get_journal_insights should have a 'top 3 things to change this week' output. Don't just show patterns — make them actionable."
- **Harris:** "Be careful with cognitive_patterns in tool output. Don't say 'you catastrophized 7 times this month.' Say 'I noticed catastrophizing language in some entries — would you like to explore that?'"
- **Dalio:** "The ownership trend is the single most important longitudinal metric. If it's declining, everything else will follow."

---

## Implementation Plan

### Phase 2a: Template Updates (15 min)
- Add 4 new fields to Notion database via API: Gratitude, Social Connection, Deep Work Hours, One Thing I'm Avoiding
- Update `patch_notion_db.py` and `NOTION_JOURNAL_SPEC.md`
- Update `notion_lambda.py` to extract new fields

### Phase 2b: Enrichment Lambda (1.5 hr)
- Add journal enrichment to existing `enrichment_lambda.py` (or create dedicated `journal_enrichment_lambda.py`)
- Haiku API call with prompt above
- Parse JSON response, write enriched fields back to DynamoDB items
- Schedule: run after notion ingestion (e.g., 6:30 AM PT or chain from notion Lambda)
- Handle entries with minimal text gracefully (skip enrichment if raw_text < 20 chars)

### Phase 3: MCP Tools (1-2 hr)
- Implement 5 tools in `mcp_server.py`
- Add to tool registry
- Deploy MCP update

### Phase 4: Brief Integration (30 min)
- Daily brief: yesterday's mood + stress + themes + notable_quote
- Weekly digest: mood/stress/energy trends, top themes, cognitive patterns, ownership trend, avoidance flags
