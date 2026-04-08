# Intelligence Layer V2: Design & Technical Brief

**Date:** 2026-04-07
**Author:** Product Board + Technical Board (via Claude planning session)
**Scope:** 6 workstreams across coach synthesis, cold-start UX, action tracking, intelligence validation, goals architecture, and mental health signal
**Estimated effort:** 6–7 Claude Code sessions
**Priority:** This is the most impactful set of changes since Observatory V2. These address credibility-destroying bugs (coaches claiming data doesn't exist when it does) and the architectural gap between "dashboard" and "coach."

---

## Pre-Session Setup

**Read these files first (in this order):**
1. `handovers/HANDOVER_LATEST.md` — current state
2. `lambdas/ai_expert_analyzer_lambda.py` — the observatory coach prompt pipeline (THIS IS THE CORE FILE)
3. `config/board_of_directors.json` in S3 (`s3://matthew-life-platform/config/board_of_directors.json`) — centralized persona config
4. `lambdas/site_api_lambda.py` — API endpoints observatory pages call
5. `lambdas/weekly_digest_v2_lambda.py` — the Weekly Digest (partially does synthesis already)
6. `lambdas/daily_brief_lambda.py` — the Daily Brief (has `unified_panel` pattern)
7. `site/training/index.html` — canonical observatory page template
8. `mcp/tools_board.py` — Board of Directors MCP tool

**Key architecture facts:**
- Observatory pages call `site_api_lambda.py` endpoints which invoke `ai_expert_analyzer_lambda.py`
- `ai_expert_analyzer_lambda.py` has a hardcoded `EXPERT_PERSONAS` dict — these are NOT the same as `board_of_directors.json`
- The observatory coaches (Dr. Amara Patel for glucose, Dr. Victor Reyes for physical, etc.) are defined ONLY in the Lambda, not in the centralized config
- Coach prompts are built by a function that receives `expert_key` + `data` dict and constructs the prompt inline
- The `data` dict is assembled from DynamoDB queries within the Lambda — this is where data blindness originates (if a query doesn't include a source, the coach doesn't know it exists)
- Results are cached in DynamoDB with ~8-day TTL; pages read from cache
- The Daily Brief has a more sophisticated pattern: it reads from `board_of_directors.json` and each coach contributes to a `unified_panel`
- DynamoDB table: `life-platform` (us-west-2)
- S3 bucket: `matthew-life-platform`
- CloudFront: `E3S424OXQZ8NBE`

---

## Workstream 1: Coach Synthesis — The Integrator

### Problem
Each observatory page has one domain coach writing an independent assessment. There is no cross-domain synthesis. When Dr. Webb (nutrition) says "waiting for input from the training coaches," it reveals that coaches operate in silos. A visitor sees 5 different actions from 5 different coaches with no way to know which matters most.

### Design

**Create a new board member: "The Integrator."**

This is NOT another domain coach. This is the person who reads all coach outputs and produces:
1. A single "This Week's Priority" — the ONE action that matters most right now, synthesized across all domains
2. A brief cross-domain context note for each observatory page (1-2 sentences explaining how that domain connects to the others)

**Persona definition (add to `board_of_directors.json`):**
```json
{
  "integrator": {
    "name": "Dr. Kai Nakamura",
    "title": "Integrative Health Director",
    "type": "fictional_advisor",
    "emoji": "🔬",
    "color": "#6366f1",
    "domains": ["cross_domain_synthesis", "priority_triage", "contradiction_resolution"],
    "voice": {
      "tone": "Clear, decisive, cuts through noise. Speaks like a chief medical officer making rounds — not adding analysis, but making the call.",
      "style": "Never hedges. Reads all domain coaches first, then makes ONE recommendation. Uses language like 'The priority this week is...' and 'Everything else can wait.'"
    },
    "principles": [
      "Five actions is zero actions. Pick one.",
      "Contradictions between coaches are signals, not problems.",
      "The domain with the biggest gap between current state and goal gets priority."
    ],
    "relationship_to_matthew": "The tiebreaker. When sleep, nutrition, and training coaches all want attention, Nakamura decides which one gets it this week based on goals, current trajectory, and risk."
  }
}
```

### Technical Implementation

**Step 1: Update `board_of_directors.json` in S3** with the integrator persona above.

**Step 2: Modify the observatory generation pipeline** (`ai_expert_analyzer_lambda.py`):

After all domain coaches have generated their content, add a second-pass call:

```python
def generate_integration(all_coach_outputs, goals_config, data_inventory):
    """
    Second pass: read all coach outputs and produce synthesis.
    
    Args:
        all_coach_outputs: dict of {domain: coach_narrative_text}
        goals_config: from s3://matthew-life-platform/config/user_goals.json
        data_inventory: from build_data_inventory() — what data exists
    
    Returns:
        {
            "weekly_priority": "Single paragraph, one action",
            "cross_domain_notes": {
                "glucose": "1-2 sentence context note for glucose page",
                "nutrition": "...",
                "training": "...",
                "physical": "...",
                "sleep": "...",
                "mind": "..."
            }
        }
    """
```

The prompt for this call:
```
You are Dr. Kai Nakamura, Integrative Health Director. You've just read assessments 
from all domain coaches. Your job: synthesize, resolve contradictions, and make ONE call.

Matthew's goals: {goals_json}

Coach assessments:
- Sleep: {sleep_narrative}
- Nutrition: {nutrition_narrative}
- Training: {training_narrative}
- Glucose: {glucose_narrative}
- Physical/Body Comp: {physical_narrative}
- Mind/Behavioral: {mind_narrative}

Produce:
1. THIS WEEK'S PRIORITY: One paragraph. One action. What matters most right now given 
   where Matthew is vs where he's trying to go? If coaches disagree, make the call and 
   say why. Do not hedge.

2. CROSS-DOMAIN NOTES: For each observatory page, write 1-2 sentences connecting that 
   domain to the others. Example for Nutrition: "Your glucose stability is strong, which 
   gives room to experiment with meal timing. The priority this week is [X], so nutrition 
   serves a supporting role."

Write in first person. You are Nakamura. Be decisive.
```

**Step 3: Surface the synthesis on the site:**
- Home page / Pulse: Add "This Week's Priority" card from the integrator, above the individual domain cards
- Each observatory page: Add a "Cross-Domain Context" callout at the top of the coach narrative section, sourced from `cross_domain_notes[domain]`

**Step 4: Add to Weekly Digest and Daily Brief:**
- Weekly Digest: New section at the top — "THE PRIORITY THIS WEEK" by Dr. Nakamura, followed by individual coaches
- Daily Brief: The unified_panel already partially does this; add Nakamura's voice as the panel chair

---

## Workstream 2: Cold-Start Orientation Mode

### Problem
With 7 days of data, coaches try to sound authoritative and fail. They hedge ("cannot yet explain"), guess at missing data, and produce actions that are premature. This IS the new-user experience and it's bad.

### Design

**Three-phase voice system based on data maturity.**

Each coach has a minimum data threshold. Below it, they use an "orientation" voice. Above it but under 30 days, they use an "emerging" voice. After 30 days, full analytical voice.

**Phase definitions per coach:**

| Coach | Orientation (<N days) | Emerging (N–30 days) | Established (>30 days) |
|-------|----------------------|---------------------|----------------------|
| Dr. Lisa Park (Sleep) | <7 nights | 7–30 nights | >30 nights |
| Dr. Marcus Webb (Nutrition) | <7 days logged | 7–30 days | >30 days |
| Dr. Sarah Chen (Training) | <1 workout logged | 1–14 workouts | >14 workouts |
| Dr. Amara Patel (Glucose) | <7 days CGM | 7–30 days | >30 days |
| Dr. Victor Reyes (Physical) | <1 DEXA or weight series <7d | 1 DEXA + 7d weight | DEXA + >30d weight |
| Coach Maya Rodriguez (Mind) | <3 journal entries | 3–14 entries | >14 entries |
| Dr. James Okafor (Longevity) | <14 days any data | 14–60 days | >60 days |

**Voice templates per phase:**

**Orientation:**
```
You are in ORIENTATION mode. You have {days} days of data. Your minimum for meaningful 
analysis is {threshold} days.

Voice rules:
- Open with: "I'm [name], and I'll be watching your [domain] data. Here's what I track 
  and what I'm looking for."
- List 2-3 specific things you're watching for as data accumulates
- Name exactly what data you have and what's missing
- Do NOT make analytical claims, trend statements, or recommendations
- End with: "I'll have more to say around [date when threshold is met]."
- Tone: professional introduction, not apology for lack of data
```

**Emerging:**
```
You are in EMERGING mode. You have {days} days of data. Patterns are starting to form 
but confidence is low.

Voice rules:
- You may note preliminary patterns with explicit confidence caveats
- Use language: "An early signal suggests...", "I'm watching whether..."
- Do NOT use definitive language like "your pattern is" or "this shows"
- Actions should be data-gathering, not behavior-changing: "Keep logging X so I can 
  confirm whether Y"
- Tone: curious investigator, not confident advisor
```

**Established:**
```
You are in ESTABLISHED mode with {days} days of data. Full analytical voice.
```

### Technical Implementation

**Step 1: Create a `build_data_maturity()` function** in `ai_expert_analyzer_lambda.py`:

```python
def build_data_maturity(data: dict) -> dict:
    """
    Calculate data maturity per domain.
    
    Returns: {
        "sleep": {"days": 12, "phase": "emerging", "threshold": 7, "established_at": 30},
        "nutrition": {"days": 8, "phase": "emerging", ...},
        "training": {"workouts": 0, "phase": "orientation", ...},
        ...
    }
    """
```

This queries DynamoDB for:
- Whoop sleep records count in last 90 days
- MacroFactor logged days count
- Strava/Hevy workout count
- CGM readings day count
- DEXA records count + Withings weight series length
- Journal entries count
- Overall platform data start date

**Step 2: Inject data maturity into every coach prompt** as a preamble block:

```
DATA MATURITY STATUS:
Phase: {phase} ({days} days of data, threshold: {threshold})
{phase_voice_template}

Available data sources: {list of sources with record counts}
Missing or insufficient: {list of gaps}
```

**Step 3: The `EXPERT_PERSONAS` dict** in the Lambda currently has no phase awareness. Add a `thresholds` key:

```python
EXPERT_PERSONAS = {
    "glucose": {
        "name": "Dr. Amara Patel",
        ...
        "thresholds": {"orientation": 7, "established": 30, "unit": "cgm_days"}
    },
    ...
}
```

**Step 4: When generating coach narrative,** select the voice template based on phase and prepend it to the prompt.

---

## Workstream 3: Action Completion Loop

### Problem
Every coach gives a "This Week's Action." Nobody tracks whether Matthew did it. No coach ever says "last week I asked you to X — did you?" The actions are fire-and-forget. This is the gap between a dashboard and a coach.

### Design

**DynamoDB partition for action tracking: `SOURCE#coach_actions`**

```
PK: USER#matthew
SK: SOURCE#coach_actions#{action_id}

Fields:
- action_id: string (ULID or date-based: "2026-W15-glucose")
- coach_id: string (e.g., "amara_patel", "marcus_webb", "integrator")
- domain: string (glucose, nutrition, training, physical, sleep, mind, integrated)
- issued_date: string (YYYY-MM-DD)
- issued_week: string (YYYY-WNN)
- action_text: string
- status: string (open | completed | expired | superseded)
- completion_date: string (nullable)
- completion_method: string (auto_detected | manual | expired)
- follow_up_note: string (nullable — what the coach says next cycle about this action)
- superseded_by: string (nullable — action_id of replacement)
```

**Lifecycle:**

1. **Issue:** When observatory/digest generates a coach narrative with an action, write to `SOURCE#coach_actions` with status `open`
2. **Auto-detect:** A nightly check Lambda looks for completion signals:
   - "Obtain DEXA" → query DEXA partition for records after issued_date
   - "Start training" → query Strava/Hevy for workouts after issued_date
   - "Log meal timing" → query MacroFactor for timestamped entries
   - "Journal about X" → query journal entries for keyword match
   - Detection rules stored in a config, not hardcoded per action
3. **Manual complete:** New MCP tool `complete_action` for Matthew to mark done
4. **Expire:** Actions older than 14 days with status `open` → `expired`
5. **Supersede:** When a coach issues a new action for the same domain, previous open action → `superseded`

**Coach prompt injection:**

When generating the next cycle's coach narrative, inject action history:

```
YOUR PREVIOUS ACTIONS:
- [2026-W14] "Obtain a DEXA scan or reliable body composition estimate" — STATUS: COMPLETED 
  (DEXA data appeared 2026-04-03)
- [2026-W15] "Increase fiber intake to 25g/day" — STATUS: OPEN (7 days, no change detected)

Rules:
- If an action was COMPLETED: acknowledge it briefly, reference the outcome if data is 
  available, then move on
- If an action is OPEN and still relevant: reference it. Either repeat with more urgency, 
  adjust the approach, or acknowledge that circumstances changed
- If an action EXPIRED without completion: note it honestly. "Last week I suggested X. 
  That didn't happen. Here's whether it still matters."
- Your new action this week should either build on a completed action, replace an 
  expired/superseded one, or be genuinely new
- Do NOT issue the same action two weeks in a row with identical wording — if it didn't 
  land the first time, reframe it
```

### Technical Implementation

**Step 1: Create the DDB partition schema** — add write logic to the observatory generation pipeline. When a coach narrative is generated, parse out the "This Week's Action" text and write it.

**Step 2: Create action detection config** in S3 (`config/action_detection_rules.json`):
```json
{
  "rules": [
    {
      "pattern": "DEXA|body composition scan",
      "detection": "query_partition",
      "partition": "SOURCE#dexa",
      "condition": "record_exists_after_issued_date"
    },
    {
      "pattern": "training|workout|gym|exercise",
      "detection": "query_partition", 
      "partition": "SOURCE#strava",
      "condition": "record_exists_after_issued_date"
    },
    {
      "pattern": "fiber|fibre",
      "detection": "query_metric",
      "source": "macrofactor",
      "metric": "fiber_g",
      "condition": "average_above_threshold",
      "threshold": 20
    },
    {
      "pattern": "journal|reflect|write about",
      "detection": "query_partition",
      "partition": "SOURCE#journal",
      "condition": "record_exists_after_issued_date"
    }
  ]
}
```

**Step 3: Create nightly action checker** — either a standalone Lambda or add to the existing nightly warmer. Runs detection rules against open actions, updates statuses.

**Step 4: New MCP tools:**
- `list_actions` — show all actions with optional status/domain filter
- `complete_action` — manually mark an action done with optional note
- `get_action_history` — show action lifecycle for a domain over time

**Step 5: Site widget — "Open Actions"** on the home page Pulse section:
- Show current week's actions across all coaches
- Visual indicator: open (amber dot), completed (green check), expired (grey strikethrough)
- Integrator's priority action highlighted at top

---

## Workstream 4: Intelligence Quality Validator

### Problem
Coaches claimed body composition data was null when DEXA data existed. Coaches asked Matthew to provide training structure when no training is the correct interpretation. These bugs were live for days and only caught by manual review on a phone. There is no automated quality check.

### Design

**Post-generation validation Lambda** (`life-platform-intelligence-validator`) that runs after every observatory or digest generation, before the result is cached/published.

### Validation Checks

**Check 1: Null Claim vs. Actual Data**
- Scan generated text for phrases indicating missing data: "unavailable", "null", "no data", "not yet available", "remains unknown", "data gap", "cannot determine"
- For each match, identify the domain (body composition, meal timing, training, etc.)
- Query the corresponding DDB partition for actual records
- If records exist within 90 days: flag `CONTRADICTION` (severity: error)

**Check 2: Stale Action — Asking for Data That Exists**
- Scan the "This Week's Action" text for requests to obtain/provide data
- Match against data inventory
- If the requested data already exists: flag `STALE_ACTION` (severity: error)

**Check 3: Source-of-Truth Violation**
- Scan for specific metric values (step counts, weight, etc.)
- If the value matches a non-SOT source when an SOT source exists: flag `SOT_VIOLATION` (severity: warning)
- Example: text says "5,112 steps" matching Apple Health when Garmin (SOT) shows 9,248

**Check 4: Cross-Coach Contradiction**
- Compare metric references across coach outputs for the same generation cycle
- If two coaches cite different values for the same metric: flag `INCONSISTENCY` (severity: warning)

**Check 5: Confidence Without Data**
- If a coach is in orientation phase (<threshold days) but uses definitive language ("your pattern shows", "this demonstrates"): flag `OVERCONFIDENT` (severity: warning)

### Technical Implementation

**Step 1: Create `build_data_inventory()` function:**

```python
def build_data_inventory() -> dict:
    """
    Query DDB for existence and recency of all major data partitions.
    
    Returns: {
        "dexa": {"exists": True, "latest": "2026-03-15", "records": 2},
        "macrofactor": {"exists": True, "latest": "2026-04-06", "records": 45},
        "strava": {"exists": True, "latest": "2026-04-01", "records": 12},
        "cgm": {"exists": True, "latest": "2026-04-06", "records": 28},
        "whoop": {"exists": True, "latest": "2026-04-07", "records": 60},
        "garmin": {"exists": True, "latest": "2026-04-07", "records": 1400},
        "journal": {"exists": True, "latest": "2026-04-05", "records": 8},
        "withings": {"exists": True, "latest": "2026-04-07", "records": 200},
        "eightsleep": {"exists": True, "latest": "2026-04-07", "records": 30},
        ...
    }
    """
```

This is also used by Workstream 2 (cold-start) and the integrator prompt.

**Step 2: Create validation function:**

```python
def validate_coach_output(coach_id: str, narrative: str, data_inventory: dict, 
                          data_maturity: dict, all_narratives: dict = None) -> list:
    """
    Run all validation checks against a coach narrative.
    
    Returns: list of {
        "check": "null_claim_vs_data",
        "severity": "error",
        "detail": "Coach claims body composition unavailable but DEXA partition has 2 records, latest 2026-03-15",
        "source_text": "body composition breakdown remains unavailable"
    }
    """
```

**Step 3: Integration into generation pipeline:**

Two modes:

**Mode A — Post-generation alert (implement first):**
After all coaches generate, run validator. Write results to `SOURCE#intelligence_quality` partition. If any errors: include a "Quality Alert" in the Daily Brief.

**Mode B — Inline correction (stretch goal):**
If validator finds errors, re-prompt the coach with corrections injected:
```
CORRECTION: Your previous draft claimed body composition data is unavailable. 
Actual status: DEXA scan from 2026-03-15 exists with body fat 38.2%, lean mass 
184 lbs, visceral fat rating 12. Rewrite your analysis incorporating this data.
```

This makes the intelligence self-correcting. More expensive (double API call on errors) but eliminates the class of bugs Matthew found today.

**Step 4: New MCP tool:**
- `get_intelligence_quality` — show recent validation results, filterable by severity/coach/check_type

**Step 5: DDB partition schema:**
```
PK: USER#matthew
SK: SOURCE#intelligence_quality#{date}#{coach_id}

Fields:
- date: string
- coach_id: string
- checks_run: int
- errors: int
- warnings: int
- flags: list of {check, severity, detail, source_text}
- generation_id: string (links to the cached narrative)
```

---

## Workstream 5: Goals Architecture

### Problem
The platform tracks everything but hasn't formally defined what Matthew is trying to achieve. Coaches navigate without coordinates. The trajectory tools can't calculate "on track" vs "behind" without targets. "Body composition experiment" is a theme, not a plan.

### Design

**Create `config/user_goals.json` in S3** — the canonical goals definition.

**Schema:**
```json
{
  "version": "1.0",
  "mission": "12-month body recomposition for longevity",
  "start_date": "2026-04-01",
  "end_date": "2027-03-31",
  "start_weight_lbs": 307,
  
  "targets": {
    "weight": {
      "goal_lbs": null,
      "interim_milestones": []
    },
    "body_composition": {
      "goal_body_fat_pct": null,
      "goal_lean_mass_lbs": null
    },
    "training": {
      "weekly_sessions_target": null,
      "zone2_minutes_per_week": null,
      "strength_sessions_per_week": null
    },
    "nutrition": {
      "daily_calories_target": null,
      "daily_protein_min_g": null,
      "daily_fiber_min_g": null
    },
    "biomarkers": {
      "resting_hr_target_bpm": null,
      "hrv_target_ms": null
    },
    "behavioral": {
      "journal_entries_per_week": null,
      "habit_adherence_pct": null
    }
  },
  
  "philosophy": "Training for longevity, not aesthetics. Peter Attia centenarian framework. Progressive, sustainable deficit — no crash dieting.",
  
  "known_constraints": [
    "History of sedentary lifestyle",
    "Starting from high body weight — joint protection matters", 
    "Building the platform simultaneously — time management tension"
  ],
  
  "coach_briefing": "Matthew is 7 days into a 12-month body recomposition experiment. He started at 307 lbs. He has not yet begun structured training. His current caloric intake is ~1,581 kcal/day with ~166g protein. He has a DEXA scan from March 2026. His primary motivation is longevity and health-span, not aesthetics. He is building this platform simultaneously as both a personal tool and a proof-of-concept for enterprise AI adoption at his company. This dual purpose means he sometimes prioritizes platform development over health behaviors."
}
```

**Note: All `null` target values are intentional.** Matthew will fill these in after the architecture is built. The system must handle nulls gracefully — if a target is null, coaches should say "no target set for X yet" rather than hallucinating one.

### Technical Implementation

**Step 1: Create the goals config file** with the schema above (nulls for targets). Upload to S3.

**Step 2: Create a loader function** used by all generation Lambdas:

```python
def load_goals_config() -> dict:
    """Load user goals from S3. Cache in memory for Lambda warm instances."""
    # Read from s3://matthew-life-platform/config/user_goals.json
    # Return parsed JSON
    # If file doesn't exist, return a default with all nulls and a note
```

**Step 3: Inject goals into EVERY coach prompt** as a preamble section:

```
MATTHEW'S GOALS AND CONTEXT:
{coach_briefing}

Defined targets:
- Weight: {goal_lbs or "not yet set"}
- Body fat: {goal_body_fat_pct or "not yet set"}
- Training: {weekly_sessions_target or "not yet set"} sessions/week
- Calories: {daily_calories_target or "not yet set"} kcal/day
- Protein: {daily_protein_min_g or "not yet set"}g minimum

If a target is "not yet set", do NOT invent one. You may suggest one based on your 
domain expertise, but frame it as a suggestion: "I'd recommend setting a target of X 
based on [reasoning]."

Known constraints: {known_constraints}
```

**Step 4: Update trajectory tools** to read from goals config:
- `get_health trajectory` view should calculate projected dates to hit weight milestones
- Character sheet components that use targets should fall back to goals config values

**Step 5: New MCP tool:**
- `get_goals` — read current goals config
- `update_goals` — update specific target values (writes to S3, invalidates any cached versions)

---

## Workstream 6: Mental Health Signal — Builder's Paradox Detection

### Problem
Matthew is 7 days into a lifestyle transformation AND building a complex platform simultaneously. Nobody on any board has asked whether the building is displacing the health behaviors it's supposed to support. The Mind pillar scores data. Nobody asks the question the data can't answer.

### Design

**Expand Coach Maya Rodriguez's mandate** to include explicit "Builder's Paradox" detection.

### Technical Implementation

**Step 1: Update `board_of_directors.json` — Maya's config:**

Add to her `focus_areas`:
```json
"builder_paradox_detection — ratio of platform/engineering activity vs health behavior execution"
```

Add to her `principles`:
```json
"If you're spending more time measuring your health than improving it, that's not optimization — it's avoidance."
```

Update her `relationship_to_matthew`:
```
"Matthew tracks obsessively but struggles with consistency. He is also the sole developer 
of the platform tracking his health — creating a unique risk that building the measurement 
system becomes a substitute for the behaviors it measures. Maya watches for this pattern 
specifically: heavy Todoist/engineering output paired with flat movement, missed journals, 
or declining habit adherence."
```

**Step 2: Create a "Builder's Paradox Score" in the warmer:**

A simple weekly metric computed from existing data:

```python
def compute_builders_paradox_score(week: str) -> dict:
    """
    Ratio of platform activity to health activity.
    
    Platform signals (from Todoist):
    - Tasks completed in platform/engineering projects
    - Late-night commits (from GitHub webhook or Todoist completion timestamps)
    
    Health signals:
    - Workouts logged (Strava/Hevy)
    - Journal entries written
    - Habit completion rate (Habitify)
    - Steps (Garmin)
    
    Score: 0-100 where:
    - 0-30: Healthy balance (health activity >= platform activity)
    - 30-60: Tipping (platform activity significantly exceeds health activity)  
    - 60-100: Displaced (heavy platform work, minimal health execution)
    
    Returns: {
        "score": 72,
        "label": "displaced",
        "platform_tasks": 23,
        "health_tasks": 2,
        "workouts": 0,
        "journal_entries": 1,
        "habit_adherence_pct": 45,
        "interpretation": "23 platform tasks completed, 0 workouts, 45% habit adherence. 
                          The platform is consuming the time and energy it was designed to protect."
    }
    """
```

**Step 3: Inject into Maya's prompt context:**

```
BUILDER'S PARADOX CHECK:
This week's score: {score}/100 ({label})
Platform tasks completed: {platform_tasks}
Health actions completed: {health_tasks}
Workouts: {workouts}
Habit adherence: {habit_adherence_pct}%

If score > 50: You MUST address this directly. Not as a side note — as the lead finding.
The question to ask: "Is the building serving the transformation, or replacing it?"
Be direct. Matthew respects honesty over comfort.
```

**Step 4: Add a weekly "check-in" journal prompt suggestion:**

In the journal template or Daily Brief, once per week include:
```
WEEKLY REFLECTION PROMPT (from Coach Maya):
"Is the building serving the transformation this week, or the other way around?"
```

This becomes data Maya can reference in subsequent assessments.

**Step 5: Surface on the Mind observatory page:**

Add a "Builder's Paradox" mini-card or callout on the Mind page showing the weekly score and trend. Simple visual — green/amber/red indicator with one sentence from Maya.

---

## Workstream 0 (Prerequisite): Consolidate Observatory Coach Architecture

### Problem
The observatory coaches (Amara Patel, Victor Reyes in Lambda) are disconnected from the main board config (Sarah Chen, Marcus Webb, etc. in `board_of_directors.json`). This means:
- Observatory coaches don't benefit from centralized config changes
- The observatory prompt templates are hardcoded in the Lambda, not configurable
- Some observatory coaches don't exist in the board config at all

### Implementation

**Step 1: Migrate all observatory coaches into `board_of_directors.json`.**

The observatory currently has these coaches in the Lambda's `EXPERT_PERSONAS` dict:
- `mind`: Dr. Elena Torres (psychodynamic) → reconcile with Coach Maya Rodriguez (behavioral)
- `nutrition`: Dr. Layne Webb → reconcile with Dr. Marcus Webb
- `training`: Dr. Sarah Chen → already in board config ✓
- `physical`: Dr. Victor Reyes → not in board config, ADD
- `glucose`: Dr. Amara Patel → not in board config, ADD
- `sleep`: likely Dr. Lisa Park → already in board config ✓

**Decision needed:** Some observatory coaches have different names than board coaches for the same domain (e.g., "Dr. Layne Webb" vs "Dr. Marcus Webb" for nutrition). Unify to the board config name. The observatory should use the SAME personas as the rest of the platform.

**Step 2: Modify `ai_expert_analyzer_lambda.py`** to read coach personas from `board_of_directors.json` instead of the hardcoded `EXPERT_PERSONAS` dict. Add an `observatory` feature key to each board member's config:

```json
"marcus_webb": {
    ...
    "features": {
        "weekly_digest": { ... },
        "daily_brief": { ... },
        "observatory": {
            "page": "nutrition",
            "prompt_focus": "Weekly observatory analysis of nutrition data. Adherence, 
                            macro balance, meal timing, deficit sustainability."
        }
    }
}
```

**Step 3: Add missing coaches to board config:**

```json
"amara_patel": {
    "name": "Dr. Amara Patel",
    "title": "Metabolic Health Researcher",
    "type": "fictional_advisor",
    "emoji": "🔬",
    "color": "#2dd4bf",
    "domains": ["glucose", "metabolic_health", "insulin_sensitivity", "cgm"],
    "data_sources": ["cgm", "macrofactor"],
    "voice": {
        "tone": "Precise, curious, thinks in mechanisms and pathways",
        "style": "References insulin signaling, glucose disposal, postprandial responses. 
                  Connects nutrition inputs to metabolic outputs."
    },
    "features": {
        "observatory": {
            "page": "glucose",
            "prompt_focus": "CGM data analysis, glucose variability, time-in-range, 
                            meal response patterns, insulin sensitivity signals"
        }
    },
    "active": true
},
"victor_reyes": {
    "name": "Dr. Victor Reyes",
    "title": "Longevity Physician — Body Composition Specialist",
    "type": "fictional_advisor",
    "emoji": "📊",
    "color": "#60a5fa",
    "domains": ["body_composition", "longevity", "weight_management", "dexa"],
    "data_sources": ["withings", "dexa", "macrofactor"],
    "voice": {
        "tone": "Clinically precise, optimistic but realistic, longevity-framed",
        "style": "Thinks in composition ratios, not just weight. References visceral fat, 
                  lean mass preservation, metabolic rate implications."
    },
    "features": {
        "observatory": {
            "page": "physical",
            "prompt_focus": "Body composition trajectory, weight trend, DEXA interpretation, 
                            visceral fat, lean mass preservation during deficit"
        }
    },
    "active": true
}
```

**Step 4: Update the observatory prompt builder** to load from config and add the common preamble blocks (goals, data maturity, data inventory, action history) that all other workstreams inject.

This is the foundation that makes Workstreams 1–6 work. Without it, each workstream has to independently solve the same "how do I inject context into observatory prompts" problem.

---

## Implementation Order for Claude Code

**Session 1: Foundation (Workstream 0 + 5)**
- Consolidate observatory coach architecture into board config
- Create `user_goals.json` schema (with null targets) and S3 upload
- Create `build_data_inventory()` and `build_data_maturity()` shared functions
- Create `load_goals_config()` shared loader
- Modify observatory Lambda to read from board config instead of hardcoded dict
- Inject goals + data inventory + data maturity into all coach prompts
- **Test:** Regenerate one observatory page and verify the coach narrative reflects available data correctly

**Session 2: Cold-Start + Voice (Workstream 2)**
- Implement three-phase voice system with thresholds per coach
- Add phase-specific prompt templates
- Add first-person voice directive to all coach prompts
- **Test:** Generate observatory content for a domain in orientation phase — verify voice is appropriate

**Session 3: Intelligence Validator (Workstream 4)**
- Build validation Lambda with all 5 check types
- Create DDB partition for quality results
- Wire into generation pipeline (Mode A: post-generation alert)
- Create `get_intelligence_quality` MCP tool
- **Test:** Run validator against current observatory content — should catch the bugs Matthew found

**Session 4: Coach Synthesis — The Integrator (Workstream 1)**
- Add Dr. Nakamura to board config
- Build synthesis generation function
- Wire into observatory pipeline (second pass after all coaches)
- Add "This Week's Priority" to home page and Weekly Digest
- Add "Cross-Domain Context" callout to each observatory page
- **Test:** Generate full observatory cycle and verify synthesis is coherent

**Session 5: Action Completion Loop (Workstream 3)**
- Create DDB partition for actions
- Build action write logic in generation pipeline
- Build nightly action checker with detection rules
- Create MCP tools (list_actions, complete_action, get_action_history)
- Wire action history into coach prompt context
- Build "Open Actions" home page widget
- **Test:** Generate a cycle, verify actions are written; manually complete one; verify next cycle acknowledges it

**Session 6: Mental Health Signal (Workstream 6)**
- Update Maya Rodriguez config in board config
- Build Builder's Paradox score computation
- Wire into Maya's prompt context
- Add journal check-in prompt
- Add Builder's Paradox card to Mind observatory page
- **Test:** Compute score for current week, verify Maya's narrative addresses it

---

## Key Rules for All Sessions

- Start each session by reading `handovers/HANDOVER_LATEST.md`
- Run `python3 -m pytest tests/test_mcp_registry.py -v` before any MCP deploy
- Use `deploy/deploy_lambda.sh` for all Lambda deploys except MCP Lambda
- MCP Lambda: `zip -j $ZIP mcp_server.py mcp_bridge.py && zip -r $ZIP mcp/`
- Never use `aws s3 sync --delete` against bucket root or `site/` prefix
- Wait 10s between sequential Lambda deploys
- CloudFront invalidation after site changes: `aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/*"`
- Update CHANGELOG.md, write handover, git commit+push at end of each session
- Ground truth for tool counts: `mcp/registry.py`. Ground truth for Lambda counts: `ci/lambda_map.json`
- All new Lambdas need entries in `ci/lambda_map.json`
- Deploy scripts go in `deploy/`

## Shared Utilities Created in Session 1 (Used by All Subsequent Sessions)

These functions should be created in a shared module (e.g., `lambdas/intelligence_common.py` or within the Lambda layer) so all generation Lambdas can import them:

1. `build_data_inventory()` → dict of all data partitions with existence/recency
2. `build_data_maturity(data_inventory)` → per-domain phase calculation
3. `load_goals_config()` → parsed goals JSON from S3
4. `build_coach_preamble(coach_id, goals, inventory, maturity, action_history)` → the standard context block injected into every coach prompt

This ensures consistency: every coach, whether observatory, digest, or brief, gets the same foundational context.
